from django.contrib import admin

from .models import CompensationType


class CompensationTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "code")
    search_fields = ("name", "code")


admin.site.register(CompensationType, CompensationTypeAdmin)
