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
    "41550": ("경기 안성시", None),
    "41370": ("경기 오산시", None),
    "41591": ("경기 화성시", "만세구"),
    "41593": ("경기 화성시", "효행구"),
    "41595": ("경기 화성시", "병점구"),
    "41597": ("경기 화성시", "동탄구"),
    "41111": ("경기 수원시", "장안구"),
    "41113": ("경기 수원시", "권선구"),
    "41115": ("경기 수원시", "팔달구"),
    "41117": ("경기 수원시", "영통구"),
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


KOSIS_CAT_LABEL = {"population": "인구·세대수", "housing": "주택 인허가(전체유형)", "business": "가동사업자수"}
KOSIS_CAT_ICON = {"population": "👥", "housing": "🏗", "business": "🏢"}
# 범례가 길어지면 차트 위를 여러 줄로 덮어 본문을 밀어내므로 범례에는 짧은 이름을 쓴다
KOSIS_CAT_SHORT = {"population": "인구", "housing": "주택인허가", "business": "사업자수"}

# 지수 차트 색상 — 색은 "지표"라는 엔티티를 따르므로 지역이 바뀌어도 같은 지표는 같은 색.
# 검증된 카테고리 팔레트 슬롯 1~4(blue/orange/aqua/yellow) 순서를 그대로 쓴다.
INDEX_COLOR_PRICE = "#2a78d6"
KOSIS_CAT_COLOR = {"population": "#eb6834", "housing": "#1baf7a", "business": "#eda100"}
GRID_INK, AXIS_INK, MUTED_INK = "#e1e0d9", "#c3c2b7", "#898781"


@st.cache_data(ttl=300)
def load_kosis() -> pd.DataFrame:
    """KOSIS 통계 (pages/kosis_fetch.py가 수집한 kosis_stats). 시군구 단위 연도별 값."""
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        df = pd.read_sql("""
            SELECT category, region_name, sub_label, unit_name, prd_de, value
            FROM kosis_stats
        """, conn)
        conn.close()
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return df
    df["year"] = pd.to_numeric(df["prd_de"], errors="coerce")
    df = df.dropna(subset=["year"])
    df["year"] = df["year"].astype(int)
    return df


def _prefer_total_sub(df: pd.DataFrame) -> pd.DataFrame:
    """세부구분(성별/산업분류 등)이 있으면 '계/전체/합계' 같은 총계 행만 남긴다."""
    subs = [s for s in df["sub_label"].dropna().unique() if s]
    if not subs:
        return df
    total_like = [s for s in subs if s in ("계", "소계", "전체", "합계")]
    keep = total_like[0] if total_like else subs[0]
    return df[df["sub_label"].isna() | (df["sub_label"] == keep)]


def _kosis_city_keyword(region_key: str) -> tuple[str, str | None]:
    """'경기 화성시 동탄구' → ('화성시', '동탄구'). 시/군 단위면 구는 None."""
    parts = region_key.split(" ")
    city = next((p for p in parts if p.endswith("시") or p.endswith("군")), parts[-1])
    gu = next((p for p in parts if p.endswith("구") and p != city), None)
    return city, gu


def _match_kosis_region(city: str, gu: str | None, kosis_regions: list[str]) -> str | None:
    """rtms 지역명(city/gu)에 가장 가까운 KOSIS region_name을 찾는다.
    KOSIS 지역명의 정확한 표기(공백 유무 등)를 확신할 수 없어 부분일치로 매칭한다."""
    if gu:
        combo = [r for r in kosis_regions if city in r and gu in r]
        if combo:
            return sorted(combo, key=len)[0]
    exact = [r for r in kosis_regions if r == city]
    if exact:
        return exact[0]
    contains = [r for r in kosis_regions if city in r]
    if contains:
        return sorted(contains, key=len)[0]  # 가장 짧은 = 시/군 전체 집계로 추정
    return None


