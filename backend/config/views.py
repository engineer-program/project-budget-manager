from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render


def home_view(request: HttpRequest) -> HttpResponse:
    return render(request, "home.html")


def healthcheck_view(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})
