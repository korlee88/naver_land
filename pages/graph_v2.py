"""
graph_v2.py  ─  단지별 가격 추이 차트
"""

from datetime import datetime, timedelta

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from utils_style import inject_korean_font
from utils_auth  import require_auth
import re as _re

from utils_graph import (
    build_df, make_daily, render_sidebar,
    PALETTE, SHARED_CSS,
)

# 중상층 기준: 11층 이상 (저층 1~5, 중층 6~10, 중상층 11층+)
MID_HIGH_FLOOR = 11

def _parse_floor(val) -> int | None:
    """floor 컬럼에서 현재 층수 추출. 예) '15/25층' → 15"""
    if not val or (isinstance(val, float) and val != val):
        return None
    s = str(val).strip()
    if s.startswith(("저", "지", "반")):
        return 1
    m = _re.match(r"^(\d+)", s)
    return int(m.group(1)) if m else None

inject_korean_font()
require_auth()

st.markdown(SHARED_CSS, unsafe_allow_html=True)

# ── 사이드바 ─────────────────────────────────
df_all = build_df()
if df_all.empty:
    st.error("데이터 없음"); st.stop()

sel, price_sel, drop_th = render_sidebar(df_all, show_drop_th=True)

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
    st.markdown("#### 📊 가격 추이 차트", unsafe_allow_html=True)
with col_info:
    st.markdown(
        f"<div style='font-size:11px;color:#64748b;padding-top:10px;'>"
        f"단지: {', '.join(sel)}  |  총 {len(df):,}건</div>",
        unsafe_allow_html=True,
    )

# ══════════════════════════════════════════════
# [1] 단지별 추이 차트
# ══════════════════════════════════════════════
st.markdown('<div class="sec">📊 가격 추이</div>', unsafe_allow_html=True)

COLS_PER_ROW = 3
Y_MAX_DEFAULT = 4.2   # 기본 y축 상한 (억)

for row_start in range(0, len(sel), COLS_PER_ROW):
    row_items  = sel[row_start : row_start + COLS_PER_ROW]
    chart_cols = st.columns(len(row_items), gap="small")

    for col_idx, cname in enumerate(row_items):
        idx   = row_start + col_idx
        dfc   = df[df["complex_name"] == cname].copy()
        color = PALETTE[idx % len(PALETTE)]

        if dfc.empty:
            chart_cols[col_idx].caption(f"{cname} — 데이터 없음")
            continue

        # 중상층(11층 이상) 필터링
        if "floor" in dfc.columns:
            dfc["_floor_n"] = dfc["floor"].apply(_parse_floor)
            dfc_mid = dfc[dfc["_floor_n"] >= MID_HIGH_FLOOR]
        else:
            dfc_mid = dfc

        # 중상층 데이터가 없으면 전체 사용 (코멘트에 명시)
        use_all = dfc_mid.empty
        plot_df = dfc if use_all else dfc_mid

        total_n   = len(dfc)
        mid_n     = len(dfc_mid)
        floor_comment = (
            f"⚠️ 중상층 데이터 없음 — 전체 {total_n}건 기준"
            if use_all else
            f"🏢 중상층(11층 이상) {mid_n}건 / 전체 {total_n}건 기준 트렌드"
        )

        d2   = make_daily(plot_df, drop_th)
        x    = d2["uploadday"]
        mask = x.notna() & d2["min_eok"].notna()

        # y축 상한: 데이터 최대값이 기본값 초과 시 데이터 최대값으로 자동 확장
        y_max = max(Y_MAX_DEFAULT, float(d2["max_eok"].max()) * 1.03) if mask.any() else Y_MAX_DEFAULT
        y_min = max(0, float(d2["min_eok"].min()) * 0.97) if mask.any() else 0

        fig = go.Figure()

        # 최저가
        fig.add_trace(go.Scatter(
            x=x[mask], y=d2["min_eok"][mask],
            name="최저", line=dict(color=color, width=2, dash="dash"),
        ))
        # 평균가
        avg_mask = mask & d2["avg_eok"].notna()
        if avg_mask.any():
            fig.add_trace(go.Scatter(
                x=x[avg_mask], y=d2["avg_eok"][avg_mask],
                name="평균", line=dict(color=color, width=1.5, dash="dot"), opacity=0.8,
            ))
        # 최고가
        fig.add_trace(go.Scatter(
            x=x[mask], y=d2["max_eok"][mask],
            name="최고", line=dict(color=color, width=1.0), opacity=0.5,
        ))
        # 급락 마커
        drops = d2[d2["is_drop"]]
        if not drops.empty:
            fig.add_trace(go.Scatter(
                x=drops["uploadday"], y=drops["min_eok"],
                mode="markers", name="▼급락",
                marker=dict(symbol="triangle-down", size=8, color="#ef4444"),
            ))

        fig.update_layout(
            title=dict(text=cname, font=dict(size=11), x=0, xanchor="left"),
            height=270,
            margin=dict(l=40, r=20, t=30, b=60),
            plot_bgcolor="white",
            legend=dict(orientation="h", y=-0.28, x=0, font=dict(size=9)),
            xaxis=dict(tickfont=dict(size=8), tickangle=30),
            yaxis=dict(
                title="가격(억)", tickfont=dict(size=8),
                showgrid=True, gridcolor="#f1f5f9",
                dtick=0.5, tickformat=".1f",
                range=[y_min, y_max],
            ),
        )
        chart_cols[col_idx].plotly_chart(fig, use_container_width=True,
                                         config={"staticPlot": True})
        chart_cols[col_idx].caption(floor_comment)


