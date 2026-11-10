#!/usr/bin/env python3
"""Render the profile README's animated SVG cards from data/profile.json.

    python scripts/render_readme_cards.py            # animated cards -> cards/
    STATIC=1 python scripts/render_readme_cards.py   # final frame only -> .preview/static/

Every run also rewrites the block between the cards markers in readme.md (animated
mode only) and writes .preview/<mode>.html, a page laid out like the README on
GitHub, for checking or screenshotting before a push.

The cards are shown through <img>, which sandboxes them: no scripts, no external
requests. So everything is self-contained: one inline <style> with CSS keyframes,
SMIL for what CSS cannot do in SVG (animated gradients, changing text), and Inter
subset per card with pyftsubset (fontTools.subset) and embedded as base64 WOFF.

Rules every animation follows, so prefers-reduced-motion and STATIC=1 both land on
the finished card:
  - An element's own attributes are its final state; CSS entrances only borrow the
    "from" keyframe while they wait (fill-mode both).
  - Looping effects rest invisible or in place when their animation is removed.
  - SMIL-only layers carry class "smil", which reduced motion hides.

Requires fonttools (pip install fonttools).
"""
import base64
import datetime as dt
import html
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
STATIC = os.environ.get("STATIC") == "1"
MODE = "static" if STATIC else "animated"
OUT = ROOT / (".preview/static" if STATIC else "cards")
DATA = ROOT / "data" / "profile.json"
README = ROOT / "readme.md"
FONTS = {w: ROOT / "fonts" / f"inter-{w}.woff" for w in (400, 500, 700)}
PORTRAIT = ROOT / "assets" / "portrait.jpg"  # optional: the hero drops it when absent

# ---------------------------------------------------------------- content ----

NAME = "Karthickrajan S"
KICKER = "HEY THERE, I AM"
TAGLINE = "Founder of Caliber Tech · Frontend developer · Videographer"
PLACE = "Salem, India"
SITE = "https://karthickrajans.vercel.app/"
SITE_LABEL = "karthickrajans.vercel.app"
STACK = ["React", "Next.js", "TypeScript", "Node.js", "MongoDB", "Tailwind"]

# value: a key of data/profile.json (an integer, which counts up) or literal text.
TILES = [
    dict(slug="portfolio", kicker="01 · PORTFOLIO", value="public_repos", caption="public repos",
         foot=SITE_LABEL, url=SITE, accent="#60a5fa"),
    dict(slug="startup", kicker="02 · STARTUP", value="Founder", caption="of Caliber Tech",
         foot="calibertech.vercel.app", url="https://calibertech.vercel.app/", accent="#a5b4fc"),
    dict(slug="connect", kicker="03 · CONNECT", value="Say hi", caption="on LinkedIn",
         foot="in/karthickrajan-s", url="https://www.linkedin.com/in/karthickrajan-s/", accent="#f9a8d4"),
]

# GitHub has no descriptions for these repos, so the blurbs come from the website.
# A description added on GitHub later replaces the blurb.
FEATURED = [
    dict(repo="gemini-disease-outbreak-monitor", title="Disease Outbreak Monitor",
         blurb="A React app that pairs Gemini AI with the latest W.H.O. news to report disease outbreaks worldwide."),
    dict(repo="KEC-VMS", title="Vehicle Management System",
         blurb="Keeps a college fleet on schedule and texts drivers their next service date through Twilio. 3rd prize, EHORYZON 2024."),
    dict(repo="3Dportfolio", title="3D Portfolio",
         blurb="A game world modelled in Blender and Spline, brought to the browser with React and Three.js."),
    dict(repo="Netflix-Clone-App", title="Netflix Clone",
         blurb="A MERN-stack clone with API-driven pages and email sign-in on Express and MongoDB."),
]

# ------------------------------------------------------------------ brand ----
# Taken from karthickrajans.vercel.app: black ground, Inter, silver gradient
# headings (#797979 -> #e8e8e8 -> #959494) and a blue accent.

BG = "#050505"
CARD = "#0a0a0a"
TEXT = "#e8e8e8"
SUB = "#a3a3a3"
MUTED = "#737373"
FAINT = "#27272a"
BLUE = "#3b82f6"
BLUE_DEEP = "#1d4ed8"
BLUE_LIGHT = "#93c5fd"
LEVELS = ["#161618", "#172554", "#1e40af", "#3b82f6", "#93c5fd"]
STREAKS = ["#3b82f6", "#93c5fd", "#a5b4fc", "#fcd34d", "#f9a8d4"]

# Start time of each card, in seconds, so the page plays top to bottom.
T_HERO, T_GRAPH, T_CHART, T_TILES, T_REPOS = 0.0, 0.55, 1.0, 1.75, 2.45
EASE = "cubic-bezier(.2,.8,.2,1)"

