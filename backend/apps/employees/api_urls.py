from django.urls import path

from .views import employee_salaries_bulk_save_view, employee_salaries_data_view

urlpatterns = [
    path("salaries/", employee_salaries_data_view, name="employee-salaries-data"),
    path("salaries/bulk-save/", employee_salaries_bulk_save_view, name="employee-salaries-bulk-save"),
]
