"""
pages/kosis_fetch.py — KOSIS(국가통계포털) 통계 자동 수집

인구·세대수 / 주택 인허가실적 / 가동사업자 현황(시군구) 3개 통계표를 수집한다.
각 통계표는 국토부 실거래가 API와 달리 지역(objL1=ALL)·연도 범위를 한 번의
요청으로 모두 받아올 수 있어 월별 반복 호출이 필요 없다.

통계표는 KOSIS(kosis.kr) 사이트에서 검색 → 통계표 상세 화면의 "Open API" 버튼으로
생성한 URL에서 orgId/tblId/itmId/objL1/objL2 값을 그대로 가져온 것.
"""
import os
import sqlite3
import time
from datetime import date, datetime

import requests
import streamlit as st

from utils_style import inject_korean_font

inject_korean_font()

DB_PATH = os.environ.get("DB_PATH", "/tmp/naver_land.db")
KOSIS_URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"

# KOSIS 사이트에서 "Open API" 버튼으로 생성한 파라미터 그대로.
# objL1/objL2 = ALL → 하위 지역(시군구) 전체를 한 번에 받아옴.
CATEGORIES: dict[str, dict] = {
    "population": {
        "label":  "인구·세대수",
        "org_id": "210", "tbl_id": "DT_21002B002", "itm_id": "T001_001",
        "obj_l1": "ALL", "obj_l2": "ALL",
    },
    "housing": {
        "label":  "주택 인허가실적",
        "org_id": "101", "tbl_id": "DT_1YL7501E", "itm_id": "13103871094T1",
        "obj_l1": "ALL", "obj_l2": "",
    },
    "business": {
        "label":  "가동사업자 현황(시군구)",
        "org_id": "133", "tbl_id": "DT_133N_A9811", "itm_id": "T01",
        "obj_l1": "ALL", "obj_l2": "ALL",
    },
}

_KEY_SS = "kosis_api_key"

REGION_HINT_CHARS = ("시", "군", "구", "도")


