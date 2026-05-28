import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Telegram
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    BOT_PROXY = os.getenv("BOT_PROXY")  # только для дебага; на сервере оставить пустым

    # IMAP
    IMAP_SERVER = os.getenv("IMAP_SERVER")
    IMAP_EMAIL_SR01 = os.getenv("IMAP_EMAIL_SR01")
    IMAP_PASSWORD_SR01 = os.getenv("IMAP_PASSWORD_SR01")
    IMAP_EMAIL_SR02 = os.getenv("IMAP_EMAIL_SR02")
    IMAP_PASSWORD_SR02 = os.getenv("IMAP_PASSWORD_SR02")
    IMAP_EMAIL_SR03 = os.getenv("IMAP_EMAIL_SR03")
    IMAP_PASSWORD_SR03 = os.getenv("IMAP_PASSWORD_SR03")
    IMAP_EMAIL_SR04 = os.getenv("IMAP_EMAIL_SR04")
    IMAP_PASSWORD_SR04 = os.getenv("IMAP_PASSWORD_SR04")

    # NocoDB
    NOCODB_SERVER = os.getenv("NOCODB_SERVER")
    NOCODB_API_TOKEN = os.getenv("NOCODB_API_TOKEN")
    NOCODB_USERS_TABLE_ID = os.getenv("NOCODB_USERS_TABLE_ID")
    NOCODB_MAILBOXES_TABLE_ID = os.getenv("NOCODB_MAILBOXES_TABLE_ID")
    NOCODB_CHATS_TABLE_ID = os.getenv("NOCODB_CHATS_TABLE_ID")

    # Логирование
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
