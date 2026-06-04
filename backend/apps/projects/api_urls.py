from django.urls import path

from .views import (
    project_budget_update_view,
    project_detail_view,
    project_expense_create_view,
    project_income_create_view,
    project_income_delete_view,
    project_incomes_view,
    projects_data_view,
)

urlpatterns = [
    path("", projects_data_view, name="projects-data"),
    path("<int:project_id>/", project_detail_view, name="project-detail"),
    path("<int:project_id>/budget/", project_budget_update_view, name="project-budget-update"),
    path("<int:project_id>/incomes/", project_incomes_view, name="project-incomes"),
    path("<int:project_id>/incomes/create/", project_income_create_view, name="project-income-create"),
    path("<int:project_id>/incomes/<int:income_id>/delete/", project_income_delete_view, name="project-income-delete"),
    path("<int:project_id>/expenses/create/", project_expense_create_view, name="project-expense-create"),
]
