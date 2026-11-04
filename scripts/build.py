#!/usr/bin/env python3
"""
build.py - generate every SVG the profile README uses, from profile.json plus live
GitHub data. Standard library only, so the Actions workflow needs no installs.

  python scripts/build.py                 # all assets, both themes
  GITHUB_TOKEN=... python scripts/build.py  # also contributions, streaks and the 3D calendar

Writes into assets/:
  terminal-{dark,light}.svg     typing hero
  timeline-{dark,light}.svg     experience
  radar-{dark,light}.svg        self-rated skill radar
  stats-{dark,light}.svg        live numbers + language mix
  calendar-{dark,light}.svg     isometric contribution calendar (needs a token)
  card-<repo>-{dark,light}.svg  project cards

Everything is self-hosted on purpose: shared public stat services rate-limit and go
down, and when they do the profile shows broken images. A file in the repo can't.
"""
import json
import math
import os
import sys
import textwrap
import urllib.error
import urllib.request
from datetime import date, timedelta
from html import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets")

MONO = "ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,'Liberation Mono',monospace"
SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans',Helvetica,Arial,sans-serif"

# GitHub's own surface colours, plus an AWS-amber accent and a cyan second accent.
THEMES = {
    "dark": dict(bg="#0d1117", card="#161b22", border="#30363d", text="#e6edf3", muted="#8b949e",
                 faint="#21262d", accent="#ffa53a", accent2="#79c0ff", ok="#3fb950",
                 cal=["#1c2129", "#5a3410", "#9a5a12", "#d9831a", "#ffb054"]),
    "light": dict(bg="#ffffff", card="#f6f8fa", border="#d0d7de", text="#1f2328", muted="#59636e",
                  faint="#eaeef2", accent="#c25e00", accent2="#0969da", ok="#1a7f37",
                  cal=["#e6e9ed", "#ffd8a8", "#ffb366", "#f08c00", "#b35400"]),
}

LANG_COLORS = {  # fallbacks for when the REST API is used (GraphQL gives colours itself)
    "Python": "#3572A5", "JavaScript": "#f1e05a", "TypeScript": "#3178c6", "HTML": "#e34c26",
    "CSS": "#663399", "Jupyter Notebook": "#DA5B0B", "Dart": "#00B4AB", "C++": "#f34b7d",
    "Java": "#b07219", "Shell": "#89e051", "Procfile": "#3B2F63",
}

REDUCED = "@media (prefers-reduced-motion:reduce){*{animation:none!important}}"


def svg_open(w, h, label, css=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'role="img" aria-label="{escape(label)}"><title>{escape(label)}</title>'
            f"<style>{css}{REDUCED}</style>")


def write(name, svg):
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"  {name:34s} {len(svg.encode()) / 1024:6.1f} KB")


# --------------------------------------------------------------------------- data

