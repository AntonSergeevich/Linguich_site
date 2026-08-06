"""Карта сайта. Нужна, чтобы поисковики находили страницы курсов и языков,
а не только главную."""

from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Course, Language


class StaticSitemap(Sitemap):
    changefreq = "weekly"
    protocol = "https"

    def items(self):
        return [
            "school:home", "school:courses", "school:teachers", "school:prices",
            "school:promos", "school:contacts", "school:signup", "placement:test",
        ]

    def location(self, item):
        return reverse(item)

    def priority(self, item):
        return 1.0 if item == "school:home" else 0.8


class CourseSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.9
    protocol = "https"

    def items(self):
        return Course.objects.filter(is_active=True)


class LanguageSitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.7
    protocol = "https"

    def items(self):
        return Language.objects.filter(is_active=True)


SITEMAPS = {
    "static": StaticSitemap,
    "courses": CourseSitemap,
    "languages": LanguageSitemap,
}
