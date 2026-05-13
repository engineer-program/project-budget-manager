from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.employees.models import Employee
from apps.projects.models import Project
from apps.redmine_sync.models import RedmineTimeEntry, SyncLog, SyncState

from .redmine_reader import RedmineReader


@dataclass
class SyncStats:
    created: int = 0
    updated: int = 0
    skipped: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
        }


class SyncService:
    def __init__(self, reader: RedmineReader | None = None) -> None:
        self.reader = reader or RedmineReader()

    def run(self, trigger_source: str = "manual") -> dict[str, dict[str, int]]:
        log = SyncLog.objects.create(
            trigger_source=trigger_source,
            status="running",
            details="",
        )
        details: dict[str, dict[str, int]] = {}

        try:
            details["employees"] = self.sync_employees().as_dict()
            details["projects"] = self.sync_projects().as_dict()
            details["time_entries"] = self.sync_time_entries().as_dict()
            log.status = "success"
            log.details = self._format_details(details)
            log.finished_at = timezone.now()
            log.save(update_fields=["status", "details", "finished_at"])
            return details
        except Exception as exc:
            log.status = "failed"
            log.details = str(exc)
            log.finished_at = timezone.now()
            log.save(update_fields=["status", "details", "finished_at"])
            raise

    @transaction.atomic
    def sync_employees(self) -> SyncStats:
        stats = SyncStats()
        payload = self.reader.fetch_employees()

        for item in payload:
            defaults = {
                "first_name": item["first_name"] or "",
                "last_name": item["last_name"] or "",
                "patronymic": item.get("patronymic") or "",
                "email": item.get("email") or "",
                "active": bool(item.get("active")),
            }
            _, created = Employee.objects.update_or_create(
                redmine_id=item["redmine_id"],
                defaults=defaults,
            )
            if created:
                stats.created += 1
            else:
                stats.updated += 1

        self._mark_state("employees", "success", stats)
        return stats

    @transaction.atomic
    def sync_projects(self) -> SyncStats:
        stats = SyncStats()
        payload = self.reader.fetch_projects()
        relation_links: list[tuple[Project, int | None, int | None]] = []

        for item in payload:
            defaults = {
                "name": item["name"] or "",
                "project_number": item.get("project_number") or "",
                "name_1s": item.get("name_1s") or "",
                "name_sanda": item.get("name_sanda") or "",
                "lead_department": item.get("lead_department") or "",
            }

            project, created = Project.objects.update_or_create(
                redmine_project_id=item["redmine_project_id"],
                defaults=defaults,
            )
            relation_links.append(
                (
                    project,
                    item.get("parent_redmine_project_id"),
                    self._safe_int(item.get("redmine_project_manager_id")),
                )
            )
            if created:
                stats.created += 1
            else:
                stats.updated += 1

        for project, parent_redmine_id, manager_redmine_id in relation_links:
            parent_project = None
            if parent_redmine_id:
                parent_project = Project.objects.filter(
                    redmine_project_id=parent_redmine_id
                ).first()

            project_manager = None
            if manager_redmine_id:
                project_manager = Employee.objects.filter(
                    redmine_id=manager_redmine_id
                ).first()

            update_fields: list[str] = []
            if project.parent_project_id != (parent_project.id if parent_project else None):
                project.parent_project = parent_project
                update_fields.append("parent_project")
            if project.project_manager_id != (project_manager.id if project_manager else None):
                project.project_manager = project_manager
                update_fields.append("project_manager")
            if update_fields:
                update_fields.append("updated_at")
                project.save(update_fields=update_fields)

        self._mark_state("projects", "success", stats)
        return stats

    @transaction.atomic
    def sync_time_entries(self) -> SyncStats:
        stats = SyncStats()
        payload = self.reader.fetch_time_entries()

        for item in payload:
            project = Project.objects.filter(
                redmine_project_id=item["redmine_project_id"]
            ).first()
            employee = Employee.objects.filter(
                redmine_id=item["redmine_user_id"]
            ).first()

            if not project or not employee:
                stats.skipped += 1
                continue

            defaults = {
                "project": project,
                "user": employee,
                "issue_id": item.get("issue_id"),
                "hours": Decimal(str(item["hours"] or 0)),
                "activity_id": item.get("activity_id"),
                "spent_on": item["spent_on"],
                "created_at": self._normalize_datetime(item.get("created_at")),
            }
            _, created = RedmineTimeEntry.objects.update_or_create(
                redmine_time_entry_id=item["redmine_time_entry_id"],
                defaults=defaults,
            )
            if created:
                stats.created += 1
            else:
                stats.updated += 1

        self._mark_state("time_entries", "success", stats)
        return stats

    def _mark_state(self, entity_code: str, status: str, stats: SyncStats) -> None:
        now = timezone.now()
        SyncState.objects.update_or_create(
            entity_code=entity_code,
            defaults={
                "last_synced_at": now,
                "last_success_at": now if status == "success" else None,
                "status": status,
                "message": self._format_details(stats.as_dict()),
            },
        )

    def _format_details(self, details: dict[str, int] | dict[str, dict[str, int]]) -> str:
        return str(details)

    def _normalize_datetime(self, value: datetime | None) -> datetime:
        if value is None:
            return timezone.now()
        if timezone.is_naive(value):
            return timezone.make_aware(value, timezone.get_current_timezone())
        return value

    def _safe_int(self, value: object) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
