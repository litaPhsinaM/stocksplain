"""Core safety tests: the NYSE calendar, the fact checks, and forecast parsing.
Run: .venv/bin/python -m pytest -q"""
import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from digest import checks, claims, hours

NY = ZoneInfo("America/New_York")


# ---------- market hours (prices fill trades only when the market is really open) ----------

@pytest.mark.parametrize("when, open_", [
    ("2026-11-12 10:00", True),    # Thursday, regular session
    ("2026-11-12 09:29", False),   # one minute before the open
    ("2026-11-12 16:01", False),   # after the close
    ("2026-11-14 12:00", False),   # Saturday
    ("2026-11-26 12:00", False),   # Thanksgiving
    ("2026-11-27 12:30", True),    # day after Thanksgiving, early close at 1 pm
    ("2026-11-27 13:30", False),   # ...so closed by 1:30 pm
    ("2026-12-25 12:00", False),   # Christmas
])
def test_market_open(when, open_):
    assert hours.is_open(dt.datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=NY)) is open_


def test_session_times():
    assert hours.session(dt.date(2026, 11, 14)) is None                      # weekend
    o, c = hours.session(dt.date(2026, 11, 27))
    assert (o.hour, o.minute, c.hour) == (9, 30, 13)                         # early close
    assert hours.session(dt.date(2026, 11, 12))[1].hour == 16                # normal close


# ---------- fact checks (numbers, dates, advice must come from / respect the source) ----------

def summary(**over):
    s = {"headline": "Nvidia shares fall after CEO scandal", "tldr": "Nvidia fell 30% after the scandal.",
         "key_points": [{"point": "Shares fell 30%.", "why_it_matters": "Leadership risk."}],
         "numbers": [{"figure": "30%", "context": "drop since October"}],
         "opinions_and_predictions": [], "segments": [], "tickers": [],
         "lesson": "When a company depends on one leader, doubts about that person move the stock.",
         "quality_note": "An analyst speaking; the figures are data-backed."}
    s.update(over)
    return s


TRANSCRIPT = "Nvidia is off more than 30% since the scandal broke in October."


def test_clean_summary_passes():
    assert checks.check_item(summary(), TRANSCRIPT) == []


def test_invented_figure_is_dropped():
    s = summary(numbers=[{"figure": "45%", "context": "made-up drop"}, {"figure": "30%", "context": "real"}])
    checks.check_item(s, TRANSCRIPT)
    assert [n["figure"] for n in s["numbers"]] == ["30%"]


def test_invented_number_in_prose_is_flagged():
    problems = checks.check_item(summary(tldr="Nvidia fell 42% after the scandal."), TRANSCRIPT)
    assert any("42" in p for p in problems)


def test_invented_date_is_flagged():
    problems = checks.check_item(summary(tldr="Nvidia fell 30% on November 3rd."), TRANSCRIPT)
    assert any("November 3rd" in p for p in problems)


def test_advice_is_flagged():
    problems = checks.check_item(summary(tldr="Investors should buy the dip: Nvidia fell 30%."), TRANSCRIPT)
    assert any("advice" in p for p in problems)


def test_recap_lesson_is_flagged():
    problems = checks.check_item(summary(lesson="This episode covers Nvidia's scandal."), TRANSCRIPT)
    assert any("lesson" in p for p in problems)


# ---------- forecasts (Scorecard): deadlines, kinds, quotes ----------

SAID = dt.date(2026, 11, 10)


@pytest.mark.parametrize("iso, said, expected", [
    ("2026-12-17", "", dt.date(2026, 12, 17)),
    ("none", "by year end", dt.date(2026, 12, 31)),
    ("none", "next year", dt.date(2027, 12, 31)),
    ("none", "at the December meeting", dt.date(2026, 12, 31)),
    ("none", "early 2028", dt.date(2028, 3, 31)),
    ("none", "not specified", None),
])
def test_deadlines(iso, said, expected):
    assert claims.resolve_deadline(iso, said, SAID) == expected


