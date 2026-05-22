from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from apps.reference.models import CompensationType

from .forms import EmployeeSalaryPeriodForm
from .models import Employee, EmployeeBonus, EmployeeCompensation, EmployeeSalary

ZERO = Decimal("0.00")
COMPENSATION_CODES = {
    "vacation": "Отпускные",
    "sick_leave": "Больничные",
    "business_trip": "Командировочные",
}


def _format_amount(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def _parse_amount(raw_value: str | None) -> Decimal:
    if raw_value is None:
        return ZERO

    normalized = raw_value.strip().replace(",", ".")
    if not normalized:
        return ZERO

    try:
        return Decimal(normalized).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return ZERO


def _selected_quarter(month: int) -> int:
    return ((month - 1) // 3) + 1


def _build_employee_salary_rows(year: int, month: int) -> list[dict[str, object]]:
    employees = list(Employee.objects.all())
    quarter = _selected_quarter(month)

    salary_map = {
        salary.employee_id: salary
        for salary in EmployeeSalary.objects.filter(year=year, month=month)
    }
    bonus_map = {
        bonus.employee_id: bonus
        for bonus in EmployeeBonus.objects.filter(bonus_year=year, bonus_quarter=quarter)
    }

    compensation_type_map = {
        item.code: item.id
        for item in CompensationType.objects.filter(code__in=COMPENSATION_CODES.keys())
    }
    compensation_rows = EmployeeCompensation.objects.filter(
        year=year,
        month=month,
        type_id__in=compensation_type_map.values(),
    ).select_related("type")

    compensation_map: dict[tuple[int, str], Decimal] = {}
    for compensation in compensation_rows:
        compensation_map[(compensation.employee_id, compensation.type.code)] = compensation.amount

    rows: list[dict[str, object]] = []
    for employee in employees:
        salary = salary_map.get(employee.id)
        bonus = bonus_map.get(employee.id)
        row = {
            "employee_id": employee.id,
            "full_name": str(employee),
            "position": "—",
            "base_salary": _format_amount(salary.base_salary if salary else ZERO),
            "extra_salary": _format_amount(salary.extra_salary if salary else ZERO),
            "bonus": _format_amount(bonus.bonus if bonus else ZERO),
            "extra_bonus": _format_amount(bonus.extra_bonus if bonus else ZERO),
            "vacation": _format_amount(compensation_map.get((employee.id, "vacation"), ZERO)),
            "sick_leave": _format_amount(compensation_map.get((employee.id, "sick_leave"), ZERO)),
            "business_trip": _format_amount(compensation_map.get((employee.id, "business_trip"), ZERO)),
        }
        rows.append(row)

    return rows


@transaction.atomic
def _save_employee_salary_rows(request: HttpRequest, year: int, month: int) -> None:
    employee_ids = list(
        Employee.objects.values_list("id", flat=True)
    )
    quarter = _selected_quarter(month)
    compensation_types = {
        item.code: item
        for item in CompensationType.objects.filter(code__in=COMPENSATION_CODES.keys())
    }

    for employee_id in employee_ids:
        base_salary = _parse_amount(request.POST.get(f"base_salary_{employee_id}"))
        extra_salary = _parse_amount(request.POST.get(f"extra_salary_{employee_id}"))
        bonus_amount = _parse_amount(request.POST.get(f"bonus_{employee_id}"))
        extra_bonus = _parse_amount(request.POST.get(f"extra_bonus_{employee_id}"))

        salary_defaults = {
            "base_salary": base_salary,
            "extra_salary": extra_salary,
        }
        EmployeeSalary.objects.update_or_create(
            employee_id=employee_id,
            year=year,
            month=month,
            defaults=salary_defaults,
        )

        EmployeeBonus.objects.update_or_create(
            employee_id=employee_id,
            bonus_year=year,
            bonus_quarter=quarter,
            defaults={
                "year": year,
                "month": month,
                "bonus": bonus_amount,
                "extra_bonus": extra_bonus,
            },
        )

        for code in COMPENSATION_CODES:
            compensation_type = compensation_types.get(code)
            if not compensation_type:
                continue

            amount = _parse_amount(request.POST.get(f"{code}_{employee_id}"))
            EmployeeCompensation.objects.update_or_create(
                employee_id=employee_id,
                year=year,
                month=month,
                type=compensation_type,
                defaults={"amount": amount},
            )


@login_required
def employee_salaries_view(request: HttpRequest) -> HttpResponse:
    show_table = False
    rows: list[dict[str, object]] = []

    if request.method == "POST":
        form = EmployeeSalaryPeriodForm(request.POST)
        action = request.POST.get("action")
        if form.is_valid():
            year = form.cleaned_data["year"]
            month = form.cleaned_data["month"]

            if action == "save":
                _save_employee_salary_rows(request, year, month)
                messages.success(request, "Изменения по заработной плате сотрудников сохранены.")
                return redirect(f"{request.path}?month={month}&year={year}&loaded=1")

            if action == "load":
                show_table = True
                rows = _build_employee_salary_rows(year, month)
        else:
            messages.error(request, "Проверьте выбранные месяц и год.")
    else:
        month = request.GET.get("month")
        year = request.GET.get("year")
        if month and year:
            form = EmployeeSalaryPeriodForm(request.GET)
        else:
            form = EmployeeSalaryPeriodForm()

        if request.GET.get("loaded") == "1" and form.is_valid():
            show_table = True
            rows = _build_employee_salary_rows(
                form.cleaned_data["year"],
                form.cleaned_data["month"],
            )

    context = {
        "form": form,
        "show_table": show_table,
        "rows": rows,
    }
    return render(request, "employees/salaries_monthly.html", context)
