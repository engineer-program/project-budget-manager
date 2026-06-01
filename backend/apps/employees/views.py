import json
from datetime import date
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

from .forms import EmployeeSalaryPeriodForm, YEAR_CHOICES
from .models import Employee, EmployeeBonus, EmployeeCompensation, EmployeeSalary, RedmineGroup

ZERO = Decimal("0.00")
COMPENSATION_CODES = ("vacation", "sick_leave", "business_trip")
MONTH_NAMES = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}
QUARTER_MONTHS = {
    1: (1, 2, 3),
    2: (4, 5, 6),
    3: (7, 8, 9),
    4: (10, 11, 12),
}


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


def _parse_year(raw_value: Any) -> int | None:
    try:
        year = int(raw_value)
    except (TypeError, ValueError):
        return None
    return year if 2019 <= year <= 2050 else None


def _parse_quarters(raw_values: list[str] | str | None) -> list[int]:
    if raw_values is None:
        return []
    if isinstance(raw_values, str):
        raw_values = raw_values.split(",")

    quarters: list[int] = []
    for raw_value in raw_values:
        try:
            quarter = int(str(raw_value).strip())
        except (TypeError, ValueError):
            continue
        if quarter in QUARTER_MONTHS and quarter not in quarters:
            quarters.append(quarter)
    return sorted(quarters)


def _validate_period(data: dict[str, Any]) -> tuple[int, int] | tuple[None, None]:
    form = EmployeeSalaryPeriodForm(data)
    if not form.is_valid():
        return None, None
    return form.cleaned_data["year"], form.cleaned_data["month"]


def _parse_group_ids(raw_values: list[str] | str | None) -> list[int]:
    if raw_values is None:
        return []
    if isinstance(raw_values, str):
        raw_values = raw_values.split(",")

    group_ids: list[int] = []
    for raw_value in raw_values:
        try:
            group_id = int(str(raw_value).strip())
        except (TypeError, ValueError):
            continue
        if group_id > 0:
            group_ids.append(group_id)
    return group_ids


def _parse_active_filter(raw_value: Any) -> bool | None:
    if raw_value in (None, ""):
        return True
    value = str(raw_value).strip().lower()
    if value in {"all", "*"}:
        return None
    if value in {"1", "true", "active"}:
        return True
    if value in {"0", "false", "blocked"}:
        return False
    return True


def _employees_queryset(
    group_ids: list[int] | None = None,
    active: bool | None = True,
):
    queryset = Employee.objects.all()
    if active is not None:
        queryset = queryset.filter(active=active)
    if group_ids:
        queryset = queryset.filter(group_memberships__group_id__in=group_ids).distinct()
    return queryset


def _build_employee_salary_rows(
    year: int,
    month: int,
    group_ids: list[int] | None = None,
    active: bool | None = True,
) -> list[dict[str, object]]:
    employees = list(_employees_queryset(group_ids, active))

    salary_map = {
        salary.employee_id: salary
        for salary in EmployeeSalary.objects.filter(year=year, month=month)
    }
    bonus_map: dict[int, EmployeeBonus] = {}
    for bonus in EmployeeBonus.objects.filter(year=year, month=month).order_by("employee_id", "-id"):
        bonus_map.setdefault(bonus.employee_id, bonus)

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
                "bonus_id": bonus.id if bonus else None,
                "bonus": _format_amount(bonus.bonus if bonus else ZERO),
                "bonus_year": bonus.bonus_year if bonus else year,
                "bonus_quarter": bonus.bonus_quarter if bonus else _selected_quarter(month),
                "extra_bonus": _format_amount(bonus.extra_bonus if bonus else ZERO),
                "vacation": _format_amount(compensation_map.get((employee.id, "vacation"), ZERO)),
                "sick_leave": _format_amount(compensation_map.get((employee.id, "sick_leave"), ZERO)),
                "business_trip": _format_amount(compensation_map.get((employee.id, "business_trip"), ZERO)),
            }
        )

    return rows


