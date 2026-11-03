"""A small client for the World Feed Monitor REST API.

This one file is the whole integration; the scripts in examples/ only use it.

    from wfm_client import WfmClient

    with WfmClient.from_env() as wfm:
        page = wfm.search(keywords="energy prices", country=["DE", "FR"])
        for article in page["data"]:
            print(article["title"], article["url"])

API reference: https://worldfeedmonitor.com/docs
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import httpx

API_URL = "https://api.worldfeedmonitor.com/v1"

# The filters GET /feeds/search accepts. The API silently ignores a name it does
# not know, so this client refuses one instead: a typo should fail loudly.
SEARCH_FILTERS = {
    "keywords",  # words in the title or text
    "title",  # words in the title only
    "country",  # ISO 3166-1 alpha-2 or alpha-3: "JP" or "JPN"
    "language",  # ISO 639-1: "ja"
    "macro_category",  # topic key: "politics"
    "publisher_category",  # the publisher's own category
    "continent",
    "continent_region",
    "source",  # publisher key or uuid, from /metadata/sources
    "source_type",
    "sector",
    "has_image",  # True / False
    "from_date",  # YYYY-MM-DD; without dates a search covers the last day
    "to_date",
    "sort",  # "relevance", "desc" (newest first) or "asc"
}

PLACEHOLDERS = {"", "your-api-key", "your-api-secret"}


class WfmError(Exception):
    """Base class. Every message says what happened and what to do about it."""


class WfmConfigError(WfmError):
    """The credentials are not set."""


class WfmAuthError(WfmError):
    """401: the API key or secret was not accepted."""


class WfmForbiddenError(WfmError):
    """403: the account cannot use the API yet (not active, or email not confirmed)."""


class WfmValidationError(WfmError):
    """422: a filter value the API does not know, or a page beyond what the plan reaches."""

    def __init__(self, message: str, errors: dict[str, list[str]]):
        super().__init__(message)
        self.errors = errors


class WfmRateLimitError(WfmError):
    """429: a plan allowance (per minute, day or month) is used up."""

    def __init__(self, message: str, retry_after: int | None, window: str | None, limit: int | None):
        super().__init__(message)
        self.retry_after = retry_after
        self.window = window
        self.limit = limit


class WfmNetworkError(WfmError):
    """The API could not be reached, or answered with a server error."""


class WfmClient:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        base_url: str = API_URL,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,  # tests pass a mock here
        on_wait: Callable[[str], None] | None = None,  # told before the client sleeps
        sleep: Callable[[float], None] = time.sleep,
    ):
        # HTTP Basic: the API key is the username and the secret the password.
        # httpx builds the Authorization header; this client never prints it.
        self._http = httpx.Client(
            base_url=base_url,
            auth=(api_key, api_secret),
            timeout=timeout,
            transport=transport,
            headers={"Accept": "application/json", "User-Agent": "worldfeedmonitor-python-example/0.1"},
        )
        self._on_wait = on_wait or (lambda message: None)
        self._sleep = sleep

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, **options: Any) -> WfmClient:
        """Credentials from WFM_API_KEY and WFM_API_SECRET, or a .env file in the current directory."""
        if env is None:
            _load_dotenv(Path(".env"))
            env = os.environ

        key = env.get("WFM_API_KEY", "").strip()
        secret = env.get("WFM_API_SECRET", "").strip()
        missing = [name for name, value in (("WFM_API_KEY", key), ("WFM_API_SECRET", secret)) if value in PLACEHOLDERS]
        if missing:
            raise WfmConfigError(
                f"{' and '.join(missing)} not set. Create a free account at https://worldfeedmonitor.com/register, "
                "create API credentials in the dashboard, and put them in .env (see .env.example)."
            )
        return cls(key, secret, base_url=env.get("WFM_API_URL", "").strip() or API_URL, **options)

    def __repr__(self) -> str:
        return f"WfmClient(base_url={str(self._http.base_url)!r})"

    def __enter__(self) -> WfmClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    # ------------------------------------------------------------------ endpoints

    def search(self, *, page: int = 1, **filters: Any) -> dict[str, Any]:
        """One page (25 articles) of GET /feeds/search. Returns {"meta": ..., "data": [...]}."""
        unknown = set(filters) - SEARCH_FILTERS
        if unknown:
            raise TypeError(f"Unknown search filter(s): {', '.join(sorted(unknown))}.")

        params = {name: _param(value) for name, value in filters.items() if value not in (None, "", [], ())}
        if page != 1:
            params["page"] = page
        return self._get("/feeds/search", params)

    def latest(self, *, country: Any = None, language: Any = None, topic: Any = None, page: int = 1) -> dict[str, Any]:
        """The newest articles from the last day.

        The REST API has no separate endpoint for this: it is a search, newest first.
        """
        return self.search(sort="desc", country=country, language=language, macro_category=topic, page=page)

    def pages(self, *, max_pages: int, **filters: Any) -> Iterator[dict[str, Any]]:
        """Page after page of a search, stopping at the last page or after max_pages, whichever comes first.

        There is deliberately no "fetch everything": every page is a request against your plan.
        """
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1.")
        for page in range(1, max_pages + 1):
            result = self.search(page=page, **filters)
            yield result
            if not result["meta"].get("has_next"):
                return

    def metadata(self, name: str, **params: Any) -> dict[str, Any]:
        """A metadata list such as "countries", "languages", "macro-categories" or "sources". Each call counts."""
        return self._get(
            f"/metadata/{name}", {key: _param(value) for key, value in params.items() if value is not None}
        )

    # ------------------------------------------------------------------- transport

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        retried = False
        while True:
            try:
                response = self._http.get(path, params=params)
            except httpx.TransportError as error:
                raise WfmNetworkError(f"Could not reach the World Feed Monitor API: {type(error).__name__}.") from None

            if response.is_success:
                return response.json()

            error = _error_for(response)

            # One polite retry, only where waiting is short and certain to help:
            # the per-minute allowance, and the API's brief "busy" answer.
            wait = _retry_delay(response, error)
            if wait is not None and not retried:
                self._on_wait(f"{error} Waiting {wait} s, then retrying once.")
                self._sleep(wait)
                retried = True
                continue

            raise error


def _param(value: Any) -> str:
    """Lists become comma-separated; booleans become true/false."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set)):
        return ",".join(str(item) for item in value)
    return str(value)


