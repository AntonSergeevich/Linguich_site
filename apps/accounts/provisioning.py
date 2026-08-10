"""Выдача учётных данных: логин из фамилии и разовый пароль.

Ученика заводит школа, а не он сам. Значит, логин и пароль должен кто-то
придумать — и если оставить это человеку, в базе окажутся «ivan» с паролем
«123456». Здесь всё генерируется по одним правилам: логин узнаваемый, чтобы
его можно было продиктовать по телефону, пароль случайный и без букв, которые
путают на слух и на глаз.
"""

import re
import secrets

from django.db import transaction

from .models import Role, StudentProfile, TeacherProfile, User

# Транслитерация по «телефонному» принципу: важно не соответствие ГОСТу,
# а чтобы фамилию можно было продиктовать и записать без переспросов.
TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

# Только строчные и без пар, которые путают на слух и на письме:
# нет i/l/o, нет 0/1, нет 5 (сливается с s). Остаётся 30 символов —
# на 12 знаков это около 59 бит, для разового пароля с запасом.
PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyz234679"
PASSWORD_GROUPS = 3
PASSWORD_GROUP_SIZE = 4

MAX_USERNAME_LENGTH = 32


def transliterate(text):
    out = []
    for char in (text or "").lower():
        out.append(TRANSLIT.get(char, char))
    return "".join(out)


def generate_username(last_name, first_name=""):
    """Логин из фамилии; при совпадении добавляем инициал, потом число.

    Порядок важен: `ivanov`, `ivanovm`, `ivanov2` читается человеком куда
    легче, чем `ivanov_7f3a`, а диктовать его придётся не раз.
    """
    base = re.sub(r"[^a-z0-9]", "", transliterate(last_name))
    if not base:
        base = re.sub(r"[^a-z0-9]", "", transliterate(first_name)) or "student"
    base = base[:MAX_USERNAME_LENGTH - 3]

    initial = re.sub(r"[^a-z]", "", transliterate(first_name))[:1]
    candidates = [base]
    if initial:
        candidates.append(base + initial)

    for candidate in candidates:
        if not User.objects.filter(username=candidate).exists():
            return candidate

    for number in range(2, 1000):
        candidate = f"{base}{number}"
        if not User.objects.filter(username=candidate).exists():
            return candidate
    # Тысяча однофамильцев — до этого не дойдёт, но пусть будет выход.
    return f"{base}{secrets.token_hex(3)}"


def generate_password():
    """Разовый пароль: читается вслух, не путается при записи от руки."""
    groups = [
        "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(PASSWORD_GROUP_SIZE))
        for _ in range(PASSWORD_GROUPS)
    ]
    return "-".join(groups)


@transaction.atomic
def create_account(*, role, first_name, last_name="", phone="", email="", **profile):
    """Завести аккаунт и вернуть ``(user, password)``.

    Пароль возвращается один раз и нигде не сохраняется в открытом виде —
    показать его администратору можно только сразу после создания.
    """
    password = generate_password()
    user = User.objects.create_user(
        username=generate_username(last_name, first_name),
        email=email or None,
        phone=phone or None,
        password=password,
        first_name=first_name,
        last_name=last_name,
        role=role,
        must_change_password=True,
    )
    if role == Role.STUDENT:
        StudentProfile.objects.get_or_create(user=user, defaults=profile)
    elif role in {Role.TEACHER, Role.OWNER}:
        TeacherProfile.objects.get_or_create(user=user, defaults=profile)
    return user, password


def reset_password(user):
    """Выдать новый разовый пароль. Возвращает его открытым текстом."""
    password = generate_password()
    user.set_password(password)
    user.must_change_password = True
    user.save(update_fields=["password", "must_change_password"])
    return password


def handover_text(user, password, site_url):
    """Готовое сообщение ученику — чтобы администратор его не сочинял."""
    return (
        f"Здравствуйте, {user.first_name}!\n"
        f"Личный кабинет школы «Лингвич»: {site_url}/accounts/login/\n"
        f"Логин: {user.username}\n"
        f"Пароль: {password}\n"
        f"При первом входе система попросит придумать свой пароль."
    )