def _build_employee_report_rows(
    year: int,
    quarters: list[int],
    group_ids: list[int] | None = None,
    active: bool | None = True,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    months = [month for quarter in quarters for month in QUARTER_MONTHS[quarter]]
    employees = list(_employees_queryset(group_ids, active))
    employee_ids = [employee.id for employee in employees]

    salary_map = {
        (salary.employee_id, salary.month): salary
        for salary in EmployeeSalary.objects.filter(
            employee_id__in=employee_ids,
            year=year,
            month__in=months,
        )
    }
    bonus_map: dict[tuple[int, int], EmployeeBonus] = {}
    for bonus in EmployeeBonus.objects.filter(
        employee_id__in=employee_ids,
        year=year,
        month__in=months,
    ).order_by("employee_id", "month", "-id"):
        bonus_map.setdefault((bonus.employee_id, bonus.month), bonus)

    compensation_type_ids = list(
        CompensationType.objects.filter(code__in=COMPENSATION_CODES).values_list("id", flat=True)
    )
    compensation_rows = EmployeeCompensation.objects.filter(
        employee_id__in=employee_ids,
        year=year,
        month__in=months,
        type_id__in=compensation_type_ids,
    ).select_related("type")

    compensation_map: dict[tuple[int, int, str], Decimal] = {}
    for compensation in compensation_rows:
        compensation_map[(compensation.employee_id, compensation.month, compensation.type.code)] = compensation.amount

    report_months = [
        {
            "month": month,
            "title": f"{MONTH_NAMES[month]} {year}",
        }
        for month in months
    ]

    rows: list[dict[str, object]] = []
    month_count = len(months)
    for employee in employees:
        row: dict[str, object] = {
            "employee_id": employee.id,
            "full_name": str(employee),
            "position": employee.position or "-",
        }
        total_income = ZERO

        for month in months:
            salary = salary_map.get((employee.id, month))
            bonus = bonus_map.get((employee.id, month))

            values = {
                "base_salary": salary.base_salary if salary else ZERO,
                "extra_salary": salary.extra_salary if salary else ZERO,
                "bonus": bonus.bonus if bonus else ZERO,
                "extra_bonus": bonus.extra_bonus if bonus else ZERO,
                "vacation": compensation_map.get((employee.id, month, "vacation"), ZERO),
                "sick_leave": compensation_map.get((employee.id, month, "sick_leave"), ZERO),
                "business_trip": compensation_map.get((employee.id, month, "business_trip"), ZERO),
            }

            for code, value in values.items():
                row[f"month_{month}_{code}"] = _format_amount(value)
                total_income += value

        average_income = total_income / month_count if month_count else ZERO
        row["average_income"] = _format_amount(average_income)
        rows.append(row)

    return rows, report_months


@transaction.atomic
def _save_employee_salary_rows(year: int, month: int, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0

    employee_ids = {int(row["employee_id"]) for row in rows if row.get("employee_id")}
    existing_employee_ids = set(
        Employee.objects.filter(id__in=employee_ids).values_list("id", flat=True)
    )
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

        bonus_year = _parse_year(row.get("bonus_year")) or year
        try:
            bonus_quarter = int(row.get("bonus_quarter") or _selected_quarter(month))
        except (TypeError, ValueError):
            bonus_quarter = _selected_quarter(month)
        if bonus_quarter not in QUARTER_MONTHS:
            bonus_quarter = _selected_quarter(month)

        bonus_defaults = {
            "year": year,
            "month": month,
            "bonus": _parse_amount(row.get("bonus")),
            "extra_bonus": _parse_amount(row.get("extra_bonus")),
            "bonus_year": bonus_year,
            "bonus_quarter": bonus_quarter,
        }
        bonus_id = row.get("bonus_id")
        if bonus_id:
            EmployeeBonus.objects.filter(id=bonus_id, employee_id=employee_id).update(**bonus_defaults)
        else:
            EmployeeBonus.objects.update_or_create(
                employee_id=employee_id,
                bonus_year=bonus_year,
                bonus_quarter=bonus_quarter,
                defaults=bonus_defaults,
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
    return render(
        request,
        "employees/salaries_monthly.html",
        {
            "form": form,
            "year_choices": YEAR_CHOICES,
        },
    )


@login_required
@ensure_csrf_cookie
def employee_report_view(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "employees/employee_report.html",
        {
            "year_choices": YEAR_CHOICES,
            "current_year": date.today().year,
        },
    )


@login_required
@require_GET
def employee_salaries_data_view(request: HttpRequest) -> JsonResponse:
    year, month = _validate_period(request.GET)
    if year is None or month is None:
        return JsonResponse(
            {"status": "error", "message": "Некорректный месяц или год."},
            status=400,
        )

    group_ids = _parse_group_ids(request.GET.getlist("group_ids") or request.GET.get("group_ids"))
    active = _parse_active_filter(request.GET.get("active"))

    return JsonResponse(
        {
            "status": "ok",
            "year": year,
            "month": month,
            "rows": _build_employee_salary_rows(year, month, group_ids, active),
        }
    )


@login_required
@require_GET
def employee_report_data_view(request: HttpRequest) -> JsonResponse:
    year = _parse_year(request.GET.get("year"))
    quarters = _parse_quarters(request.GET.getlist("quarters") or request.GET.get("quarters"))
    group_ids = _parse_group_ids(request.GET.getlist("group_ids") or request.GET.get("group_ids"))
    active = _parse_active_filter(request.GET.get("active"))

    if year is None:
        return JsonResponse(
            {"status": "error", "message": "Некорректный год."},
            status=400,
        )
    if not quarters:
        return JsonResponse(
            {"status": "error", "message": "Выберите хотя бы один квартал."},
            status=400,
        )

    rows, months = _build_employee_report_rows(year, quarters, group_ids, active)
    return JsonResponse(
        {
            "status": "ok",
            "year": year,
            "quarters": quarters,
            "months": months,
            "rows": rows,
        }
    )


@login_required
@require_GET
def employee_groups_data_view(request: HttpRequest) -> JsonResponse:
    groups = list(
        RedmineGroup.objects.filter(active=True)
        .values("id", "name")
        .order_by("name")
    )
    return JsonResponse({"status": "ok", "groups": groups})


@login_required
@require_GET
def employee_bonus_conflict_view(request: HttpRequest) -> JsonResponse:
    try:
        employee_id = int(request.GET.get("employee_id") or 0)
        bonus_year = int(request.GET.get("bonus_year") or 0)
        bonus_quarter = int(request.GET.get("bonus_quarter") or 0)
        payout_year = int(request.GET.get("payout_year") or 0)
        payout_month = int(request.GET.get("payout_month") or 0)
    except (TypeError, ValueError):
        return JsonResponse(
            {"status": "error", "message": "Некорректные данные премии."},
            status=400,
        )

    field = request.GET.get("field")
    if field not in {"bonus", "extra_bonus"}:
        return JsonResponse(
            {"status": "error", "message": "Некорректный тип премии."},
            status=400,
        )

    bonus_id = request.GET.get("bonus_id")
    queryset = EmployeeBonus.objects.filter(
        employee_id=employee_id,
        bonus_year=bonus_year,
        bonus_quarter=bonus_quarter,
    )
    if bonus_id:
        queryset = queryset.exclude(id=bonus_id)
    queryset = queryset.exclude(year=payout_year, month=payout_month)
    queryset = queryset.exclude(**{field: ZERO})

    existing_bonus = queryset.order_by("year", "month", "id").first()
    if existing_bonus is None:
        return JsonResponse({"status": "ok", "has_conflict": False})

    return JsonResponse(
        {
            "status": "ok",
            "has_conflict": True,
            "message": (
                f"Премия за {existing_bonus.bonus_quarter} кв. {existing_bonus.bonus_year} "
                f"уже создана в месяце {MONTH_NAMES.get(existing_bonus.month, existing_bonus.month)} "
                f"{existing_bonus.year}. Вы хотите изменить значения премии?"
            ),
            "existing": {
                "id": existing_bonus.id,
                "year": existing_bonus.year,
                "month": existing_bonus.month,
                "month_name": MONTH_NAMES.get(existing_bonus.month, str(existing_bonus.month)),
                "bonus_year": existing_bonus.bonus_year,
                "bonus_quarter": existing_bonus.bonus_quarter,
            },
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
