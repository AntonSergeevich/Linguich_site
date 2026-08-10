import zoneinfo

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone


class TimezoneMiddleware:
    """Render every date in the viewer's own timezone.

    Online students are spread across time zones; showing a Krasnoyarsk clock to
    someone in Moscow is the fastest way to have them miss a lesson.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tzname = settings.TIME_ZONE
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.timezone:
            tzname = user.timezone
        try:
            timezone.activate(zoneinfo.ZoneInfo(tzname))
        except Exception:
            timezone.activate(zoneinfo.ZoneInfo(settings.TIME_ZONE))
        try:
            return self.get_response(request)
        finally:
            timezone.deactivate()


class ForcePasswordChangeMiddleware:
    """Пароль, выданный школой, знает ещё и администратор.

    Пока ученик не заменил его своим, пускать в кабинет нельзя — иначе
    временный пароль живёт годами и лежит в переписке. Выпускаем только
    на страницу смены пароля и на выход.
    """

    # Публичный сайт не запираем: человек имеет право читать страницы школы.
    # Закрыт только кабинет — всё, что за логином.
    GUARDED_PREFIX = ("/cabinet/", "/accounts/profile")
    ALLOWED = {"accounts:set_password", "accounts:logout"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        """Именно process_view, а не __call__: на входе в __call__ адрес ещё
        не разобран, resolver_match пуст, и страница смены пароля отправляла
        бы сама на себя — вечный редирект."""
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated or not user.must_change_password:
            return None
        match = request.resolver_match
        if match is not None and match.view_name in self.ALLOWED:
            return None
        if not request.path.startswith(self.GUARDED_PREFIX):
            return None
        return redirect(reverse("accounts:set_password"))
