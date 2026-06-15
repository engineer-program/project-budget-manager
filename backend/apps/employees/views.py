import json
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from json import JSONDecodeError
from typing import Any

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from apps.audit.models import ChangeLog
from apps.audit.services import log_change, serialize_instance
from apps.reference.models import CompensationType

from .forms import EmployeeSalaryPeriodForm, YEAR_CHOICES
from .models import Employee, EmployeeBonus, EmployeeCompensation, EmployeeSalary, RedmineGroup

ZERO = Decimal("0.00")
COMPENSATION_CODES = ("vacation", "sick_leave", "business_trip")
CLEARABLE_SALARY_COLUMNS = {
    "base_salary",
    "extra_salary",
    "bonus",
    "extra_bonus",
    *COMPENSATION_CODES,
}
COPYABLE_SALARY_COLUMNS = {
    "base_salary",
    "extra_salary",
    "bonus",
    "extra_bonus",
    *COMPENSATION_CODES,
}
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


def _parse_employee_ids(raw_values: list[Any] | None) -> list[int]:
    if not isinstance(raw_values, list):
        return []

    employee_ids: list[int] = []
    for raw_value in raw_values:
        try:
            employee_id = int(raw_value)
        except (TypeError, ValueError):
            continue
        if employee_id > 0 and employee_id not in employee_ids:
            employee_ids.append(employee_id)
    return employee_ids


def _parse_active_filter(raw_value: Any) -> str:
    if raw_value in (None, ""):
        return "active"
    value = str(raw_value).strip().lower()
    if value in {"all", "*"}:
        return "all"
    if value in {"1", "true", "active"}:
        return "active"
    if value in {"0", "false", "blocked"}:
        return "blocked"
    return "active"


def _month_period(year: int, month: int) -> tuple[date, date]:
    period_start = date(year, month, 1)
    if month == 12:
        period_end = date(year, 12, 31)
    else:
        period_end = date(year, month + 1, 1) - timedelta(days=1)
    return period_start, period_end


def _employees_queryset(
    group_ids: list[int] | None = None,
    status: str = "active",
    period_start: date | None = None,
    period_end: date | None = None,
):
    queryset = Employee.objects.all()
    if status != "all" and period_start is not None and period_end is not None:
        active_for_period = (
            Q(active=True)
            & (Q(employment_date__isnull=True) | Q(employment_date__lte=period_end))
            & (Q(dismissal_date__isnull=True) | Q(dismissal_date__gte=period_start))
        )
        if status == "active":
            queryset = queryset.filter(active_for_period)
        elif status == "blocked":
            queryset = queryset.exclude(active_for_period)
    if group_ids:
        queryset = queryset.filter(group_memberships__group_id__in=group_ids).distinct()
    return queryset


def _build_employee_salary_rows(
    year: int,
    month: int,
    group_ids: list[int] | None = None,
    status: str = "active",
) -> list[dict[str, object]]:
    period_start, period_end = _month_period(year, month)
    employees = list(_employees_queryset(group_ids, status, period_start, period_end))

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
    status: str = "active",
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    months = [month for quarter in quarters for month in QUARTER_MONTHS[quarter]]
    period_start, _ = _month_period(year, min(months))
    _, period_end = _month_period(year, max(months))
    employees = list(_employees_queryset(group_ids, status, period_start, period_end))
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


def _save_with_audit(instance, user, update_fields: list[str], before_data: dict[str, Any]) -> None:
    audited_fields = [field for field in update_fields if field != "updated_at"]
    after_data = serialize_instance(instance, audited_fields)
    if before_data == after_data:
        return

    instance.save(update_fields=update_fields)
    log_change(
        user=user,
        entity=instance,
        action=ChangeLog.ACTION_UPDATE,
        before_data=before_data,
        after_data=after_data,
    )


def _log_created(instance, user) -> None:
    log_change(
        user=user,
        entity=instance,
        action=ChangeLog.ACTION_CREATE,
        before_data=None,
        after_data=serialize_instance(instance),
    )


def _bonus_payload(bonus: EmployeeBonus) -> dict[str, object]:
    return {
        "id": bonus.id,
        "employee_id": bonus.employee_id,
        "year": bonus.year,
        "month": bonus.month,
        "bonus": _format_amount(bonus.bonus),
        "extra_bonus": _format_amount(bonus.extra_bonus),
        "bonus_year": bonus.bonus_year,
        "bonus_quarter": bonus.bonus_quarter,
    }


