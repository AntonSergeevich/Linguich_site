"""Small shared helpers: JSON responses for the async layer and role guards."""

from functools import wraps

from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import redirect


def is_ajax(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def json_ok(message="", **extra):
    payload = {"ok": True}
    if message:
        payload["message"] = message
    payload.update(extra)
    return JsonResponse(payload)


def json_error(message, fields=None, status=400):
    payload = {"ok": False, "error": message}
    if fields:
        payload["fields"] = fields
    return JsonResponse(payload, status=status)


def form_errors(form):
    """First error per field — that is all the inline UI shows."""
    return {name: errors[0] for name, errors in form.errors.items()}


def json_form_error(form, message="Проверьте, пожалуйста, поля формы."):
    non_field = form.non_field_errors()
    return json_error(non_field[0] if non_field else message, fields=form_errors(form))


def role_required(*roles):
    """Guard a view by user role. Anonymous users go to login, wrong roles get 403."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return redirect(f"/accounts/login/?next={request.path}")
            if roles and user.role not in roles:
                raise PermissionDenied("Недостаточно прав.")
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


def teacher_required(view):
    """Teachers and the owner — the owner teaches too."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"/accounts/login/?next={request.path}")
        if not request.user.is_teacher:
            raise PermissionDenied("Раздел только для преподавателей.")
        return view(request, *args, **kwargs)

    return wrapper


def owner_required(view):
    """Только владелица: зарплаты, состав сотрудников, настройки школы."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"/accounts/login/?next={request.path}")
        if not request.user.is_owner:
            raise PermissionDenied("Раздел только для владельца школы.")
        return view(request, *args, **kwargs)

    return wrapper


def manager_required(view):
    """Администраторы и владелица — повседневная работа CRM."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"/accounts/login/?next={request.path}")
        if not request.user.is_manager:
            raise PermissionDenied("Раздел только для администраторов школы.")
        return view(request, *args, **kwargs)

    return wrapper


def plural_ru(count, one, few, many):
    """Русское окончание по числу: 1 место, 2 места, 5 мест.

    Встроенный ``pluralize`` умеет только две формы — с тремя он молча
    возвращает пустую строку, поэтому счётные подписи считаем здесь.
    """
    mod10, mod100 = count % 10, count % 100
    if mod10 == 1 and mod100 != 11:
        return one
    if 2 <= mod10 <= 4 and not 12 <= mod100 <= 14:
        return few
    return many
