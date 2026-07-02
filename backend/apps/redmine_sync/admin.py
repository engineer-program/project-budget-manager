from django.contrib import admin

from .models import RedmineTimeEntry, SyncLog, SyncRun, SyncState


admin.site.register(RedmineTimeEntry)
admin.site.register(SyncState)
admin.site.register(SyncLog)
admin.site.register(SyncRun)
