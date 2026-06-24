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


class SyncRun(models.Model):
    MODE_INCREMENTAL = "incremental"
    MODE_WINDOW = "window"
    MODE_FULL = "full"

    STATUS_RUNNING = "running"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_PARTIAL = "partial"

    mode = models.CharField(max_length=50)
    trigger_source = models.CharField(max_length=100)
    triggered_by = models.CharField(max_length=150, blank=True)
    status = models.CharField(max_length=50, default=STATUS_RUNNING)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    log_file_path = models.CharField(max_length=500, blank=True)
    error_message = models.TextField(blank=True)

    employees_created = models.PositiveIntegerField(default=0)
    employees_updated = models.PositiveIntegerField(default=0)
    employees_deleted = models.PositiveIntegerField(default=0)
    employees_skipped = models.PositiveIntegerField(default=0)

    groups_created = models.PositiveIntegerField(default=0)
    groups_updated = models.PositiveIntegerField(default=0)
    groups_deleted = models.PositiveIntegerField(default=0)
    groups_skipped = models.PositiveIntegerField(default=0)

    group_memberships_created = models.PositiveIntegerField(default=0)
    group_memberships_updated = models.PositiveIntegerField(default=0)
    group_memberships_deleted = models.PositiveIntegerField(default=0)
    group_memberships_skipped = models.PositiveIntegerField(default=0)

    projects_created = models.PositiveIntegerField(default=0)
    projects_updated = models.PositiveIntegerField(default=0)
    projects_deleted = models.PositiveIntegerField(default=0)
    projects_skipped = models.PositiveIntegerField(default=0)

    time_entries_created = models.PositiveIntegerField(default=0)
    time_entries_updated = models.PositiveIntegerField(default=0)
    time_entries_deleted = models.PositiveIntegerField(default=0)
    time_entries_skipped = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "sync_runs"
        ordering = ["-started_at"]
