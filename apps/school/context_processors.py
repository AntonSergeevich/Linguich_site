from .models import Language, Location, SiteSettings


def site_settings(request):
    """Brand, contacts and nav data every page needs."""
    return {
        "site": SiteSettings.load(),
        "nav_languages": Language.objects.filter(is_active=True),
        "nav_locations": Location.objects.filter(is_active=True, is_online=False),
    }
