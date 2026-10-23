# naver_land

네이버 부동산 매물 데이터를 수집·분석하는 Streamlit 멀티페이지 앱. 국토교통부 실거래가(RTMS) 데이터도 함께 수집해 가격 추이를 비교한다.

실행/배포/아키텍처 상세 가이드는 [`CLAUDE.md`](./CLAUDE.md) 참고.

## 파일 구성

| 파일 | 역할 |
|---|---|
| `app.py` | 진입점 — 폰트/DB 초기화, Google Sheets 자동복원, 네비게이션 설정 |
| `db.py` | 모든 SQLite CRUD, Google Sheets 백업/복원 |
| `utils_area_trend.py` | 실거래 데이터 로드/집계/KOSIS 상관분석/차트 빌더 — 가격 추이·가격동향·시뮬레이터 페이지 공용 |
| `utils_analysis.py` | 시장 연동 분석 통계 엔진 — 시차 교차상관(다중비교 보정), 지역 베타, 전이 경로, 유사 국면 |
| `utils_ecos.py` | 한국은행 ECOS Open API 클라이언트 (URL 조립·응답 해석·레코드 변환) |
| `utils_market.py` | 파생지표(평당가·연식·층)와 대출 상환·손익분기·시장신호 계산 — Streamlit/DB에 의존하지 않는 순수 함수 |
| `utils_style.py` | 한글 폰트 전역 적용 (Noto Sans KR + Plotly) |
| `setup_fonts.py` | 앱 시작 시 1회 실행되는 폰트 설치 스크립트 |
| `fetch_rtms.py` | 국토부 실거래가 독립 실행형 수집 CLI |
| `pages/rtms_fetch.py` | 국토부 실거래가 수집 UI (매매·전월세) |
| `pages/rtms_chart.py` | 국토부 실거래가 가격 추이 차트 (매매·전세) |
| `pages/rtms_area_trend.py` | 국토부 실거래가 기반 구/동 단위 가격동향 비교 (PC) |
| `pages/rtms_area_trend_mobile.py` | 구/동 단위 가격동향 비교 (모바일 최적화) |
| `pages/simulator.py` | 보유 시나리오 시뮬레이터 — 대출 상환, 가격 시나리오별 손익, 시장 신호, 평당가·연식·층 분석 |
| `pages/market_link.py` | 시장 연동 분석 — 선행지표 탐색, 지역 베타, 전이 경로, 유사 국면 |
| `pages/ecos_fetch.py` | 한국은행 ECOS 금리 수집 UI (연결 테스트·통계표 검색 포함) |
| `pages/kosis_fetch.py` | KOSIS(국가통계포털) 인구·주택·경제 통계 수집 UI |
| `pages/kosis_trend.py` | KOSIS 통계 기반 인구·세대수/주택 인허가/사업자 현황 트렌드 |
| `gas/Code.gs` | Google Apps Script 소스 (참고용 — 실배포본은 스프레드시트 편집기) |
| `.streamlit/config.toml` | Streamlit 서버 설정 |
| `requirements.txt` | Python 의존성 |
| `packages.txt` | apt 시스템 패키지 (`fonts-nanum`) |

`backup/`, `out/`는 로컬 산출물 디렉토리로 `.gitignore` 대상이며 커밋하지 않는다.
