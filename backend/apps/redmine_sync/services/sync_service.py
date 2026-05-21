from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
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
    ANONYMOUS_REDMINE_USER_ID = 2
    TIME_ENTRIES_MODE_INCREMENTAL = "incremental"
    TIME_ENTRIES_MODE_WINDOW = "window"
    TIME_ENTRIES_MODE_FULL = "full"
    DEFAULT_CHUNK_SIZE = 5000
    DEFAULT_WINDOW_DAYS = 365

    def __init__(self, reader: RedmineReader | None = None) -> None:
        self.reader = reader or RedmineReader()

    def run(
        self,
        trigger_source: str = "manual",
        *,
        time_entries_mode: str = TIME_ENTRIES_MODE_INCREMENTAL,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        window_days: int = DEFAULT_WINDOW_DAYS,
    ) -> dict[str, dict[str, int]]:
        log = SyncLog.objects.create(
            trigger_source=trigger_source,
            status="running",
            details="",
        )
        details: dict[str, dict[str, int]] = {}

        try:
            details["employees"] = self.sync_employees().as_dict()
            details["projects"] = self.sync_projects().as_dict()
            self.ensure_technical_employees()
            details["time_entries"] = self.sync_time_entries(
                mode=time_entries_mode,
                chunk_size=chunk_size,
                window_days=window_days,
            ).as_dict()
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

    def sync_employees(self) -> SyncStats:
        stats = SyncStats()
        payload = self.reader.fetch_employees()

        redmine_ids = [item["redmine_id"] for item in payload]
        existing_by_redmine_id = Employee.objects.in_bulk(redmine_ids, field_name="redmine_id")

        employees_to_create: list[Employee] = []
        employees_to_update: list[Employee] = []

        for item in payload:
            defaults = {
                "first_name": item["first_name"] or "",
                "last_name": item["last_name"] or "",
                "patronymic": item.get("patronymic") or "",
                "email": item.get("email") or "",
                "active": bool(item.get("active")),
            }
            employee = existing_by_redmine_id.get(item["redmine_id"])
            if employee is None:
                employees_to_create.append(
                    Employee(
                        redmine_id=item["redmine_id"],
                        **defaults,
                    )
                )
                continue

            if self._apply_changes(employee, defaults):
                employees_to_update.append(employee)

        with transaction.atomic():
            if employees_to_create:
                Employee.objects.bulk_create(employees_to_create, batch_size=500)
            if employees_to_update:
                Employee.objects.bulk_update(
                    employees_to_update,
                    ["first_name", "last_name", "patronymic", "email", "active"],
                    batch_size=500,
                )

        stats.created = len(employees_to_create)
        stats.updated = len(employees_to_update)
        self._mark_state("employees", "success", stats)
        return stats

    def sync_projects(self) -> SyncStats:
        stats = SyncStats()
        payload = self.reader.fetch_projects()
        now = timezone.now()

        redmine_project_ids = [item["redmine_project_id"] for item in payload]
        existing_by_redmine_id = Project.objects.in_bulk(
            redmine_project_ids,
            field_name="redmine_project_id",
        )

        projects_to_create: list[Project] = []
        projects_to_update: list[Project] = []
        relation_links: list[tuple[int, int | None, int | None]] = []

        for item in payload:
            defaults = {
                "name": item["name"] or "",
                "project_number": item.get("project_number") or "",
                "name_1s": item.get("name_1s") or "",
                "name_sanda": item.get("name_sanda") or "",
                "lead_department": item.get("lead_department") or "",
            }
            redmine_project_id = item["redmine_project_id"]
            relation_links.append(
                (
                    redmine_project_id,
                    self._safe_int(item.get("parent_redmine_project_id")),
                    self._safe_int(item.get("redmine_project_manager_id")),
                )
            )

            project = existing_by_redmine_id.get(redmine_project_id)
            if project is None:
                projects_to_create.append(
                    Project(
                        redmine_project_id=redmine_project_id,
                        created_at=now,
                        updated_at=now,
                        **defaults,
                    )
                )
                continue

            if self._apply_changes(project, defaults):
                project.updated_at = now
                projects_to_update.append(project)

        with transaction.atomic():
            if projects_to_create:
                Project.objects.bulk_create(projects_to_create, batch_size=500)
            if projects_to_update:
                Project.objects.bulk_update(
                    projects_to_update,
                    ["name", "project_number", "name_1s", "name_sanda", "lead_department", "updated_at"],
                    batch_size=500,
                )

        project_map = Project.objects.in_bulk(redmine_project_ids, field_name="redmine_project_id")
        employee_ids = {
            manager_redmine_id
            for _, _, manager_redmine_id in relation_links
            if manager_redmine_id is not None
        }
        employee_map = Employee.objects.in_bulk(employee_ids, field_name="redmine_id") if employee_ids else {}

        relation_updates: list[Project] = []
        for redmine_project_id, parent_redmine_id, manager_redmine_id in relation_links:
            project = project_map.get(redmine_project_id)
            if project is None:
                stats.skipped += 1
                continue

            parent_project = project_map.get(parent_redmine_id) if parent_redmine_id else None
            project_manager = employee_map.get(manager_redmine_id) if manager_redmine_id else None

            changed = False
            parent_project_id = parent_project.id if parent_project else None
            project_manager_id = project_manager.id if project_manager else None

            if project.parent_project_id != parent_project_id:
                project.parent_project = parent_project
                changed = True
            if project.project_manager_id != project_manager_id:
                project.project_manager = project_manager
                changed = True

            if changed:
                project.updated_at = now
                relation_updates.append(project)

        with transaction.atomic():
            if relation_updates:
                Project.objects.bulk_update(
                    relation_updates,
                    ["parent_project", "project_manager", "updated_at"],
                    batch_size=500,
                )

        updated_project_ids = {
            project.redmine_project_id
            for project in [*projects_to_update, *relation_updates]
        }

        stats.created = len(projects_to_create)
        stats.updated = len(updated_project_ids)
        self._mark_state("projects", "success", stats)
        return stats

    def sync_time_entries(
        self,
        *,
        mode: str = TIME_ENTRIES_MODE_INCREMENTAL,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        window_days: int = DEFAULT_WINDOW_DAYS,
    ) -> SyncStats:
        if mode not in {
            self.TIME_ENTRIES_MODE_INCREMENTAL,
            self.TIME_ENTRIES_MODE_WINDOW,
            self.TIME_ENTRIES_MODE_FULL,
        }:
            raise ValueError(f"Unsupported time entries sync mode: {mode}")

        stats = SyncStats()
        state_code = self._time_entries_state_code(mode)
        after_id = self._get_time_entries_cursor(state_code) if mode == self.TIME_ENTRIES_MODE_INCREMENTAL else None
        changed_since = (
            timezone.now() - timedelta(days=window_days)
            if mode == self.TIME_ENTRIES_MODE_WINDOW
            else None
        )

        while True:
            payload = self.reader.fetch_time_entries_chunk(
                after_id=after_id,
                changed_since=changed_since,
                limit=chunk_size,
            )
            if not payload:
                break

            chunk_stats = self._sync_time_entries_chunk(payload)
            stats.created += chunk_stats.created
            stats.updated += chunk_stats.updated
            stats.skipped += chunk_stats.skipped

            after_id = payload[-1]["redmine_time_entry_id"]
            self._mark_state(
                state_code,
                "running",
                stats,
                cursor_int=after_id if mode == self.TIME_ENTRIES_MODE_INCREMENTAL else None,
            )

        self._mark_state(
            state_code,
            "success",
            stats,
            cursor_int=after_id if mode == self.TIME_ENTRIES_MODE_INCREMENTAL else None,
        )
        return stats

    def _sync_time_entries_chunk(self, payload: list[dict[str, object]]) -> SyncStats:
        stats = SyncStats()

        redmine_time_entry_ids = [item["redmine_time_entry_id"] for item in payload]
        project_ids = {
            item["redmine_project_id"]
            for item in payload
            if item.get("redmine_project_id") is not None
        }
        employee_ids = {
            item["redmine_user_id"]
            for item in payload
            if item.get("redmine_user_id") is not None
        }

        existing_by_redmine_id = RedmineTimeEntry.objects.in_bulk(
            redmine_time_entry_ids,
            field_name="redmine_time_entry_id",
        )
        project_map = Project.objects.in_bulk(project_ids, field_name="redmine_project_id") if project_ids else {}
        employee_map = Employee.objects.in_bulk(employee_ids, field_name="redmine_id") if employee_ids else {}

        time_entries_to_create: list[RedmineTimeEntry] = []
        time_entries_to_update: list[RedmineTimeEntry] = []

        for item in payload:
            project = project_map.get(item["redmine_project_id"])
            employee = employee_map.get(item["redmine_user_id"])

            if not project or not employee:
                stats.skipped += 1
                continue

            issue_id = item.get("issue_id")
            hours = Decimal(str(item["hours"] or 0))
            activity_id = item.get("activity_id")
            spent_on = item["spent_on"]
            created_at = self._normalize_datetime(item.get("created_at"))

            time_entry = existing_by_redmine_id.get(item["redmine_time_entry_id"])
            if time_entry is None:
                time_entries_to_create.append(
                    RedmineTimeEntry(
                        redmine_time_entry_id=item["redmine_time_entry_id"],
                        project_id=project.id,
                        user_id=employee.id,
                        issue_id=issue_id,
                        hours=hours,
                        activity_id=activity_id,
                        spent_on=spent_on,
                        created_at=created_at,
                    )
                )
                continue

            changed = False
            if time_entry.project_id != project.id:
                time_entry.project_id = project.id
                changed = True
            if time_entry.user_id != employee.id:
                time_entry.user_id = employee.id
                changed = True
            if time_entry.issue_id != issue_id:
                time_entry.issue_id = issue_id
                changed = True
            if time_entry.hours != hours:
                time_entry.hours = hours
                changed = True
            if time_entry.activity_id != activity_id:
                time_entry.activity_id = activity_id
                changed = True
            if time_entry.spent_on != spent_on:
                time_entry.spent_on = spent_on
                changed = True
            if time_entry.created_at != created_at:
                time_entry.created_at = created_at
                changed = True

            if changed:
                time_entries_to_update.append(time_entry)

        with transaction.atomic():
            if time_entries_to_create:
                RedmineTimeEntry.objects.bulk_create(time_entries_to_create, batch_size=1000)
            if time_entries_to_update:
                RedmineTimeEntry.objects.bulk_update(
                    time_entries_to_update,
                    ["project_id", "user_id", "issue_id", "hours", "activity_id", "spent_on", "created_at"],
                    batch_size=1000,
                )

        stats.created = len(time_entries_to_create)
        stats.updated = len(time_entries_to_update)
        return stats

    def ensure_technical_employees(self) -> None:
        Employee.objects.update_or_create(
            redmine_id=self.ANONYMOUS_REDMINE_USER_ID,
            defaults={
                "first_name": "Анонимный",
                "last_name": "пользователь",
                "patronymic": "",
                "email": "",
                "active": False,
            },
        )

    def _time_entries_state_code(self, mode: str) -> str:
        return f"time_entries_{mode}"

    def _get_time_entries_cursor(self, entity_code: str) -> int | None:
        state = SyncState.objects.filter(entity_code=entity_code).only("cursor_int").first()
        return state.cursor_int if state else None

    def _mark_state(
        self,
        entity_code: str,
        status: str,
        stats: SyncStats,
        *,
        cursor_int: int | None = None,
    ) -> None:
        now = timezone.now()
        defaults = {
            "last_synced_at": now,
            "last_success_at": now if status == "success" else None,
            "status": status,
            "message": self._format_details(stats.as_dict()),
        }
        if cursor_int is not None:
            defaults["cursor_int"] = cursor_int

        SyncState.objects.update_or_create(
            entity_code=entity_code,
            defaults=defaults,
        )

    def _apply_changes(self, instance: object, values: dict[str, object]) -> bool:
        changed = False
        for field_name, new_value in values.items():
            if getattr(instance, field_name) != new_value:
                setattr(instance, field_name, new_value)
                changed = True
        return changed

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
