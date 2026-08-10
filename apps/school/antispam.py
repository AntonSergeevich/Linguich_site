"""Защита форм заявки от ботов.

Один приём ничего не даёт: ловушку обходят, таймер подделывают, IP меняют.
Поэтому слоёв несколько, и каждый стоит дёшево — ни капчи, ни внешних
сервисов, ни единого лишнего запроса для живого человека.

1. Ловушка (honeypot) — поле, которого человек не видит.
2. Подписанная метка времени: форму нельзя отправить быстрее человека
   и нельзя переиспользовать спустя сутки.
3. Ограничение по IP — сколько заявок принимаем с одного адреса в час.
4. Гашение дублей по телефону: повторная отправка того же номера не
   плодит заявки, но и не выглядит для отправителя ошибкой.

Всё, что здесь помечено как спам, отдаётся наружу вежливым текстом.
Боту незачем знать, какой именно слой его поймал.
"""

from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.utils import timezone

# Быстрее этого форму не заполнит даже тот, кто печатает вслепую:
# нужно попасть в поля, набрать имя и телефон, поставить галочку.
MIN_FILL_SECONDS = 3
# Дольше суток вкладку не держат — а вот заготовленный токен живёт вечно.
MAX_FORM_AGE_SECONDS = 24 * 3600
# Столько заявок с одного адреса за час считаем нормальным: семья с одного
# роутера, офис, мобильный оператор с общим NAT.
MAX_LEADS_PER_IP_PER_HOUR = 5
# Тот же номер в пределах этого окна — это повтор, а не новая заявка.
DUPLICATE_WINDOW_MINUTES = 30

TIMESTAMP_SALT = "linguich.lead.form"


class SpamRejected(Exception):
    """Заявку не приняли. Текст можно показывать отправителю."""


def form_timestamp(moment=None):
    """Метка для скрытого поля формы. Подписана, подделать нельзя.

    `moment` нужен тестам: чтобы проверить приём заявки, метку приходится
    выдавать задним числом — иначе сработает защита от слишком быстрой
    отправки.
    """
    moment = moment or timezone.now()
    return signing.dumps(moment.timestamp(), salt=TIMESTAMP_SALT)


def _seconds_since(token):
    """Сколько секунд прошло с момента отрисовки формы, или None."""
    if not token:
        return None
    try:
        issued = signing.loads(token, salt=TIMESTAMP_SALT, max_age=MAX_FORM_AGE_SECONDS)
    except signing.BadSignature:
        return None
    return timezone.now().timestamp() - float(issued)


def client_ip(request):
    """IP отправителя с поправкой на nginx.

    nginx ставит `X-Forwarded-For: $proxy_add_x_forwarded_for` — он
    дописывает реально подключившийся адрес в КОНЕЦ списка. Всё, что левее,
    прислал сам клиент, и туда можно написать что угодно. Поэтому берём
    последний элемент, а не первый.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        parts = [part.strip() for part in forwarded.split(",") if part.strip()]
        if parts:
            return parts[-1][:45]
    return (request.META.get("REMOTE_ADDR") or "")[:45]


def check_request(request, form=None):
    """Проверить отправку до создания заявки.

    Кидает ``SpamRejected`` с текстом для отправителя либо молча
    возвращает управление.
    """
    if getattr(settings, "LEAD_ANTISPAM_ENABLED", True) is False:
        return

    # 1. Ловушка. Настоящий посетитель это поле не видит и не заполнит.
    if (request.POST.get("company") or "").strip():
        raise SpamRejected("Не удалось отправить заявку. Позвоните нам, пожалуйста.")

    # 2. Время заполнения.
    elapsed = _seconds_since(request.POST.get("form_ts"))
    if elapsed is None:
        # Токена нет или подпись не сходится: форму собрали в обход страницы.
        raise SpamRejected("Форма устарела. Обновите страницу и попробуйте ещё раз.")
    if elapsed < MIN_FILL_SECONDS:
        # Отрицательное значение сюда же: метка «из будущего» — это подделка.
        raise SpamRejected("Слишком быстро. Проверьте поля и отправьте ещё раз.")
    if elapsed > MAX_FORM_AGE_SECONDS:
        # Подпись протухает и сама, но проверять возраст только через неё
        # значит зависеть от того, какие часы взял signing. Явно надёжнее.
        raise SpamRejected("Форма устарела. Обновите страницу и попробуйте ещё раз.")

    # 3. Частота с одного адреса.
    from .models import Lead

    ip = client_ip(request)
    if ip:
        since = timezone.now() - timedelta(hours=1)
        recent = Lead.objects.filter(ip=ip, created_at__gte=since).count()
        if recent >= MAX_LEADS_PER_IP_PER_HOUR:
            raise SpamRejected(
                "С этого устройства уже несколько заявок. "
                "Мы их видим — позвоните, если срочно."
            )


def find_recent_duplicate(phone):
    """Та же самая заявка, отправленная только что? Тогда новую не заводим."""
    from .models import Lead

    if not phone:
        return None
    since = timezone.now() - timedelta(minutes=DUPLICATE_WINDOW_MINUTES)
    return Lead.objects.filter(phone=phone, created_at__gte=since).first()
