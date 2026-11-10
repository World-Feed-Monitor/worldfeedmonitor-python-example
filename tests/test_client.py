from __future__ import annotations

import httpx
import pytest
from fake_api import AUTH, KEY, SECRET, FakeApi, rate_limited

from wfm_client import (
    API_URL,
    WfmAuthError,
    WfmClient,
    WfmConfigError,
    WfmForbiddenError,
    WfmNetworkError,
    WfmRateLimitError,
    WfmValidationError,
)


def make(api: FakeApi, key: str = KEY, secret: str = SECRET, **options) -> WfmClient:
    return WfmClient(key, secret, transport=api.transport(), **options)


# ------------------------------------------------------------------ authentication


def test_every_request_carries_basic_auth_with_key_and_secret() -> None:
    api = FakeApi()
    with make(api) as wfm:
        wfm.search()
        wfm.metadata("countries")

    assert [r.headers["Authorization"] for r in api.requests] == [AUTH, AUTH]
    assert str(api.requests[0].url).startswith(API_URL + "/articles/search")


def test_wrong_credentials_raise_an_auth_error_that_says_what_to_check() -> None:
    with make(FakeApi(), secret="wrong") as wfm, pytest.raises(WfmAuthError, match="WFM_API_KEY and WFM_API_SECRET"):
        wfm.search()


def test_the_secret_never_appears_in_the_clients_repr() -> None:
    assert SECRET not in repr(make(FakeApi()))


# ---------------------------------------------------------------- configuration


def test_from_env_reads_the_credentials() -> None:
    api = FakeApi()
    with WfmClient.from_env({"WFM_API_KEY": KEY, "WFM_API_SECRET": SECRET}, transport=api.transport()) as wfm:
        wfm.search()
    assert api.requests[0].headers["Authorization"] == AUTH


@pytest.mark.parametrize(
    "env",
    [{}, {"WFM_API_KEY": KEY}, {"WFM_API_KEY": "your-api-key", "WFM_API_SECRET": "your-api-secret"}],
)
def test_missing_credentials_say_which_and_where_to_get_them(env: dict[str, str]) -> None:
    with pytest.raises(WfmConfigError, match="WFM_API_SECRET") as raised:
        WfmClient.from_env(env)
    assert "worldfeedmonitor.com/register" in str(raised.value)


def test_from_env_reads_a_dotenv_file_without_overriding_the_shell(tmp_path, monkeypatch) -> None:
    (tmp_path / ".env").write_text(f"WFM_API_KEY=from-file\nWFM_API_SECRET={SECRET}\n# a comment\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WFM_API_KEY", KEY)
    monkeypatch.delenv("WFM_API_SECRET", raising=False)

    api = FakeApi()
    with WfmClient.from_env(transport=api.transport()) as wfm:
        wfm.search()

    assert api.requests[0].headers["Authorization"] == AUTH  # shell key + file secret


# ----------------------------------------------------------- query construction


def test_filters_use_the_apis_names_lists_join_with_commas_and_booleans_are_words() -> None:
    api = FakeApi()
    with make(api) as wfm:
        wfm.search(
            keywords="energy prices",
            country=["DE", "FR"],
            topic="politics",
            has_image=True,
            from_date="2026-11-01",
            sort="desc",
            language=None,
            page=2,
        )

    assert dict(api.requests[0].url.params) == {
        "keywords": "energy prices",
        "country": "DE,FR",
        "topic": "politics",
        "has_image": "true",
        "from_date": "2026-11-01",
        "sort": "desc",
        "page": "2",
    }


def test_page_one_and_empty_filters_are_not_sent() -> None:
    api = FakeApi()
    with make(api) as wfm:
        wfm.search(keywords="", country=[])
    assert dict(api.requests[0].url.params) == {}


def test_a_misspelled_filter_fails_here_instead_of_being_ignored_by_the_api() -> None:
    with make(FakeApi()) as wfm, pytest.raises(TypeError, match="contry"):
        wfm.search(contry="JP")


def test_latest_is_a_newest_first_search() -> None:
    api = FakeApi()
    with make(api) as wfm:
        wfm.latest(country="JP", topic="technology")
    assert dict(api.requests[0].url.params) == {"sort": "desc", "country": "JP", "topic": "technology"}


