from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from apps.redmine_sync.models import SyncState
from apps.redmine_sync.services.sync_service import SyncService


def _can_run_full_sync(request: HttpRequest) -> bool:
    user = request.user
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.is_staff or user.groups.filter(name="admin").exists()


def _serialize_sync_state(entity_code: str) -> dict[str, object] | None:
    state = (
        SyncState.objects.filter(entity_code=entity_code)
        .values(
            "entity_code",
            "status",
            "cursor_int",
            "last_synced_at",
            "last_success_at",
            "message",
        )
        .first()
    )
    return state


@login_required
@require_POST
def run_incremental_sync_view(request: HttpRequest) -> JsonResponse:
    service = SyncService()
    details = service.run(
        trigger_source="ui-incremental",
        time_entries_mode=SyncService.TIME_ENTRIES_MODE_INCREMENTAL,
        chunk_size=SyncService.DEFAULT_CHUNK_SIZE,
    )
    return JsonResponse(
        {
            "status": "ok",
            "mode": SyncService.TIME_ENTRIES_MODE_INCREMENTAL,
            "details": details,
        }
    )


@login_required
@require_POST
def run_window_sync_view(request: HttpRequest) -> JsonResponse:
    service = SyncService()
    details = service.run(
        trigger_source="ui-window",
        time_entries_mode=SyncService.TIME_ENTRIES_MODE_WINDOW,
        chunk_size=SyncService.DEFAULT_CHUNK_SIZE,
        window_days=SyncService.DEFAULT_WINDOW_DAYS,
    )
    return JsonResponse(
        {
            "status": "ok",
            "mode": SyncService.TIME_ENTRIES_MODE_WINDOW,
            "details": details,
        }
    )


@login_required
@require_POST
def run_full_sync_view(request: HttpRequest) -> JsonResponse:
    if not _can_run_full_sync(request):
        return JsonResponse(
            {
                "status": "forbidden",
                "message": "Full sync is available only for administrators.",
            },
            status=403,
        )

    service = SyncService()
    details = service.run(
        trigger_source="ui-full",
        time_entries_mode=SyncService.TIME_ENTRIES_MODE_FULL,
        chunk_size=SyncService.DEFAULT_CHUNK_SIZE,
    )
    return JsonResponse(
        {
            "status": "ok",
            "mode": SyncService.TIME_ENTRIES_MODE_FULL,
            "details": details,
        }
    )


@login_required
@require_GET
def redmine_sync_status_view(request: HttpRequest) -> JsonResponse:
    return JsonResponse(
        {
            "status": "ok",
            "employees": _serialize_sync_state("employees"),
            "projects": _serialize_sync_state("projects"),
            "time_entries_incremental": _serialize_sync_state("time_entries_incremental"),
            "time_entries_window": _serialize_sync_state("time_entries_window"),
            "time_entries_full": _serialize_sync_state("time_entries_full"),
        }
    )
