from django.urls import path

from . import views

app_name = "school"

urlpatterns = [
    path("", views.home, name="home"),
    path("courses/", views.courses, name="courses"),
    path("courses/<slug:slug>/", views.course_detail, name="course"),
    path("languages/<slug:slug>/", views.language_detail, name="language"),
    path("teachers/", views.teachers, name="teachers"),
    path("prices/", views.prices, name="prices"),
    path("promos/", views.promos, name="promos"),
    path("contacts/", views.contacts, name="contacts"),
    path("privacy/", views.privacy, name="privacy"),
    path("signup/", views.signup, name="signup"),
    path("api/lead/", views.lead_create, name="lead_create"),
    path("api/callback/", views.callback_create, name="callback_create"),
]