@transaction.atomic
def _clear_employee_salary_columns(
    *,
    year: int,
    month: int,
    employee_ids: list[int],
    columns: set[str],
    user,
) -> int:
    if not employee_ids or not columns:
        return 0

    changed_count = 0

    salary_fields = columns & {"base_salary", "extra_salary"}
    if salary_fields:
        salary_rows = EmployeeSalary.objects.filter(
            employee_id__in=employee_ids,
            year=year,
            month=month,
        )
        for salary in salary_rows:
            before_data = serialize_instance(salary, list(salary_fields))
            changed = False
            update_fields = ["updated_at"]
            for field_name in salary_fields:
                if getattr(salary, field_name) != ZERO:
                    setattr(salary, field_name, ZERO)
                    update_fields.append(field_name)
                    changed = True
            if changed:
                _save_with_audit(salary, user, update_fields, before_data)
                changed_count += 1

    bonus_fields = columns & {"bonus", "extra_bonus"}
    if bonus_fields:
        bonus_rows = EmployeeBonus.objects.filter(
            employee_id__in=employee_ids,
            year=year,
            month=month,
        )
        for bonus in bonus_rows:
            before_data = serialize_instance(bonus)
            changed = False
            for field_name in bonus_fields:
                if getattr(bonus, field_name) != ZERO:
                    setattr(bonus, field_name, ZERO)
                    changed = True
            if not changed:
                continue

            if bonus.bonus == ZERO and bonus.extra_bonus == ZERO:
                log_change(
                    user=user,
                    entity=bonus,
                    action=ChangeLog.ACTION_DELETE,
                    before_data=before_data,
                    after_data=None,
                )
                bonus.delete()
            else:
                bonus.save(update_fields=[*bonus_fields, "updated_at"])
                log_change(
                    user=user,
                    entity=bonus,
                    action=ChangeLog.ACTION_UPDATE,
                    before_data=before_data,
                    after_data=serialize_instance(bonus),
                )
            changed_count += 1

    compensation_columns = columns & set(COMPENSATION_CODES)
    if compensation_columns:
        compensation_types = {
            item.code: item.id
            for item in CompensationType.objects.filter(code__in=compensation_columns)
        }
        type_id_to_code = {type_id: code for code, type_id in compensation_types.items()}
        compensation_rows = EmployeeCompensation.objects.filter(
            employee_id__in=employee_ids,
            year=year,
            month=month,
            type_id__in=compensation_types.values(),
        )
        for compensation in compensation_rows:
            if compensation.amount == ZERO:
                continue

            code = type_id_to_code.get(compensation.type_id)
            before_data = serialize_instance(compensation, ["amount"])
            compensation.amount = ZERO
            _save_with_audit(compensation, user, ["amount", "updated_at"], before_data)
            if code:
                changed_count += 1

    return changed_count


def _target_columns_have_values(
    *,
    year: int,
    month: int,
    employee_ids: list[int],
    columns: set[str],
) -> bool:
    salary_fields = columns & {"base_salary", "extra_salary"}
    if salary_fields:
        salary_query = Q()
        for field_name in salary_fields:
            salary_query |= ~Q(**{field_name: ZERO})
        if salary_query and EmployeeSalary.objects.filter(
            salary_query,
            employee_id__in=employee_ids,
            year=year,
            month=month,
        ).exists():
            return True

    bonus_fields = columns & {"bonus", "extra_bonus"}
    if bonus_fields:
        bonus_query = Q()
        for field_name in bonus_fields:
            bonus_query |= ~Q(**{field_name: ZERO})
        if bonus_query and EmployeeBonus.objects.filter(
            bonus_query,
            employee_id__in=employee_ids,
            year=year,
            month=month,
        ).exists():
            return True

    compensation_columns = columns & set(COMPENSATION_CODES)
    if compensation_columns:
        type_ids = CompensationType.objects.filter(
            code__in=compensation_columns,
        ).values_list("id", flat=True)
        if EmployeeCompensation.objects.filter(
            employee_id__in=employee_ids,
            year=year,
            month=month,
            type_id__in=type_ids,
        ).exclude(amount=ZERO).exists():
            return True

    return False


