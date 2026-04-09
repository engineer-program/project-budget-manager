from django.conf import settings
from django.db import models


class ChangeLog(models.Model):
    ACTION_CREATE = "create"
    ACTION_UPDATE = "update"
    ACTION_DELETE = "delete"

    ACTION_CHOICES = [
        (ACTION_CREATE, "Create"),
        (ACTION_UPDATE, "Update"),
        (ACTION_DELETE, "Delete"),
    ]

    entity_name = models.CharField(max_length=100, db_index=True)
    entity_id = models.PositiveIntegerField(db_index=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="change_logs",
    )
    changed_at = models.DateTimeField(auto_now_add=True, db_index=True)
    before_data = models.JSONField(null=True, blank=True)
    after_data = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "change_log"
        ordering = ["-changed_at"]
        indexes = [
            models.Index(fields=["entity_name", "entity_id"], name="idx_change_entity"),
        ]
