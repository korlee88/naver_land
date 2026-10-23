# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 언어 지침

모든 응답과 설명은 반드시 **한글**로 작성한다. 코드, 명령어, 파일명 등 기술적 요소는 영어 그대로 사용하되, 설명 텍스트는 항상 한글로 한다.

---

## 파일 관리 규칙

1. 새 파일보다 기존 파일 수정을 우선한다. 새 파일을 만들었으면 왜 필요했는지 한 줄로 설명한다.
2. 버전 백업 파일(`_v2`, `_old`, `.bak`, `_backup`)을 만들지 않는다. 버전 관리는 git이 한다.
3. 임시·실험 파일은 저장소 밖에 만든다. 저장소 안에 만들었으면 작업 후 삭제한다. 작업을 마칠 때 `git status`가 깨끗해야 한다.
4. 생성물(`__pycache__`, `node_modules`, `.venv`, 빌드 산출물)은 커밋하지 않는다. `.gitignore`에 없는 새 생성물이 보이면 커밋 말고 `.gitignore`에 추가한다.
5. 요청하지 않은 문서 파일(`SUMMARY.md`, `NOTES.md`, `IMPLEMENTATION.md` 등)을 만들지 않는다. 설명은 대화로, 맥락은 주석이나 커밋 메시지에 남긴다.
6. 문서·산출물 이름은 `yymmdd_제목_부제목_vX.Y.확장자` 형식을 쓴다 (예: `260822_설계안_초안_v1.0.md`). 단 소스코드·설정 파일에는 적용하지 않는다 — 실행 대상이 이름으로 고정돼 있어 이름을 바꾸면 조용히 깨진다.
7. `README.md`에 "파일 구성" 표를 두고 각 파일 역할을 한 줄로 적는다. 파일을 추가·삭제·이름변경하면 같은 커밋에서 이 표도 갱신한다. 목록 전용 파일(`INDEX.md`)은 만들지 않는다.
8. 파일을 지우거나 옮기기 전에 다른 파일이 참조하는지 검색해서(import, 워크플로 실행 경로, README 언급) 함께 고친다.
9. 미사용 코드는 주석 처리하지 말고 삭제한다. 기록은 git 히스토리에 남는다.
10. API 키·토큰·계정정보를 코드나 커밋에 넣지 않는다. private 저장소도 히스토리에 영구히 남으므로 동일하게 취급한다.

---

## 저장소 구조

Python(Streamlit) 단일 언어 프로젝트. Node/JS 빌드 체인 없음.

```
naver_land/
├── app.py                   # 진입점 — 폰트/DB 초기화, Sheets 자동복원, 네비게이션
├── db.py                    # SQLite CRUD, Google Sheets 백업/복원 (RTMS·KOSIS·ECOS)
├── utils_area_trend.py      # 실거래 로드/집계/KOSIS 상관분석/차트 빌더 (페이지 공용)
├── utils_market.py          # 파생지표(평당가·연식·층) + 대출/손익분기/시장신호 (순수 함수)
├── utils_analysis.py        # 시장 연동 분석 통계 엔진 (시차상관·베타·전이경로·유사국면)
├── utils_ecos.py            # 한국은행 ECOS Open API 클라이언트
├── utils_style.py           # inject_korean_font() — 한글 폰트 전역 적용
├── setup_fonts.py           # 앱 시작 시 1회 실행되는 폰트 설치 스크립트
├── fetch_rtms.py            # 국토부 실거래가 독립 실행형 수집 CLI (스케줄/대량 백필용)
├── pages/                   # Streamlit 멀티페이지 (app.py의 st.navigation 대상)
│   ├── rtms_chart.py        # 실거래가 가격 추이 (매매·전세·전세가율)
│   ├── rtms_area_trend.py   # 구/동 단위 가격동향 비교 + KOSIS 상관분석 (PC)
│   ├── rtms_area_trend_mobile.py  # 구/동 단위 가격동향 비교 (모바일)
│   ├── simulator.py         # 보유 시나리오 시뮬레이터
│   ├── market_link.py       # 시장 연동 분석
│   ├── rtms_fetch.py        # 국토부 실거래가 수집 UI (매매+전월세)
│   ├── kosis_trend.py       # KOSIS 인구·주택·경제 통계 추이
│   ├── kosis_fetch.py       # KOSIS 통계 수집 UI
│   └── ecos_fetch.py        # 한국은행 ECOS 금리 수집 UI
├── gas/Code.gs               # Google Apps Script 소스 (참고용 — 실배포본은 스프레드시트 편집기)
├── .streamlit/config.toml    # Streamlit 서버 설정
├── requirements.txt / packages.txt   # Python 의존성 / apt 시스템 패키지
└── backup/, out/              # 로컬 산출물 디렉토리 — .gitignore 대상, 커밋 금지
```

