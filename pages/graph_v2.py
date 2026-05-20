"""
graph_v2.py  ─  단지별 가격 추이 차트
"""
import math
from datetime import datetime, timedelta

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from utils_style import inject_korean_font
from utils_auth  import require_auth
import re as _re

from utils_graph import build_df, make_weekly, DROP_TH, SHARED_CSS

PRIORITY_COMPLEX = "평택센트럴자이 2단지"
MY_BUY_PRICE     = 3.20
COLS_PER_ROW     = 2

X_OPTIONS = {
    "1주": 7, "2주": 14, "3주": 21, "4주": 28,
    "6주": 42, "2달": 60, "3달": 90, "6달": 180, "1년": 365,
}
DEFAULT_PERIOD = "2달"

FLOOR_GROUPS = {
    "저층(≤5)":      (None, 5),
    "중층(6-10)":    (6, 10),
    "중상층(11-15)": (11, 15),
    "고층(≥16)":     (16, None),
}
FLOOR_KEYS     = list(FLOOR_GROUPS.keys())
DEFAULT_FLOORS = ["중상층(11-15)"]

TRADE_OPTS    = ["매매", "전세", "월세"]
DIR_ORDER     = ["남향", "남동향", "남서향", "동향", "서향", "북향"]


def _parse_floor(val) -> int | None:
    if not val or (isinstance(val, float) and val != val):
        return None
    s = str(val).strip()
    if s.startswith(("저", "지", "반")):
        return 1
    m = _re.match(r"^(\d+)", s)
    return int(m.group(1)) if m else None


def _area_label(area_str) -> str:
    """'84A/59.7m²' → '84A'"""
    if not area_str or str(area_str) in ("None", "nan"):
        return "?"
    return str(area_str).split("/")[0].strip()


def _auto_dtick(y_range: float) -> float:
    if y_range <= 0.5:  return 0.1
    if y_range <= 1.5:  return 0.2
    if y_range <= 3.0:  return 0.5
    if y_range <= 8.0:  return 1.0
    return 2.0


def _week_label(dt) -> str:
    """날짜 → 'W21' 형식 (ISO 주차)"""
    try:
        iso = pd.Timestamp(dt).isocalendar()
        return f"W{iso[1]:02d}"
    except Exception:
        return str(dt)[:5]


def _init_ms(key: str, default: list, valid: list):
    """multiselect 세션 상태 초기화 + 유효성 정리"""
    if key not in st.session_state:
        st.session_state[key] = [v for v in default if v in valid]
        return
    existing = st.session_state[key]
    if isinstance(existing, list):
        st.session_state[key] = [v for v in existing if v in valid]
    else:
        v = str(existing)
        st.session_state[key] = [v] if v in valid else [v2 for v2 in default if v2 in valid]


inject_korean_font()
require_auth()

st.markdown(SHARED_CSS, unsafe_allow_html=True)
st.markdown("""
<style>
[data-testid="stButton"] button {
    height: 28px !important; min-height: 0 !important;
    padding: 0 5px !important; font-size: 11px !important;
}
/* 멀티셀렉트 레이블 */
[data-testid="stMultiSelect"] label {
    font-size: 11px !important;
    color: #475569 !important;
    margin-bottom: 1px !important;
    font-weight: 600 !important;
}
/* 선택된 태그(pill) */
[data-baseweb="tag"] {
    font-size: 10px !important;
    padding: 1px 5px !important;
    height: 20px !important;
    line-height: 18px !important;
    border-radius: 4px !important;
}
[data-baseweb="tag"] span { font-size: 10px !important; }
/* 멀티셀렉트 입력창 높이 */
[data-testid="stMultiSelect"] [data-baseweb="select"] > div {
    min-height: 30px !important;
    padding: 2px 6px !important;
    font-size: 11px !important;
}
/* 필터 컨테이너 내부 여백 */
[data-testid="stVerticalBlockBorderWrapper"] > div > div {
    padding: 8px 10px 6px 10px !important;
    gap: 4px !important;
}
/* selectbox 컴팩트 */
[data-testid="stSelectbox"] [data-baseweb="select"] > div {
    min-height: 30px !important; font-size: 11px !important;
}
[data-testid="stSelectbox"] label { font-size: 11px !important; }
</style>
""", unsafe_allow_html=True)

