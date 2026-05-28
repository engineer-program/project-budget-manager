import json
from decimal import Decimal, InvalidOperation
from json import JSONDecodeError
from typing import Any

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from apps.reference.models import CompensationType

from .forms import EmployeeSalaryPeriodForm
from .models import Employee, EmployeeBonus, EmployeeCompensation, EmployeeSalary

ZERO = Decimal("0.00")
COMPENSATION_CODES = ("vacation", "sick_leave", "business_trip")


def _format_amount(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def _parse_amount(raw_value: Any) -> Decimal:
    if raw_value is None:
        return ZERO

    normalized = str(raw_value).strip().replace(",", ".")
    if not normalized:
        return ZERO

    try:
        return Decimal(normalized).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return ZERO


def _selected_quarter(month: int) -> int:
    return ((month - 1) // 3) + 1


def _validate_period(data: dict[str, Any]) -> tuple[int, int] | tuple[None, None]:
    form = EmployeeSalaryPeriodForm(data)
    if not form.is_valid():
        return None, None
    return form.cleaned_data["year"], form.cleaned_data["month"]


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

    compensation_type_ids = list(
        CompensationType.objects.filter(code__in=COMPENSATION_CODES).values_list("id", flat=True)
    )
    compensation_rows = EmployeeCompensation.objects.filter(
        year=year,
        month=month,
        type_id__in=compensation_type_ids,
    ).select_related("type")

    compensation_map: dict[tuple[int, str], Decimal] = {}
    for compensation in compensation_rows:
        compensation_map[(compensation.employee_id, compensation.type.code)] = compensation.amount

    rows: list[dict[str, object]] = []
    for employee in employees:
        salary = salary_map.get(employee.id)
        bonus = bonus_map.get(employee.id)
        rows.append(
            {
                "employee_id": employee.id,
                "full_name": str(employee),
                "position": employee.position or "-",
                "base_salary": _format_amount(salary.base_salary if salary else ZERO),
                "extra_salary": _format_amount(salary.extra_salary if salary else ZERO),
                "bonus": _format_amount(bonus.bonus if bonus else ZERO),
                "extra_bonus": _format_amount(bonus.extra_bonus if bonus else ZERO),
                "vacation": _format_amount(compensation_map.get((employee.id, "vacation"), ZERO)),
                "sick_leave": _format_amount(compensation_map.get((employee.id, "sick_leave"), ZERO)),
                "business_trip": _format_amount(compensation_map.get((employee.id, "business_trip"), ZERO)),
            }
        )

    return rows


@transaction.atomic
def _save_employee_salary_rows(year: int, month: int, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0

    employee_ids = {int(row["employee_id"]) for row in rows if row.get("employee_id")}
    existing_employee_ids = set(
        Employee.objects.filter(id__in=employee_ids).values_list("id", flat=True)
    )
    quarter = _selected_quarter(month)
    compensation_types = {
        item.code: item
        for item in CompensationType.objects.filter(code__in=COMPENSATION_CODES)
    }

    saved = 0
    for row in rows:
        employee_id = int(row.get("employee_id") or 0)
        if employee_id not in existing_employee_ids:
            continue

        EmployeeSalary.objects.update_or_create(
            employee_id=employee_id,
            year=year,
            month=month,
            defaults={
                "base_salary": _parse_amount(row.get("base_salary")),
                "extra_salary": _parse_amount(row.get("extra_salary")),
            },
        )

        EmployeeBonus.objects.update_or_create(
            employee_id=employee_id,
            bonus_year=year,
            bonus_quarter=quarter,
            defaults={
                "year": year,
                "month": month,
                "bonus": _parse_amount(row.get("bonus")),
                "extra_bonus": _parse_amount(row.get("extra_bonus")),
            },
        )

        for code in COMPENSATION_CODES:
            compensation_type = compensation_types.get(code)
            if compensation_type is None:
                continue

            EmployeeCompensation.objects.update_or_create(
                employee_id=employee_id,
                year=year,
                month=month,
                type=compensation_type,
                defaults={"amount": _parse_amount(row.get(code))},
            )

        saved += 1

    return saved


@login_required
@ensure_csrf_cookie
def employee_salaries_view(request: HttpRequest) -> HttpResponse:
    form = EmployeeSalaryPeriodForm()
    return render(request, "employees/salaries_monthly.html", {"form": form})


@login_required
@require_GET
def employee_salaries_data_view(request: HttpRequest) -> JsonResponse:
    year, month = _validate_period(request.GET)
    if year is None or month is None:
        return JsonResponse(
            {"status": "error", "message": "Некорректный месяц или год."},
            status=400,
        )

    return JsonResponse(
        {
            "status": "ok",
            "year": year,
            "month": month,
            "rows": _build_employee_salary_rows(year, month),
        }
    )


@login_required
@require_POST
def employee_salaries_bulk_save_view(request: HttpRequest) -> JsonResponse:
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {"status": "error", "message": "Некорректный JSON."},
            status=400,
        )

    year, month = _validate_period(payload)
    rows = payload.get("rows")
    if year is None or month is None or not isinstance(rows, list):
        return JsonResponse(
            {"status": "error", "message": "Некорректные данные для сохранения."},
            status=400,
        )

    saved = _save_employee_salary_rows(year, month, rows)
    return JsonResponse({"status": "ok", "saved": saved})
