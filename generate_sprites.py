#!/usr/bin/env python3
"""
Generate placeholder pixel-crab sprites for CrabCodeBar.

Canvas is 15x13 logical pixels, upscaled 3x (nearest-neighbor) to 45x39 PNG.
Upscale is 3x (not 4x) so the PNG fits inside the ~44px retina menu bar
without clipping. The crab itself occupies ~9 cols x ~8 rows, leaving
horizontal margin for idle pacing and vertical margin for jumps.

Per-state animation (at 1 fps classic refresh):
    working  -> body stationary, claws tap alternately, eyes dart
    waiting  -> whole body paces ±1 col horizontally, eyes track direction
    jumping  -> whole body bounces up (y offset 0, -1, -2, -1), claws raised
    asleep   -> curled sleeping body at canvas bottom, closed-eye slashes,
                solid sleep-bubble blocks rise above across two frames

Swap in hand-drawn 45x39 PNGs of the same filenames any time; the plugin
only needs body=(217,119,87) and body-dark=(168,83,59) so the runtime
color tinting continues to work.
"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared import BODY as _BODY, BODY_DARK as _BODY_DARK  # noqa: E402

SPRITE_DIR = Path(__file__).parent / "sprites"
SIZE_W = 15
SIZE_H = 13
UPSCALE = 3  # 15x13 * 3 = 45x39 retina — fits inside the ~44px menu bar

# Crab origin within the expanded canvas (leaves margin on all sides)
BASE_X = 2
BASE_Y = 2

# Palette (RGBA; RGB values come from shared.py)
BODY = (*_BODY, 255)
BODY_DARK = (*_BODY_DARK, 255)
EYE_WHITE = (255, 255, 255, 255)
EYE_PUPIL = (31, 31, 31, 255)
Z_COLOR = (160, 160, 180, 255)


def new_canvas():
    return Image.new("RGBA", (SIZE_W, SIZE_H), (0, 0, 0, 0))


def px(d, x, y, color):
    if 0 <= x < SIZE_W and 0 <= y < SIZE_H:
        d.point((x, y), fill=color)


def draw_eyes(d, x_off, y_off, eye_dir):
    """Two 2x2 white eye blocks with single-pixel pupil inside each."""
    for x in (3, 4, 6, 7):
        px(d, x + x_off, 2 + y_off, EYE_WHITE)
        px(d, x + x_off, 3 + y_off, EYE_WHITE)
    # Pupil column within each 2x2: -1 -> left, 0/+1 -> right
    left_col = 3 if eye_dir < 0 else 4
    right_col = 6 if eye_dir < 0 else 7
    px(d, left_col + x_off, 3 + y_off, EYE_PUPIL)
    px(d, right_col + x_off, 3 + y_off, EYE_PUPIL)


def draw_body(d, x_off, y_off):
    """5-wide body rows 4-5 (light) + row 6 (dark shadow)."""
    for x in range(3, 8):
        px(d, x + x_off, 4 + y_off, BODY)
        px(d, x + x_off, 5 + y_off, BODY)
    for x in range(3, 8):
        px(d, x + x_off, 6 + y_off, BODY_DARK)


def draw_claws(d, x_off, y_off, left_up=False, right_up=False, raised=False):
    """2x2 mitten claws at cols 1-2 and 8-9 (relative to x_off)."""
    if raised:
        for cx in (1, 2):
            for cy in (1, 2):
                px(d, cx + x_off, cy + y_off, BODY)
        for cx in (8, 9):
            for cy in (1, 2):
                px(d, cx + x_off, cy + y_off, BODY)
        return
    l_top = 3 if left_up else 4
    for cx in (1, 2):
        px(d, cx + x_off, l_top + y_off, BODY)
        px(d, cx + x_off, l_top + 1 + y_off, BODY)
    r_top = 3 if right_up else 4
    for cx in (8, 9):
        px(d, cx + x_off, r_top + y_off, BODY)
        px(d, cx + x_off, r_top + 1 + y_off, BODY)


def draw_legs(d, x_off, y_off):
    for lx in (3, 5, 7):
        px(d, lx + x_off, 7 + y_off, BODY_DARK)


def draw_sleeping_body(d):
    """
    Curled sleeping pose at canvas bottom. Full rounded silhouette (5 rows
    tall, 9 cols wide at middle), closed-eye slashes visible on top. Claws
    and legs are tucked under — readable as "crab curled up asleep."

    Layout (absolute canvas coords, symmetric around col 7):

        row 8:         E E . E E             closed eyes
        row 9:       B B B B B B B           body top (7 wide)
        row 10:    B B B B B B B B B         widest (9 wide)
        row 11:      D D D D D D D           dark (7 wide)
        row 12:        D D D D D             tapered bottom (5 wide)
    """
    # Closed eyes
    for cx in (5, 6, 8, 9):
        px(d, cx, 8, EYE_PUPIL)
    # Body top row (cols 4-10)
    for cx in range(4, 11):
        px(d, cx, 9, BODY)
    # Widest row (cols 3-11)
    for cx in range(3, 12):
        px(d, cx, 10, BODY)
    # Dark upper bottom (cols 4-10)
    for cx in range(4, 11):
        px(d, cx, 11, BODY_DARK)
    # Dark tapered bottom (cols 5-9)
    for cx in range(5, 10):
        px(d, cx, 12, BODY_DARK)


def draw_crab(img, pace=0, hop=0, claws_up=False, left_up=False,
              right_up=False, eye_dir=0, curled=False):
    """pace: horizontal shift (idle pacing). hop: vertical shift (jumps, negative=up)."""
    d = ImageDraw.Draw(img)
    if curled:
        draw_sleeping_body(d)
        return
    x_off = BASE_X + pace
    y_off = BASE_Y + hop
    draw_eyes(d, x_off, y_off, eye_dir)
    draw_body(d, x_off, y_off)
    draw_claws(d, x_off, y_off, left_up=left_up, right_up=right_up, raised=claws_up)
    if not claws_up:
        draw_legs(d, x_off, y_off)


def draw_bubble(img, x, y, size=2):
    """
    Solid square "sleep bubble." size=2 (default) is a 2x2 block; size=1 is
    a single pixel used for smaller/further-drifted bubbles.
    """
    d = ImageDraw.Draw(img)
    for dx in range(size):
        for dy in range(size):
            px(d, x + dx, y + dy, Z_COLOR)


def save(img, name):
    big = img.resize((SIZE_W * UPSCALE, SIZE_H * UPSCALE), Image.NEAREST)
    path = SPRITE_DIR / f"{name}.png"
    big.save(path)
    print(f"  wrote {path.name}")


def build_working():
    """Typing motion: body still, claws alternate, eyes dart."""
    variants = [
        (False, False,  0),   # rest, eyes center
        (True,  False, -1),   # left claw taps, eyes left
        (False, True,   1),   # right claw taps, eyes right
    ]
    for i, (lu, ru, eye) in enumerate(variants):
        img = new_canvas()
        draw_crab(img, left_up=lu, right_up=ru, eye_dir=eye)
        save(img, f"working_{i}")


def build_jumping():
    """Whole-body bounce with claws raised."""
    for i, hop in enumerate([0, -1, -2, -1]):
        img = new_canvas()
        draw_crab(img, hop=hop, claws_up=True)
        save(img, f"jumping_{i}")


def build_waiting():
    """Idle pacing: crab shifts ±1 col horizontally, eyes track the motion."""
    # (pace, eye_dir)
    variants = [(-1, -1), (0, 0), (1, 1)]
    for i, (pace, eye) in enumerate(variants):
        img = new_canvas()
        draw_crab(img, pace=pace, eye_dir=eye)
        save(img, f"waiting_{i}")


def build_asleep():
    """
    Curled crab with rising sleep bubbles. 2x2 primary blocks + 1x1 smaller
    blocks higher up (perspective: smaller = further away), positioned so
    none clip at canvas edges.

        Frame 0: 2x2 bubble near head + tiny 1x1 bubble drifted high-right
        Frame 1: 2x2 bubble drifted up-right + tiny 1x1 even higher +
                 fresh 1x1 appearing low — reads as continuous rising.
    """
    # Frame 0: main bubble near head + small drifted bubble
    img0 = new_canvas()
    draw_crab(img0, curled=True)
    draw_bubble(img0, 10, 5, size=2)   # primary bubble near crab head
    draw_bubble(img0, 12, 4, size=1)   # tiny bubble at the spot the big one will rise to
    save(img0, "asleep_0")

    # Frame 1: main bubble drifted + new tiny bubble rising
    img1 = new_canvas()
    draw_crab(img1, curled=True)
    draw_bubble(img1, 11, 3, size=2)   # primary bubble drifted up-right
    draw_bubble(img1, 14, 0, size=1)   # tiny bubble drifted top-right corner
    draw_bubble(img1, 10, 6, size=1)   # fresh tiny bubble near head
    save(img1, "asleep_1")


def main():
    SPRITE_DIR.mkdir(exist_ok=True)
    print(f"Generating sprites in {SPRITE_DIR}...")
    build_working()
    build_jumping()
    build_waiting()
    build_asleep()
    print("Done.")


if __name__ == "__main__":
    main()