KEYFRAMES = """
@keyframes rise{from{opacity:0;transform:translateY(14px)}}
@keyframes fade{from{opacity:0}}
@keyframes show{from{opacity:0}to{opacity:0}}
@keyframes pop{from{opacity:0;transform:scale(.3)}}
@keyframes grow{from{transform:scaleY(0)}}
@keyframes draw{from{stroke-dashoffset:var(--len)}}
@keyframes swing{0%{opacity:0;transform:translateY(70px) rotate(-7deg)}55%{opacity:1;transform:translateY(-8px) rotate(1.5deg)}78%{transform:translateY(2px) rotate(-.4deg)}100%{transform:none}}
@keyframes ring{0%{opacity:.9;transform:scale(1)}70%,100%{opacity:0;transform:scale(3.4)}}
@keyframes beat{0%,100%{opacity:1}50%{opacity:.35}}
@keyframes nudge{0%,70%,100%{transform:none}80%{transform:translate(3px,-3px)}90%{transform:translate(-1px,1px)}}
@keyframes sweep{0%{transform:translateX(0)}22%,100%{transform:translateX(var(--to))}}
@keyframes drift{from{transform:translateX(-14px)}to{transform:translateX(14px)}}
.fb{transform-box:fill-box;transform-origin:center}
.fbb{transform-box:fill-box;transform-origin:50% 100%}
.num{font-variant-numeric:tabular-nums}
@media (prefers-reduced-motion:reduce){*{animation:none!important}.smil{display:none}}
"""

# ------------------------------------------------------------------ fonts ----

_metrics = {}
_subsets = {}


def _font(weight):
    if weight not in _metrics:
        f = TTFont(FONTS[weight])
        _metrics[weight] = (f.getBestCmap(), f["hmtx"], f["head"].unitsPerEm)
    return _metrics[weight]


def measure(s, size, weight=400, spacing=0.0):
    cmap, hmtx, upm = _font(weight)
    units = sum(hmtx[cmap.get(ord(c), ".notdef")][0] for c in s)
    return units * size / upm + spacing * len(s)


def fit(s, size, weight, width, spacing=0.0, floor=10):
    """Largest font size up to `size` at which `s` fits in `width`."""
    while size > floor and measure(s, size, weight, spacing) > width:
        size -= 0.5
    return size


def wrap(s, size, weight, width, max_lines):
    lines, words = [], s.split()
    while words and len(lines) < max_lines:
        line = words.pop(0)
        while words and measure(line + " " + words[0], size, weight) <= width:
            line += " " + words.pop(0)
        lines.append(line)
    if words:
        last = lines[-1]
        while last and measure(last + "…", size, weight) > width:
            last = last[:-1].rstrip()
        lines[-1] = last.rstrip(",.;:") + "…"
    return lines


def subset_woff(weight, chars):
    """pyftsubset the source font down to `chars` and return it as base64 WOFF."""
    text = "".join(sorted(chars))
    key = (weight, text)
    if key not in _subsets:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "subset.woff"
            subprocess.run(
                [sys.executable, "-m", "fontTools.subset", str(FONTS[weight]),
                 f"--text={text}", "--flavor=woff", f"--output-file={out}",
                 "--layout-features=kern,tnum", "--no-hinting", "--desubroutinize"],
                check=True,
            )
            _subsets[key] = base64.b64encode(out.read_bytes()).decode()
    return _subsets[key]


# ------------------------------------------------------------------- card ----

def anim(name, dur, delay, ease=EASE, extra=""):
    """An inline animation declaration, or nothing in STATIC mode."""
    if STATIC:
        return ""
    return f"animation:{name} {dur}s {ease} {delay:.3f}s {extra or 'both'};"


def esc(s):
    return html.escape(str(s), quote=True)