@transaction.atomic
def _copy_employee_salary_columns(
    *,
    source_year: int,
    source_month: int,
    target_year: int,
    target_month: int,
    employee_ids: list[int],
    columns: set[str],
    bonus_year: int | None = None,
    bonus_quarter: int | None = None,
    user,
) -> int:
    if source_year == target_year and source_month == target_month:
        raise ValueError("Выберите месяц-источник, отличный от текущего месяца.")

    if _target_columns_have_values(
        year=target_year,
        month=target_month,
        employee_ids=employee_ids,
        columns=columns,
    ):
        raise ValueError(
            "В текущем месяце уже есть заполненные значения в одном из выбранных столбцов!"
        )

    changed_count = 0

    bonus_fields = columns & {"bonus", "extra_bonus"}
    if bonus_fields:
        if bonus_year is None or bonus_quarter is None or bonus_quarter not in QUARTER_MONTHS:
            raise ValueError("Выберите корректный квартал и год премии.")

        if EmployeeBonus.objects.filter(
            employee_id__in=employee_ids,
            bonus_year=bonus_year,
            bonus_quarter=bonus_quarter,
        ).exists():
            raise ValueError(
                f"У одного или нескольких сотрудников уже есть премия за {bonus_quarter} кв. {bonus_year}. "
                "Копирование отменено."
            )

        source_bonus_map: dict[int, EmployeeBonus] = {}
        for bonus in EmployeeBonus.objects.filter(
            employee_id__in=employee_ids,
            year=source_year,
            month=source_month,
        ).order_by("employee_id", "-id"):
            source_bonus_map.setdefault(bonus.employee_id, bonus)

        for employee_id in employee_ids:
            source_bonus = source_bonus_map.get(employee_id)
            values = {
                field_name: getattr(source_bonus, field_name, ZERO) if source_bonus else ZERO
                for field_name in bonus_fields
            }
            if all(value == ZERO for value in values.values()):
                continue

            target_bonus = EmployeeBonus(
                employee_id=employee_id,
                year=target_year,
                month=target_month,
                bonus_year=bonus_year,
                bonus_quarter=bonus_quarter,
                bonus=values.get("bonus", ZERO),
                extra_bonus=values.get("extra_bonus", ZERO),
            )
            target_bonus.save()
            _log_created(target_bonus, user)
            changed_count += 1

    salary_fields = columns & {"base_salary", "extra_salary"}
    if salary_fields:
        source_salary_map = {
            salary.employee_id: salary
            for salary in EmployeeSalary.objects.filter(
                employee_id__in=employee_ids,
                year=source_year,
                month=source_month,
            )
        }

        for employee_id in employee_ids:
            source_salary = source_salary_map.get(employee_id)
            values = {
                field_name: getattr(source_salary, field_name, ZERO) if source_salary else ZERO
                for field_name in salary_fields
            }
            if all(value == ZERO for value in values.values()):
                continue

            target_salary, created = EmployeeSalary.objects.get_or_create(
                employee_id=employee_id,
                year=target_year,
                month=target_month,
            )
            before_data = serialize_instance(target_salary, list(salary_fields)) if not created else None
            for field_name, value in values.items():
                setattr(target_salary, field_name, value)

            if created:
                target_salary.save()
                _log_created(target_salary, user)
            else:
                _save_with_audit(
                    target_salary,
                    user,
                    [*salary_fields, "updated_at"],
                    before_data,
                )
            changed_count += 1

    compensation_columns = columns & set(COMPENSATION_CODES)
    if compensation_columns:
        compensation_types = {
            item.code: item
            for item in CompensationType.objects.filter(code__in=compensation_columns)
        }
        source_compensation_map = {
            (compensation.employee_id, compensation.type.code): compensation.amount
            for compensation in EmployeeCompensation.objects.filter(
                employee_id__in=employee_ids,
                year=source_year,
                month=source_month,
                type_id__in=[item.id for item in compensation_types.values()],
            ).select_related("type")
        }

        for employee_id in employee_ids:
            for code, compensation_type in compensation_types.items():
                amount = source_compensation_map.get((employee_id, code), ZERO)
                if amount == ZERO:
                    continue

                target_compensation, created = EmployeeCompensation.objects.get_or_create(
                    employee_id=employee_id,
                    year=target_year,
                    month=target_month,
                    type=compensation_type,
                )
                before_data = serialize_instance(target_compensation, ["amount"]) if not created else None
                target_compensation.amount = amount

                if created:
                    target_compensation.save()
                    _log_created(target_compensation, user)
                else:
                    _save_with_audit(
                        target_compensation,
                        user,
                        ["amount", "updated_at"],
                        before_data,
                    )
                changed_count += 1

    return changed_count


