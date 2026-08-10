import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login as auth_login, logout as auth_logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
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

    return render(request, "registration/login.html", {
        "form": form,
        "next": request.GET.get("next", ""),
        "registration_open": getattr(settings, "PUBLIC_REGISTRATION_ENABLED", False),
    })


def register_view(request):
    """Самостоятельная регистрация.

    По умолчанию закрыта: аккаунт ученику заводит школа, чтобы в кабинете
    не заводились люди, которых никто не знает. Открывается настройкой,
    если школа решит вернуть свободную запись.
    """
    if request.user.is_authenticated:
        return redirect("cabinet:home")
    if not getattr(settings, "PUBLIC_REGISTRATION_ENABLED", False):
        return render(request, "registration/register_closed.html", status=403)

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

    # cabinet_context даёт боковое меню. Без него страница открывалась
    # с пустой навигацией, и уйти с неё можно было только кнопкой «назад»
    # в браузере.
    from apps.cabinet.common import cabinet_context

    return render(request, "cabinet/profile.html", cabinet_context(
        request,
        form=profile_form,
        details_form=details_form,
        password_form=PasswordChangeForm(request.user),
        bot_username=getattr(settings, "TELEGRAM_BOT_USERNAME", ""),
    ))


@login_required
@require_POST
def change_password(request):
    form = PasswordChangeForm(request.user, request.POST)
    if not form.is_valid():
        return json_form_error(form, "Не удалось сменить пароль.")
    user = form.save()
    _clear_temporary_password(user)
    update_session_auth_hash(request, user)
    return json_ok("Пароль обновлён.")


def _clear_temporary_password(user):
    if user.must_change_password:
        user.must_change_password = False
        user.save(update_fields=["must_change_password"])


@login_required
def set_password(request):
    """Обязательная смена пароля, выданного школой.

    Отдельная страница, а не блок в профиле: пока пароль временный,
    кабинет закрыт целиком, и человеку нужен один экран с одним действием.
    """
    if not request.user.must_change_password:
        return redirect("cabinet:home")

    form = SetPasswordForm(request.user)
    if request.method == "POST":
        form = SetPasswordForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            _clear_temporary_password(user)
            update_session_auth_hash(request, user)
            messages.success(request, "Пароль сохранён. Добро пожаловать!")
            return redirect("cabinet:home")

    return render(request, "registration/set_password.html", {"form": form})


@login_required
@require_POST
def telegram_test(request):
    """Отправить себе проверочное сообщение прямо сейчас, минуя очередь.

    Chat ID вписывают руками и легко ошибаются: чужой номер, ID канала
    вместо личного чата, не нажатый «Start». Без немедленной проверки об
    ошибке узнают в день, когда не пришло напоминание об уроке.
    """
    from apps.notifications.models import Channel, Notification
    from apps.notifications.services import _deliver_telegram

    if not request.user.telegram_chat_id:
        return json_error("Сначала укажите Telegram ID и сохраните профиль.")

    # Объект намеренно не сохраняем: это разовая проверка канала,
    # в истории уведомлений ей не место.
    probe = Notification(
        recipient=request.user, channel=Channel.TELEGRAM,
        subject="Проверка связи",
        body="Если вы это видите — уведомления школы будут приходить сюда.",
    )
    try:
        delivered = _deliver_telegram(probe)
    except Exception as exc:
        return json_error(_telegram_hint(exc))
    if not delivered:
        return json_error("Не настроен токен бота — обратитесь к разработчику.")
    return json_ok("Отправили сообщение в Telegram. Проверьте бота.")


def _telegram_hint(error):
    """Ответы Telegram лаконичны до бесполезности — переводим их в действие."""
    text = str(error)
    if "403" in text:
        return ("Бот не может написать вам первым. Откройте бота в Telegram "
                "и нажмите «Start», затем повторите проверку.")
    if "400" in text:
        return "Telegram не знает такой chat_id. Проверьте число — его выдаёт @userinfobot."
    if "401" in text:
        return "Токен бота неверный — обратитесь к разработчику."
    return f"Telegram ответил ошибкой: {text}"


@login_required
@require_POST
def unlink_telegram(request):
    request.user.telegram_chat_id = ""
    request.user.save(update_fields=["telegram_chat_id"])
    return json_ok("Telegram отвязан.")


def _link_chat(code, chat_id):
    """Attach a Telegram chat to the account that owns ``code``."""
    user = User.objects.filter(telegram_link_code=code).first()
    if not user:
        return None
    user.telegram_chat_id = str(chat_id)
    user.save(update_fields=["telegram_chat_id"])
    return user


@csrf_exempt
@require_POST
def telegram_link(request):
    """Linking endpoint for a bot the school already runs.

    Отправлять сообщения через Bot API может кто угодно, кто знает токен, —
    для этого интеграция не нужна. А вот узнать chat_id ученика может только
    тот, кто принимает апдейты. Если бот уже работает на long polling,
    ставить вебхук нельзя (Telegram отдаёт апдейты кому-то одному), поэтому
    бот сам зовёт этот эндпоинт, получив /start <код>.
    """
    from django.conf import settings

    api_key = getattr(settings, "TELEGRAM_LINK_API_KEY", "")
    if not api_key or request.headers.get("X-Api-Key", "") != api_key:
        return json_error("forbidden", status=403)

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return json_error("bad payload")

    code = (payload.get("code") or "").strip()
    chat_id = payload.get("chat_id")
    if not code or not chat_id:
        return json_error("нужны code и chat_id")

    user = _link_chat(code, chat_id)
    if user is None:
        return json_error("код не найден", status=404)
    return json_ok(f"Привязано к аккаунту {user.full_name}", user=user.pk)


@csrf_exempt
@require_POST
def telegram_webhook(request):
    """Alternative to ``telegram_link``: the platform receives updates itself.

    Годится, только если у школы нет своего бота на long polling.
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
    if code:
        _link_chat(code, chat_id)
    return json_ok()
