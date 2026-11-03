# World Feed Monitor · Python example

Search the world's news from Python with the [World Feed Monitor](https://worldfeedmonitor.com) REST API.

World Feed Monitor reads publishers in every country and language, categorises and deduplicates their articles, and serves them through one API. You don't build or maintain any crawling. This repository shows how to use that API from Python: authentication, searching with filters, paging, exporting, and handling errors and rate limits.

**Read [`wfm_client.py`](wfm_client.py) first.** It's the whole integration in one file, about 250 lines with comments. The scripts in [`examples/`](examples) only use it.

This is an example, not an official SDK. Copy the file into your project and change it as you like.

## 1. Create a free account

Sign up at [worldfeedmonitor.com/register](https://worldfeedmonitor.com/register) with an email address, GitHub or Google. No card is needed. **Confirm your email address**: the API answers only after that.

Want to see the data first? The [API Playground](https://worldfeedmonitor.com/playground) runs searches with no account.

## 2. Create API credentials

In the dashboard, open **API Credentials** and create one. You get:

- an **API key**;
- an **API secret**, shown **once**. Copy it straight away. If you lose it, create a new credential.

## 3. Install

Python 3.10 or later.

```bash
git clone https://github.com/World-Feed-Monitor/worldfeedmonitor-python-example.git
cd worldfeedmonitor-python-example
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env    # then put your key and secret in .env
```

`.env` is ignored by git. Variables already set in your shell take precedence over the file.

## 4. Run the examples

```bash
# Search: keywords, countries, topics, dates
python examples/search_news.py --keywords "energy prices" --country DE,FR
python examples/search_news.py --topic politics --country BR --from 2026-11-01 --page 2

# The newest articles from the last day
python examples/latest_news.py
python examples/latest_news.py --country JP --topic technology

# Save a search to CSV or JSON
python examples/export_news.py --keywords semiconductors --country TW --from 2026-10-27 --format csv --output taiwan.csv
python examples/export_news.py --topic environment --pages 3 --format json --output environment.json
```

What `search_news.py` prints (placeholders in angle brackets; real output has the publishers' own headlines):

```text
• <headline, as the publisher wrote it>
  <publisher>, <country> | 2026-11-03 07:41:00 UTC
  <link to the original article>
• …

Page 1 of 12, 297 article(s). Filters as understood by the API: {'keywords': 'energy prices', 'country': ['DEU', 'FRA'], …}
Next page: add --page 2
```

The last line echoes `meta.applied_filters`: how the API understood each filter, after resolving codes (`DE` becomes `DEU`). Check it when a search returns something unexpected.

## Using the client in your code

```python
from wfm_client import WfmClient, WfmRateLimitError

with WfmClient.from_env() as wfm:  # reads WFM_API_KEY / WFM_API_SECRET (or .env)
    page = wfm.search(keywords="climate", country=["BR", "AR"], from_date="2026-10-27")

    for article in page["data"]:
        print(article["published_at_utc"], article["source"]["name"], article["title"], article["url"])

    print(page["meta"]["total_items"], "articles,", page["meta"]["total_pages"], "pages")
```

| Method | Request |
| --- | --- |
| `search(page=1, **filters)` | `GET /v1/feeds/search`: one page of 25 articles |
| `latest(country=, language=, topic=, page=1)` | The same search, newest first (there's no separate "latest" endpoint) |
| `pages(max_pages=N, **filters)` | Page after page of one search, stopping at the last page or after `N` |
| `metadata(name, **params)` | `GET /v1/metadata/{name}`, e.g. `"countries"`, `"languages"`, `"macro-categories"`, `"sources"` |

Authentication is **HTTP Basic**: the API key is the username and the API secret is the password. `httpx` builds the header, and the client never prints it.

## Search filters

| Filter | Example | Notes |
| --- | --- | --- |
| `keywords` | `"energy prices"` | Words in the title or text. Up to two words must all match; for longer queries, three in four. |
| `title` | `"election"` | Words in the title only |
| `country` | `"JP"`, `["DE", "FR"]` | ISO 3166-1 alpha-2 or alpha-3 |
| `language` | `"ja"` | ISO 639-1 |
| `macro_category` | `"politics"` | A topic key, from `metadata("macro-categories")` |
| `source` | `"<publisher key>"` | From `metadata("sources")` |
| `continent`, `continent_region` | | Keys from `metadata("continents")` |
| `source_type`, `sector` | | What the publisher is, and what it covers |
| `publisher_category` | | The publisher's own category keys |
| `has_image` | `True` | Only articles with (or without) an image |
| `from_date`, `to_date` | `"2026-10-27"` | `YYYY-MM-DD`. **Without dates, a search covers the last day.** |
| `sort` | `"desc"` | `relevance` (the default with keywords), `desc` (newest first, the default otherwise) or `asc` |

Lists may be passed as Python lists or comma-separated strings. Values within one filter are alternatives (OR); different filters narrow each other (AND).

The API ignores a filter name it doesn't know, so a typo would quietly widen your search. This client refuses unknown names with a `TypeError` instead.

### What each article contains

`title`, `url` (the original article), `content` (a plain-text summary), `author`, `image`, `source` (`key`, `name`, `url`), `country` (`iso_2`, `iso_3`, `name`), `language` (`code`, `name`), `categories`, `macro_categories`, and three times:

- `published_at`: the publisher's own clock, `YYYY-MM-DD HH:MM:SS`;
- `published_timezone`: that clock's zone;
- `published_at_utc`: the same moment in UTC (ISO 8601). Results are ordered by this.

## Pagination

Results come 25 to a page. `meta` gives `current_page`, `total_pages`, `has_next` and `has_previous`. Pass `page=2`, `page=3`, and so on.

**Plans limit how deep you can page.** On Free, a search reaches its first 100 results (4 pages). `total_items` reports what you can reach, and a later page is refused with a 422. Narrow the search (dates, countries, topics) rather than paging further.

`pages(max_pages=N)` needs an explicit `N`; there's no "fetch everything". `export_news.py` accepts `--pages` from 1 to 10 and keeps what it has already fetched if the plan stops it earlier.

## CSV and JSON export

- **CSV:** one row per article with `published_at_utc`, `published_at`, `published_timezone`, `title`, `source`, `country`, `language`, `topics` and `url`.
- **JSON:** `{"filters": …, "articles": […]}`, with each article exactly as the API returned it.

Exported files are git-ignored (`*.csv`, `*.json`).

## Errors and rate limits

| What happens | Exception | What the client does |
| --- | --- | --- |
| Credentials missing | `WfmConfigError` | Says which variable, and where to get it |
| 401: key or secret not accepted | `WfmAuthError` | Raises |
| 403: account not active, or email not confirmed | `WfmForbiddenError` | Raises with the API's reason |
| 422: unknown filter value, or a page beyond the plan's reach | `WfmValidationError` (`.errors` per field) | Raises |
| 429: per-minute allowance used up | `WfmRateLimitError` | Waits `retry_after` seconds (at most 60) and retries **once**, saying so |
| 429: daily or monthly allowance used up | `WfmRateLimitError` (`.window`, `.retry_after`, `.limit`) | Raises: waiting hours isn't the client's decision |
| 503: API briefly busy | | Waits `Retry-After` (5 s) and retries once |
| Network failure or other server error | `WfmNetworkError` | Raises |

The example scripts turn each of these into one line on stderr and a non-zero exit code.

Successful responses carry no rate-limit headers, so the client can't slow down ahead of a limit. It reacts to the 429, whose `Retry-After`, `X-RateLimit-Limit` and body (`window`, `limit`, `retry_after`) say exactly when to try again.

## Free plan limits

| | Free |
| --- | --- |
| Requests | 30 a minute, 1,000 a day, 10,000 a month |
| Results reachable per search | the first 100 (4 pages) |
| Coverage | every country, language and topic |
| REST API and MCP server | both included |

Every endpoint counts as one request, **metadata included**. If you look up countries or topics often, cache the answers: they change rarely. See your usage in the dashboard. Paid plans raise the request and depth limits; see [pricing](https://worldfeedmonitor.com/#pricing).

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check .
```

The tests use `httpx.MockTransport` with responses in the API's documented shapes, so they need no credentials and no network.

## Links

- [API reference](https://worldfeedmonitor.com/docs) and the [OpenAPI document](https://worldfeedmonitor.com/openapi.json)
- [API Playground](https://worldfeedmonitor.com/playground)
- [MCP server](https://worldfeedmonitor.com/#mcp) for AI agents
- Other examples: [Next.js dashboard](https://github.com/World-Feed-Monitor/worldfeedmonitor-nextjs-example), [MCP research agent](https://github.com/World-Feed-Monitor/worldfeedmonitor-mcp-agent-example)

## License

[MIT](LICENSE)
