from pathlib import Path

from vk_api.upload import VkUpload


class VkPhotoUploader:
    def __init__(self, vk_session) -> None:
        self._upload = VkUpload(vk_session)
        self._attachments: dict[Path, str] = {}

    def attachment(self, image_path: Path) -> str:
        resolved = image_path.resolve()
        cached = self._attachments.get(resolved)
        if cached:
            return cached

        uploaded = self._upload.photo_messages(str(resolved))[0]
        owner_id = uploaded["owner_id"]
        photo_id = uploaded["id"]
        access_key = uploaded.get("access_key")
        attachment = f"photo{owner_id}_{photo_id}"
        if access_key:
            attachment += f"_{access_key}"
        self._attachments[resolved] = attachment
        return attachment
