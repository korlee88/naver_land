"""
pages/rtms_chart.py — 국토부 실거래가 기반 가격 추이 차트
"""
import os
import sqlite3
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils_style import inject_korean_font

inject_korean_font()

DB_PATH = os.environ.get("DB_PATH", "/tmp/naver_land.db")
MY_APT_KEYWORD = "센트럴자이"  # 실거주 단지 식별 키워드 (표기 차이 흡수)
MY_PRICE = 3.20                # 매수가 (억)

PALETTE = [
    "#4C72B0","#DD8452","#55A868","#C44E52",
    "#8172B2","#937860","#DA8BC3","#8C8C8C",
    "#CCB974","#64B5CD",
]


def _hex_to_rgba(hex_color: str, alpha: float = 0.12) -> str:
    """#RRGGBB → rgba(r,g,b,alpha)"""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _is_my_apt(name: str) -> bool:
    return MY_APT_KEYWORD in name and "2단지" in name


# ── 데이터 로드 ────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_data() -> pd.DataFrame:
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        df = pd.read_sql("""
            SELECT apt_name, deal_year, deal_month, deal_day,
                   area, floor, price_man, cancel_yn
            FROM rtms_transactions
            ORDER BY deal_year, deal_month, deal_day
        """, conn)
        conn.close()
    except Exception:
        return pd.DataFrame()

    if df.empty:
        return df

    # 취소 거래 제거
    df = df[df["cancel_yn"].isna() | (df["cancel_yn"] != "O")].copy()

    # 가격: 만원 → 억
    df["eok"] = df["price_man"] / 10000

    # 날짜
    df["ym"] = pd.to_datetime(
        df["deal_year"].astype(str) + df["deal_month"].astype(str).str.zfill(2),
        format="%Y%m"
    )

    # 평형 라벨 (전용면적 → 가장 가까운 표준 평형)
    def _area_label(a):
        try:
            v = float(a)
        except (TypeError, ValueError):
            return "기타"
        if v < 45:   return f"{round(v)}㎡"
        if v < 63:   return "59㎡"
        if v < 75:   return "72㎡"
        if v < 100:  return "84㎡"
        if v < 130:  return "114㎡"
        return f"{round(v)}㎡"

    df["area_label"] = df["area"].apply(_area_label)
    return df


# ── 월별 집계 ──────────────────────────────────────────────────
def monthly_stats(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("ym")["eok"]
    return pd.DataFrame({
        "ym":     g.min().index,
        "min":    g.min().values,
        "avg":    g.mean().values,
        "max":    g.max().values,
        "count":  g.count().values,
    }).reset_index(drop=True)


# ── 차트 ──────────────────────────────────────────────────────
def make_chart(stats: pd.DataFrame, cname: str, color: str, height: int = 380) -> go.Figure:
    fig = go.Figure()

    # 범위 영역 (min~max)
    fig.add_trace(go.Scatter(
        x=pd.concat([stats["ym"], stats["ym"][::-1]]),
        y=pd.concat([stats["max"], stats["min"][::-1]]),
        fill="toself",
        fillcolor=_hex_to_rgba(color, 0.12),
        line=dict(color="rgba(0,0,0,0)"),
        hoverinfo="skip",
        showlegend=False,
        name="범위",
    ))

    # 평균선
    fig.add_trace(go.Scatter(
        x=stats["ym"], y=stats["avg"],
        mode="lines+markers",
        name="평균",
        line=dict(color=color, width=2),
        marker=dict(size=5),
        hovertemplate="%{x|%Y-%m}<br>평균 %{y:.2f}억<extra></extra>",
    ))

    # 최저선
    fig.add_trace(go.Scatter(
        x=stats["ym"], y=stats["min"],
        mode="lines",
        name="최저",
        line=dict(color=color, width=1.5, dash="dot"),
        hovertemplate="%{x|%Y-%m}<br>최저 %{y:.2f}억<extra></extra>",
    ))

    # 내 매수가 기준선 (실거주 단지만)
    if _is_my_apt(cname):
        fig.add_hline(
            y=MY_PRICE,
            line=dict(color="#e74c3c", width=1.5, dash="dash"),
            annotation_text=f"내 매수가 {MY_PRICE}억",
            annotation_position="top left",
            annotation_font_color="#e74c3c",
        )

    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=32, b=8),
        plot_bgcolor="white",
        paper_bgcolor="white",
        legend=dict(orientation="h", x=0, y=1.08, font=dict(size=11)),
        xaxis=dict(
            tickformat="%y.%m",
            showgrid=True, gridcolor="#f0f0f0",
            tickfont=dict(size=11),
        ),
        yaxis=dict(
            ticksuffix="억",
            showgrid=True, gridcolor="#f0f0f0",
            tickfont=dict(size=11),
        ),
        hovermode="x unified",
    )
    return fig


# ══════════════════════════════════════════════════════════════
# 페이지
# ══════════════════════════════════════════════════════════════
df_all = load_data()

st.title("실거래가 가격 추이")

if df_all.empty:
    st.warning("수집된 실거래가 데이터가 없습니다. 먼저 **🏛️ 국토부 실거래가** 메뉴에서 수집을 실행해주세요.")
    st.stop()