def _error_for(response: httpx.Response) -> WfmError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    message = body.get("message") or f"The API answered {response.status_code}."
    status = response.status_code

    if status == 401:
        return WfmAuthError(
            "World Feed Monitor did not accept WFM_API_KEY and WFM_API_SECRET. Check them; a lost secret "
            "cannot be shown again, so create a new credential in the dashboard."
        )
    if status == 403:
        # The API's own reason, e.g. "Account is not active" or "Email address not confirmed. ..."
        hint = "" if "confirm" in message.lower() else " Check that your account is active in the dashboard."
        return WfmForbiddenError(message.rstrip(".") + "." + hint)
    if status == 422:
        return WfmValidationError(message, body.get("errors") or {})
    if status == 429:
        retry_after = body.get("retry_after") or _int(response.headers.get("Retry-After"))
        return WfmRateLimitError(message, retry_after, body.get("window"), body.get("limit"))
    return WfmNetworkError(f"The API answered {status}: {message}")


def _retry_delay(response: httpx.Response, error: WfmError) -> int | None:
    if isinstance(error, WfmRateLimitError) and error.window == "minute" and error.retry_after is not None:
        return error.retry_after if error.retry_after <= 60 else None
    if response.status_code == 503:
        return min(_int(response.headers.get("Retry-After")) or 5, 30)
    return None


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _load_dotenv(path: Path) -> None:
    """KEY=VALUE lines into the environment, without overriding what is already set."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            value = value.strip().strip("'\"")
            if value not in PLACEHOLDERS:
                os.environ.setdefault(key.strip(), value)
