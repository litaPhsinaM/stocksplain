"""The morning email: today's top stories, markets and concept, sent to everyone who opted in.

Runs after the site is published (so every link works). Needs SUPABASE_DB_URL plus SMTP_USER / SMTP_PASS
(a Gmail address and its app password). Each person is emailed at most once a day (email_prefs.last_sent),
so re-running the job is safe.
"""
from __future__ import annotations

import html
import json
import os
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

SITE = "https://stocksplain.app/"
DATA = Path(__file__).resolve().parent.parent / "data"
INDEXES = {"^GSPC": "S&P 500", "^IXIC": "Nasdaq", "^DJI": "Dow"}


def _load(kind: str, day: str):
    p = DATA / kind / f"{day}.json"
    return json.loads(p.read_text()) if p.exists() else None


def _long_date(day: str) -> str:
    import datetime as dt
    d = dt.date.fromisoformat(day)
    return f"{d:%A}, {d:%B} {d.day}"


BEATS = {"markets": "📈", "economy": "🏦", "tech": "💻", "energy": "🛢️", "policy": "🏛️", "world": "🌍"}
_CUTS = (" as ", " amid ", " following ", " after ", " despite ", " while ", ", ", " with ", "; ", ": ")


def _short(title: str, limit: int = 48) -> str:
    """The headline's main clause, for the subject line: cut at the first natural break, never mid-word."""
    for c in _CUTS:
        i = title.find(c)
        if 22 <= i <= limit:
            return title[:i]
    return title if len(title) <= limit else title[:limit].rsplit(" ", 1)[0] + "…"


def _first_sentence(text: str, min_len: int = 40) -> str:
    """First sentence, without stopping at abbreviations like "U.S.", "Mr." or "Inc." """
    import re
    text = " ".join(text.split())
    for m in re.finditer(r"[.!?](?=\s+[A-Z0-9\"“‘(])", text):
        word = text[:m.end()].rsplit(" ", 1)[-1]
        if m.end() < min_len or re.fullmatch(r"(?:[A-Za-z]\.)+", word) or \
                word.rstrip(".") in {"Mr", "Mrs", "Ms", "Dr", "St", "Jr", "Sr", "Inc", "Corp", "Co", "Ltd", "vs", "No", "Gov", "Sen", "Rep"}:
            continue
        return text[:m.end()]
    return text


def subject_line(topics: list[dict], idx: list[dict], day: str) -> str:
    sp = next((i for i in idx if i["symbol"] == "^GSPC"), None)
    lead = _short(topics[0]["title"]) if topics else f"Your market lesson for {_long_date(day)}"
    more = f" + {len(topics) - 1} more" if len(topics) > 1 else ""
    mk = f" · S&P {sp['change_pct']:+.1f}%".replace("+-", "-").replace("-", "−") if sp else ""
    return lead + more + mk


