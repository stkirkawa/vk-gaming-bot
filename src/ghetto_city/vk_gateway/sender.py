import secrets
import threading
from pathlib import Path

from ghetto_city.media.catalog import MediaCatalog
from ghetto_city.media.vk_upload import VkPhotoUploader


class VkMessageSender:
    def __init__(self, vk_session, api, media: MediaCatalog) -> None:
        self._api = api
        self._photos = VkPhotoUploader(vk_session)
        self._media = media
        self._lock = threading.Lock()

    def send(
        self,
        peer_id: int,
        text: str,
        image: str,
        keyboard: str | None = None,
    ) -> None:
        with self._lock:
            image_path = self._media.image(image)
            attachment = self._photos.attachment(image_path)
            params = {
                "peer_id": peer_id,
                "random_id": secrets.randbits(31) or 1,
                "message": text,
                "attachment": attachment,
            }
            if keyboard:
                params["keyboard"] = keyboard
            self._api.messages.send(**params)

    def send_notification(self, user_id: int, text: str, image_path: str) -> None:
        image_name = Path(image_path).name
        self.send(user_id, text, image_name)
