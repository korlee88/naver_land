"""
pages/naver_fetch.py — 네이버 부동산 시세 자동 수집 (로컬 전용)

⚠️  이 페이지는 로컬에서 실행할 때만 동작합니다.
    네이버가 클라우드 서버 IP를 차단하기 때문입니다.
"""
import time
import os
import sqlite3
from datetime import date, timedelta

import requests
import streamlit as st

from utils_style import inject_korean_font

inject_korean_font()

DB_PATH = os.environ.get("DB_PATH", "/tmp/naver_land.db")

COMPLEX_MAP: dict[str, int] = {
    "평택센트럴자이 2단지": 110834,
    # "평택센트럴자이 1단지": 0,
    # "평택센트럴자이 3단지": 0,
    # "더샵지제역센트럴파크(1BL)": 0,
    # "e편한세상지제역": 0,
}

BASE_URL = "https://fin.land.naver.com/front-api/v1"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Origin": "https://fin.land.naver.com",
    "Referer": "https://fin.land.naver.com/",
    "sec-fetch-site": "same-origin",
    "sec-fetch-mode": "cors",
    "sec-fetch-dest": "empty",
}


# ── API helpers ───────────────────────────────────────────────
def _get_pyeong_list(session: requests.Session, complex_number: int) -> list[dict]:
    try:
        resp = session.get(
            f"{BASE_URL}/complex/pyeong/complexPyeongList",
            params={"complexNumber": complex_number},
            timeout=10,
        )
        data = resp.json()
        if data.get("isSuccess"):
            return data.get("result", [])
    except Exception:
        pass
    return []


def _fetch_prices(
    session: requests.Session,
    complex_number: int,
    pyeong_type_number: int,
    start_date: date,
    end_date: date,
) -> dict:
    try:
        resp = session.get(
            f"{BASE_URL}/complex/marketPrice/list",
            params={
                "complexNumber": complex_number,
                "pyeongTypeNumber": pyeong_type_number,
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "cpList": ["kab", "kbstar"],
            },
            timeout=15,
        )
        return resp.json()
    except Exception:
        return {}


def _save_prices(
    complex_name: str,
    complex_number: int,
    pyeong_label: str,
    pyeong_type_number: int,
    data: dict,
) -> int:
    fetched_at = date.today().isoformat()
    rows = []
    for cp_data in data.get("result", []):
        cp = cp_data.get("cp", "")
        for price_date, avg_price in cp_data.get("dealPrices", {}).items():
            rng = cp_data.get("dealPriceRanges", {}).get(price_date, {})
            rows.append((
                complex_name, complex_number, pyeong_label, pyeong_type_number,
                cp, "매매", price_date, avg_price,
                rng.get("ceiling"), rng.get("floor"), fetched_at,
            ))
        for price_date, avg_price in cp_data.get("depositPrices", {}).items():
            rng = cp_data.get("depositPriceRanges", {}).get(price_date, {})
            rows.append((
                complex_name, complex_number, pyeong_label, pyeong_type_number,
                cp, "전세", price_date, avg_price,
                rng.get("ceiling"), rng.get("floor"), fetched_at,
            ))
    if not rows:
        return 0
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executemany("""
        INSERT INTO naver_market_prices
          (complex_name, complex_number, pyeong_label, pyeong_type_number,
           cp, trade_type, price_date, avg_price, max_price, min_price, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(complex_number, pyeong_type_number, cp, trade_type, price_date)
        DO UPDATE SET
            avg_price  = excluded.avg_price,
            max_price  = excluded.max_price,
            min_price  = excluded.min_price,
            fetched_at = excluded.fetched_at
    """, rows)
    conn.commit()
    conn.close()
    return len(rows)


# ── 저장된 쿠키 로드/저장 ─────────────────────────────────────
_COOKIE_KEY = "naver_fetch_cookie"


def _load_cookie() -> str:
    return st.session_state.get(_COOKIE_KEY, "")


def _save_cookie(val: str):
    st.session_state[_COOKIE_KEY] = val


# ── 페이지 UI ─────────────────────────────────────────────────
st.title("네이버 시세 자동 수집")

st.info(
    "**로컬 실행 전용** — 네이버가 클라우드 서버 IP를 차단하므로, "
    "`streamlit run app.py` 를 내 컴퓨터에서 실행해야 동작합니다.",
    icon="ℹ️",
)

