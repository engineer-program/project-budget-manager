from django.contrib import admin

from .models import Project


class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "project_number", "name_1s", "project_manager", "start_budget")
    search_fields = ("name", "project_number", "name_1s", "name_sanda")
    list_filter = ("lead_department",)
    autocomplete_fields = ["parent_project", "project_manager", "budget_updated_by"]


admin.site.register(Project, ProjectAdmin)
