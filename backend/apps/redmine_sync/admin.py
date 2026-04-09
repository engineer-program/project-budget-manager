from django.contrib import admin

from .models import RedmineTimeEntry, SyncLog, SyncState


admin.site.register(RedmineTimeEntry)
admin.site.register(SyncState)
admin.site.register(SyncLog)
