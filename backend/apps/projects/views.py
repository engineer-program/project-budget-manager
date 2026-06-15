import json
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from json import JSONDecodeError
from typing import Any

from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.db.models.functions import ExtractMonth, ExtractYear
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from apps.audit.models import ChangeLog
from apps.audit.services import log_change, serialize_instance
from apps.employees.forms import YEAR_CHOICES
from apps.employees.models import Employee, EmployeeBonus, EmployeeCompensation, EmployeeSalary
from apps.finance.models import ExpenseCategory, ProjectExpense, ProjectIncome
from apps.redmine_sync.models import RedmineTimeEntry
from apps.reference.models import CompensationType

from .models import Project

ZERO = Decimal("0.00")
REPORT_START_YEAR = 2019
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
PROJECT_REPORT_EXPENSE_FIELDS = (
    "base_salary_expense",
    "extra_salary_expense",
    "bonus_expense",
    "extra_bonus_expense",
    "vacation_expense",
    "sick_leave_expense",
    "business_trip_expense",
    "other_expense",
)


def _format_datetime(value) -> str:
    if value is None:
        return "-"
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime("%d.%m.%Y %H:%M")


def _format_amount(value: Decimal | None) -> str:
    return format((value or ZERO).quantize(Decimal("0.01")), "f")


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


def _month_period(year: int, month: int) -> tuple[date, date]:
    period_start = date(year, month, 1)
    if month == 12:
        period_end = date(year, 12, 31)
    else:
        period_end = date(year, month + 1, 1) - timedelta(days=1)
    return period_start, period_end


def _iter_month_keys(start_year: int, start_month: int, end_year: int, end_month: int) -> list[tuple[int, int]]:
    keys = []
    year = start_year
    month = start_month
    while (year, month) <= (end_year, end_month):
        keys.append((year, month))
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
    return keys


def _new_project_month_metrics() -> dict[str, Decimal]:
    return {
        "budget_start": ZERO,
        "income": ZERO,
        "base_salary_expense": ZERO,
        "extra_salary_expense": ZERO,
        "bonus_expense": ZERO,
        "extra_bonus_expense": ZERO,
        "vacation_expense": ZERO,
        "sick_leave_expense": ZERO,
        "business_trip_expense": ZERO,
        "other_expense": ZERO,
    }


def _project_report_month_title(year: int, month: int) -> str:
    return f"{MONTH_NAMES[month]} {year}"


def _project_report_expense_total(metrics: dict[str, Decimal]) -> Decimal:
    return sum((metrics[field] for field in PROJECT_REPORT_EXPENSE_FIELDS), ZERO)


def _find_opr_project_id() -> int | None:
    project = (
        Project.objects.filter(
            Q(project_number__iexact="ОПР")
            | Q(project_number__iexact="OPR")
            | Q(name__iexact="Общепроизводственные работы")
        )
        .order_by("id")
        .first()
    )
    return project.id if project else None


def _get_user_employee(request: HttpRequest) -> Employee | None:
    binding = getattr(request.user, "employee_binding", None)
    return binding.employee if binding else None


def _load_json_payload(request: HttpRequest) -> tuple[dict[str, Any] | None, JsonResponse | None]:
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (JSONDecodeError, UnicodeDecodeError):
        return None, JsonResponse({"status": "error", "message": "Некорректный JSON."}, status=400)

    if not isinstance(payload, dict):
        return None, JsonResponse({"status": "error", "message": "Некорректные данные."}, status=400)

    return payload, None


def _project_totals() -> tuple[dict[int, Decimal], dict[int, Decimal]]:
    income_totals = {
        item["project_id"]: item["total"] or ZERO
        for item in ProjectIncome.objects.values("project_id").annotate(total=Sum("amount"))
    }
    expense_totals = {
        item["project_id"]: item["total"] or ZERO
        for item in ProjectExpense.objects.values("project_id").annotate(total=Sum("amount"))
    }
    return income_totals, expense_totals


def _project_ids_with_descendants(project_id: int) -> set[int]:
    projects = Project.objects.values("id", "parent_project_id")
    children_by_parent: dict[int | None, list[int]] = {}
    for project in projects:
        children_by_parent.setdefault(project["parent_project_id"], []).append(project["id"])

    result = {project_id}
    stack = list(children_by_parent.get(project_id, []))
    while stack:
        child_id = stack.pop()
        if child_id in result:
            continue
        result.add(child_id)
        stack.extend(children_by_parent.get(child_id, []))

    return result


