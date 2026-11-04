#!/usr/bin/env python3
"""
portrait.py - turn one or more photos into an animated halftone SVG for a README.

What the SVG does (pure CSS, so it plays inside <img>, which is how GitHub shows it):
  * Dots start scattered and fly into place, nearest-the-face first, so each
    portrait condenses outward from the eyes.
  * With two or more photos it loops: every --hold seconds the current portrait
    blows apart from the face outward while the next one assembles in its place.
  * With a single photo it assembles once, then a soft light band sweeps over it.
  * prefers-reduced-motion shows the first portrait, still.

Two themes, because a halftone reads differently on each background:
  dark   bright parts of the photo = big, bright dots (light on #0d1117)
  light  dark parts of the photo   = big, dark dots   (ink on white paper)

Usage:
  python scripts/portrait.py --photo assets/photo-1.webp assets/mask-1.png \\
                             --photo assets/photo-2.webp assets/mask-2.png \\
                             --theme dark -o assets/portrait-dark.svg

Masks come from scripts/mask.py (white = person). Requires Pillow, numpy, scikit-image.
"""
import argparse
import math
import random

import numpy as np
from PIL import Image, ImageFilter
from skimage import exposure

CELL = 10                                   # SVG units per grid cell
SLATE = np.array([86.0, 104.0, 150.0])      # tint for pixels too dark to carry a hue
INK = np.array([40.0, 52.0, 84.0])          # same idea for the light theme
N_DIR, N_DELAY = 24, 20                     # scatter directions / landing-time buckets


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--photo", nargs=2, action="append", metavar=("IMAGE", "MASK"), required=True,
                   help="photo and its subject mask; repeat for more photos")
    p.add_argument("-o", "--out", default="assets/portrait-dark.svg")
    p.add_argument("--theme", choices=["dark", "light"], default="dark")
    p.add_argument("--cols", type=int, default=124, help="dots across; the main size/quality dial")
    p.add_argument("--aspect", type=float, default=1.08, help="canvas height / width, shared by all photos")
    p.add_argument("--pad", type=float, default=0.03, help="padding around each subject (fraction)")
    p.add_argument("--clahe", type=float, default=0.018, help="adaptive equalisation strength (0 = off)")
    p.add_argument("--gamma", type=float, default=0.85)
    p.add_argument("--sharpen", type=int, default=140, help="unsharp-mask strength in percent (0 = off)")
    p.add_argument("--hold", type=float, default=15.0, help="seconds each portrait stays (multi-photo)")
    p.add_argument("--fly", type=float, default=1.6, help="seconds a dot takes to land")
    p.add_argument("--leave", type=float, default=1.1, help="seconds a dot takes to blow away")
    p.add_argument("--spread", type=float, default=1.8, help="seconds between first and last dot moving")
    p.add_argument("--sweep", type=float, default=7.0, help="single photo: seconds per light sweep (0 = off)")
    p.add_argument("--seed", type=int, default=7)
    return p.parse_args()


def luminance(rgb):
    return 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]


def hex3(rgb):
    r, g, b = (int(max(0, min(255, c)) / 17 + 0.5) for c in rgb)
    return "#%x%x%x" % (r, g, b)


