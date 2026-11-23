"""Shareable stories: one small page per top story and per podcast episode, with its own link-preview image.

When someone shares a story to a group chat, the chat shows this page's title, one-line summary and image, and the
link opens the story itself (not the home page), with credit to the newsrooms or podcast it came from and a way into
the rest of the day. Every word on these pages comes from the day's published, already-checked files: nothing here
asks an AI for anything new.

Links never change once published: /s/<date>/<slug>.html. A top story replaced by the afternoon edition keeps its
page (the earlier edition is kept in data/hot_earlier/).
"""
from __future__ import annotations

import re
import textwrap
from pathlib import Path

FONTS = Path(__file__).resolve().parent.parent / "templates" / "fonts"
IMAGE_DAYS = 14   # preview images for the last two weeks; older pages fall back to the site image


def slug(text: str, n: int = 60) -> str:
    """Short, readable, stable URL part: 'Nvidia reinstates Jensen Huang as CEO' → 'nvidia-reinstates-jensen-huang-as-ceo'."""
    s = re.sub(r"[^a-z0-9]+", "-", text.lower().replace("’", "").replace("'", "")).strip("-")
    if len(s) > n:
        s = s[:n].rsplit("-", 1)[0]
    return s or "story"


def _ticker(raw: str) -> str:
    return raw.split("(")[-1].rstrip(")").strip()


def collect(hots: dict, earlier: dict, days: dict) -> list[dict]:
    """Every shareable story, newest day first, top stories before episodes. Same story twice on a day → one page."""
    out, taken = [], set()

    def add(s):
        key = (s["date"], s["slug"])
        if key in taken:
            return
        taken.add(key)
        s["path"] = f"s/{s['date']}/{s['slug']}.html"
        out.append(s)

    for date in sorted(set(hots) | set(earlier) | set(days), reverse=True):
        for edition, hot in (("latest", hots.get(date)), ("earlier", earlier.get(date))):
            if not hot:
                continue
            for n, t in enumerate(hot.get("topics", []), 1):
                by_src = {}
                for i in t.get("headline_ids", []):
                    h = hot.get("headlines", {}).get(i)
                    if h:
                        by_src.setdefault(h["source"], h)
                add({"kind": "hot", "date": date, "slug": slug(t["title"]), "title": t["title"],
                     "text": t["explanation"], "why": t.get("why_it_matters", ""), "tickers": t.get("tickers", []),
                     "links": list(by_src.values())[:4], "beat": t.get("beat"),
                     "anchor": f"hot-{n}" if edition == "latest" else None})
        good = sorted((i for i in days.get(date, []) if i["summary"]["worth_reading"]), key=lambda i: i["source_name"])
        for it in good:
            s = it["summary"]
            add({"kind": "episode", "date": date, "slug": slug(s["headline"]), "title": s["headline"], "text": s["tldr"],
                 "why": s.get("lesson", ""), "points": s.get("key_points", [])[:4], "terms": s.get("glossary", [])[:3],
                 "tickers": [_ticker(t) for t in s.get("tickers", [])], "source_name": it["source_name"],
                 "listen": it.get("url"), "anchor": it["id"], "id": it["id"]})
    return out


# ---------- link-preview image (1200×630, what WhatsApp, iMessage, X, Slack and Discord show) ----------
_BG, _INK, _MUTED, _ACCENT = (17, 17, 16), (240, 239, 236), (195, 194, 183), (92, 192, 162)


def _fit(draw, text, font_path, width, max_lines, sizes):
    """Largest font size (from sizes) at which text wraps into max_lines within width."""
    from PIL import ImageFont
    for size in sizes:
        font = ImageFont.truetype(str(font_path), size)
        avg = font.getlength("abcdefghijklmnopqrstuvwxyz") / 26
        lines = textwrap.wrap(text, max(8, int(width / avg)))
        while lines and max(draw.textlength(l, font=font) for l in lines) > width:  # wrap tighter until it fits
            lines = textwrap.wrap(text, max(8, int(len(max(lines, key=len)) * .92)))
        if len(lines) <= max_lines:
            return font, lines
    lines = textwrap.wrap(text, max(8, int(width / avg)))[:max_lines]
    lines[-1] = lines[-1].rstrip(" ,.;:") + "…"
    return font, lines


def image(story: dict, path: Path, pretty_date: str, moves: dict | None = None):
    """Draw the story's preview image as a small JPEG. moves: {symbol: change_pct} for the story's tickers."""
    from PIL import Image, ImageDraw, ImageFont
    W, H, M = 1200, 630, 72
    im = Image.new("RGB", (W, H), _BG)
    d = ImageDraw.Draw(im)
    for y in range(H):  # the app's dark green-to-black wash
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(15 + 2 * t), int(42 - 25 * t), int(35 - 19 * t)))
    bold, med = FONTS / "inter-700.ttf", FONTS / "inter-500.ttf"
    # brand mark + name
    d.rounded_rectangle([M, 56, M + 52, 108], 13, fill=(31, 111, 92))
    d.line([(M + 13, 91), (M + 24, 80), (M + 31, 87), (M + 40, 74)], fill=(255, 255, 255), width=6, joint="curve")
    d.text((M + 68, 82), "Stocksplain", font=ImageFont.truetype(str(bold), 34), fill=_INK, anchor="lm")
    kicker = ("TOP STORY" if story["kind"] == "hot" else story.get("source_name", "PODCAST").upper()) + "  ·  " + pretty_date.upper()
    d.text((M, 168), kicker, font=ImageFont.truetype(str(bold), 24), fill=_ACCENT, anchor="ls")
    font, lines = _fit(d, story["title"], FONTS / "fraunces-800.ttf", W - 2 * M, 3, (68, 62, 56, 50))
    y = 200
    for l in lines:
        d.text((M, y), l, font=font, fill=(255, 255, 255))
        y += int(font.size * 1.16)
    sub, slines = _fit(d, story["text"], med, W - 2 * M, 2, (30, 27))
    y += 18
    for l in slines:
        d.text((M, y), l, font=sub, fill=_MUTED)
        y += int(sub.size * 1.4)
    # footer: ticker moves (real prices from that day's snapshot) and the promise
    d.line([(M, H - 92), (W - M, H - 92)], fill=(44, 44, 42), width=2)
    x, chip = M, ImageFont.truetype(str(bold), 24)
    for sym, pct in list((moves or {}).items())[:3]:
        label = f"{sym} {'+' if pct >= 0 else '−'}{abs(pct):.1f}%"
        w = d.textlength(label, font=chip) + 28
        d.rounded_rectangle([x, H - 66, x + w, H - 26], 20, fill=(23, 48, 26) if pct >= 0 else (58, 28, 28))
        d.text((x + 14, H - 46), label, font=chip, fill=(76, 201, 76) if pct >= 0 else (240, 112, 112), anchor="lm")
        x += w + 12
    d.text((W - M, H - 46), "Explained in plain English →", font=ImageFont.truetype(str(med), 26), fill=_INK, anchor="rm")
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, "JPEG", quality=82, optimize=True, progressive=True)
