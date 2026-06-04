from django.conf import settings
from django.db import models


class ExpenseCategory(models.Model):
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "expense_categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class ProjectExpense(models.Model):
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        related_name="expenses",
        db_column="project_id",
    )
    category = models.ForeignKey(
        "finance.ExpenseCategory",
        on_delete=models.PROTECT,
        related_name="project_expenses",
        db_column="category_id",
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    responsible_employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        related_name="responsible_expenses",
        db_column="responsible_employee_id",
    )
    description = models.TextField(blank=True)
    expense_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_project_expenses",
        db_column="created_by_id",
    )

    class Meta:
        db_table = "project_expenses"
        ordering = ["-expense_date", "-id"]
        indexes = [
            models.Index(fields=["project", "expense_date"], name="idx_exp_project_date"),
            models.Index(fields=["category"], name="idx_exp_category"),
            models.Index(fields=["responsible_employee"], name="idx_exp_resp_employee"),
            models.Index(fields=["created_by"], name="idx_exp_created_by"),
        ]


class ProjectIncome(models.Model):
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        related_name="incomes",
        db_column="project_id",
    )
    article = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    responsible_employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        related_name="responsible_incomes",
        db_column="responsible_employee_id",
    )
    description = models.TextField(blank=True)
    income_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_project_incomes",
        db_column="created_by_id",
    )

    class Meta:
        db_table = "project_incomes"
        ordering = ["-income_date", "-id"]
        indexes = [
            models.Index(fields=["project", "income_date"], name="idx_inc_project_date"),
            models.Index(fields=["responsible_employee"], name="idx_inc_resp_employee"),
            models.Index(fields=["created_by"], name="idx_inc_created_by"),
        ]
