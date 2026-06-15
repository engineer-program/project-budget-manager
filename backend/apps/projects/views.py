import json
from decimal import Decimal, InvalidOperation
from json import JSONDecodeError
from typing import Any

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from apps.audit.models import ChangeLog
from apps.audit.services import log_change, serialize_instance
from apps.employees.models import Employee
from apps.finance.models import ExpenseCategory, ProjectExpense, ProjectIncome

from .models import Project

ZERO = Decimal("0.00")


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


@login_required
@ensure_csrf_cookie
def projects_page_view(request: HttpRequest) -> HttpResponse:
    return render(request, "projects/projects.html")


@login_required
@require_GET
def projects_data_view(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok", "rows": _project_tree_rows()})


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
