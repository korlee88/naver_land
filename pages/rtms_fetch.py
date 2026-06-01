"""
pages/rtms_fetch.py — 국토교통부 아파트 실거래가 자동 수집 (웹앱 내장)

네이버와 달리 국토부 공공 API는 클라우드 서버에서도 호출 가능하므로,
Streamlit Cloud에 배포된 웹앱에서 버튼만 누르면 바로 수집됩니다.
"""
import os
import sqlite3
import time
import xml.etree.ElementTree as ET
from datetime import date

import requests
import streamlit as st

from utils_style import inject_korean_font

inject_korean_font()

DB_PATH = os.environ.get("DB_PATH", "/tmp/naver_land.db")

API_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"

# 수집 대상 단지명 키워드 (포함 시 저장, 빈 값이면 전체)
TARGET_KEYWORDS = [
    "센트럴자이", "더샵지제역", "e편한세상",
    "동문굿모닝힐", "동문디이스트", "우미린", "공도",
]

# 법정동 코드 (앞 5자리)
LAWD_OPTIONS = {
    "경기 평택시": "41220",
    "충북 청주시 흥덕구": "43113",
    "충북 청주시 청원구": "43114",
}

_KEY_SS = "rtms_api_key"


# ── DB ────────────────────────────────────────────────────────
def _init_table():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rtms_transactions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            lawd_cd       TEXT    NOT NULL,
            deal_year     INTEGER NOT NULL,
            deal_month    INTEGER NOT NULL,
            deal_day      INTEGER NOT NULL,
            apt_name      TEXT    NOT NULL,
            dong          TEXT,
            floor         INTEGER,
            area          REAL,
            price_man     INTEGER NOT NULL,
            build_year    INTEGER,
            road_name     TEXT,
            cancel_yn     TEXT,
            fetched_at    TEXT    NOT NULL,
            UNIQUE(lawd_cd, deal_year, deal_month, deal_day, apt_name, dong, floor, area, price_man)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_rtms_apt_date
        ON rtms_transactions(apt_name, deal_year, deal_month)
    """)
    conn.commit()
    conn.close()


def _ym_list(months: int) -> list[str]:
    """오늘 기준 최근 N개월 YYYYMM 리스트"""
    today = date.today()
    out = []
    y, m = today.year, today.month
    for _ in range(months):
        out.append(f"{y}{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return out


def _fetch_month(api_key: str, lawd_cd: str, ym: str, page: int, num_rows: int = 100) -> dict:
    params = {
        "serviceKey": api_key,
        "LAWD_CD":    lawd_cd,
        "DEAL_YMD":   ym,
        "pageNo":     page,
        "numOfRows":  num_rows,
    }
    try:
        resp = requests.get(API_URL, params=params, timeout=20)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        code = root.findtext(".//resultCode", "")
        if code not in ("00", "000"):
            msg = root.findtext(".//resultMsg", "알 수 없는 오류")
            return {"error": f"[{code}] {msg}", "totalCount": 0, "items": []}

        total = int(root.findtext(".//totalCount", "0") or 0)
        items = []
        for item in root.findall(".//item"):
            def g(tag):
                v = item.findtext(tag, "")
                return v.strip() if v else ""
            items.append({
                "apt_name":   g("아파트"),
                "dong":       g("법정동"),
                "floor":      g("층"),
                "area":       g("전용면적"),
                "price_man":  g("거래금액").replace(",", ""),
                "build_year": g("건축년도"),
                "deal_day":   g("일"),
                "road_name":  g("도로명"),
                "cancel_yn":  g("해제여부"),
            })
        return {"error": "", "totalCount": total, "items": items}
    except Exception as e:
        return {"error": str(e), "totalCount": 0, "items": []}


def _save_items(lawd_cd: str, ym: str, items: list) -> int:
    year, month = int(ym[:4]), int(ym[4:])
    fetched_at = date.today().isoformat()
    rows = []
    for it in items:
        if TARGET_KEYWORDS and not any(kw in it["apt_name"] for kw in TARGET_KEYWORDS):
            continue
        try:
            price_man = int(it["price_man"]) if it["price_man"] else None
            floor     = int(it["floor"])     if it["floor"]     else None
            area      = float(it["area"])    if it["area"]      else None
            build_yr  = int(it["build_year"]) if it["build_year"] else None
            day       = int(it["deal_day"])  if it["deal_day"]  else 1
        except (ValueError, TypeError):
            continue
        if price_man is None:
            continue
        rows.append((
            lawd_cd, year, month, day,
            it["apt_name"], it["dong"], floor, area, price_man,
            build_yr, it["road_name"], it["cancel_yn"] or None, fetched_at,
        ))
    if not rows:
        return 0
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cur = conn.executemany("""
        INSERT OR IGNORE INTO rtms_transactions
          (lawd_cd, deal_year, deal_month, deal_day, apt_name, dong, floor, area,
           price_man, build_year, road_name, cancel_yn, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()
    saved = cur.rowcount
    conn.close()
    return saved


# ── 페이지 UI ─────────────────────────────────────────────────
_init_table()

st.title("국토부 실거래가 자동 수집")
st.caption("실제 거래 완료된 가격 (국토교통부 공식). 네이버 호가보다 정확하며, 클라우드에서 바로 수집됩니다.")

# API 키 입력
default_key = st.session_state.get(_KEY_SS, os.environ.get("RTMS_API_KEY", ""))
api_key = st.text_input(
    "공공데이터포털 API 인증키",
    value=default_key,
    type="password",
    help="data.go.kr 마이페이지 → 일반 인증키(Decoding)",
)
if api_key:
    st.session_state[_KEY_SS] = api_key

col1, col2 = st.columns(2)
with col1:
    region = st.selectbox("지역", list(LAWD_OPTIONS.keys()), index=0)
with col2:
    months = st.number_input("수집 개월 수", min_value=1, max_value=60, value=24, step=6)

lawd_cd = LAWD_OPTIONS[region]
st.caption(f"법정동 코드: {lawd_cd}  |  대상 단지 키워드: {', '.join(TARGET_KEYWORDS)}")

st.divider()

if st.button("▶ 지금 수집 시작", type="primary", disabled=not api_key):
    yms = _ym_list(int(months))
    progress = st.progress(0.0)
    status = st.empty()
    log = st.container()
    total_saved = 0
    first_error = None

    for i, ym in enumerate(yms):
        status.markdown(f"**수집 중...** {ym} ({i+1}/{len(yms)})")

        all_items = []
        page = 1
        while True:
            res = _fetch_month(api_key, lawd_cd, ym, page)
            if res["error"]:
                if first_error is None:
                    first_error = res["error"]
                break
            all_items.extend(res["items"])
            if len(all_items) >= res["totalCount"] or not res["items"]:
                break
            page += 1
            time.sleep(0.2)

        saved = _save_items(lawd_cd, ym, all_items)
        total_saved += saved
        with log:
            st.caption(f"  {ym} → 전체 {len(all_items)}건 중 대상 {saved}건 저장")
        progress.progress((i + 1) / len(yms))
        time.sleep(0.1)

    status.empty()
    if first_error:
        st.error(f"API 오류: {first_error}\n\n인증키가 올바른지, 활용신청이 승인됐는지 확인하세요.")
    if total_saved > 0:
        st.success(f"🎉 수집 완료 — 총 **{total_saved}건** 저장")
    elif not first_error:
        st.warning("저장된 건이 없습니다. (해당 기간 대상 단지 거래가 없었을 수 있음)")

    st.cache_data.clear()

# ── 수집 현황 ─────────────────────────────────────────────────
st.divider()
st.subheader("저장된 실거래가 현황")
try:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT apt_name,
               COUNT(*) AS cnt,
               MIN(printf('%04d-%02d', deal_year, deal_month)) AS from_ym,
               MAX(printf('%04d-%02d', deal_year, deal_month)) AS to_ym,
               MIN(price_man) AS min_man,
               MAX(price_man) AS max_man
        FROM rtms_transactions
        GROUP BY apt_name
        ORDER BY cnt DESC
    """).fetchall()
    conn.close()
    if rows:
        import pandas as pd
        df = pd.DataFrame([dict(r) for r in rows])
        df["min_man"] = (df["min_man"] / 10000).round(2).astype(str) + "억"
        df["max_man"] = (df["max_man"] / 10000).round(2).astype(str) + "억"
        df.columns = ["단지명", "거래건수", "시작", "종료", "최저가", "최고가"]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.caption("아직 수집된 실거래가가 없습니다. 위에서 수집을 시작하세요.")
except Exception as e:
    st.caption(f"현황 조회 오류: {e}")
