import json

from django.contrib import messages
from django.contrib.auth import login as auth_login, logout as auth_logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.utils import is_ajax, json_error, json_form_error, json_ok

from .forms import LoginForm, ProfileForm, RegistrationForm, StudentDetailsForm
from .models import User


def _safe_next(request):
    target = request.POST.get("next") or request.GET.get("next") or ""
    return target if target.startswith("/") and not target.startswith("//") else reverse("cabinet:home")


def login_view(request):
    if request.user.is_authenticated:
        return redirect("cabinet:home")

    form = LoginForm(request)
    if request.method == "POST":
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            auth_login(request, form.user)
            destination = _safe_next(request)
            if is_ajax(request):
                return json_ok(redirect=destination)
            return redirect(destination)
        if is_ajax(request):
            return json_form_error(form, "Не удалось войти.")

    return render(request, "registration/login.html", {"form": form, "next": request.GET.get("next", "")})


def register_view(request):
    if request.user.is_authenticated:
        return redirect("cabinet:home")

    form = RegistrationForm()
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user, backend="apps.accounts.backends.EmailOrPhoneBackend")
            if is_ajax(request):
                return json_ok(redirect=reverse("cabinet:home"))
            return redirect("cabinet:home")
        if is_ajax(request):
            return json_form_error(form, "Проверьте данные регистрации.")

    return render(request, "registration/register.html", {"form": form})


def logout_view(request):
    auth_logout(request)
    return redirect("school:home")


@login_required
def profile_view(request):
    profile_form = ProfileForm(instance=request.user)
    details_form = None
    if request.user.is_student:
        student_profile, _created = request.user.student_profile.__class__.objects.get_or_create(
            user=request.user
        )
        details_form = StudentDetailsForm(instance=student_profile)

    if request.method == "POST":
        profile_form = ProfileForm(request.POST, request.FILES, instance=request.user)
        forms_valid = profile_form.is_valid()
        if details_form is not None:
            details_form = StudentDetailsForm(request.POST, instance=request.user.student_profile)
            forms_valid = forms_valid and details_form.is_valid()
        if forms_valid:
            profile_form.save()
            if details_form is not None:
                details_form.save()
            if is_ajax(request):
                return json_ok("Профиль сохранён.")
            messages.success(request, "Профиль сохранён.")
            return redirect("accounts:profile")
        if is_ajax(request):
            return json_form_error(profile_form)

    return render(request, "cabinet/profile.html", {
        "form": profile_form,
        "details_form": details_form,
        "password_form": PasswordChangeForm(request.user),
    })


@login_required
@require_POST
def change_password(request):
    form = PasswordChangeForm(request.user, request.POST)
    if not form.is_valid():
        return json_form_error(form, "Не удалось сменить пароль.")
    user = form.save()
    update_session_auth_hash(request, user)
    return json_ok("Пароль обновлён.")


@login_required
@require_POST
def unlink_telegram(request):
    request.user.telegram_chat_id = ""
    request.user.save(update_fields=["telegram_chat_id"])
    return json_ok("Telegram отвязан.")


@csrf_exempt
@require_POST
def telegram_webhook(request):
    """Links a Telegram chat to an account when the user sends /start <code>.

    Deliberately minimal: the bot is a notification channel, not a second UI.
    """
    from django.conf import settings

    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    expected = getattr(settings, "TELEGRAM_WEBHOOK_SECRET", "")
    if expected and secret != expected:
        return json_error("forbidden", status=403)

    try:
        update = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return json_error("bad payload")

    message = update.get("message") or {}
    text = (message.get("text") or "").strip()
    chat_id = str((message.get("chat") or {}).get("id") or "")
    if not chat_id or not text.startswith("/start"):
        return json_ok()

    parts = text.split(maxsplit=1)
    code = parts[1].strip() if len(parts) > 1 else ""
    if not code:
        return json_ok()

    user = User.objects.filter(telegram_link_code=code).first()
    if user:
        user.telegram_chat_id = chat_id
        user.save(update_fields=["telegram_chat_id"])
    return json_ok()
