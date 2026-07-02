from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.employees.models import Employee, EmployeeGroupMembership, RedmineGroup
from apps.projects.models import Project
from apps.redmine_sync.models import RedmineTimeEntry, SyncLog, SyncState

from .redmine_reader import RedmineReader
from .sync_run_logger import SyncRunLogger


@dataclass
class SyncStats:
    created: int = 0
    updated: int = 0
    deleted: int = 0
    skipped: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "created": self.created,
            "updated": self.updated,
            "deleted": self.deleted,
            "skipped": self.skipped,
        }


class SyncService:
    ANONYMOUS_REDMINE_USER_ID = 2
    TIME_ENTRIES_MODE_INCREMENTAL = "incremental"
    TIME_ENTRIES_MODE_WINDOW = "window"
    TIME_ENTRIES_MODE_FULL = "full"
    DEFAULT_CHUNK_SIZE = 5000
    DEFAULT_WINDOW_DAYS = 365
    DEFAULT_INCREMENTAL_RECONCILE_DAYS = 30
    PROJECT_TIMESTAMP_PREFIX_RE = re.compile(
        r"^'?\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2}\s+(?P<name>.+)$"
    )

    def __init__(self, reader: RedmineReader | None = None) -> None:
        self.reader = reader or RedmineReader()
        self.run_logger: SyncRunLogger | None = None

    def run(
        self,
        trigger_source: str = "manual",
        *,
        time_entries_mode: str = TIME_ENTRIES_MODE_INCREMENTAL,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        window_days: int = DEFAULT_WINDOW_DAYS,
        triggered_by: str = "",
    ) -> dict[str, dict[str, int]]:
        self.run_logger = SyncRunLogger(
            mode=time_entries_mode,
            trigger_source=trigger_source,
            triggered_by=triggered_by,
            chunk_size=chunk_size,
            window_days=window_days if time_entries_mode == self.TIME_ENTRIES_MODE_WINDOW else None,
        )
        log = SyncLog.objects.create(
            trigger_source=trigger_source,
            status="running",
            details="",
        )
        details: dict[str, dict[str, int]] = {}

        try:
            details["employees"] = self.sync_employees().as_dict()
            self.run_logger.record_section_result("employees", details["employees"])
            details["groups"] = self.sync_groups().as_dict()
            self.run_logger.record_section_result("groups", details["groups"])
            details["group_memberships"] = self.sync_group_memberships().as_dict()
            self.run_logger.record_section_result("group_memberships", details["group_memberships"])
            details["projects"] = self.sync_projects().as_dict()
            self.run_logger.record_section_result("projects", details["projects"])
            self.ensure_technical_employees()
            details["time_entries"] = self.sync_time_entries(
                mode=time_entries_mode,
                chunk_size=chunk_size,
                window_days=window_days,
            ).as_dict()
            self.run_logger.record_section_result("time_entries", details["time_entries"])
            log.status = "success"
            log.details = self._format_details(details)
            log.finished_at = timezone.now()
            log.save(update_fields=["status", "details", "finished_at"])
            self.run_logger.finalize_success(details)
            return details
        except Exception as exc:
            log.status = "failed"
            log.details = str(exc)
            log.finished_at = timezone.now()
            log.save(update_fields=["status", "details", "finished_at"])
            if self.run_logger is not None:
                self.run_logger.finalize_failed(exc)
            raise
        finally:
            self.run_logger = None

    def sync_employees(self) -> SyncStats:
        stats = SyncStats()
        payload = self.reader.fetch_employees()
        now = timezone.now()

        redmine_ids = [item["redmine_id"] for item in payload]
        existing_by_redmine_id = Employee.objects.in_bulk(redmine_ids, field_name="redmine_id")

        employees_to_create: list[Employee] = []
        employees_to_update: list[Employee] = []

        for item in payload:
            defaults = {
                "first_name": item["first_name"] or "",
                "last_name": item["last_name"] or "",
                "patronymic": item.get("patronymic") or "",
                "position": item.get("position") or "",
                "employment_date": self._normalize_date(item.get("employment_date")),
                "dismissal_date": self._normalize_date(item.get("dismissal_date")),
                "email": item.get("email") or "",
                "active": bool(item.get("active")),
                "synced_at": now,
                "is_deleted_in_redmine": False,
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
                    [
                        "first_name",
                        "last_name",
                        "patronymic",
                        "position",
                        "employment_date",
                        "dismissal_date",
                        "email",
                        "active",
                        "synced_at",
                        "is_deleted_in_redmine",
                    ],
                    batch_size=500,
                )

            deleted_employees = list(
                Employee.objects.exclude(redmine_id__in=redmine_ids)
                .filter(is_deleted_in_redmine=False)
                .values(
                    "id",
                    "redmine_id",
                    "first_name",
                    "last_name",
                    "patronymic",
                    "email",
                    "active",
                )
            )
            deleted_count = Employee.objects.filter(
                id__in=[employee["id"] for employee in deleted_employees],
            ).update(
                is_deleted_in_redmine=True,
                synced_at=now,
            )

        stats.created = len(employees_to_create)
        stats.updated = len(employees_to_update)
        stats.deleted = deleted_count
        if self.run_logger is not None:
            for employee in deleted_employees:
                self.run_logger.record_employee_deleted(employee)
        self._mark_state("employees", "success", stats)
        return stats

    def sync_groups(self) -> SyncStats:
        stats = SyncStats()
        payload = self.reader.fetch_groups()
        now = timezone.now()

        redmine_group_ids = [item["redmine_group_id"] for item in payload]
        existing_by_redmine_id = RedmineGroup.objects.in_bulk(
            redmine_group_ids,
            field_name="redmine_group_id",
        )

        groups_to_create: list[RedmineGroup] = []
        groups_to_update: list[RedmineGroup] = []

        for item in payload:
            defaults = {
                "name": item.get("name") or "",
                "active": bool(item.get("active")),
                "synced_at": now,
            }
            group = existing_by_redmine_id.get(item["redmine_group_id"])
            if group is None:
                groups_to_create.append(
                    RedmineGroup(
                        redmine_group_id=item["redmine_group_id"],
                        **defaults,
                    )
                )
                continue

            if self._apply_changes(group, defaults):
                groups_to_update.append(group)

        with transaction.atomic():
            if groups_to_create:
                RedmineGroup.objects.bulk_create(groups_to_create, batch_size=500)
            if groups_to_update:
                RedmineGroup.objects.bulk_update(
                    groups_to_update,
                    ["name", "active", "synced_at"],
                    batch_size=500,
                )

        stats.created = len(groups_to_create)
        stats.updated = len(groups_to_update)
        self._mark_state("groups", "success", stats)
        return stats

    def sync_group_memberships(self) -> SyncStats:
        stats = SyncStats()
        payload = self.reader.fetch_group_memberships()

        redmine_group_ids = {item["redmine_group_id"] for item in payload}
        redmine_user_ids = {item["redmine_user_id"] for item in payload}

        group_map = (
            RedmineGroup.objects.in_bulk(redmine_group_ids, field_name="redmine_group_id")
            if redmine_group_ids
            else {}
        )
        employee_map = (
            Employee.objects.in_bulk(redmine_user_ids, field_name="redmine_id")
            if redmine_user_ids
            else {}
        )

        target_pairs: set[tuple[int, int]] = set()
        for item in payload:
            group = group_map.get(item["redmine_group_id"])
            employee = employee_map.get(item["redmine_user_id"])
            if group is None or employee is None:
                stats.skipped += 1
                continue
            target_pairs.add((employee.id, group.id))

        existing_pairs = set(
            EmployeeGroupMembership.objects.values_list("employee_id", "group_id")
        )
        pairs_to_create = target_pairs - existing_pairs
        pairs_to_delete = existing_pairs - target_pairs

        with transaction.atomic():
            if pairs_to_delete:
                delete_query = Q()
                for employee_id, group_id in pairs_to_delete:
                    delete_query |= Q(employee_id=employee_id, group_id=group_id)
                EmployeeGroupMembership.objects.filter(delete_query).delete()
            if pairs_to_create:
                EmployeeGroupMembership.objects.bulk_create(
                    [
                        EmployeeGroupMembership(employee_id=employee_id, group_id=group_id)
                        for employee_id, group_id in pairs_to_create
                    ],
                    batch_size=1000,
                    ignore_conflicts=True,
                )

        stats.created = len(pairs_to_create)
        stats.deleted = len(pairs_to_delete)
        self._mark_state("group_memberships", "success", stats)
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
                "name": self._normalize_project_name(item.get("name")),
                "status": self._safe_int(item.get("status")) or 1,
                "project_number": item.get("project_number") or "",
                "name_1s": item.get("name_1s") or "",
                "name_sanda": item.get("name_sanda") or "",
                "lead_department": item.get("lead_department") or "",
                "redmine_created_on": self._normalize_datetime(item.get("redmine_created_on")),
                "redmine_updated_on": self._normalize_datetime(item.get("redmine_updated_on")),
                "synced_at": now,
                "is_deleted_in_redmine": False,
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
                    [
                        "name",
                        "status",
                        "project_number",
                        "name_1s",
                        "name_sanda",
                        "lead_department",
                        "redmine_created_on",
                        "redmine_updated_on",
                        "synced_at",
                        "is_deleted_in_redmine",
                        "updated_at",
                    ],
                    batch_size=500,
                )

            deleted_projects = list(
                Project.objects.exclude(redmine_project_id__in=redmine_project_ids)
                .filter(is_deleted_in_redmine=False)
                .values("id", "redmine_project_id", "name", "project_number", "status")
            )
            deleted_count = Project.objects.filter(
                id__in=[project["id"] for project in deleted_projects],
            ).update(
                is_deleted_in_redmine=True,
                synced_at=now,
                updated_at=now,
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
        stats.deleted = deleted_count
        if self.run_logger is not None:
            for project in deleted_projects:
                self.run_logger.record_project_deleted(project)
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
        if mode == self.TIME_ENTRIES_MODE_FULL:
            deleted_count = self._reconcile_deleted_time_entries_full()
        elif mode == self.TIME_ENTRIES_MODE_WINDOW:
            reconcile_start = date.today() - timedelta(days=window_days)
            deleted_count = self._reconcile_deleted_time_entries_by_spent_on(start_date=reconcile_start)
        elif mode == self.TIME_ENTRIES_MODE_INCREMENTAL:
            reconcile_start = date.today() - timedelta(days=self.DEFAULT_INCREMENTAL_RECONCILE_DAYS)
            deleted_count = self._reconcile_deleted_time_entries_by_spent_on(start_date=reconcile_start)
        else:
            deleted_count = 0

        if deleted_count:
            stats.deleted += deleted_count
            self._mark_state(
                state_code,
                "success",
                stats,
                cursor_int=after_id if mode == self.TIME_ENTRIES_MODE_INCREMENTAL else None,
            )
        return stats

    def _reconcile_deleted_time_entries_full(self) -> int:
        redmine_ids = set(self.reader.fetch_time_entry_ids())
        deleted_entries = list(
            RedmineTimeEntry.objects.exclude(redmine_time_entry_id__in=redmine_ids)
            .filter(is_deleted_in_redmine=False)
            .values(
                "id",
                "redmine_time_entry_id",
                "project_id",
                "user_id",
                "issue_id",
                "hours",
                "activity_id",
                "spent_on",
            )
        )
        deleted_count = RedmineTimeEntry.objects.filter(
            id__in=[entry["id"] for entry in deleted_entries],
        ).update(is_deleted_in_redmine=True)
        if self.run_logger is not None:
            for entry in deleted_entries:
                self.run_logger.record_time_entry_deleted(entry)
        return deleted_count

    def _reconcile_deleted_time_entries_by_spent_on(
        self,
        *,
        start_date: date,
        end_date: date | None = None,
    ) -> int:
        redmine_ids = set(
            self.reader.fetch_time_entry_ids_by_spent_on(
                start_date=start_date,
                end_date=end_date,
            )
        )
        queryset = RedmineTimeEntry.objects.filter(
            spent_on__gte=start_date,
            is_deleted_in_redmine=False,
        )
        if end_date is not None:
            queryset = queryset.filter(spent_on__lte=end_date)

        deleted_entries = list(
            queryset.exclude(redmine_time_entry_id__in=redmine_ids).values(
                "id",
                "redmine_time_entry_id",
                "project_id",
                "user_id",
                "issue_id",
                "hours",
                "activity_id",
                "spent_on",
            )
        )
        deleted_count = RedmineTimeEntry.objects.filter(
            id__in=[entry["id"] for entry in deleted_entries],
        ).update(is_deleted_in_redmine=True)
        if self.run_logger is not None:
            for entry in deleted_entries:
                self.run_logger.record_time_entry_deleted(entry)
        return deleted_count

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
        project_map = (
            Project.objects.filter(is_deleted_in_redmine=False).in_bulk(project_ids, field_name="redmine_project_id")
            if project_ids
            else {}
        )
        employee_map = (
            Employee.objects.filter(is_deleted_in_redmine=False).in_bulk(employee_ids, field_name="redmine_id")
            if employee_ids
            else {}
        )

        time_entries_to_create: list[RedmineTimeEntry] = []
        time_entries_to_update: list[RedmineTimeEntry] = []

        for item in payload:
            project = project_map.get(item["redmine_project_id"])
            employee = employee_map.get(item["redmine_user_id"])

            if not project and not employee:
                stats.skipped += 1
                if self.run_logger is not None:
                    self.run_logger.record_time_entry_skipped(
                        item,
                        "проект и сотрудник не найдены или помечены удалёнными",
                    )
                continue
            if not project:
                stats.skipped += 1
                if self.run_logger is not None:
                    self.run_logger.record_time_entry_skipped(
                        item,
                        "проект не найден или помечен удалённым",
                    )
                continue
            if not employee:
                stats.skipped += 1
                if self.run_logger is not None:
                    self.run_logger.record_time_entry_skipped(
                        item,
                        "сотрудник не найден или помечен удалённым",
                    )
                continue

            issue_id = item.get("issue_id")
            hours = Decimal(str(item["hours"] or 0))
            activity_id = item.get("activity_id")
            spent_on = item["spent_on"]
            created_at = self._normalize_datetime(item.get("created_at"))
            redmine_updated_on = self._normalize_datetime(item.get("updated_at"))

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
                        redmine_updated_on=redmine_updated_on,
                        is_deleted_in_redmine=False,
                    )
                )
                continue

            changed = False
            changes: dict[str, tuple[object, object]] = {}
            if time_entry.project_id != project.id:
                changes["project_id"] = (time_entry.project_id, project.id)
                time_entry.project_id = project.id
                changed = True
            if time_entry.user_id != employee.id:
                changes["user_id"] = (time_entry.user_id, employee.id)
                time_entry.user_id = employee.id
                changed = True
            if time_entry.issue_id != issue_id:
                changes["issue_id"] = (time_entry.issue_id, issue_id)
                time_entry.issue_id = issue_id
                changed = True
            if time_entry.hours != hours:
                changes["hours"] = (time_entry.hours, hours)
                time_entry.hours = hours
                changed = True
            if time_entry.activity_id != activity_id:
                changes["activity_id"] = (time_entry.activity_id, activity_id)
                time_entry.activity_id = activity_id
                changed = True
            if time_entry.spent_on != spent_on:
                changes["spent_on"] = (time_entry.spent_on, spent_on)
                time_entry.spent_on = spent_on
                changed = True
            if time_entry.created_at != created_at:
                changes["created_at"] = (time_entry.created_at, created_at)
                time_entry.created_at = created_at
                changed = True
            if time_entry.redmine_updated_on != redmine_updated_on:
                changes["redmine_updated_on"] = (time_entry.redmine_updated_on, redmine_updated_on)
                time_entry.redmine_updated_on = redmine_updated_on
                changed = True
            if time_entry.is_deleted_in_redmine:
                changes["is_deleted_in_redmine"] = (True, False)
                time_entry.is_deleted_in_redmine = False
                changed = True

            if changed:
                time_entries_to_update.append(time_entry)
                if self.run_logger is not None:
                    self.run_logger.record_time_entry_updated(
                        redmine_time_entry_id=time_entry.redmine_time_entry_id,
                        employee_name=self._format_employee_name(employee),
                        employee_id=employee.id,
                        redmine_user_id=employee.redmine_id,
                        issue_id=issue_id,
                        spent_on=spent_on,
                        changes=changes,
                    )

        with transaction.atomic():
            if time_entries_to_create:
                RedmineTimeEntry.objects.bulk_create(time_entries_to_create, batch_size=1000)
            if time_entries_to_update:
                RedmineTimeEntry.objects.bulk_update(
                    time_entries_to_update,
                    [
                        "project_id",
                        "user_id",
                        "issue_id",
                        "hours",
                        "activity_id",
                        "spent_on",
                        "created_at",
                        "redmine_updated_on",
                        "is_deleted_in_redmine",
                    ],
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
                "position": "",
                "employment_date": None,
                "dismissal_date": None,
                "email": "",
                "active": False,
                "synced_at": timezone.now(),
                "is_deleted_in_redmine": False,
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

    def _normalize_project_name(self, value: object) -> str:
        name = str(value or "").strip()
        match = self.PROJECT_TIMESTAMP_PREFIX_RE.match(name)
        if match:
            return match.group("name").strip()
        return name

    def _format_details(self, details: dict[str, int] | dict[str, dict[str, int]]) -> str:
        return str(details)

    def _format_employee_name(self, employee: Employee) -> str:
        full_name = " ".join(
            part
            for part in (
                employee.last_name,
                employee.first_name,
                employee.patronymic,
            )
            if part
        ).strip()
        return full_name or f"employee_id={employee.id}"

    def _normalize_datetime(self, value: datetime | None) -> datetime:
        if value is None:
            return timezone.now()
        if settings.USE_TZ and timezone.is_naive(value):
            return timezone.make_aware(value, timezone.get_current_timezone())
        if not settings.USE_TZ and timezone.is_aware(value):
            return timezone.make_naive(value, timezone.get_current_timezone())
        return value

    def _normalize_date(self, value: object) -> date | None:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value

        text_value = str(value).strip()
        if not text_value:
            return None

        for date_format in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(text_value, date_format).date()
            except ValueError:
                continue
        return None

    def _safe_int(self, value: object) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
