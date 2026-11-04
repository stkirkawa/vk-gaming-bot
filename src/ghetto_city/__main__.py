import logging
import threading
from pathlib import Path

import vk_api

from ghetto_city.application.game_service import GameService
from ghetto_city.domain.catalog import GameCatalog
from ghetto_city.infrastructure.database import Database
from ghetto_city.jobs.trip_worker import run_trip_worker
from ghetto_city.media.catalog import MediaCatalog
from ghetto_city.settings import load_settings
from ghetto_city.vk_gateway.application import BotApplication
from ghetto_city.vk_gateway.longpoll import VkLongPollGateway
from ghetto_city.vk_gateway.sender import VkMessageSender


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = load_settings()
    project_root = Path(__file__).resolve().parents[2]
    catalog = GameCatalog.load(project_root / "config" / "gameplay.json")
    media_dir = settings.media_dir
    if not media_dir.is_absolute():
        media_dir = project_root / media_dir

    database = Database(settings.database_path)
    database.initialize()
    media = MediaCatalog(media_dir)
    vk_session = vk_api.VkApi(token=settings.vk_bot_token)
    sender = VkMessageSender(vk_session, vk_session.get_api(), media)
    service = GameService(database, catalog)
    application = BotApplication(
        database, catalog, service, media, sender, settings.vk_group_id
    )

    worker = threading.Thread(
        target=run_trip_worker,
        args=(database, catalog, media, sender.send_notification),
        name="trip-worker",
        daemon=True,
    )
    worker.start()
    VkLongPollGateway(vk_session, settings.vk_group_id, application).run()


if __name__ == "__main__":
    main()
