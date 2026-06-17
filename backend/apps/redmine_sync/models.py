from django.db import models


class RedmineTimeEntry(models.Model):
    redmine_time_entry_id = models.IntegerField(unique=True, db_index=True)
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        related_name="redmine_time_entries",
        db_column="project_id",
    )
    user = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        related_name="redmine_time_entries",
        db_column="user_id",
    )
    issue_id = models.IntegerField(null=True, blank=True, db_index=True)
    hours = models.DecimalField(max_digits=8, decimal_places=2)
    activity_id = models.IntegerField(db_index=True)
    spent_on = models.DateField()
    created_at = models.DateTimeField()
    redmine_updated_on = models.DateTimeField(null=True, blank=True)
    is_deleted_in_redmine = models.BooleanField(default=False, db_index=True)

    class Meta:
        db_table = "redmine_time_entries"
        ordering = ["-spent_on", "-id"]
        indexes = [
            models.Index(fields=["project", "spent_on"], name="idx_rte_project_spent"),
            models.Index(fields=["user", "spent_on"], name="idx_rte_user_spent"),
        ]


class SyncState(models.Model):
    entity_code = models.CharField(max_length=100, unique=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=50, blank=True)
    cursor_int = models.BigIntegerField(null=True, blank=True)
    message = models.TextField(blank=True)

    class Meta:
        db_table = "sync_state"
        ordering = ["entity_code"]


class SyncLog(models.Model):
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    trigger_source = models.CharField(max_length=50)
    status = models.CharField(max_length=50)
    details = models.TextField(blank=True)

    class Meta:
        db_table = "sync_log"
        ordering = ["-started_at"]
