from __future__ import annotations

import traceback
from pathlib import Path
from typing import TextIO

from django.conf import settings
from django.utils import timezone

from apps.redmine_sync.models import SyncRun


class SyncRunLogger:
    """Writes a human-readable audit report for one Redmine synchronization run."""

    def __init__(
        self,
        *,
        mode: str,
        trigger_source: str,
        triggered_by: str = "",
        chunk_size: int,
        window_days: int | None = None,
    ) -> None:
        self.mode = mode
        self.trigger_source = trigger_source
        self.triggered_by = triggered_by or "system"
        self.chunk_size = chunk_size
        self.window_days = window_days
        self.started_at = timezone.now()
        self._details: dict[str, dict[str, int]] = {}
        self._file: TextIO | None = None

        logs_dir = Path(settings.PROJECT_ROOT) / "var" / "sync_logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        timestamp = self._format_filename_timestamp(self.started_at)
        self.log_file_path = logs_dir / f"redmine_sync_{timestamp}_{mode}_running.log"

        self.run = SyncRun.objects.create(
            mode=mode,
            trigger_source=trigger_source,
            triggered_by=self.triggered_by,
            status=SyncRun.STATUS_RUNNING,
            started_at=self.started_at,
            log_file_path=str(self.log_file_path),
        )

        self._file = self.log_file_path.open("w", encoding="utf-8")
        self._write_header()

    def record_section_result(self, section: str, stats: dict[str, int]) -> None:
        self._details[section] = stats
        self.write("")
        self.write(f"Итог по разделу: {section}")
        self.write("-" * 50)
        self.write(f"- создано: {stats.get('created', 0)}")
        self.write(f"- обновлено: {stats.get('updated', 0)}")
        self.write(f"- помечено удалёнными в Redmine: {stats.get('deleted', 0)}")
        self.write(f"- пропущено: {stats.get('skipped', 0)}")

    def record_time_entry_updated(
        self,
        *,
        redmine_time_entry_id: int,
        employee_name: str,
        employee_id: int | None,
        redmine_user_id: int | None,
        issue_id: int | None,
        spent_on: object,
        changes: dict[str, tuple[object, object]],
    ) -> None:
        self.write("")
        self.write(f"[TIME_ENTRY_UPDATED] redmine_time_entry_id={redmine_time_entry_id}")
        self.write(f"- сотрудник: {employee_name}")
        self.write(f"- employee_id: {employee_id}")
        self.write(f"- redmine_user_id: {redmine_user_id}")
        self.write(f"- issue_id: {issue_id}")
        self.write(f"- spent_on: {spent_on}")
        for field_name, (old_value, new_value) in changes.items():
            self.write(f"- {field_name}: {old_value} -> {new_value}")

    def record_time_entry_deleted(self, item: dict[str, object]) -> None:
        self.write("")
        self.write(f"[TIME_ENTRY_DELETED_IN_REDMINE] redmine_time_entry_id={item.get('redmine_time_entry_id')}")
        self.write(f"- project_id: {item.get('project_id')}")
        self.write(f"- user_id: {item.get('user_id')}")
        self.write(f"- issue_id: {item.get('issue_id')}")
        self.write(f"- hours: {item.get('hours')}")
        self.write(f"- activity_id: {item.get('activity_id')}")
        self.write(f"- spent_on: {item.get('spent_on')}")
        self.write("- причина: запись отсутствует в Redmine при reconciliation")

    def record_time_entry_skipped(self, item: dict[str, object], reason: str) -> None:
        self.write("")
        self.write(f"[TIME_ENTRY_SKIPPED] redmine_time_entry_id={item.get('redmine_time_entry_id')}")
        self.write(f"- причина: {reason}")
        self.write(f"- redmine_project_id: {item.get('redmine_project_id')}")
        self.write(f"- redmine_user_id: {item.get('redmine_user_id')}")
        self.write(f"- hours: {item.get('hours')}")
        self.write(f"- spent_on: {item.get('spent_on')}")

    def record_project_deleted(self, item: dict[str, object]) -> None:
        self.write("")
        self.write(f"[PROJECT_DELETED_IN_REDMINE] redmine_project_id={item.get('redmine_project_id')}")
        self.write(f"- project_finance.id: {item.get('id')}")
        self.write(f"- name: {item.get('name')}")
        self.write(f"- project_number: {item.get('project_number')}")
        self.write(f"- status: {item.get('status')}")
        self.write(f"- marked_at: {self._format_dt(timezone.now())}")

    def record_employee_deleted(self, item: dict[str, object]) -> None:
        full_name = " ".join(
            str(item.get(field) or "").strip()
            for field in ("last_name", "first_name", "patronymic")
        ).strip()
        self.write("")
        self.write(f"[EMPLOYEE_DELETED_IN_REDMINE] redmine_id={item.get('redmine_id')}")
        self.write(f"- employee_id: {item.get('id')}")
        self.write(f"- ФИО: {full_name or '-'}")
        self.write(f"- email: {item.get('email') or '-'}")
        self.write(f"- active: {item.get('active')}")
        self.write(f"- marked_at: {self._format_dt(timezone.now())}")

    def finalize_success(self, details: dict[str, dict[str, int]]) -> None:
        self._details = details
        self._finalize(status=SyncRun.STATUS_SUCCESS)

    def finalize_failed(self, exc: Exception) -> None:
        self.write("")
        self.write("Ошибки")
        self.write("=" * 50)
        self.write(f"[ERROR] {type(exc).__name__}: {exc}")
        self.write("")
        self.write(traceback.format_exc())
        self._finalize(status=SyncRun.STATUS_FAILED, error_message=str(exc))

    def write(self, message: str) -> None:
        if self._file is None:
            return
        self._file.write(f"{message}\n")
        self._file.flush()

    def _write_header(self) -> None:
        self.write("Синхронизация Easy Redmine")
        self.write("=" * 50)
        self.write("")
        self.write("Статус: ВЫПОЛНЯЕТСЯ")
        self.write(f"Тип синхронизации: {self.mode}")
        self.write(f"Источник запуска: {self.trigger_source}")
        self.write(f"Запустил пользователь: {self.triggered_by}")
        self.write(f"Время начала: {self._format_dt(self.started_at)}")
        self.write(f"Batch size: {self.chunk_size}")
        if self.window_days is not None:
            self.write(f"Окно синхронизации: {self.window_days} дней")

    def _finalize(self, *, status: str, error_message: str = "") -> None:
        finished_at = timezone.now()
        duration_seconds = int((finished_at - self.started_at).total_seconds())

        self.write("")
        self.write("Финальная сводка")
        self.write("=" * 50)
        self.write(f"Статус: {status.upper()}")
        self.write(f"Время окончания: {self._format_dt(finished_at)}")
        self.write(f"Длительность: {duration_seconds} сек.")

        for section, stats in self._details.items():
            self.write("")
            self.write(f"{section}:")
            self.write(f"- создано: {stats.get('created', 0)}")
            self.write(f"- обновлено: {stats.get('updated', 0)}")
            self.write(f"- помечено удалёнными в Redmine: {stats.get('deleted', 0)}")
            self.write(f"- пропущено: {stats.get('skipped', 0)}")

        final_path = self._rename_final_log(status)
        self.run.status = status
        self.run.finished_at = finished_at
        self.run.duration_seconds = duration_seconds
        self.run.log_file_path = str(final_path)
        self.run.error_message = error_message
        self._apply_details_to_run()
        self.run.save()

        if self._file is not None:
            self._file.close()
            self._file = None

    def _rename_final_log(self, status: str) -> Path:
        if self._file is not None:
            self._file.flush()

        final_path = Path(str(self.log_file_path).replace("_running.log", f"_{status}.log"))
        if final_path == self.log_file_path:
            return self.log_file_path

        if self._file is not None:
            self._file.close()
            self._file = None
        self.log_file_path.rename(final_path)
        self.log_file_path = final_path
        return final_path

    def _apply_details_to_run(self) -> None:
        section_map = {
            "employees": "employees",
            "groups": "groups",
            "group_memberships": "group_memberships",
            "projects": "projects",
            "time_entries": "time_entries",
        }
        for section, prefix in section_map.items():
            stats = self._details.get(section, {})
            for key in ("created", "updated", "deleted", "skipped"):
                setattr(self.run, f"{prefix}_{key}", stats.get(key, 0))

    def _format_dt(self, value: object) -> str:
        if value is None:
            return "-"
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.strftime("%Y-%m-%d %H:%M:%S %Z")

    def _format_value(self, value: object) -> str:
        if hasattr(value, "strftime"):
            return self._format_dt(value)
        return str(value)

    def _format_filename_timestamp(self, value: object) -> str:
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.strftime("%Y-%m-%d_%H-%M-%S")