# 쿠키 입력
with st.expander("🍪 Cookie 설정", expanded=(_load_cookie() == "")):
    st.markdown(
        "**Chrome DevTools에서 복사 방법:**\n"
        "1. `fin.land.naver.com` 접속\n"
        "2. **F12** → **Network** 탭\n"
        "3. 아무 요청이나 클릭 → **Headers** → `Cookie` 값 전체 복사\n"
        "4. 아래에 붙여넣기"
    )
    cookie_input = st.text_area(
        "Cookie 값",
        value=_load_cookie(),
        height=100,
        placeholder="NAC=...; NNB=...; nstore_session=...",
        label_visibility="collapsed",
    )
    if st.button("저장", key="save_cookie"):
        _save_cookie(cookie_input.strip())
        st.success("저장됨")
        st.rerun()

cookie = _load_cookie()

# 수집 설정
col1, col2 = st.columns(2)
with col1:
    days = st.number_input("수집 기간 (일)", min_value=7, max_value=730, value=365, step=30)
with col2:
    end_date = st.date_input("종료일", value=date.today())

start_date = end_date - timedelta(days=int(days))
st.caption(f"📅 {start_date} ~ {end_date}")

# 수집 대상 단지 표시
active_complexes = {k: v for k, v in COMPLEX_MAP.items() if v != 0}
if not active_complexes:
    st.warning("COMPLEX_MAP에 complexNumber가 설정된 단지가 없습니다.")
else:
    st.markdown("**수집 대상 단지:**")
    for name, num in active_complexes.items():
        st.markdown(f"- {name} (#{num})")

st.divider()

# 수집 버튼
if st.button("▶ 지금 수집 시작", type="primary", disabled=(not cookie or not active_complexes)):
    if not cookie:
        st.error("Cookie를 먼저 입력해주세요.")
        st.stop()

    session = requests.Session()
    session.headers.update(_HEADERS)
    session.headers["Cookie"] = cookie

    total = 0
    errors = []

    progress_bar = st.progress(0.0)
    status_text = st.empty()
    log_area = st.container()

    complexes = list(active_complexes.items())
    for ci, (cname, cnum) in enumerate(complexes):
        status_text.markdown(f"**수집 중...** {cname} ({ci+1}/{len(complexes)})")

        with log_area:
            with st.spinner(f"{cname} 평형 목록 조회 중..."):
                pyeong_list = _get_pyeong_list(session, cnum)

        if not pyeong_list:
            errors.append(f"{cname}: 평형 목록 조회 실패 (쿠키 만료 또는 네트워크 오류)")
            progress_bar.progress((ci + 1) / len(complexes))
            continue

        for pi, pyeong in enumerate(pyeong_list):
            ptype_no = (
                pyeong.get("pyeongTypeNo")
                or pyeong.get("pyeongTypeNumber")
                or 1
            )
            plabel = str(
                pyeong.get("supplyPyeong")
                or pyeong.get("pyeongName")
                or ptype_no
            )

            data = _fetch_prices(session, cnum, ptype_no, start_date, end_date)
            if data.get("isSuccess"):
                n = _save_prices(cname, cnum, plabel, ptype_no, data)
                total += n
                with log_area:
                    st.caption(f"  ✅ {cname} {plabel}평 → {n}건 저장")
            else:
                with log_area:
                    st.caption(f"  ❌ {cname} {plabel}평 → 실패")
                errors.append(f"{cname} {plabel}평 응답 오류")

            time.sleep(0.5)
            progress_bar.progress((ci + pi / max(len(pyeong_list), 1)) / len(complexes))

        progress_bar.progress((ci + 1) / len(complexes))

    status_text.empty()
    progress_bar.progress(1.0)

    if total > 0:
        st.success(f"🎉 수집 완료 — 총 **{total}건** 저장 ({DB_PATH})")
    if errors:
        with st.expander(f"⚠️ 오류 {len(errors)}건"):
            for e in errors:
                st.text(e)

    st.cache_data.clear()

# ── 수집 현황 ─────────────────────────────────────────────────
st.divider()
st.subheader("저장된 시세 현황")

try:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT complex_name, trade_type,
               COUNT(*) as cnt,
               MIN(price_date) as from_date,
               MAX(price_date) as to_date,
               MAX(fetched_at) as last_fetched
        FROM naver_market_prices
        GROUP BY complex_name, trade_type
        ORDER BY complex_name, trade_type
    """).fetchall()
    conn.close()

    if rows:
        import pandas as pd
        df = pd.DataFrame([dict(r) for r in rows])
        df.columns = ["단지명", "거래유형", "레코드 수", "시작일", "종료일", "마지막 수집"]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.caption("아직 수집된 시세 데이터가 없습니다.")
except Exception as e:
    st.caption(f"현황 조회 오류: {e}")
