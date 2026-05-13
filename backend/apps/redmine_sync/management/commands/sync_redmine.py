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

    def handle(self, *args, **options):
        service = SyncService()
        details = service.run(trigger_source=options["trigger_source"])
        self.stdout.write(self.style.SUCCESS(f"Sync completed: {details}"))
