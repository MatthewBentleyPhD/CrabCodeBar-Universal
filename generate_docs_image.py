#!/usr/bin/env python3
"""
Generate documentation images for the README:

  docs/crab-states.png  — composite grid of every sprite frame by state
  docs/crab-colors.png  — all 11 color options side by side

Regenerate after swapping sprites or changing the palette so the README
stays in sync.

Usage:
    python3 generate_docs_image.py           # generate both images
    python3 generate_docs_image.py states    # just the states grid
    python3 generate_docs_image.py colors    # just the color palette
"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared import BODY, BODY_DARK  # noqa: E402

PLUGIN_DIR = Path(__file__).parent
SPRITE_DIR = PLUGIN_DIR / "sprites"
DOCS_DIR = PLUGIN_DIR / "docs"
OUT_STATES = DOCS_DIR / "crab-states.png"
OUT_COLORS = DOCS_DIR / "crab-colors.png"

# Rows of the composite, in the order they should appear.
STATES = [
    ("Working", ["working_0", "working_1", "working_2"]),
    ("Waiting", ["waiting_0", "waiting_1", "waiting_2"]),
    ("Jumping", ["jumping_0", "jumping_1", "jumping_2", "jumping_3"]),
    ("Asleep",  ["asleep_0",  "asleep_1"]),
]

# Layout
SPRITE_SCALE = 2              # 45x39 * 2 = 90x78 per tile
SPRITE_W = 45 * SPRITE_SCALE
SPRITE_H = 39 * SPRITE_SCALE
COL_PAD = 20                  # horizontal gap between sprites
ROW_PAD = 28                  # vertical gap between state rows
LABEL_W = 120                 # column reserved for state names
MARGIN = 32                   # outer margin on all sides
BG_COLOR = (248, 248, 245, 255)
LABEL_COLOR = (40, 40, 40)


def try_font(size):
    """Try common system fonts; fall back to Pillow's bitmap default."""
    for name in ("Helvetica.ttc", "HelveticaNeue.ttc", "Arial.ttf",
                 "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


# ---- Color palette (must match COLOR_PALETTES in crabcodebar.py) ----
# Imported as display-order list of (name, tint-pair-or-None).
COLOR_ORDER = [
    ("Orange", None),
    ("Yellow", ((230, 190, 70),  (170, 135, 50))),
    ("Green",  ((104, 190, 104), (64, 140, 64))),
    ("Teal",   ((80, 180, 180),  (50, 130, 130))),
    ("Blue",   ((87, 142, 217),  (59, 99, 168))),
    ("Purple", ((155, 100, 200), (110, 70, 150))),
    ("Pink",   ((236, 125, 168), (186, 80, 125))),
    ("Red",    ((239, 68, 68),   (179, 50, 50))),
    ("Brown",  ((140, 95, 60),   (95, 60, 35))),
    ("Grey",   ((150, 150, 150), (95, 95, 95))),
    ("Black",  ((50, 50, 50),    (25, 25, 25))),
]

# Representative sprite for the color grid
COLOR_SPRITE = "working_0"


def tint_sprite(img, tint):
    """Return a copy of img with body colors swapped to tint palette."""
    if tint is None:
        return img.copy()
    primary, dark = tint
    out = img.copy()
    pixels = out.load()
    for y in range(out.height):
        for x in range(out.width):
            r, g, b, a = pixels[x, y]
            if (r, g, b) == BODY:
                pixels[x, y] = (*primary, a)
            elif (r, g, b) == BODY_DARK:
                pixels[x, y] = (*dark, a)
    return out


def generate_states():
    """Generate docs/crab-states.png — sprite frames by state."""
    max_cols = max(len(frames) for _, frames in STATES)
    width = (MARGIN + LABEL_W
             + max_cols * SPRITE_W + (max_cols - 1) * COL_PAD
             + MARGIN)
    height = (MARGIN
              + len(STATES) * SPRITE_H + (len(STATES) - 1) * ROW_PAD
              + MARGIN)

    canvas = Image.new("RGBA", (width, height), BG_COLOR)
    draw = ImageDraw.Draw(canvas)
    label_font = try_font(22)

    for row_idx, (label, frames) in enumerate(STATES):
        row_y = MARGIN + row_idx * (SPRITE_H + ROW_PAD)

        text_bbox = label_font.getbbox(label)
        text_h = text_bbox[3] - text_bbox[1]
        text_y = row_y + (SPRITE_H - text_h) // 2 - text_bbox[1]
        draw.text((MARGIN, text_y), label, fill=LABEL_COLOR, font=label_font)

        for col_idx, name in enumerate(frames):
            sprite_path = SPRITE_DIR / f"{name}.png"
            img = Image.open(sprite_path).convert("RGBA")
            img = img.resize((SPRITE_W, SPRITE_H), Image.NEAREST)
            x = MARGIN + LABEL_W + col_idx * (SPRITE_W + COL_PAD)
            canvas.alpha_composite(img, (x, row_y))

    DOCS_DIR.mkdir(exist_ok=True)
    canvas.save(OUT_STATES)
    print(f"Wrote {OUT_STATES} ({width}x{height})")


def generate_colors():
    """Generate docs/crab-colors.png — one crab per color, labeled."""
    n = len(COLOR_ORDER)
    # Two rows: top row gets the ceiling, bottom gets the rest
    top_n = (n + 1) // 2
    bot_n = n - top_n
    max_cols = top_n
    label_h = 24
    row_height = SPRITE_H + label_h + 4
    width = MARGIN + max_cols * SPRITE_W + (max_cols - 1) * COL_PAD + MARGIN
    height = MARGIN + 2 * row_height + ROW_PAD + MARGIN

    canvas = Image.new("RGBA", (width, height), BG_COLOR)
    draw = ImageDraw.Draw(canvas)
    label_font = try_font(16)

    base = Image.open(SPRITE_DIR / f"{COLOR_SPRITE}.png").convert("RGBA")

    for idx, (name, tint) in enumerate(COLOR_ORDER):
        if idx < top_n:
            row, col = 0, idx
        else:
            row, col = 1, idx - top_n
        # Center the bottom row if it has fewer items
        x_offset = 0
        if row == 1:
            x_offset = ((top_n - bot_n) * (SPRITE_W + COL_PAD)) // 2
        x = MARGIN + x_offset + col * (SPRITE_W + COL_PAD)
        y = MARGIN + row * (row_height + ROW_PAD)

        tinted = tint_sprite(base, tint)
        tinted = tinted.resize((SPRITE_W, SPRITE_H), Image.NEAREST)
        canvas.alpha_composite(tinted, (x, y))

        # Label centered below
        text_bbox = label_font.getbbox(name)
        text_w = text_bbox[2] - text_bbox[0]
        text_x = x + (SPRITE_W - text_w) // 2
        text_y = y + SPRITE_H + 4
        draw.text((text_x, text_y), name, fill=LABEL_COLOR, font=label_font)

    DOCS_DIR.mkdir(exist_ok=True)
    canvas.save(OUT_COLORS)
    print(f"Wrote {OUT_COLORS} ({width}x{height})")


def main():
    args = sys.argv[1:]
    if not args or "states" in args:
        generate_states()
    if not args or "colors" in args:
        generate_colors()


if __name__ == "__main__":
    main()
