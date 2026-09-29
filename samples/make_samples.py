"""Generate synthetic test images that exercise the deterministic checks.

These are NOT car damage photos. They exist so the pipeline runs end to end
with zero setup, and so the quality gate can be demonstrated failing for real
reasons (measured sharpness, brightness and resolution) rather than simulated
ones. Replace them with real photographs for the recorded demo.
"""
import os, random
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
random.seed(7)

def base_image(w=1600, h=1200, bg=(120, 125, 132)):
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    mx, my = int(w * 0.075), int(h * 0.18)
    # crude "vehicle panel" with a damage region, enough to carry real edges
    d.rounded_rectangle([mx, my, w - mx, h - my], radius=max(8, w // 26), fill=(48, 62, 88))
    rx, ry = int(w * 0.12), int(h * 0.11)
    d.ellipse([w//2-rx, h//2-ry, w//2+rx, h//2+ry], fill=(92, 104, 124))
    for _ in range(900):
        x = random.randint(mx + 20, w - mx - 20); y = random.randint(my + 20, h - my - 20)
        d.point((x, y), fill=(random.randint(0,255),)*3)
    step = max(4, rx // 10)
    for i in range(18):
        x0 = w//2 - rx + i * step
        d.line([(x0, h//2 - int(ry*0.7)), (x0 + step*3, h//2 + int(ry*0.75))],
               fill=(196, 202, 210), width=max(1, w // 800))
    return img

def save(img, name, exif_dt=None):
    path = os.path.join(HERE, name)
    kwargs = {"quality": 92}
    if exif_dt:
        ex = Image.Exif()
        ex[271] = "DemoPhone"          # Make
        ex[272] = "Model X"            # Model
        ex[306] = exif_dt.strftime("%Y:%m:%d %H:%M:%S")   # DateTime
        ex[36867] = exif_dt.strftime("%Y:%m:%d %H:%M:%S") # DateTimeOriginal
        kwargs["exif"] = ex
    img.save(path, **kwargs)
    return path

# 1. Good photos for the clean path (CLM-1001)
for i, ang in enumerate(["a", "b", "c"], 1):
    save(base_image(), f"good_{ang}.jpg",
         exif_dt=datetime(2026, 9, 14, 14, 20) + timedelta(minutes=i))

# 2. Blurry -> fails sharpness (CLM-1002)
save(base_image().filter(ImageFilter.GaussianBlur(7)), "bad_blurry.jpg",
     exif_dt=datetime(2026, 9, 20, 11, 5))

# 3. Dark -> fails brightness (CLM-1002)
save(base_image(bg=(14, 15, 18)).point(lambda p: int(p * 0.16)), "bad_dark.jpg",
     exif_dt=datetime(2026, 9, 20, 22, 40))

# 4. Low resolution -> fails resolution (CLM-1002)
save(base_image(520, 390), "bad_lowres.jpg", exif_dt=datetime(2026, 9, 20, 11, 9))

# 5. Bumper photos for the ADAS surprise (CLM-1003)
for i, ang in enumerate(["a", "b", "c"], 1):
    save(base_image(bg=(136, 138, 142)), f"bumper_{ang}.jpg",
         exif_dt=datetime(2026, 9, 18, 16, 10) + timedelta(minutes=i))

# 6. Capture time PREDATES the loss -> authenticity flag (CLM-1004, loss 2026-09-22)
save(base_image(bg=(128, 130, 136)), "stale_timestamp.jpg",
     exif_dt=datetime(2026, 8, 30, 9, 15))
save(base_image(bg=(128, 130, 136)), "stale_timestamp_2.jpg",
     exif_dt=datetime(2026, 8, 30, 9, 17))

print("Generated:")
for f in sorted(os.listdir(HERE)):
    if f.endswith(".jpg"):
        print("  ", f)
