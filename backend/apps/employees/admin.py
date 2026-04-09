from django.contrib import admin

from .models import Employee, EmployeeBonus, EmployeeCompensation, EmployeeSalary


admin.site.register(Employee)
admin.site.register(EmployeeSalary)
admin.site.register(EmployeeBonus)
admin.site.register(EmployeeCompensation)
