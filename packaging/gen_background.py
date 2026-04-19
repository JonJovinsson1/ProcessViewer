"""Generate DMG background images for Programmer Process Viewer.

Produces:
  packaging/background.png     (600x400, 1x)
  packaging/background@2x.png  (1200x800, 2x retina)

build.sh combines these into a multi-resolution TIFF that Finder renders at
the correct size on any display.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).parent

# Base (1x) dimensions — must match the AppleScript window bounds in build.sh.
BASE_W, BASE_H = 600, 400

BG = (13, 17, 23)          # #0d1117
TEXT = (201, 209, 217)     # #c9d1d9
MUTED = (139, 148, 158)    # #8b949e
ACCENT = (46, 160, 67)     # #2ea043

# Icon layout (1x coords) — must match the AppleScript positions in build.sh.
ICON_SIZE = 128
APP_POS = (150, 200)
APPS_POS = (450, 200)


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/SFNSDisplay.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render(scale: int) -> Image.Image:
    W, H = BASE_W * scale, BASE_H * scale
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Subtle top glow.
    glow_h = 80 * scale
    for i in range(glow_h):
        t = 1 - i / glow_h
        delta = int(18 * t)
        draw.line(
            [(0, i), (W, i)],
            fill=(BG[0] + delta, BG[1] + delta, BG[2] + delta),
        )

    title_font = load_font(26 * scale)
    sub_font = load_font(13 * scale)
    hint_font = load_font(10 * scale)

    title = "Programmer Process Viewer"
    tw = draw.textlength(title, font=title_font)
    draw.text(
        ((W - tw) / 2, 38 * scale),
        title,
        fill=TEXT,
        font=title_font,
    )

    subtitle = "Drag the app onto Applications to install"
    sw = draw.textlength(subtitle, font=sub_font)
    draw.text(
        ((W - sw) / 2, 74 * scale),
        subtitle,
        fill=MUTED,
        font=sub_font,
    )

    # Arrow between the two icon centers, staying clear of the icon bounds.
    arrow_y = APP_POS[1] * scale
    arrow_x1 = (APP_POS[0] + ICON_SIZE // 2 + 12) * scale
    arrow_x2 = (APPS_POS[0] - ICON_SIZE // 2 - 12) * scale
    thickness = 4 * scale
    draw.line(
        [(arrow_x1, arrow_y), (arrow_x2, arrow_y)],
        fill=ACCENT,
        width=thickness,
    )
    head = 14 * scale
    draw.polygon(
        [
            (arrow_x2, arrow_y),
            (arrow_x2 - head, arrow_y - head // 2),
            (arrow_x2 - head, arrow_y + head // 2),
        ],
        fill=ACCENT,
    )

    hint = "v1.0  ·  macOS arm64"
    hw = draw.textlength(hint, font=hint_font)
    draw.text(
        ((W - hw) / 2, H - 28 * scale),
        hint,
        fill=MUTED,
        font=hint_font,
    )

    return img


def main() -> None:
    render(1).save(OUT_DIR / "background.png", "PNG", optimize=True)
    render(2).save(OUT_DIR / "background@2x.png", "PNG", optimize=True)
    print(f"wrote {OUT_DIR}/background.png ({BASE_W}x{BASE_H})")
    print(f"wrote {OUT_DIR}/background@2x.png ({BASE_W * 2}x{BASE_H * 2})")


if __name__ == "__main__":
    main()
