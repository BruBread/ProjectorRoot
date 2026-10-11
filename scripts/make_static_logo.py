#!/usr/bin/env python3
"""Replace the U-Boot/kernel static boot logo inside a Rockchip boot.img, IN PLACE.

Finds the 1024x576 24bpp BMP (the "Smart Projector" splash) in boot_orig.img and
overwrites ONLY its pixel bytes with a new CRT/synthwave image, keeping the BMP
header and total byte size identical -> the RESOURCE index stays valid, no repack
tool needed, no signature (AVB is disabled on this device).

Usage: python make_static_logo.py <boot_orig.img> <out_dir>
Outputs: <out_dir>/boot_patched.img, <out_dir>/static_logo_preview.png
This script only writes local files. It does NOT flash anything.
"""
import sys, struct, os, numpy as np
from PIL import Image, ImageFilter, ImageDraw, ImageFont

boot_path, outdir = sys.argv[1], sys.argv[2]
img = bytearray(open(boot_path, "rb").read())

# locate the 1024x576 24bpp BMP
target = None
i = 0
while True:
    i = img.find(b"BM", i)
    if i < 0:
        break
    if i + 54 <= len(img):
        fsize = struct.unpack_from("<I", img, i + 2)[0]
        dib = struct.unpack_from("<I", img, i + 14)[0]
        w = struct.unpack_from("<i", img, i + 18)[0]
        h = struct.unpack_from("<i", img, i + 22)[0]
        bpp = struct.unpack_from("<H", img, i + 28)[0]
        if dib in (40, 108, 124) and abs(w) == 1024 and abs(h) == 576 and bpp == 24:
            data_off = struct.unpack_from("<I", img, i + 10)[0]  # pixel array offset
            target = (i, fsize, w, h, bpp, data_off)
            break
    i += 2
if not target:
    sys.exit("1024x576 24bpp BMP not found")
off, fsize, W, Hsign, bpp, data_off = target
H = abs(Hsign)
topdown = Hsign < 0
print(f"found logo BMP @ {off:#x} size {fsize} {W}x{Hsign} {bpp}bpp pixel_off={data_off} topdown={topdown}")

# ---- render the new 1024x576 image (CRT/synthwave, matches the animation) ----
W2, H2 = 1024, 576
ys = np.linspace(0, 1, H2)[:, None]
xs = np.linspace(0, 1, W2)[None, :]
BG = np.array([5, 7, 15], float)
CYAN = np.array([0, 229, 255], float)
MAGENTA = np.array([255, 45, 149], float)
WHITE = np.array([235, 245, 255], float)

def blur(mask, r):
    im = Image.fromarray(np.clip(mask, 0, 255).astype(np.uint8))
    return np.asarray(im.filter(ImageFilter.GaussianBlur(r)), float)

# STYLE=line -> a single centered horizontal line, identical to the animation's
# first frame, so the CRT turn-on continues FROM this static logo.
if os.environ.get("LOGO_STYLE", "line") == "line":
    scene = np.ones((H2, W2, 3), float) * BG
    ysl = np.linspace(0, 1, H2)
    line = np.exp(-((ysl - 0.5) ** 2) / (2 * 0.0016 ** 2))
    scene += line[:, None, None] * WHITE
    scene += blur(line * 255, 10)[:, :, None] / 255 * CYAN * 0.7
    final = Image.fromarray(np.clip(scene, 0, 255).astype(np.uint8))
    final.save(os.path.join(outdir, "static_logo_preview.png"))
    rgb = np.asarray(final.convert("RGB")); bgr = rgb[:, :, ::-1]
    if not topdown: bgr = bgr[::-1, :, :]
    pixbytes = bgr.tobytes(); expected = W * H * 3
    assert len(pixbytes) == expected
    img[off + data_off: off + data_off + expected] = pixbytes
    assert len(img) == os.path.getsize(boot_path), "size drift!"
    outimg = os.path.join(outdir, "boot_patched.img"); open(outimg, "wb").write(img)
    print("LINE logo written ->", outimg, "size-identical:",
          os.path.getsize(outimg) == os.path.getsize(boot_path))
    print("preview ->", os.path.join(outdir, "static_logo_preview.png"))
    sys.exit(0)

scene = np.ones((H2, W2, 3), float) * BG
horizon = int(H2 * 0.62)
# retro sun glow
d = np.sqrt(((xs - 0.5) * (W2 / H2)) ** 2 + (ys - 0.58) ** 2)
sun = np.clip(1 - d / 0.16, 0, 1) ** 1.5
sun[horizon:, :] = 0
scene += sun[:, :, None] * MAGENTA * 0.9
scene += blur(sun * 120, 16)[:, :, None] / 120 * CYAN * 0.4
# perspective grid floor
floor = np.zeros((H2, W2), float)
for k in range(1, 14):
    row = int(horizon + (H2 - horizon) * (k / 14) ** 2.2)
    if 0 <= row < H2:
        floor[row, :] = 1.0
for vx in np.linspace(-1, 2, 25):
    for row in range(horizon, H2):
        t = (row - horizon) / (H2 - horizon)
        col = int((0.5 + (vx - 0.5) * (0.15 + t * 1.6)) * W2)
        if 0 <= col < W2:
            floor[row, col] = 1.0
scene += blur(floor * 180, 1.2)[:, :, None] / 180 * CYAN * 0.5

pil = Image.fromarray(np.clip(scene, 0, 255).astype(np.uint8))

# optional wordmark (edit TEXT; empty string = clean, no text)
TEXT = os.environ.get("LOGO_TEXT", "")
if TEXT:
    draw = ImageDraw.Draw(pil)
    try:
        font = ImageFont.truetype("arialbd.ttf", 72)
    except Exception:
        font = ImageFont.load_default()
    bb = draw.textbbox((0, 0), TEXT, font=font)
    tx = (W2 - (bb[2] - bb[0])) // 2
    tyc = int(H2 * 0.30)
    for dx, dy, c in [(2, 2, (255, 45, 149)), (-2, -2, (0, 229, 255)), (0, 0, (235, 245, 255))]:
        draw.text((tx + dx, tyc + dy), TEXT, font=font, fill=c)

# scanlines + vignette
arr = np.asarray(pil, float)
arr *= (1.0 - 0.28 * (np.sin(np.arange(H2) * np.pi) ** 2))[:, None, None]
dd = np.sqrt((xs - 0.5) ** 2 + (ys - 0.5) ** 2)
arr *= (1.0 - 0.85 * np.clip((dd - 0.25) / 0.6, 0, 1) ** 2)[:, :, None]
final = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
final.save(os.path.join(outdir, "static_logo_preview.png"))

# ---- pack into BMP pixel bytes (BGR, row order per header) ----
rgb = np.asarray(final.convert("RGB"))
bgr = rgb[:, :, ::-1]
if not topdown:  # positive height = bottom-up
    bgr = bgr[::-1, :, :]
pixbytes = bgr.tobytes()
expected = W * H * 3
assert len(pixbytes) == expected, (len(pixbytes), expected)
# write pixel bytes in place (header untouched)
img[off + data_off: off + data_off + expected] = pixbytes
assert len(img) == os.path.getsize(boot_path), "size drift!"

outimg = os.path.join(outdir, "boot_patched.img")
open(outimg, "wb").write(img)
print("wrote", outimg, os.path.getsize(outimg), "bytes (identical size:",
      os.path.getsize(outimg) == os.path.getsize(boot_path), ")")
print("preview ->", os.path.join(outdir, "static_logo_preview.png"))
