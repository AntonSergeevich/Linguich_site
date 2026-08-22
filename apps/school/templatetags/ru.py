"""Русские счётные формы для шаблонов.

Встроенный ``pluralize`` рассчитан на два числа — единственное и множественное.
Русскому нужно три формы, и с тремя аргументами Django молча возвращает пустую
строку: `{{ n }} занятие{{ n|pluralize:",я,й" }}` даёт «8 занятие». Поэтому
формы перечисляем целиком, а не суффиксами — так в шаблоне сразу видно,
что получится.
"""

from django import template

from apps.utils import plural_ru

register = template.Library()


@register.filter(name="plural")
def plural(count, forms):
    """{{ n }} {{ n|plural:"занятие,занятия,занятий" }}"""
    parts = [part.strip() for part in str(forms).split(",")]
    if len(parts) != 3:
        return ""
    try:
        number = int(count)
    except (TypeError, ValueError):
        return parts[2]
    return plural_ru(number, *parts)