def compose(day: str) -> dict | None:
    """Subject, preview line, plain text and HTML (with an {UNSUB} placeholder) for one day, or None if there's
    nothing to send. Everything comes from the day's published (already checked) files: no new AI writing here."""
    brief, hot, market, quiz = _load("briefs", day), _load("hot", day), _load("market", day), _load("quiz", day)
    if not brief and not hot:
        return None
    topics = (hot or {}).get("topics", [])[:5]
    lede = (brief or {}).get("big_picture", "")
    concept = (brief or {}).get("concept_of_the_day") or {}
    q = ((quiz or {}).get("questions") or [None])[0]
    idx = [i for i in (market or {}).get("indices", []) if i.get("symbol") in INDEXES and i.get("change_pct") is not None]
    link = lambda frag="": f"{SITE}?ref=email{frag}"
    e = html.escape
    pct = lambda x: f"{x:+.1f}%".replace("-", "−")

    subject = subject_line(topics, idx, day)
    preview = f"Quiz: {q['question']} Tap to answer." if q else _first_sentence(lede)

    # ---- plain text ----
    text = [f"Stocksplain · {_long_date(day)} · 3-minute read", ""]
    if idx:
        text += ["Markets (previous close): " + " · ".join(f"{INDEXES[i['symbol']]} {pct(i['change_pct'])}" for i in idx), ""]
    text += ["TODAY'S STORIES"]
    for n, t in enumerate(topics, 1):
        text += [f"{BEATS.get(t.get('beat'), '•')} {t['title']}", f"   {_first_sentence(t['explanation'])}",
                 f"   Why it matters: {link(f'#hot-{n}')}", ""]
    if q:
        text += ["QUICK QUIZ", q["question"]] + [f"   {'ABCD'[i]}. {o}" for i, o in enumerate(q["options"])]
        text += [f"Answer it (right answers earn +$100 play money): {link('#quiz')}", ""]
    if concept:
        text += [f"CONCEPT OF THE DAY: {concept.get('concept', '')}", _first_sentence(concept.get("explanation", "")),
                 f"Learn it in 60 seconds: {link()}", ""]
    text += ["For learning only, not financial advice. Summaries are written by AI and can contain mistakes.",
             "Unsubscribe: {UNSUB}"]

    # ---- HTML (email-safe: tables + inline styles) ----
    F = "Arial,Helvetica,sans-serif"
    mk_html = "".join(
        f"""<span style="display:inline-block;margin:0 6px 6px 0;padding:7px 10px;background:#f4f3ef;border-radius:8px;font:13px {F};color:#33332f">{e(INDEXES[i['symbol']])}
<b style="color:{'#17714f' if i['change_pct'] >= 0 else '#b3261e'}">{'▲' if i['change_pct'] >= 0 else '▼'}&nbsp;{pct(i['change_pct'])}</b></span>""" for i in idx)
    rows = "".join(
        f"""<tr><td style="padding:14px 0;border-top:1px solid #ecebe6">
<a href="{link(f'#hot-{n}')}" style="text-decoration:none;color:#1b1b19">
<div style="font:700 17px/1.35 Georgia,serif;color:#1b1b19">{BEATS.get(t.get('beat'), '•')}&nbsp; {e(t['title'])}</div>
<div style="font:15px/1.5 {F};color:#45443f;margin-top:5px">{e(_first_sentence(t['explanation']))}</div>
<div style="font:700 14px {F};color:#17714f;margin-top:7px">Why it matters →</div></a></td></tr>""" for n, t in enumerate(topics, 1))
    quiz_html = "" if not q else f"""<tr><td style="padding:18px;background:#1b1b19;border-radius:14px">
<div style="font:800 12px/1 {F};color:#3fbf8f;letter-spacing:.08em">QUICK QUIZ · +$100 PLAY MONEY</div>
<div style="font:700 18px/1.35 Georgia,serif;color:#ffffff;margin:10px 0 12px">{e(q['question'])}</div>
{''.join(f'<a href="{link("#quiz")}" style="display:block;margin:0 0 8px;padding:11px 14px;border:1px solid #4a4944;border-radius:10px;font:15px/1.35 {F};color:#f4f3ef;text-decoration:none"><b style="color:#3fbf8f">{"ABCD"[i]}</b>&nbsp; {e(o)}</a>' for i, o in enumerate(q['options']))}
<div style="font:13px {F};color:#b9b8b0;margin-top:4px">Tap an answer to check it on Stocksplain.</div></td></tr><tr><td height="18"></td></tr>"""
    concept_html = "" if not concept else f"""<tr><td style="padding:16px;background:#eef8f3;border-radius:14px">
<div style="font:800 12px/1 {F};color:#17714f;letter-spacing:.08em">CONCEPT OF THE DAY</div>
<div style="font:700 18px/1.35 Georgia,serif;color:#1b1b19;margin:8px 0 6px">{e(concept.get('concept', ''))}</div>
<div style="font:15px/1.5 {F};color:#33332f">{e(_first_sentence(concept.get('explanation', '')))}</div>
<a href="{link()}" style="display:inline-block;margin-top:8px;font:700 14px {F};color:#17714f;text-decoration:none">Learn it in 60 seconds →</a></td></tr>
<tr><td height="18"></td></tr>"""
    body = f"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light only"></head>
