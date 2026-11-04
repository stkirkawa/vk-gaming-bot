import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    vk_bot_token: str
    vk_group_id: int
    database_path: Path
    media_dir: Path


def load_settings() -> Settings:
    load_dotenv()

    vk_bot_token = os.environ.get("VK_BOT_TOKEN", "").strip()
    if not vk_bot_token:
        raise ValueError("VK_BOT_TOKEN must be set in the environment")

    group_id = os.environ.get("VK_GROUP_ID", "").strip()
    if not group_id:
        raise ValueError("VK_GROUP_ID must be set in the environment")
    try:
        vk_group_id = int(group_id)
    except ValueError as error:
        raise ValueError("VK_GROUP_ID must be a positive integer") from error
    if vk_group_id <= 0:
        raise ValueError("VK_GROUP_ID must be a positive integer")

    database_path = Path(os.environ.get("DATABASE_PATH", "data/ghetto_city.sqlite3"))
    media_dir = Path(os.environ.get("MEDIA_DIR", "assets"))
    return Settings(
        vk_bot_token=vk_bot_token,
        vk_group_id=vk_group_id,
        database_path=database_path,
        media_dir=media_dir,
    )