# ── 데이터 로드 ─────────────────────────────────
df_all = build_df()
if df_all.empty:
    st.error("데이터 없음"); st.stop()

_raw_list     = sorted(df_all["complex_name"].unique().tolist())
_complex_list = (
    [PRIORITY_COMPLEX] + [c for c in _raw_list if c != PRIORITY_COMPLEX]
    if PRIORITY_COMPLEX in _raw_list else _raw_list
)

with st.sidebar:
    st.markdown("## 🔍 단지 선택")
    if st.button("🔄 캐시 초기화", use_container_width=True):
        st.cache_data.clear(); st.rerun()
    st.divider()
    _default_sel = [PRIORITY_COMPLEX] if PRIORITY_COMPLEX in _complex_list else _complex_list[:1]
    sel = st.multiselect(
        "단지 (최대 4개 권장)",
        _complex_list,
        default=_default_sel,
        key="sidebar_sel_v2",
    )

if not sel:
    st.warning("왼쪽에서 단지를 선택해 주세요."); st.stop()

df = df_all[df_all["complex_name"].isin(sel)].copy()
if df.empty:
    st.warning("조건에 맞는 데이터가 없습니다."); st.stop()

if "floor" in df.columns:
    df["_floor_n"] = df["floor"].apply(_parse_floor)

# ── 헤더 ──────────────────────────────────────
st.markdown("#### 📊 가격 추이 차트")

# ── 기간 선택 (섹션 타이틀과 나란히) ─────────────
_sec_col, _period_col, _ = st.columns([3, 1, 6])
_sec_col.markdown('<div class="sec" style="padding-top:6px;">📊 가격 추이 (주차 기준)</div>', unsafe_allow_html=True)
_period_label = _period_col.selectbox(
    "기간",
    list(X_OPTIONS.keys()),
    index=list(X_OPTIONS.keys()).index(DEFAULT_PERIOD),
    key="x_period_v2",
    label_visibility="collapsed",
)
_x_days = X_OPTIONS[_period_label]

_all_days = df["uploadday"].dropna().tolist()
if _all_days:
    X_MAX = max(_all_days)
    X_MIN = X_MAX - timedelta(days=_x_days)
else:
    X_MIN, X_MAX = None, None

