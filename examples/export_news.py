"""Save a search to CSV or JSON.

    python examples/export_news.py --keywords semiconductors --country TW --from 2026-10-27 \
        --format csv --output taiwan.csv
    python examples/export_news.py --topic environment --pages 3 --format json --output environment.json

Every page is one request against your plan, so the number of pages is yours to
choose and capped: this is for a report, not for copying the index.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from typing import Any, TextIO

from _common import add_filters, client, filters_from, published, run

from wfm_client import WfmValidationError

MAX_PAGES = 10  # 250 articles. Free reaches the first 100 (4 pages); the API refuses deeper pages.

CSV_COLUMNS = [
    "published_at_utc",
    "published_at",
    "published_timezone",
    "title",
    "publisher",
    "country",
    "language",
    "topics",
    "url",
]


def write_csv(articles: list[dict[str, Any]], out: TextIO) -> None:
    writer = csv.DictWriter(out, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for article in articles:
        writer.writerow(
            {
                "published_at_utc": article.get("published_at_utc"),
                "published_at": article.get("published_at"),
                "published_timezone": article.get("published_timezone"),
                "title": article.get("title"),
                "publisher": (article.get("publisher") or {}).get("name"),
                "country": (article.get("country") or {}).get("iso_2"),
                "language": (article.get("language") or {}).get("code"),
                "topics": "; ".join(t.get("name", "") for t in article.get("topics") or []),
                "url": article.get("url"),
            }
        )


def write_json(articles: list[dict[str, Any]], filters: dict[str, Any], out: TextIO) -> None:
    """The articles exactly as the API returned them, with the filters that produced them."""
    json.dump({"filters": filters, "articles": articles}, out, ensure_ascii=False, indent=2)
    out.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a World Feed Monitor search to CSV or JSON.")
    add_filters(parser)
    parser.add_argument("--format", choices=["csv", "json"], default="csv")
    parser.add_argument("--output", required=True, help="file to write")
    parser.add_argument(
        "--pages",
        type=int,
        default=1,
        choices=range(1, MAX_PAGES + 1),
        metavar=f"1-{MAX_PAGES}",
        help="pages of 25 to fetch (default 1); each page is one request",
    )
    args = parser.parse_args()
    filters = {name: value for name, value in filters_from(args).items() if value}

    articles: list[dict[str, Any]] = []
    with client() as wfm:
        try:
            for page in wfm.pages(max_pages=args.pages, **filters):
                articles.extend(page["data"])
        except WfmValidationError as error:
            if not articles:
                raise
            # A page beyond what the plan reaches: keep what was already fetched.
            print(f"Stopped early: {error}", file=sys.stderr)

    with open(args.output, "w", encoding="utf-8", newline="") as out:
        if args.format == "csv":
            write_csv(articles, out)
        else:
            write_json(articles, filters, out)

    newest = published(articles[0]) if articles else "none"
    print(f"Wrote {len(articles)} article(s) to {args.output} (first: {newest}).")
    return 0


if __name__ == "__main__":
    run(main)
