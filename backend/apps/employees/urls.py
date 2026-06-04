from django.urls import path

from .views import employee_report_view, employee_salaries_view

urlpatterns = [
    path("employees-salaries/", employee_salaries_view, name="employees-salaries"),
    path("employee-report/", employee_report_view, name="employee-report"),
]
