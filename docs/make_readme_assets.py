"""
One-off / repeatable: normalize README screenshots for a consistent look on GitHub.
Run from repo root:  python docs/make_readme_assets.py
Requires: Pillow
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
README_DIR = ROOT / "readme"
SOURCE_DIR = README_DIR / "_source"
PROCESSED_DIR = README_DIR / "processed"

# Dark neutral that matches Flow-ish UIs; avoids pure #000 banding in some viewers
BG = (14, 14, 18)
PAD = 36
MAX_WIDTH = 1080
HERO_HEIGHT = 140
HERO_GAP = 20


def _load_rgba(path: Path) -> Image.Image:
    im = Image.open(path).convert("RGBA")
    return im


def _fit_max_width(im: Image.Image) -> Image.Image:
    w, h = im.size
    if w <= MAX_WIDTH:
        return im
    ratio = MAX_WIDTH / w
    nh = max(1, int(round(h * ratio)))
    return im.resize((MAX_WIDTH, nh), Image.Resampling.LANCZOS)


def _on_canvas(im: Image.Image) -> Image.Image:
    im = _fit_max_width(im)
    w, h = im.size
    canvas = Image.new("RGB", (w + PAD * 2, h + PAD * 2), BG)
    canvas.paste(im, (PAD, PAD), im.split()[3] if im.mode == "RGBA" else None)
    return canvas


def _ensure_source_backup() -> None:
    """First run: copy flat readme/*.png into _source/ if _source is empty."""
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    if any(SOURCE_DIR.glob("[0-9][0-9]-*.png")):
        return
    for p in sorted(README_DIR.glob("[0-9][0-9]-*.png")):
        if p.parent != README_DIR:
            continue
        dest = SOURCE_DIR / p.name
        dest.write_bytes(p.read_bytes())


def _iter_source_pngs():
    _ensure_source_backup()
    for p in sorted(SOURCE_DIR.glob("[0-9][0-9]-*.png")):
        yield p


def process_numbered() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    for p in _iter_source_pngs():
        out = PROCESSED_DIR / p.name
        canvas = _on_canvas(_load_rgba(p))
        canvas.save(out, "PNG", optimize=True)
        print(f"OK {out.relative_to(ROOT)}")


def make_hero_strip() -> None:
    """Single image: idle → transcribing → pasted (same height, tight strip)."""
    use = [
        SOURCE_DIR / "01-pill-idle.png",
        SOURCE_DIR / "03-transcribing.png",
        SOURCE_DIR / "04-pasted.png",
    ]
    if not all(x.exists() for x in use):
        print("Skip hero: missing 01/03/04 in readme/_source/")
        return
    tiles: list[Image.Image] = []
    for path in use:
        im = _load_rgba(path)
        w, h = im.size
        scale = HERO_HEIGHT / h
        nw = max(1, int(round(w * scale)))
        im = im.resize((nw, HERO_HEIGHT), Image.Resampling.LANCZOS)
        tiles.append(im)
    total_w = sum(t.width for t in tiles) + HERO_GAP * (len(tiles) - 1)
    hero = Image.new("RGB", (total_w + PAD * 2, HERO_HEIGHT + PAD * 2), BG)
    x = PAD
    for i, t in enumerate(tiles):
        hero.paste(t, (x, PAD), t.split()[3])
        x += t.width + HERO_GAP
    out = PROCESSED_DIR / "00-hero-strip.png"
    hero.save(out, "PNG", optimize=True)
    print(f"OK {out.relative_to(ROOT)}")


def main() -> None:
    _ensure_source_backup()
    process_numbered()
    make_hero_strip()
    print("Done. Update README to use docs/readme/processed/*.png")


if __name__ == "__main__":
    main()
