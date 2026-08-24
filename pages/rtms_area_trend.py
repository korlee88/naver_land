"""
pages/rtms_area_trend.py — 국토부 실거래가 기반 구/동 단위 가격동향 비교

단지별이 아니라 구/동(행정동) 단위로 실거래를 묶어 여러 지역을 나란히 비교한다.
데이터 출처는 구글시트에서 자동 복원되는 rtms_transactions 테이블 하나뿐이며
(pages/rtms_fetch.py의 국토부 API 수집 → 구글시트 백업 → app.py 자동복원 흐름),
이 페이지 자체는 API를 호출하지 않는다.
"""
import os
import sqlite3
from datetime import date

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from utils_style import inject_korean_font

inject_korean_font()

DB_PATH = os.environ.get("DB_PATH", "/tmp/naver_land.db")

PALETTE = [
    "#4C72B0", "#DD8452", "#55A868", "#C44E52",
    "#8172B2", "#937860", "#DA8BC3", "#8C8C8C",
    "#CCB974", "#64B5CD",
]

# lawd_cd → (시, 구) 계층 매핑 — pages/rtms_chart.py와 동일
LAWD_HIER: dict[str, tuple[str, str | None]] = {
    "41220": ("경기 평택시", None),
    "43113": ("충북 청주시", "흥덕구"),
    "43114": ("충북 청주시", "청원구"),
}


def _hex_to_rgba(hex_color: str, alpha: float = 0.12) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _lawd_label(code: str) -> str:
    si, gu = LAWD_HIER.get(str(code), (str(code), None))
    return f"{si} {gu}" if gu else si


# ── 데이터 로드 (구글시트 → 자동복원된 로컬 rtms_transactions) ──
@st.cache_data(ttl=300)
def load_data() -> pd.DataFrame:
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        df = pd.read_sql("""
            SELECT lawd_cd, apt_name, dong, deal_year, deal_month, deal_day,
                   area, floor, price_man, cancel_yn
            FROM rtms_transactions
            ORDER BY deal_year, deal_month, deal_day
        """, conn)
        conn.close()
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return df
    df = df[df["cancel_yn"].isna() | (df["cancel_yn"] != "O")].copy()
    df["eok"] = df["price_man"] / 10000
    df["ym"] = pd.to_datetime(
        df["deal_year"].astype(str) + df["deal_month"].astype(str).str.zfill(2),
        format="%Y%m"
    )
    return df


def monthly_stats(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("ym")["eok"]
    stats = pd.DataFrame({
        "ym":    g.min().index,
        "min":   g.min().values,
        "avg":   g.mean().values,
        "max":   g.max().values,
        "count": g.count().values,
    }).reset_index(drop=True)
    stats["ma3"] = stats["avg"].rolling(3, min_periods=2).mean()
    return stats


def trend_signal(stats: pd.DataFrame) -> tuple[str, str, str]:
    """최근 3개월 vs 이전 3개월 평균 비교. 반환: (이모지, 설명, 색상)"""
    if len(stats) < 4:
        return "─", "데이터 부족", "#888"
    n = len(stats)
    recent = stats["avg"].iloc[max(n - 3, 0):].mean()
    prev = stats["avg"].iloc[max(n - 6, 0):max(n - 3, 0)].mean()
    if prev == 0:
        return "─", "보합", "#f39c12"
    pct = (recent - prev) / prev * 100
    if pct >= 2:
        return "🔺", f"상승세 (+{pct:.1f}%)", "#27ae60"
    elif pct <= -2:
        return "🔻", f"하락세 ({pct:.1f}%)", "#e74c3c"
    else:
        return "➡️", f"보합 ({pct:+.1f}%)", "#f39c12"


def make_chart(stats: pd.DataFrame, color: str) -> go.Figure:
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.72, 0.28], vertical_spacing=0.04,
        subplot_titles=["가격(억)", ""],
    )
    fig.add_trace(go.Scatter(
        x=pd.concat([stats["ym"], stats["ym"][::-1]]),
        y=pd.concat([stats["max"], stats["min"][::-1]]),
        fill="toself", fillcolor=_hex_to_rgba(color, 0.10),
        line=dict(color="rgba(0,0,0,0)"), hoverinfo="skip",
        showlegend=False, name="범위",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=stats["ym"], y=stats["min"], name="최저",
        line=dict(color=color, width=1.5, dash="dot"),
        hovertemplate="%{x|%Y-%m} 최저 %{y:.2f}억<extra></extra>",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=stats["ym"], y=stats["avg"], name="평균",
        line=dict(color=color, width=2.5), marker=dict(size=5),
        hovertemplate="%{x|%Y-%m} 평균 %{y:.2f}억<extra></extra>",
    ), row=1, col=1)
    if stats["ma3"].notna().sum() >= 2:
        fig.add_trace(go.Scatter(
            x=stats["ym"], y=stats["ma3"], name="3개월 MA",
            line=dict(color="#888", width=1.5, dash="dash"),
            hovertemplate="%{x|%Y-%m} MA3 %{y:.2f}억<extra></extra>",
        ), row=1, col=1)
    vol_colors = [
        _hex_to_rgba(color, 0.8) if c >= stats["count"].median() else _hex_to_rgba(color, 0.4)
        for c in stats["count"]
    ]
    fig.add_trace(go.Bar(
        x=stats["ym"], y=stats["count"], name="거래건수",
        marker_color=vol_colors,
        hovertemplate="%{x|%Y-%m} %{y}건<extra></extra>",
    ), row=2, col=1)
    fig.update_layout(
        height=340,
        margin=dict(l=8, r=8, t=24, b=8),
        plot_bgcolor="white", paper_bgcolor="white",
        legend=dict(orientation="h", x=0, y=1.08, font=dict(size=10)),
        hovermode="x unified",
    )
    fig.update_xaxes(tickformat="%y.%m", showgrid=True, gridcolor="#f0f0f0", tickfont=dict(size=10))
    fig.update_yaxes(tickfont=dict(size=10), showgrid=True, gridcolor="#f0f0f0")
    fig.update_yaxes(ticksuffix="억", row=1)
    fig.update_yaxes(title_text="건", row=2, title_font=dict(size=9))
    return fig


