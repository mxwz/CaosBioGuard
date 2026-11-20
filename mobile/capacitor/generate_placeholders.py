"""生成 Capacitor 占位图标和启动页。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
FONT_PATH = Path('C:/Windows/Fonts/arialbd.ttf')


def rounded_icon(size: int = 1024) -> Image.Image:
    img = Image.new('RGBA', (size, size), (7, 12, 18, 255))
    draw = ImageDraw.Draw(img)
    margin = int(size * 0.08)
    draw.rounded_rectangle(
        (margin, margin, size - margin, size - margin),
        radius=int(size * 0.18), fill=(34, 211, 238, 255),
    )
    font = ImageFont.truetype(str(FONT_PATH), int(size * 0.52))
    bbox = draw.textbbox((0, 0), 'C', font=font)
    x = (size - (bbox[2] - bbox[0])) / 2 - bbox[0]
    y = (size - (bbox[3] - bbox[1])) / 2 - bbox[1]
    draw.text((x, y), 'C', font=font, fill=(4, 16, 24, 255))
    return img


def splash(size: int = 2732) -> Image.Image:
    img = Image.new('RGBA', (size, size), (7, 12, 18, 255))
    icon = rounded_icon(760)
    offset = ((size - icon.width) // 2, (size - icon.height) // 2)
    img.alpha_composite(icon, offset)
    return img


def main() -> None:
    resources = ROOT / 'resources'
    resources.mkdir(exist_ok=True)
    rounded_icon().save(resources / 'icon.png')
    splash().save(resources / 'splash.png')
    www_icon = ROOT / 'www' / 'icons'
    www_icon.mkdir(parents=True, exist_ok=True)
    rounded_icon(512).save(www_icon / 'icon.png')


if __name__ == '__main__':
    main()