# ══════════════════════════════════════════════
# 단지별 추이 차트
# ══════════════════════════════════════════════
for row_start in range(0, len(sel), COLS_PER_ROW):
    row_items  = sel[row_start : row_start + COLS_PER_ROW]
    chart_cols = st.columns(len(row_items), gap="small")

    for col_idx, cname in enumerate(row_items):
        with chart_cols[col_idx]:
            dfc = df[df["complex_name"] == cname].copy()
            if dfc.empty:
                st.caption(f"{cname} — 데이터 없음")
                continue

            # ── 필터 옵션 준비 ───────────────────────
            _area_raw   = dfc["area"].dropna().unique().tolist() if "area" in dfc.columns else []
            _area_opts  = sorted({_area_label(a) for a in _area_raw if _area_label(a) != "?"})
            _dong_opts  = sorted(dfc["dong"].dropna().unique().tolist()) if "dong" in dfc.columns else []
            _trade_opts = [t for t in TRADE_OPTS if t in dfc["trade_type"].unique()] if "trade_type" in dfc.columns else []
            _dir_raw    = dfc["direction"].dropna().unique().tolist() if "direction" in dfc.columns else []
            _dir_opts   = [d for d in DIR_ORDER if d in _dir_raw] + [d for d in _dir_raw if d not in DIR_ORDER]

            _fk_floor = f"ff_{cname}"
            _fk_area  = f"fa_{cname}"
            _fk_dong  = f"fd_{cname}"
            _fk_trade = f"ft_{cname}"
            _fk_dir   = f"fdir_{cname}"

            _init_ms(_fk_floor, DEFAULT_FLOORS, FLOOR_KEYS)
            _init_ms(_fk_area,  [],             _area_opts)
            _init_ms(_fk_dong,  [],             _dong_opts)
            _init_ms(_fk_trade, [],             _trade_opts)
            _init_ms(_fk_dir,   [],             _dir_opts)

            # ── 필터 UI ─────────────────────────────
            with st.container(border=True):
                # 1행: 층 / 평형 / 동
                _r1c1, _r1c2, _r1c3 = st.columns([1.1, 1.2, 1.7])
                with _r1c1:
                    st.multiselect("층",  FLOOR_KEYS,  key=_fk_floor, placeholder="전체")
                with _r1c2:
                    st.multiselect("평형", _area_opts, key=_fk_area,  placeholder="전체")
                with _r1c3:
                    st.multiselect("동",  _dong_opts,  key=_fk_dong,  placeholder="전체")

                # 2행: 거래유형 / 방향
                _r2c1, _r2c2 = st.columns([1, 2])
                with _r2c1:
                    st.multiselect("거래유형", _trade_opts, key=_fk_trade, placeholder="전체")
                with _r2c2:
                    st.multiselect("방향", _dir_opts, key=_fk_dir, placeholder="전체")

            # ── 필터 적용 ────────────────────────────
            _sel_floors = st.session_state[_fk_floor]
            _sel_areas  = st.session_state[_fk_area]
            _sel_dongs  = st.session_state[_fk_dong]
            _sel_trades = st.session_state[_fk_trade]
            _sel_dirs   = st.session_state[_fk_dir]

            plot_df = dfc.copy()

            if _sel_dongs and "dong" in plot_df.columns:
                _tmp = plot_df[plot_df["dong"].isin(_sel_dongs)]
                if not _tmp.empty: plot_df = _tmp

            if _sel_areas and "area" in plot_df.columns:
                _tmp = plot_df[plot_df["area"].apply(_area_label).isin(_sel_areas)]
                if not _tmp.empty: plot_df = _tmp

            if _sel_trades and "trade_type" in plot_df.columns:
                _tmp = plot_df[plot_df["trade_type"].isin(_sel_trades)]
                if not _tmp.empty: plot_df = _tmp

            if _sel_dirs and "direction" in plot_df.columns:
                _tmp = plot_df[plot_df["direction"].isin(_sel_dirs)]
                if not _tmp.empty: plot_df = _tmp

            if _sel_floors and "floor" in plot_df.columns:
                plot_df["_floor_n"] = plot_df["floor"].apply(_parse_floor)
                _fmask = pd.Series(False, index=plot_df.index)
                for _fl_key in _sel_floors:
                    _flo, _fhi = FLOOR_GROUPS[_fl_key]
                    if _flo is not None and _fhi is not None:
                        _fmask |= ((plot_df["_floor_n"] >= _flo) & (plot_df["_floor_n"] <= _fhi))
                    elif _flo is not None:
                        _fmask |= (plot_df["_floor_n"] >= _flo)
                    elif _fhi is not None:
                        _fmask |= (plot_df["_floor_n"] <= _fhi)
                _tmp = plot_df[_fmask]
                if not _tmp.empty: plot_df = _tmp

            _f_str = "/".join(_sel_floors) if _sel_floors else "전체"
            _a_str = "/".join(_sel_areas)  if _sel_areas  else "전체"
            _d_str = "/".join(_sel_dongs)  if _sel_dongs  else "전체"
            _t_str = "/".join(_sel_trades) if _sel_trades else "전체"
            _r_str = "/".join(_sel_dirs)   if _sel_dirs   else "전체"
            filter_note = (
                f"층:{_f_str}  ·  평형:{_a_str}  ·  동:{_d_str}  ·  "
                f"거래:{_t_str}  ·  방향:{_r_str}  ·  {len(plot_df)}건"
            )

            # 주차 집계
            d2   = make_weekly(plot_df, DROP_TH)
            x    = d2["uploadday"]
            mask = x.notna() & d2["min_eok"].notna()
            if not mask.any():
                st.caption(f"{cname} — 표시할 데이터 없음")
                continue

            # ── Y축 개별 범위 ──────────────────────
            _vals  = pd.concat([d2["min_eok"], d2["max_eok"]]).dropna()
            _v_min = float(_vals.min())
            _v_max = float(_vals.max())
            _span  = max(_v_max - _v_min, 0.2)
            _pad   = max(0.1, round(_span * 0.15, 2))
            _y_min = round(math.floor(_v_min * 10) / 10 - _pad, 2)
            _y_max = round(math.ceil(_v_max * 10) / 10 + _pad, 2)
            _dtick = _auto_dtick(_y_max - _y_min)

            # ── X축 주차 레이블 ────────────────────
            _tickvals = x[mask].tolist()
            _ticktext = [_week_label(dt) for dt in _tickvals]

            C_MIN  = "#2563eb"
            C_AVG  = "#94a3b8"
            C_MAX  = "#fca5a5"
            _hover = "%{x|%Y-%m-%d}<br><b>%{y:.2f}억</b><extra></extra>"

            _n_actual = d2[d2["n"] > 0]
            _n_max    = int(_n_actual["n"].max()) if not _n_actual.empty else 5

            fig = make_subplots(specs=[[{"secondary_y": True}]])

            fig.add_trace(go.Scatter(
                x=x[mask], y=d2["max_eok"][mask], name="최고",
                mode="lines+markers",
                line=dict(color=C_MAX, width=1.2),
                marker=dict(color=C_MAX, size=4),
                hovertemplate=_hover,
            ), secondary_y=False)
            fig.add_trace(go.Scatter(
                x=x[mask], y=d2["min_eok"][mask],
                mode="none", name="가격범위",
                fill="tonexty", fillcolor="rgba(37,99,235,0.06)",
                showlegend=False, hoverinfo="skip",
            ), secondary_y=False)

            avg_mask = mask & d2["avg_eok"].notna()
            if avg_mask.any():
                fig.add_trace(go.Scatter(
                    x=x[avg_mask], y=d2["avg_eok"][avg_mask], name="평균",
                    mode="lines",
                    line=dict(color=C_AVG, width=1.5, dash="dot"),
                    hovertemplate=_hover,
                ), secondary_y=False)

            _trend_mask = d2["min_7avg"].notna()
            if _trend_mask.any():
                fig.add_trace(go.Scatter(
                    x=d2["uploadday"][_trend_mask], y=d2["min_7avg"][_trend_mask],
                    name="추세(7주)",
                    mode="lines",
                    line=dict(color="#a78bfa", width=1.5, dash="dash"),
                    hovertemplate="%{x|%Y-%m-%d}<br>추세 %{y:.2f}억<extra></extra>",
                ), secondary_y=False)

            fig.add_trace(go.Scatter(
                x=x[mask], y=d2["min_eok"][mask], name="최저",
                mode="lines+markers",
                line=dict(color=C_MIN, width=2.5),
                marker=dict(color=C_MIN, size=6, line=dict(color="white", width=1.5)),
                hovertemplate=_hover,
            ), secondary_y=False)

            drops = d2[d2["is_drop"]]
            if not drops.empty:
                fig.add_trace(go.Scatter(
                    x=drops["uploadday"], y=drops["min_eok"],
                    mode="markers", name="▼급락",
                    marker=dict(symbol="triangle-down", size=9, color="#ef4444"),
                    hovertemplate="%{x|%Y-%m-%d}<br>▼ 급락 %{y:.2f}억<extra></extra>",
                ), secondary_y=False)

            if not _n_actual.empty:
                fig.add_trace(go.Bar(
                    x=_n_actual["uploadday"], y=_n_actual["n"],
                    name="매물수",
                    marker_color="rgba(148,163,184,0.3)",
                    hovertemplate="%{x|%m/%d}<br>매물 %{y}건<extra></extra>",
                ), secondary_y=True)

            # KPI (실거주 단지)
            if cname == PRIORITY_COMPLEX:
                _valid_kpi = d2["min_eok"].dropna()
                if len(_valid_kpi) >= 2:
                    _cur   = float(_valid_kpi.iloc[-1])
                    _prev  = float(_valid_kpi.iloc[-2])
                    _delta = _cur - _prev
                    _pct   = _delta / _prev * 100 if _prev else 0
                    _km1, _km2, _km3 = st.columns(3)
                    _km1.metric("현재 최저가", f"{_cur:.2f}억", f"{_delta:+.2f}억")
                    _km2.metric("전주 대비", f"{_pct:+.1f}%")
                    _km3.metric("매수가 대비", "3.20억", f"{_cur - MY_BUY_PRICE:+.2f}억")

            fig.update_layout(
                title=dict(text=cname, font=dict(size=13, color="#1e293b"), x=0, xanchor="left"),
                height=360,
                margin=dict(l=50, r=40, t=36, b=60),
                plot_bgcolor="white",
                legend=dict(orientation="h", y=-0.20, x=0, font=dict(size=10)),
                hovermode="x unified",
                xaxis=dict(
                    tickvals=_tickvals,
                    ticktext=_ticktext,
                    tickfont=dict(size=10), tickangle=0,
                    range=[X_MIN, X_MAX] if X_MIN is not None else None,
                    gridcolor="#f1f5f9", showgrid=True,
                    fixedrange=True,
                ),
                yaxis=dict(
                    title=dict(text="억", font=dict(size=10)),
                    tickfont=dict(size=10),
                    showgrid=True, gridcolor="#f1f5f9",
                    dtick=_dtick, tickformat=".2f",
                    range=[_y_min, _y_max],
                    fixedrange=True,
                ),
                yaxis2=dict(
                    showgrid=False, showticklabels=True,
                    tickfont=dict(size=8, color="#94a3b8"),
                    ticksuffix="건",
                    range=[0, _n_max * 6],
                    fixedrange=True,
                ),
            )
            st.plotly_chart(
                fig, use_container_width=True,
                config={"staticPlot": False, "displayModeBar": False, "scrollZoom": False},
            )
            st.caption(filter_note)