@pytest.mark.parametrize("text, kind", [
    ("The Fed will hike rates in December", "rate_hike"),
    ("The Fed will ease policy next year", "rate_cut"),
    ("M&A activity will increase next year", "other"),   # 'increase' must not read as a Fed 'ease'
    ("Stocks will rally into year end", "up"),
])
def test_infer_kind(text, kind):
    assert claims.infer_kind("other", text) == kind


def test_quote_must_be_in_transcript():
    flat = claims._norm("I think the Fed will raise rates by fifty basis points at the December meeting, honestly.")
    assert claims.quote_in("the Fed will raise rates by fifty basis points at the December meeting", flat)
    assert claims.quote_in("the Fed will raise rates by 50 basis points at the December meeting", flat)  # one word off
    assert not claims.quote_in("the Fed will cut rates sharply in the spring because inflation is falling", flat)


# ---------- model routing (each morning job goes to the model that's best at it, with fallbacks) ----------

def test_each_job_has_its_own_first_choice_and_fallbacks():
    from digest import summarize
    firsts = {t: summarize.task_models(t)[0] for t in ("summary", "forecasts", "top_stories", "brief", "quiz", "audio_script")}
    assert "gemini-3-flash-preview" not in firsts.values()   # 504s most mornings: only a last resort
    assert firsts["brief"] == "gemini-3.6-flash"
    for t in firsts:
        assert len(summarize.task_models(t)) >= 4          # never a single point of failure
        assert "gemini-3.1-flash-lite" in summarize.task_models(t)


def test_every_answer_shape_maps_to_a_job():
    from digest import summarize
    for schema in (summarize.ItemSummary, summarize.Quiz, summarize.Briefing, summarize.DailyBrief, summarize.HotTopics):
        assert schema.__name__ in summarize._SCHEMA_TASK


def test_forecast_prompt_rejects_facts_and_moods():
    for phrase in ("already happened", "descriptions of the present", "vague moods", "List each forecast once"):
        assert phrase in claims.PROMPT


# ---------- 60-second stories and name spellings ----------
def test_story_slides_skip_repeats():
    from digest.build import story_slides
    hot = {"topics": [
        {"title": "Nvidia CEO Jensen Huang resigns", "explanation": "x", "why_it_matters": "y", "tickers": ["NVDA"]},
        {"title": "NVIDIA shares slide after Huang exit", "explanation": "x", "why_it_matters": "y", "tickers": ["NVDA"]},
        {"title": "Oil prices jump on OPEC cut", "explanation": "x", "why_it_matters": "y", "tickers": []}]}
    item = lambda src, head, kps: {"id": src, "source_name": src, "summary": {
        "headline": head, "tldr": "t", "lesson": "l", "tickers": ["Nvidia (NVDA)"],
        "key_points": [{"point": p, "why_it_matters": "w"} for p in kps]}}
    items = [item("A", "Nvidia's CEO resigns amid scandal", ["Huang quit on Thursday", "October inflation rose 0.4%"]),
             item("B", "Nvidia CEO Jensen Huang steps down", ["Nvidia named an interim CEO"])]
    titles = [s["title"] for s in story_slides(hot, items)]
    assert titles == ["Nvidia CEO Jensen Huang resigns", "Oil prices jump on OPEC cut", "October inflation rose 0.4%"]


def test_name_fixes_use_headline_spelling():
    from digest import checks
    ref = ["Nvidia names CFO Colette Kress interim CEO", "Democrat Scott Colom wins Mississippi Senate seat"]
    fx = checks.name_fixes(["Collette Kress named", "Colet Kress", "Scott Colm won", "John Smith", "Jensen Huang"], ref)
    assert fx == {"Collette Kress": "Colette Kress", "Colet Kress": "Colette Kress", "Scott Colm": "Scott Colom"}
    assert checks.fix_names({"a": ["Colet Kress said"]}, fx) == {"a": ["Colette Kress said"]}


