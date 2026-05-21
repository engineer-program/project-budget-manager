from django.urls import path

from .views import (
    redmine_sync_status_view,
    run_full_sync_view,
    run_incremental_sync_view,
    run_window_sync_view,
)


app_name = "redmine_sync"

urlpatterns = [
    path("status/", redmine_sync_status_view, name="status"),
    path("incremental/", run_incremental_sync_view, name="incremental"),
    path("window/", run_window_sync_view, name="window"),
    path("full/", run_full_sync_view, name="full"),
]
