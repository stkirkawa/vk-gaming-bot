from pathlib import Path

import pytest

from ghetto_city.settings import load_settings


@pytest.fixture(autouse=True)
def prevent_loading_local_secrets(monkeypatch):
    monkeypatch.setattr("ghetto_city.settings.load_dotenv", lambda: None)


def test_load_settings_reads_environment(monkeypatch):
    monkeypatch.setenv("VK_BOT_TOKEN", "test-token")
    monkeypatch.setenv("VK_GROUP_ID", "123")
    monkeypatch.setenv("DATABASE_PATH", "test-data/game.sqlite3")
    monkeypatch.setenv("MEDIA_DIR", "test-assets")

    settings = load_settings()

    assert settings.vk_bot_token == "test-token"
    assert settings.vk_group_id == 123
    assert settings.database_path == Path("test-data/game.sqlite3")
    assert settings.media_dir == Path("test-assets")


@pytest.mark.parametrize("missing", ["VK_BOT_TOKEN", "VK_GROUP_ID"])
def test_load_settings_requires_credentials(monkeypatch, missing):
    monkeypatch.setenv("VK_BOT_TOKEN", "test-token")
    monkeypatch.setenv("VK_GROUP_ID", "123")
    monkeypatch.delenv(missing)

    with pytest.raises(ValueError, match=missing):
        load_settings()


@pytest.mark.parametrize("group_id", ["abc", "0", "-2"])
def test_load_settings_rejects_invalid_group_id(monkeypatch, group_id):
    monkeypatch.setenv("VK_BOT_TOKEN", "test-token")
    monkeypatch.setenv("VK_GROUP_ID", group_id)

    with pytest.raises(ValueError, match="VK_GROUP_ID"):
        load_settings()
