"""Deterministic image measurements. No AI.

Sharpness, brightness and resolution are arithmetic over pixels. Using a
model for these would add cost and non-determinism for no gain.
"""

import math
from datetime import datetime
from typing import Optional

from PIL import Image, ExifTags

# Reverse map so we can look up tag numbers by name
_TAG_IDS = {name: num for num, name in ExifTags.TAGS.items()}


def _laplacian_variance(img: Image.Image) -> float:
    """Variance of the Laplacian: the standard cheap sharpness measure.

    A blurred image has little high-frequency content, so the second
    derivative is small everywhere and its variance is low.
    """
    grey = img.convert("L")
    # Downscale large images so this stays fast and scale-independent
    grey.thumbnail((512, 512))
    px = grey.load()
    w, h = grey.size
    if w < 3 or h < 3:
        return 0.0

    values = []
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            lap = (
                -4 * px[x, y]
                + px[x - 1, y] + px[x + 1, y]
                + px[x, y - 1] + px[x, y + 1]
            )
            values.append(lap)

    n = len(values)
    if n == 0:
        return 0.0
    mean = sum(values) / n
    return sum((v - mean) ** 2 for v in values) / n


def _mean_brightness(img: Image.Image) -> float:
    grey = img.convert("L")
    grey.thumbnail((256, 256))
    px = list(grey.getdata())
    return sum(px) / len(px) if px else 0.0


def _parse_exif_datetime(raw: str) -> Optional[datetime]:
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except (ValueError, TypeError):
            continue
    return None


def measure(path: str) -> dict:
    """Return every deterministic signal we can read from one image file."""
    with Image.open(path) as img:
        img.load()
        width, height = img.size
        sharpness = _laplacian_variance(img)
        brightness = _mean_brightness(img)
        exif_raw = img.getexif()

        # Perceptual hash, for detecting the same photo reused across claims
        try:
            import imagehash
            phash = str(imagehash.phash(img.convert("RGB")))
        except Exception:
            phash = ""

    exif = {}
    if exif_raw:
        for tag_id, value in exif_raw.items():
            name = ExifTags.TAGS.get(tag_id, str(tag_id))
            exif[name] = value

    capture_time = None
    for key in ("DateTimeOriginal", "DateTime", "DateTimeDigitized"):
        if key in exif:
            capture_time = _parse_exif_datetime(str(exif[key]))
            if capture_time:
                break

    make = str(exif.get("Make", "")).strip() or None
    model = str(exif.get("Model", "")).strip() or None
    device = " ".join(p for p in (make, model) if p) or None

    software = str(exif.get("Software", "")).strip() or None

    return {
        "width": width,
        "height": height,
        "sharpness": round(sharpness, 2),
        "brightness": round(brightness, 2),
        "exif_present": bool(exif),
        "capture_time": capture_time,
        "device": device,
        "editing_software": software,
        "perceptual_hash": phash,
    }


def hamming(a: str, b: str) -> int:
    """Hamming distance between two hex perceptual hashes."""
    if not a or not b or len(a) != len(b):
        return 999
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except ValueError:
        return 999
