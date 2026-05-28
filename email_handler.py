import os
import time
import asyncio
import logging
import email.utils

from aiogram.types import BufferedInputFile
from imap_tools import MailBox, AND
from email.header import decode_header
from datetime import timezone, timedelta

from bot import bot
from db import get_last_uid, update_last_uid, get_subscribers_for_email


logger = logging.getLogger(__name__)


async def handle_email(email_msg):
    """
    Извлекает из письма тему и вложения (только изображения и PDF: jpg, jpeg, png, pdf).
    Текстовые части письма игнорируются. Тема редактируется для информативности.
    """
    # Допустимые форматы: по расширению имени файла и по content-type
    allowed_extensions = ('.pdf', '.png', '.jpg', '.jpeg')

    def detect_extension(fname: str | None, content_type: str) -> str | None:
        """Определяет допустимое расширение по имени файла, затем по content-type."""
        # 1) по имени файла
        if fname:
            low = fname.lower()
            for ext in allowed_extensions:
                if low.endswith(ext):
                    return ext
        # 2) по content-type
        ct = (content_type or '').lower()
        if 'pdf' in ct:
            return '.pdf'
        if 'png' in ct:
            return '.png'
        if 'jpeg' in ct or 'jpg' in ct:
            return '.jpg'
        return None

    try:
        # Получаем и парсим дату из письма (с конвертацией в московское время)
        date_str = email_msg['Date']
        parsed_date = email.utils.parsedate_to_datetime(date_str)

        # Конвертируем UTC в московское время (+3 часа)
        moscow_tz = timezone(timedelta(hours=3))
        moscow_date = parsed_date.astimezone(moscow_tz)

        # Форматируем дату
        formatted_date = moscow_date.strftime('%d.%m.%Y %H:%M')

        # Декодируем тему письма
        subject = email_msg['Subject'] or 'Без темы'
        decoded_subject = []
        for part, encoding in decode_header(subject):
            if isinstance(part, bytes):
                decoded_subject.append(part.decode(encoding or 'utf-8'))
            else:
                decoded_subject.append(str(part))
        subject = ' '.join(decoded_subject)

        # Обрабатываем тему: удаляем [Superset] и добавляем дату
        subject = subject.replace('[Superset]', '').strip()
        subject = f"{subject} {formatted_date}" if subject else formatted_date
        logger.info("Тема письма обработана")
        logger.debug(f"Тема: {subject}")

        attachments = []

        # Перебираем все части письма
        for part in email_msg.walk():
            # Пропускаем multipart-контейнеры
            if part.get_content_maintype() == 'multipart':
                continue

            # Явно игнорируем текстовые части письма (тело, html)
            if part.get_content_maintype() == 'text':
                continue

            content_disposition = str(part.get("Content-Disposition", "")).lower()
            filename = part.get_filename()

            # Берём только то, что выглядит как вложение
            if not (filename or 'attachment' in content_disposition):
                continue

            try:
                payload = part.get_payload(decode=True)
                if not payload:
                    continue

                # Декодируем имя файла с учётом разных кодировок
                if filename:
                    decoded_filename = []
                    for part_filename, encoding in decode_header(filename):
                        if isinstance(part_filename, bytes):
                            try:
                                try:
                                    decoded_part = part_filename.decode('utf-8')
                                except UnicodeDecodeError:
                                    decoded_part = part_filename.decode('koi8-r')
                                decoded_filename.append(decoded_part)
                            except Exception as e:
                                logger.warning(f"Ошибка декодирования имени файла: {e}")
                                decoded_filename.append(part_filename.decode('latin-1'))
                        else:
                            decoded_filename.append(str(part_filename))
                    filename = ''.join(decoded_filename)
                    logger.debug(f"Декодированное имя файла: {filename}")

                # Определяем допустимое расширение (по имени, затем по content-type)
                file_extension = detect_extension(filename, part.get_content_type())

                # Пропускаем всё, что не входит в допустимые форматы
                if not file_extension:
                    logger.debug(f"Пропущено вложение недопустимого типа: {filename}")
                    continue

                # Формируем имя файла
                if not filename:
                    # Имени нет (например, inline-картинка) — создаём своё
                    filename = f"attachment_{formatted_date.replace(':', '_')}{file_extension}"
                else:
                    if file_extension == '.pdf':
                        # Для PDF добавляем дату к имени
                        base_name = os.path.splitext(filename)[0]
                        filename = f"{base_name} {formatted_date}{file_extension}"
                    else:
                        # Для картинок гарантируем корректное расширение
                        if not filename.lower().endswith(allowed_extensions):
                            filename = f"{filename}{file_extension}"

                logger.info("Найдено вложение допустимого типа")
                logger.debug(f"Вложение: {filename} ({len(payload)} bytes)")
                attachments.append((filename, payload))

            except Exception as e:
                logger.error(f"Ошибка обработки вложения: {e}")
                logger.debug(f"Ошибка обработки вложения {filename}: {e}")

        logger.info(f"Итого найдено вложений: {len(attachments)}")
        return subject, attachments

    except Exception as e:
        logger.error(f"Критическая ошибка в handle_email: {e}", exc_info=True)
        raise

