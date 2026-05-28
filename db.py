import logging
from typing import Dict, List, Optional, Tuple

from config import Config
from nocodb_client import NocoDBClient
from utils import normalize_phone
from custom_logging import mask_phone, mask_name

logger = logging.getLogger(__name__)


# ──────────────────────────── Mailboxes ────────────────────────────

async def _find_mailbox_by_email(client: NocoDBClient, email: str) -> Optional[Dict]:
    """Находит строку mailbox по email. Возвращает строку или None."""
    if not email:
        return None
    # email в таблице хранится как есть, поэтому ищем серверным where
    row = await client.find_one(
        table_id=Config.NOCODB_MAILBOXES_TABLE_ID,
        where=f"(email,eq,{email})",
    )
    if not row:
        logger.warning("Mailbox не найден по email")
        logger.debug(f"Mailbox не найден: email={email}")
    return row


async def get_subscribers_for_email(email: str) -> Tuple[List[str], List[str]]:
    """
    Возвращает кортеж (telegram_id пользователей, telegram_id чатов),
    подписанных на указанный email. Пустые id_telegram отбрасываются.
    """
    try:
        async with NocoDBClient() as client:
            mailbox = await _find_mailbox_by_email(client, email)

        if not mailbox:
            return [], []

        user_ids: List[str] = []
        for link in mailbox.get("_nc_m2m_Mailboxes_Users", []) or []:
            user = link.get("Users") or {}
            tg_id = user.get("id_telegram")
            if tg_id:
                user_ids.append(str(tg_id))

        chat_ids: List[str] = []
        for link in mailbox.get("_nc_m2m_Mailboxes_Chats", []) or []:
            chat = link.get("Chats") or {}
            tg_id = chat.get("id_telegram_chat")
            if tg_id:
                chat_ids.append(str(tg_id))

        logger.info(
            "Подписчики для рассылки: пользователей=%d, чатов=%d",
            len(user_ids), len(chat_ids),
        )
        logger.debug(f"users={user_ids}, chats={chat_ids} (email={email})")
        return user_ids, chat_ids

    except Exception as e:
        logger.error(f"Ошибка получения подписчиков: {e}", exc_info=True)
        return [], []


async def get_users_to_send(email: str) -> List[str]:
    """Список telegram_id пользователей, подписанных на email."""
    users, _ = await get_subscribers_for_email(email)
    return users


async def get_chats_to_send(email: str) -> List[str]:
    """Список telegram_id чатов, подписанных на email."""
    _, chats = await get_subscribers_for_email(email)
    return chats


async def get_last_uid(email: str) -> Optional[str]:
    """Возвращает last_uid (id последнего обработанного письма) для mailbox по email."""
    try:
        async with NocoDBClient() as client:
            mailbox = await _find_mailbox_by_email(client, email)

        if not mailbox:
            return None

        last_uid = mailbox.get("last_uid")
        logger.debug(f"last_uid для {email}: {last_uid}")
        return str(last_uid) if last_uid else None

    except Exception as e:
        logger.error(f"Ошибка получения last_uid: {e}", exc_info=True)
        return None


async def update_last_uid(email: str, uid: str) -> bool:
    """Обновляет last_uid для mailbox по email."""
    try:
        async with NocoDBClient() as client:
            mailbox = await _find_mailbox_by_email(client, email)
            if not mailbox:
                return False

            await client.update_record(
                table_id=Config.NOCODB_MAILBOXES_TABLE_ID,
                record_id=mailbox["Id"],
                data={"last_uid": str(uid)},
            )

        logger.info("last_uid обновлён")
        logger.debug(f"last_uid обновлён для {email}: {uid}")
        return True

    except Exception as e:
        logger.error(f"Ошибка обновления last_uid: {e}", exc_info=True)
        return False


# ───────────────────────────── Users ─────────────────────────────

