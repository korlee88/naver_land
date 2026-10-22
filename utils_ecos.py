# utils_ecos.py — 한국은행 경제통계시스템(ECOS) Open API 클라이언트
#
# 금리는 부동산 가격을 움직이는 가장 큰 외부 변수인데 이 앱은 지금까지 전혀 보지
# 않았다. ECOS는 무료·자동승인 인증키로 전국 단일 시계열을 주므로, KOSIS처럼
# 지역명을 맞추는 문제도 없다.
#
# 네트워크 호출(fetch_*)과 응답 해석(parse_rows)을 분리해 둔 이유: 개발 환경에서
# ecos.bok.or.kr에 접근할 수 없어 파싱 로직만이라도 모의 응답으로 검증해야 했다.
#
# API 명세: https://ecos.bok.or.kr/api/  (요청 형식은 경로 파라미터 방식)
#   /api/{서비스명}/{인증키}/{요청유형}/{언어}/{시작건수}/{종료건수}/{서비스별 추가 인자...}
import requests

BASE = "https://ecos.bok.or.kr/api"

# 부동산 분석에 쓸 만한 통계표 프리셋.
# ⚠️ 통계표코드는 한국은행이 개편하면 바뀔 수 있어 이 목록을 정답으로 보지 말 것 —
#    페이지의 "통계표 검색"으로 현재 코드를 확인한 뒤 쓰도록 만들어 뒀다.
RATE_PRESETS = {
    "한국은행 기준금리 및 여수신금리 (월)": {"stat_code": "721Y001", "cycle": "M"},
    "시장금리 (월)":                      {"stat_code": "817Y002", "cycle": "M"},
    "예금은행 가중평균 대출금리 (월)":      {"stat_code": "121Y006", "cycle": "M"},
}


class EcosError(RuntimeError):
    """ECOS가 RESULT 블록으로 돌려준 오류 (인증키 오류, 데이터 없음 등)."""


def build_url(service: str, api_key: str, *args, start: int = 1, end: int = 100) -> str:
    """ECOS 요청 URL. 경로 파라미터 방식이라 순서가 곧 의미다."""
    parts = [BASE, service, api_key, "json", "kr", str(start), str(end)]
    parts += [str(a) for a in args if a not in (None, "")]
    return "/".join(parts)


def parse_rows(data: dict, service: str) -> list[dict]:
    """ECOS 응답에서 행 목록을 꺼낸다.

    성공: {"<서비스명>": {"list_total_count": N, "row": [...]}}
    실패: {"RESULT": {"CODE": "INFO-100", "MESSAGE": "..."}}
          — HTTP 200으로 오기 때문에 상태코드만 보면 실패를 못 걸러낸다
            (이 앱이 Apps Script 백업에서 이미 겪은 것과 같은 함정).
    서비스명 블록 안에 RESULT가 들어오는 변형도 있어 양쪽 다 확인한다.
    """
    if not isinstance(data, dict):
        raise EcosError(f"예상치 못한 응답 형식: {str(data)[:200]}")

    result = data.get("RESULT")
    if isinstance(result, dict):
        raise EcosError(f"[{result.get('CODE', '?')}] {result.get('MESSAGE', '알 수 없는 오류')}")

    block = data.get(service)
    if block is None:
        raise EcosError(f"응답에 '{service}' 블록이 없습니다: {str(data)[:200]}")

    if isinstance(block, dict):
        inner = block.get("RESULT")
        if isinstance(inner, dict):
            raise EcosError(f"[{inner.get('CODE', '?')}] {inner.get('MESSAGE', '알 수 없는 오류')}")
        rows = block.get("row", [])
    else:
        rows = block

    return rows if isinstance(rows, list) else []


def _get(service: str, api_key: str, *args, start: int = 1, end: int = 100,
         timeout: int = 30) -> list[dict]:
    url = build_url(service, api_key, *args, start=start, end=end)
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    try:
        data = resp.json()
    except ValueError:
        raise EcosError(f"JSON이 아닌 응답: {resp.text[:200]}")
    return parse_rows(data, service)


