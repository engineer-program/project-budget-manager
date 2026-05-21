from django.contrib import admin
from django.urls import include, path

from .views import healthcheck_view, home_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("sync/redmine/", include("apps.redmine_sync.urls")),
    path("health/", healthcheck_view, name="healthcheck"),
    path("", home_view, name="home"),
]
