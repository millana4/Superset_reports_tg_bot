import asyncio
import logging
import threading

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

import handlers
import custom_logging
from config import Config
from bot import bot
from email_handler import imap_idle_listener
from telegram_api import router as chat_member


async def main():
    # Логирование — самым первым, чтобы старт тоже попал в файл
    custom_logging.setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Запуск бота...")

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(chat_member)       # события добавления бота в группу
    dp.include_router(handlers.router)   # /start и авторизация по контакту

    # Удаляем вебхук (на всякий случай) и сбрасываем накопившиеся апдейты
    await bot.delete_webhook(drop_pending_updates=True)

    me = await bot.get_me()
    logger.info("Telegram bot @%s запущен", me.username)

    accounts = [
        {"email": Config.IMAP_EMAIL_SR01, "password": Config.IMAP_PASSWORD_SR01, "imap": Config.IMAP_SERVER},
        {"email": Config.IMAP_EMAIL_SR02, "password": Config.IMAP_PASSWORD_SR02, "imap": Config.IMAP_SERVER},
        {"email": Config.IMAP_EMAIL_SR03, "password": Config.IMAP_PASSWORD_SR03, "imap": Config.IMAP_SERVER},
        {"email": Config.IMAP_EMAIL_SR04, "password": Config.IMAP_PASSWORD_SR04, "imap": Config.IMAP_SERVER},
    ]

    loop = asyncio.get_running_loop()

    # Запускаем IMAP-слушателей, каждый в своём демон-потоке
    for account in accounts:
        if not account["email"]:
            continue  # пропускаем незаполненные ящики
        threading.Thread(
            target=imap_idle_listener,
            args=(account, loop),
            daemon=True,
        ).start()
        logger.info(f"IMAP-листенер запущен для ящика {account["email"]}")

    # Запускаем Telegram-бота
    try:
        await dp.start_polling(bot)
    finally:
        logger.info("Остановка бота, закрываю сессию...")
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    asyncio.run(main())