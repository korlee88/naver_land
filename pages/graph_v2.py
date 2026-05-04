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

# ── 모바일 반응형 CSS ─────────────────────────
st.markdown("""
<style>
@media screen and (max-width: 768px) {

    /* ── 차트 컬럼: 1열 전환 ── */
    [data-testid="column"]:has([data-testid="stPlotlyChart"]) {
        width: 100% !important;
        flex: 0 0 100% !important;
        min-width: 100% !important;
    }

    /* ── 가격 현황 카드: 1열 전환 ── */
    [data-testid="column"]:has(div[style*="border-radius:10px"]) {
        width: 100% !important;
        flex: 0 0 100% !important;
        min-width: 100% !important;
    }

    /* ── Y축 입력 행: 가로 유지 + 크기 축소 ── */
    section.main [data-testid="stHorizontalBlock"]:has([data-testid="stNumberInput"]) {
        flex-wrap: nowrap !important;
        gap: 6px !important;
    }
    section.main [data-testid="stHorizontalBlock"]:has([data-testid="stNumberInput"]) > div[data-testid="column"] {
        flex: 1 1 0% !important;
        min-width: 0 !important;
        width: auto !important;
    }
    [data-testid="stNumberInput"] label { font-size: 11px !important; }
    [data-testid="stNumberInput"] input {
        font-size: 13px !important;
        height: 36px !important;
        padding: 2px 8px !important;
    }
    [data-testid="stNumberInput"] button {
        height: 36px !important;
        width: 28px !important;
        min-width: 0 !important;
    }

    /* ── 기간 버튼 행: 가로 유지 + 높이/폰트 축소 ── */
    section.main [data-testid="stHorizontalBlock"]:has([data-testid="stButton"]) {
        flex-wrap: nowrap !important;
        gap: 4px !important;
    }
    section.main [data-testid="stHorizontalBlock"]:has([data-testid="stButton"]) > div[data-testid="column"] {
        flex: 1 1 0% !important;
        min-width: 0 !important;
    }
    [data-testid="stButton"] button {
        height: 34px !important;
        min-height: 0 !important;
        padding: 0 4px !important;
    }
    [data-testid="stButton"] button p {
        font-size: 11px !important;
        line-height: 1 !important;
    }
}
</style>
""", unsafe_allow_html=True)

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

COLS_PER_ROW = 2
Y_TICK = 0.3          # 3천만원 단위

# 모든 단지의 중상층 데이터를 모아 공통 Y·X축 범위 계산
import math
_all_vals = []
_all_days = []
for _cn in sel:
    _d = df[df["complex_name"] == _cn].copy()
    if "floor" in _d.columns:
        _d["_floor_n"] = _d["floor"].apply(_parse_floor)
        _dm = _d[_d["_floor_n"] >= MID_HIGH_FLOOR]
        _d  = _dm if not _dm.empty else _d
    if not _d.empty:
        _all_vals.extend(_d["eok"].dropna().tolist())
        _all_days.extend(_d["uploadday"].dropna().tolist())

# ── Y축 기본값: 데이터 최고가+0.2 / 최저가-0.2 자동 계산 ──
_data_max = max(_all_vals) if _all_vals else 4.5
_data_min = min(_all_vals) if _all_vals else 3.0
_default_y_max = round(math.ceil(_data_max * 10) / 10 + 0.2, 1)
_default_y_min = round(math.floor(_data_min * 10) / 10 - 0.2, 1)

# 첫 로드 또는 단지 선택 변경 시 Y축 자동 초기화
if st.session_state.get("_prev_sel_graph") != sel or "y_min" not in st.session_state:
    st.session_state.y_min = _default_y_min
    st.session_state.y_max = _default_y_max
st.session_state._prev_sel_graph = sel

# ── X축 기간 옵션 ──────────────────────────────
X_RANGE_OPTIONS = {"1주": 7, "2주": 14, "3주": 21, "1달": 30, "2달": 60}
if "x_range_label" not in st.session_state:
    st.session_state.x_range_label = "1달"

def _set_x_range(label):
    st.session_state.x_range_label = label

# ── Y축 범위 (2열 입력, 트레일링 공백 제거) ──
_y_cols = st.columns(2)
_new_y_min = _y_cols[0].number_input("Y 최솟값 (억)", value=float(st.session_state.y_min), step=0.1, format="%.1f", min_value=0.0)
_new_y_max = _y_cols[1].number_input("Y 최댓값 (억)", value=float(st.session_state.y_max), step=0.1, format="%.1f", min_value=0.1)
st.session_state.y_min = _new_y_min
st.session_state.y_max = _new_y_max

# ── 기간 선택 버튼 (트레일링 공백 제거) ──────
_xr_cols = st.columns([0.5] + [1] * len(X_RANGE_OPTIONS))
_xr_cols[0].markdown("<div style='font-size:10px;color:#64748b;padding-top:8px;'>기간</div>", unsafe_allow_html=True)
for _xi, _label in enumerate(X_RANGE_OPTIONS):
    _xr_cols[_xi + 1].button(
        _label, key=f"xr_{_label}",
        type="primary" if st.session_state.x_range_label == _label else "secondary",
        use_container_width=True,
        on_click=_set_x_range, args=(_label,),
    )

