# naver_land

네이버 부동산 매물 데이터를 수집·분석하는 Streamlit 멀티페이지 앱. 국토교통부 실거래가(RTMS) 데이터도 함께 수집해 가격 추이를 비교한다.

실행/배포/아키텍처 상세 가이드는 [`CLAUDE.md`](./CLAUDE.md) 참고.

## 파일 구성

| 파일 | 역할 |
|---|---|
| `app.py` | 진입점 — 폰트/DB 초기화, Google Sheets 자동복원, 네비게이션 설정 |
| `rawdata.py` | 네이버 부동산 raw 텍스트 붙여넣기 → 정규식 파싱 → DB 저장 |
| `db.py` | 모든 SQLite CRUD, Google Sheets 백업/복원 |
| `utils_graph.py` | DB → DataFrame 변환, 일별 집계, 사이드바 필터, 추천 점수 계산 |
| `utils_uid.py` | 매물 고유 uid 생성 (SHA-1) |
| `utils_auth.py` | 비밀번호 인증 (현재 비활성화) |
| `utils_style.py` | 한글 폰트 전역 적용 (Noto Sans KR + Plotly) |
| `setup_fonts.py` | 앱 시작 시 1회 실행되는 폰트 설치 스크립트 |
| `fetch_naver.py` | 네이버 부동산 API 독립 실행형 수집 CLI |
| `fetch_rtms.py` | 국토부 실거래가 독립 실행형 수집 CLI |
| `pages/graph_v2.py` | 단지별 가격 추이 차트 (PC) |
| `pages/graph_mobile.py` | 단지별 가격 추이 차트 (모바일 최적화) |
| `pages/raw_manage.py` | 매물 데이터 배치 삭제/복원 관리 |
| `pages/rtms_fetch.py` | 국토부 실거래가 수집 UI (매매·전월세) |
| `pages/rtms_chart.py` | 국토부 실거래가 가격 추이 차트 (매매·전세) |
| `pages/rtms_area_trend.py` | 국토부 실거래가 기반 구/동 단위 가격동향 비교 |
| `pages/kosis_fetch.py` | KOSIS(국가통계포털) 인구·주택·경제 통계 수집 UI |
| `pages/kosis_trend.py` | KOSIS 통계 기반 인구·세대수/주택 인허가/사업자 현황 트렌드 |
| `pages/naver_fetch.py` | 네이버 부동산 수집 UI |
| `pages/recommend.py` | 가중치 기반 매물 점수 추천 (메뉴 숨김) |
| `pages/visited.py` | 방문 매물 수기 기록 (메뉴 숨김) |
| `pages/view_manage.py` | 동별 조망(뻥뷰) 등급 관리 (메뉴 숨김) |
| `pages/policy_news.py` | 평택 부동산 뉴스 RSS (메뉴 숨김) |
| `pages/loan_info.py` | 보금자리론 월 납입액 계산기 (메뉴 숨김) |
| `pages/notebooklm.py` | 뉴스+매물 요약 → NotebookLM용 (메뉴 숨김) |
| `gas/Code.gs` | Google Apps Script 소스 (참고용 — 실배포본은 스프레드시트 편집기) |
| `.streamlit/config.toml` | Streamlit 서버 설정 |
| `requirements.txt` | Python 의존성 |
| `packages.txt` | apt 시스템 패키지 (`fonts-nanum`) |
| `Procfile` / `railway.toml` | Railway 배포 설정 (현재 미사용, 재활성화 참고용 보관) |

`backup/`, `out/`는 로컬 산출물 디렉토리로 `.gitignore` 대상이며 커밋하지 않는다.
