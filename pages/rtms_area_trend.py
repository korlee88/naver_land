"""
pages/rtms_area_trend.py — 국토부 실거래가 기반 구/동 단위 가격동향 비교

단지별이 아니라 구/동(행정동) 단위로 실거래를 묶어 여러 지역을 나란히 비교한다.
데이터 출처는 구글시트에서 자동 복원되는 rtms_transactions / rtms_jeonse 테이블뿐이며
(pages/rtms_fetch.py의 국토부 API 수집 → 구글시트 백업 → app.py 자동복원 흐름),
이 페이지 자체는 API를 호출하지 않는다.

주의: rtms_jeonse에는 행정동(dong) 컬럼이 없어 시/구(lawd_cd) 단위로만 구분 가능하다.
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
JEONSE_COLOR = "#55A868"

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


# ── 데이터 로드 (구글시트 → 자동복원된 로컬 DB) ────────────────
@st.cache_data(ttl=300)
def load_data() -> pd.DataFrame:
    """매매 실거래 (rtms_transactions)"""
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
    # 매매는 실거래 신고일(deal_day)까지 있어 주 단위 집계가 가능
    df["date"] = pd.to_datetime(
        df["deal_year"].astype(str) + "-" +
        df["deal_month"].astype(str).str.zfill(2) + "-" +
        df["deal_day"].astype(str).str.zfill(2),
        errors="coerce",
    )
    df = df.dropna(subset=["date"])
    return df


@st.cache_data(ttl=300)
def load_jeonse() -> pd.DataFrame:
    """전월세 (rtms_jeonse) 중 순수 전세(월세 없는 보증금만) 거래만. dong 컬럼이 없어 시/구 단위만 가능."""
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        df = pd.read_sql("""
            SELECT lawd_cd, apt_name, deal_year, deal_month, area, deposit_man, monthly_rent
            FROM rtms_jeonse
            ORDER BY deal_year, deal_month
        """, conn)
        conn.close()
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return df
    df = df[df["monthly_rent"].fillna(0) == 0].copy()
    if df.empty:
        return df
    df["deposit_eok"] = df["deposit_man"] / 10000
    df["ym"] = pd.to_datetime(
        df["deal_year"].astype(str) + df["deal_month"].astype(str).str.zfill(2),
        format="%Y%m"
    )
    return df


def monthly_stats(df: pd.DataFrame, col: str = "eok") -> pd.DataFrame:
    g = df.groupby("ym")[col]
    stats = pd.DataFrame({
        "ym":    g.min().index,
        "min":   g.min().values,
        "avg":   g.mean().values,
        "max":   g.max().values,
        "count": g.count().values,
    }).reset_index(drop=True)
    stats["ma"] = stats["avg"].rolling(3, min_periods=2).mean()
    return stats


def weekly_stats(df: pd.DataFrame, col: str = "eok", ma_window: int = 4) -> pd.DataFrame:
    """주(월요일 시작) 단위 집계. 컬럼 구성은 monthly_stats와 동일하게 맞춰 재사용(ym에는 그 주의 월요일 날짜가 담김)."""
    d = df.copy()
    d["ym"] = d["date"] - pd.to_timedelta(d["date"].dt.dayofweek, unit="D")
    g = d.groupby("ym")[col]
    stats = pd.DataFrame({
        "ym":    g.min().index,
        "min":   g.min().values,
        "avg":   g.mean().values,
        "max":   g.max().values,
        "count": g.count().values,
    }).reset_index(drop=True)
    stats["ma"] = stats["avg"].rolling(ma_window, min_periods=2).mean()
    return stats


def trend_signal(stats: pd.DataFrame, window: int = 3) -> tuple[str, str, str]:
    """최근 window구간 vs 이전 window구간 평균 비교. 반환: (이모지, 설명, 색상)"""
    if len(stats) < window + 1:
        return "─", "데이터 부족", "#888"
    n = len(stats)
    recent = stats["avg"].iloc[max(n - window, 0):].mean()
    prev = stats["avg"].iloc[max(n - 2 * window, 0):max(n - window, 0)].mean()
    if not prev:
        return "─", "보합", "#f39c12"
    pct = (recent - prev) / prev * 100
    if pct >= 2:
        return "🔺", f"상승세 (+{pct:.1f}%)", "#27ae60"
    elif pct <= -2:
        return "🔻", f"하락세 ({pct:.1f}%)", "#e74c3c"
    else:
        return "➡️", f"보합 ({pct:+.1f}%)", "#f39c12"


def _price_band_traces(fig, stats, color, row, name_min="최저", name_avg="평균",
                        ma_label="이동평균", date_fmt="%Y-%m"):
    fig.add_trace(go.Scatter(
        x=pd.concat([stats["ym"], stats["ym"][::-1]]),
        y=pd.concat([stats["max"], stats["min"][::-1]]),
        fill="toself", fillcolor=_hex_to_rgba(color, 0.10),
        line=dict(color="rgba(0,0,0,0)"), hoverinfo="skip",
        showlegend=False, name="범위",
    ), row=row, col=1)
    fig.add_trace(go.Scatter(
        x=stats["ym"], y=stats["min"], name=name_min,
        line=dict(color=color, width=1.5, dash="dot"),
        hovertemplate=f"%{{x|{date_fmt}}} {name_min} " + "%{y:.2f}억<extra></extra>",
    ), row=row, col=1)
    fig.add_trace(go.Scatter(
        x=stats["ym"], y=stats["avg"], name=name_avg,
        line=dict(color=color, width=2.5), marker=dict(size=5),
        hovertemplate=f"%{{x|{date_fmt}}} {name_avg} " + "%{y:.2f}억<extra></extra>",
    ), row=row, col=1)
    if stats["ma"].notna().sum() >= 2:
        fig.add_trace(go.Scatter(
            x=stats["ym"], y=stats["ma"], name=ma_label,
            line=dict(color="#888", width=1.5, dash="dash"),
            hovertemplate=f"%{{x|{date_fmt}}} {ma_label} " + "%{y:.2f}억<extra></extra>",
        ), row=row, col=1)


def _volume_bar_trace(fig, stats, color, row, name="거래건수", date_fmt="%Y-%m"):
    vol_colors = [
        _hex_to_rgba(color, 0.8) if c >= stats["count"].median() else _hex_to_rgba(color, 0.4)
        for c in stats["count"]
    ]
    fig.add_trace(go.Bar(
        x=stats["ym"], y=stats["count"], name=name,
        marker_color=vol_colors,
        hovertemplate=f"%{{x|{date_fmt}}} " + "%{y}건<extra></extra>",
    ), row=row, col=1)


def make_chart(
    stats: pd.DataFrame, color: str, *,
    price_title: str = "가격(억)", vol_name: str = "거래건수",
    min_label: str = "최저", avg_label: str = "평균",
    ma_label: str = "이동평균", date_fmt: str = "%Y-%m",
) -> go.Figure:
    """가격(밴드+평균+이동평균)/거래량 2단 차트 1개. 확대·이동 불가(고정형).
    매매·전세를 하나의 차트에 욱여넣으면 범례가 제목과 겹쳐 매매용/전세용을 각각 별도로 그린다."""
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.7, 0.3], vertical_spacing=0.06,
        subplot_titles=[price_title, ""],
    )
    _price_band_traces(fig, stats, color, row=1, name_min=min_label, name_avg=avg_label,
                        ma_label=ma_label, date_fmt=date_fmt)
    _volume_bar_trace(fig, stats, color, row=2, name=vol_name, date_fmt=date_fmt)

    fig.update_layout(
        height=380,
        margin=dict(l=8, r=8, t=32, b=8),
        plot_bgcolor="white", paper_bgcolor="white",
        legend=dict(orientation="h", x=0, y=1.14, font=dict(size=10)),
        hovermode="x unified",
    )
    fig.update_xaxes(
        tickformat="%y.%m", showgrid=True, gridcolor="#f0f0f0",
        tickfont=dict(size=10), fixedrange=True,
    )
    fig.update_yaxes(tickfont=dict(size=10), showgrid=True, gridcolor="#f0f0f0", fixedrange=True)
    # 가격 행은 이 지역 자체의 최저~최고에 딱 맞춘 여백만 둬서 등락이 눌려 보이지 않게 함
    p_lo, p_hi = float(stats["min"].min()), float(stats["max"].max())
    pad = max((p_hi - p_lo) * 0.10, 0.03)
    fig.update_yaxes(ticksuffix="억", range=[p_lo - pad, p_hi + pad], row=1)
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
    "국토부 실거래가 기준 — 단지 하나가 아니라 **구/동 전체를 합친** 매매·전세 시세와 거래량 추이를 "
    "여러 지역 나란히 비교합니다. 단지별 상세 비교는 **가격 추이** 메뉴를 이용하세요. "
    "매매는 **주 단위**, 전세는 국토부 데이터에 일자 정보가 없어 **월 단위**로 집계됩니다."
)

df_all = load_data()
if df_all.empty:
    st.warning("수집된 실거래가 데이터가 없습니다. 먼저 **🏛️ 실거래가 수집** 메뉴에서 수집을 실행해주세요.")
    st.stop()

df_jeonse_all = load_jeonse()

# ── 사이드바 ───────────────────────────────────────────────────
with st.sidebar:
    st.markdown("**비교 단위**")
    unit_level = _pick_one("단위", ["구/시 단위", "동 단위"], "area_unit_level", default="동 단위")
    if unit_level == "동 단위" and not df_jeonse_all.empty:
        st.caption("ℹ️ 전세는 행정동 구분이 없어 같은 시/구 전체 기준으로 표시됩니다.")

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


def _filter_jeonse(lawd_codes: list[str]) -> pd.DataFrame:
    if df_jeonse_all.empty:
        return df_jeonse_all
    jdf = df_jeonse_all[df_jeonse_all["lawd_cd"].isin(lawd_codes)].copy()
    jdf = jdf[(jdf["area"] >= lo) & (jdf["area"] < hi)]
    if cutoff is not None:
        jdf = jdf[jdf["ym"] >= cutoff]
    return jdf


# ── 종합 비교 차트 (매매 평균가 라인 오버레이) ─────────────────
st.subheader("종합 비교 — 매매 평균가 추이")
compare_mode = _pick_one(
    "표시 방식", ["변동률(%)", "절대가격(억)"], "area_compare_mode", default="변동률(%)",
)
if compare_mode == "변동률(%)":
    st.caption("ℹ️ 지역마다 가격대가 달라 절대가격으로 겹쳐 보면 등락이 눌려 보입니다 — 각 지역의 첫 주를 100으로 놓고 변동률로 비교합니다.")

fig_overlay = go.Figure()
region_stats: dict[str, pd.DataFrame] = {}
for i, region in enumerate(selected_regions):
    dfc = _filter(region)
    if dfc.empty:
        continue
    stats = weekly_stats(dfc)
    region_stats[region] = stats
    color = PALETTE[i % len(PALETTE)]
    if compare_mode == "변동률(%)":
        base = stats["avg"].iloc[0]
        y_vals = stats["avg"] / base * 100 if base else stats["avg"]
        hover = f"{region}<br>" + "%{x|%Y-%m-%d} %{y:.1f} (시작주=100)<extra></extra>"
    else:
        y_vals = stats["avg"]
        hover = f"{region}<br>" + "%{x|%Y-%m-%d} 평균 %{y:.2f}억<extra></extra>"
    fig_overlay.add_trace(go.Scatter(
        x=stats["ym"], y=y_vals, name=region,
        line=dict(color=color, width=2), marker=dict(size=4),
        hovertemplate=hover,
    ))
fig_overlay.update_layout(
    height=380,
    margin=dict(l=8, r=8, t=8, b=8),
    plot_bgcolor="white", paper_bgcolor="white",
    legend=dict(orientation="h", x=0, y=1.1, font=dict(size=11)),
    hovermode="x unified",
)
fig_overlay.update_xaxes(tickformat="%y.%m", showgrid=True, gridcolor="#f0f0f0", fixedrange=True)
if compare_mode == "변동률(%)":
    fig_overlay.add_hline(y=100, line=dict(color="#999", width=1, dash="dot"))
    fig_overlay.update_yaxes(title_text="변동률 (시작주=100)", showgrid=True, gridcolor="#f0f0f0", fixedrange=True)
else:
    fig_overlay.update_yaxes(ticksuffix="억", showgrid=True, gridcolor="#f0f0f0", fixedrange=True)
st.plotly_chart(fig_overlay, use_container_width=True, config={"displayModeBar": False, "scrollZoom": False, "staticPlot": False})

st.divider()

# ── 지역별 상세 카드 (2열 · 매매+전세+거래량) ──────────────────
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
            stats = region_stats.get(region) if region in region_stats else weekly_stats(dfc)
            latest = stats.iloc[-1]
            emoji, trend_txt, trend_color = trend_signal(stats, window=4)
            n_complex = dfc["apt_name"].nunique()

            lawd_codes = dfc["lawd_cd"].unique().tolist()
            jdf = _filter_jeonse(lawd_codes)
            jeonse_stats = monthly_stats(jdf, col="deposit_eok") if not jdf.empty else None

            st.markdown(
                f"**{region}** &nbsp; "
                f"<span style='color:{trend_color};font-size:13px'>{emoji} {trend_txt}</span>",
                unsafe_allow_html=True,
            )
            cap = (
                f"포함 단지 {n_complex}개  |  "
                f"매매 최저 {latest['min']:.2f}억 · 평균 {latest['avg']:.2f}억 · 최고 {latest['max']:.2f}억"
            )
            if jeonse_stats is not None:
                j_latest = jeonse_stats.iloc[-1]
                cap += f"  ·  전세 평균 {j_latest['avg']:.2f}억"
            st.caption(cap)

            fig = make_chart(
                stats, color, price_title="매매가(억) · 주 단위", vol_name="매매건수",
                ma_label="4주 이동평균", date_fmt="%Y-%m-%d",
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False, "scrollZoom": False, "staticPlot": False})

            if jeonse_stats is not None:
                fig_j = make_chart(
                    jeonse_stats, JEONSE_COLOR,
                    price_title="전세가(억) · 월 단위", vol_name="전세건수",
                    min_label="전세최저", avg_label="전세평균", ma_label="3개월 이동평균",
                )
                st.plotly_chart(fig_j, use_container_width=True, config={"displayModeBar": False, "scrollZoom": False, "staticPlot": False})

# ── 요약 테이블 ────────────────────────────────────────────────
st.divider()
st.subheader("지역별 최근 거래 요약")

summary_rows = []
for region in selected_regions:
    dfc = _filter(region)
    if dfc.empty:
        continue
    stats = region_stats.get(region) if region in region_stats else weekly_stats(dfc)
    latest_ym = dfc["ym"].max()
    latest = dfc[dfc["ym"] == latest_ym]
    emoji, trend_txt, _ = trend_signal(stats, window=4)
    row_dict = {
        "지역":       region,
        "트렌드":     f"{emoji} {trend_txt}",
        "최근거래":   latest_ym.strftime("%Y.%m"),
        "매매최저(억)": round(latest["eok"].min(), 2),
        "매매평균(억)": round(latest["eok"].mean(), 2),
        "매매최고(억)": round(latest["eok"].max(), 2),
        "매매건수":   len(latest),
        "포함단지":   dfc["apt_name"].nunique(),
    }
    lawd_codes = dfc["lawd_cd"].unique().tolist()
    jdf = _filter_jeonse(lawd_codes)
    if not jdf.empty:
        j_latest_ym = jdf["ym"].max()
        j_latest = jdf[jdf["ym"] == j_latest_ym]
        row_dict["전세평균(억)"] = round(j_latest["deposit_eok"].mean(), 2)
        row_dict["전세건수"] = len(j_latest)
    else:
        row_dict["전세평균(억)"] = None
        row_dict["전세건수"] = None
    summary_rows.append(row_dict)

if summary_rows:
    summary_df = pd.DataFrame(summary_rows).sort_values("매매평균(억)")
    st.dataframe(summary_df, use_container_width=True, hide_index=True)
