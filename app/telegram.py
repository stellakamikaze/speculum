"""
Telegram Webhook notifications for Speculum
Sends notifications about crawl status, new requests, etc.
"""
import os
import requests
import logging
from typing import Optional

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def is_telegram_configured() -> bool:
    """Check if Telegram is properly configured"""
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def send_telegram_message(message: str, parse_mode: str = 'HTML') -> bool:
    """
    Send a message to the configured Telegram chat.

    Args:
        message: The message to send (supports HTML formatting)
        parse_mode: 'HTML' or 'Markdown'

    Returns:
        True if message was sent successfully, False otherwise
    """
    if not is_telegram_configured():
        logger.debug("Telegram not configured, skipping notification")
        return False

    try:
        url = TELEGRAM_API_URL.format(token=TELEGRAM_BOT_TOKEN)
        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message,
            'parse_mode': parse_mode,
            'disable_web_page_preview': True
        }

        response = requests.post(url, json=payload, timeout=10)

        if response.status_code == 200:
            logger.info("Telegram notification sent successfully")
            return True
        else:
            logger.warning(f"Telegram API returned {response.status_code}: {response.text}")
            return False

    except requests.RequestException as e:
        logger.error(f"Failed to send Telegram notification: {e}")
        return False


def notify_crawl_started(site_name: str, url: str) -> bool:
    """Notify when a crawl starts"""
    message = (
        f"🔄 <b>Crawl Avviato</b>\n"
        f"<b>Sito:</b> {escape_html(site_name)}\n"
        f"<b>URL:</b> {escape_html(url)}"
    )
    return send_telegram_message(message)


def notify_crawl_completed(site_name: str, url: str, pages: int, size_human: str) -> bool:
    """Notify when a crawl completes successfully"""
    message = (
        f"✅ <b>Crawl Completato</b>\n"
        f"<b>Sito:</b> {escape_html(site_name)}\n"
        f"<b>URL:</b> {escape_html(url)}\n"
        f"<b>Pagine:</b> {pages}\n"
        f"<b>Dimensione:</b> {size_human}"
    )
    return send_telegram_message(message)


def notify_crawl_failed(site_name: str, url: str, error: str) -> bool:
    """Notify when a crawl fails"""
    message = (
        f"❌ <b>Crawl Fallito</b>\n"
        f"<b>Sito:</b> {escape_html(site_name)}\n"
        f"<b>URL:</b> {escape_html(url)}\n"
        f"<b>Errore:</b> {escape_html(error[:200])}"
    )
    return send_telegram_message(message)


def notify_new_mirror_request(url: str, requester: Optional[str] = None) -> bool:
    """Notify when a new mirror request is submitted"""
    requester_text = requester or "Anonimo"
    message = (
        f"📝 <b>Nuova Richiesta Mirror</b>\n"
        f"<b>URL:</b> {escape_html(url)}\n"
        f"<b>Richiedente:</b> {escape_html(requester_text)}"
    )
    return send_telegram_message(message)


def notify_site_dead(site_name: str, url: str) -> bool:
    """Notify when a site is marked as dead"""
    message = (
        f"💀 <b>Sito Irraggiungibile</b>\n"
        f"<b>Sito:</b> {escape_html(site_name)}\n"
        f"<b>URL:</b> {escape_html(url)}\n"
        f"Il sito è stato marcato come morto dopo ripetuti tentativi."
    )
    return send_telegram_message(message)


def notify_daily_summary(stats: dict) -> bool:
    """Send a daily summary of the archive status"""
    message = (
        f"📊 <b>Riepilogo Giornaliero Speculum</b>\n\n"
        f"📁 Siti totali: {stats.get('total_sites', 0)}\n"
        f"✅ Pronti: {stats.get('ready', 0)}\n"
        f"🔄 In crawl: {stats.get('crawling', 0)}\n"
        f"❌ Errori: {stats.get('error', 0)}\n"
        f"💀 Morti: {stats.get('dead', 0)}\n"
        f"💾 Spazio totale: {stats.get('total_size_human', 'N/A')}"
    )
    return send_telegram_message(message)


def escape_html(text: str) -> str:
    """Escape HTML special characters for Telegram"""
    if not text:
        return ''
    return (
        str(text)
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
    )
