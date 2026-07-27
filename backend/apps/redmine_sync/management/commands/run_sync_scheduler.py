from __future__ import annotations

import time
from datetime import date, datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.redmine_sync.services.sync_service import SyncService


class Command(BaseCommand):
    help = "Run the Redmine synchronization scheduler loop."

    def add_arguments(self, parser):
        parser.add_argument(
            "--poll-seconds",
            type=int,
            default=60,
            help="How often to check the scheduler plan in seconds.",
        )

    def handle(self, *args, **options):
        poll_seconds: int = options["poll_seconds"]
        service = SyncService()

        last_incremental_slot: datetime | None = None
        last_window_run_date: date | None = None

        self.stdout.write(
            self.style.SUCCESS(
                "Sync scheduler started: incremental every 30 minutes, "
                "window sync daily at 05:00."
            )
        )

        while True:
            current_time = timezone.now()
            now = timezone.localtime(current_time) if timezone.is_aware(current_time) else current_time

            if self._should_run_window(now, last_window_run_date):
                self.stdout.write(
                    f"[{now:%Y-%m-%d %H:%M:%S}] Running daily window sync for last 365 days."
                )
                details = service.run(
                    trigger_source="scheduler-daily-5am",
                    time_entries_mode=SyncService.TIME_ENTRIES_MODE_WINDOW,
                    chunk_size=SyncService.DEFAULT_CHUNK_SIZE,
                    window_days=SyncService.DEFAULT_WINDOW_DAYS,
                )
                self.stdout.write(self.style.SUCCESS(f"Window sync completed: {details}"))
                last_window_run_date = now.date()
                # Skip the overlapping 05:00 incremental slot; the window sync already covers it.
                last_incremental_slot = now.replace(second=0, microsecond=0)

            # elif self._should_run_incremental(now, last_incremental_slot):
            #     slot = now.replace(minute=(now.minute // 30) * 30, second=0, microsecond=0)
            #     self.stdout.write(
            #         f"[{now:%Y-%m-%d %H:%M:%S}] Running incremental sync."
            #     )
            #     details = service.run(
            #         trigger_source="scheduler-30m",
            #         time_entries_mode=SyncService.TIME_ENTRIES_MODE_INCREMENTAL,
            #         chunk_size=SyncService.DEFAULT_CHUNK_SIZE,
            #     )
            #     self.stdout.write(self.style.SUCCESS(f"Incremental sync completed: {details}"))
            #     last_incremental_slot = slot

            time.sleep(poll_seconds)

    # def _should_run_incremental(
    #     self,
    #     now: datetime,
    #     last_incremental_slot: datetime | None,
    # ) -> bool:
    #     if now.minute not in (0, 30):
    #         return False

    #     slot = now.replace(minute=(now.minute // 30) * 30, second=0, microsecond=0)
    #     return slot != last_incremental_slot

    def _should_run_window(
        self,
        now: datetime,
        last_window_run_date: date | None,
    ) -> bool:
        if now.hour != 5 or now.minute != 0:
            return False
        return now.date() != last_window_run_date
