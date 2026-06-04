from django.urls import path

from .views import (
    employee_groups_data_view,
    employee_bonus_conflict_view,
    employee_bonus_delete_view,
    employee_report_data_view,
    employee_salaries_bulk_save_view,
    employee_salaries_data_view,
)

urlpatterns = [
    path("groups/", employee_groups_data_view, name="employee-groups-data"),
    path("bonus-conflict/", employee_bonus_conflict_view, name="employee-bonus-conflict"),
    path("bonus-delete/", employee_bonus_delete_view, name="employee-bonus-delete"),
    path("report/", employee_report_data_view, name="employee-report-data"),
    path("salaries/", employee_salaries_data_view, name="employee-salaries-data"),
    path("salaries/bulk-save/", employee_salaries_bulk_save_view, name="employee-salaries-bulk-save"),
]
