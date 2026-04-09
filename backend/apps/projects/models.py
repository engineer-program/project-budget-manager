from django.conf import settings
from django.db import models

from apps.common.models import TimestampedModel


class Project(TimestampedModel):
    redmine_project_id = models.IntegerField(unique=True, db_index=True)
    name = models.CharField(max_length=255)
    name_1s = models.CharField(max_length=255, blank=True, db_column="name_1s")
    name_sanda = models.CharField(max_length=255, blank=True)
    project_number = models.CharField(max_length=100, blank=True, db_index=True)
    lead_department = models.CharField(max_length=255, blank=True)
    parent_project = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="subprojects",
        db_column="parent_project_id",
    )
    project_manager = models.ForeignKey(
        "employees.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_projects",
        db_column="project_manager_id",
    )
    start_budget = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    budget_updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="budget_updated_projects",
        db_column="budget_updated_by_id",
    )

    class Meta:
        db_table = "projects"
        ordering = ["name"]

    def __str__(self):
        return self.name
