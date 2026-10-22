"""
pages/ecos_fetch.py — 한국은행 ECOS 금리·경제통계 수집

금리는 부동산 가격을 움직이는 가장 큰 외부 변수인데 이 앱은 지금까지 보지 않았다.
ECOS는 무료·자동승인 인증키로 전국 단일 시계열을 주므로 KOSIS처럼 지역명을
맞출 필요가 없다.

통계표코드는 한국은행이 개편하면 바뀔 수 있어, 프리셋을 정답으로 두지 않고
**앱 안에서 직접 검색해 확인**하도록 만들었다 (아래 "통계표 찾기").
"""
import os
import sqlite3
from datetime import date, datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from db import push_ecos_to_sheet, restore_ecos_from_sheet, backup_sheet_usage, BACKUP_SHEET_URL
from utils_style import inject_korean_font
import utils_ecos as ec

inject_korean_font()

DB_PATH = os.environ.get("DB_PATH", "/tmp/naver_land.db")
_KEY_SS = "ecos_api_key"


def _init_table():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ecos_stats (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            stat_code   TEXT    NOT NULL,
            stat_name   TEXT,
            item_name   TEXT,
            unit_name   TEXT,
            period      TEXT    NOT NULL,
            value       REAL,
            fetched_at  TEXT    NOT NULL,
            UNIQUE(stat_code, item_name, period)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ecos_code_period ON ecos_stats(stat_code, period)")
    conn.commit()
    conn.close()


def _saved_api_key() -> tuple[str, str]:
    if st.session_state.get(_KEY_SS):
        return st.session_state[_KEY_SS], "세션 입력"
    try:
        if "ECOS_API_KEY" in st.secrets:
            return str(st.secrets["ECOS_API_KEY"]), "Streamlit Secrets (영구 저장)"
    except Exception:
        pass
    env = os.environ.get("ECOS_API_KEY", "")
    return (env, "환경변수") if env else ("", "")


def _save_records(records: list[tuple]) -> int:
    if not records:
        return 0
    fetched_at = datetime.now().isoformat(timespec="seconds")
    rows = [r + (fetched_at,) for r in records]
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cur = conn.executemany("""
        INSERT OR IGNORE INTO ecos_stats
          (stat_code, stat_name, item_name, unit_name, period, value, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()
    saved = cur.rowcount
    conn.close()
    return saved


_init_table()

st.title("한국은행 ECOS 금리 수집")
st.caption(
    "기준금리·대출금리 같은 금리 시계열을 수집합니다. 인증키는 "
    "[ecos.bok.or.kr/api](https://ecos.bok.or.kr/api/)에서 회원가입하면 자동 발급되며 "
    "보통 1일 이내에 사용할 수 있습니다."
)

_pre_key, _src = _saved_api_key()
api_key = st.text_input(
    "ECOS 인증키", value=_pre_key, type="password",
    help="앱 재시작 후에도 유지하려면 Streamlit Cloud → Settings → Secrets 에 "
         'ECOS_API_KEY = "키값" 으로 저장하세요.',
)
if api_key:
    st.session_state[_KEY_SS] = api_key
if _src:
    st.caption(f"🔑 저장된 인증키를 {_src}에서 불러왔습니다.")

if not api_key:
    st.info("인증키를 입력하면 아래 기능이 열립니다.")
    st.stop()

# ── 1. 연결 테스트 ────────────────────────────────────────────
# 파라미터가 없는 호출이라 실패하면 원인이 '인증키' 하나로 좁혀진다.
st.divider()
st.subheader("1. 연결 테스트")
st.caption("100대 통계지표를 불러옵니다. 파라미터가 없는 호출이라 실패하면 원인은 인증키입니다.")

if st.button("🔌 연결 테스트 / 최신 지표 보기", type="primary"):
    try:
        rows = ec.fetch_key_statistics(api_key)
        st.session_state["ecos_keystat"] = rows
        st.success(f"연결 성공 — 지표 {len(rows)}건을 받았습니다.")
    except Exception as e:
        st.session_state.pop("ecos_keystat", None)
        st.error(f"실패: {e}")

_ks = st.session_state.get("ecos_keystat")
if _ks:
    kdf = pd.DataFrame(_ks)
    name_col = "KEYSTAT_NAME" if "KEYSTAT_NAME" in kdf.columns else kdf.columns[0]
    rate_rows = kdf[kdf[name_col].astype(str).str.contains("금리", na=False)]
    if not rate_rows.empty:
        st.markdown("**금리 관련 지표 (현재값)**")
        st.dataframe(rate_rows, use_container_width=True, hide_index=True)
    with st.expander(f"전체 {len(kdf)}개 지표 보기"):
        st.dataframe(kdf, use_container_width=True, hide_index=True)

# ── 2. 통계표 찾기 ────────────────────────────────────────────
st.divider()
st.subheader("2. 통계표 찾기")
st.caption(
    "아래 프리셋의 통계표코드는 한국은행 개편으로 바뀔 수 있습니다. "
    "수집이 '데이터 없음'으로 나오면 여기서 현재 코드를 확인해 직접 입력하세요."
)

kw = st.text_input("통계표명 검색어", value="금리", key="ecos_kw")
if st.button("🔍 통계표 검색"):
    try:
        found = ec.search_tables(api_key, kw, limit=500)
        st.session_state["ecos_tables"] = found
        st.success(f"{len(found)}건 검색됨")
    except Exception as e:
        st.error(f"검색 실패: {e}")

if st.session_state.get("ecos_tables"):
    tdf = pd.DataFrame(st.session_state["ecos_tables"])
    keep = [c for c in ("STAT_CODE", "STAT_NAME", "CYCLE", "SRCH_YN", "ORG_NAME") if c in tdf.columns]
    st.dataframe(tdf[keep] if keep else tdf, use_container_width=True, hide_index=True)

# ── 3. 수집 ───────────────────────────────────────────────────
st.divider()
st.subheader("3. 시계열 수집")

preset_names = list(ec.RATE_PRESETS) + ["직접 입력"]
sel = st.selectbox("통계표", preset_names)
if sel == "직접 입력":
    c1, c2 = st.columns(2)
    stat_code = c1.text_input("통계표코드", value="721Y001")
    cycle = c2.selectbox("주기", ["M", "Q", "A", "D"], index=0,
                         help="월 M / 분기 Q / 년 A / 일 D")
else:
    stat_code = ec.RATE_PRESETS[sel]["stat_code"]
    cycle = ec.RATE_PRESETS[sel]["cycle"]
    st.caption(f"통계표코드 **{stat_code}** · 주기 **{cycle}**")

c3, c4 = st.columns(2)
start_year = c3.number_input("시작 연도", 1990, date.today().year, 2015)
end_year = c4.number_input("종료 연도", 1990, date.today().year, date.today().year)


def _period(year: int, cyc: str, end: bool) -> str:
    if cyc == "A":
        return str(year)
    if cyc == "M":
        return f"{year}12" if end else f"{year}01"
    if cyc == "Q":
        return f"{year}Q4" if end else f"{year}Q1"
    return f"{year}1231" if end else f"{year}0101"


if st.button("▶ 지금 수집 시작", type="primary"):
    try:
        with st.spinner("ECOS에서 수집 중..."):
            rows = ec.fetch_series(
                api_key, stat_code, cycle,
                _period(int(start_year), cycle, False),
                _period(int(end_year), cycle, True),
            )
            recs = ec.rows_to_records(rows, stat_code)
            saved = _save_records(recs)
        st.session_state["ecos_last"] = {
            "total": len(rows), "valid": len(recs), "saved": saved,
            "sample": rows[:3], "stat_code": stat_code,
        }
        if saved > 0:
            with st.spinner("☁️ 구글시트에 자동 백업 중..."):
                n, err = push_ecos_to_sheet()
            st.session_state["ecos_last"]["backup"] = (n, err)
        st.cache_data.clear()
        st.rerun()
    except Exception as e:
        st.error(f"수집 실패: {e}")
        st.caption("'데이터 없음'이면 통계표코드나 주기가 맞지 않는 경우가 많습니다 — "
                   "위 **2. 통계표 찾기**에서 현재 코드를 확인해보세요.")

_last = st.session_state.get("ecos_last")
if _last:
    with st.container(border=True):
        top = st.columns([5, 1])
        top[0].markdown("### 📋 마지막 수집 결과")
        if top[1].button("지우기", key="ecos_clear"):
            del st.session_state["ecos_last"]
            st.rerun()
        st.success(
            f"**{_last['stat_code']}** — 받은 {_last['total']}건 중 유효 {_last['valid']}건, "
            f"새로 저장 {_last['saved']}건 (중복 제외)"
        )
        if _last.get("backup"):
            n, err = _last["backup"]
            if err:
                st.error(f"⚠️ 구글시트 백업 실패: {err}")
            else:
                st.success(f"☁️ 구글시트 백업 완료 — {n}건")
        if _last["valid"] == 0 and _last["sample"]:
            with st.expander("🔍 받은 원본 샘플 (유효 데이터가 0건일 때 확인)", expanded=True):
                st.json(_last["sample"])

# ── 4. 저장 현황 ──────────────────────────────────────────────
st.divider()
st.subheader("저장된 금리 데이터")
try:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cur = pd.read_sql("""
        SELECT stat_code, item_name, unit_name, COUNT(*) AS 건수,
               MIN(period) AS 시작, MAX(period) AS 종료
        FROM ecos_stats GROUP BY stat_code, item_name, unit_name ORDER BY 건수 DESC
    """, conn)
    series = pd.read_sql("""
        SELECT stat_code, item_name, period, value FROM ecos_stats ORDER BY period
    """, conn)
    conn.close()
except Exception as e:
    cur, series = pd.DataFrame(), pd.DataFrame()
    st.caption(f"현황 조회 오류: {e}")

if cur.empty:
    st.caption("아직 수집된 금리 데이터가 없습니다.")
else:
    st.dataframe(cur.rename(columns={"stat_code": "통계표", "item_name": "항목", "unit_name": "단위"}),
                 use_container_width=True, hide_index=True)

    labels = (series["stat_code"] + " · " + series["item_name"].fillna("")).unique().tolist()
    picked = st.multiselect("차트로 볼 항목", labels, default=labels[:3])
    if picked:
        fig = go.Figure()
        for i, lab in enumerate(picked):
            code, _, item = lab.partition(" · ")
            s = series[(series["stat_code"] == code) & (series["item_name"].fillna("") == item)]
            s = s.assign(date=[ec.period_to_date(p, "M") for p in s["period"]]).dropna(subset=["date"])
            if s.empty:
                continue
            fig.add_trace(go.Scatter(x=pd.to_datetime(s["date"]), y=s["value"], name=lab[:40],
                                     mode="lines", line=dict(width=2),
                                     hovertemplate="%{x|%Y-%m} %{y:.2f}<extra></extra>"))
        fig.update_layout(height=320, margin=dict(l=8, r=8, t=8, b=8),
                          plot_bgcolor="white", paper_bgcolor="white",
                          legend=dict(orientation="h", x=0, y=1.12, font=dict(size=10)),
                          hovermode="x unified",
                          xaxis=dict(showgrid=True, gridcolor="#f0f0f0", fixedrange=True),
                          yaxis=dict(showgrid=True, gridcolor="#f0f0f0", fixedrange=True))
        st.plotly_chart(fig, use_container_width=True,
                        config={"displayModeBar": False, "scrollZoom": False}, key="ecos_chart")

# ── 5. 백업/복원 ──────────────────────────────────────────────
st.divider()
st.subheader("☁️ 데이터 영구 저장 (구글시트)")
_usage = backup_sheet_usage()
st.progress(min(_usage["ratio"], 1.0))
st.caption(
    f"백업 시트 사용량 **{_usage['cells']:,} / {_usage['limit']:,}셀 ({_usage['ratio'] * 100:.1f}%)**"
    + "  —  " + "  ·  ".join(f"{l} {n:,}행" for l, n, _ in _usage["rows"] if n)
)

b1, b2, b3 = st.columns(3)
with b1:
    if st.button("☁️ 지금 시트로 백업", use_container_width=True, disabled=cur.empty):
        with st.spinner("백업 중..."):
            n, err = push_ecos_to_sheet()
        st.error(f"백업 실패: {err}") if err else st.success(f"백업 완료 — {n}건")
with b2:
    if st.button("📥 시트에서 복원", use_container_width=True):
        with st.spinner("복원 중..."):
            n, err = restore_ecos_from_sheet()
        if n > 0:
            st.success(f"복원 완료 — {n}건")
            st.cache_data.clear()
        elif err:
            st.error(f"복원 실패: {err}")
        else:
            st.warning("복원된 데이터가 없습니다 (시트가 비었거나 이미 모두 있음).")
with b3:
    st.link_button("📄 백업 시트 열기", BACKUP_SHEET_URL, use_container_width=True)
