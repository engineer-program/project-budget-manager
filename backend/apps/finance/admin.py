from django.contrib import admin

from .models import ExpenseCategory, ProjectExpense, ProjectIncome


class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name", "description")


class ProjectExpenseAdmin(admin.ModelAdmin):
    list_display = ("project", "category", "amount", "expense_date", "created_by")
    search_fields = ("project__name", "category__name", "description")
    list_filter = ("category", "expense_date")
    autocomplete_fields = ["project", "category", "responsible_employee", "created_by"]


class ProjectIncomeAdmin(admin.ModelAdmin):
    list_display = ("project", "article", "amount", "income_date", "created_by")
    search_fields = ("project__name", "article", "description")
    list_filter = ("income_date",)
    autocomplete_fields = ["project", "responsible_employee", "created_by"]


admin.site.register(ExpenseCategory, ExpenseCategoryAdmin)
admin.site.register(ProjectExpense, ProjectExpenseAdmin)
admin.site.register(ProjectIncome, ProjectIncomeAdmin)