async def distribute_attachments(email: str, subject: str, attachments: list[tuple[str, bytes]]):
    """Рассылает вложения пользователям и чатам, подписанным на указанный email."""
    try:
        # За один запрос получаем и пользователей, и чаты
        telegram_users_ids, telegram_chats_ids = await get_subscribers_for_email(email)
        telegram_ids = telegram_users_ids + telegram_chats_ids

        if not telegram_ids:
            logger.warning("Нет подписчиков или групп для рассылки")
            logger.debug(f"distribute_attachments: нет получателей для {email}")
            return

        # Рассылаем вложения
        for telegram_id in telegram_ids:
            for filename, content in attachments:
                try:
                    await bot.send_document(
                        chat_id=telegram_id,
                        document=BufferedInputFile(content, filename=filename),
                        caption=subject if subject else None
                    )
                    logger.info("Вложение отправлено получателю")
                    logger.debug(f"[{email}] Отправлено {telegram_id}: {filename}")
                except Exception as e:
                    logger.error(f"Ошибка отправки получателю: {e}")
                    logger.debug(f"[{email}] Ошибка отправки {telegram_id}: {e}")

    except Exception as e:
        logger.error(f"Критическая ошибка рассылки: {e}", exc_info=True)


async def resend_report(message, account_email: str, loop: asyncio.AbstractEventLoop):
    """Запускает пересылку PDF-вложения и запускает обновление last_uid (последнего обработанного письма)"""
    try:
        logger.info("Обработка нового письма")
        logger.info(f"[{account_email}] UID={message.uid}, тема: {message.subject}")

        # Обработка письма и извлечение данных
        subject, attachments = await handle_email(message.obj)

        # Пересылка пользователям из БД
        if attachments:
            await distribute_attachments(account_email, subject, attachments)

            # Обновляем last_uid, если вложения были успешно отправлены
            await update_last_uid(account_email, str(message.uid))
        else:
            logger.info("Вложений нет, рассылка не требуется")
            logger.debug(f"[{account_email}] UID={message.uid}: вложений нет")

    except Exception as e:
        logger.error(f"Ошибка обработки письма: {e}", exc_info=True)
        logger.debug(f"[{account_email}] Ошибка обработки UID={message.uid}: {e}")

def imap_idle_listener(account, loop):
    """Слушает входящие письма на одном почтовом аккаунте через IMAP IDLE."""
    while True:
        try:
            with MailBox(account["imap"]).login(account["email"], account["password"]) as mailbox:
                mailbox.folder.set('INBOX')
                logger.info("IMAP подключён, выбрана папка INBOX")
                logger.debug(f"[{account['email']}] Подключён, ожидание писем...")

                while True:
                    logger.debug(f"[{account['email']}] Режим IDLE")
                    for _ in mailbox.idle.wait(timeout=300):  # Ждём новые письма до 5 минут
                        break

                    # Получаем все непрочитанные письма
                    messages = list(mailbox.fetch(AND(seen=False)))

                    if not messages:
                        logger.debug(f"[{account['email']}] Нет непрочитанных писем")
                        continue

                    # Получаем последний обработанный UID
                    last_uid = asyncio.run_coroutine_threadsafe(
                        get_last_uid(account['email']), loop
                    ).result()

                    # Преобразуем к int, если значение есть
                    last_uid = int(last_uid) if last_uid is not None else None

                    if last_uid is None:
                        # Обрабатываем только самое свежее письмо
                        latest_message = max(messages, key=lambda m: int(m.uid))
                        logger.info("Первая инициализация ящика")
                        logger.debug(f"[{account['email']}] Обрабатываем UID={latest_message.uid}")

                        asyncio.run_coroutine_threadsafe(
                            resend_report(latest_message, account['email'], loop),
                            loop
                        )
                        # После обработки обновим last_uid
                        asyncio.run_coroutine_threadsafe(
                            update_last_uid(account['email'], str(latest_message.uid)), loop
                        )
                        continue

                    # Фильтруем только новые письма
                    unseen_messages = [m for m in messages if int(m.uid) > last_uid]
                    if any(int(m.uid) < last_uid for m in messages):
                        logger.warning("Обнаружены письма с UID меньше последнего обработанного — игнорируются")
                        logger.debug(f"[{account['email']}] last_uid={last_uid}")

                    if not unseen_messages:
                        logger.debug(f"[{account['email']}] Новых писем нет")
                        continue

                    # Сортируем по UID (на всякий случай)
                    unseen_messages.sort(key=lambda m: int(m.uid))

                    # Обрабатываем каждое новое письмо
                    for message in unseen_messages:
                        asyncio.run_coroutine_threadsafe(
                            resend_report(message, account['email'], loop),
                            loop
                        )

        except Exception as e:
            logger.error(f"Ошибка подключения или работы с IMAP: {e}")
            logger.debug(f"[{account['email']}] IMAP error: {e}")
            time.sleep(10)
