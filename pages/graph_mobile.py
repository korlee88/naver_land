"""
graph_mobile.py — 모바일 전용 가격 추이 차트 (트렌드만 표시)
"""
from datetime import datetime, timedelta
import math
import re as _re

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from utils_style import inject_korean_font
from utils_auth  import require_auth
from utils_graph import build_df, make_daily, render_sidebar, SHARED_CSS

MID_HIGH_FLOOR = 11

def _parse_floor(val):
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

# ── 모바일 전용 CSS ────────────────────────────
st.markdown("""
<style>
/* 페이지 가로 오버플로우 완전 차단 */
html, body { overflow-x: hidden !important; }
.block-container {
    padding: 0.5rem 0.6rem !important;
    max-width: 100vw !important;
    overflow-x: hidden !important;
    box-sizing: border-box !important;
}

/* 모든 수평 블록 오버플로우 차단 */
[data-testid="stHorizontalBlock"] {
    max-width: 100% !important;
    overflow: hidden !important;
    box-sizing: border-box !important;
}

/* Y축 입력 2열: 각 50% 강제 */
[data-testid="stHorizontalBlock"]:has([data-testid="stNumberInput"]) {
    flex-wrap: nowrap !important;
    gap: 6px !important;
}
[data-testid="stHorizontalBlock"]:has([data-testid="stNumberInput"]) > [data-testid="column"] {
    flex: 1 1 0% !important;
    min-width: 0 !important;
    max-width: calc(50% - 3px) !important;
    overflow: hidden !important;
    box-sizing: border-box !important;
}
[data-testid="stNumberInput"] { width: 100% !important; min-width: 0 !important; }
[data-baseweb="input"], [data-baseweb="base-input"] { min-width: 0 !important; }
[data-testid="stNumberInput"] label { font-size: 11px !important; }
[data-testid="stNumberInput"] input {
    font-size: 14px !important;
    height: 38px !important;
    padding: 4px 6px !important;
}
[data-testid="stNumberInput"] button { height: 38px !important; width: 28px !important; }

/* 기간 버튼 5열: 각 20% 강제 */
[data-testid="stHorizontalBlock"]:has([data-testid="stButton"]) {
    flex-wrap: nowrap !important;
    gap: 3px !important;
}
[data-testid="stHorizontalBlock"]:has([data-testid="stButton"]) > [data-testid="column"] {
    flex: 1 1 0% !important;
    min-width: 0 !important;
    max-width: calc(20% - 3px) !important;
    overflow: hidden !important;
    box-sizing: border-box !important;
}
[data-testid="stButton"] { width: 100% !important; min-width: 0 !important; }
[data-testid="stButton"] button {
    width: 100% !important;
    height: 40px !important;
    min-width: 0 !important;
    padding: 0 !important;
    border-radius: 8px !important;
    overflow: hidden !important;
}
[data-testid="stButton"] button p {
    font-size: 12px !important;
    font-weight: 600 !important;
    line-height: 1 !important;
    white-space: nowrap !important;
    overflow: hidden !important;
}
</style>
""", unsafe_allow_html=True)

# ── 데이터 로드 ────────────────────────────────
df_all = build_df()
if df_all.empty:
    st.error("데이터 없음"); st.stop()

sel, price_sel, _ = render_sidebar(df_all, show_drop_th=False)

if not sel:
    st.warning("왼쪽에서 단지를 선택해 주세요."); st.stop()

df = df_all[df_all["complex_name"].isin(sel)].copy()
df = df[(df["eok"] >= price_sel[0]) & (df["eok"] <= price_sel[1])]
if df.empty:
    st.warning("조건에 맞는 데이터가 없습니다."); st.stop()

# ── 헤더 ──────────────────────────────────────
st.markdown(
    f"<div style='font-size:11px;color:#64748b;margin-bottom:4px;'>"
    f"총 {len(df):,}건</div>",
    unsafe_allow_html=True,
)

Y_TICK = 0.3

# ── 데이터 범위 계산 ───────────────────────────
_all_vals, _all_days = [], []
for _cn in sel:
    _d = df[df["complex_name"] == _cn].copy()
    if "floor" in _d.columns:
        _d["_floor_n"] = _d["floor"].apply(_parse_floor)
        _dm = _d[_d["_floor_n"] >= MID_HIGH_FLOOR]
        _d  = _dm if not _dm.empty else _d
    if not _d.empty:
        _all_vals.extend(_d["eok"].dropna().tolist())
        _all_days.extend(_d["uploadday"].dropna().tolist())

# ── Y축 자동 초기화 ────────────────────────────
_data_max = max(_all_vals) if _all_vals else 4.5
_data_min = min(_all_vals) if _all_vals else 3.0
_default_y_max = round(math.ceil(_data_max * 10) / 10 + 0.2, 1)
_default_y_min = round(math.floor(_data_min * 10) / 10 - 0.2, 1)

