# -*- coding: utf-8 -*-
"""Кусок для вашего уже работающего Telegram-бота.

Задача одна: когда ученик нажимает в кабинете «Подключить Telegram», он
попадает в бота со ссылкой вида https://t.me/ваш_бот?start=КОД. Бот получает
этот код в /start и должен сообщить платформе, какому chat_id он соответствует.

Дальше платформа шлёт напоминания сама, через Bot API с тем же токеном —
дополнительный код в боте для этого не нужен.

Вебхук на стороне платформы в этом случае НЕ ставится: Telegram отдаёт
апдейты кому-то одному, и вебхук сломает ваш polling.
"""

import os

import requests

LINK_URL = os.environ.get("LINGUICH_LINK_URL", "https://linguich.ru/accounts/telegram/link/")
LINK_API_KEY = os.environ["LINGUICH_LINK_API_KEY"]  # тот же, что в .env платформы


def link_account(code: str, chat_id: int) -> tuple[bool, str]:
    """Привязывает чат к аккаунту. Возвращает (успех, сообщение для ученика)."""
    try:
        response = requests.post(
            LINK_URL,
            json={"code": code, "chat_id": chat_id},
            headers={"X-Api-Key": LINK_API_KEY},
            timeout=5,
        )
    except requests.RequestException:
        return False, "Сервис временно недоступен, попробуйте через минуту."

    if response.status_code == 200:
        return True, "Готово! Напоминания об уроках будут приходить сюда."
    if response.status_code == 404:
        return False, "Ссылка устарела. Откройте кабинет и нажмите «Подключить Telegram» ещё раз."
    return False, "Не удалось привязать аккаунт. Напишите администратору."


# --- aiogram 3 --------------------------------------------------------------
#
# from aiogram import Router
# from aiogram.filters import CommandStart, CommandObject
# from aiogram.types import Message
#
# router = Router()
#
# @router.message(CommandStart(deep_link=True))
# async def start_with_code(message: Message, command: CommandObject):
#     code = (command.args or "").strip()
#     if not code:
#         await message.answer("Привет! Это бот школы «Лингвич».")
#         return
#     # requests синхронный — в aiogram выносим его из event loop.
#     ok, text = await asyncio.to_thread(link_account, code, message.chat.id)
#     await message.answer(text)


# --- pyTelegramBotAPI (telebot) --------------------------------------------
#
# @bot.message_handler(commands=["start"])
# def start(message):
#     parts = message.text.split(maxsplit=1)
#     code = parts[1].strip() if len(parts) > 1 else ""
#     if not code:
#         bot.reply_to(message, "Привет! Это бот школы «Лингвич».")
#         return
#     ok, text = link_account(code, message.chat.id)
#     bot.reply_to(message, text)
