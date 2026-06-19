from django.contrib import admin
from django.utils import timezone

from .models import ChangeLog


@admin.register(ChangeLog)
class ChangeLogAdmin(admin.ModelAdmin):
    list_display = (
        "entity_name",
        "entity_id",
        "action",
        "changed_by",
        "changed_at_moscow",
    )
    list_filter = ("action", "entity_name", "changed_at")
    search_fields = ("entity_name", "entity_id", "changed_by__username")
    readonly_fields = (
        "entity_name",
        "entity_id",
        "action",
        "changed_by",
        "changed_at",
        "changed_at_moscow",
        "before_data",
        "after_data",
    )
    ordering = ("-changed_at",)

    @admin.display(description="Changed at MSK", ordering="changed_at")
    def changed_at_moscow(self, obj: ChangeLog) -> str:
        changed_at = obj.changed_at
        if timezone.is_aware(changed_at):
            changed_at = timezone.localtime(changed_at)
        return changed_at.strftime("%d.%m.%Y %H:%M:%S")