<body style="margin:0;background:#f4f3ef">
<div style="display:none;max-height:0;overflow:hidden;opacity:0">{e(preview)}{'&#847;&zwnj;&nbsp;' * 60}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f3ef"><tr><td align="center" style="padding:18px 10px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background:#fff;border-radius:18px"><tr><td style="padding:22px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr><td><a href="{link()}" style="font:800 21px Georgia,serif;color:#1b1b19;text-decoration:none">📈 Stocksplain</a>
<div style="font:13px {F};color:#6b6a64;margin-top:4px">{e(_long_date(day))} · 3-minute read</div></td></tr>
{f'<tr><td style="padding:14px 0 4px">{mk_html}<div style="font:12px {F};color:#8a8983;margin-top:5px">Previous close</div></td></tr>' if mk_html else ''}
<tr><td style="padding:16px 0 6px;font:800 12px {F};color:#6b6a64;letter-spacing:.08em">TODAY'S STORIES</td></tr>
<tr><td><table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows}</table></td></tr>
<tr><td height="14"></td></tr>
{quiz_html}{concept_html}
<tr><td align="center" style="padding:2px 0 10px"><a href="{link()}" style="display:inline-block;background:#3fbf8f;color:#0d2b20;font:800 16px {F};padding:14px 24px;border-radius:999px;text-decoration:none">Open today's lesson →</a></td></tr>
<tr><td style="padding-top:16px;border-top:1px solid #ecebe6;font:12px/1.5 {F};color:#8a8983">
For learning only, not financial advice. Summaries are written by AI from public podcasts and news and can contain mistakes; every story links to its sources on the site.<br>
You get this because you turned on the daily email at stocksplain.app. <a href="{{UNSUB}}" style="color:#8a8983">Unsubscribe in one tap</a>.</td></tr>
</table></td></tr></table></td></tr></table></body></html>"""
    return {"subject": subject, "preview": preview, "text": "\n".join(text), "html": body}


def recipients(conn, day: str) -> list[tuple[str, str, str]]:
    return conn.execute("""
        select p.user_id::text, u.email, p.token::text from public.email_prefs p join auth.users u on u.id = p.user_id
        where p.daily and u.email is not null and u.email_confirmed_at is not null
          and (p.last_sent is null or p.last_sent < %s::date)""", (day,)).fetchall()


def send(day: str, db_url: str, dry_run: bool = False) -> int:
    import psycopg
    msg = compose(day)
    if not msg:
        print("  (nothing to email today)")
        return 0
    user = (os.environ.get("SMTP_USER") or "").strip()
    pw = (os.environ.get("SMTP_PASS") or "").replace(" ", "").strip()  # Google shows app passwords with spaces
    if not dry_run and not (user and pw):
        print("  (no SMTP_USER/SMTP_PASS, skipping the daily email)")
        return 0
    sent = 0
    with psycopg.connect(db_url, autocommit=True) as conn:
        people = recipients(conn, day)
        print(f"Daily email: {len(people)} subscriber(s) due")
        if dry_run or not people:
            return 0
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=30) as s:
            s.login(user, pw)
            for uid, email, token in people:
                unsub = f"{SITE}unsubscribe.html?t={token}"
                m = EmailMessage()
                m["From"] = formataddr(("Stocksplain", user))
                m["To"] = email
                m["Subject"] = msg["subject"]
                m["Message-ID"] = make_msgid(domain="stocksplain.app")
                m["List-Unsubscribe"] = f"<{unsub}>, <mailto:{user}?subject=unsubscribe>"
                m.set_content(msg["text"].replace("{UNSUB}", unsub))
                m.add_alternative(msg["html"].replace("{UNSUB}", unsub), subtype="html")
                try:
                    s.send_message(m)
                except smtplib.SMTPException as ex:
                    print(f"  ! couldn't send to one subscriber: {type(ex).__name__}")
                    continue
                conn.execute("update public.email_prefs set last_sent = %s::date where user_id = %s::uuid", (day, uid))
                sent += 1
                time.sleep(0.5)  # stay well inside Gmail's sending pace
    print(f"  ✉ sent {sent}")
    return sent


if __name__ == "__main__":  # python -m digest.email_daily  (light: needs only psycopg)
    import datetime as dt
    import sys
    from zoneinfo import ZoneInfo
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import migrate
    send(dt.datetime.now(ZoneInfo("America/New_York")).date().isoformat(), migrate.db_url())