# ══════════════════════════════════════════════
# [2] 단지별 가격 현황 요약
# ══════════════════════════════════════════════
st.divider()
st.markdown('<div class="sec" style="margin-top:4px;">📋 단지별 가격 현황 <span style="font-size:10px;color:#94a3b8;font-weight:400;">· 중상층(11층 이상) 매물 기준, 최근 1주</span></div>', unsafe_allow_html=True)

CUT_RECENT = pd.Timestamp(datetime.now() - timedelta(days=7))

summary_rows = []
for cname in sel:
    dfc = df[df["complex_name"] == cname].copy()
    if dfc.empty:
        continue
    # 중상층 필터 (없으면 전체)
    if "floor" in dfc.columns:
        dfc["_floor_n"] = dfc["floor"].apply(_parse_floor)
        dfc_m = dfc[dfc["_floor_n"] >= MID_HIGH_FLOOR]
        dfc   = dfc_m if not dfc_m.empty else dfc
    recent  = dfc[dfc["uploadday"] >= CUT_RECENT]
    older   = dfc[dfc["uploadday"] <  CUT_RECENT]

    cur_min = recent["eok"].min()  if not recent.empty else dfc["eok"].min()
    cur_avg = recent["eok"].mean() if not recent.empty else dfc["eok"].mean()
    cur_max = recent["eok"].max()  if not recent.empty else dfc["eok"].max()
    prv_min = older["eok"].min()   if not older.empty  else None
    prv_avg = older["eok"].mean()  if not older.empty  else None

    min_chg = round(cur_min - prv_min, 2) if prv_min is not None else None
    avg_chg = round(cur_avg - prv_avg, 2) if prv_avg is not None else None

    latest_day = dfc["uploadday"].max()
    summary_rows.append({
        "단지": cname,
        "cur_min": cur_min, "cur_avg": cur_avg, "cur_max": cur_max,
        "min_chg": min_chg, "avg_chg": avg_chg,
        "latest": latest_day,
        "n": len(recent) if not recent.empty else 0,
    })

summary_rows.sort(key=lambda r: r["cur_min"])
border_colors = ["#fbbf24", "#94a3b8", "#cd7f32"] + ["#e2e8f0"] * 10
rank_icons    = ["🥇", "🥈", "🥉"] + [""] * 10

if summary_rows:
    cols_s = st.columns(len(summary_rows))
    for i, r in enumerate(summary_rows):

        def _chg_html(v):
            if v is None or abs(v) < 0.01:
                return "<span style='color:#94a3b8;font-size:10px;'>보합</span>"
            color = "#dc2626" if v > 0 else "#16a34a"
            arrow = "▲" if v > 0 else "▼"
            return f"<span style='color:{color};font-size:10px;'>{arrow} {abs(v):.2f}억</span>"

        latest_str = r["latest"].strftime("%m/%d") if pd.notna(r["latest"]) else "-"

        cols_s[i].markdown(f"""
<div style="background:#f8fafc;border:1.5px solid {border_colors[i]};border-radius:10px;
            padding:10px 12px;">
  <div style="font-size:11px;color:#64748b;margin-bottom:4px;">{rank_icons[i]} {r['단지']}</div>
  <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:2px;">
    <span style="font-size:10px;color:#94a3b8;">최저</span>
    <span style="font-size:17px;font-weight:800;color:#1e293b;">{r['cur_min']:.2f}억</span>
    {_chg_html(r['min_chg'])}
  </div>
  <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:2px;">
    <span style="font-size:10px;color:#94a3b8;">평균</span>
    <span style="font-size:13px;font-weight:600;color:#475569;">{r['cur_avg']:.2f}억</span>
    {_chg_html(r['avg_chg'])}
  </div>
  <div style="display:flex;justify-content:space-between;align-items:baseline;">
    <span style="font-size:10px;color:#94a3b8;">최고</span>
    <span style="font-size:13px;color:#94a3b8;">{r['cur_max']:.2f}억</span>
    <span style="font-size:9px;color:#cbd5e1;">기준 {latest_str}</span>
  </div>
</div>""", unsafe_allow_html=True)
