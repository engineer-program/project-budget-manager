from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render


HOME_PAGES = [
    {"title": "З/П сотрудников", "url_name": "employees-salaries"},
    {"title": "Проекты", "url_name": "projects-list"},
    {"title": "Отчет по сотрудникам", "url_name": "employee-report"},
    {"title": "Отчет по проектам", "url_name": "project-report"},
    {"title": "Статистика по проектам по годам", "url_name": "project-yearly-stats"},
    {"title": "Табель для бухгалтерии", "url_name": "accounting-timesheet"},
]


@login_required
def home_view(request: HttpRequest) -> HttpResponse:
    return render(request, "home.html", {"pages": HOME_PAGES})


@login_required
def section_placeholder_view(request: HttpRequest, title: str) -> HttpResponse:
    return render(request, "section_placeholder.html", {"title": title})


def healthcheck_view(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})
