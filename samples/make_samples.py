"""Generate synthetic test images that exercise the deterministic checks.

These are NOT car damage photos. They exist so the pipeline runs end to end
with zero setup, and so the quality gate can be demonstrated failing for real
reasons (measured sharpness, brightness and resolution) rather than simulated
ones. The real photographs in this folder are used for the recorded demo.

WHY EACH CLAIM GETS ITS OWN COMPOSITION
---------------------------------------
A perceptual hash is a signature of an image's LOW-FREQUENCY LUMINANCE LAYOUT:
where the light and dark regions sit, at roughly 32x32 resolution. It ignores
fine detail almost entirely, which is the whole point, since that is what makes
it survive resizing and recompression.

The first version of this file drew every sample from one composition and
varied only a random speckle pattern. Speckle is high-frequency, so it does not
move the hash at all. The result was that all fourteen synthetic files hashed
to within the duplicate threshold of one another, and two of them were at
distance ZERO.

The authenticity screen flags a photo when it is near-identical to one already
recorded against a DIFFERENT claim. With every sample colliding, the flag fired
on whichever scripted claim was opened second, third and fourth, purely as a
function of click order. That put a fraud flag on the Camry and dropped its
confidence from 0.60 to 0.40, contradicting the worked example in the PRD.

So each claim's photographs now get their own SCENE: a different panel
geometry, damage position, hatch direction and tonal layout. Within a claim the
images stay similar, which is correct, because three angles of one dent should
look alike, and the screen skips same-claim comparisons anyway.

ui_test.py asserts that no two samples belonging to different claims fall
within the duplicate threshold, so this cannot silently come back.
"""
import os
import random
from datetime import datetime, timedelta

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))