def _kosis_summary(cat_df: pd.DataFrame, region_name: str) -> dict | None:
    dfc = cat_df[cat_df["region_name"] == region_name].sort_values("year")
    dfc = _prefer_total_sub(dfc)
    if dfc.empty:
        return None
    dfc = dfc.groupby("year", as_index=False)["value"].sum()
    latest = dfc.iloc[-1]
    yoy = None
    if len(dfc) >= 2:
        prev = dfc.iloc[-2]
        if prev["value"]:
            yoy = (latest["value"] - prev["value"]) / prev["value"] * 100
    return {"df": dfc, "latest_value": latest["value"], "yoy": yoy}


def _price_year_series(dfc: pd.DataFrame) -> pd.DataFrame:
    """지역 매매 실거래(dfc, eok/ym 컬럼)를 KOSIS와 맞춰 연도별 평균가로 집계."""
    d = dfc.assign(year=dfc["ym"].dt.year)
    return d.groupby("year", as_index=False)["eok"].mean().rename(columns={"eok": "price"})


def _price_kosis_corr(dfc: pd.DataFrame, kosis_yearly: pd.DataFrame) -> tuple[float | None, int]:
    """연도별 매매평균가 vs KOSIS 연도별 값의 피어슨 상관계수. 반환: (r 또는 None, 겹치는 연도 수)."""
    if dfc.empty or kosis_yearly.empty:
        return None, 0
    price_yr = _price_year_series(dfc)
    merged = pd.merge(price_yr, kosis_yearly.rename(columns={"value": "kosis"}), on="year", how="inner")
    if len(merged) < 3:
        return None, len(merged)
    r = merged["price"].corr(merged["kosis"])
    return (None if pd.isna(r) else float(r)), len(merged)


def _corr_label(r: float) -> tuple[str, str]:
    strength = "강한" if abs(r) >= 0.7 else "중간" if abs(r) >= 0.4 else "약한" if abs(r) >= 0.2 else "거의 없는"
    direction = "양의" if r >= 0 else "음의"
    color = "#27ae60" if r >= 0.2 else "#e74c3c" if r <= -0.2 else "#888"
    return f"{strength} {direction} 상관 (r={r:+.2f})", color


def _rebase_to_100(df: pd.DataFrame, value_col: str, base_year: int) -> pd.DataFrame | None:
    """base_year 값을 100으로 놓고 지수화. 기준값이 없거나 0이면 None."""
    d = df[df["year"] >= base_year].sort_values("year")
    if len(d) < 2:
        return None
    at_base = d.loc[d["year"] == base_year, value_col]
    base = at_base.iloc[0] if not at_base.empty else d[value_col].iloc[0]
    if not base:
        return None
    return pd.DataFrame({"year": d["year"].values, "idx": d[value_col].values / base * 100})