class Card:
    def __init__(self, name, w, h, title):
        self.name, self.w, self.h, self.title = name, w, h, title
        self.defs, self.body, self.css = [], [], []
        self.glyphs = {w_: set() for w_ in FONTS}

    def add(self, *parts):
        self.body.extend(parts)

    def text(self, x, y, s, size, weight=400, fill=TEXT, anchor=None, style="", cls="",
             spacing=None, attrs="", inner=""):
        self.glyphs[weight].update(str(s))
        a = f' text-anchor="{anchor}"' if anchor else ""
        a += f' letter-spacing="{spacing}"' if spacing else ""
        a += f' class="{cls}"' if cls else ""
        a += f' style="{style}"' if style else ""
        return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" '
                f'fill="{fill}"{a}{attrs}>{esc(s)}{inner}</text>')

    def countup(self, x, y, value, size, weight, fill, start, dur, anchor=None, cls="num"):
        """A number that counts up from zero.

        CSS cannot change text, so the count is SMIL: one <text> per frame, each made
        visible for its slice of time with <set>. The real number is a plain element
        that CSS reveals as the last frame ends, so reduced motion (which hides the
        frames and removes the reveal) and STATIC both show it straight away.
        """
        label = f"{value:,}"
        final = self.text(x, y, label, size, weight, fill, anchor, cls=cls,
                          style=anim("show", .01, start + dur, "linear", "backwards"))
        if STATIC or value <= 0:
            return final
        n, frames, prev = 18, [], None
        times = [start + dur * i / n for i in range(n + 1)]
        values = [round(value * (1 - (1 - i / n) ** 3)) for i in range(n)]
        spans = []
        for i, v in enumerate(values):
            if v == prev:
                spans[-1][2] = times[i + 1]
            else:
                spans.append([v, times[i], times[i + 1]])
            prev = v
        for v, t0, t1 in spans:
            frames.append(self.text(
                x, y, f"{v:,}", size, weight, fill, anchor, cls=cls, attrs=' visibility="hidden"',
                inner=f'<set attributeName="visibility" to="visible" begin="{t0:.3f}s" end="{t1:.3f}s"/>'))
        return f'<g class="smil">{"".join(frames)}</g>{final}'

    def svg(self):
        faces = "".join(
            f"@font-face{{font-family:'Inter';font-weight:{w};"
            f"src:url(data:font/woff;base64,{subset_woff(w, chars)}) format('woff')}}"
            for w, chars in self.glyphs.items() if chars)
        style = (faces + "text{font-family:Inter,ui-sans-serif,system-ui,-apple-system,'Segoe UI',sans-serif}"
                 + KEYFRAMES + "".join(self.css))
        return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                f'width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}" role="img" '
                f'aria-labelledby="t"><title id="t">{esc(self.title)}</title>'
                f"<style>{style}</style><defs>{''.join(self.defs)}</defs>{''.join(self.body)}</svg>\n")


def frame(card, rx=20, inset=0.5, fill=BG):
    w, h = card.w - 2 * inset, card.h - 2 * inset
    card.defs.append(f'<clipPath id="clip"><rect x="{inset}" y="{inset}" width="{w}" height="{h}" rx="{rx}"/></clipPath>')
    return (f'<rect x="{inset}" y="{inset}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
            f'stroke="#ffffff" stroke-opacity=".09"/>')


def silver_defs(card, gid="silver"):
    card.defs.append(
        f'<linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="0">'
        '<stop offset="0" stop-color="#9a9a9a"/><stop offset=".5" stop-color="#e8e8e8"/>'
        '<stop offset="1" stop-color="#959494"/></linearGradient>')


def shine_gradient(card, gid, begin, period=6.0):
    """A bright band that crosses its element once per period.

    background-clip:text does not exist in SVG, so the band is a gradient fill whose
    gradientTransform SMIL slides across. It rests off the element before `begin`.
    """
    motion = "" if STATIC else (
        f'<animateTransform attributeName="gradientTransform" type="translate" values="-1 0;1 0;1 0" '
        f'keyTimes="0;.32;1" dur="{period}s" begin="{begin:.2f}s" repeatCount="indefinite"/>')
    card.defs.append(
        f'<linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="0" gradientTransform="translate(-1 0)">'
        '<stop offset=".38" stop-color="#fff" stop-opacity="0"/>'
        '<stop offset=".5" stop-color="#fff" stop-opacity=".95"/>'
        f'<stop offset=".62" stop-color="#fff" stop-opacity="0"/>{motion}</linearGradient>')


def arrow(card, x, y, color, delay, size=16):
    return card.text(x, y, "↗", size, 500, color, "end", cls="fb",
                     style=anim("nudge", 2.6, delay, "ease-in-out", "infinite"))


# ------------------------------------------------------------------- data ----

def load():
    if not DATA.exists():
        sys.exit(f"render: {DATA.relative_to(ROOT)} is missing; run scripts/fetch_profile_data.py first")
    data = json.loads(DATA.read_text())
    days = [(dt.date.fromisoformat(d["date"]), d["count"]) for d in data["days"]]
    if not days:
        sys.exit("render: the contribution calendar in data/profile.json is empty")
    data["days"] = days
    return data