def api(url, token=None, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None)
    req.add_header("User-Agent", "profile-readme-build")
    req.add_header("Accept", "application/vnd.github+json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch(user, token):
    """Returns dict(repos, stars, followers, langs[(name,bytes,color)], repo_meta{}, calendar|None)."""
    data = dict(repos=0, stars=0, followers=0, langs=[], repo_meta={}, calendar=None)
    try:
        u = api(f"https://api.github.com/users/{user}", token)
        data["followers"] = u.get("followers", 0)
        repos = api(f"https://api.github.com/users/{user}/repos?per_page=100&type=owner", token)
    except (urllib.error.URLError, OSError) as e:
        print(f"! GitHub API unavailable ({e}); building with profile.json only", file=sys.stderr)
        return data

    own = [r for r in repos if not r.get("fork")]
    data["repos"] = len(own)
    data["stars"] = sum(r.get("stargazers_count", 0) for r in own)
    for r in repos:
        data["repo_meta"][r["name"]] = dict(stars=r.get("stargazers_count", 0), forks=r.get("forks_count", 0),
                                            lang=r.get("language"), pushed=r.get("pushed_at", "")[:10])

    if token:
        q = """query($login:String!){user(login:$login){
          contributionsCollection{contributionCalendar{totalContributions
            weeks{contributionDays{date contributionCount contributionLevel}}}}
          repositories(ownerAffiliations:OWNER,isFork:false,first:100){nodes{
            languages(first:12,orderBy:{field:SIZE,direction:DESC}){edges{size node{name color}}}}}}}"""
        try:
            g = api("https://api.github.com/graphql", token, {"query": q, "variables": {"login": user}})
            gu = g["data"]["user"]
            totals = {}
            for n in gu["repositories"]["nodes"]:
                for e in n["languages"]["edges"]:
                    k = e["node"]["name"]
                    b, _ = totals.get(k, (0, None))
                    totals[k] = (b + e["size"], e["node"]["color"])
            data["langs"] = sorted(((k, b, c) for k, (b, c) in totals.items()), key=lambda t: -t[1])
            cal = gu["contributionsCollection"]["contributionCalendar"]
            levels = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2, "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}
            data["calendar"] = dict(total=cal["totalContributions"], weeks=[
                [(d["date"], d["contributionCount"], levels.get(d["contributionLevel"], 0))
                 for d in w["contributionDays"]] for w in cal["weeks"]])
            return data
        except (urllib.error.URLError, OSError, KeyError, TypeError) as e:
            print(f"! GraphQL failed ({e}); falling back to REST languages", file=sys.stderr)

    totals = {}
    for r in own:
        try:
            for k, b in api(r["languages_url"], token).items():
                totals[k] = totals.get(k, 0) + b
        except (urllib.error.URLError, OSError):
            pass
    data["langs"] = sorted(((k, b, LANG_COLORS.get(k, "#8b949e")) for k, b in totals.items()), key=lambda t: -t[1])
    return data


def streaks(weeks):
    days = [d for w in weeks for d in w]
    longest = run = 0
    for _, c, _ in days:
        run = run + 1 if c > 0 else 0
        longest = max(longest, run)
    cur = 0
    # Today with no commits yet shouldn't break the streak.
    for i, (_, c, _) in enumerate(reversed(days)):
        if c > 0:
            cur += 1
        elif i > 0:
            break
    best = max(days, key=lambda d: d[1]) if days else ("", 0, 0)
    return cur, longest, best


# --------------------------------------------------------------------------- terminal

def terminal(p, t):
    W, PAD, TOP, LH, FS = 860, 26, 54, 25, 14.5
    CW = FS * 0.6  # monospace advance; only used for timing, the clip is percentage based
    lines = p["terminal"]["lines"]
    H = TOP + len(lines) * LH * 2 + LH + 18
    host = p["terminal"]["host"]

    css = (f"text{{font:{FS}px {MONO};white-space:pre}}"
           f".h{{fill:{t['ok']}}}.d{{fill:{t['muted']}}}.c{{fill:{t['text']}}}"
           f".accent{{fill:{t['accent']};font-weight:700}}.accent2{{fill:{t['accent2']}}}.text{{fill:{t['text']}}}"
           f".muted{{fill:{t['muted']}}}.ok{{fill:{t['ok']}}}.ok-pulse{{fill:{t['ok']};animation:pulse 1.6s ease-in-out infinite}}"
           "@keyframes show{to{opacity:1}}"
           "@keyframes type{from{clip-path:inset(0 100% 0 0)}to{clip-path:inset(0 0 0 0)}}"
           "@keyframes blink{50%{opacity:0}}"
           "@keyframes pulse{50%{opacity:.25}}"
           ".hide{opacity:0}"
           "@media (prefers-reduced-motion:reduce){.hide{opacity:1}.ty{clip-path:none}}")
    s = [svg_open(W, H, f"{p['name']} - terminal", css)]
    s.append(f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="12" fill="{t["card"]}" stroke="{t["border"]}"/>')
    s.append(f'<path d="M1 38H{W - 1}" stroke="{t["border"]}"/>')
    for i, c in enumerate(["#ff5f57", "#febc2e", "#28c840"]):
        s.append(f'<circle cx="{22 + i * 20}" cy="19.5" r="6" fill="{c}"/>')
    s.append(f'<text x="{W / 2}" y="24" text-anchor="middle" class="d" style="font-size:12.5px">'
             f'{escape(p["terminal"]["title"])}</text>')

    clock = 0.5
    y = TOP + 14
    for ln in lines:
        prompt = f"{host}:~$ "
        cmd = ln["cmd"]
        dur = max(0.35, len(cmd) * 0.045)
        # Prompt appears, then the command is typed one character per step.
        s.append(f'<g class="hide" style="animation:show 0s {clock:.2f}s forwards">'
                 f'<text x="{PAD}" y="{y}" textLength="{(len(host) + 3) * CW:.1f}" lengthAdjust="spacing"><tspan class="h">{host}</tspan><tspan class="d">:~$</tspan></text>'
                 f'<text x="{PAD + (len(prompt) + 0) * CW:.1f}" y="{y}" class="c ty" '
                 f'style="clip-path:inset(0 100% 0 0);animation:type {dur:.2f}s steps({len(cmd)}) {clock + 0.25:.2f}s forwards">'
                 f'{escape(cmd)}</text></g>')
        clock += 0.25 + dur + 0.25
        y += LH
        spans = "".join(f'<tspan class="{cls}">{escape(txt)}</tspan>' for txt, cls in ln["out"])
        s.append(f'<text x="{PAD}" y="{y}" class="hide" style="animation:show 0s {clock:.2f}s forwards">{spans}</text>')
        clock += 0.45
        y += LH
    # Final prompt with a blinking block cursor.
    s.append(f'<g class="hide" style="animation:show 0s {clock:.2f}s forwards">'
             f'<text x="{PAD}" y="{y}" textLength="{(len(host) + 3) * CW:.1f}" lengthAdjust="spacing"><tspan class="h">{host}</tspan><tspan class="d">:~$</tspan></text>'
             f'<rect x="{PAD + (len(host) + 4) * CW:.1f}" y="{y - FS + 2}" width="{CW:.1f}" height="{FS + 2}" '
             f'fill="{t["accent"]}" style="animation:blink 1.05s steps(1) infinite"/></g>')
    s.append("</svg>")
    return "".join(s)


# --------------------------------------------------------------------------- timeline

def timeline(p, t):
    W, X_DATE, X_RAIL, X_BODY = 860, 24, 196, 222
    wrap_at = 92
    entries = []
    y = 30
    for e in p["experience"]:
        pts = [textwrap.wrap(pt, wrap_at) for pt in e["points"]]
        h = 48 + sum(len(x) for x in pts) * 20 + 22
        entries.append((e, pts, y, h))
        y += h
    H = y + 6

    css = (f".r{{font:600 15.5px {SANS};fill:{t['text']}}}.o{{font:600 13.5px {SANS};fill:{t['accent']}}}"
           f".w{{font:12.5px {MONO};fill:{t['muted']}}}.p{{font:13.5px {SANS};fill:{t['muted']}}}"
           f".b{{fill:{t['accent2']}}}"
           "@keyframes in{from{opacity:0;transform:translateX(-12px)}to{opacity:1;transform:none}}"
           ".e{opacity:0;animation:in .7s cubic-bezier(.2,.8,.2,1) forwards}"
           "@keyframes ring{0%{r:6;opacity:.7}100%{r:17;opacity:0}}"
           ".ring{animation:ring 2s ease-out infinite}"
           "@keyframes grow{from{transform:scaleY(0)}to{transform:scaleY(1)}}"
           ".rail{transform-origin:top;transform-box:fill-box;animation:grow 1.4s ease-out both}"
           "@media (prefers-reduced-motion:reduce){.e{opacity:1}}")
    s = [svg_open(W, H, "Experience timeline", css)]
    s.append(f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="12" fill="{t["card"]}" stroke="{t["border"]}"/>')
    first_y, last_y = entries[0][2] + 14, entries[-1][2] + 14
    s.append(f'<rect class="rail" x="{X_RAIL - 1}" y="{first_y}" width="2" height="{last_y - first_y}" fill="{t["border"]}"/>')
    for i, (e, pts, y0, h) in enumerate(entries):
        cy = y0 + 14
        s.append(f'<g class="e" style="animation-delay:{0.25 + i * 0.3:.2f}s">')
        s.append(f'<text x="{X_DATE}" y="{cy + 4.5}" class="w">{escape(e["when"])}</text>')
        if e.get("current"):
            s.append(f'<circle cx="{X_RAIL}" cy="{cy}" r="6" fill="none" stroke="{t["accent"]}" stroke-width="2" class="ring"/>')
            s.append(f'<circle cx="{X_RAIL}" cy="{cy}" r="6" fill="{t["accent"]}"/>')
        else:
            s.append(f'<circle cx="{X_RAIL}" cy="{cy}" r="5.5" fill="{t["card"]}" stroke="{t["muted"]}" stroke-width="2"/>')
        s.append(f'<text x="{X_BODY}" y="{cy + 5}" class="r">{escape(e["role"])}</text>')
        s.append(f'<text x="{X_BODY}" y="{cy + 26}" class="o">{escape(e["org"])}</text>')
        ly = cy + 50
        for wrapped in pts:
            for j, line in enumerate(wrapped):
                if j == 0:
                    s.append(f'<text x="{X_BODY}" y="{ly}" class="p"><tspan class="b">▸ </tspan>{escape(line)}</text>')
                else:
                    s.append(f'<text x="{X_BODY + 14}" y="{ly}" class="p">{escape(line)}</text>')
                ly += 20
        s.append("</g>")
    s.append("</svg>")
    return "".join(s)


# --------------------------------------------------------------------------- radar

def radar(p, t):
    W, H, R = 440, 400, 132
    cx, cy = W / 2, H / 2 + 4
    skills = [(k, v) for k, v in p["skills"].items() if not k.startswith("_")]
    n = len(skills)

    def pt(i, f):
        a = -math.pi / 2 + 2 * math.pi * i / n
        return cx + math.cos(a) * R * f, cy + math.sin(a) * R * f

    css = (f".l{{font:600 12.5px {SANS};fill:{t['text']}}}.v{{font:11px {MONO};fill:{t['muted']}}}"
           "@keyframes grow{from{transform:scale(0);opacity:0}to{transform:scale(1);opacity:1}}"
           f".shape{{transform-origin:{cx}px {cy}px;animation:grow 1.3s cubic-bezier(.2,.9,.25,1.15) .3s both}}"
           "@keyframes fade{from{opacity:0}to{opacity:1}}"
           ".lab{animation:fade .6s ease-out both}")
    s = [svg_open(W, H, "Skill radar (self-rated)", css)]
    for ring in (0.25, 0.5, 0.75, 1.0):
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (pt(i, ring) for i in range(n)))
        s.append(f'<polygon points="{pts}" fill="none" stroke="{t["border"]}" stroke-width="1"/>')
    for i in range(n):
        x, y = pt(i, 1)
        s.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" stroke="{t["border"]}"/>')
    shape = " ".join(f"{x:.1f},{y:.1f}" for x, y in (pt(i, v / 100) for i, (_, v) in enumerate(skills)))
    s.append(f'<g class="shape"><polygon points="{shape}" fill="{t["accent"]}" fill-opacity=".22" '
             f'stroke="{t["accent"]}" stroke-width="2" stroke-linejoin="round"/>')
    for i, (_, v) in enumerate(skills):
        x, y = pt(i, v / 100)
        s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{t["accent"]}"/>')
    s.append("</g>")
    for i, (k, v) in enumerate(skills):
        x, y = pt(i, 1.17)
        anchor = "middle" if abs(x - cx) < 8 else ("start" if x > cx else "end")
        s.append(f'<g class="lab" style="animation-delay:{0.9 + i * 0.08:.2f}s">'
                 f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" class="l">{escape(k)}</text>'
                 f'<text x="{x:.1f}" y="{y + 15:.1f}" text-anchor="{anchor}" class="v">{v}</text></g>')
    s.append("</svg>")
    return "".join(s)


# --------------------------------------------------------------------------- stats

def stats(p, d, t):
    W, H = 860, 212
    langs = [l for l in d["langs"] if l[0] not in set(p.get("exclude_languages", []))]
    # Tiles that are zero say nothing good about anyone, so they're left out
    # until they aren't zero - the daily rebuild adds them back on its own.
    tiles = []
    if d["calendar"]:
        cur, longest, best = streaks(d["calendar"]["weeks"])
        tiles += [("contributions · 1y", d["calendar"]["total"]), ("current streak", f"{cur}d"),
                  ("longest streak", f"{longest}d"), ("best day", best[1])]
    tiles += [("public repos", d["repos"]), ("languages", len(langs)),
              ("stars earned", d["stars"]), ("followers", d["followers"])]
    tiles = [x for x in tiles if str(x[1]) not in ("0", "0d")][:5]
    css = (f".n{{font:700 26px {SANS};fill:{t['text']}}}.k{{font:12px {MONO};fill:{t['muted']}}}"
           f".lg{{font:12.5px {SANS};fill:{t['text']}}}.pc{{font:11.5px {MONO};fill:{t['muted']}}}"
           "@keyframes up{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}"
           ".tile{animation:up .6s ease-out both}"
           "@keyframes bar{from{transform:scaleX(0)}to{transform:scaleX(1)}}"
           ".bar{transform-box:fill-box;transform-origin:left;animation:bar .9s cubic-bezier(.2,.8,.2,1) both}")
    s = [svg_open(W, H, "GitHub stats", css)]
    s.append(f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="12" fill="{t["card"]}" stroke="{t["border"]}"/>')
    tw = (W - 48) / len(tiles)
    for i, (k, v) in enumerate(tiles):
        x = 24 + i * tw
        s.append(f'<g class="tile" style="animation-delay:{0.1 + i * 0.08:.2f}s">'
                 f'<text x="{x:.0f}" y="58" class="n">{escape(str(v))}</text>'
                 f'<text x="{x:.0f}" y="80" class="k">{escape(k)}</text></g>')
        if i:
            s.append(f'<line x1="{x - 14:.0f}" y1="34" x2="{x - 14:.0f}" y2="84" stroke="{t["faint"]}"/>')
    s.append(f'<line x1="24" y1="108" x2="{W - 24}" y2="108" stroke="{t["faint"]}"/>')

    total = sum(b for _, b, _ in langs) or 1
    top = langs[:7]
    other = total - sum(b for _, b, _ in top)
    if other > 0:
        top.append(("Other", other, t["muted"]))
    bx, bw, by = 24, W - 48, 128
    s.append(f'<clipPath id="bc"><rect x="{bx}" y="{by}" width="{bw}" height="10" rx="5"/></clipPath>')
    s.append(f'<g clip-path="url(#bc)"><rect x="{bx}" y="{by}" width="{bw}" height="10" fill="{t["faint"]}"/>')
    x = bx
    for i, (k, b, c) in enumerate(top):
        w = bw * b / total
        s.append(f'<rect class="bar" style="animation-delay:{0.4 + i * 0.07:.2f}s" x="{x:.1f}" y="{by}" '
                 f'width="{w + 0.6:.1f}" height="10" fill="{c or t["muted"]}"/>')
        x += w
    s.append("</g>")
    cols = 4
    for i, (k, b, c) in enumerate(top):
        lx = 24 + (i % cols) * ((W - 48) / cols)
        ly = 164 + (i // cols) * 24
        s.append(f'<g class="tile" style="animation-delay:{0.7 + i * 0.05:.2f}s">'
                 f'<circle cx="{lx + 5:.0f}" cy="{ly - 4}" r="5" fill="{c or t["muted"]}"/>'
                 f'<text x="{lx + 16:.0f}" y="{ly}" class="lg">{escape(k)} '
                 f'<tspan class="pc">{100 * b / total:.1f}%</tspan></text></g>')
    s.append("</svg>")
    return "".join(s)


# --------------------------------------------------------------------------- calendar

def calendar(d, t):
    weeks = d["calendar"]["weeks"]
    WV, DV = (11.0, 2.4), (-5.2, 4.0)   # screen step per week / per day (dimetric)
    FOOT = 0.84                          # cube footprint, leaves a gap between columns
    MAXH = 40.0
    counts = [c for w in weeks for _, c, _ in w]
    peak = max(counts) or 1
    nW = len(weeks)
    ox = 7 * -DV[0] + 24
    oy = 56 + MAXH
    W = int(ox + nW * WV[0] + 30)
    H = int(oy + nW * WV[1] + 7 * DV[1] + 40)

    def shade(hexc, f):
        r, g, b = (int(hexc[i:i + 2], 16) for i in (1, 3, 5))
        return "#%02x%02x%02x" % (int(r * f), int(g * f), int(b * f))

    cur, longest, best = streaks(weeks)
    css = (f".h{{font:600 15px {SANS};fill:{t['text']}}}.k{{font:12px {MONO};fill:{t['muted']}}}"
           f".a{{fill:{t['accent']};font-weight:700}}"
           "@keyframes drop{from{opacity:0;transform:translateY(-26px)}to{opacity:1;transform:none}}"
           ".w{animation:drop .55s cubic-bezier(.2,.8,.25,1.1) both}")
    s = [svg_open(W, H, "Isometric contribution calendar", css)]
    s.append(f'<text x="24" y="32" class="h"><tspan class="a">{d["calendar"]["total"]}</tspan> contributions in the last year</text>')
    facts = ([f"streak {cur}d"] if cur else []) + [f"longest {longest}d", f"best day {best[1]}"]
    s.append(f'<text x="{W - 24}" y="32" text-anchor="end" class="k">{" · ".join(facts)}</text>')

    def P(x, y):
        return f"{x:.1f},{y:.1f}"

    for wi, week in enumerate(weeks):
        s.append(f'<g class="w" style="animation-delay:{0.15 + wi * 0.025:.3f}s">')
        for di, (_, c, lvl) in enumerate(week):
            # weekday from date isn't needed: GitHub returns each week Sun..Sat, and the
            # first week can be partial, so offset it to keep rows aligned.
            dd = di + (7 - len(week) if wi == 0 else 0)
            bx = ox + wi * WV[0] + dd * DV[0]
            by = oy + wi * WV[1] + dd * DV[1]
            h = 2.0 + (MAXH * (c / peak) ** 0.75 if c else 0)
            col = t["cal"][lvl]
            w_ = (WV[0] * FOOT, WV[1] * FOOT)
            d_ = (DV[0] * FOOT, DV[1] * FOOT)
            p0 = (bx, by)
            p1 = (bx + w_[0], by + w_[1])
            p2 = (bx + w_[0] + d_[0], by + w_[1] + d_[1])
            p3 = (bx + d_[0], by + d_[1])
            up = lambda q: (q[0], q[1] - h)
            s.append(f'<polygon points="{P(*up(p3))} {P(*up(p2))} {P(*p2)} {P(*p3)}" fill="{shade(col, .78)}"/>')
            s.append(f'<polygon points="{P(*up(p1))} {P(*up(p2))} {P(*p2)} {P(*p1)}" fill="{shade(col, .62)}"/>')
            s.append(f'<polygon points="{P(*up(p0))} {P(*up(p1))} {P(*up(p2))} {P(*up(p3))}" fill="{col}"/>')
        s.append("</g>")
    # Legend
    lx = W - 24 - 5 * 16 - 70
    s.append(f'<text x="{lx}" y="{H - 14}" class="k">less</text>')
    for i, c in enumerate(t["cal"]):
        s.append(f'<rect x="{lx + 34 + i * 16}" y="{H - 25}" width="12" height="12" rx="2" fill="{c}"/>')
    s.append(f'<text x="{lx + 34 + 5 * 16 + 4}" y="{H - 14}" class="k">more</text>')
    s.append("</svg>")
    return "".join(s)


# --------------------------------------------------------------------------- project cards

def card(p, proj, meta, t):
    W, H = 420, 190
    css = (f".t{{font:700 17px {SANS};fill:{t['text']}}}.d{{font:13px {SANS};fill:{t['muted']}}}"
           f".m{{font:600 12px {MONO};fill:{t['accent']}}}.g{{font:11.5px {MONO};fill:{t['text']}}}"
           f".s{{font:11.5px {MONO};fill:{t['muted']}}}"
           "@keyframes in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}"
           ".f{animation:in .6s ease-out both}"
           "@keyframes edge{from{transform:scaleY(0)}to{transform:scaleY(1)}}"
           ".edge{transform-box:fill-box;transform-origin:top;animation:edge .8s cubic-bezier(.2,.8,.2,1) both}")
    s = [svg_open(W, H, proj["name"], css)]
    s.append(f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="12" fill="{t["card"]}" stroke="{t["border"]}"/>')
    s.append(f'<rect class="edge" x="0" y="18" width="3" height="40" rx="1.5" fill="{t["accent"]}"/>')
    s.append(f'<g class="f"><text x="22" y="40" class="t">{escape(proj["name"])}</text>')
    if meta:
        right = "   ".join(x for x in (meta.get("lang") or "",
                                        f'★ {meta["stars"]}' if meta["stars"] else "") if x)
        s.append(f'<text x="{W - 20}" y="39" text-anchor="end" class="s">{escape(right)}</text>')
    else:
        s.append(f'<text x="{W - 20}" y="39" text-anchor="end" class="s">private build</text>')
    y = 66
    for line in textwrap.wrap(proj["blurb"], 54)[:3]:
        s.append(f'<text x="22" y="{y}" class="d">{escape(line)}</text>')
        y += 19
    s.append(f'<text x="22" y="{y + 8}" class="m">▸ {escape(proj["metric"])}</text></g>')
    # Stack chips along the bottom
    x = 22
    s.append('<g class="f" style="animation-delay:.25s">')
    for tag in proj["stack"]:
        w = len(tag) * 7.0 + 18
        if x + w > W - 18:
            break
        s.append(f'<rect x="{x:.0f}" y="{H - 38}" width="{w:.0f}" height="22" rx="11" fill="{t["faint"]}" stroke="{t["border"]}"/>'
                 f'<text x="{x + w / 2:.0f}" y="{H - 23}" text-anchor="middle" class="g">{escape(tag)}</text>')
        x += w + 7
    s.append("</g></svg>")
    return "".join(s)


# --------------------------------------------------------------------------- main

def main():
    with open(os.path.join(ROOT, "profile.json"), encoding="utf-8") as f:
        p = json.load(f)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    d = fetch(p["user"], token)
    os.makedirs(OUT, exist_ok=True)
    print(f"building for {p['user']}: {d['repos']} repos, {len(d['langs'])} languages, "
          f"calendar={'yes' if d['calendar'] else 'no (no token)'}")
    for name, t in THEMES.items():
        write(f"terminal-{name}.svg", terminal(p, t))
        write(f"timeline-{name}.svg", timeline(p, t))
        write(f"radar-{name}.svg", radar(p, t))
        write(f"stats-{name}.svg", stats(p, d, t))
        if d["calendar"]:
            write(f"calendar-{name}.svg", calendar(d, t))
        for proj in p["projects"]:
            slug = proj["repo"] or proj["name"].lower().replace(" ", "-")
            write(f"card-{slug}-{name}.svg", card(p, proj, d["repo_meta"].get(proj["repo"]), t))


if __name__ == "__main__":
    main()