@transaction.atomic
def _save_employee_salary_rows(year: int, month: int, rows: list[dict[str, Any]], user) -> int:
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

        salary, created = EmployeeSalary.objects.get_or_create(
            employee_id=employee_id,
            year=year,
            month=month,
        )
        salary_before = serialize_instance(salary, ["base_salary", "extra_salary"]) if not created else None
        salary.base_salary = _parse_amount(row.get("base_salary"))
        salary.extra_salary = _parse_amount(row.get("extra_salary"))
        if created:
            salary.save()
            _log_created(salary, user)
        else:
            _save_with_audit(salary, user, ["base_salary", "extra_salary", "updated_at"], salary_before)

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
            bonus = EmployeeBonus.objects.filter(id=bonus_id, employee_id=employee_id).first()
            if bonus is not None:
                bonus_before = serialize_instance(
                    bonus,
                    ["year", "month", "bonus", "extra_bonus", "bonus_year", "bonus_quarter"],
                )
                for field_name, value in bonus_defaults.items():
                    setattr(bonus, field_name, value)
                _save_with_audit(
                    bonus,
                    user,
                    ["year", "month", "bonus", "extra_bonus", "bonus_year", "bonus_quarter", "updated_at"],
                    bonus_before,
                )
            else:
                bonus, created = EmployeeBonus.objects.update_or_create(
                    employee_id=employee_id,
                    bonus_year=bonus_year,
                    bonus_quarter=bonus_quarter,
                    defaults=bonus_defaults,
                )
                if created:
                    _log_created(bonus, user)
        else:
            bonus, created = EmployeeBonus.objects.get_or_create(
                employee_id=employee_id,
                bonus_year=bonus_year,
                bonus_quarter=bonus_quarter,
                defaults=bonus_defaults,
            )
            bonus_before = (
                serialize_instance(bonus, ["year", "month", "bonus", "extra_bonus", "bonus_year", "bonus_quarter"])
                if not created
                else None
            )
            for field_name, value in bonus_defaults.items():
                setattr(bonus, field_name, value)
            if created:
                bonus.save()
                _log_created(bonus, user)
            else:
                _save_with_audit(
                    bonus,
                    user,
                    ["year", "month", "bonus", "extra_bonus", "bonus_year", "bonus_quarter", "updated_at"],
                    bonus_before,
                )

        for code in COMPENSATION_CODES:
            compensation_type = compensation_types.get(code)
            if compensation_type is None:
                continue

            compensation, created = EmployeeCompensation.objects.get_or_create(
                employee_id=employee_id,
                year=year,
                month=month,
                type=compensation_type,
            )
            compensation_before = serialize_instance(compensation, ["amount"]) if not created else None
            compensation.amount = _parse_amount(row.get(code))
            if created:
                compensation.save()
                _log_created(compensation, user)
            else:
                _save_with_audit(compensation, user, ["amount", "updated_at"], compensation_before)

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
    status = _parse_active_filter(request.GET.get("active"))

    return JsonResponse(
        {
            "status": "ok",
            "year": year,
            "month": month,
            "rows": _build_employee_salary_rows(year, month, group_ids, status),
        }
    )