모든 페이지가 `app.py`의 `st.navigation()`에 올라가 있다 — 숨김 페이지는 없다.

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

**독립 실행형 수집 CLI (앱 UI와 별개로 실제 운용 중):**
```bash
python fetch_rtms.py --key YOUR_API_KEY --months 24
```
- `pages/rtms_fetch.py`(앱 내 UI)와 기능은 겹치지만, 스케줄 실행이나 대량 백필처럼 UI 없이 돌릴 때 이 CLI를 쓴다.

**배포 (Streamlit Community Cloud — 현재 기본, 무료):**
- https://share.streamlit.io 에서 GitHub 리포(`korlee88/naver_land`) 연결
- Main file: `app.py`
- 시스템 패키지: `packages.txt`에 `fonts-nanum` 명시 → 자동 설치
- Secrets (대시보드 → Settings → Secrets):
  - `DB_PATH` 미설정 시 `/tmp/naver_land.db` 사용 (ephemeral, 재시작마다 초기화)
- `.streamlit/config.toml` — `headless=true`, `enableCORS=false` 설정

테스트 및 린팅 설정 없음.

---

## Architecture

네이버 부동산 매물 데이터를 수집·분석하는 **Streamlit 멀티페이지 앱**.
데이터는 SQLite에 저장되며, Streamlit Community Cloud 환경에서는 `/tmp/naver_land.db`(ephemeral)를 사용하고 Google Sheets 자동 복원으로 보완한다.

### 진입점

**`app.py`** — 폰트 초기화(`setup_fonts.main()`), DB 초기화(`init_db()`), Google Sheets 자동 복원, 네비게이션 설정.

현재 활성화된 메뉴 (9개) — 전부 국토부 실거래가·공공통계 기반이다:
```python
pg = st.navigation([
    st.Page("pages/rtms_chart.py",       title="가격 추이",       icon="📊", default=True),
    st.Page("pages/rtms_area_trend.py",  title="지역별 가격동향", icon="🗺️"),
    st.Page("pages/rtms_area_trend_mobile.py", title="지역별 가격동향(모바일)", icon="📱"),
    st.Page("pages/simulator.py",        title="보유 시뮬레이터", icon="🧮"),
    st.Page("pages/market_link.py",      title="시장 연동 분석", icon="🔗"),
    st.Page("pages/rtms_fetch.py",       title="실거래가 수집",   icon="🏛️"),
    st.Page("pages/kosis_trend.py",      title="인구·주택·경제 통계", icon="📈"),
    st.Page("pages/kosis_fetch.py",      title="KOSIS 통계 수집",     icon="🏢"),
    st.Page("pages/ecos_fetch.py",       title="금리 수집(ECOS)",     icon="🏦"),
], position="hidden")
```

### Pages (`pages/`)

| 파일 | 상태 | 기능 |
|---|---|---|
| `rtms_chart.py` | ✅ 활성 | 국토부 실거래가 단지별 가격 추이 (매매·전세·전세가율) |
| `rtms_area_trend.py` | ✅ 활성 | 구/동 단위 가격동향 비교 + KOSIS 상관분석 (PC) |
| `rtms_area_trend_mobile.py` | ✅ 활성 | 구/동 단위 가격동향 비교 (모바일) |
| `simulator.py` | ✅ 활성 | 보유 시나리오 시뮬레이터 — 대출 상환·손익분기·시장신호·평당가/연식/층 분석 |
| `market_link.py` | ✅ 활성 | 시장 연동 분석 — 시차 교차상관·지역 베타·전이 경로·유사 국면 |
| `rtms_fetch.py` | ✅ 활성 | 국토부 실거래가 수집 (매매·전월세) |
| `kosis_trend.py` | ✅ 활성 | KOSIS 인구·주택·경제 통계 추이 |
| `kosis_fetch.py` | ✅ 활성 | KOSIS 통계 수집 |
| `ecos_fetch.py` | ✅ 활성 | 한국은행 ECOS 금리 수집 (연결 테스트·통계표 검색 포함) |

### Core Modules

