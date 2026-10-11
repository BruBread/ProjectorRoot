#!/usr/bin/env python3
"""Render a futuristic/retro CRT power-on boot animation for the projector.

Output: crt_bootanimation.zip (Android bootanimation format, 1280x720 @ 15fps).
  part 'intro' plays once (CRT turn-on), 'loop' repeats until boot finishes.
PNGs are added STORED (zip -0), which this build's bootanimation requires.
Usage: python make_crt_bootanim.py [out_dir]
"""
import os, sys, zipfile, numpy as np
from PIL import Image, ImageFilter

W, H, FPS = 1280, 720, 15
N_INTRO, N_LOOP = 12, 12   # snappier turn-on + calm short loop
OUT = sys.argv[1] if len(sys.argv) > 1 else "."
FRAMES = os.path.join(OUT, "frames")

# palette (retro-futuristic / synthwave CRT)
BG      = np.array([5, 7, 15], float)      # near-black navy
CYAN    = np.array([0, 229, 255], float)   # phosphor core
MAGENTA = np.array([255, 45, 149], float)  # accent / sun
WHITE   = np.array([235, 245, 255], float)

ys = np.linspace(0, 1, H)[:, None]
xs = np.linspace(0, 1, W)[None, :]

def smooth(t):  # smoothstep, clamped
    t = np.clip(t, 0, 1); return t * t * (3 - 2 * t)

def blur(mask, r):  # gaussian blur a HxW float mask via PIL
    im = Image.fromarray(np.clip(mask, 0, 255).astype(np.uint8))
    return np.asarray(im.filter(ImageFilter.GaussianBlur(r)), float)

def scanlines(img, strength=0.28):
    s = 1.0 - strength * (np.sin(np.arange(H) * np.pi) ** 2)  # darken alt rows
    return img * s[:, None, None]

def vignette(img, k=0.85):
    d = np.sqrt((xs - 0.5) ** 2 + (ys - 0.5) ** 2)
    v = 1.0 - k * smooth((d - 0.25) / 0.6)
    return img * v[:, :, None]

def grid_horizon(phase=0.0):
    """Synthwave perspective grid + sun glow in the lower third. Returns HxWx3 add-light."""
    g = np.zeros((H, W, 3), float)
    horizon = int(H * 0.62)
    # retro sun: magenta/cyan arc glowing above the horizon
    sun = np.zeros((H, W), float)
    cx, cy, rad = 0.5, 0.58, 0.16
    d = np.sqrt(((xs - cx) * (W / H)) ** 2 + (ys - cy) ** 2)
    sun = np.clip(1 - d / rad, 0, 1) ** 1.5
    sun[horizon:, :] = 0  # cut at horizon
    g += sun[:, :, None] * MAGENTA * 0.9
    g += blur(sun * 120, 18)[:, :, None] / 120 * CYAN * 0.4
    # perspective floor lines below horizon (cyan)
    floor = np.zeros((H, W), float)
    for i in range(1, 14):  # horizontal receding lines
        yy = horizon + (H - horizon) * (i / 14) ** 2.2
        row = int(yy)
        if 0 <= row < H:
            floor[row, :] = 1.0
    phx = (phase * 0.5) % 1.0
    for vx in np.linspace(-1, 2, 25):  # vertical lines converging to center
        for row in range(horizon, H):
            t = (row - horizon) / (H - horizon)
            xcol = 0.5 + (vx + phx - 0.5) * (0.15 + t * 1.6)
            col = int(xcol * W)
            if 0 <= col < W:
                floor[row, col] = 1.0
    floor = blur(floor * 180, 1.2) / 180
    g += floor[:, :, None] * CYAN * 0.5
    return g

def crt_on_look(phase, flicker=1.0):
    """The settled 'CRT is on' screen."""
    img = np.ones((H, W, 3), float) * BG
    img += grid_horizon(phase)
    # moving bright scan sweep
    sweep_y = (phase % 1.0)
    band = np.exp(-((ys[:, 0] - sweep_y) ** 2) / (2 * 0.004 ** 2))
    img += (band[:, None, None] * WHITE * 0.18)
    img = scanlines(img)
    img = vignette(img)
    img *= (0.92 + 0.08 * flicker)  # subtle brightness flicker
    return img

