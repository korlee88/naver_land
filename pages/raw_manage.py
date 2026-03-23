# pages/raw_manage.py
import streamlit as st
import pandas as pd
from db import read_history, read_listings, delete_history_by_ids

st.set_page_config(page_title="RAW 관리", layout="wide")

from utils_style import inject_korean_font
from utils_auth import require_auth
inject_korean_font()
require_auth()

st.title("🧹 RAW 데이터 관리")

# ── 데이터 로드 (price_history + listings 조인) ──
hist = read_history()
lst  = read_listings()
df   = pd.DataFrame(hist) if hist else pd.DataFrame()

if df.empty:
    st.info("price_history 데이터가 없습니다.")
    st.stop()

if "id" not in df.columns:
    st.error("id 컬럼이 없어 삭제 기능을 사용할 수 없습니다.")
    st.stop()

# listings에서 단지명·동·층·호수 가져오기
if lst:
    df_lst = pd.DataFrame(lst)[["uid","complex_name","dong","floor","area","trade_type"]]
    df = df.merge(df_lst, on="uid", how="left")

# seen_at → 날짜 문자열 (YYYY-MM-DD)
if "seen_at" in df.columns:
    df["seen_at"] = pd.to_datetime(df["seen_at"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df.sort_values("seen_at", ascending=False)

# ── 필터 ──────────────────────────────────────
f1, f2, f3 = st.columns([2, 2, 3])

if "complex_name" in df.columns:
    complex_opts = sorted(df["complex_name"].dropna().astype(str).unique().tolist())
    sel_complex  = f1.multiselect("단지 (복수 선택 가능)", complex_opts, default=complex_opts)
else:
    sel_complex = []

if "dong" in df.columns:
    dong_opts = ["전체"] + sorted(df["dong"].dropna().astype(str).unique().tolist())
    sel_dong  = f2.selectbox("동", dong_opts)
else:
    sel_dong = "전체"

keyword = f3.text_input("키워드 검색", placeholder="메모 / 금액 등")

# 필터 적용
view = df.copy()
if sel_complex and "complex_name" in view.columns:
    view = view[view["complex_name"].astype(str).isin(sel_complex)]
if sel_dong != "전체" and "dong" in view.columns:
    view = view[view["dong"].astype(str) == sel_dong]
if keyword:
    mask = pd.Series(False, index=view.index)
    for col in view.select_dtypes(include="object").columns:
        mask |= view[col].str.contains(keyword, na=False, case=False)
    view = view[mask]

st.caption(f"총 {len(df):,}건 중 필터 결과: **{len(view):,}건**")

# ── 표시 컬럼: seen_at(일자) / 단지 / 동 / 평형 / 층 / 금액 / 메모 ──
SHOW_COLS = [c for c in [
    "id", "seen_at", "complex_name", "dong", "area", "floor", "price_text", "memo"
] if c in view.columns]

# ── 행 선택 테이블 (Shift+클릭 / 드래그로 블록 선택) ──
show_df = view[SHOW_COLS].copy().reset_index(drop=True)

st.caption("💡 행 클릭으로 선택 · Shift+클릭으로 범위 선택 · Ctrl+클릭으로 추가 선택")

event = st.dataframe(
    show_df,
    use_container_width=True,
    height=600,
    column_config={
        "seen_at":      st.column_config.TextColumn("날짜",   width="small"),
        "complex_name": st.column_config.TextColumn("단지명", width="medium"),
        "dong":         st.column_config.TextColumn("동",     width="small"),
        "area":         st.column_config.TextColumn("평형",   width="small"),
        "floor":        st.column_config.TextColumn("층",     width="small"),
        "price_text":   st.column_config.TextColumn("금액",   width="small"),
        "memo":         st.column_config.TextColumn("메모"),
        "id":           st.column_config.NumberColumn("ID",   width="small"),
    },
    hide_index=True,
    on_select="rerun",
    selection_mode="multi-row",
)

selected_rows = event.selection.rows if event and event.selection else []
selected_ids  = show_df.iloc[selected_rows]["id"].tolist() if selected_rows else []

# ── 삭제 실행 ─────────────────────────────────
d1, d2, d3 = st.columns([1, 1, 4])
d1.metric("선택", f"{len(selected_ids)}건")
confirm = d2.checkbox("삭제 확인")

if d3.button("🗑️ 선택 항목 삭제", type="primary",
             disabled=(not confirm or len(selected_ids) == 0)):
    deleted = delete_history_by_ids(selected_ids)
    st.success(f"{deleted}건 삭제 완료")
    st.rerun()
