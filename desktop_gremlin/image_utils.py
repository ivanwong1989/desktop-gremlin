from __future__ import annotations

import base64
from io import BytesIO
import os

from PIL import Image, UnidentifiedImageError


ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
MAX_INPUT_IMAGE_BYTES = 25 * 1024 * 1024


def image_file_to_base64(path: str, max_side: int = 1600, jpeg_quality: int = 90) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_IMAGE_EXTENSIONS))
        raise ValueError(f"Unsupported image type. Use one of: {allowed}")

    try:
        size = os.path.getsize(path)
    except OSError as exc:
        raise ValueError(f"Could not read image file: {exc}") from exc

    if size > MAX_INPUT_IMAGE_BYTES:
        mb = MAX_INPUT_IMAGE_BYTES // (1024 * 1024)
        raise ValueError(f"Image is too large. Maximum input size is {mb} MB.")

    try:
        with Image.open(path) as image:
            image.load()
            if max(image.size) > max_side:
                image.thumbnail((max_side, max_side), Image.LANCZOS)

            output = BytesIO()
            if _has_transparency(image):
                png_image = image.convert("RGBA")
                png_image.save(output, format="PNG", optimize=True)
            else:
                rgb_image = image.convert("RGB")
                rgb_image.save(output, format="JPEG", quality=jpeg_quality, optimize=True)
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError(f"Invalid image file: {exc}") from exc

    return base64.b64encode(output.getvalue()).decode("ascii")


def _has_transparency(image: Image.Image) -> bool:
    if image.mode in ("RGBA", "LA"):
        return True
    if image.mode == "P" and "transparency" in image.info:
        return True
    return False

