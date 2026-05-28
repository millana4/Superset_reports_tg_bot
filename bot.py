from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession

from config import Config


# Для дебага бот может работать через прокси (BOT_PROXY в .env).
# На сервере BOT_PROXY оставить пустым — тогда сессия создаётся без прокси.
session = AiohttpSession(proxy=Config.BOT_PROXY) if Config.BOT_PROXY else AiohttpSession()

# Инициализация бота
bot = Bot(token=Config.BOT_TOKEN, session=session)