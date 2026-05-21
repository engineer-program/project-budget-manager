from django.core.management.base import BaseCommand

from apps.redmine_sync.services.sync_service import SyncService


class Command(BaseCommand):
    help = "Synchronize employees, projects and time entries from Easy Redmine."

    def add_arguments(self, parser):
        parser.add_argument(
            "--trigger-source",
            default="manual",
            help="Source of synchronization trigger, e.g. manual, login, scheduler.",
        )
        parser.add_argument(
            "--time-entries-mode",
            default=SyncService.TIME_ENTRIES_MODE_INCREMENTAL,
            choices=[
                SyncService.TIME_ENTRIES_MODE_INCREMENTAL,
                SyncService.TIME_ENTRIES_MODE_WINDOW,
                SyncService.TIME_ENTRIES_MODE_FULL,
            ],
            help="Synchronization mode for time entries: incremental, window or full.",
        )
        parser.add_argument(
            "--chunk-size",
            type=int,
            default=SyncService.DEFAULT_CHUNK_SIZE,
            help="Chunk size for time entries synchronization.",
        )
        parser.add_argument(
            "--window-days",
            type=int,
            default=SyncService.DEFAULT_WINDOW_DAYS,
            help="Window size in days for window-based time entries synchronization.",
        )

    def handle(self, *args, **options):
        service = SyncService()
        details = service.run(
            trigger_source=options["trigger_source"],
            time_entries_mode=options["time_entries_mode"],
            chunk_size=options["chunk_size"],
            window_days=options["window_days"],
        )
        self.stdout.write(self.style.SUCCESS(f"Sync completed: {details}"))