def chroma(img, shift=3):
    out = img.copy()
    out[:, :, 0] = np.roll(img[:, :, 0], shift, axis=1)   # R right
    out[:, :, 2] = np.roll(img[:, :, 2], -shift, axis=1)  # B left
    return out

def save(img, path):
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(path)

def crt_line(bright=1.0):
    """The single centered horizontal line — shared with the static boot logo
    so the animation starts FROM the same line (seamless handoff)."""
    img = np.ones((H, W, 3), float) * BG
    line = np.exp(-((ys[:, 0] - 0.5) ** 2) / (2 * 0.0016 ** 2))
    img += line[:, None, None] * (WHITE * bright)
    img += blur(line * 255 * bright, 10)[:, :, None] / 255 * CYAN * 0.7
    return img

def render_intro(i):
    p = i / (N_INTRO - 1)
    img = np.ones((H, W, 3), float) * BG
    cy = 0.5
    if p < 0.12:                       # a: steady line == the static boot logo
        img = crt_line(bright=1.0)
    elif p < 0.55:                     # b: bloom open vertically (CRT turn-on)
        a = smooth((p - 0.12) / 0.43)
        half = 0.5 * a
        edge = 0.006
        band = np.clip(1 - (np.abs(ys[:, 0] - cy) - half) / edge, 0, 1)
        inside = (np.abs(ys[:, 0] - cy) <= half).astype(float)
        img += inside[:, None, None] * (BG * 2 + CYAN * 0.10)
        img += band[:, None, None] * WHITE * 1.0        # bright leading edges
        img += blur(band * 255, 14)[:, :, None] / 255 * CYAN * 0.8
    elif p < 0.75:                     # c: flash + horizontal retrace sweep
        a = 1 - smooth((p - 0.55) / 0.20)
        base = crt_on_look(phase=0.0, flicker=1.0)
        img = base + (WHITE * 0.9 * a)
        ry = (p - 0.55) / 0.20
        band = np.exp(-((ys[:, 0] - ry) ** 2) / (2 * 0.01 ** 2))
        img += band[:, None, None] * CYAN * 0.6
    else:                              # d: settle into the on-look
        a = smooth((p - 0.75) / 0.25)
        on = crt_on_look(phase=0.0, flicker=1.0)
        flash = np.ones((H, W, 3), float) * BG + WHITE * 0.3
        img = flash * (1 - a) + on * a
    return chroma(img, shift=int(3 * (1 - min(p / 0.75, 1)) + 1))

def render_loop(j):
    phase = j / N_LOOP                 # 0..1 seamless
    fl = 0.5 + 0.5 * np.sin(2 * np.pi * (j / N_LOOP) * 2 + 1.3)
    img = crt_on_look(phase=phase, flicker=fl)
    return chroma(img, shift=1)

def main():
    import shutil
    shutil.rmtree(FRAMES, ignore_errors=True)   # avoid packing stale frames
    for d in (os.path.join(FRAMES, "intro"), os.path.join(FRAMES, "loop")):
        os.makedirs(d, exist_ok=True)
    for i in range(N_INTRO):
        save(render_intro(i), os.path.join(FRAMES, "intro", f"{i:03d}.png"))
    for j in range(N_LOOP):
        save(render_loop(j), os.path.join(FRAMES, "loop", f"{j:03d}.png"))
    desc = f"{W} {H} {FPS}\np 1 0 intro\np 0 0 loop\n"
    zpath = os.path.join(OUT, "crt_bootanimation.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_STORED) as z:  # STORED required
        z.writestr("desc.txt", desc)
        for part in ("intro", "loop"):
            for f in sorted(os.listdir(os.path.join(FRAMES, part))):
                z.write(os.path.join(FRAMES, part, f), f"{part}/{f}")
    print("wrote", zpath, os.path.getsize(zpath), "bytes;",
          N_INTRO, "intro +", N_LOOP, "loop frames")
    print("desc:\n" + desc)

if __name__ == "__main__":
    main()
