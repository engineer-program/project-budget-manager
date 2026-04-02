from django.contrib import admin

from .models import ExpenseCategory, ProjectExpense, ProjectIncome


admin.site.register(ExpenseCategory)
admin.site.register(ProjectExpense)
admin.site.register(ProjectIncome)
