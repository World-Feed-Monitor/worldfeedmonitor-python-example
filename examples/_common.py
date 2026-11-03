"""What the example scripts share: their filter options, printing, and error exits."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from typing import Any

from wfm_client import WfmClient, WfmConfigError, WfmError, WfmRateLimitError, WfmValidationError


def add_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--keywords", help='words in the title or text, e.g. "energy prices"')
    parser.add_argument("--country", help="ISO codes, comma-separated: JP or JPN,KOR")
    parser.add_argument("--language", help="ISO 639-1 codes, comma-separated: ja,en")
    parser.add_argument("--topic", help="topic keys, comma-separated: politics,business")
    parser.add_argument("--source", help="publisher keys, comma-separated (see /metadata/sources)")
    parser.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD", help="earliest date (default: last day)")
    parser.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD", help="latest date")
    parser.add_argument(
        "--sort", choices=["relevance", "desc", "asc"], help="default: relevance with keywords, else newest"
    )


def filters_from(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "keywords": args.keywords,
        "country": args.country,
        "language": args.language,
        "macro_category": args.topic,
        "source": args.source,
        "from_date": args.from_date,
        "to_date": args.to_date,
        "sort": args.sort,
    }


def client() -> WfmClient:
    """A client that says so on stderr when it waits out a per-minute limit."""
    return WfmClient.from_env(on_wait=lambda message: print(message, file=sys.stderr))


def published(article: dict[str, Any]) -> str:
    """UTC when the API has it; otherwise the publisher's own clock, with its zone."""
    if article.get("published_at_utc"):
        return article["published_at_utc"][:19].replace("T", " ") + " UTC"
    if article.get("published_at"):
        return f"{article['published_at'][:16]} {article.get('published_timezone') or ''}".strip()
    return "undated"


def print_page(result: dict[str, Any]) -> None:
    meta, articles = result["meta"], result["data"]

    if not articles:
        print("No articles matched. Searches cover the last day unless you pass --from/--to.")
    for article in articles:
        source = (article.get("source") or {}).get("name") or "unknown publisher"
        country = (article.get("country") or {}).get("name") or ""
        print(f"• {article['title']}")
        print(f"  {source}, {country} | {published(article)}")
        print(f"  {article['url']}")

    print()
    print(
        f"Page {meta['current_page']} of {meta['total_pages']}, {meta['total_items']} article(s). "
        f"Filters as understood by the API: {meta.get('applied_filters') or {}}"
    )
    if meta.get("has_next"):
        print(f"Next page: add --page {meta['current_page'] + 1}")


def run(main: Callable[[], int]) -> None:
    """Runs a script's main(), turning the client's errors into one clear line and an exit code."""
    try:
        sys.exit(main())
    except WfmConfigError as error:
        sys.exit(f"Configuration: {error}")
    except WfmRateLimitError as error:
        wait = f" It resets in {error.retry_after} s." if error.retry_after else ""
        sys.exit(f"Rate limit: {error}{wait}")
    except WfmValidationError as error:
        details = "; ".join(f"{field}: {' '.join(messages)}" for field, messages in error.errors.items())
        sys.exit(f"The API did not accept the request: {error}" + (f" ({details})" if details else ""))
    except WfmError as error:
        sys.exit(str(error))
