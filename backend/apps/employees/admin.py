from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from .models import (
    Employee,
    EmployeeBonus,
    EmployeeCompensation,
    EmployeeSalary,
    EmployeeUserBinding,
)

User = get_user_model()


class EmployeeUserBindingInline(admin.StackedInline):
    model = EmployeeUserBinding
    fk_name = "user"
    can_delete = False
    extra = 0
    autocomplete_fields = ["employee"]
    verbose_name = "Привязка к сотруднику"
    verbose_name_plural = "Привязка к сотруднику"


class EmployeeUserBindingAdmin(admin.ModelAdmin):
    list_display = ("employee", "user", "created_at", "updated_at")
    search_fields = (
        "employee__last_name",
        "employee__first_name",
        "employee__patronymic",
        "user__username",
        "user__email",
    )
    autocomplete_fields = ["employee", "user"]


class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("last_name", "first_name", "patronymic", "position", "email", "active", "redmine_id")
    search_fields = ("last_name", "first_name", "patronymic", "position", "email", "redmine_id")
    list_filter = ("active",)


class EmployeeSalaryAdmin(admin.ModelAdmin):
    list_display = ("employee", "year", "month", "base_salary", "extra_salary", "updated_at")
    search_fields = ("employee__last_name", "employee__first_name", "employee__patronymic")
    list_filter = ("year", "month")
    autocomplete_fields = ["employee"]


class EmployeeBonusAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "year",
        "month",
        "bonus_year",
        "bonus_quarter",
        "bonus",
        "extra_bonus",
        "updated_at",
    )
    search_fields = ("employee__last_name", "employee__first_name", "employee__patronymic")
    list_filter = ("year", "month", "bonus_year", "bonus_quarter")
    autocomplete_fields = ["employee"]


class EmployeeCompensationAdmin(admin.ModelAdmin):
    list_display = ("employee", "year", "month", "type", "amount", "updated_at")
    search_fields = ("employee__last_name", "employee__first_name", "employee__patronymic")
    list_filter = ("year", "month", "type")
    autocomplete_fields = ["employee", "type"]


class ProjectFinanceUserAdmin(UserAdmin):
    inlines = [EmployeeUserBindingInline]
    list_display = UserAdmin.list_display + ("get_employee",)

    @admin.display(description="Сотрудник")
    def get_employee(self, obj):
        binding = getattr(obj, "employee_binding", None)
        return binding.employee if binding else "-"


try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass

admin.site.register(User, ProjectFinanceUserAdmin)
admin.site.register(Employee, EmployeeAdmin)
admin.site.register(EmployeeSalary, EmployeeSalaryAdmin)
admin.site.register(EmployeeBonus, EmployeeBonusAdmin)
admin.site.register(EmployeeCompensation, EmployeeCompensationAdmin)
admin.site.register(EmployeeUserBinding, EmployeeUserBindingAdmin)