def scene(seed: int, w=1600, h=1200, bg=(120, 125, 132)):
    """One composition. The same seed always yields the same layout.

    Everything varied here is large-scale on purpose: panel position and size,
    where the damage sits, which way the scratches run, and where the broad
    light and dark bands fall. Those are the things a perceptual hash actually
    sees.
    """
    rng = random.Random(seed)
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)

    # Panel: position and proportions differ per scene.
    mx = int(w * rng.uniform(0.05, 0.16))
    my = int(h * rng.uniform(0.12, 0.26))
    panel = (rng.randint(36, 74), rng.randint(52, 96), rng.randint(74, 128))
    d.rounded_rectangle([mx, my, w - mx, h - my],
                        radius=max(8, w // rng.randint(18, 34)), fill=panel)

    # Broad tonal bands. These carry most of the hash, so their orientation and
    # placement are what actually separates one scene from another.
    for _ in range(rng.randint(2, 4)):
        if rng.random() < 0.5:
            y0 = rng.randint(my, h - my - 80)
            d.rectangle([mx, y0, w - mx, y0 + rng.randint(60, 190)],
                        fill=tuple(min(255, c + rng.randint(22, 58)) for c in panel))
        else:
            x0 = rng.randint(mx, w - mx - 80)
            d.rectangle([x0, my, x0 + rng.randint(60, 190), h - my],
                        fill=tuple(max(0, c - rng.randint(18, 46)) for c in panel))

    # Damage region, placed away from center so scenes do not converge.
    cx = int(w * rng.uniform(0.28, 0.72))
    cy = int(h * rng.uniform(0.32, 0.68))
    rx, ry = int(w * rng.uniform(0.08, 0.17)), int(h * rng.uniform(0.07, 0.15))
    d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry],
              fill=tuple(min(255, c + rng.randint(30, 70)) for c in panel))

    # Scratches. Direction flips per scene, which moves the hash further.
    step = max(4, rx // rng.randint(6, 12))
    down = rng.random() < 0.5
    for i in range(rng.randint(12, 24)):
        x0 = cx - rx + i * step
        y0 = cy - int(ry * 0.7) if down else cy + int(ry * 0.7)
        y1 = cy + int(ry * 0.75) if down else cy - int(ry * 0.75)
        d.line([(x0, y0), (x0 + step * 3, y1)],
               fill=(196, 202, 210), width=max(1, w // 800))

    # Fine speckle. Gives the sharpness measure real edges to find. It does not
    # affect the perceptual hash, which is exactly why it cannot be relied on
    # to separate scenes.
    for _ in range(900):
        x = rng.randint(mx + 20, w - mx - 20)
        y = rng.randint(my + 20, h - my - 20)
        d.point((x, y), fill=(rng.randint(0, 255),) * 3)

    return img


def save(img, name, exif_dt=None):
    path = os.path.join(HERE, name)
    kwargs = {"quality": 92}
    if exif_dt:
        ex = Image.Exif()
        ex[271] = "DemoPhone"                              # Make
        ex[272] = "Model X"                                # Model
        ex[306] = exif_dt.strftime("%Y:%m:%d %H:%M:%S")    # DateTime
        ex[36867] = exif_dt.strftime("%Y:%m:%d %H:%M:%S")  # DateTimeOriginal
        kwargs["exif"] = ex
    img.save(path, **kwargs)
    return path


# Seeds are spread widely and chosen so that the resulting scenes clear the
# duplicate threshold against every other claim's set. ui_test.py verifies it.
SEED_GOOD, SEED_BAD, SEED_BUMPER, SEED_STALE = 101, 233, 419, 577
SEED_SIDESWIPE = 811

# 1. Good photos for the clean path (fallback set)
for i, ang in enumerate(["a", "b", "c"], 1):
    save(scene(SEED_GOOD + i), f"good_{ang}.jpg",
         exif_dt=datetime(2026, 9, 14, 14, 20) + timedelta(minutes=i))

# 2. Blurry -> fails sharpness (CLM-1002 attempt 1)
save(scene(SEED_BAD).filter(ImageFilter.GaussianBlur(7)), "bad_blurry.jpg",
     exif_dt=datetime(2026, 9, 20, 11, 5))

# 3. Dark -> fails brightness (CLM-1002 attempt 1)
save(scene(SEED_BAD + 1, bg=(14, 15, 18)).point(lambda p: int(p * 0.16)),
     "bad_dark.jpg", exif_dt=datetime(2026, 9, 20, 22, 40))

# 4. Low resolution -> fails resolution (CLM-1002 attempt 1)
save(scene(SEED_BAD + 2, 520, 390), "bad_lowres.jpg",
     exif_dt=datetime(2026, 9, 20, 11, 9))

# 5. Bumper photos for the ADAS surprise (CLM-1003)
for i, ang in enumerate(["a", "b", "c"], 1):
    save(scene(SEED_BUMPER + i, bg=(136, 138, 142)), f"bumper_{ang}.jpg",
         exif_dt=datetime(2026, 9, 18, 16, 10) + timedelta(minutes=i))

# 6. Capture time PREDATES the loss -> authenticity flag (CLM-1004, loss 2026-09-22)
save(scene(SEED_STALE, bg=(128, 130, 136)), "stale_timestamp.jpg",
     exif_dt=datetime(2026, 8, 30, 9, 15))
save(scene(SEED_STALE + 1, bg=(128, 130, 136)), "stale_timestamp_2.jpg",
     exif_dt=datetime(2026, 8, 30, 9, 17))

# 7. Side-swipe for the low confidence claim (CLM-1007, loss 2026-09-24).
# Wide, low aspect: a side-swipe is photographed along the length of the car.
for i, ang in enumerate(["a", "b", "c"], 1):
    save(scene(SEED_SIDESWIPE + i, w=1800, h=1100, bg=(132, 134, 138)),
         f"sideswipe_{ang}.jpg",
         exif_dt=datetime(2026, 9, 24, 17, 30) + timedelta(minutes=i))

print("Generated:")
for f in sorted(os.listdir(HERE)):
    if f.endswith(".jpg"):
        print("  ", f)