@login_required
@require_GET
def employee_report_data_view(request: HttpRequest) -> JsonResponse:
    year = _parse_year(request.GET.get("year"))
    quarters = _parse_quarters(request.GET.getlist("quarters") or request.GET.get("quarters"))
    group_ids = _parse_group_ids(request.GET.getlist("group_ids") or request.GET.get("group_ids"))
    status = _parse_active_filter(request.GET.get("active"))

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

    rows, months = _build_employee_report_rows(year, quarters, group_ids, status)
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
def employee_bonus_save_view(request: HttpRequest) -> JsonResponse:
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {"status": "error", "message": "Некорректный JSON."},
            status=400,
        )

    year, month = _validate_period(
        {
            "year": payload.get("payout_year"),
            "month": payload.get("payout_month"),
        }
    )
    if year is None or month is None:
        return JsonResponse(
            {"status": "error", "message": "Некорректный месяц выплаты премии."},
            status=400,
        )

    field = payload.get("field")
    if field not in {"bonus", "extra_bonus"}:
        return JsonResponse(
            {"status": "error", "message": "Некорректный тип премии."},
            status=400,
        )

    try:
        employee_id = int(payload.get("employee_id") or 0)
        bonus_quarter = int(payload.get("bonus_quarter") or 0)
    except (TypeError, ValueError):
        return JsonResponse(
            {"status": "error", "message": "Некорректные данные премии."},
            status=400,
        )

    bonus_year = _parse_year(payload.get("bonus_year"))
    if (
        employee_id <= 0
        or bonus_year is None
        or bonus_quarter not in QUARTER_MONTHS
        or not Employee.objects.filter(id=employee_id).exists()
    ):
        return JsonResponse(
            {"status": "error", "message": "Некорректные данные премии."},
            status=400,
        )

    try:
        bonus_id = int(payload.get("bonus_id") or 0)
    except (TypeError, ValueError):
        bonus_id = 0

    amount = _parse_amount(payload.get("amount"))
    confirm_existing = bool(payload.get("confirm_existing"))
    existing_bonus = EmployeeBonus.objects.filter(
        employee_id=employee_id,
        bonus_year=bonus_year,
        bonus_quarter=bonus_quarter,
    ).first()
    source_bonus = (
        EmployeeBonus.objects.filter(id=bonus_id, employee_id=employee_id).first()
        if bonus_id
        else None
    )
    existing_is_current_month = (
        existing_bonus is not None
        and existing_bonus.year == year
        and existing_bonus.month == month
    )
    existing_has_bonus_values = (
        existing_bonus is not None
        and (existing_bonus.bonus != ZERO or existing_bonus.extra_bonus != ZERO)
    )

    if (
        existing_bonus is not None
        and existing_bonus.id != bonus_id
        and existing_has_bonus_values
        and not existing_is_current_month
        and not confirm_existing
    ):
        return JsonResponse(
            {
                "status": "conflict",
                "message": (
                    f"За {existing_bonus.bonus_quarter} кв. {existing_bonus.bonus_year} у сотрудника уже есть "
                    f"запись премий в месяце {MONTH_NAMES.get(existing_bonus.month, existing_bonus.month)} "
                    f"{existing_bonus.year}:\n"
                    f"Премия кв.: {_format_amount(existing_bonus.bonus)}₽.\n"
                    f"Доп. премия: {_format_amount(existing_bonus.extra_bonus)}₽.\n"
                    f"Если продолжить, запись премий будет перенесена в текущий месяц "
                    f"{MONTH_NAMES.get(month, month)} {year}.\nУже заполненные значения сохранятся, "
                    "а редактируемое значение будет обновлено.\nПродолжить?"
                ),
                "existing": _bonus_payload(existing_bonus),
            }
        )

    with transaction.atomic():
        if existing_bonus is not None and existing_bonus.id != bonus_id:
            bonus = existing_bonus
        elif source_bonus is not None:
            bonus = source_bonus
        else:
            bonus = None

        if bonus is None:
            bonus = EmployeeBonus(
                employee_id=employee_id,
                year=year,
                month=month,
                bonus_year=bonus_year,
                bonus_quarter=bonus_quarter,
                bonus=ZERO,
                extra_bonus=ZERO,
            )
            setattr(bonus, field, amount)
            bonus.save()
            _log_created(bonus, request.user)
        else:
            before_data = serialize_instance(
                bonus,
                ["year", "month", "bonus", "extra_bonus", "bonus_year", "bonus_quarter"],
            )
            bonus.year = year
            bonus.month = month
            bonus.bonus_year = bonus_year
            bonus.bonus_quarter = bonus_quarter
            setattr(bonus, field, amount)
            _save_with_audit(
                bonus,
                request.user,
                ["year", "month", field, "bonus_year", "bonus_quarter", "updated_at"],
                before_data,
            )

        if source_bonus is not None and source_bonus.id != bonus.id:
            before_data = serialize_instance(source_bonus)
            setattr(source_bonus, field, ZERO)
            if source_bonus.bonus == ZERO and source_bonus.extra_bonus == ZERO:
                log_change(
                    user=request.user,
                    entity=source_bonus,
                    action=ChangeLog.ACTION_DELETE,
                    before_data=before_data,
                    after_data=None,
                )
                source_bonus.delete()
            else:
                source_bonus.save(update_fields=[field, "updated_at"])
                log_change(
                    user=request.user,
                    entity=source_bonus,
                    action=ChangeLog.ACTION_UPDATE,
                    before_data=before_data,
                    after_data=serialize_instance(source_bonus),
                )

    return JsonResponse({"status": "ok", "bonus": _bonus_payload(bonus)})