def framed(image, mask, aspect, pad):
    """Crop to the subject, then letterbox onto a canvas of the shared aspect ratio,
    centred horizontally and sitting on the bottom edge, so every photo lines up."""
    im = Image.open(image).convert("RGB")
    m = Image.open(mask).convert("L").resize(im.size)
    box = m.point(lambda v: 255 if v > 127 else 0).getbbox() or (0, 0, *im.size)
    w, h = im.size
    px, py = int(w * pad), int(h * pad)
    box = (max(0, box[0] - px), max(0, box[1] - py), min(w, box[2] + px), h)
    im, m = im.crop(box), m.crop(box)
    w, h = im.size
    W = max(w, round(h / aspect))
    H = round(W * aspect)
    canvas, cmask = Image.new("RGB", (W, H)), Image.new("L", (W, H))
    canvas.paste(im, ((W - w) // 2, H - h))
    cmask.paste(m, ((W - w) // 2, H - h))
    return canvas, cmask


def dots_for(image, mask, a, rows, rnd):
    im, mask = framed(image, mask, a.aspect, a.pad)
    cols = a.cols
    w, h = im.size
    lum_full = luminance(np.asarray(im, dtype=np.float64)) / 255.0
    m_full = np.asarray(mask, dtype=np.float64) / 255.0

    # CLAHE at full resolution pulls apart face, glasses and the folds of dark
    # clothing, which one global curve can't do next to a bright white shirt.
    eq = (exposure.equalize_adapthist(lum_full * (m_full > 0.5), kernel_size=max(w, h) // 10, clip_limit=a.clahe)
          if a.clahe > 0 else lum_full)
    tone_img = Image.fromarray((np.clip(eq, 0, 1) * 255).astype(np.uint8))
    # Sharpen at the scale of one dot before sampling, so edges that matter for
    # recognising a face (eyes, glasses rims, nose, mouth, jaw) survive the
    # box-average instead of smearing across neighbouring dots.
    cell_px = w / cols
    tone_img = tone_img.filter(ImageFilter.UnsharpMask(radius=cell_px * 1.2, percent=a.sharpen, threshold=0))
    im = im.filter(ImageFilter.UnsharpMask(radius=cell_px, percent=a.sharpen // 2, threshold=0))

    small = np.asarray(im.resize((cols, rows), Image.BOX), dtype=np.float64)
    tone = np.asarray(tone_img.resize((cols, rows), Image.BOX), dtype=np.float64) / 255.0
    subject = np.asarray(mask.resize((cols, rows), Image.BOX), dtype=np.float64) / 255.0 > 0.5

    vals = np.sort(tone[subject])
    tone = (np.searchsorted(vals, tone) / max(1, len(vals))) ** a.gamma

    # Focus = centre of the head: the subject's centroid within its top third.
    ys, xs = np.nonzero(subject)
    top = ys < ys.min() + 0.33 * (ys.max() - ys.min())
    cx0, cy0 = xs[top].mean(), ys[top].mean()
    maxd = math.hypot(max(cx0, cols - cx0), max(cy0, rows - cy0))

    out = []
    for y in range(rows):
        for x in range(cols):
            if not subject[y, x]:
                continue
            t = float(tone[y, x])
            c = small[y, x]
            L = max(1.0, float(luminance(c)))
            wgt = min(1.0, L / 45.0)
            if a.theme == "dark":
                r = 1.3 + 3.9 * t
                target = 62 + 193 * t
                base = SLATE * (target / luminance(SLATE))
            else:
                r = 1.0 + 4.2 * (1 - t) ** 0.65
                target = 25 + 120 * t
                base = INK * (target / 50.0)
            col = c * min(3.0, target / L) * wgt + base * (1 - wgt)
            d = math.hypot(x - cx0, (y - cy0) * 0.9) / maxd
            d = min(1.0, max(0.0, d + rnd.uniform(-0.04, 0.04)))
            out.append((x * CELL + CELL / 2, y * CELL + CELL / 2, r, hex3(col),
                        rnd.randrange(N_DIR), int(d * (N_DELAY - 1))))
    return out


def scatter(i):
    ang = 2 * math.pi * i / N_DIR + 0.3
    dist = 220 + 180 * ((i * 7) % N_DIR) / N_DIR
    return math.cos(ang) * dist, math.sin(ang) * dist


def main():
    a = parse_args()
    rnd = random.Random(a.seed)
    cols = a.cols
    rows = round(cols * a.aspect)
    W, H = cols * CELL, rows * CELL
    portraits = [dots_for(img, msk, a, rows, rnd) for img, msk in a.photo]
    n = len(portraits)

    css = []
    if n == 1:
        for i in range(N_DIR):
            dx, dy = scatter(i)
            css.append(f"@keyframes k{i}{{0%{{transform:translate({dx:.0f}px,{dy:.0f}px);opacity:0}}"
                       f"55%{{opacity:1}}100%{{transform:none;opacity:1}}}}"
                       f".a{i}{{animation:k{i} {a.fly}s cubic-bezier(.16,.84,.3,1) both}}")
    else:
        # One loop of the whole show is n * hold. Each dot's own clock starts when
        # its portrait's turn begins (plus its distance-from-face stagger), so the
        # outgoing and incoming dots for the same spot swap at the same moment.
        P = n * a.hold
        f_in = 100 * a.fly / P
        f_hold = 100 * a.hold / P
        f_out = 100 * (a.hold + a.leave) / P
        for i in range(N_DIR):
            dx, dy = scatter(i)
            ex, ey = scatter((i + N_DIR // 2) % N_DIR)
            css.append(
                f"@keyframes k{i}{{"
                f"0%{{transform:translate({dx:.0f}px,{dy:.0f}px);opacity:0;"
                f"animation-timing-function:cubic-bezier(.16,.84,.3,1)}}"
                f"{f_in:.2f}%{{transform:none;opacity:1}}"
                f"{f_hold:.2f}%{{transform:none;opacity:1;animation-timing-function:cubic-bezier(.55,0,.8,.4)}}"
                f"{f_out:.2f}%,100%{{transform:translate({ex * 1.3:.0f}px,{ey * 1.3:.0f}px);opacity:0}}}}"
                f".a{i}{{animation:k{i} {P:g}s linear infinite backwards}}")
        # Reduced motion: no animation, and only the first portrait is shown.
        css.append("@media (prefers-reduced-motion:reduce){.q~.q{display:none}}")
    for k in range(n):
        for j in range(N_DELAY):
            css.append(f".p{k} .t{j}{{animation-delay:{k * a.hold + a.spread * j / (N_DELAY - 1):.2f}s}}")
    css.append("@media (prefers-reduced-motion:reduce){.q g{animation:none!important}.sw{display:none}}")

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="Vedanth Raj, halftone portrait">',
        "<title>Vedanth Raj</title>",
        "<style>" + "".join(css) + "</style>",
    ]
    sweep = n == 1 and a.sweep > 0
    if sweep:
        glint = "#fff" if a.theme == "dark" else "#58a6ff"
        out.append(
            f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2=".35">'
            f'<stop offset="0" stop-color="{glint}" stop-opacity="0"/><stop offset=".5" stop-color="{glint}" stop-opacity=".6"/>'
            f'<stop offset="1" stop-color="{glint}" stop-opacity="0"/></linearGradient>'
            f'<mask id="m" maskUnits="userSpaceOnUse" x="0" y="0" width="{W}" height="{H}">'
            f'<g style="filter:brightness(4)"><use xlink:href="#d0" href="#d0"/></g></mask></defs>')
    for k, dots in enumerate(portraits):
        out.append(f'<g id="d{k}" class="q p{k}">')
        # Dots sharing a scatter direction and landing time are animated as one
        # group: hundreds of animations instead of ~20k, which keeps the file
        # small and the page smooth. Directions are assigned at random, so each
        # ring of dots still breaks into many independently moving pieces.
        groups = {}
        for (x, y, r, col, di, dl) in dots:
            groups.setdefault((di, dl), []).append(f'<circle cx="{x:g}" cy="{y:g}" r="{r:.1f}" fill="{col}"/>')
        for (di, dl), circles in sorted(groups.items()):
            out.append(f'<g class="a{di} t{dl}">' + "".join(circles) + "</g>")
        out.append("</g>")
    if sweep:
        bw = W * 0.45
        out.append(
            f'<g class="sw" mask="url(#m)"><rect y="0" width="{bw:.0f}" height="{H}" fill="url(#g)" x="{-bw:.0f}">'
            f'<animate attributeName="x" values="{-bw:.0f};{W:.0f};{W:.0f}" keyTimes="0;.4;1" '
            f'dur="{a.sweep}s" begin="{a.fly + a.spread:.1f}s" repeatCount="indefinite"/></rect></g>')
    out.append("</svg>")
    svg = "\n".join(out)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(svg)
    counts = " + ".join(str(len(d)) for d in portraits)
    print(f"{a.out}: {counts} dots, {cols}x{rows} grid, {len(svg.encode()) / 1024:.0f} KB")


if __name__ == "__main__":
    main()