def _pick_one(label: str, options: list[str], key: str, default: str | None = None) -> str:
    default = default if default in options else options[0]
    if hasattr(st, "segmented_control"):
        sel = st.segmented_control(label, options, default=default, key=key)
        return sel or default
    return st.radio(label, options, horizontal=True, key=key, index=options.index(default))


# ══════════════════════════════════════════════════════════════
# 페이지
# ══════════════════════════════════════════════════════════════
st.title("지역별 가격동향 비교")
st.caption(
    "국토부 실거래가(매매) 기준 — 단지 하나가 아니라 **구/동 전체를 합친** 시세 추이를 "
    "여러 지역 나란히 비교합니다. 단지별 상세 비교는 **가격 추이** 메뉴를 이용하세요."
)

df_all = load_data()
if df_all.empty:
    st.warning("수집된 실거래가 데이터가 없습니다. 먼저 **🏛️ 실거래가 수집** 메뉴에서 수집을 실행해주세요.")
    st.stop()

# ── 사이드바 ───────────────────────────────────────────────────
with st.sidebar:
    st.markdown("**비교 단위**")
    unit_level = _pick_one("단위", ["구/시 단위", "동 단위"], "area_unit_level", default="동 단위")

    df_all["region_gu"] = df_all["lawd_cd"].apply(_lawd_label)
    if unit_level == "구/시 단위":
        df_all["region_key"] = df_all["region_gu"]
    else:
        df_all["region_key"] = df_all["region_gu"] + " " + df_all["dong"].fillna("(동 미상)")

    region_options = sorted(df_all["region_key"].dropna().unique())

    st.markdown("**지역 선택 (나란히 비교)**")
    default_regions = (
        [r for r in region_options if "동삭동" in r]
        or region_options[:min(4, len(region_options))]
    )
    if "area_region_sel" in st.session_state:
        st.session_state.area_region_sel = [
            r for r in st.session_state.area_region_sel if r in region_options
        ]
    selected_regions = st.multiselect(
        "지역", region_options, default=default_regions, key="area_region_sel",
    )
    st.divider()

    st.markdown("**평형 필터**")
    PYEONG = 3.3058
    area_max = float(df_all["area"].max())
    AREA_BUCKETS = {
        "전체":      (0.0, area_max + 1),
        "10평대":    (10 * PYEONG, 15 * PYEONG),
        "15평대":    (15 * PYEONG, 20 * PYEONG),
        "20평대":    (20 * PYEONG, 25 * PYEONG),
        "25평대":    (25 * PYEONG, 30 * PYEONG),
        "30평대":    (30 * PYEONG, 35 * PYEONG),
        "35평 이상": (35 * PYEONG, area_max + 1),
    }
    sel_area = _pick_one("평형", list(AREA_BUCKETS.keys()), "area_area_bucket", default="전체")
    lo, hi = AREA_BUCKETS[sel_area]
    st.divider()

    st.markdown("**기간**")
    period = st.selectbox(
        "", ["전체", "최근 6개월", "최근 1년", "최근 2년"],
        index=0, key="area_period", label_visibility="collapsed",
    )