@login_required
@require_POST
def employee_bonus_delete_view(request: HttpRequest) -> JsonResponse:
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {"status": "error", "message": "Некорректный JSON."},
            status=400,
        )

    try:
        bonus_id = int(payload.get("bonus_id") or 0)
    except (TypeError, ValueError):
        return JsonResponse(
            {"status": "error", "message": "Некорректная запись премии."},
            status=400,
        )
    field = payload.get("field")
    if field not in {"bonus", "extra_bonus"}:
        return JsonResponse(
            {"status": "error", "message": "Некорректный тип премии."},
            status=400,
        )

    bonus = EmployeeBonus.objects.filter(id=bonus_id).first()
    if bonus is None:
        return JsonResponse({"status": "ok"})

    before_data = serialize_instance(bonus)
    setattr(bonus, field, ZERO)
    if bonus.bonus == ZERO and bonus.extra_bonus == ZERO:
        log_change(
            user=request.user,
            entity=bonus,
            action=ChangeLog.ACTION_DELETE,
            before_data=before_data,
            after_data=None,
        )
        bonus.delete()
        return JsonResponse({"status": "ok", "deleted_record": True})

    bonus.save(update_fields=[field, "updated_at"])
    log_change(
        user=request.user,
        entity=bonus,
        action=ChangeLog.ACTION_UPDATE,
        before_data=before_data,
        after_data=serialize_instance(bonus),
    )
    return JsonResponse({"status": "ok", "deleted_record": False})


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

    saved = _save_employee_salary_rows(year, month, rows, request.user)
    return JsonResponse({"status": "ok", "saved": saved})


@login_required
@require_POST
def employee_salaries_clear_columns_view(request: HttpRequest) -> JsonResponse:
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {"status": "error", "message": "Некорректный JSON."},
            status=400,
        )

    year, month = _validate_period(payload)
    employee_ids = _parse_employee_ids(payload.get("employee_ids"))
    raw_columns = payload.get("columns")
    columns = set(raw_columns) if isinstance(raw_columns, list) else set()
    invalid_columns = columns - CLEARABLE_SALARY_COLUMNS

    if year is None or month is None or not employee_ids or not columns or invalid_columns:
        return JsonResponse(
            {"status": "error", "message": "Некорректные данные для очистки столбцов."},
            status=400,
        )

    cleared = _clear_employee_salary_columns(
        year=year,
        month=month,
        employee_ids=employee_ids,
        columns=columns,
        user=request.user,
    )
    return JsonResponse({"status": "ok", "cleared": cleared})


@login_required
@require_POST
def employee_salaries_copy_columns_view(request: HttpRequest) -> JsonResponse:
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {"status": "error", "message": "Некорректный JSON."},
            status=400,
        )

    target_year, target_month = _validate_period(payload)
    source_year, source_month = _validate_period(
        {
            "year": payload.get("source_year"),
            "month": payload.get("source_month"),
        }
    )
    employee_ids = _parse_employee_ids(payload.get("employee_ids"))
    raw_columns = payload.get("columns")
    columns = set(raw_columns) if isinstance(raw_columns, list) else set()
    invalid_columns = columns - COPYABLE_SALARY_COLUMNS
    bonus_columns = columns & {"bonus", "extra_bonus"}
    bonus_year = _parse_year(payload.get("bonus_year")) if bonus_columns else None
    try:
        bonus_quarter = int(payload.get("bonus_quarter") or 0) if bonus_columns else None
    except (TypeError, ValueError):
        bonus_quarter = None

    if (
        target_year is None
        or target_month is None
        or source_year is None
        or source_month is None
        or not employee_ids
        or not columns
        or invalid_columns
        or (bonus_columns and (bonus_year is None or bonus_quarter not in QUARTER_MONTHS))
    ):
        return JsonResponse(
            {"status": "error", "message": "Некорректные данные для копирования."},
            status=400,
        )

    try:
        copied = _copy_employee_salary_columns(
            source_year=source_year,
            source_month=source_month,
            target_year=target_year,
            target_month=target_month,
            employee_ids=employee_ids,
            columns=columns,
            bonus_year=bonus_year,
            bonus_quarter=bonus_quarter,
            user=request.user,
        )
    except ValueError as exc:
        return JsonResponse(
            {"status": "error", "message": str(exc)},
            status=400,
        )

    return JsonResponse({"status": "ok", "copied": copied})
