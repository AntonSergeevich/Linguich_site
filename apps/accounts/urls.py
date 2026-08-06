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
    # Два способа привязать чат: свой бот школы зовёт link, либо платформа
    # сама принимает апдейты через webhook. Одновременно — не нужно.
    path("telegram/link/", views.telegram_link, name="telegram_link"),
    path("telegram/webhook/", views.telegram_webhook, name="telegram_webhook"),
]
