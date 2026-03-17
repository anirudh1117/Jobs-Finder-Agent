"""Telegram Bot webhook handler for account verification and linking."""

from __future__ import annotations

import json
import logging
import uuid

import requests
from django.http import HttpRequest, JsonResponse
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.database.models import TelegramVerification, UserProfile
from core.config.settings import TELEGRAM_BOT_TOKEN

logger = logging.getLogger(__name__)


@csrf_exempt
@require_http_methods(["POST"])
def telegram_webhook(request: HttpRequest) -> JsonResponse:
    """Handle inbound Telegram messages for bot-first account linking.

    The bot no longer relies on payload-bearing `/start` commands. Any normal
    message from a Telegram user is enough to capture the chat ID and return an
    authenticated web confirmation URL.
    """

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Received malformed Telegram webhook payload.")
        return JsonResponse({"ok": True}, status=200)

    try:
        message = data.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "")

        if not chat_id:
            logger.warning("Received Telegram update missing chat_id.")
            return JsonResponse({"ok": True}, status=200)

        _handle_chat_link_request(
            request=request,
            chat_id=chat_id,
            text=str(text or "").strip(),
        )

        return JsonResponse({"ok": True}, status=200)

    except Exception as e:
        logger.exception("Error processing Telegram webhook: %s", str(e))
        return JsonResponse({"ok": True}, status=200)


def _handle_chat_link_request(request: HttpRequest, chat_id: int | str, text: str) -> None:
    """Create a pending verification and send a web confirmation link to Telegram."""

    chat_id_str = str(chat_id)
    existing_profile = UserProfile.objects.filter(telegram_chat_id=chat_id_str).select_related("user").first()
    if existing_profile is not None:
        logger.info("Telegram chat %s is already linked to user=%s", chat_id_str, existing_profile.user.username)
        _send_telegram_message(
            chat_id,
            "This Telegram account is already linked. If you need to switch accounts, unlink it from the website first.",
        )
        return

    TelegramVerification.objects.filter(chat_id=chat_id_str, is_used=False).delete()
    verification = TelegramVerification.objects.create(
        token=uuid.uuid4().hex,
        chat_id=chat_id_str,
    )
    confirm_url = request.build_absolute_uri(
        reverse("connect-telegram-confirm", kwargs={"token": verification.token})
    )

    logger.info("Telegram pending verification created for chat_id=%s", chat_id_str)
    _send_telegram_message(
        chat_id,
        (
            "Open this confirmation link while logged in to Freelance Agent to finish linking your Telegram account:\n\n"
            f"{confirm_url}\n\n"
            "If this link expires, return to the bot and press Start again."
        ),
    )


def _send_telegram_message(chat_id: int | str, text: str) -> bool:
    """Send a message to a Telegram user.

    Args:
        chat_id: Telegram chat ID (numeric or string).
        text: Message content to send.

    Returns:
        True if message sent successfully, otherwise False.
    """

    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not configured.")
        return False

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
    }

    try:
        response = requests.post(api_url, json=payload, timeout=20)
        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            logger.error(f"Telegram API rejected message: {data}")
            return False

        logger.info(f"Telegram message sent to {chat_id}")
        return True

    except requests.RequestException as e:
        logger.exception(f"Failed to send Telegram message: {str(e)}")
        return False
    except ValueError as e:
        logger.exception(f"Failed to decode Telegram API response: {str(e)}")
        return False
