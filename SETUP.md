# Setup

This folder is a GitHub **profile README**. It has to live in a public repo named exactly
like your username, so: **`github.com/vedanth-raj/vedanth-raj`**. That repo's README is what
shows at the top of your profile.

## 1. Push it

Create an empty public repo called `vedanth-raj` on GitHub (no README, no licence), then from
this folder:

```bash
git init -b main
git add -A
git commit -m "profile readme"
git remote add origin https://github.com/vedanth-raj/vedanth-raj.git
git push -u origin main
```

> This folder currently sits inside a git repo rooted at your home directory. `git init` here
> makes it its own repo, which is what you want. Nothing in the parent repo changes.

## 2. Let Actions write to the repo

Repo → **Settings** → **Actions** → **General** → **Workflow permissions** →
**Read and write permissions** → Save.

## 3. Run the two workflows once

Repo → **Actions** → enable workflows if asked → run each with **Run workflow**:

| workflow | makes | where |
|---|---|---|
| **Build profile art** | terminal, timeline, radar, stats, 3D calendar, project cards | `assets/*.svg` on `main` |
| **Snake** | snake eating your contribution graph | `output` branch |

After that they run on their own (art daily, snake every 12 h). The snake image is blank until
the Snake workflow has run once.

Optional: to count **private** contributions too, create a classic token with `read:user`
at https://github.com/settings/tokens and add it as the repo secret `METRICS_TOKEN`. Without
it the built-in token is used and only public activity is counted.

---

## Editing

Almost everything comes from **`profile.json`**: the terminal lines, experience, skill radar
(self-rated, change the numbers to taste), project cards and which languages to ignore.
Push a change and the workflow redraws the SVGs. To build locally instead:

```bash
python scripts/build.py
```

(Set `GITHUB_TOKEN` first, for example `GITHUB_TOKEN=$(gh auth token)`, to include the
contribution calendar and streaks.)

The bio bullets, badges and the toolbox icons are plain Markdown in `README.md`.

### The portrait

Two files, `assets/portrait-dark.svg` and `assets/portrait-light.svg`, one per GitHub theme.
In dark mode bright areas become big bright dots; in light mode dark areas become big ink dots,
like newspaper halftone.

Both photos (`assets/photo-1.webp`, `assets/photo-2.webp`) are baked into each file. On load
the first portrait's dots fly in and assemble outward from the face. Every 15 s the current
portrait blows apart from the face outward while the next one assembles in its place, and it
loops forever. Visitors with "reduce motion" turned on just see the first portrait, still.

To change or add photos (any number works, they take turns in order):

```bash
python scripts/mask.py assets/photo-1.webp -o assets/mask-1.png
python scripts/mask.py assets/photo-2.webp -o assets/mask-2.png
python scripts/portrait.py --photo assets/photo-1.webp assets/mask-1.png --photo assets/photo-2.webp assets/mask-2.png --theme dark  -o assets/portrait-dark.svg
python scripts/portrait.py --photo assets/photo-1.webp assets/mask-1.png --photo assets/photo-2.webp assets/mask-2.png --theme light -o assets/portrait-light.svg
```

Knobs worth knowing: `--hold` (seconds per portrait, default 15), `--cols` (detail vs. file
size; 124 with two photos is about 730 KB), `--sharpen` (edge crispness, default 140), `--fly` / `--leave` / `--spread` (transition timing).
With a single `--photo` it assembles once and a light band sweeps over it every 7 s instead.
`mask.py` needs `torch` + `torchvision`; `portrait.py` needs `pillow`, `numpy`, `scikit-image`.
`build.py` needs nothing beyond Python itself.

### Preview before pushing

```bash
python -m http.server 8731
```

Then open http://localhost:8731/preview.html. It has a dark/light toggle and a button to
replay the animations.