# --------------------------------------------------------------------- pagination


def test_pages_stops_at_the_last_page() -> None:
    api = FakeApi(total=60)  # 3 pages
    with make(api) as wfm:
        pages = list(wfm.pages(max_pages=10, keywords="x"))

    assert [p["meta"]["current_page"] for p in pages] == [1, 2, 3]
    assert sum(len(p["data"]) for p in pages) == 60
    assert len(api.requests) == 3


def test_pages_never_goes_past_max_pages() -> None:
    api = FakeApi(total=1000)
    with make(api) as wfm:
        pages = list(wfm.pages(max_pages=2))
    assert len(pages) == 2 and len(api.requests) == 2


def test_pages_has_no_unlimited_mode() -> None:
    with make(FakeApi()) as wfm, pytest.raises(ValueError):
        list(wfm.pages(max_pages=0))


def test_a_successful_page_is_returned_as_the_api_sent_it() -> None:
    with make(FakeApi(total=3)) as wfm:
        result = wfm.search(country="JP")

    assert result["meta"]["total_items"] == 3
    assert result["data"][0]["url"] == "https://publisher.example/articles/1?ref=rss&lang=ja"
    assert result["data"][0]["published_at_utc"] == "2026-11-03T00:12:00Z"


# ----------------------------------------------------------------- rate limiting


def test_a_spent_minute_is_waited_out_once_then_retried() -> None:
    api = FakeApi(responses=[rate_limited("minute", 24)])
    slept, said = [], []
    with make(api, sleep=slept.append, on_wait=said.append) as wfm:
        result = wfm.search()

    assert result["data"]
    assert slept == [24] and len(api.requests) == 2
    assert "Waiting 24 s" in said[0]


def test_only_one_retry() -> None:
    api = FakeApi(responses=[rate_limited("minute", 5), rate_limited("minute", 5)])
    with make(api, sleep=lambda s: None) as wfm, pytest.raises(WfmRateLimitError):
        wfm.search()
    assert len(api.requests) == 2


def test_a_spent_day_is_not_waited_for() -> None:
    api = FakeApi(responses=[rate_limited("day", 36_000, limit=1000)])
    slept = []
    with make(api, sleep=slept.append) as wfm, pytest.raises(WfmRateLimitError) as raised:
        wfm.search()

    assert slept == [] and len(api.requests) == 1
    assert (raised.value.window, raised.value.retry_after, raised.value.limit) == ("day", 36_000, 1000)


def test_a_busy_api_is_retried_once_after_its_retry_after() -> None:
    api = FakeApi(
        responses=[
            httpx.Response(503, json={"message": "API temporarily busy. Retry shortly."}, headers={"Retry-After": "5"})
        ]
    )
    slept = []
    with make(api, sleep=slept.append) as wfm:
        wfm.search()
    assert slept == [5]


# ------------------------------------------------------------------- other errors


def test_an_inactive_account_gets_the_apis_reason() -> None:
    api = FakeApi(responses=[httpx.Response(403, json={"message": "Account is not active", "status": "inactive"})])
    with make(api) as wfm, pytest.raises(WfmForbiddenError, match="Account is not active. Check that your account"):
        wfm.search()


def test_an_unknown_filter_value_keeps_the_per_field_errors() -> None:
    body = {"message": "The selected country is invalid.", "errors": {"country": ["ZZZ is not a country we know."]}}
    api = FakeApi(responses=[httpx.Response(422, json=body)])
    with make(api) as wfm, pytest.raises(WfmValidationError) as raised:
        wfm.search(country="ZZZ")
    assert raised.value.errors == {"country": ["ZZZ is not a country we know."]}


def test_a_network_failure_is_a_network_error() -> None:
    with make(FakeApi(network_down=True)) as wfm, pytest.raises(WfmNetworkError, match="Could not reach"):
        wfm.search()


def test_a_server_error_without_a_json_body_is_still_explained() -> None:
    api = FakeApi(responses=[httpx.Response(502, text="Bad gateway")])
    with make(api) as wfm, pytest.raises(WfmNetworkError, match="502"):
        wfm.search()