def _init_table():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kosis_stats (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            category    TEXT    NOT NULL,
            tbl_id      TEXT    NOT NULL,
            region_name TEXT    NOT NULL,
            sub_label   TEXT,
            item_name   TEXT,
            unit_name   TEXT,
            prd_de      TEXT    NOT NULL,
            value       REAL,
            fetched_at  TEXT    NOT NULL,
            UNIQUE(category, tbl_id, region_name, sub_label, item_name, prd_de)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_kosis_cat_region
        ON kosis_stats(category, region_name, prd_de)
    """)
    conn.commit()
    conn.close()


def _saved_api_key() -> tuple[str, str]:
    if st.session_state.get(_KEY_SS):
        return st.session_state[_KEY_SS], "세션 입력"
    try:
        if "KOSIS_API_KEY" in st.secrets:
            return str(st.secrets["KOSIS_API_KEY"]), "Streamlit Secrets (영구 저장)"
    except Exception:
        pass
    env_key = os.environ.get("KOSIS_API_KEY", "")
    if env_key:
        return env_key, "환경변수"
    return "", ""


def _fetch_kosis(cfg: dict, api_key: str, start_yr: int, end_yr: int, retries: int = 2) -> dict:
    """반환: {"error": str, "rows": list[dict]}. rows는 KOSIS 원본 JSON 그대로."""
    params = {
        "method":       "getList",
        "apiKey":       api_key,
        "itmId":        cfg["itm_id"],
        "objL1":        cfg["obj_l1"],
        "objL2":        cfg["obj_l2"],
        "objL3": "", "objL4": "", "objL5": "", "objL6": "", "objL7": "", "objL8": "",
        "format":       "json",
        "jsonVD":       "Y",
        "prdSe":        "Y",
        "startPrdDe":   str(start_yr),
        "endPrdDe":     str(end_yr),
        "outputFields": "TBL_NM NM ITM_NM UNIT_NM ",
        "orgId":        cfg["org_id"],
        "tblId":        cfg["tbl_id"],
    }
    for attempt in range(retries + 1):
        try:
            resp = requests.get(KOSIS_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                # KOSIS는 오류 시 리스트 대신 {"err": "...", "errMsg": "..."} 형태를 반환
                err = data.get("err") or data.get("Err")
                msg = data.get("errMsg") or data.get("ErrMsg") or "알 수 없는 오류"
                return {"error": f"[{err}] {msg}" if err else str(data)[:200], "rows": []}
            if not isinstance(data, list):
                return {"error": f"예상치 못한 응답 형식: {str(data)[:200]}", "rows": []}
            return {"error": "", "rows": data}
        except Exception as e:
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            return {"error": str(e), "rows": []}


def _extract_region_and_sub(row: dict) -> tuple[str, str]:
    """C1_NM/C2_NM 중 지역명처럼 보이는 쪽을 지역으로, 나머지를 세부분류로 사용.
    (어느 분류축이 지역인지 응답을 직접 못 받아봐서 확정할 수 없어 휴리스틱으로 판단)"""
    c1 = (row.get("C1_NM") or "").strip()
    c2 = (row.get("C2_NM") or "").strip()

    def looks_region(s: str) -> bool:
        return bool(s) and any(ch in s for ch in REGION_HINT_CHARS)

    if looks_region(c1):
        return c1, c2
    if looks_region(c2):
        return c2, c1
    return (c1 or c2 or "(미상)"), ""


def _save_rows(category: str, tbl_id: str, rows: list[dict]) -> int:
    fetched_at = datetime.now().isoformat(timespec="seconds")
    out = []
    for r in rows:
        region_name, sub_label = _extract_region_and_sub(r)
        prd_de = (r.get("PRD_DE") or "").strip()
        dt_raw = r.get("DT")
        try:
            value = float(dt_raw) if dt_raw not in (None, "", "-") else None
        except (TypeError, ValueError):
            value = None
        if not prd_de or value is None:
            continue
        out.append((
            category, tbl_id, region_name, sub_label,
            (r.get("ITM_NM") or "").strip(), (r.get("UNIT_NM") or "").strip(),
            prd_de, value, fetched_at,
        ))
    if not out:
        return 0
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cur = conn.executemany("""
        INSERT OR IGNORE INTO kosis_stats
          (category, tbl_id, region_name, sub_label, item_name, unit_name, prd_de, value, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, out)
    conn.commit()
    saved = cur.rowcount
    conn.close()
    return saved


# ── 페이지 UI ─────────────────────────────────────────────────
_init_table()

st.title("KOSIS 통계 수집")
st.caption(
    "인구·세대수 / 주택 인허가실적 / 가동사업자 현황(시군구) — KOSIS(국가통계포털)에서 "
    "지역·연도를 한 번에 수집합니다. 통계표는 kosis.kr에서 검색 → 상세화면의 **Open API** "
    "버튼으로 생성한 파라미터를 그대로 사용합니다."
)

_pre_key, _key_src = _saved_api_key()
api_key = st.text_input(
    "KOSIS Open API 인증키",
    value=_pre_key, type="password",
    help="kosis.kr/openapi → 회원가입 → Open API 활용신청 (자동승인) → 마이페이지에서 확인. "
         "앱 재시작 후에도 유지하려면 Streamlit Cloud → Settings → Secrets 에 "
         "KOSIS_API_KEY = \"키값\" 으로 저장하세요.",
)
if api_key:
    st.session_state[_KEY_SS] = api_key
if _key_src == "Streamlit Secrets (영구 저장)":
    st.caption("🔒 저장된 인증키를 Streamlit Secrets에서 불러왔습니다.")
elif _key_src == "환경변수":
    st.caption("🔑 환경변수(KOSIS_API_KEY)에 저장된 인증키를 불러왔습니다.")

col1, col2 = st.columns(2)
with col1:
    start_yr = st.number_input("시작 연도", min_value=1990, max_value=date.today().year, value=2010, step=1)
with col2:
    end_yr = st.number_input("종료 연도", min_value=1990, max_value=date.today().year + 1, value=date.today().year, step=1)

st.divider()

if st.button("▶ 지금 수집 시작", type="primary", disabled=not api_key):
    results = {}
    for key, cfg in CATEGORIES.items():
        with st.spinner(f"{cfg['label']} 수집 중..."):
            res = _fetch_kosis(cfg, api_key, int(start_yr), int(end_yr))
            saved = 0
            if not res["error"]:
                saved = _save_rows(key, cfg["tbl_id"], res["rows"])
            results[key] = {
                "label": cfg["label"],
                "error": res["error"],
                "total": len(res["rows"]),
                "saved": saved,
                "sample": res["rows"][:5],
            }

    st.session_state["kosis_last_result"] = results
    st.cache_data.clear()
    st.rerun()

_res = st.session_state.get("kosis_last_result")
if _res:
    with st.container(border=True):
        top = st.columns([5, 1])
        top[0].markdown("### 📋 마지막 수집 결과")
        if top[1].button("지우기", key="kosis_clear_result"):
            del st.session_state["kosis_last_result"]
            st.rerun()

        for key, r in _res.items():
            if r["error"]:
                st.error(f"**{r['label']}**: {r['error']}")
                continue
            st.success(f"**{r['label']}**: 전체 {r['total']}건 중 {r['saved']}건 새로 저장 (중복 제외)")
            with st.expander(f"🔍 {r['label']} 원본 응답 샘플 (5건) — 어느 필드가 지역명인지 직접 확인해보세요", expanded=(r["saved"] == 0)):
                st.json(r["sample"] if r["sample"] else "응답에 item이 없습니다.")

st.divider()
st.subheader("저장된 KOSIS 통계 현황")
try:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT category,
               COUNT(*) AS cnt,
               COUNT(DISTINCT region_name) AS n_region,
               MIN(prd_de) AS from_yr, MAX(prd_de) AS to_yr
        FROM kosis_stats
        GROUP BY category
    """).fetchall()
    conn.close()
    if rows:
        import pandas as pd
        df = pd.DataFrame([dict(r) for r in rows])
        df["category"] = df["category"].map(lambda c: CATEGORIES.get(c, {}).get("label", c))
        df.columns = ["카테고리", "행 수", "지역 수", "시작연도", "종료연도"]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.caption("아직 수집된 KOSIS 통계가 없습니다. 위에서 수집을 시작하세요.")
except Exception as e:
    st.caption(f"현황 조회 오류: {e}")