def _aggregate_project_values(project_id: int) -> dict[str, Decimal]:
    project_ids = _project_ids_with_descendants(project_id)
    start_budget = (
        Project.objects.filter(id__in=project_ids).aggregate(total=Sum("start_budget"))["total"] or ZERO
    )
    total_income = (
        ProjectIncome.objects.filter(project_id__in=project_ids).aggregate(total=Sum("amount"))["total"] or ZERO
    )
    total_expense = (
        ProjectExpense.objects.filter(project_id__in=project_ids).aggregate(total=Sum("amount"))["total"] or ZERO
    )
    return {
        "start_budget": start_budget,
        "total_income": total_income,
        "total_expense": total_expense,
        "budget_today": start_budget + total_income - total_expense,
    }


def _project_tree_rows() -> list[dict[str, Any]]:
    projects = list(Project.objects.all().select_related("project_manager"))
    income_totals, expense_totals = _project_totals()
    project_ids = {project.id for project in projects}
    children_by_parent: dict[int | None, list[Project]] = {}

    for project in projects:
        parent_id = project.parent_project_id if project.parent_project_id in project_ids else None
        children_by_parent.setdefault(parent_id, []).append(project)

    for siblings in children_by_parent.values():
        siblings.sort(key=lambda item: ((item.name or "").lower(), item.id))

    def build_node(project: Project, visited: set[int]) -> dict[str, Any]:
        own_income = income_totals.get(project.id, ZERO)
        own_expense = expense_totals.get(project.id, ZERO)
        aggregate_start_budget = project.start_budget
        aggregate_income = own_income
        aggregate_expense = own_expense
        child_rows = []

        if project.id not in visited:
            next_visited = {*visited, project.id}
            for child in children_by_parent.get(project.id, []):
                child_row = build_node(child, next_visited)
                child_rows.append(child_row)
                aggregate_start_budget += Decimal(child_row["start_budget"])
                aggregate_income += Decimal(child_row["total_income"])
                aggregate_expense += Decimal(child_row["total_expense"])

        budget_today = aggregate_start_budget + aggregate_income - aggregate_expense
        row = {
            "id": project.id,
            "name": project.name,
            "project_number": project.project_number,
            "name_1s": project.name_1s,
            "own_start_budget": _format_amount(project.start_budget),
            "start_budget": _format_amount(aggregate_start_budget),
            "budget_today": _format_amount(budget_today),
            "total_income": _format_amount(aggregate_income),
            "total_expense": _format_amount(aggregate_expense),
        }
        if child_rows:
            row["_children"] = child_rows
        return row

    return [build_node(project, set()) for project in children_by_parent.get(None, [])]


