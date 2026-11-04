import hashlib
import json
import logging
import sqlite3

import requests
from vk_api.bot_longpoll import VkBotEventType, VkBotLongPoll
from vk_api.exceptions import ApiError

from ghetto_city.vk_gateway.application import BotApplication

logger = logging.getLogger(__name__)

CHAT_INVITE_ACTIONS = {"chat_invite_user", "chat_invite_user_by_link"}


def _message_event_id(message, raw_event: dict) -> str:
    peer_id = getattr(message, "peer_id", 0) or 0
    conversation_message_id = getattr(message, "conversation_message_id", 0) or 0
    if conversation_message_id:
        return f"message:{peer_id}:{conversation_message_id}"

    message_id = getattr(message, "id", 0) or 0
    if message_id:
        return f"message:{message_id}"

    serialized = json.dumps(raw_event, ensure_ascii=True, sort_keys=True, default=str)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return f"message:fallback:{digest}"


def _message_action_type(message) -> str | None:
    action = getattr(message, "action", None)
    if action is None:
        return None
    if isinstance(action, dict):
        return action.get("type")
    return getattr(action, "type", None)


class VkLongPollGateway:
    def __init__(self, vk_session, group_id: int, application: BotApplication) -> None:
        self._vk_session = vk_session
        self._api = vk_session.get_api()
        self._longpoll = VkBotLongPoll(vk_session, group_id)
        self._application = application

    def run(self) -> None:
        logger.info("VK community long poll started")
        for event in self._longpoll.listen():
            try:
                if event.type == VkBotEventType.MESSAGE_NEW:
                    message = event.message
                    if message is None or message.from_id <= 0:
                        continue
                    action_type = _message_action_type(message)
                    event_id = _message_event_id(message, event.raw)
                    if (
                        message.peer_id >= 2_000_000_000
                        and action_type in CHAT_INVITE_ACTIONS
                    ):
                        self._application.handle_chat_invite(
                            peer_id=message.peer_id,
                            event_id=event_id,
                        )
                        continue
                    self._application.handle_message(
                        user_id=message.from_id,
                        peer_id=message.peer_id,
                        text=message.text or "",
                        event_id=event_id,
                    )
                elif event.type == VkBotEventType.MESSAGE_EVENT:
                    self._answer_callback(event)
                    self._application.handle_callback(
                        user_id=event.obj.user_id,
                        peer_id=event.obj.peer_id,
                        payload=event.obj.payload,
                        event_id=f"callback:{event.obj.event_id}",
                    )
            except (ApiError, requests.RequestException, sqlite3.Error, OSError):
                logger.exception("Failed to process VK event %s", event.type)

    def _answer_callback(self, event) -> None:
        self._api.messages.sendMessageEventAnswer(
            event_id=event.obj.event_id,
            user_id=event.obj.user_id,
            peer_id=event.obj.peer_id,
        )
