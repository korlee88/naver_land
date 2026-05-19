# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 언어 지침

모든 응답과 설명은 반드시 **한글**로 작성한다. 코드, 명령어, 파일명 등 기술적 요소는 영어 그대로 사용하되, 설명 텍스트는 항상 한글로 한다.

---

## Commands

**로컬 실행:**
```bash
streamlit run app.py
```

**의존성 설치:**
```bash
pip install -r requirements.txt
```

**배포 (Streamlit Community Cloud — 현재 기본, 무료):**
- https://share.streamlit.io 에서 GitHub 리포(`korlee88/naver_land`) 연결
- Main file: `app.py`
- 시스템 패키지: `packages.txt`에 `fonts-nanum` 명시 → 자동 설치
- Secrets (대시보드 → Settings → Secrets):
  - `AUTO_RESTORE_SHEET = "시트명"` — 콜드 스타트 시 Google Sheets에서 자동 복원
  - `DB_PATH` 미설정 시 `/tmp/naver_land.db` 사용 (ephemeral, 재시작마다 초기화)
- `.streamlit/config.toml` — `headless=true`, `enableCORS=false` 설정

**배포 (Railway — 유료, 현재 미사용):**
```
python setup_fonts.py && streamlit run app.py --server.port $PORT --server.address 0.0.0.0
```
- `Procfile`, `railway.toml` 파일이 레포에 남아 있음 (재활성화 시 참고)

테스트 및 린팅 설정 없음.

---

## Architecture

네이버 부동산 매물 데이터를 수집·분석하는 **Streamlit 멀티페이지 앱**.
데이터는 SQLite에 저장되며, Streamlit Community Cloud 환경에서는 `/tmp/naver_land.db`(ephemeral)를 사용하고 Google Sheets 자동 복원으로 보완한다.

### 진입점

**`app.py`** — 폰트 초기화(`setup_fonts.main()`), DB 초기화(`init_db()`), Google Sheets 자동 복원, 네비게이션 설정.

현재 활성화된 메뉴 (4개):
```python
pg = st.navigation([
    st.Page("pages/graph_v2.py",     title="가격 추이 차트",  icon="📊", default=True),
    st.Page("pages/graph_mobile.py", title="추이 (모바일)",   icon="📱"),
    st.Page("rawdata.py",            title="매물 입력",       icon="📝"),
    st.Page("pages/raw_manage.py",   title="RAW 관리",        icon="🧹"),
], position="hidden")
```

### Pages (`pages/`)

| 파일 | 상태 | 기능 |
|---|---|---|
| `graph_v2.py` | ✅ 활성 | 단지별 가격 추이 차트 (PC) |
| `graph_mobile.py` | ✅ 활성 | 단지별 가격 추이 차트 (모바일 최적화) |
| `raw_manage.py` | ✅ 활성 | 배치 삭제/복원, 데이터 관리 |
| `recommend.py` | 💤 메뉴 숨김 | 가중치 기반 매물 점수 추천 |
| `visited.py` | 💤 메뉴 숨김 | 방문 매물 수기 기록 |
| `view_manage.py` | 💤 메뉴 숨김 | 동별 조망(뻥뷰) 등급 관리 |
| `policy_news.py` | 💤 메뉴 숨김 | 평택 부동산 뉴스 RSS |
| `loan_info.py` | 💤 메뉴 숨김 | 보금자리론 월 납입액 계산기 |
| `notebooklm.py` | 💤 메뉴 숨김 | 뉴스+매물 요약 → NotebookLM용 |

`rawdata.py` (루트, pages/ 아님) — 네이버 부동산 raw 텍스트 붙여넣기 → 정규식 파싱 → DB 저장.

숨겨진 페이지들은 파일이 존재하므로 `app.py`의 `st.navigation()`에 추가하면 즉시 재활성화 가능.

### graph_v2.py 차트 구성

- **2열 레이아웃** — `COLS_PER_ROW = 2`, 중상층(11층 이상) 기준 트렌드
- **Y축 자동 계산** — 데이터 최댓값+0.2억 / 최솟값-0.2억으로 초기화; 단지 변경 시 리셋
- **컨트롤 1행 배치** — Y 최솟값·최댓값 입력 + 기간 버튼(1주~2달)을 한 행으로 압축
- **차트 트레이스** (`make_subplots(secondary_y=True)` 사용):
  - 최고~최저 범위 밴드 (연파랑 채우기, `fill="tonexty"`)
  - 최고가 선 (연빨강), 평균가 점선 (회색), 최저가 선 (파랑, 굵게)
  - 추세(7일) 점선 (보라) — 최저가 7일 이동평균 (`min_7avg`)
  - 급락 마커 (빨간 역삼각형, `is_drop` 기준)
  - 매물 수량 막대 (보조 Y축 오른쪽, 회색 반투명)
