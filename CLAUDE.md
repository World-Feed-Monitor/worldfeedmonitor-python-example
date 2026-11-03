# CLAUDE.md

A small, public Python example of the World Feed Monitor (WFM) REST API. Educational, not an SDK: one readable
client file (`wfm_client.py`) and three scripts in `examples/`. Keep it small.

## Verified API behaviour

Taken from the WFM server code and `openapi.json`, 2026-11-03. Don't add endpoints, parameters or fields that
aren't here; if the API changes, update this section first.

- Base URL `https://api.worldfeedmonitor.com/v1` (the legacy `/api` prefix is off). HTTP Basic auth on every
  endpoint: username = API key, password = API secret.
- `GET /feeds/search`. Filters: keywords, title, country (ISO-2/3), language (ISO 639-1), macro_category (alias
  `category`), publisher_category, continent, continent_region, source, source_type, sector, has_image, from_date,
  to_date (YYYY-MM-DD), sort (relevance|desc|asc), page. Lists: repeat the parameter or comma-separate.
  No dates = the last day. Default sort: relevance with keywords/title, else desc.
- **Unknown parameter names are silently ignored** by the API; `meta.applied_filters` shows what was understood.
  The client refuses unknown names (`TypeError`).
- There is no "latest" REST endpoint: latest = search with `sort=desc` (MCP's get_latest_news does the same).
- Response `{meta, data}`. meta: timeout, total_pages, items_per_page (25), total_items (capped at the plan's
  depth), current_page, has_previous, has_next, applied_filters. Article: uuid, source{uuid,key,name,url,type,sector},
  country{uuid,iso_2,iso_3,name}, continent, continent_region, language{uuid,name,local_name,code,locale}, title,
  author, content, url, categories, macro_categories, image, published_at (publisher's local clock),
  published_timezone, published_at_utc (ISO 8601 UTC; results are ordered by it; may be null on older documents).
- Metadata: /metadata/countries, languages, macro-categories, categories, continents, sources (paginated),
  source-types, sectors, and per-item / nested variants (e.g. /metadata/countries/{code}/sources). Also /stats.
- Metering: **every** endpoint counts, metadata included. Free: 30/min, 1,000/day, 10,000/month, first 100 results
  per search (page 5 → 422). All countries on every plan.
- Errors: 401 `{message}`; 403 `{message, status?}` (inactive account, or "Email address not confirmed. …");
  422 `{message, errors{field: [..]}}` (unknown filter value, or page beyond the plan's depth);
  429 `{message, window: minute|day|month, limit, retry_after}` + headers Retry-After, X-RateLimit-Limit,
  X-RateLimit-Remaining: 0; 503 `{message}` + Retry-After: 5 when briefly busy.
  No rate-limit headers on successful responses.

## Conventions

- Dependencies: `httpx` only (+ pytest, ruff for development). Standard library for .env, CSV, JSON, CLI.
- Retry policy: once, only for a per-minute 429 with retry_after ≤ 60 s and for 503. Never retry day/month limits.
  No unlimited pagination: `pages()` needs `max_pages`; `export_news.py --pages` is capped at 10.
- Never print or log credentials or the Authorization header; keep `WfmClient.__repr__` free of them.
- README sample output uses placeholders, never invented headlines.
- Tests: pytest + `httpx.MockTransport` (`tests/fake_api.py`), no network or credentials. Run `pytest` and
  `ruff check . && ruff format --check .`.
- Out of scope: web UI, database, background workers, MCP, AI, a full SDK, bulk downloading.
- Commits: no AI attribution trailers or footers.
