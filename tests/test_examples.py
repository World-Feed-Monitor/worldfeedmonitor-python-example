"""The example scripts, run end to end against the stand-in API."""

from __future__ import annotations

import base64
import csv
import io
import json
import sys

import _common
import export_news
import httpx
import latest_news
import pytest
import search_news
from fake_api import KEY, SECRET, FakeApi, article, rate_limited

from wfm_client import WfmClient


@pytest.fixture
def api(monkeypatch, tmp_path) -> FakeApi:
    """Every script's client talks to the stand-in, with credentials from the environment."""
    fake = FakeApi()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WFM_API_KEY", KEY)
    monkeypatch.setenv("WFM_API_SECRET", SECRET)

    def client() -> WfmClient:
        return WfmClient.from_env(
            transport=fake.transport(), sleep=lambda s: None, on_wait=lambda m: print(m, file=sys.stderr)
        )

    # Each script imported `client` by name, so each one's reference is replaced.
    for script in (search_news, latest_news, export_news):
        monkeypatch.setattr(script, "client", client)
    return fake


def run(script, monkeypatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", [script.__name__, *argv])
    with pytest.raises(SystemExit) as exited:
        _common.run(script.main)
    return exited.value.code


def no_secret_in(*texts: str) -> None:
    encoded = base64.b64encode(f"{KEY}:{SECRET}".encode()).decode()
    for text in texts:
        assert SECRET not in text and encoded not in text


def test_search_prints_articles_with_their_links_and_the_page_summary(api, monkeypatch, capsys) -> None:
    code = run(search_news, monkeypatch, "--keywords", "energy prices", "--country", "DE,FR", "--sort", "desc")

    out, err = capsys.readouterr()
    assert code == 0
    assert dict(api.requests[0].url.params) == {"keywords": "energy prices", "country": "DE,FR", "sort": "desc"}
    assert "• Example headline 1" in out
    assert "Example Daily, Japan | 2026-11-03 00:12:00 UTC" in out
    assert "https://publisher.example/articles/1?ref=rss&lang=ja" in out
    assert "Page 1 of 3, 60 article(s)." in out and "Next page: add --page 2" in out
    no_secret_in(out, err)


def test_latest_asks_for_newest_first(api, monkeypatch, capsys) -> None:
    assert run(latest_news, monkeypatch, "--country", "JP", "--topic", "technology") == 0
    assert dict(api.requests[0].url.params) == {"sort": "desc", "country": "JP", "macro_category": "technology"}


def test_no_results_say_so(api, monkeypatch, capsys) -> None:
    api.total = 0
    assert run(search_news, monkeypatch, "--keywords", "nothing") == 0
    assert "No articles matched" in capsys.readouterr().out


def test_missing_credentials_exit_with_a_message(api, monkeypatch, capsys) -> None:
    monkeypatch.delenv("WFM_API_SECRET")
    monkeypatch.setattr(search_news, "client", lambda: WfmClient.from_env())
    code = run(search_news, monkeypatch)
    assert "WFM_API_SECRET not set" in str(code)


def test_a_spent_day_exits_with_when_it_resets(api, monkeypatch) -> None:
    api.responses = [rate_limited("day", 3600, limit=1000)]
    code = run(search_news, monkeypatch)
    assert "Rate limit" in str(code) and "resets in 3600 s" in str(code)


def test_a_waited_minute_is_announced_on_stderr(api, monkeypatch, capsys) -> None:
    api.responses = [rate_limited("minute", 3)]
    assert run(search_news, monkeypatch) == 0
    assert "Waiting 3 s, then retrying once." in capsys.readouterr().err


def test_export_writes_csv_across_a_capped_number_of_pages(api, monkeypatch, tmp_path) -> None:
    api.total = 60
    assert run(export_news, monkeypatch, "--topic", "environment", "--pages", "2", "--output", "out.csv") == 0

    rows = list(csv.DictReader((tmp_path / "out.csv").open(encoding="utf-8")))
    assert len(api.requests) == 2 and len(rows) == 50
    assert rows[0]["url"] == "https://publisher.example/articles/1?ref=rss&lang=ja"
    assert rows[0]["published_at_utc"] == "2026-11-03T00:12:00Z"
    assert rows[0]["topics"] == "Technology" and rows[0]["country"] == "JP"


def test_export_writes_the_api_objects_as_json(api, monkeypatch, tmp_path) -> None:
    api.total = 3
    assert run(export_news, monkeypatch, "--country", "JP", "--format", "json", "--output", "out.json") == 0

    saved = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert saved["filters"] == {"country": "JP"}
    assert saved["articles"][0] == article(1)


def test_export_keeps_what_it_has_when_the_plan_stops_paging(api, monkeypatch, tmp_path, capsys) -> None:
    api.total = 1000
    refusal = {
        "message": "Your plan reaches the first 100 results. Narrow the search to find what you need.",
        "errors": {},
    }
    # Pages 1 and 2 succeed (generated), page 3 is refused.
    original = api.handle

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "3":
            api.requests.append(request)
            return httpx.Response(422, json=refusal)
        return original(request)

    api.handle = handle
    assert run(export_news, monkeypatch, "--pages", "5", "--output", "out.csv") == 0

    assert len(list(csv.DictReader((tmp_path / "out.csv").open(encoding="utf-8")))) == 50
    assert "Stopped early: Your plan reaches the first 100 results" in capsys.readouterr().err


def test_export_refuses_more_than_its_cap(api, monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["export_news", "--pages", "50", "--output", "out.csv"])
    with pytest.raises(SystemExit):
        export_news.main()
    assert "invalid choice" in capsys.readouterr().err
    assert api.requests == []


def test_csv_writer_handles_missing_fields() -> None:
    out = io.StringIO()
    export_news.write_csv([{"title": "Undated", "url": "https://x.example", "published_at": None}], out)
    row = next(csv.DictReader(io.StringIO(out.getvalue())))
    assert row["title"] == "Undated" and row["source"] == "" and row["published_at_utc"] == ""
