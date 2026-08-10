from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import AdminPasswordChangeForm

from .models import StudentProfile, TeacherProfile, User


class TeacherProfileInline(admin.StackedInline):
    model = TeacherProfile
    extra = 0
    filter_horizontal = ["languages"]


class StudentProfileInline(admin.StackedInline):
    model = StudentProfile
    extra = 0


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    change_password_form = AdminPasswordChangeForm
    ordering = ["-date_joined"]
    list_display = ["full_name", "username", "email", "phone", "role", "is_active", "date_joined"]
    list_filter = ["role", "is_active", "is_staff", "must_change_password"]
    search_fields = ["first_name", "last_name", "username", "email", "phone"]
    inlines = [TeacherProfileInline, StudentProfileInline]

    fieldsets = (
        (None, {"fields": ("username", "email", "phone", "password", "must_change_password")}),
        ("Профиль", {"fields": ("first_name", "last_name", "avatar", "role", "timezone")}),
        ("Уведомления", {"fields": ("notify_email", "notify_telegram", "telegram_chat_id")}),
        ("Права", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "email", "phone", "first_name", "last_name", "role",
                       "password1", "password2"),
        }),
    )