async def check_id_telegram(id_telegram: int | str) -> bool:
    """True, если в таблице Users есть пользователь с таким id_telegram."""
    try:
        async with NocoDBClient() as client:
            row = await client.find_one(
                table_id=Config.NOCODB_USERS_TABLE_ID,
                where=f"(id_telegram,eq,{id_telegram})",
            )
        found = row is not None
        logger.info("Проверка id_telegram: найден=%s", found)
        logger.debug(f"check_id_telegram: id_telegram={id_telegram}, найден={found}")
        return found

    except Exception as e:
        logger.error(f"Ошибка проверки пользователя: {e}", exc_info=True)
        return False


async def register_id_telegram(phone: str, id_telegram: int | str) -> bool:
    """
    Ищет пользователя по телефону и записывает его id_telegram.
    Телефоны в таблице нормализуются «лениво»: если в строке телефон записан
    в ненормализованном виде, перезаписываем его нормализованным.
    """
    normalized_input = normalize_phone(phone)
    if not normalized_input:
        logger.warning("Не удалось нормализовать входящий телефон")
        logger.debug(f"register_id_telegram: телефон не нормализуется: {mask_phone(phone)}")
        return False

    try:
        async with NocoDBClient() as client:
            users = await client.get_all(table_id=Config.NOCODB_USERS_TABLE_ID)

            matched = None
            for user in users:
                row_phone = user.get("phone")
                if row_phone and normalize_phone(str(row_phone)) == normalized_input:
                    matched = user
                    break

            if not matched:
                logger.warning("Пользователь с указанным телефоном не найден")
                logger.debug(f"register_id_telegram: телефон не найден: {mask_phone(normalized_input)}")
                return False

            # Готовим обновление: всегда пишем id_telegram;
            # если телефон в таблице был ненормализован — заодно перезаписываем его
            update: Dict[str, str] = {"id_telegram": str(id_telegram)}
            if str(matched.get("phone")) != normalized_input:
                update["phone"] = normalized_input

            await client.update_record(
                table_id=Config.NOCODB_USERS_TABLE_ID,
                record_id=matched["Id"],
                data=update,
            )

        logger.info("id_telegram успешно записан пользователю")
        logger.debug(f"register_id_telegram: id_telegram записан для {mask_phone(normalized_input)}")
        return True

    except Exception as e:
        logger.error(f"Ошибка регистрации пользователя: {e}", exc_info=True)
        return False


# ───────────────────────────── Chats ─────────────────────────────

async def register_group(chat_id: int, chat_title: str) -> bool:
    """
    Ищет группу по названию и записывает id_telegram_chat, затем блокирует её
    (is_locked=True), чтобы вторая группа с тем же названием не перехватила рассылку.
    Уже заблокированную группу не трогаем.
    """
    logger.info("Начало регистрации группы")
    logger.debug(f"register_group: title={chat_title}, chat_id={chat_id}")
    try:
        async with NocoDBClient() as client:
            # Названия групп неуникальны — берём все совпадения по имени
            candidates = await client.get_all(
                table_id=Config.NOCODB_CHATS_TABLE_ID,
                where=f"(Name,eq,{chat_title})",
            )

            if not candidates:
                logger.warning("Группа с таким названием не найдена в таблице")
                logger.debug(f"register_group: название не найдено: {chat_title}")
                return False

            # Ищем первую незаблокированную строку
            target = next((c for c in candidates if not c.get("is_locked")), None)

            if not target:
                logger.warning("Все группы с таким названием уже заблокированы — регистрация отклонена")
                logger.debug(f"register_group: все строки '{chat_title}' заблокированы")
                return False

            await client.update_record(
                table_id=Config.NOCODB_CHATS_TABLE_ID,
                record_id=target["Id"],
                data={
                    "id_telegram_chat": str(chat_id),
                    "is_locked": True,
                },
            )

        logger.info("Группа зарегистрирована и заблокирована для перезаписи")
        logger.debug(f"register_group: записан chat_id={chat_id} для группы '{chat_title}'")
        return True

    except Exception as e:
        logger.error(f"Ошибка регистрации группы: {e}", exc_info=True)
        return False