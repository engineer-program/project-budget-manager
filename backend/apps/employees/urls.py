from django.urls import path

from .views import employee_salaries_view

urlpatterns = [
    path("employees-salaries/", employee_salaries_view, name="employees-salaries"),
]