| 모듈 | 역할 |
|---|---|
| **`db.py`** | 모든 SQLite CRUD. `upsert_listing_and_history()`가 주요 쓰기 경로 |
| **`utils_style.py`** | `inject_korean_font()` — 모든 페이지 최상단 호출 필수. Noto Sans KR + Plotly 전역 폰트 설정 |
| **`setup_fonts.py`** | 앱 시작 시 1회 실행. `packages.txt`의 `fonts-nanum` 시스템 폰트 우선 사용, 없으면 Google Fonts에서 다운로드 |

### 시장 연동 분석의 통계 원칙 (`utils_analysis.py`)

이 앱의 표본은 짧다(실거래 월별 24~60개, KOSIS 연간 ~16개). 그래서 상관을 다룰 때
아래 세 가지를 반드시 지킨다 — 어기면 숫자가 그럴듯하게 거짓말을 한다.

1. **수준이 아니라 변화율로 잰다.** 추세를 가진 두 계열은 무관해도 상관이 높게 나온다.
   36개월 모의실험에서 무관한 두 상승 계열의 |r|이 0.5를 넘을 확률이 **수준 91% vs 차분 0.3%**.
2. **점추정만 주지 않는다.** 표본수와 신뢰구간을 항상 같이 낸다. n=36이면 진짜 r=0.5여도
   95% 구간이 [0.21, 0.71]이라 '약함'과 '강함'을 구분할 수 없다.
3. **시차 스캔에는 다중비교 보정을 적용한다.** ±12개월을 훑으면 25회 검정이라 가짜 양성이
   쌓인다. 보정 없이는 무관한 계열끼리도 **68%** 확률로 '유의한 시차'가 나왔고,
   Bonferroni 보정 후 **4%** 로 떨어졌다.

회귀 예측 모델은 만들지 않는다 — n=36에 변수 5개면 과적합이 확정적이다.

### DB 스키마 (`db.py`)

| 테이블 | 역할 |
|---|---|
| `rtms_transactions` | 국토부 아파트 매매 실거래 |
| `rtms_jeonse` | 국토부 아파트 전월세 실거래 (`pages/rtms_fetch.py`가 생성) |
| `kosis_stats` | KOSIS 인구·주택 인허가·사업자 통계 (연 단위) |
| `ecos_stats` | 한국은행 ECOS 금리 시계열 |

### 데이터 흐름

```
pages/rtms_fetch.py  ← 국토부 실거래가 API (매매·전월세)
pages/kosis_fetch.py ← KOSIS 인구·주택·경제 통계
pages/ecos_fetch.py  ← 한국은행 ECOS 금리
    → SQLite (rtms_transactions / rtms_jeonse / kosis_stats / ecos_stats)
    → 구글시트 자동 백업 (Apps Script 엔드포인트)
    → 앱 재시작 시 app.py가 자동 복원

utils_area_trend.load_data()  : DB → DataFrame (+ build_year·floor)
utils_market.add_derived()    : 평당가·연식·층·평형 라벨 부착
→ rtms_chart / rtms_area_trend / simulator / market_link 가 소비
```

### Google Sheets 연동

- `push_*_to_sheet()` / `restore_*_from_sheet()` — Apps Script 엔드포인트(`GAS_URL`)로 RTMS·KOSIS·ECOS를 백업/복원
- 백업은 매번 DB 전체 스냅샷 덮어쓰기. 대상 스프레드시트는 `BACKUP_SHEET_ID` 한 곳으로 모은다
- 앱이 콜드 스타트하면 `app.py`가 빈 테이블을 감지해 자동 복원
- 구글시트는 통합문서당 1천만 셀 한도가 있어 `backup_sheet_usage()`로 사용률을 상시 표시한다
- GAS 스크립트 소스는 `gas/Code.gs`에 참고용으로 보관 (실제 배포본은 구글 스프레드시트의 Apps Script 에디터에 있음 — 수정 시 두 곳 모두 갱신)

### 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `DB_PATH` | `/tmp/naver_land.db` | SQLite 파일 경로 |
| `KOSIS_API_KEY` | (없음) | KOSIS Open API 인증키 (kosis.kr/openapi, 자동승인) |
| `ECOS_API_KEY` | (없음) | 한국은행 ECOS Open API 인증키 (ecos.bok.or.kr/api, 자동승인·1일 내 활성화) |
| `RTMS_API_KEY` | (없음) | 국토부 실거래가 일반 인증키. **매매·전월세 공통 1개** (계정 단위 키). Streamlit Secrets에 넣으면 `pages/rtms_fetch.py`가 `st.secrets`→환경변수 순으로 읽어 입력칸에 자동 채움 |

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
