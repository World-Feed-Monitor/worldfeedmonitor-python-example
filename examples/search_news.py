"""Search the world's news.

python examples/search_news.py --keywords "energy prices" --country DE,FR
python examples/search_news.py --topic politics --country BR --from 2026-11-01 --page 2
"""

from __future__ import annotations

import argparse

from _common import add_filters, client, filters_from, print_page, run


def main() -> int:
    parser = argparse.ArgumentParser(description="Search World Feed Monitor news (25 articles per page).")
    add_filters(parser)
    parser.add_argument("--page", type=int, default=1, help="page number, from 1")
    args = parser.parse_args()

    with client() as wfm:
        print_page(wfm.search(page=args.page, **filters_from(args)))
    return 0


if __name__ == "__main__":
    run(main)