def month_add(d, n):
    m = d.month - 1 + n
    return dt.date(d.year + m // 12, m % 12 + 1, 1)


def stats(data):
    days = data["days"]
    last = days[-1][0]
    first_month = month_add(last.replace(day=1), -11)
    window = [(d, c) for d, c in days if d >= first_month]
    months = []
    for i in range(12):
        m = month_add(first_month, i)
        months.append((m, sum(c for d, c in window if d.year == m.year and d.month == m.month)))

    # Today is not over yet, so an empty today does not break the streak.
    seq = [c for _, c in days]
    if seq and seq[-1] == 0:
        seq = seq[:-1]
    current = 0
    for c in reversed(seq):
        if not c:
            break
        current += 1
    longest = run = 0
    for _, c in days:
        run = run + 1 if c else 0
        longest = max(longest, run)

    busiest = max(window, key=lambda dc: (dc[1], dc[0]))
    best = max(months, key=lambda mc: (mc[1], mc[0]))
    return dict(
        months=months, total=sum(c for _, c in months), current=current, longest=longest,
        active=sum(1 for _, c in window if c), span=len(window),
        busiest=busiest, best=best,
    )


def fmt_day(d):
    return f"{d:%b} {d.day}, {d.year}"


def plural(n, word):
    return f"{n:,} {word}{'' if n == 1 else 's'}"


# ------------------------------------------------------------------ cards ----

def hero(data):
    W, H = 880, 330
    c = Card("hero", W, H, f"{NAME}. {TAGLINE}. {PLACE}.")
    silver_defs(c)
    shine_gradient(c, "shine", T_HERO + 1.6)
    c.defs.append('<filter id="soft" x="-50%" y="-20%" width="200%" height="140%"><feGaussianBlur stdDeviation="16"/></filter>')
    c.defs.append('<radialGradient id="wash" cx=".18" cy="0" r=".9"><stop offset="0" stop-color="#fff" stop-opacity=".09"/>'
                  '<stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>')
    for i, col in enumerate(STREAKS):
        c.defs.append(f'<linearGradient id="st{i}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{col}" stop-opacity="0"/>'
                      f'<stop offset=".45" stop-color="{col}" stop-opacity=".55"/><stop offset="1" stop-color="{col}" stop-opacity="0"/></linearGradient>')
    has_portrait = PORTRAIT.exists()

    c.add(frame(c), '<g clip-path="url(#clip)">', f'<rect width="{W}" height="{H}" fill="url(#wash)"/>')
    # Light streaks like the site's hero, drifting slowly behind the portrait.
    streak_x = [560, 618, 676, 740, 806]
    for i, x in enumerate(streak_x):
        c.add(f'<rect x="{x}" y="-40" width="{34 + 10 * (i % 2)}" height="{H + 80}" fill="url(#st{i})" '
              f'opacity="{.55 if i < 3 else .35}" filter="url(#soft)" '
              f'style="{anim("fade", 1.6, T_HERO + .2 * i)}"/>')
    c.add("</g>")
    if not STATIC:
        c.add(f'<g clip-path="url(#clip)"><g style="{anim("drift", 9, 0, "ease-in-out", "infinite alternate")}">'
              f'<rect x="590" y="-40" width="26" height="{H + 80}" fill="url(#st2)" opacity=".4" filter="url(#soft)"/></g></g>')

    x0 = 56
    text_w = (560 if has_portrait else W - 2 * x0)
    lines = []
    lines.append(c.text(x0, 92, KICKER, 12, 500, MUTED, spacing=2.6, style=anim("rise", .7, T_HERO + .1)))
    size = fit(NAME, 60, 700, text_w)
    lines.append(c.text(x0, 158, NAME, size, 700, "url(#silver)", spacing=-1, style=anim("rise", .8, T_HERO + .22)))
    if not STATIC:
        lines.append(c.text(x0, 158, NAME, size, 700, "url(#shine)", spacing=-1, cls="smil",
                            style=anim("show", .01, T_HERO + 1.0, "linear", "backwards")))
    tag = wrap(TAGLINE, 17, 400, text_w, 2)
    for i, line in enumerate(tag):
        lines.append(c.text(x0, 196 + 24 * i, line, 17, 400, SUB, style=anim("rise", .8, T_HERO + .36 + .08 * i)))
    c.add(*lines)

    # Stack chips, popping in one after another.
    y = 214 + 24 * len(tag)
    x = x0
    for i, name in enumerate(STACK):
        w = measure(name, 12, 500) + 22
        if x + w > x0 + text_w:
            break
        st = anim("pop", .5, T_HERO + .6 + .06 * i, "cubic-bezier(.3,1.5,.5,1)")
        c.add(f'<g class="fb" style="{st}"><rect x="{x}" y="{y}" width="{w:.1f}" height="26" rx="13" fill="#fff" '
              f'fill-opacity=".04" stroke="#fff" stroke-opacity=".14"/>',
              c.text(x + w / 2, y + 17.5, name, 12, 500, TEXT, "middle"), "</g>")
        x += w + 8

    # Place line with a beating dot.
    py = H - 36
    c.add(f'<circle cx="{x0 + 4}" cy="{py - 4}" r="4" fill="{BLUE}" style="{anim("beat", 2.2, T_HERO + 1.2, "ease-in-out", "infinite")}"/>',
          f'<circle cx="{x0 + 4}" cy="{py - 4}" r="4" fill="none" stroke="{BLUE}" opacity="0" class="fb" '
          f'style="{anim("ring", 2.2, T_HERO + 1.2, "ease-out", "infinite")}"/>',
          c.text(x0 + 16, py, f"{PLACE}  ·  {SITE_LABEL}", 13, 400, MUTED, style=anim("fade", .8, T_HERO + .9)))

    if has_portrait:
        cx, cy, r = 735, H / 2, 96
        img = base64.b64encode(PORTRAIT.read_bytes()).decode()
        c.defs.append(f'<clipPath id="face"><circle cx="{cx}" cy="{cy}" r="{r}"/></clipPath>')
        circ = 2 * math.pi * (r + 9)
        c.add(f'<g class="fb" style="{anim("pop", .9, T_HERO + .3, "cubic-bezier(.2,1.2,.3,1)")}">'
              f'<image href="data:image/jpeg;base64,{img}" x="{cx - r}" y="{cy - r}" width="{2 * r}" height="{2 * r}" '
              f'clip-path="url(#face)" preserveAspectRatio="xMidYMid slice"/>'
              f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#fff" stroke-opacity=".18"/></g>',
              f'<circle cx="{cx}" cy="{cy}" r="{r + 9}" fill="none" stroke="{BLUE}" stroke-width="1.5" '
              f'stroke-linecap="round" stroke-dasharray="{circ:.1f}" transform="rotate(-90 {cx} {cy})" '
              f'style="--len:{circ:.1f};{anim("draw", 1.4, T_HERO + .5)}"/>')
    return c


def graph(data):
    days = data["days"]
    W = 880
    pitch, cell = 14.6, 11.4
    first = days[0][0]
    start = first - dt.timedelta(days=(first.weekday() + 1) % 7)  # weeks start on Sunday, like GitHub
    cols = (days[-1][0] - start).days // 7 + 1
    gx = (W - cols * pitch + (pitch - cell)) / 2
    gy = 96
    H = int(gy + 7 * pitch + 58)
    total = sum(cnt for _, cnt in days)
    active = sum(1 for _, cnt in days if cnt)
    c = Card("graph", W, H, f"Contribution graph: {total:,} contributions on {active} days in the last year.")

    nz = sorted(cnt for _, cnt in days if cnt)
    cuts = [nz[min(len(nz) - 1, int(len(nz) * q))] for q in (.25, .5, .75)] if nz else [0, 0, 0]

    def level(cnt):
        if not cnt:
            return 0
        return 1 + sum(cnt > q for q in cuts)

    c.add(frame(c))
    c.add(c.text(gx, 44, "CONTRIBUTIONS", 12, 500, BLUE_LIGHT, spacing=2.4, style=anim("rise", .6, T_GRAPH)))
    c.add(c.text(W - gx + (pitch - cell), 44, f"{total:,} in the last year", 13, 500, SUB, "end",
                 style=anim("rise", .6, T_GRAPH + .08)))
    # One rule per column, after the shared one, so squares sweep in left to right.
    if not STATIC:
        c.css.append(".q{animation:pop .45s cubic-bezier(.3,1.4,.5,1) both}"
                     + "".join(f".k{i}{{animation-delay:{T_GRAPH + .25 + i * .014:.3f}s}}" for i in range(cols)))

    rects, labelled = [], -9
    for d, cnt in days:
        col = (d - start).days // 7
        row = (d.weekday() + 1) % 7
        if d.day == 1 and col - labelled >= 3 and col <= cols - 2:
            labelled = col
            rects.append(c.text(gx + col * pitch, gy - 10, f"{d:%b}", 11, 400, MUTED,
                                style=anim("fade", .6, T_GRAPH + .25 + col * .014)))
        cls = "fb" if STATIC else f"fb q k{col}"
        rects.append(f'<rect x="{gx + col * pitch:.1f}" y="{gy + row * pitch:.1f}" width="{cell}" height="{cell}" '
                     f'rx="2.5" fill="{LEVELS[level(cnt)]}" class="{cls}"/>')
    c.add(*rects)

    ly = gy + 7 * pitch + 30
    right = W - gx + (pitch - cell)
    lx = right - 5 * pitch - measure("More", 11) - 6
    c.add(c.text(lx - 6, ly + 9.5, "Less", 11, 400, MUTED, "end", style=anim("fade", .6, T_GRAPH + 1)))
    for i, col in enumerate(LEVELS):
        c.add(f'<rect x="{lx + i * pitch:.1f}" y="{ly}" width="{cell}" height="{cell}" rx="2.5" fill="{col}" '
              f'style="{anim("fade", .6, T_GRAPH + 1 + .05 * i)}"/>')
    c.add(c.text(lx + 5 * pitch + 4, ly + 9.5, "More", 11, 400, MUTED, style=anim("fade", .6, T_GRAPH + 1.25)))
    c.add(c.text(gx, ly + 9.5, f"{active} active days  ·  updated {fmt_day(days[-1][0])}", 11, 400, MUTED,
                 style=anim("fade", .6, T_GRAPH + 1)))
    return c


def chart(data, s):
    W, H = 880, 340
    peaks = (f" Busiest day {fmt_day(s['busiest'][0])} with {s['busiest'][1]}. Best month {s['best'][0]:%B %Y}."
             if s["total"] else "")
    c = Card("activity", W, H,
             f"{s['total']:,} contributions in the last 12 months. Current streak {plural(s['current'], 'day')}, "
             f"longest {plural(s['longest'], 'day')}. {s['active']} active days.{peaks}")
    silver_defs(c)
    c.defs.append(f'<linearGradient id="best" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{BLUE_LIGHT}"/>'
                  f'<stop offset=".35" stop-color="{BLUE}"/><stop offset="1" stop-color="{BLUE_DEEP}"/></linearGradient>')
    c.defs.append('<linearGradient id="rest" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#3f3f46"/>'
                  f'<stop offset="1" stop-color="{FAINT}"/></linearGradient>')
    c.add(frame(c))
    x0 = 48
    m0, m1 = s["months"][0][0], s["months"][-1][0]
    span = f"ACTIVITY  ·  {m0:%b %Y} – {m1:%b %Y}".upper()
    c.add(c.text(x0, 50, span, 12, 500, BLUE_LIGHT, spacing=2.4, style=anim("rise", .6, T_CHART)))
    c.add(c.countup(x0, 102, s["total"], 44, 700, TEXT, T_CHART + .2, 1.1))
    c.add(c.text(x0 + measure(f"{s['total']:,}", 44, 700) + 12, 102, "contributions", 18, 400, SUB,
                 style=anim("rise", .7, T_CHART + .15)))

    # Stats, two by two.
    b_day, b_cnt = s["busiest"]
    m_day, m_cnt = s["best"]
    cells = [
        ("CURRENT STREAK", plural(s["current"], "day"), f"longest {plural(s['longest'], 'day')}"),
        ("ACTIVE DAYS", f"{s['active']}", f"of {s['span']} days"),
        ("BUSIEST DAY", f"{b_day:%b} {b_day.day}" if b_cnt else "—", plural(b_cnt, "contribution") if b_cnt else "no activity yet"),
        ("BEST MONTH", f"{m_day:%B}" if m_cnt else "—", plural(m_cnt, "contribution") if m_cnt else "no activity yet"),
    ]
    for i, (label, value, sub) in enumerate(cells):
        x = x0 + (i % 2) * 150
        y = 168 + (i // 2) * 84
        d = T_CHART + 1.0 + .1 * i
        c.add(f'<g style="{anim("rise", .7, d)}">',
              c.text(x, y, label, 10.5, 500, MUTED, spacing=1.6),
              c.text(x, y + 28, value, fit(value, 22, 700, 136), 700, TEXT, cls="num"),
              c.text(x, y + 48, sub, 12, 400, SUB), "</g>")

    # Bars, one per month; the best month in brand blue with its number on top.
    bx0, bx1, top, base = 360, W - 48, 150, 290
    slot = (bx1 - bx0) / 12
    bw = slot * .58
    peak = max(cnt for _, cnt in s["months"]) or 1
    c.add(f'<line x1="{bx0}" y1="{base + .5}" x2="{bx1}" y2="{base + .5}" stroke="#fff" stroke-opacity=".12" '
          f'stroke-dasharray="{bx1 - bx0}" style="--len:{bx1 - bx0};{anim("draw", .9, T_CHART + .2)}"/>')
    for i, (m, cnt) in enumerate(s["months"]):
        x = bx0 + slot * i + (slot - bw) / 2
        h = max(3, (base - top) * cnt / peak) if cnt else 3
        is_best = (m, cnt) == s["best"] and cnt > 0
        d = T_CHART + .35 + .05 * i
        c.add(f'<rect x="{x:.1f}" y="{base - h:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="4" '
              f'fill="url(#{"best" if is_best else "rest"})" class="fbb" style="{anim("grow", .8, d)}"/>')
        c.add(c.text(x + bw / 2, base + 22, f"{m:%b}", 11, 500 if is_best else 400, TEXT if is_best else MUTED, "middle",
                     style=anim("fade", .6, d)))
        if is_best:
            c.add(f'<g class="fb" style="{anim("pop", .6, T_CHART + 1.25, "cubic-bezier(.3,1.6,.5,1)")}">',
                  c.text(x + bw / 2, base - h - 10, f"{cnt:,}", 13, 700, BLUE_LIGHT, "middle", cls="num"), "</g>")
    return c


def tile(data, t, i):
    W, H = 280, 224
    delay = T_TILES + .15 * i
    raw = data.get(t["value"], t["value"])
    numeric = isinstance(raw, int)
    c = Card(f"tile-{t['slug']}", W, H, f"{t['kicker'].split('· ')[-1].title()}: {raw} {t['caption']}. {t['foot']}")
    acc = t["accent"]
    c.defs.append(f'<radialGradient id="glow" cx="1" cy="0" r="1"><stop offset="0" stop-color="{acc}" stop-opacity=".22"/>'
                  f'<stop offset=".6" stop-color="{acc}" stop-opacity="0"/></radialGradient>')
    c.defs.append('<linearGradient id="band" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff" stop-opacity="0"/>'
                  '<stop offset=".5" stop-color="#fff" stop-opacity=".09"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>')
    pad = 6
    c.add(f'<g class="fbb" style="{anim("swing", 1.1, delay, "cubic-bezier(.25,.9,.3,1)")}">')
    c.add(f'<rect x="{pad}" y="{pad}" width="{W - 2 * pad}" height="{H - 2 * pad}" rx="18" fill="{CARD}" stroke="#fff" stroke-opacity=".1"/>')
    c.defs.append(f'<clipPath id="clip"><rect x="{pad}" y="{pad}" width="{W - 2 * pad}" height="{H - 2 * pad}" rx="18"/></clipPath>')
    c.add(f'<rect x="{pad}" y="{pad}" width="{W - 2 * pad}" height="{H - 2 * pad}" rx="18" fill="url(#glow)"/>')
    # A soft band sweeps across every few seconds once the tile has landed; it rests off the card.
    if not STATIC:
        c.add(f'<g clip-path="url(#clip)"><g style="--to:{W + 220}px;{anim("sweep", 6, delay + 1.9, "ease-in-out", "infinite")}">'
              f'<rect x="-120" y="-20" width="90" height="{H + 40}" fill="url(#band)" transform="skewX(-18)"/></g></g>')
    x = 28
    c.add(c.text(x, 46, t["kicker"], 11, 500, acc, spacing=1.8))
    # Corner beacon: a dot with a ring pulsing out of it.
    c.add(f'<circle cx="{W - 34}" cy="42" r="4.5" fill="{acc}"/>',
          f'<circle cx="{W - 34}" cy="42" r="4.5" fill="none" stroke="{acc}" stroke-width="1.5" opacity="0" class="fb" '
          f'style="{anim("ring", 2.8, delay + 1.2, "ease-out", "infinite")}"/>')
    silver_defs(c)
    if numeric:
        size = fit(f"{raw:,}", 50, 700, W - 2 * x)
        c.add(c.countup(x, 124, raw, size, 700, "url(#silver)", delay + .45, .9))
    else:
        size = fit(str(raw), 46, 700, W - 2 * x, spacing=-1)
        c.add(c.text(x, 124, raw, size, 700, "url(#silver)", spacing=-1, style=anim("rise", .7, delay + .5)))
    c.add(c.text(x, 152, t["caption"], 14, 400, SUB, style=anim("fade", .7, delay + .65)))
    c.add(f'<line x1="{x}" y1="176.5" x2="{W - x}" y2="176.5" stroke="#fff" stroke-opacity=".08"/>')
    c.add(c.text(x, 201, t["foot"], 12, 400, MUTED), arrow(c, W - x, 202, acc, delay + 1.5))
    c.add("</g>")
    return c


def repo_card(data, f, i):
    r = data["repos"][f["repo"]]
    W, H = 436, 190
    delay = T_REPOS + .12 * i
    title = f.get("title") or f["repo"]
    desc = r["description"] or f.get("blurb") or ""
    c = Card(f"repo-{i + 1}", W, H, f"{title} ({f['repo']}): {desc}")
    c.add(f'<g style="{anim("rise", .8, delay)}">', frame(c, rx=18, fill=CARD))
    x = 26
    c.add(c.text(x, 42, f"FEATURED  ·  0{i + 1}", 10.5, 500, BLUE_LIGHT, spacing=1.8))
    c.add(arrow(c, W - x, 44, BLUE_LIGHT, delay + 1.4))
    c.add(c.text(x, 76, title, fit(title, 21, 700, W - 2 * x - 20), 700, TEXT))
    c.add(c.text(x, 97, f["repo"], 12, 400, MUTED))
    for j, line in enumerate(wrap(desc, 13, 400, W - 2 * x, 2)):
        c.add(c.text(x, 125 + 19 * j, line, 13, 400, SUB, style=anim("fade", .8, delay + .25 + .08 * j)))

    fy = H - 24
    fx = x
    lang, lc = r.get("language"), r.get("language_color") or MUTED
    if lang:
        c.add(f'<circle cx="{fx + 5}" cy="{fy - 4}" r="5" fill="{lc}" class="fb" '
              f'style="{anim("pop", .5, delay + .5, "cubic-bezier(.3,1.6,.5,1)")}"/>',
              c.text(fx + 16, fy, lang, 12, 400, SUB))
        fx += 16 + measure(lang, 12) + 18
    for count, path in ((r["stars"], STAR), (r["forks"], FORK)):
        if count:
            c.add(f'<path d="{path}" transform="translate({fx} {fy - 11}) scale(.8)" fill="{SUB}"/>',
                  c.text(fx + 17, fy, f"{count:,}", 12, 400, SUB, cls="num"))
            fx += 17 + measure(f"{count:,}", 12) + 16
    pushed = dt.date.fromisoformat(r["pushed_at"][:10])
    c.add(c.text(W - x, fy, f"Updated {pushed:%b %Y}", 12, 400, MUTED, "end"))
    c.add("</g>")
    return c


# Octicons star-fill-16 and repo-forked-16 (MIT, GitHub).
STAR = ("M8 .25a.75.75 0 0 1 .673.418l1.882 3.815 4.21.612a.75.75 0 0 1 .416 1.279l-3.046 2.97.719 4.192a.751.751 0 0 1"
        "-1.088.791L8 12.347l-3.766 1.98a.75.75 0 0 1-1.088-.79l.72-4.194L.818 6.374a.75.75 0 0 1 .416-1.28l4.21-.611"
        "L7.327.668A.75.75 0 0 1 8 .25Z")
FORK = ("M5 5.372v.878c0 .414.336.75.75.75h4.5a.75.75 0 0 0 .75-.75v-.878a2.25 2.25 0 1 1 1.5 0v.878a2.25 2.25 0 0 1"
        "-2.25 2.25h-1.5v2.128a2.251 2.251 0 1 1-1.5 0V8.5h-1.5A2.25 2.25 0 0 1 3.5 6.25v-.878a2.25 2.25 0 1 1 1.5 0Z"
        "M5 3.25a.75.75 0 1 0-1.5 0 .75.75 0 0 0 1.5 0Zm6.75.75a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Zm-3 8.75a.75.75 0 1 0"
        "-1.5 0 .75.75 0 0 0 1.5 0Z")


# ----------------------------------------------------------------- layout ----

def layout(cards, prefix, data):
    """The README markup: hero, graph, chart, a row of three tiles, repos two by two."""
    def img(card, width, href=None):
        tag = f'<img src="{prefix}/{card.name}.svg" width="{width}" alt="{esc(card.title)}" />'
        return f'<a href="{href}">{tag}</a>' if href else tag

    by = {c.name: c for c in cards}
    rows = [
        img(by["hero"], "100%", SITE),
        img(by["graph"], "100%", f"https://github.com/{data['login']}"),
        img(by["activity"], "100%"),
        "\n".join(img(by[f"tile-{t['slug']}"], "32.5%", t["url"]) for t in TILES),
    ]
    repos = [c for c in cards if c.name.startswith("repo-")]
    for j in range(0, len(repos), 2):
        rows.append("\n".join(img(c, "49.5%", c.href) for c in repos[j:j + 2]))
    return "\n\n".join(f'<p align="center">\n{r}\n</p>' for r in rows)


def write_readme(block):
    start, end = "<!-- cards:start -->", "<!-- cards:end -->"
    text = README.read_text()
    if start not in text or end not in text:
        print(f"render: {README.name} has no {start} / {end} markers; left it alone")
        return
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    README.write_text(f"{head}{start}\n{block}\n{end}{tail}")


def write_preview(block):
    page = ROOT / ".preview" / f"{MODE}.html"
    page.parent.mkdir(exist_ok=True)
    page.write_text(f"""<!doctype html><meta charset="utf-8"><title>README cards: {MODE}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{margin:0;background:#0d1117;color:#e6edf3;font:16px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}}
article{{max-width:838px;margin:24px auto;padding:24px;border:1px solid #30363d;border-radius:6px}}
p{{margin:0 0 16px}} img{{max-width:100%;vertical-align:top}}
@media (prefers-color-scheme:light){{body{{background:#fff}}article{{border-color:#d0d7de}}}}
</style>
<article>
{block}
</article>
""")
    return page


def main():
    data = load()
    s = stats(data)
    cards = [hero(data), graph(data), chart(data, s)]
    cards += [tile(data, t, i) for i, t in enumerate(TILES)]
    shown = 0
    for f in FEATURED:
        if f["repo"] not in data["repos"]:
            print(f"render: featured repo {f['repo']!r} is not in data/profile.json; skipped")
            continue
        card = repo_card(data, f, shown)
        card.href = data["repos"][f["repo"]]["url"]
        cards.append(card)
        shown += 1

    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.svg"):
        old.unlink()
    for card in cards:
        svg = card.svg()
        (OUT / f"{card.name}.svg").write_text(svg)
        print(f"render: {MODE:8} {card.name:16} {len(svg) / 1024:6.1f} KB")

    rel = os.path.relpath(OUT, ROOT / ".preview")
    page = write_preview(layout(cards, rel, data))
    if not STATIC:
        write_readme(layout(cards, "./cards", data))
    print(f"render: preview at {page.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
