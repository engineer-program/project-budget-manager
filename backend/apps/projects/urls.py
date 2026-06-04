from django.urls import path

from .views import projects_page_view

urlpatterns = [
    path("", projects_page_view, name="projects-list"),
]