if not selected_regions:
    st.info("왼쪽 사이드바에서 비교할 지역을 선택하세요.")
    st.stop()

cutoff = None
today = pd.Timestamp(date.today())
if period == "최근 6개월":
    cutoff = today - pd.DateOffset(months=6)
elif period == "최근 1년":
    cutoff = today - pd.DateOffset(months=12)
elif period == "최근 2년":
    cutoff = today - pd.DateOffset(months=24)


def _filter(region_key: str) -> pd.DataFrame:
    dfc = df_all[df_all["region_key"] == region_key].copy()
    dfc = dfc[(dfc["area"] >= lo) & (dfc["area"] < hi)]
    if cutoff is not None:
        dfc = dfc[dfc["ym"] >= cutoff]
    return dfc


# ── 종합 비교 차트 (평균가 라인 오버레이) ─────────────────────
st.subheader("종합 비교 — 평균가 추이")
fig_overlay = go.Figure()
region_stats: dict[str, pd.DataFrame] = {}
for i, region in enumerate(selected_regions):
    dfc = _filter(region)
    if dfc.empty:
        continue
    stats = monthly_stats(dfc)
    region_stats[region] = stats
    color = PALETTE[i % len(PALETTE)]
    fig_overlay.add_trace(go.Scatter(
        x=stats["ym"], y=stats["avg"], name=region,
        line=dict(color=color, width=2.5), marker=dict(size=5),
        hovertemplate=f"{region}<br>" + "%{x|%Y-%m} 평균 %{y:.2f}억<extra></extra>",
    ))
fig_overlay.update_layout(
    height=340,
    margin=dict(l=8, r=8, t=8, b=8),
    plot_bgcolor="white", paper_bgcolor="white",
    legend=dict(orientation="h", x=0, y=1.1, font=dict(size=11)),
    hovermode="x unified",
)
fig_overlay.update_xaxes(tickformat="%y.%m", showgrid=True, gridcolor="#f0f0f0")
fig_overlay.update_yaxes(ticksuffix="억", showgrid=True, gridcolor="#f0f0f0")
st.plotly_chart(fig_overlay, use_container_width=True, config={"displayModeBar": False})

st.divider()

# ── 지역별 상세 카드 (2열) ────────────────────────────────────
st.subheader("지역별 상세")
COLS = 2
rows_layout = [selected_regions[i:i + COLS] for i in range(0, len(selected_regions), COLS)]

for row in rows_layout:
    cols = st.columns(len(row))
    for col, region in zip(cols, row):
        with col:
            dfc = _filter(region)
            color = PALETTE[selected_regions.index(region) % len(PALETTE)]
            if dfc.empty:
                st.markdown(f"**{region}**")
                st.caption("해당 조건 데이터 없음")
                continue
            stats = region_stats.get(region) if region in region_stats else monthly_stats(dfc)
            latest = stats.iloc[-1]
            emoji, trend_txt, trend_color = trend_signal(stats)
            n_complex = dfc["apt_name"].nunique()
            st.markdown(
                f"**{region}** &nbsp; "
                f"<span style='color:{trend_color};font-size:13px'>{emoji} {trend_txt}</span>",
                unsafe_allow_html=True,
            )
            st.caption(
                f"포함 단지 {n_complex}개  |  "
                f"최저 {latest['min']:.2f}억 · 평균 {latest['avg']:.2f}억 · 최고 {latest['max']:.2f}억"
            )
            fig = make_chart(stats, color)
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

# ── 요약 테이블 ────────────────────────────────────────────────
st.divider()
st.subheader("지역별 최근 거래 요약")

summary_rows = []
for region in selected_regions:
    dfc = _filter(region)
    if dfc.empty:
        continue
    stats = monthly_stats(dfc)
    latest_ym = dfc["ym"].max()
    latest = dfc[dfc["ym"] == latest_ym]
    emoji, trend_txt, _ = trend_signal(stats)
    summary_rows.append({
        "지역":     region,
        "트렌드":   f"{emoji} {trend_txt}",
        "최근거래": latest_ym.strftime("%Y.%m"),
        "최저(억)": round(latest["eok"].min(), 2),
        "평균(억)": round(latest["eok"].mean(), 2),
        "최고(억)": round(latest["eok"].max(), 2),
        "거래건수": len(latest),
        "포함단지": dfc["apt_name"].nunique(),
    })

if summary_rows:
    summary_df = pd.DataFrame(summary_rows).sort_values("평균(억)")
    st.dataframe(summary_df, use_container_width=True, hide_index=True)