- **고정 범위** — `fixedrange=True` (드래그/줌 비활성화, 호버만 허용)
- **기본 단지 선택** — 4개

### graph_mobile.py 차트 구성

- graph_v2.py와 동일한 트레이스 구성 (7일 추세선 제외)
- 높이 280px, `st.slider`로 Y축 범위 조절, `st.radio(horizontal=True)`로 기간 선택
- 모든 축 `fixedrange=True`

### Core Modules

| 모듈 | 역할 |
|---|---|
| **`db.py`** | 모든 SQLite CRUD. `upsert_listing_and_history()`가 주요 쓰기 경로 |
| **`utils_graph.py`** | `build_df()` (DB → DataFrame), `make_daily()` (일별 집계), `render_sidebar()` (공통 필터), `compute_score()` / `get_badges()` (추천 점수) |
| **`utils_uid.py`** | `make_uid()` — SHA-1(단지명, 동, 평형, 거래유형, 방향). 층은 제외 |
| **`utils_auth.py`** | 비밀번호 인증 (현재 `require_auth()` 첫 줄 `return`으로 비활성화) |
| **`utils_style.py`** | `inject_korean_font()` — 모든 페이지 최상단 호출 필수. Noto Sans KR + Plotly 전역 폰트 설정 |
| **`setup_fonts.py`** | 앱 시작 시 1회 실행. `packages.txt`의 `fonts-nanum` 시스템 폰트 우선 사용, 없으면 Google Fonts에서 다운로드 |

### DB 스키마 (`db.py`)

| 테이블 | 역할 |
|---|---|
| `listings` | 매물 최신 상태 (uid PRIMARY KEY) |
| `price_history` | 가격/확인일 변동 이력 (listings 삭제 시 CASCADE) |
| `deleted_uids` | 삭제된 uid 블랙리스트 (재입력 차단) |
| `visited_properties` | 방문 매물 수기 기록 |
| `view_scores` | 동별 조망 등급 (S/A/B/C, 층수 조건) |
| `presets` | 추천 페이지 가중치 프리셋 (슬롯 0~2) |

### `make_daily()` 반환 컬럼

```python
d2 = make_daily(dfc, drop_th=0.1)
# uploadday, min_eok, max_eok, avg_eok, n, min_7avg, is_drop
```

- `n` — 실제 데이터가 있는 날의 매물 건수 (forward-fill 된 날은 0)
- `min_7avg` — `.rolling(7, min_periods=3).mean().shift(1)` (전일 기준 7일 평균, 급락 감지용)
- `is_drop` — `(min_eok - min_7avg) <= -drop_th`

### 데이터 흐름

```
rawdata.py  ← 사용자 raw 텍스트 붙여넣기
    → 정규식 파싱 (단지명·동·평형·층·방향·가격·확인매물·메모)
    → make_uid() → SHA-1 uid 생성
    → db.upsert_listing_and_history()
        → listings INSERT/UPDATE
        → 가격·확인일 변경 시 price_history 추가

graph_v2.py / graph_mobile.py
    → build_df() : listings JOIN price_history → eok(억) 파싱
    → make_daily() : uploadday 기준 일별 집계
    → Plotly 차트 렌더링 (make_subplots, secondary_y)
```

### Google Sheets 연동

- `db.restore_from_sheet(sheet_name)` — Google Apps Script 엔드포인트(`GAS_URL`)로 GET 요청 → 시트 데이터를 DB에 복원
- 복원 시 원본 `seen_at`(날짜) 보존하여 히스토리 유지
- `AUTO_RESTORE_SHEET` 환경변수가 있고 DB가 비어있을 때 `app.py`에서 자동 호출

### 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `DB_PATH` | `/tmp/naver_land.db` | SQLite 파일 경로 |
| `AUTO_RESTORE_SHEET` | (없음) | 콜드 스타트 시 복원할 Google Sheets 시트명 |

### git push 주의사항

로컬 프록시(`http://127.0.0.1:포트`)를 통한 `git push`가 HTTP 403으로 실패할 수 있음.
이 경우 `mcp__github__push_files` 도구로 GitHub API 직접 푸시 후, `git fetch && git reset --hard origin/main`으로 로컬 동기화.

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
