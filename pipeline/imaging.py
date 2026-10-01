"""Deterministic image measurements. No AI.

Sharpness, brightness and resolution are arithmetic over pixels. Using a
model for these would add cost and non-determinism for no gain.
"""

import math
import os
from datetime import datetime
from typing import Optional

from PIL import ExifTags, Image, UnidentifiedImageError

# Reverse map so we can look up tag numbers by name
_TAG_IDS = {name: num for num, name in ExifTags.TAGS.items()}

# HEIC is what an iPhone shoots by default, so a reviewer photographing real
# damage will most often produce one. Pillow cannot read it alone. The import
# is optional: without the package the format simply is not offered, rather
# than the app failing to start.
try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF_AVAILABLE = True
except Exception:  # pragma: no cover - depends on the install
    HEIF_AVAILABLE = False

# Everything Pillow reads that a claim photograph plausibly arrives as.
# WEBP and HEIC usually reach us stripped of EXIF, which the authenticity
# stage flags rather than ignores.
_BASE_UPLOAD_TYPES = ["jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff", "gif"]


def supported_upload_types() -> list[str]:
    """Extensions the uploader should accept, given what is installed."""
    return _BASE_UPLOAD_TYPES + (["heic", "heif"] if HEIF_AVAILABLE else [])


# Video is accepted and never assessed: the MVP works from still photographs.
# Without these in the uploader, Streamlit refused a video inside the widget
# ("video/mp4 files are not allowed.") and the pipeline never saw it, so a
# video-only claim got no request for the photos it needs. A video is kept by
# name only: never written to disk, opened, hashed or sent to the model.
VIDEO_UPLOAD_TYPES = ["mp4", "mov", "m4v", "avi", "webm", "3gp"]


def is_video(filename: str) -> bool:
    """Decided by extension, the only thing the pipeline ever reads of a video."""
    return os.path.splitext(filename)[1].lower().lstrip(".") in VIDEO_UPLOAD_TYPES


def _laplacian_variance(img: Image.Image) -> float:
    """Variance of the Laplacian: the standard cheap sharpness measure.

    A blurred image has little high-frequency content, so the second
    derivative is small everywhere and its variance is low.
    """
    gray = img.convert("L")
    # Downscale large images so this stays fast and scale-independent
    gray.thumbnail((512, 512))
    px = gray.load()
    w, h = gray.size
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
    gray = img.convert("L")
    gray.thumbnail((256, 256))
    px = list(gray.getdata())
    return sum(px) / len(px) if px else 0.0


def _parse_exif_datetime(raw: str) -> Optional[datetime]:
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except (ValueError, TypeError):
            continue
    return None


def unreadable_reason(path: str) -> Optional[str]:
    """None if the file decodes fully as an image, otherwise a short reason.

    An upload is whatever the user picked. A renamed document, a zero-byte
    file or a half-transferred JPEG must be refused with a sentence, not
    allowed to reach measure() and take the review screen down with a
    traceback.
    """
    try:
        if os.path.getsize(path) == 0:
            return "the file is empty"
        with Image.open(path) as img:
            img.load()
        return None
    except UnidentifiedImageError:
        return "not a recognized image format"
    except OSError as e:
        return "the image data is incomplete or damaged" if "truncated" in str(e) \
            else "the file could not be decoded as an image"
    except Exception:
        return "the file could not be decoded as an image"


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
        # Cameras and phones write the capture time (DateTimeOriginal) into
        # the Exif sub-IFD, not the main block. getexif() returns only the main
        # block, whose DateTime is the LAST MODIFIED time. Reading only the
        # main block meant a photo taken before the loss and edited after it
        # passed the capture-window check. The sub-IFD is merged in and wins.
        try:
            sub = exif_raw.get_ifd(0x8769)
        except Exception:
            sub = {}
        for tag_id, value in (sub or {}).items():
            exif[ExifTags.TAGS.get(tag_id, str(tag_id))] = value

    # Capture time first, then digitized, and only then the modification time
    # as a last resort, since an edit rewrites DateTime.
    capture_time = None
    for key in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
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