# ---------- scorecard: Fed decisions and official numbers ----------
def test_official_forecasts_score_from_data(monkeypatch):
    import datetime as dt
    from digest import claims
    vals = {}
    monkeypatch.setattr(claims, "_fred_value", lambda series, how, day: vals[(series, day.isoformat())])
    base = {"id": "x", "said_on": "2026-11-10", "deadline": "2026-12-31", "status": "open"}
    vals.update({("DFEDTARU", "2026-11-10"): (4.0, "2026-11-10"), ("DFEDTARU", "2026-12-31"): (4.25, "2026-12-31")})
    hike = {**base, "kind": "rate_hike", "target": 0.25}
    assert claims._resolve_official(hike, dt.date(2026, 12, 20)) == 0          # too early: waits for the data
    assert claims._resolve_official(hike, dt.date(2027, 1, 5)) == 1 and hike["status"] == "right"
    big = {**base, "kind": "rate_hike", "target": 0.5}
    claims._resolve_official(big, dt.date(2027, 1, 5)); assert big["status"] == "wrong"   # hiked, but not by 50
    vals.update({("MORTGAGE30US", "2026-11-10"): (7.18, "2026-11-06"), ("MORTGAGE30US", "2026-12-31"): (7.31, "2026-12-30")})
    m = {**base, "kind": "metric_below", "metric": "mortgage_30y", "target": 7.25}
    claims._resolve_official(m, dt.date(2027, 1, 20)); assert m["status"] == "wrong" and m["end_value"] == 7.31
    vals[("MORTGAGE30US", "2026-12-31")] = (7.0, "2026-10-01")                 # stale reading: don't score
    m2 = {**base, "kind": "metric_below", "metric": "mortgage_30y", "target": 7.25}
    assert claims._resolve_official(m2, dt.date(2027, 1, 20)) == 0 and m2["status"] == "open"


def test_name_fixes_sound_alike_surname():
    from digest import checks
    fx = checks.name_fixes(["Jensen Wong resigned", "Wailin Wong hosts", "Alice Wong"], ["Jensen Huang quits"])
    assert fx.get("Jensen Wong") == "Jensen Huang"
    assert "Wailin Wong" not in fx and "Alice Wong" not in fx


def test_claude_steps_in_only_for_text_when_gemini_fails(monkeypatch):
    from digest import summarize as S
    def down(*a, **k):
        raise RuntimeError("no Gemini model answered")
    monkeypatch.setattr(S, "_gemini_call", down)
    monkeypatch.setattr(S, "_claude_generate", lambda prompt, schema: ("claude", prompt))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    assert S._gemini_generate(["a", "b"], S.Quiz) == ("claude", "a\n\nb")
    with pytest.raises(RuntimeError):            # audio/video can't go to Claude
        S._gemini_generate([object(), "prompt"], S.Quiz)
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with pytest.raises(RuntimeError):            # no key: fail as before
        S._gemini_generate(["a"], S.Quiz)


def test_email_subject_is_short_and_true_to_the_data():
    from digest.email_daily import subject_line, _short
    t = [{"title": "Nvidia reports strong quarterly earnings beat as board rules out reinstating former CEO"}, {"title": "x"}]
    s = subject_line(t, [{"symbol": "^GSPC", "change_pct": -0.23}], "2026-11-18")
    assert s == "Nvidia reports strong quarterly earnings beat + 1 more · S&P −0.2%"
    assert _short("A" * 70).endswith("…") or len(_short("A" * 70)) <= 49


def test_email_first_sentence_skips_abbreviations():
    from digest.email_daily import _first_sentence
    assert _first_sentence("U.S. stocks fell on Tuesday as Mr. Powell spoke. Bonds rose.") == \
        "U.S. stocks fell on Tuesday as Mr. Powell spoke."


# ---------- shareable story pages and the afternoon edition ----------

def test_story_slugs_are_short_and_stable():
    from digest import share
    assert share.slug("Nvidia’s CEO returns: S&P 500 +2%") == "nvidias-ceo-returns-s-p-500-2"
    long = share.slug("word " * 40)
    assert len(long) <= 60 and not long.endswith("-") and long.endswith("word")


