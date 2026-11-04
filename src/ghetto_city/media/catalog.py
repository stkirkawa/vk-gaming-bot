from pathlib import Path


class MediaCatalog:
    def __init__(self, media_dir: Path) -> None:
        self.image_dir = media_dir / "images"

    def image(self, filename: str) -> Path:
        path = self.image_dir / filename
        if not path.is_file():
            raise FileNotFoundError(f"Required bot image is missing: {path}")
        return path