if st.session_state.get("_prev_sel_mobile") != sel or "y_min_m" not in st.session_state:
    st.session_state.y_min_m = _default_y_min
    st.session_state.y_max_m = _default_y_max
st.session_state._prev_sel_mobile = sel

# ── X축 기간 옵션 ──────────────────────────────
X_OPTS = {"1주": 7, "2주": 14, "3주": 21, "1달": 30, "2달": 60}
if "x_range_m" not in st.session_state:
    st.session_state.x_range_m = "1달"

def _set_x(label):
    st.session_state.x_range_m = label

# ── Y축 입력 (2열) ─────────────────────────────
_yc = st.columns(2)
_new_y_min = _yc[0].number_input("Y 최솟값 (억)", value=float(st.session_state.y_min_m), step=0.1, format="%.1f", min_value=0.0)
_new_y_max = _yc[1].number_input("Y 최댓값 (억)", value=float(st.session_state.y_max_m), step=0.1, format="%.1f", min_value=0.1)
st.session_state.y_min_m = _new_y_min
st.session_state.y_max_m = _new_y_max

# ── 기간 버튼 (5열) ────────────────────────────
_xc = st.columns(len(X_OPTS))
for _i, _label in enumerate(X_OPTS):
    _xc[_i].button(
        _label, key=f"xr_m_{_label}",
        type="primary" if st.session_state.x_range_m == _label else "secondary",
        use_container_width=True,
        on_click=_set_x, args=(_label,),
    )

Y_MIN = st.session_state.y_min_m
Y_MAX = st.session_state.y_max_m
_x_days = X_OPTS[st.session_state.x_range_m]

_DAY_MS   = 86_400_000
_DTICK_MAP = {7: _DAY_MS, 14: _DAY_MS*2, 21: _DAY_MS*3, 30: _DAY_MS*5, 60: _DAY_MS*10}
X_DTICK = _DTICK_MAP.get(_x_days, _DAY_MS * 5)

if _all_days:
    X_MAX = max(_all_days)
    X_MIN = X_MAX - timedelta(days=_x_days)
else:
    X_MIN, X_MAX = None, None

# ── 차트 (1열, 모바일 높이) ────────────────────
C_MIN = "#2563eb"
C_AVG = "#94a3b8"
C_MAX = "#fca5a5"
_hover = "%{x|%Y-%m-%d}<br><b>%{y:.2f}억</b><extra></extra>"

for cname in sel:
    dfc = df[df["complex_name"] == cname].copy()
    if dfc.empty:
        st.caption(f"{cname} — 데이터 없음")
        continue

    if "floor" in dfc.columns:
        dfc["_floor_n"] = dfc["floor"].apply(_parse_floor)
        dfc_mid = dfc[dfc["_floor_n"] >= MID_HIGH_FLOOR]
    else:
        dfc_mid = dfc

    plot_df = dfc if dfc_mid.empty else dfc_mid
    d2   = make_daily(plot_df)
    x    = d2["uploadday"]
    mask = x.notna() & d2["min_eok"].notna()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x[mask], y=d2["max_eok"][mask], name="최고",
        mode="lines+markers",
        line=dict(color=C_MAX, width=1.5),
        marker=dict(color=C_MAX, size=4),
        hovertemplate=_hover,
    ))
    avg_mask = mask & d2["avg_eok"].notna()
    if avg_mask.any():
        fig.add_trace(go.Scatter(
            x=x[avg_mask], y=d2["avg_eok"][avg_mask], name="평균",
            mode="lines+markers",
            line=dict(color=C_AVG, width=1.5, dash="dot"),
            marker=dict(color=C_AVG, size=4),
            hovertemplate=_hover,
        ))
    fig.add_trace(go.Scatter(
        x=x[mask], y=d2["min_eok"][mask], name="최저",
        mode="lines+markers",
        line=dict(color=C_MIN, width=2.5),
        marker=dict(color=C_MIN, size=5, line=dict(color="white", width=1)),
        hovertemplate=_hover,
    ))
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
        height=270,
        margin=dict(l=42, r=8, t=30, b=55),
        plot_bgcolor="white",
        legend=dict(orientation="h", y=-0.25, x=0, font=dict(size=10)),
        hovermode="x unified",
        xaxis=dict(
            tickfont=dict(size=9), tickangle=45,
            tickformat="%m/%d", dtick=X_DTICK,
            range=[X_MIN, X_MAX] if X_MIN is not None else None,
            gridcolor="#f1f5f9", showgrid=True,
            fixedrange=True,
        ),
        yaxis=dict(
            title=dict(text="억", font=dict(size=9)),
            tickfont=dict(size=9),
            showgrid=True, gridcolor="#f1f5f9",
            dtick=Y_TICK, tickformat=".1f",
            range=[Y_MIN, Y_MAX],
            fixedrange=True,
        ),
    )
    st.plotly_chart(fig, use_container_width=True,
                    config={"staticPlot": False, "displayModeBar": False, "scrollZoom": False})
