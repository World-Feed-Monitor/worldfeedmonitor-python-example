"""The newest articles from the last day, optionally for one country, language or topic.

python examples/latest_news.py
python examples/latest_news.py --country JP --topic technology
"""

from __future__ import annotations

import argparse

from _common import client, print_page, run


def main() -> int:
    parser = argparse.ArgumentParser(description="The newest World Feed Monitor articles, newest first.")
    parser.add_argument("--country", help="ISO codes, comma-separated: JP or JPN,KOR")
    parser.add_argument("--language", help="ISO 639-1 codes, comma-separated: ja,en")
    parser.add_argument("--topic", help="topic keys, comma-separated: politics,business")
    parser.add_argument("--page", type=int, default=1, help="page number, from 1")
    args = parser.parse_args()

    with client() as wfm:
        print_page(wfm.latest(country=args.country, language=args.language, topic=args.topic, page=args.page))
    return 0


if __name__ == "__main__":
    run(main)
