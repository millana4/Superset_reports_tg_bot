import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from config import Config


# ──────────────────────── Маскирование ПД ────────────────────────

def mask_phone(phone: Optional[str]) -> str:
    """Маскирует телефон, оставляя только последние 3 цифры."""
    if not phone:
        return "<нет>"
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if len(digits) < 3:
        return "*" * len(digits)
    return "*" * (len(digits) - 3) + digits[-3:]


def mask_name(name: Optional[str]) -> str:
    """Маскирует имя/ФИО, оставляя только первые 3 символа."""
    if not name:
        return "<нет>"
    name = str(name)
    return name[:3] + "***"


def mask_pii(value: Optional[str]) -> str:
    """Универсальное маскирование: телефоноподобное → mask_phone, иначе mask_name."""
    if not value:
        return "<нет>"
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if digits and len(digits) >= 7:
        return mask_phone(value)
    return mask_name(value)


# ──────────────────────────── Настройка ────────────────────────────

def setup_logging():
    """Настройка логирования для всего проекта."""
    # Папка для логов в корне проекта; создаём при старте, если её нет
    log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "bot.log"

    # Уровень из переменной окружения LOG_LEVEL
    log_level = getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO)

    logger = logging.getLogger()
    logger.setLevel(log_level)

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Файловый обработчик: открываем файл сразу (delay=False), пишем без задержки
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding='utf-8',
        delay=False,
    )
    file_handler.setFormatter(formatter)

    # Flush после каждой записи — логи сразу оказываются в файле, не в буфере
    _orig_emit = file_handler.emit

    def _emit_and_flush(record):
        _orig_emit(record)
        try:
            file_handler.flush()
        except Exception:
            pass

    file_handler.emit = _emit_and_flush

    # Консольный обработчик
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # Добавляем обработчики один раз
    if not logger.handlers:
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    # Уровни шумных библиотек
    logging.getLogger('aiogram').setLevel(logging.INFO)
    logging.getLogger('aiohttp').setLevel(logging.WARNING)