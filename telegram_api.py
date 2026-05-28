from aiogram import Router
from aiogram.types import ChatMemberUpdated
import logging

from db import register_group

router = Router()
logger = logging.getLogger(__name__)

# Статусы, означающие, что бот находится в группе
PRESENT_STATUSES = ("member", "administrator", "creator")


@router.my_chat_member()
async def on_my_chat_member_updated(event: ChatMemberUpdated):
    """Регистрирует группу, когда бота в неё добавляют (без требования прав администратора).
    Реагируем только на переход «бот не в группе → бот в группе»."""
    logger.info("Получено событие my_chat_member")
    logger.debug(f"my_chat_member: {event.model_dump()}")

    # Реагируем только на изменения статуса самого бота
    if event.new_chat_member.user.id != event.bot.id:
        return

    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status

    # Бот только что попал в группу (раньше его там не было)
    just_added = new_status in PRESENT_STATUSES and old_status not in PRESENT_STATUSES

    if not just_added:
        logger.debug(f"Изменение статуса не требует регистрации: old={old_status}, new={new_status}")
        return

    chat_id = event.chat.id
    chat_title = event.chat.title

    logger.info("Бот добавлен в группу — запускаю регистрацию")
    logger.debug(f"Группа: {chat_title} (ID: {chat_id})")

    try:
        success = await register_group(chat_id, chat_title)
        if not success:
            logger.warning("Группа не зарегистрирована (не найдена в базе или уже заблокирована)")
    except Exception as e:
        logger.error(f"Ошибка при регистрации группы: {e}", exc_info=True)