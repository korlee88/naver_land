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

**Deploy (Streamlit Community Cloud — 무료):**
- https://share.streamlit.io 에서 GitHub 리포 연결
- Main file: `app.py` (시작 명령 자동 처리, 별도 설정 불필요)
- 시스템 패키지: `packages.txt` 자동 인식 (fonts-nanum 설치)
- Secrets: 대시보드 → Settings → Secrets에 환경변수 입력
  - `AUTO_RESTORE_SHEET = "시트명"` (재시작 시 Google Sheets에서 자동복원)
  - `DB_PATH` 미설정 시 `/tmp/naver_land.db` 사용 (ephemeral)

**Deploy (Railway — 유료):**
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
- **`utils_style.py`** — `inject_korean_font()` must be called at the top of every page to fix Korean font rendering on Linux/cloud.

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
| `DB_PATH` | SQLite file path (default: `/tmp/naver_land.db`) |
| `AUTO_RESTORE_SHEET` | Google Sheet name to auto-restore from on empty DB |

---

## 사용자 컨텍스트 (자산 현황 · 단지 관리 전략)

### 부동산 자산 현황 (2026-05-19 기준)

**매수 완료**

| 항목 | 내용 |
|---|---|
| 단지 | 평택센트럴자이 2단지 |
| 동·호수 | 203동 2104호 |
| 매매가 | 3억 2천만원 |
| 목적 | 실거주 |

**대출 승인 현황**

| 항목 | 내용 |
|---|---|
| 상품 | 아낌e 보금자리론 (담보한정형, 한국주택금융공사) |
| 대출금액 | 1억원 |
| 금리 | 연 4.75% (고정) |
| 만기 | 40년 |
| 거치기간 | 없음 |
| 상환방식 | 원리금체증식 |
| 자기자금 | 약 2억 2천만원 |

체증식 월납입금 근사치 (HF 체증식 기준):

| 시기 | 월납입금 (추정) |
|---|---|
| 초기 1~5년 | 약 330,000~345,000원 |
| 중기 15~25년 | 약 460,000~510,000원 |
| 후기 35~40년 | 약 620,000~650,000원 |

> 균등상환 시: 약 465,000원/월 (P=1억, r=4.75%/12, n=480개월)  
> 정확한 체증 스케줄: HF 스마트주택금융앱 → 대출 신청내역 → 상환일정

---

### 단지 관리 전략

**앱 활용 목적**: 장기 시세 모니터링 — 실거주 단지 주변 아파트 가격 추세를 장기적으로 추적

**단지 분류**

| 분류 | 단지명 | 비고 |
|---|---|---|
| 🏠 실거주 (매수 완료) | 평택센트럴자이 2단지 | 203동 2104호, 3.2억 |
| 📊 주변 시세 모니터링 | 평택센트럴자이 1단지 | 동일 브랜드 가격 비교 |
| 📊 주변 시세 모니터링 | 평택센트럴자이 3단지 | 동일 브랜드 가격 비교 |
| 📊 주변 시세 모니터링 | 평택센트럴자이 4단지 | 동일 브랜드 가격 비교 |
| 📊 주변 시세 모니터링 | 평택센트럴자이 5단지 | 동일 브랜드 가격 비교 |
| 📊 주변 시세 모니터링 | 더샵지제역센트럴파크(1BL) | 지제역 인근 |
| 📊 주변 시세 모니터링 | 더샵지제역센트럴파크(2BL) | 지제역 인근 |
| 📊 주변 시세 모니터링 | 더샵지제역센트럴파크(3BL) | 지제역 인근 |
| 📊 주변 시세 모니터링 | e편한세상지제역 | |
| 📊 주변 시세 모니터링 | e편한세상평택용이2단지 | |
| 📊 주변 시세 모니터링 | 안성공도우미린더퍼스트 | |
| 📊 주변 시세 모니터링 | 평택지제역동문굿모닝힐맘시티1단지 | |
| 📊 주변 시세 모니터링 | 평택지제역동문굿모닝힐맘시티2단지 | |
| 📊 주변 시세 모니터링 | 평택지제역동문굿모닝힐맘시티3단지 | |
| 📊 주변 시세 모니터링 | 평택지제역동문굿모닝힐맘시티4단지 | |
| 📊 주변 시세 모니터링 | 평택지제역동문디이스트4단지 | |
| 🔍 관련 지역 모니터링 | (청주·오송 지역 단지) | 사용자 관련 지역, 향후 추가 예정 |
