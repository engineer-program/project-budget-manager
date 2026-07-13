from django.contrib import admin
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import include, path, re_path
from django.contrib.staticfiles.views import serve

from apps.projects.views import project_report_page_view

from .views import healthcheck_view, home_view, section_placeholder_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "login/",
        LoginView.as_view(
            template_name="registration/login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("sync/redmine/", include("apps.redmine_sync.urls")),
    path("api/employees/", include("apps.employees.api_urls")),
    path("api/projects/", include("apps.projects.api_urls")),
    path("pages/", include("apps.employees.urls")),
    path("pages/projects/", include("apps.projects.urls")),
    path("pages/project-report/", project_report_page_view, name="project-report"),
    path(
        "pages/project-yearly-stats/",
        section_placeholder_view,
        {"title": "Статистика по проектам по годам"},
        name="project-yearly-stats",
    ),
    path(
        "pages/accounting-timesheet/",
        section_placeholder_view,
        {"title": "Табель для бухгалтерии"},
        name="accounting-timesheet",
    ),
    path("health/", healthcheck_view, name="healthcheck"),
    path("", home_view, name="home"),
]

urlpatterns += [
    re_path(r"^static/(?P<path>.*)$", serve),
]