def test_shared_links_survive_the_afternoon_edition():
    from digest import share
    topic = lambda t: {"title": t, "explanation": "x", "why_it_matters": "y", "tickers": [], "headline_ids": []}
    morning = {"topics": [topic("Oil jumps"), topic("Fed holds rates")], "headlines": {}}
    afternoon = {"topics": [topic("Fed holds rates"), topic("Stocks close higher")], "headlines": {}}
    got = share.collect({"2026-11-23": afternoon}, {"2026-11-23": morning}, {})
    paths = [s["path"] for s in got]
    assert len(paths) == len(set(paths)) == 3   # the repeated story is one page
    assert "s/2026-11-23/oil-jumps.html" in paths   # the morning-only story keeps its page
    anchors = {s["slug"]: s["anchor"] for s in got}
    assert anchors["fed-holds-rates"] == "hot-1" and anchors["oil-jumps"] is None


def test_rerun_keeps_the_quiz_people_answered(tmp_path, monkeypatch):
    import json
    import run
    for name in ("ITEMS", "HOT", "QUIZ", "AUDIO", "BRIEFS"):
        (tmp_path / name).mkdir()
        monkeypatch.setattr(run, name, tmp_path / name)
    (tmp_path / "HOT" / "2026-11-23.json").write_text(json.dumps({"topics": []}))
    (tmp_path / "QUIZ" / "2026-11-23.json").write_text('{"keep": true}')
    (tmp_path / "AUDIO" / "2026-11-23.mp3").write_bytes(b"x")
    monkeypatch.setattr(run.summarize, "quiz", lambda *a: pytest.fail("the quiz was rewritten"))
    run.write_extras("2026-11-23")
    assert json.loads((tmp_path / "QUIZ" / "2026-11-23.json").read_text()) == {"keep": True}


def test_groq_steps_in_before_claude_with_a_prompt_that_fits(monkeypatch):
    from digest import summarize as S
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(S, "_gemini_call", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(S, "_claude_generate", lambda *a: pytest.fail("Claude was asked before the free backup"))
    seen = []
    monkeypatch.setattr(S, "_groq_generate", lambda p, schema: seen.append(p) or "ok")
    big = "x" * (S.GROQ_MAX_PROMPT_CHARS + 1)
    assert S._gemini_generate([big], S.Quiz, small=lambda b: "short " * 3) == "ok"
    assert seen == ["short short short "]


def test_compact_material_fits_and_only_cuts():
    from digest import summarize as S
    item = {"id": "a", "source_name": "Pod", "summary": {"headline": "H", "tldr": "word " * 200,
            "key_points": ["p " * 100] * 5, "lesson": "l " * 100}}
    m = S._compact([item] * 30, None, 4000)
    assert len(m) <= 4000 and '"headline":"H"' in m


def test_backup_answer_keeps_good_entries_and_drops_bad_ones():
    import json
    from pydantic import BaseModel
    from typing import Literal
    from digest import summarize as S

    class Tag(BaseModel):
        term: str
        topic: Literal["stocks", "other"]

    class Tags(BaseModel):
        tags: list[Tag]

    raw = json.dumps({"tags": [{"term": "a", "topic": "stocks"}, {"term": "b", "topic": "nonsense"}, {"term": "c", "topic": "other"}]})
    assert [t.term for t in S._validate_dropping_bad_items(Tags, raw).tags] == ["a", "c"]


def test_after_one_full_outage_later_jobs_dont_wait_again(monkeypatch):
    from digest import summarize as S
    monkeypatch.setattr(S, "_gemini_outage", False)
    slept = []
    monkeypatch.setattr(S.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(S, "_pace", lambda: None)
    monkeypatch.setattr(S, "_with_deadline", lambda f, t: (_ for _ in ()).throw(TimeoutError()))
    from google.genai import types
    cfg = types.GenerateContentConfig()
    for _ in range(2):
        with pytest.raises(RuntimeError):
            S._gemini_call(["x"], cfg, lambda r: r, models=["m"])
    assert slept == [20, 60, 120]   # the full backoff happened once, not twice
