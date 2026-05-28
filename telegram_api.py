from aiogram import Router
from aiogram.types import ChatMemberUpdated
import logging

from db import register_group

router = Router()
logger = logging.getLogger(__name__)

@router.my_chat_member()
async def on_my_chat_member_updated(event: ChatMemberUpdated):
    """Отслеживает, как меняется статус бота — в какую группу его добавляют, становится там участником
    или администратором, или покидает группу. Если бот становится администратором в группе, то вызывается
    функция регистрации группы. Остальные изменения статусов игнорируются."""
    logger.info(f"Получено событие my_chat_member: {event.model_dump()}")

    if (event.new_chat_member.status in ("administrator", "creator") and
            event.new_chat_member.user.id == event.bot.id):

        chat_id = event.chat.id
        chat_title = event.chat.title

        logger.info(f"Бот стал администратором в группе: {chat_title} (ID: {chat_id})")

        try:
            success = await register_group(chat_id, chat_title)
            if not success:
                logger.error("Не удалось зарегистрировать группу в Seatable")
        except Exception as e:
            logger.error(f"Ошибка при регистрации группы: {str(e)}", exc_info=True)
    else:
        logger.info(f"Событие не соответствует условиям обработки. Статусы: old={event.old_chat_member.status}, new={event.new_chat_member.status}")