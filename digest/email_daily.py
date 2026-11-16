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


def compose(day: str) -> dict | None:
    """Subject, plain text and HTML (with a {UNSUB} placeholder) for one day, or None if there's nothing to send."""
    brief, hot, market, quiz = _load("briefs", day), _load("hot", day), _load("market", day), _load("quiz", day)
    if not brief and not hot:
        return None
    topics = (hot or {}).get("topics", [])[:5]
    lede = (brief or {}).get("big_picture", "")
    concept = (brief or {}).get("concept_of_the_day") or {}
    idx = [i for i in (market or {}).get("indices", []) if i.get("symbol") in INDEXES and i.get("change_pct") is not None]
    link = lambda frag="": f"{SITE}?ref=email{frag}"
    e = html.escape

    subject = topics[0]["title"] if topics else f"Your 5-minute market lesson for {_long_date(day)}"
    if len(subject) > 90:
        subject = subject[:87].rsplit(" ", 1)[0] + "…"

    mk = " · ".join(f"{INDEXES[i['symbol']]} {i['change_pct']:+.1f}%" for i in idx)
    text = [f"Stocksplain · {_long_date(day)}", "", lede, ""]
    for n, t in enumerate(topics, 1):
        text += [f"{n}. {t['title']}", t["explanation"], f"Why it matters: {t['why_it_matters']}", ""]
    if mk:
        text += [f"Markets (previous close): {mk}", ""]
    if concept:
        text += [f"Concept of the day: {concept.get('concept', '')}", concept.get("explanation", ""), ""]
    text += [f"Read it all, swipe the 60-second version{' and take the 3-question quiz' if quiz else ''}: {link()}", "",
             "For learning only, not financial advice. Summaries are written by AI and can contain mistakes.",
             "Unsubscribe: {UNSUB}"]

    rows = "".join(
        f"""<tr><td style="padding:14px 0;border-top:1px solid #e6e4dd">
<div style="font:700 12px/1 Arial,sans-serif;color:#3fbf8f;letter-spacing:.06em">#{n}</div>
<div style="font:700 17px/1.35 Georgia,serif;color:#1b1b19;margin:6px 0">{e(t['title'])}</div>
<div style="font:15px/1.5 Arial,sans-serif;color:#33332f">{e(t['explanation'])}</div>
<div style="font:14px/1.5 Arial,sans-serif;color:#5c5b55;margin-top:6px"><b>Why it matters:</b> {e(t['why_it_matters'])}</div>
</td></tr>""" for n, t in enumerate(topics, 1))
    mk_html = "".join(
        f"""<td style="padding:8px 10px;background:#f4f3ef;border-radius:8px;font:13px Arial,sans-serif;color:#33332f">{e(INDEXES[i['symbol']])}
<b style="color:{'#17714f' if i['change_pct'] >= 0 else '#b3261e'}">{i['change_pct']:+.1f}%</b></td><td width="6"></td>""" for i in idx)
    concept_html = f"""<tr><td style="padding:16px;background:#eef8f3;border-radius:12px">
<div style="font:700 12px/1 Arial,sans-serif;color:#17714f;letter-spacing:.06em">CONCEPT OF THE DAY</div>
<div style="font:700 17px/1.35 Georgia,serif;color:#1b1b19;margin:6px 0">{e(concept.get('concept', ''))}</div>
<div style="font:15px/1.5 Arial,sans-serif;color:#33332f">{e(concept.get('explanation', ''))}</div></td></tr>
<tr><td height="16"></td></tr>""" if concept else ""
    body = f"""<!doctype html><html><body style="margin:0;background:#f4f3ef">
<div style="display:none;max-height:0;overflow:hidden">{e(lede[:140])}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f3ef"><tr><td align="center" style="padding:20px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background:#fff;border-radius:16px;padding:24px">
<tr><td><a href="{link()}" style="font:800 20px Georgia,serif;color:#1b1b19;text-decoration:none">📈 Stocksplain</a>
<div style="font:13px Arial,sans-serif;color:#5c5b55;margin-top:4px">{e(_long_date(day))} · your 5-minute market lesson</div></td></tr>
<tr><td style="padding:16px 0 6px;font:16px/1.55 Arial,sans-serif;color:#1b1b19">{e(lede)}</td></tr>
{f'<tr><td style="padding:8px 0 4px"><table role="presentation" cellpadding="0" cellspacing="0"><tr>{mk_html}</tr></table><div style="font:12px Arial,sans-serif;color:#6b6a64;margin-top:4px">Previous close · Yahoo Finance</div></td></tr>' if mk_html else ''}
<tr><td><table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows}</table></td></tr>
<tr><td height="8"></td></tr>
{concept_html}
<tr><td align="center" style="padding:4px 0 8px"><a href="{link()}" style="display:inline-block;background:#3fbf8f;color:#0d2b20;font:700 16px Arial,sans-serif;padding:13px 22px;border-radius:999px;text-decoration:none">Read today{' + take the quiz' if quiz else ''} →</a></td></tr>
<tr><td style="padding-top:18px;border-top:1px solid #e6e4dd;font:12px/1.5 Arial,sans-serif;color:#6b6a64">
For learning only, not financial advice. Summaries are written by AI from public podcasts and news and can contain mistakes; every story links to its source on the site.<br>
You get this because you asked for the daily email on stocksplain.app. <a href="{{UNSUB}}" style="color:#6b6a64">Unsubscribe in one tap</a>.</td></tr>
</table></td></tr></table></body></html>"""
    return {"subject": subject, "text": "\n".join(text), "html": body}


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
    user, pw = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASS")
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
