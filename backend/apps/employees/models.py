from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.common.models import TimestampedModel


class Employee(models.Model):
    redmine_id = models.IntegerField(unique=True, db_index=True)
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)
    patronymic = models.CharField(max_length=255, blank=True)
    position = models.CharField(max_length=255, blank=True)
    employment_date = models.DateField(null=True, blank=True)
    dismissal_date = models.DateField(null=True, blank=True)
    email = models.EmailField(max_length=255, blank=True, db_index=True)
    active = models.BooleanField(default=True, db_index=True)
    synced_at = models.DateTimeField(null=True, blank=True)
    is_deleted_in_redmine = models.BooleanField(default=False, db_index=True)

    class Meta:
        db_table = "employees"
        ordering = ["last_name", "first_name", "patronymic"]

    def __str__(self):
        parts = [self.last_name, self.first_name, self.patronymic]
        return " ".join(part for part in parts if part).strip()


class RedmineGroup(models.Model):
    redmine_group_id = models.IntegerField(unique=True, db_index=True)
    name = models.CharField(max_length=255)
    active = models.BooleanField(default=True, db_index=True)
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "redmine_groups"
        ordering = ["name"]

    def __str__(self):
        return self.name


class EmployeeGroupMembership(models.Model):
    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.CASCADE,
        related_name="group_memberships",
        db_column="employee_id",
    )
    group = models.ForeignKey(
        "employees.RedmineGroup",
        on_delete=models.CASCADE,
        related_name="employee_memberships",
        db_column="group_id",
    )

    class Meta:
        db_table = "employee_group_memberships"
        ordering = ["group_id", "employee_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "group"],
                name="uniq_employee_group_membership",
            ),
        ]


class EmployeeUserBinding(TimestampedModel):
    employee = models.OneToOneField(
        "employees.Employee",
        on_delete=models.PROTECT,
        related_name="user_binding",
        db_column="employee_id",
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="employee_binding",
        db_column="user_id",
    )

    class Meta:
        db_table = "employee_user_bindings"
        ordering = ["employee_id"]

    def __str__(self):
        return f"{self.employee} -> {self.user}"


class EmployeeSalary(TimestampedModel):
    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        related_name="salaries",
        db_column="employee_id",
    )
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()
    base_salary = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    extra_salary = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        db_table = "employee_salaries"
        ordering = ["-year", "-month", "employee_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "year", "month"],
                name="uniq_employee_salary_period",
            ),
            models.CheckConstraint(
                condition=Q(month__gte=1) & Q(month__lte=12),
                name="chk_employee_salary_month_1_12",
            ),
        ]
        indexes = [
            models.Index(fields=["year", "month"], name="idx_salary_year_month"),
        ]


class EmployeeBonus(TimestampedModel):
    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        related_name="bonuses",
        db_column="employee_id",
    )
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()
    bonus = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    bonus_year = models.PositiveSmallIntegerField()
    bonus_quarter = models.PositiveSmallIntegerField()
    extra_bonus = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        db_table = "employee_bonuses"
        ordering = ["-bonus_year", "-bonus_quarter", "employee_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "bonus_year", "bonus_quarter"],
                name="uniq_employee_bonus_quarter",
            ),
            models.CheckConstraint(
                condition=Q(month__gte=1) & Q(month__lte=12),
                name="chk_employee_bonus_month_1_12",
            ),
            models.CheckConstraint(
                condition=Q(bonus_quarter__gte=1) & Q(bonus_quarter__lte=4),
                name="chk_employee_bonus_quarter_1_4",
            ),
        ]
        indexes = [
            models.Index(
                fields=["employee", "year", "month"],
                name="idx_bonus_employee_year_month",
            ),
        ]


class EmployeeCompensation(TimestampedModel):
    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        related_name="compensations",
        db_column="employee_id",
    )
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()
    type = models.ForeignKey(
        "reference.CompensationType",
        on_delete=models.PROTECT,
        related_name="employee_compensations",
        db_column="type_id",
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        db_table = "employee_compensations"
        ordering = ["-year", "-month", "employee_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "year", "month", "type"],
                name="uniq_employee_compensation_period_type",
            ),
            models.CheckConstraint(
                condition=Q(month__gte=1) & Q(month__lte=12),
                name="chk_employee_comp_month_1_12",
            ),
        ]
        indexes = [
            models.Index(
                fields=["employee", "year", "month"],
                name="idx_comp_employee_year_month",
            ),
        ]