# ── 사이드바 ───────────────────────────────────────────────────
with st.sidebar:
    st.markdown("**단지 선택**")
    all_apts = sorted(df_all["apt_name"].unique())

    # 실거주 단지 우선
    priority = [a for a in all_apts if _is_my_apt(a)]
    rest     = [a for a in all_apts if a not in priority]
    apt_list = priority + rest

    selected = st.multiselect(
        "단지", apt_list, default=apt_list[:min(4, len(apt_list))],
        key="rtms_sel",
    )

    st.divider()
    st.markdown("**평형 필터**")
    all_areas = sorted(df_all["area_label"].unique())
    sel_areas = st.multiselect(
        "평형 (비우면 전체)", all_areas, default=[],
        key="rtms_area",
        placeholder="전체",
    )

    st.divider()
    st.markdown("**기간**")
    period = st.selectbox(
        "", ["전체", "최근 6개월", "최근 1년", "최근 2년"],
        index=2, key="rtms_period", label_visibility="collapsed",
    )

if not selected:
    st.info("왼쪽 사이드바에서 단지를 선택하세요.")
    st.stop()

# 기간 필터
cutoff = None
today = pd.Timestamp(date.today())
if period == "최근 6개월":
    cutoff = today - pd.DateOffset(months=6)
elif period == "최근 1년":
    cutoff = today - pd.DateOffset(months=12)
elif period == "최근 2년":
    cutoff = today - pd.DateOffset(months=24)

# ── KPI (실거주 단지) ──────────────────────────────────────────
_my_selected = next((a for a in selected if _is_my_apt(a)), None)
if _my_selected:
    dfc = df_all[df_all["apt_name"] == _my_selected]
    if sel_areas:
        dfc = dfc[dfc["area_label"].isin(sel_areas)]
    if cutoff is not None:
        dfc = dfc[dfc["ym"] >= cutoff]
    if not dfc.empty:
        stats = monthly_stats(dfc)
        if len(stats) >= 2:
            cur  = stats["avg"].iloc[-1]
            prev = stats["avg"].iloc[-2]
            delta = cur - prev
            cur_min = stats["min"].iloc[-1]

            st.markdown(f"### 🏠 {_my_selected}")
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("이번 달 평균", f"{cur:.2f}억", f"{delta:+.2f}억")
            k2.metric("이번 달 최저", f"{cur_min:.2f}억")
            k3.metric("내 매수가", f"{MY_PRICE:.2f}억", f"{cur_min - MY_PRICE:+.2f}억 (현 최저 기준)")
            k4.metric("거래 건수", f"{int(stats['count'].iloc[-1])}건")
            st.divider()

# ── 차트 그리기 ────────────────────────────────────────────────
COLS = 2
rows = [selected[i:i+COLS] for i in range(0, len(selected), COLS)]

for row in rows:
    cols = st.columns(len(row))
    for col, cname in zip(cols, row):
        with col:
            dfc = df_all[df_all["apt_name"] == cname].copy()
            if sel_areas:
                dfc = dfc[dfc["area_label"].isin(sel_areas)]
            if cutoff is not None:
                dfc = dfc[dfc["ym"] >= cutoff]

            color = PALETTE[apt_list.index(cname) % len(PALETTE)]

            if dfc.empty:
                st.markdown(f"**{cname}**")
                st.caption("해당 조건 데이터 없음")
                continue

            stats = monthly_stats(dfc)
            latest = stats.iloc[-1]
            delta_str = ""
            if len(stats) >= 2:
                d = stats["avg"].iloc[-1] - stats["avg"].iloc[-2]
                delta_str = f"  `{d:+.2f}억`"

            st.markdown(f"**{cname}**{delta_str}")
            area_info = " · ".join(dfc["area_label"].unique()) if len(dfc["area_label"].unique()) <= 4 else f"{len(dfc['area_label'].unique())}종"
            st.caption(f"{area_info}  |  최저 {latest['min']:.2f}억 · 평균 {latest['avg']:.2f}억 · 최고 {latest['max']:.2f}억")

            fig = make_chart(stats, cname, color)
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

# ── 요약 테이블 ────────────────────────────────────────────────
st.divider()
st.subheader("단지별 최근 거래 요약")

summary_rows = []
for cname in selected:
    dfc = df_all[df_all["apt_name"] == cname]
    if sel_areas:
        dfc = dfc[dfc["area_label"].isin(sel_areas)]
    if cutoff is not None:
        dfc = dfc[dfc["ym"] >= cutoff]
    if dfc.empty:
        continue
    latest_ym = dfc["ym"].max()
    latest    = dfc[dfc["ym"] == latest_ym]
    summary_rows.append({
        "단지명":   cname,
        "최근거래": latest_ym.strftime("%Y.%m"),
        "최저(억)": round(latest["eok"].min(), 2),
        "평균(억)": round(latest["eok"].mean(), 2),
        "최고(억)": round(latest["eok"].max(), 2),
        "거래건":   len(latest),
    })

if summary_rows:
    summary_df = pd.DataFrame(summary_rows).sort_values("최저(억)")
    st.dataframe(summary_df, use_container_width=True, hide_index=True)
