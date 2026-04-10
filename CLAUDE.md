# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 언어 지침

모든 응답과 설명은 반드시 **한글**로 작성한다. 코드, 명령어, 파일명 등 기술적 요소는 영어 그대로 사용하되, 설명 텍스트는 항상 한글로 한다.

## Commands

**Run locally:**
```bash
streamlit run app.py
```

**Install dependencies:**
```bash
pip install -r requirements.txt
```

**Deploy (Railway):**
```
python setup_fonts.py && streamlit run app.py --server.port $PORT --server.address 0.0.0.0
```

There are no automated tests or linting configured in this project.

## Architecture

This is a **Streamlit multi-page app** for tracking and analyzing Korean real estate (Naver Land) listings. Data is stored locally in SQLite (`naver_land.db`). On Railway deployment, the DB path is overridden via `DB_PATH` env var.

### Entry point

`app.py` — sets up navigation and handles auto-restore from Google Sheets on cold start (when `AUTO_RESTORE_SHEET` env var is set and the DB is empty).

### Pages (`pages/`)

| File | Purpose |
|---|---|
| `graph_v2.py` | Price trend charts per complex (Plotly) |
| `recommend.py` | Scored listing recommendations with configurable weights |
| `visited.py` | Manual log of visited properties |
| `view_manage.py` | Manage "뻥뷰" (view) grades per dong |
| `raw_manage.py` | Bulk delete/restore, batch management |
| `policy_news.py` | Pyeongtaek real estate news (RSS) |
| `loan_info.py` | 보금자리론 monthly payment calculator |
| `notebooklm.py` | One-click news + listing summary for NotebookLM |

`rawdata.py` (project root, not in `pages/`) is the listing data entry page — it parses raw text pasted from Naver Land using regex.

### Core modules

- **`db.py`** — All SQLite operations. Tables: `listings` (current state), `price_history` (change log), `visited_properties`, `view_scores`, `presets`, `deleted_uids` (blacklist). `upsert_listing_and_history()` is the main write path; deleted UIDs are blacklisted to prevent re-entry.
- **`utils_graph.py`** — Shared logic for `graph_v2` and `recommend`: `build_df()` loads and parses all listings, `make_daily()` builds time series, `compute_score()` / `get_badges()` handle ranking, `render_sidebar()` draws the common filter sidebar.
- **`utils_uid.py`** — `make_uid()` generates a SHA-1 UID from `(complex_name, dong, area, trade_type, direction)` — floor is intentionally excluded so the same unit type groups together.
- **`utils_auth.py`** — Password auth (currently disabled via early `return` in `require_auth()`).
- **`utils_style.py`** — `inject_korean_font()` must be called at the top of every page to fix Korean font rendering on Railway/Linux.

### Data flow

1. User pastes raw Naver Land text → `rawdata.py` parses it with regex into structured rows
2. Each row gets a UID via `make_uid()` and is saved via `db.upsert_listing_and_history()`
3. Price/confirm_date changes automatically append a `price_history` record
4. `build_df()` in `utils_graph.py` joins `listings` + `price_history` into a DataFrame with parsed price (`eok` column, in 억 units) for all chart/recommend pages

### Google Sheets integration

`db.restore_from_sheet()` fetches data from a Google Apps Script endpoint (`GAS_URL` in `db.py`) to restore the DB from a sheet. The sheet name is passed via `AUTO_RESTORE_SHEET` env var at startup.

### Environment variables

| Variable | Purpose |
|---|---|
| `DB_PATH` | SQLite file path (default: `/app/data/naver_land.db`) |
| `AUTO_RESTORE_SHEET` | Google Sheet name to auto-restore from on empty DB |