# ══════════════════════════════════════════════
# 단지별 가격 현황 요약
# ══════════════════════════════════════════════
st.divider()
st.markdown(
    '<div class="sec" style="margin-top:4px;">📋 단지별 가격 현황 '
    '<span style="font-size:10px;color:#94a3b8;font-weight:400;">· 필터 선택 기준, 최근 1주</span></div>',
    unsafe_allow_html=True,
)

CUT_RECENT = pd.Timestamp(datetime.now() - timedelta(days=7))
summary_rows = []

for cname in sel:
    dfc = df[df["complex_name"] == cname].copy()
    if dfc.empty:
        continue

    _sel_floors = st.session_state.get(f"ff_{cname}",   DEFAULT_FLOORS)
    _sel_areas  = st.session_state.get(f"fa_{cname}",   [])
    _sel_dongs  = st.session_state.get(f"fd_{cname}",   [])
    _sel_trades = st.session_state.get(f"ft_{cname}",   [])
    _sel_dirs   = st.session_state.get(f"fdir_{cname}", [])

    if _sel_dongs and "dong" in dfc.columns:
        _t = dfc[dfc["dong"].isin(_sel_dongs)]
        if not _t.empty: dfc = _t
    if _sel_areas and "area" in dfc.columns:
        _t = dfc[dfc["area"].apply(_area_label).isin(_sel_areas)]
        if not _t.empty: dfc = _t
    if _sel_trades and "trade_type" in dfc.columns:
        _t = dfc[dfc["trade_type"].isin(_sel_trades)]
        if not _t.empty: dfc = _t
    if _sel_dirs and "direction" in dfc.columns:
        _t = dfc[dfc["direction"].isin(_sel_dirs)]
        if not _t.empty: dfc = _t
    if _sel_floors and "floor" in dfc.columns:
        dfc["_floor_n"] = dfc["floor"].apply(_parse_floor)
        _fmask = pd.Series(False, index=dfc.index)
        for _fl_key in _sel_floors:
            _flo, _fhi = FLOOR_GROUPS[_fl_key]
            if _flo is not None and _fhi is not None:
                _fmask |= ((dfc["_floor_n"] >= _flo) & (dfc["_floor_n"] <= _fhi))
            elif _flo is not None:
                _fmask |= (dfc["_floor_n"] >= _flo)
            elif _fhi is not None:
                _fmask |= (dfc["_floor_n"] <= _fhi)
        _t = dfc[_fmask]
        if not _t.empty: dfc = _t

    recent = dfc[dfc["uploadday"] >= CUT_RECENT]
    older  = dfc[dfc["uploadday"] <  CUT_RECENT]

    cur_min = recent["eok"].min()  if not recent.empty else dfc["eok"].min()
    cur_avg = recent["eok"].mean() if not recent.empty else dfc["eok"].mean()
    cur_max = recent["eok"].max()  if not recent.empty else dfc["eok"].max()
    prv_min = older["eok"].min()   if not older.empty  else None
    prv_avg = older["eok"].mean()  if not older.empty  else None

    summary_rows.append({
        "단지": cname,
        "cur_min": cur_min, "cur_avg": cur_avg, "cur_max": cur_max,
        "min_chg": round(cur_min - prv_min, 2) if prv_min is not None else None,
        "avg_chg": round(cur_avg - prv_avg, 2) if prv_avg is not None else None,
        "latest": dfc["uploadday"].max(),
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
