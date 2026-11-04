import logging
import sqlite3
import time
from collections.abc import Callable

import requests
from vk_api.exceptions import ApiError

from ghetto_city.domain.catalog import GameCatalog
from ghetto_city.infrastructure.database import Database
from ghetto_city.media.catalog import MediaCatalog

logger = logging.getLogger(__name__)


def process_due_trips(
    database: Database,
    catalog: GameCatalog,
    media: MediaCatalog,
    send_message: Callable[[int, str, str], None],
    now: float | None = None,
) -> None:
    current_time = time.time() if now is None else now
    database.complete_due_trips(current_time)
    for notification in database.pending_notifications():
        city = catalog.destinations[notification["destination_city_id"]]
        transport = catalog.transports.get(notification["transport_id"])
        transport_name = notification["transport_name"] or (
            transport.name if transport else "личном транспорте"
        )
        transport_image = notification["transport_image"] or (
            transport.image if transport else None
        )
        if transport_image is None:
            raise ValueError(
                f"Trip notification {notification['id']} has no transport image"
            )
        image = media.image(transport_image)
        text = f"Вы прибыли в {city.name} на транспорте «{transport_name}»."
        send_message(notification["user_id"], text, str(image))
        database.mark_notification_sent(notification["id"], current_time)


def run_trip_worker(
    database: Database,
    catalog: GameCatalog,
    media: MediaCatalog,
    send_message: Callable[[int, str, str], None],
    poll_interval: float = 2,
) -> None:
    logger.info("Trip completion worker started")
    while True:
        try:
            process_due_trips(database, catalog, media, send_message)
        except (ApiError, requests.RequestException, sqlite3.Error, OSError):
            logger.exception("Trip completion batch failed; it will be retried")
        time.sleep(poll_interval)
