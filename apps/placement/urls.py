from django.urls import path

from . import views

app_name = "placement"

urlpatterns = [
    path("", views.test_page, name="test"),
    path("api/start/", views.start, name="start"),
    path("api/answer/", views.answer, name="answer"),
    path("api/lead/", views.capture_lead, name="lead"),
]
