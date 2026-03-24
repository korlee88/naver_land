"""
recommend.py  ─  핵심 추천 매물 TOP 5
"""

import streamlit as st
import pandas as pd

from utils_style import inject_korean_font
from utils_auth  import require_auth
from utils_graph import (
    build_df, compute_score, get_badges, render_sidebar,
    RANK_EMOJIS, SHARED_CSS,
)

inject_korean_font()
require_auth()

st.markdown(SHARED_CSS, unsafe_allow_html=True)

# ── 사이드바 ─────────────────────────────────
df_all = build_df()
if df_all.empty:
    st.error("데이터 없음"); st.stop()

sel, price_sel, _ = render_sidebar(df_all, show_drop_th=False)

# ── 필터 적용 ────────────────────────────────
if not sel:
    st.warning("왼쪽에서 단지를 선택해 주세요."); st.stop()

df = df_all[df_all["complex_name"].isin(sel)].copy()
df = df[(df["eok"] >= price_sel[0]) & (df["eok"] <= price_sel[1])]
if df.empty:
    st.warning("조건에 맞는 데이터가 없습니다."); st.stop()

# ── 헤더 ─────────────────────────────────────
col_title, col_info = st.columns([3, 7])
with col_title:
    st.markdown("#### 🏆 핵심 추천 매물", unsafe_allow_html=True)
with col_info:
    _latest = df["uploadday"].max().strftime("%Y-%m-%d") if not df.empty else "?"
    st.markdown(
        f"<div style='font-size:11px;color:#64748b;padding-top:10px;'>"
        f"기준일: {_latest}  |  단지: {', '.join(sel)}</div>",
        unsafe_allow_html=True,
    )

st.caption(
    "점수 기준: 가격(4억±1000만원당±5) · 층수(-30~+40) · 방향(-15~+25) · "
    "평형(-20~+15) · 하락폭(+20) · 신규(+10) · 확인매물(+10) · 메모키워드(-10~+15)"
)

# ── 점수 계산 ────────────────────────────────
parts = [
    compute_score(df[df["complex_name"] == cn])
    for cn in sel
    if not df[df["complex_name"] == cn].empty
]

if not parts:
    st.info("추천 점수를 계산할 데이터가 없습니다."); st.stop()

df_sc     = pd.concat(parts, ignore_index=True)
latest_day = df_sc["uploadday"].max()
df_latest  = df_sc[df_sc["uploadday"] == latest_day].copy()

if "uid" in df_latest.columns:
    df_latest = df_latest.sort_values("score", ascending=False).drop_duplicates("uid")

# ── TOP 5 표시 ───────────────────────────────
st.markdown('<div class="sec">🥇 TOP 5 추천 매물</div>', unsafe_allow_html=True)

top5 = df_latest.sort_values("score", ascending=False).head(5).reset_index(drop=True)

card_cols = st.columns(5)
for i, row in top5.iterrows():
    badges    = get_badges(row)
    area_str  = f"{row['area']}"            if pd.notna(row.get("area"))      else ""
    floor_str = f"{row['floor']}층"         if pd.notna(row.get("floor"))     else ""
    dong_str  = f"{row['dong']}동"          if pd.notna(row.get("dong"))  and str(row.get("dong"))  not in ("", "nan") else ""
    dir_str   = f"{row['direction']}"       if pd.notna(row.get("direction")) and str(row.get("direction")) not in ("", "nan") else ""
    date_str  = f"확인: {row['confirm_date']}" if pd.notna(row.get("confirm_date")) and str(row.get("confirm_date")) not in ("", "nan") else ""
    memo_str  = str(row.get("memo", ""))[:30] if pd.notna(row.get("memo")) and str(row.get("memo")) not in ("", "nan") else ""
    drop_txt  = f"▼{row['drop_eok']:.2f}억 하락" if row.get("drop_eok", 0) > 0 else ""

    detail_parts = [p for p in [dong_str, area_str, floor_str, dir_str] if p]
    detail_str   = "  ·  ".join(detail_parts)
    total_score  = row["score"]

    def _fmt(v, label):
        if v == 0: return ""
        sign = "+" if v > 0 else ""
        return f'<span style="color:{"#16a34a" if v>0 else "#dc2626"};font-size:9px;">{label}{sign}{v:.0f}</span>'

    breakdown = " ".join(filter(None, [
        _fmt(row.get("score_price", 0), "가격"),
        _fmt(row.get("score_floor", 0), "층"),
        _fmt(row.get("score_dir",   0), "방향"),
        _fmt(row.get("score_area",  0), "평형"),
        _fmt(row.get("score_drop",  0), "하락"),
        _fmt(row.get("score_memo",  0), "메모"),
    ]))

    bar_w = max(0, min(100, int((total_score + 50) / 150 * 100)))

    with card_cols[i]:
        st.markdown(f"""
<div class="rec-card">
  <div style="display:flex;justify-content:space-between;align-items:center;">
    <span class="rec-rank">{RANK_EMOJIS[i]}</span>
    <span style="font-size:13px;color:#6366f1;font-weight:800;">{total_score:.0f}점</span>
  </div>
  <div class="rec-name" style="margin-top:4px;">{row.get('complex_name','')}</div>
  <div class="rec-price">{row['eok']:.2f}억</div>
  <div style="margin-top:4px;">{badges}</div>
  <div class="rec-detail" style="margin-top:6px;">{detail_str}</div>
  {'<div class="rec-detail" style="color:#ef4444;">' + drop_txt + '</div>' if drop_txt else ''}
  {'<div class="rec-detail">' + date_str + '</div>' if date_str else ''}
  {'<div class="rec-detail" style="color:#475569;font-style:italic;">' + memo_str + '</div>' if memo_str else ''}
  <div style="margin-top:6px;line-height:1.8;">{breakdown}</div>
  <div class="score-bar-bg">
    <div class="score-bar-fill" style="width:{bar_w}%;"></div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── TOP 5 이후 전체 순위표 ────────────────────
st.markdown('<div class="sec" style="margin-top:16px;">📋 전체 순위</div>', unsafe_allow_html=True)

show_cols = ["complex_name", "eok", "score", "score_price", "score_floor",
             "score_dir", "score_area", "score_drop", "score_new", "score_conf",
             "floor", "direction", "area", "dong"]
show_cols = [c for c in show_cols if c in df_latest.columns]

df_show = (
    df_latest[show_cols]
    .sort_values("score", ascending=False)
    .reset_index(drop=True)
)
df_show.index += 1

rename_map = {
    "complex_name": "단지", "eok": "가격(억)", "score": "총점",
    "score_price": "가격점", "score_floor": "층수점", "score_dir": "방향점",
    "score_area": "평형점", "score_drop": "하락점", "score_new": "신규점",
    "score_conf": "확인점", "floor": "층", "direction": "방향",
    "area": "평형", "dong": "동",
}
df_show.rename(columns=rename_map, inplace=True)

st.dataframe(df_show, use_container_width=True, height=400)