def fetch_key_statistics(api_key: str) -> list[dict]:
    """100대 통계지표 — 인증키만 있으면 되는 가장 단순한 호출.

    파라미터가 없어 실패하면 원인이 '인증키' 하나로 좁혀지므로 연결 테스트에 쓴다.
    한국은행 기준금리도 이 목록에 들어 있어 최신값을 바로 확인할 수 있다.
    """
    return _get("KeyStatisticList", api_key, start=1, end=100)


def search_tables(api_key: str, keyword: str = "", limit: int = 200) -> list[dict]:
    """통계표 목록에서 이름으로 검색. 통계표코드가 개편돼도 사용자가 직접 찾게 하려는 용도."""
    rows = _get("StatisticTableList", api_key, start=1, end=limit)
    if not keyword:
        return rows
    kw = keyword.strip()
    return [r for r in rows if kw in str(r.get("STAT_NAME", ""))]


def fetch_items(api_key: str, stat_code: str, limit: int = 200) -> list[dict]:
    """통계표의 세부항목(통계항목코드) 목록 — 어떤 항목을 받을지 고르기 위해."""
    return _get("StatisticItemList", api_key, stat_code, start=1, end=limit)


def fetch_series(api_key: str, stat_code: str, cycle: str, start_period: str,
                 end_period: str, item_code: str | None = None,
                 limit: int = 10000) -> list[dict]:
    """통계 시계열 조회.

    cycle: 년 A / 반년 S / 분기 Q / 월 M / 반월 SM / 일 D
    start_period·end_period는 주기에 맞춘 형식 (연 2015, 월 201501, 일 20150101).
    """
    return _get("StatisticSearch", api_key, stat_code, cycle, start_period, end_period,
                item_code, start=1, end=limit)


def rows_to_records(rows: list[dict], stat_code: str) -> list[tuple]:
    """ECOS 행 → ecos_stats 테이블 입력 튜플.

    값이 비었거나(DATA_VALUE 공란) 숫자가 아닌 행은 버린다 — ECOS는 미공표 시점을
    빈 문자열로 돌려주는데 그대로 넣으면 평균·추세가 망가진다.
    """
    out = []
    for r in rows:
        try:
            raw = r.get("DATA_VALUE")
            if raw in (None, "", "-"):
                continue
            value = float(raw)
        except (TypeError, ValueError):
            continue
        time = str(r.get("TIME") or "").strip()
        if not time:
            continue
        # 항목명은 1~4단계로 나뉘어 오므로 채워진 것만 이어 붙인다
        names = [str(r.get(f"ITEM_NAME{i}") or "").strip() for i in (1, 2, 3, 4)]
        item_name = " / ".join(n for n in names if n and n.lower() != "nan")
        out.append((
            str(r.get("STAT_CODE") or stat_code),
            str(r.get("STAT_NAME") or "").strip(),
            item_name,
            str(r.get("UNIT_NAME") or "").strip(),
            time,
            value,
        ))
    return out


def period_to_date(time: str, cycle: str) -> str | None:
    """ECOS 시점 문자열을 'YYYY-MM-DD'로. 차트 x축에 쓰려면 날짜여야 한다."""
    t = str(time).strip()
    if not t.isdigit():
        # 분기(2015Q1)·반기(2015S1) 같은 형식
        if len(t) == 6 and t[4] in ("Q", "S"):
            year, n = t[:4], int(t[5])
            month = {"Q": {1: 1, 2: 4, 3: 7, 4: 10}, "S": {1: 1, 2: 7}}[t[4]].get(n)
            return f"{year}-{month:02d}-01" if month else None
        return None
    if len(t) == 4:
        return f"{t}-01-01"
    if len(t) == 6:
        return f"{t[:4]}-{t[4:6]}-01"
    if len(t) == 8:
        return f"{t[:4]}-{t[4:6]}-{t[6:8]}"
    return None