def _indexed_trend_chart(price_yearly: pd.DataFrame, kosis_series: dict) -> go.Figure | None:
    """매매평균가와 KOSIS 지표를 '기준연도=100' 지수로 바꿔 하나의 축에 겹쳐 그린다.

    축을 두 개 쓰면(이중축) 두 축의 정렬이 임의적이라 실제로는 없는 상관관계를 만들어 보여준다.
    단위가 다른 계열을 한 그림에서 비교하는 표준 해법은 공통 기준연도로 지수화하는 것이다.
    """
    tracks = [("price", "매매가", price_yearly, "price", INDEX_COLOR_PRICE, None)]
    for cat_key, info in kosis_series.items():
        tracks.append((
            cat_key, KOSIS_CAT_SHORT.get(cat_key, cat_key), info["df"], "value",
            KOSIS_CAT_COLOR.get(cat_key, MUTED_INK), info.get("r"),
        ))
    tracks = [t for t in tracks if not t[2].empty]
    if not tracks:
        return None

    # 모든 계열이 값을 갖는 첫 해를 공통 기준연도로 삼아야 출발점이 같아 비교가 공정하다
    base_year = max(int(t[2]["year"].min()) for t in tracks)

    fig, plotted = go.Figure(), 0
    for key, label, df, col, color, r in tracks:
        idx = _rebase_to_100(df, col, base_year)
        if idx is None:
            continue
        is_price = key == "price"
        fig.add_trace(go.Scatter(
            x=idx["year"], y=idx["idx"],
            name=label if r is None else f"{label} (r={r:+.2f})",
            mode="lines+markers",
            line=dict(color=color, width=2.5 if is_price else 1.8),
            marker=dict(size=8 if is_price else 7),
            hovertemplate=f"{label} " + "%{y:.1f}<extra></extra>",
        ))
        plotted += 1
    if not plotted:
        return None

    fig.add_hline(y=100, line=dict(color=AXIS_INK, width=1))
    fig.update_layout(
        height=250, margin=dict(l=6, r=6, t=6, b=6),
        plot_bgcolor="white", paper_bgcolor="white",
        legend=dict(orientation="h", x=0, y=1.18, font=dict(size=10)),
        hovermode="x unified",
    )
    fig.update_xaxes(dtick=1, tickfont=dict(size=10, color=MUTED_INK),
                      showgrid=True, gridcolor=GRID_INK, linecolor=AXIS_INK, fixedrange=True)
    fig.update_yaxes(title_text=f"{base_year}년=100", title_font=dict(size=10, color=MUTED_INK),
                      tickfont=dict(size=10, color=MUTED_INK),
                      showgrid=True, gridcolor=GRID_INK, linecolor=AXIS_INK, fixedrange=True)
    return fig


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
        row_heights=[0.72, 0.28], vertical_spacing=0.05,
        subplot_titles=[price_title, ""],
    )
    _price_band_traces(fig, stats, color, row=1, name_min=min_label, name_avg=avg_label,
                        ma_label=ma_label, date_fmt=date_fmt)
    _volume_bar_trace(fig, stats, color, row=2, name=vol_name, date_fmt=date_fmt)

    fig.update_layout(
        height=270,
        margin=dict(l=8, r=8, t=28, b=4),
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
    height=300,
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
with st.expander("📊 지역별 상세 차트 — 매매·전세 (연도 요약은 아래 표에 있습니다)", expanded=False):
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
                chart_cfg = {"displayModeBar": False, "scrollZoom": False, "staticPlot": False}
                if jeonse_stats is not None:
                    # 매매+전세를 둘 다 항상 펼쳐두면 세로 공간을 두 배로 먹어 탭으로 전환
                    fig_j = make_chart(
                        jeonse_stats, JEONSE_COLOR,
                        price_title="전세가(억) · 월 단위", vol_name="전세건수",
                        min_label="전세최저", avg_label="전세평균", ma_label="3개월 이동평균",
                    )
                    tab_sale, tab_jeonse = st.tabs(["📈 매매", "🏠 전세"])
                    with tab_sale:
                        st.plotly_chart(fig, use_container_width=True, config=chart_cfg, key=f"price_sale_{region}")
                    with tab_jeonse:
                        st.plotly_chart(fig_j, use_container_width=True, config=chart_cfg, key=f"price_jeonse_{region}")
                else:
                    st.plotly_chart(fig, use_container_width=True, config=chart_cfg, key=f"price_sale_{region}")

# ── 지역 통계 (인구·주택·경제) ───────────────────────────────
with st.expander("🏘️ 지역 통계 — 인구·주택·경제 (KOSIS) · 가격과의 상관관계", expanded=False):
    st.caption(
        "가격 추이만으로는 안 보이는 배경 지표입니다 — 인구 증감(수요), 주택 인허가실적(향후 공급), "
        "가동사업자 수(지역 경제 활력)를 함께 보면 판단에 참고가 됩니다. KOSIS 기준 **연 단위** 통계입니다. "
        "단위가 제각각(억·명·호·개)이라 **기준연도를 100으로 놓은 지수**로 바꿔 한 축에 겹쳤습니다 — "
        "선이 위로 벌어질수록 그 해 기준보다 많이 늘어난 것이고, 매매가 선과 나란히 가는 지표일수록 "
        "가격과 함께 움직였다는 뜻입니다. 범례의 **r**은 그 동행 정도를 계수로 요약한 값이며, "
        "연도 수가 적어(보통 5~10개) 참고용으로만 보세요."
    )
    st.caption("⚠️ 주택 인허가실적은 이 앱이 다루는 **아파트만이 아니라** 단독·연립·다세대 등 모든 주택 유형을 합친 값입니다 (KOSIS 통계표 특성상 유형별 분리 항목을 아직 확인 못함) — 다른 두 지표보다 해석에 유의하세요.")

    df_kosis_all = load_kosis()
    if df_kosis_all.empty:
        st.info("아직 수집된 KOSIS 통계가 없습니다.")
        st.page_link("pages/kosis_fetch.py", label="KOSIS 통계 수집 메뉴로 이동", icon="🏢")
    else:
        shown_cats = st.multiselect(
            "함께 볼 지표", list(KOSIS_CAT_LABEL),
            default=list(KOSIS_CAT_LABEL), key="area_kosis_cats",
            format_func=lambda c: f"{KOSIS_CAT_ICON[c]} {KOSIS_CAT_LABEL[c]}",
            help="인허가실적처럼 해마다 크게 출렁이는 지표를 빼면 나머지 선의 등락이 더 잘 보입니다.",
        )

        corr_collect: dict[str, list[float]] = {k: [] for k in KOSIS_CAT_LABEL}
        kosis_rows = [selected_regions[i:i + COLS] for i in range(0, len(selected_regions), COLS)]
        for row in kosis_rows:
            cols = st.columns(len(row))
            for col, region in zip(cols, row):
                with col:
                    st.markdown(f"**{region}**")
                    city, gu = _kosis_city_keyword(region)
                    dfc_price = _filter(region)
                    price_yearly = (
                        _price_year_series(dfc_price) if not dfc_price.empty
                        else pd.DataFrame(columns=["year", "price"])
                    )

                    series, notes = {}, []
                    for cat_key in KOSIS_CAT_LABEL:
                        cat_df = df_kosis_all[df_kosis_all["category"] == cat_key]
                        matched = _match_kosis_region(city, gu, sorted(cat_df["region_name"].dropna().unique()))
                        summary = _kosis_summary(cat_df, matched) if matched else None
                        if not summary:
                            if cat_key in shown_cats:
                                notes.append(f"{KOSIS_CAT_ICON[cat_key]} {KOSIS_CAT_SHORT[cat_key]} 통계 없음")
                            continue
                        r, _ = _price_kosis_corr(dfc_price, summary["df"])
                        # 상관계수는 표시 여부와 무관하게 모아야 아래 종합 표가 지표 선택에 흔들리지 않는다
                        if r is not None:
                            corr_collect[cat_key].append(r)
                        if cat_key in shown_cats:
                            series[cat_key] = {"df": summary["df"], "r": r}
                            unit_s = cat_df.loc[cat_df["region_name"] == matched, "unit_name"].dropna()
                            unit = unit_s.iloc[0] if not unit_s.empty else ""
                            yoy = f" ({summary['yoy']:+.1f}%)" if summary["yoy"] is not None else ""
                            notes.append(
                                f"{KOSIS_CAT_ICON[cat_key]} {KOSIS_CAT_SHORT[cat_key]} "
                                f"{summary['latest_value']:,.0f}{unit}{yoy}"
                            )

                    st.caption("  ·  ".join(notes) if notes else "매칭되는 통계 없음")
                    fig_idx = _indexed_trend_chart(price_yearly, series)
                    if fig_idx is None:
                        st.caption("지수 비교에 필요한 연도별 데이터가 부족합니다.")
                    else:
                        st.plotly_chart(
                            fig_idx, use_container_width=True,
                            config={"displayModeBar": False, "scrollZoom": False, "staticPlot": False},
                            key=f"kosis_idx_{region}",
                        )

        corr_summary_rows = []
        for cat_key, rs in corr_collect.items():
            if not rs:
                continue
            avg_r = sum(rs) / len(rs)
            corr_txt, _ = _corr_label(avg_r)
            corr_summary_rows.append({
                "지표": f"{KOSIS_CAT_ICON[cat_key]} {KOSIS_CAT_LABEL[cat_key]}",
                "평균 상관계수": f"{avg_r:+.2f}",
                "해석": corr_txt,
                "표본 지역 수": len(rs),
            })
        if corr_summary_rows:
            st.markdown("**📎 종합 — 선택 지역 전체의 평균 상관관계**")
            st.dataframe(pd.DataFrame(corr_summary_rows), use_container_width=True, hide_index=True)

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
