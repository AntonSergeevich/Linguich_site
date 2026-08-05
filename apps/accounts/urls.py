from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("register/", views.register_view, name="register"),
    path("logout/", views.logout_view, name="logout"),
    path("profile/", views.profile_view, name="profile"),
    path("profile/password/", views.change_password, name="change_password"),
    path("profile/telegram/unlink/", views.unlink_telegram, name="unlink_telegram"),
    path("telegram/webhook/", views.telegram_webhook, name="telegram_webhook"),
]
