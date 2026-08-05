import zoneinfo

from django.conf import settings
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
