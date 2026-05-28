import asyncio
import pprint
import time
import aiohttp
import logging
from typing import List, Dict, Optional, Any

from config import Config
from utils import normalize_phone

logger = logging.getLogger(__name__)

# Глобальный кэш токена
_token_cache: Dict[str, Optional[Dict]] = {
    "token_data": None,
    "timestamp": 0
}
_TOKEN_TTL = 172800  # время жизни токена в секундах — 48 часов


async def get_base_token() -> Optional[Dict]:
    """
    Получает временный токен для синхронизации по Апи.
    Возвращает словарь:
    {
        "app_name":"app_bot",
        "access_token":"some_token_string",
        "dtable_uuid":"54abc13e-2968-495b-b40d-b690775cd64f",
        "dtable_server":"server/dtable-server/",
        "dtable_socket":"server",
        "dtable_db":"server/dtable-db/",
        "workspace_id":1,
        "dtable_name":"users_sset-grp"
    }
    """
    now = time.time()
    cached = _token_cache["token_data"]
    cached_time = _token_cache["timestamp"]

    if cached and (now - cached_time) < _TOKEN_TTL:
        return cached

    url = f"{Config.SEATABLE_SERVER}/api/v2.1/dtable/app-access-token/"
    headers = {
        "accept": "application/json",
        "authorization": f"Bearer {Config.SEATABLE_API_TOKEN}"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                response.raise_for_status()
                token_data = await response.json()
                logger.debug("Base token successfully obtained and cached")

                # Обновляем кэш
                _token_cache["token_data"] = token_data
                _token_cache["timestamp"] = now

                return token_data

    except aiohttp.ClientError as e:
        logger.error(f"API request failed: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")

    return None


async def check_id_telegram(id_telegram: str) -> bool:
    """
    Проверяет наличие telegram_id в таблице Users.
    Возвращает True если пользователь найден, False если нет.
    """
    try:
        token_data = await get_base_token()
        if not token_data:
            logger.error("Не удалось получить токен SeaTable")
            return False

        base_url = f"{token_data['dtable_server']}api/v1/dtables/{token_data['dtable_uuid']}/rows/"
        headers = {
            "Authorization": f"Bearer {token_data['access_token']}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        params = {"table_name": Config.SEATABLE_USERS_TABLE_ID}

        async with aiohttp.ClientSession() as session:
            async with session.get(base_url, headers=headers, params=params) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Ошибка запроса: {response.status}. Ответ: {error_text}")
                    return False

                data = await response.json()
                """
                Пример data:
                {'rows': 
                    [
                        {'_id': 'HiQYOMv4SLSsSMF_EpGpOg', 
                        '_mtime': '2025-07-31T11:52:03.380+00:00', 
                        '_ctime': '2025-07-08T11:58:08.914+00:00', 
                        'Name': 'usertest01_seller', 
                        'phone': '+7981ХХХХХХХ', 
                        'mailboxes': ['Rp5djUppTcqM1LQO_3x_gg', 'FrwMkbJJSfejzUb7a6RdoQ']
                        },
                    ]
                """

                # Ищем пользователя с совпадающим id_telegram
                for row in data.get("rows", []):
                    if str(row.get("id_telegram")) == str(id_telegram):
                        logger.info(f"Найден пользователь с id_telegram: {id_telegram}")
                        return True

                logger.info(f"Пользователь с id_telegram {id_telegram} не найден")
                return False

    except Exception as e:
        logger.error(f"Ошибка при проверке пользователя: {str(e)}", exc_info=True)
        return False


async def register_id_telegram(phone: str, id_telegram: str) -> bool:
    """Обращается по API к Seatable, ищет там пользователя по телефону и записывает его id_telegram."""
    try:
        # Получаем токен
        token_data = await get_base_token()
        if not token_data:
            logger.error("Не удалось получить токен SeaTable")
            return False

        base_url = f"{token_data['dtable_server']}api/v1/dtables/{token_data['dtable_uuid']}/rows/"
        headers = {
            "Authorization": f"Bearer {token_data['access_token']}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

        # Используем человекочитаемые названия колонок, а не их внутренние ключи
        phone_column = "phone"  # Колонка с телефонами
        id_telegram_column = "id_telegram"  # Колонка для id_telegram

        # Получаем параметры
        params = {
            "table_name": Config.SEATABLE_USERS_TABLE_ID,
            "convert_keys": "false"
        }

        async with aiohttp.ClientSession() as session:
            # Запрашиваем все строки
            async with session.get(base_url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    logger.error(f"Ошибка получения данных: {resp.status}")
                    return False

                data = await resp.json()
                rows = data.get("rows", [])

                for row in rows[:5]:
                    raw_phone = str(row.get(phone_column, "N/A"))
                    logger.debug(f"- Исходный: '{raw_phone}' | Нормализованный: '{normalize_phone(raw_phone)}'")

                # Ищем точное совпадение
                matched_row = None
                for row in rows:
                    if phone_column in row:
                        # Нормализуем телефон из таблицы перед сравнением
                        row_phone_normalized = normalize_phone(str(row[phone_column]))
                        if row_phone_normalized == phone:
                            matched_row = row
                            break

                if not matched_row:
                    logger.error("Совпадений не найдено. Проверьте:")
                    logger.error(
                        f"- Номер {phone} в таблице: {[normalize_phone(str(r.get(phone_column, ''))) for r in rows if phone_column in r]}")
                    logger.error(f"- Колонка телефон: {phone_column}")
                    return False

                row_id = matched_row.get("_id")
                if not row_id:
                    logger.error("У строки нет ID")
                    return False

                logger.info(f"Найдена строка пользователя для обновления (ID: {row_id})")

                # Подготовка обновления
                update_data = {
                    "table_name": Config.SEATABLE_USERS_TABLE_ID,
                    "row_id": row_id,
                    "row": {
                        id_telegram_column: str(id_telegram)
                    }
                }

                # Отправка обновления
                async with session.put(base_url, headers=headers, json=update_data) as resp:
                    if resp.status != 200:
                        logger.error(f"Ошибка обновления: {resp.status} - {await resp.text()}")
                        return False

                    logger.info(f"ID Telegram успешно добавлен для пользователя с телефоном {phone}")
                    return True

    except Exception as e:
        logger.error(f"Критическая ошибка: {str(e)}", exc_info=True)
        return False


async def get_users_to_send(email: str) -> list[str]:
    """Получает список id_telegram пользователей, подписанных на указанный email"""
    try:
        token_data = await get_base_token()
        if not token_data:
            logger.error("Не удалось получить токен SeaTable")
            return []

        base_url = f"{token_data['dtable_server']}api/v1/dtables/{token_data['dtable_uuid']}/rows/"
        headers = {
            "Authorization": f"Bearer {token_data['access_token']}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

        # Поиск mailbox по email
        mailboxes_params = {"table_name": Config.SEATABLE_MAILBOXES_TABLE_ID}
        async with aiohttp.ClientSession() as session:
            async with session.get(base_url, headers=headers, params=mailboxes_params) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"Ошибка получения mailboxes. Status: {resp.status}, Response: {error_text}")
                    return []

                mailboxes_data = await resp.json()
                logger.info(f"Получено mailboxes: {len(mailboxes_data.get('rows', []))} записей")

                target_mailbox = None
                found_emails = []  # Для логирования всех email в таблице

                for mailbox in mailboxes_data.get("rows", []):
                    current_email = str(mailbox.get("email", ""))
                    found_emails.append(current_email)

                    if current_email == str(email):
                        target_mailbox = mailbox
                        logger.info(f"Найден mailbox: {mailbox}")
                        break

                if not target_mailbox:
                    logger.error(f"Mailbox {email} не найден. Доступные email: {', '.join(found_emails)}")
                    return []

                # Получаем список пользователей из поля users
                user_ids = target_mailbox.get("users", [])
                logger.info(f"Найдены user_ids для {email}: {user_ids}")

                if not user_ids:
                    logger.error(f"Для ящика {email} поле users пустое или отсутствует")
                    return []

                # Получаем telegram_ids из таблицы users
                users_params = {"table_name": Config.SEATABLE_USERS_TABLE_ID}

                async with session.get(base_url, headers=headers, params=users_params) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"Ошибка получения users. Status: {resp.status}, Response: {error_text}")
                        return []

                    users_data = await resp.json()
                    users_rows = users_data.get("rows", [])
                    logger.info(f"Получено users: {len(users_rows)} записей")

                    # Собираем id_telegram нужных пользователей
                    valid_users = []

                    for user in users_rows:
                        id_seatable = user.get("_id")
                        tg_id = user.get("id_telegram")
                        if id_seatable in user_ids and tg_id:
                            valid_users.append(str(tg_id))
                    logger.info(f"Подходящие пользователи: {valid_users}")

                    return valid_users

    except Exception as e:
        logger.error(f"Критическая ошибка в get_users_idtg_to_send: {str(e)}", exc_info=True)
        return []

async def register_group(chat_id: int, chat_title: str) -> bool:
    """Обращается по API к Seatable, ищет группу по названию и записывает её id_telegram_chat.
    После записи, группа блокируется для перезаписи. То есть нельзя будет создать группу с таким же названием,
    перерегистрировать id_telegram_chat и перехватить рассылку."""
    logger.info(f"Начало регистрации группы: {chat_title} ({chat_id})")
    try:
        # Получаем токен
        token_data = await get_base_token()
        if not token_data:
            logger.error("Не удалось получить токен SeaTable")
            return False

        base_url = f"{token_data['dtable_server']}api/v1/dtables/{token_data['dtable_uuid']}/rows/"
        headers = {
            "Authorization": f"Bearer {token_data['access_token']}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

        # Используем названия колонок
        name_column = "Name"  # Колонка с названиями групп
        id_chat_column = "id_telegram_chat"  # Колонка для id чата
        lock_column = "is_locked"  # Колонка для блокировки

        # Получаем параметры
        params = {
            "table_name": Config.SEATABLE_T_CHATS_TABLE_ID,
            "convert_keys": "false"
        }

        async with aiohttp.ClientSession() as session:
            # Запрашиваем все строки
            async with session.get(base_url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    logger.error(f"Ошибка получения данных: {resp.status}")
                    return False

                data = await resp.json()
                rows = data.get("rows", [])

                # Ищем точное совпадение по названию группы
                matched_row = None
                for row in rows:
                    if name_column in row and str(row[name_column]).strip() == chat_title.strip():
                        matched_row = row
                        break

                if not matched_row:
                    logger.error("Группа не найдена. Проверьте:")
                    logger.error(f"- Название группы в Telegram: '{chat_title}'")
                    logger.error(f"- Названия групп в таблице: {[str(r.get(name_column, '')) for r in rows if name_column in r]}")
                    logger.error(f"- Колонка с названиями: {name_column}")
                    return False

                row_id = matched_row.get("_id")
                if not row_id:
                    logger.error("У строки нет ID")
                    return False

                # Проверяем блокировку
                if lock_column in matched_row and matched_row[lock_column]:
                    logger.error(f"Группа '{chat_title}' заблокирована для изменений")
                    return False

                logger.info(f"Найдена строка группы для обновления (ID: {row_id})")

                # Подготовка обновления (ID чата + блокировка)
                update_data = {
                    "table_name": Config.SEATABLE_T_CHATS_TABLE_ID,
                    "row_id": row_id,
                    "row": {
                        id_chat_column: str(chat_id),
                        lock_column: True  # Блокируем после записи
                    }
                }

                # Отправка обновления
                async with session.put(base_url, headers=headers, json=update_data) as resp:
                    if resp.status != 200:
                        logger.error(f"Ошибка обновления: {resp.status} - {await resp.text()}")
                        return False

                    logger.info(f"ID чата {chat_id} успешно добавлен и группа '{chat_title}' заблокирована для перезаписи.")
                    return True

    except Exception as e:
        logger.error(f"Критическая ошибка при регистрации группы: {str(e)}", exc_info=True)
        return False


async def get_chats_to_send(email: str) -> list[str]:
    """Получает список id_telegram групп (чатов), подписанных на указанный email"""
    try:
        token_data = await get_base_token()
        if not token_data:
            logger.error("Не удалось получить токен SeaTable")
            return []

        base_url = f"{token_data['dtable_server']}api/v1/dtables/{token_data['dtable_uuid']}/rows/"
        headers = {
            "Authorization": f"Bearer {token_data['access_token']}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

        # Поиск чатов по email
        t_chats_params = {"table_name": Config.SEATABLE_MAILBOXES_TABLE_ID}
        async with aiohttp.ClientSession() as session:
            async with session.get(base_url, headers=headers, params=t_chats_params) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"Ошибка получения t_chats. Status: {resp.status}, Response: {error_text}")
                    return []

                t_chats_data = await resp.json()
                logger.info(f"Получено t_chats: {len(t_chats_data.get('rows', []))} записей")

                target_t_chats = None
                found_emails = []  # Для логирования всех email в таблице

                for t_chat in t_chats_data.get("rows", []):
                    current_email = str(t_chat.get("email", ""))
                    found_emails.append(current_email)

                    if current_email == str(email):
                        target_t_chats = t_chat
                        logger.info(f"Найден чат: {t_chat}")
                        break

                if not target_t_chats:
                    logger.error(f"Mailbox {email} не найден. Доступные email: {', '.join(found_emails)}")
                    return []

                # Получаем список чатов из поля
                t_chats_ids = target_t_chats.get("t_chats", [])
                logger.info(f"Найдены t_chats_ids для {email}: {t_chats_ids}")

                if not t_chats_ids:
                    logger.error(f"Для ящика {email} поле t_chats пустое или отсутствует")
                    return []

                # Получаем telegram_ids из таблицы t_chats
                t_chats_params = {"table_name": Config.SEATABLE_T_CHATS_TABLE_ID}

                async with session.get(base_url, headers=headers, params=t_chats_params) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"Ошибка получения t_chats. Status: {resp.status}, Response: {error_text}")
                        return []

                    t_chats_data = await resp.json()
                    t_chats_rows = t_chats_data.get("rows", [])
                    logger.info(f"Получено users: {len(t_chats_rows)} записей")

                    # Собираем id_telegram нужных чатов
                    valid_t_chats = []

                    for t_chat in t_chats_rows:
                        id_seatable = t_chat.get("_id")
                        tg_id = t_chat.get("id_telegram_chat")
                        if id_seatable in t_chats_ids and tg_id:
                            valid_t_chats.append(str(tg_id))
                    logger.info(f"Подходящие чаты для рассылки: {valid_t_chats}")

                    return valid_t_chats

    except Exception as e:
        logger.error(f"Критическая ошибка в get_chats_to_send: {str(e)}", exc_info=True)
        return []


async def get_last_uid(email: str) -> str | None:
    """Получает last_uid (id последнего обработанного письма) из таблицы Mailbox по email"""
    try:
        # Получаем токен доступа
        token_data = await get_base_token()
        if not token_data:
            logger.error("Не удалось получить токен SeaTable")
            return None

        # Формируем URL и заголовки
        base_url = f"{token_data['dtable_server']}api/v1/dtables/{token_data['dtable_uuid']}/rows/"
        headers = {
            "Authorization": f"Bearer {token_data['access_token']}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        params = {"table_name": Config.SEATABLE_MAILBOXES_TABLE_ID}

        # Делаем запрос к API
        async with aiohttp.ClientSession() as session:
            async with session.get(base_url, headers=headers, params=params) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Ошибка запроса last_uid: {response.status}. Ответ: {error_text}")
                    return None

                data = await response.json()

                # Ищем запись с нужным email
                for row in data.get("rows", []):
                    if str(row.get("email")) == str(email):
                        last_uid = row.get("last_uid")
                        logger.debug(f"Найден last_uid для {email}: {last_uid}")
                        return last_uid if last_uid else None

                logger.info(f"Почтовый ящик {email} не найден в таблице")
                return None

    except Exception as e:
        logger.error(f"Ошибка при получении last_uid: {str(e)}", exc_info=True)
        return None


async def update_last_uid(email: str, uid: str) -> bool:
    """Обновляет last_uid для почтового ящика в таблице Mailbox"""
    try:
        # Получаем токен доступа
        token_data = await get_base_token()
        if not token_data:
            logger.error("Не удалось получить токен SeaTable")
            return False

        # Формируем URL и заголовки
        base_url = f"{token_data['dtable_server']}api/v1/dtables/{token_data['dtable_uuid']}/rows/"
        headers = {
            "Authorization": f"Bearer {token_data['access_token']}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        params = {
            "table_name": Config.SEATABLE_MAILBOXES_TABLE_ID,
            "convert_keys": "false"
        }

        async with aiohttp.ClientSession() as session:
            # Получаем все записи из таблицы
            async with session.get(base_url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    logger.error(f"Ошибка получения данных: {resp.status} - {await resp.text()}")
                    return False

                data = await resp.json()
                rows = data.get("rows", [])

                # Ищем запись с нужным email
                matched_row = None
                for row in rows:
                    if str(row.get("email")) == str(email):
                        matched_row = row
                        break

                if not matched_row:
                    logger.error(f"Почтовый ящик {email} не найден в таблице")
                    return False

                row_id = matched_row.get("_id")
                if not row_id:
                    logger.error("У найденной строки отсутствует _id")
                    return False

                logger.debug(f"Найдена запись для обновления (ID: {row_id})")

                # Подготавливаем данные для обновления
                update_data = {
                    "table_name": Config.SEATABLE_MAILBOXES_TABLE_ID,
                    "row_id": row_id,
                    "row": {
                        "last_uid": str(uid)  # Обновляем только last_uid
                    }
                }

                # Отправляем обновление
                async with session.put(base_url, headers=headers, json=update_data) as resp:
                    if resp.status != 200:
                        logger.error(f"Ошибка обновления: {resp.status} - {await resp.text()}")
                        return False

                    logger.info(f"Успешно обновлен last_uid для {email}: {uid}")
                    return True

    except Exception as e:
        logger.error(f"Ошибка при обновлении last_uid: {str(e)}", exc_info=True)
        return False