Y_MIN = st.session_state.y_min
Y_MAX = st.session_state.y_max

_x_days = X_RANGE_OPTIONS[st.session_state.x_range_label]
# dtick: 라벨 겹침 없도록 기간에 따라 자동 조절 (ms 단위)
_DAY_MS = 86_400_000
_DTICK_MAP = {7: _DAY_MS, 14: _DAY_MS * 2, 21: _DAY_MS * 3, 30: _DAY_MS * 5, 60: _DAY_MS * 10}
X_DTICK = _DTICK_MAP.get(_x_days, _DAY_MS * 5)

if _all_days:
    X_MAX = max(_all_days)
    X_MIN = X_MAX - timedelta(days=_x_days)
else:
    X_MIN, X_MAX = None, None

for row_start in range(0, len(sel), COLS_PER_ROW):
    row_items  = sel[row_start : row_start + COLS_PER_ROW]
    chart_cols = st.columns(len(row_items), gap="small")

    for col_idx, cname in enumerate(row_items):
        dfc = df[df["complex_name"] == cname].copy()

        if dfc.empty:
            chart_cols[col_idx].caption(f"{cname} — 데이터 없음")
            continue

        # 중상층(11층 이상) 필터링
        if "floor" in dfc.columns:
            dfc["_floor_n"] = dfc["floor"].apply(_parse_floor)
            dfc_mid = dfc[dfc["_floor_n"] >= MID_HIGH_FLOOR]
        else:
            dfc_mid = dfc

        use_all = dfc_mid.empty
        plot_df = dfc if use_all else dfc_mid

        total_n = len(dfc)
        mid_n   = len(dfc_mid)
        floor_comment = (
            f"⚠️ 중상층 데이터 없음 — 전체 {total_n}건 기준"
            if use_all else
            f"🏢 중상층(11층 이상) {mid_n}건 / 전체 {total_n}건 기준 트렌드"
        )

        d2   = make_daily(plot_df, drop_th)
        x    = d2["uploadday"]
        mask = x.notna() & d2["min_eok"].notna()

        # 고정 색상: 최저=파랑, 평균=회색, 최고=연빨강
        C_MIN = "#2563eb"
        C_AVG = "#94a3b8"
        C_MAX = "#fca5a5"

        _hover = "%{x|%Y-%m-%d}<br><b>%{y:.2f}억</b><extra></extra>"

        fig = go.Figure()

        # 최고가 (배경 느낌, 먼저 그림)
        fig.add_trace(go.Scatter(
            x=x[mask], y=d2["max_eok"][mask],
            name="최고",
            mode="lines+markers",
            line=dict(color=C_MAX, width=1.5),
            marker=dict(color=C_MAX, size=4),
            hovertemplate=_hover,
        ))
        # 평균가
        avg_mask = mask & d2["avg_eok"].notna()
        if avg_mask.any():
            fig.add_trace(go.Scatter(
                x=x[avg_mask], y=d2["avg_eok"][avg_mask],
                name="평균",
                mode="lines+markers",
                line=dict(color=C_AVG, width=1.5, dash="dot"),
                marker=dict(color=C_AVG, size=4),
                hovertemplate=_hover,
            ))
        # 최저가 (가장 위)
        fig.add_trace(go.Scatter(
            x=x[mask], y=d2["min_eok"][mask],
            name="최저",
            mode="lines+markers",
            line=dict(color=C_MIN, width=2.5),
            marker=dict(color=C_MIN, size=5, line=dict(color="white", width=1)),
            hovertemplate=_hover,
        ))
        # 급락 마커
        drops = d2[d2["is_drop"]]
        if not drops.empty:
            fig.add_trace(go.Scatter(
                x=drops["uploadday"], y=drops["min_eok"],
                mode="markers", name="▼급락",
                marker=dict(symbol="triangle-down", size=9, color="#ef4444"),
                hovertemplate="%{x|%Y-%m-%d}<br>▼ 급락 %{y:.2f}억<extra></extra>",
            ))

        fig.update_layout(
            title=dict(text=cname, font=dict(size=13, color="#1e293b"), x=0, xanchor="left"),
            height=340,
            margin=dict(l=50, r=20, t=36, b=70),
            plot_bgcolor="white",
            legend=dict(orientation="h", y=-0.22, x=0, font=dict(size=10)),
            hovermode="x unified",
            xaxis=dict(
                tickfont=dict(size=10), tickangle=45,
                tickformat="%m/%d",
                dtick=X_DTICK,
                range=[X_MIN, X_MAX] if X_MIN is not None else None,
                gridcolor="#f1f5f9", showgrid=True,
                fixedrange=True,
            ),
            yaxis=dict(
                title=dict(text="억", font=dict(size=10)),
                tickfont=dict(size=10),
                showgrid=True, gridcolor="#f1f5f9",
                dtick=Y_TICK, tickformat=".1f",
                range=[Y_MIN, Y_MAX],
                fixedrange=True,
            ),
        )
        chart_cols[col_idx].plotly_chart(fig, use_container_width=True,
                                         config={"staticPlot": False,
                                                 "displayModeBar": False,
                                                 "scrollZoom": False})
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
