# -*- coding: utf-8 -*-
"""Готовый бот школы «Лингвич». Запускается как есть.

Он делает ровно одну вещь: когда человек нажимает в кабинете «Подключить
Telegram», он попадает сюда по ссылке вида t.me/бот?start=КОД, и бот
сообщает платформе, какому chat_id этот код соответствует.

Уведомления бот НЕ отправляет — их шлёт сама платформа через Bot API тем же
токеном. Боту для этого ничего делать не нужно.

    pip install pyTelegramBotAPI requests
    export TELEGRAM_BOT_TOKEN=...        # тот же, что в .env платформы
    export LINGUICH_LINK_API_KEY=...     # TELEGRAM_LINK_API_KEY из .env
    python telegram_bot.py

Важно: вебхук при этом ставить нельзя. Telegram отдаёт апдейты кому-то
одному — вебхук platform'ы и long polling бота исключают друг друга.
"""

import logging
import os

import requests
import telebot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("linguich-bot")

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
LINK_URL = os.environ.get("LINGUICH_LINK_URL", "https://linguich.ru/accounts/telegram/link/")
LINK_API_KEY = os.environ["LINGUICH_LINK_API_KEY"]

bot = telebot.TeleBot(TOKEN)


def link_account(code, chat_id):
    """Привязать чат к аккаунту. Возвращает текст ответа человеку."""
    try:
        response = requests.post(
            LINK_URL,
            json={"code": code, "chat_id": chat_id},
            headers={"X-Api-Key": LINK_API_KEY},
            timeout=5,
        )
    except requests.RequestException as exc:
        log.warning("платформа недоступна: %s", exc)
        return "Сервис временно недоступен, попробуйте через минуту."

    if response.status_code == 200:
        return "Готово! Уведомления школы будут приходить сюда."
    if response.status_code == 404:
        return ("Ссылка устарела. Откройте личный кабинет и нажмите "
                "«Подключить Telegram» ещё раз.")
    if response.status_code == 403:
        # Ключ не совпал — это ошибка настройки, а не человека.
        log.error("платформа отвергла ключ: проверьте LINGUICH_LINK_API_KEY")
        return "Не удалось привязать аккаунт. Сообщите, пожалуйста, администратору."
    log.error("неожиданный ответ платформы: %s %s", response.status_code, response.text[:200])
    return "Не удалось привязать аккаунт. Сообщите, пожалуйста, администратору."


@bot.message_handler(commands=["start"])
def on_start(message):
    # Telegram присылает код как аргумент: «/start abc123».
    parts = message.text.split(maxsplit=1)
    code = parts[1].strip() if len(parts) > 1 else ""
    if code:
        bot.reply_to(message, link_account(code, message.chat.id))
        return
    bot.reply_to(
        message,
        "Здравствуйте! Это бот языковой школы «Лингвич».\n\n"
        "Чтобы получать напоминания об уроках, откройте личный кабинет "
        "и нажмите «Подключить Telegram».\n\n"
        f"Ваш ID для ручной привязки: {message.chat.id}",
    )


@bot.message_handler(commands=["id"])
def on_id(message):
    """Подсказка администратору: вписать этот номер в профиль вручную."""
    bot.reply_to(message, f"Ваш Telegram ID: {message.chat.id}")


@bot.message_handler(func=lambda _: True)
def on_anything(message):
    bot.reply_to(
        message,
        "Я умею только подключать уведомления. Напишите /id, чтобы узнать свой ID, "
        "или откройте личный кабинет и нажмите «Подключить Telegram».",
    )


if __name__ == "__main__":
    log.info("бот запущен, ждём сообщений")
    bot.infinity_polling(skip_pending=True)