def _project_report_rows(year: int, quarters: list[int]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected_months = [month for quarter in quarters for month in QUARTER_MONTHS[quarter]]
    selected_keys = [(year, month) for month in selected_months]
    timeline_keys = _iter_month_keys(REPORT_START_YEAR, 1, year, max(selected_months))
    timeline_start, _ = _month_period(REPORT_START_YEAR, 1)
    _, timeline_end = _month_period(year, max(selected_months))

    projects = list(Project.objects.all())
    project_by_id = {project.id: project for project in projects}
    project_ids = set(project_by_id)
    children_by_parent: dict[int | None, list[Project]] = {}
    for project in projects:
        parent_id = project.parent_project_id if project.parent_project_id in project_ids else None
        children_by_parent.setdefault(parent_id, []).append(project)
    for siblings in children_by_parent.values():
        siblings.sort(key=lambda item: ((item.project_number or ""), (item.name_1s or ""), (item.name or "")))

    own_metrics: dict[int, dict[tuple[int, int], dict[str, Decimal]]] = {
        project.id: {key: _new_project_month_metrics() for key in timeline_keys}
        for project in projects
    }

    for item in (
        ProjectIncome.objects.filter(income_date__gte=timeline_start, income_date__lte=timeline_end)
        .annotate(report_year=ExtractYear("income_date"), report_month=ExtractMonth("income_date"))
        .values("project_id", "report_year", "report_month")
        .annotate(total=Sum("amount"))
    ):
        key = (item["report_year"], item["report_month"])
        project_id = item["project_id"]
        if project_id in own_metrics and key in own_metrics[project_id]:
            own_metrics[project_id][key]["income"] += item["total"] or ZERO

    salary_map = {
        (salary.employee_id, salary.year, salary.month): salary
        for salary in EmployeeSalary.objects.filter(year__gte=REPORT_START_YEAR, year__lte=year)
        if (salary.year, salary.month) in timeline_keys
    }
    employee_month_hours: dict[tuple[int, int, int], Decimal] = {}
    employee_project_month_hours: dict[tuple[int, int, int, int], Decimal] = {}
    for item in (
        RedmineTimeEntry.objects.filter(spent_on__gte=timeline_start, spent_on__lte=timeline_end)
        .annotate(report_year=ExtractYear("spent_on"), report_month=ExtractMonth("spent_on"))
        .values("user_id", "project_id", "report_year", "report_month")
        .annotate(total_hours=Sum("hours"))
    ):
        key = (item["report_year"], item["report_month"])
        project_id = item["project_id"]
        employee_id = item["user_id"]
        if project_id not in own_metrics or key not in own_metrics[project_id]:
            continue

        hours = item["total_hours"] or ZERO
        employee_month_key = (employee_id, key[0], key[1])
        employee_project_key = (employee_id, project_id, key[0], key[1])
        employee_month_hours[employee_month_key] = employee_month_hours.get(employee_month_key, ZERO) + hours
        employee_project_month_hours[employee_project_key] = (
            employee_project_month_hours.get(employee_project_key, ZERO) + hours
        )

    for (employee_id, project_id, item_year, item_month), project_hours in employee_project_month_hours.items():
        total_hours = employee_month_hours.get((employee_id, item_year, item_month), ZERO)
        if total_hours == ZERO:
            continue

        salary = salary_map.get((employee_id, item_year, item_month))
        if salary is None:
            continue

        ratio = project_hours / total_hours
        metrics = own_metrics[project_id][(item_year, item_month)]
        metrics["base_salary_expense"] += (salary.base_salary * ratio).quantize(Decimal("0.01"))
        metrics["extra_salary_expense"] += (salary.extra_salary * ratio).quantize(Decimal("0.01"))

    opr_project_id = _find_opr_project_id()
    if opr_project_id in own_metrics:
        opr_metrics = own_metrics[opr_project_id]
        for item in (
            EmployeeBonus.objects.filter(year__gte=REPORT_START_YEAR, year__lte=year)
            .values("year", "month")
            .annotate(total_bonus=Sum("bonus"), total_extra_bonus=Sum("extra_bonus"))
        ):
            key = (item["year"], item["month"])
            if key in opr_metrics:
                opr_metrics[key]["bonus_expense"] += item["total_bonus"] or ZERO
                opr_metrics[key]["extra_bonus_expense"] += item["total_extra_bonus"] or ZERO

        compensation_type_by_id = {
            compensation_type.id: compensation_type.code
            for compensation_type in CompensationType.objects.filter(
                code__in=("vacation", "sick_leave", "business_trip")
            )
        }
        compensation_field_by_code = {
            "vacation": "vacation_expense",
            "sick_leave": "sick_leave_expense",
            "business_trip": "business_trip_expense",
        }
        for item in (
            EmployeeCompensation.objects.filter(
                year__gte=REPORT_START_YEAR,
                year__lte=year,
                type_id__in=compensation_type_by_id,
            )
            .values("year", "month", "type_id")
            .annotate(total=Sum("amount"))
        ):
            key = (item["year"], item["month"])
            code = compensation_type_by_id.get(item["type_id"])
            field = compensation_field_by_code.get(code)
            if key in opr_metrics and field:
                opr_metrics[key][field] += item["total"] or ZERO

        for item in (
            ProjectExpense.objects.filter(
                project_id=opr_project_id,
                expense_date__gte=timeline_start,
                expense_date__lte=timeline_end,
            )
            .annotate(report_year=ExtractYear("expense_date"), report_month=ExtractMonth("expense_date"))
            .values("report_year", "report_month")
            .annotate(total=Sum("amount"))
        ):
            key = (item["report_year"], item["report_month"])
            if key in opr_metrics:
                opr_metrics[key]["other_expense"] += item["total"] or ZERO

    for project in projects:
        cumulative_income = ZERO
        cumulative_expense = ZERO
        for key in timeline_keys:
            metrics = own_metrics[project.id][key]
            metrics["budget_start"] = project.start_budget + cumulative_income - cumulative_expense
            cumulative_income += metrics["income"]
            cumulative_expense += _project_report_expense_total(metrics)

    report_months = [
        {
            "year": item_year,
            "month": month,
            "key": f"{item_year}_{month}",
            "title": _project_report_month_title(item_year, month),
        }
        for item_year, month in selected_keys
    ]

    def build_node(project: Project, visited: set[int]) -> dict[str, Any]:
        aggregate_start_budget = project.start_budget
        aggregate_months = {
            key: dict(own_metrics[project.id][key])
            for key in selected_keys
        }
        child_rows = []

        if project.id not in visited:
            next_visited = {*visited, project.id}
            for child in children_by_parent.get(project.id, []):
                child_row = build_node(child, next_visited)
                child_rows.append(child_row)
                aggregate_start_budget += Decimal(child_row["start_budget"])
                for key in selected_keys:
                    month_key = f"{key[0]}_{key[1]}"
                    for field in ("budget_start", "income", *PROJECT_REPORT_EXPENSE_FIELDS):
                        aggregate_months[key][field] += Decimal(child_row[f"month_{month_key}_{field}"])

        period_income = ZERO
        period_expense = ZERO
        row: dict[str, Any] = {
            "id": project.id,
            "project_number": project.project_number,
            "name_1s": project.name_1s,
            "name": project.name,
            "start_budget": _format_amount(aggregate_start_budget),
        }
        for key in selected_keys:
            month_key = f"{key[0]}_{key[1]}"
            metrics = aggregate_months[key]
            period_income += metrics["income"]
            period_expense += _project_report_expense_total(metrics)
            for field in ("budget_start", "income", *PROJECT_REPORT_EXPENSE_FIELDS):
                row[f"month_{month_key}_{field}"] = _format_amount(metrics[field])

        row["period_income"] = _format_amount(period_income)
        row["period_expense"] = _format_amount(period_expense)
        if child_rows:
            row["_children"] = child_rows
        return row

    return [build_node(project, set()) for project in children_by_parent.get(None, [])], report_months


@login_required
@ensure_csrf_cookie
def projects_page_view(request: HttpRequest) -> HttpResponse:
    return render(request, "projects/projects.html")


@login_required
@ensure_csrf_cookie
def project_report_page_view(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "projects/project_report.html",
        {
            "year_choices": YEAR_CHOICES,
            "current_year": date.today().year,
        },
    )


@login_required
@require_GET
def projects_data_view(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok", "rows": _project_tree_rows()})


@login_required
@require_GET
def project_report_data_view(request: HttpRequest) -> JsonResponse:
    year = _parse_year(request.GET.get("year"))
    quarters = _parse_quarters(request.GET.getlist("quarters") or request.GET.get("quarters"))

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

    rows, months = _project_report_rows(year, quarters)
    return JsonResponse(
        {
            "status": "ok",
            "year": year,
            "quarters": quarters,
            "months": months,
            "opr_project_found": _find_opr_project_id() is not None,
            "rows": rows,
        }
    )


@login_required
@require_GET
def project_detail_view(request: HttpRequest, project_id: int) -> JsonResponse:
    project = get_object_or_404(
        Project.objects.select_related("project_manager"),
        id=project_id,
    )
    aggregate_values = _aggregate_project_values(project.id)

    return JsonResponse(
        {
            "status": "ok",
            "project": {
                "id": project.id,
                "name": project.name,
                "project_number": project.project_number,
                "name_1s": project.name_1s,
                "name_sanda": project.name_sanda,
                "lead_department": project.lead_department,
                "project_manager": str(project.project_manager) if project.project_manager else "-",
                "redmine_created_on": _format_datetime(project.redmine_created_on),
                "has_subprojects": project.subprojects.exists(),
                "own_start_budget": _format_amount(project.start_budget),
                "start_budget": _format_amount(aggregate_values["start_budget"]),
                "budget_today": _format_amount(aggregate_values["budget_today"]),
            },
        }
    )


@login_required
@require_POST
def project_budget_update_view(request: HttpRequest, project_id: int) -> JsonResponse:
    project = get_object_or_404(Project, id=project_id)
    payload, error_response = _load_json_payload(request)
    if error_response:
        return error_response

    before_data = serialize_instance(project, ["start_budget", "budget_updated_by_id"])
    project.start_budget = _parse_amount(payload.get("start_budget"))
    project.budget_updated_by = request.user
    after_data = serialize_instance(project, ["start_budget", "budget_updated_by_id"])
    if before_data != after_data:
        project.save(update_fields=["start_budget", "budget_updated_by", "updated_at"])
        log_change(
            user=request.user,
            entity=project,
            action=ChangeLog.ACTION_UPDATE,
            before_data=before_data,
            after_data=after_data,
        )
    return JsonResponse({"status": "ok", "start_budget": _format_amount(project.start_budget)})


@login_required
@require_GET
def project_incomes_view(request: HttpRequest, project_id: int) -> JsonResponse:
    project = get_object_or_404(Project, id=project_id)
    project_ids = _project_ids_with_descendants(project.id)
    rows = []
    for income in (
        ProjectIncome.objects.filter(project_id__in=project_ids)
        .select_related("created_by", "project")
        .order_by("-income_date", "-id")
    ):
        rows.append(
            {
                "id": income.id,
                "project_id": income.project_id,
                "project_name": income.project.name,
                "article": income.article,
                "amount": _format_amount(income.amount),
                "date": income.income_date.isoformat(),
                "description": income.description,
                "author": income.created_by.get_username() if income.created_by else "-",
            }
        )
    return JsonResponse({"status": "ok", "rows": rows})


@login_required
@require_POST
def project_income_create_view(request: HttpRequest, project_id: int) -> JsonResponse:
    project = get_object_or_404(Project, id=project_id)
    employee = _get_user_employee(request)
    if employee is None:
        return JsonResponse(
            {"status": "error", "message": "Пользователь не привязан к сотруднику."},
            status=400,
        )

    payload, error_response = _load_json_payload(request)
    if error_response:
        return error_response

    income = ProjectIncome.objects.create(
        project=project,
        article=str(payload.get("article") or "").strip(),
        amount=_parse_amount(payload.get("amount")),
        responsible_employee=employee,
        description=str(payload.get("description") or "").strip(),
        income_date=payload.get("date"),
        created_by=request.user,
    )
    log_change(
        user=request.user,
        entity=income,
        action=ChangeLog.ACTION_CREATE,
        before_data=None,
        after_data=serialize_instance(income),
    )
    return JsonResponse({"status": "ok"})


@login_required
@require_POST
def project_income_delete_view(request: HttpRequest, project_id: int, income_id: int) -> JsonResponse:
    project = get_object_or_404(Project, id=project_id)
    project_ids = _project_ids_with_descendants(project.id)
    income = get_object_or_404(ProjectIncome, id=income_id, project_id__in=project_ids)
    before_data = serialize_instance(income)
    log_change(
        user=request.user,
        entity=income,
        action=ChangeLog.ACTION_DELETE,
        before_data=before_data,
        after_data=None,
    )
    income.delete()
    return JsonResponse({"status": "ok"})


@login_required
@require_POST
def project_expense_create_view(request: HttpRequest, project_id: int) -> JsonResponse:
    project = get_object_or_404(Project, id=project_id)
    employee = _get_user_employee(request)
    if employee is None:
        return JsonResponse(
            {"status": "error", "message": "Пользователь не привязан к сотруднику."},
            status=400,
        )

    payload, error_response = _load_json_payload(request)
    if error_response:
        return error_response

    category_name = str(payload.get("article") or "").strip()
    if not category_name:
        return JsonResponse({"status": "error", "message": "Укажите статью расхода."}, status=400)

    category, _ = ExpenseCategory.objects.get_or_create(name=category_name)
    expense = ProjectExpense.objects.create(
        project=project,
        category=category,
        amount=_parse_amount(payload.get("amount")),
        responsible_employee=employee,
        description=str(payload.get("description") or "").strip(),
        expense_date=payload.get("date"),
        created_by=request.user,
    )
    log_change(
        user=request.user,
        entity=expense,
        action=ChangeLog.ACTION_CREATE,
        before_data=None,
        after_data=serialize_instance(expense),
    )
    return JsonResponse({"status": "ok"})
