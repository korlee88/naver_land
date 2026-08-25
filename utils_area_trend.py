# utils_area_trend.py — 구/동 단위 가격동향(pages/rtms_area_trend.py, rtms_area_trend_mobile.py) 공용 로직
#
# 데이터 로딩·집계·상관분석·차트 빌더를 PC/모바일 두 페이지가 그대로 재사용한다.
# 페이지 레이아웃(사이드바, 컬럼 배치, expander 등)은 각 페이지 파일에 남겨두고,
# 화면 폭에 상관없이 동일해야 하는 계산 로직만 여기 둔다.
import os
import sqlite3

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

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

KOSIS_CAT_LABEL = {"population": "인구·세대수", "housing": "주택 인허가(전체유형)", "business": "가동사업자수"}
KOSIS_CAT_ICON = {"population": "👥", "housing": "🏗", "business": "🏢"}
# 범례가 길어지면 차트 위를 여러 줄로 덮어 본문을 밀어내므로 범례에는 짧은 이름을 쓴다
KOSIS_CAT_SHORT = {"population": "인구", "housing": "주택인허가", "business": "사업자수"}

# 지수 차트 색상 — 색은 "지표"라는 엔티티를 따르므로 지역이 바뀌어도 같은 지표는 같은 색.
# 검증된 카테고리 팔레트 슬롯 1~4(blue/orange/aqua/yellow) 순서를 그대로 쓴다.
INDEX_COLOR_PRICE = "#2a78d6"
KOSIS_CAT_COLOR = {"population": "#eb6834", "housing": "#1baf7a", "business": "#eda100"}
GRID_INK, AXIS_INK, MUTED_INK = "#e1e0d9", "#c3c2b7", "#898781"

# 모든 st.plotly_chart 호출에 공통으로 넘기는 설정 — 확대/축소·팬·모드바를 전부 잠근다.
# fixedrange=True(축 단위)와 짝을 이뤄야 모바일 핀치줌까지 막힌다(축만 잠그면 터치 핀치는 새는 경우가 있음).
CHART_CONFIG = {"displayModeBar": False, "scrollZoom": False, "staticPlot": False}


def _hex_to_rgba(hex_color: str, alpha: float = 0.12) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def lawd_label(code: str) -> str:
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


# ── 집계 ─────────────────────────────────────────────────────
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


# ── KOSIS 매칭·상관분석 ─────────────────────────────────────
def prefer_total_sub(df: pd.DataFrame) -> pd.DataFrame:
    """세부구분(성별/산업분류 등)이 있으면 '계/전체/합계' 같은 총계 행만 남긴다."""
    subs = [s for s in df["sub_label"].dropna().unique() if s]
    if not subs:
        return df
    total_like = [s for s in subs if s in ("계", "소계", "전체", "합계")]
    keep = total_like[0] if total_like else subs[0]
    return df[df["sub_label"].isna() | (df["sub_label"] == keep)]


def kosis_city_keyword(region_key: str) -> tuple[str, str | None]:
    """'경기 화성시 동탄구' → ('화성시', '동탄구'). 시/군 단위면 구는 None."""
    parts = region_key.split(" ")
    city = next((p for p in parts if p.endswith("시") or p.endswith("군")), parts[-1])
    gu = next((p for p in parts if p.endswith("구") and p != city), None)
    return city, gu


def match_kosis_region(city: str, gu: str | None, kosis_regions: list[str]) -> str | None:
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


def kosis_summary(cat_df: pd.DataFrame, region_name: str) -> dict | None:
    dfc = cat_df[cat_df["region_name"] == region_name].sort_values("year")
    dfc = prefer_total_sub(dfc)
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


def build_kosis_series_for_region(
    region: str, dfc_price: pd.DataFrame, df_kosis_all: pd.DataFrame,
    shown_cats: list[str] | None = None,
) -> tuple[dict, list[str], dict[str, float | None]]:
    """지역 하나에 대해 KOSIS 3개 카테고리를 매칭·상관분석까지 한 번에 처리.

    상관계수는 shown_cats와 무관하게 항상 3개 다 계산한다 — "종합 상관관계" 요약표가
    사용자의 화면 표시 선택에 따라 흔들리면 안 되기 때문(표시는 취향, 통계는 사실).
    반환: (지수차트에 넣을 series dict, 카드에 표시할 요약 문구 리스트, 카테고리별 r)
    """
    city, gu = kosis_city_keyword(region)
    shown = shown_cats if shown_cats is not None else list(KOSIS_CAT_LABEL)
    series, notes, corrs = {}, [], {}
    for cat_key in KOSIS_CAT_LABEL:
        cat_df = df_kosis_all[df_kosis_all["category"] == cat_key]
        matched = match_kosis_region(city, gu, sorted(cat_df["region_name"].dropna().unique()))
        summary = kosis_summary(cat_df, matched) if matched else None
        if not summary:
            corrs[cat_key] = None
            if cat_key in shown:
                notes.append(f"{KOSIS_CAT_ICON[cat_key]} {KOSIS_CAT_SHORT[cat_key]} 통계 없음")
            continue
        r, _ = price_kosis_corr(dfc_price, summary["df"])
        corrs[cat_key] = r
        if cat_key in shown:
            series[cat_key] = {"df": summary["df"], "r": r}
            unit_s = cat_df.loc[cat_df["region_name"] == matched, "unit_name"].dropna()
            unit = unit_s.iloc[0] if not unit_s.empty else ""
            yoy = f" ({summary['yoy']:+.1f}%)" if summary["yoy"] is not None else ""
            notes.append(
                f"{KOSIS_CAT_ICON[cat_key]} {KOSIS_CAT_SHORT[cat_key]} "
                f"{summary['latest_value']:,.0f}{unit}{yoy}"
            )
    return series, notes, corrs


def price_year_series(dfc: pd.DataFrame) -> pd.DataFrame:
    """지역 매매 실거래(dfc, eok/ym 컬럼)를 KOSIS와 맞춰 연도별 평균가로 집계."""
    d = dfc.assign(year=dfc["ym"].dt.year)
    return d.groupby("year", as_index=False)["eok"].mean().rename(columns={"eok": "price"})


def price_kosis_corr(dfc: pd.DataFrame, kosis_yearly: pd.DataFrame) -> tuple[float | None, int]:
    """연도별 매매평균가 vs KOSIS 연도별 값의 피어슨 상관계수. 반환: (r 또는 None, 겹치는 연도 수)."""
    if dfc.empty or kosis_yearly.empty:
        return None, 0
    price_yr = price_year_series(dfc)
    merged = pd.merge(price_yr, kosis_yearly.rename(columns={"value": "kosis"}), on="year", how="inner")
    if len(merged) < 3:
        return None, len(merged)
    r = merged["price"].corr(merged["kosis"])
    return (None if pd.isna(r) else float(r)), len(merged)


def corr_label(r: float) -> tuple[str, str]:
    strength = "강한" if abs(r) >= 0.7 else "중간" if abs(r) >= 0.4 else "약한" if abs(r) >= 0.2 else "거의 없는"
    direction = "양의" if r >= 0 else "음의"
    color = "#27ae60" if r >= 0.2 else "#e74c3c" if r <= -0.2 else "#888"
    return f"{strength} {direction} 상관 (r={r:+.2f})", color


def rebase_to_100(df: pd.DataFrame, value_col: str, base_year: int) -> pd.DataFrame | None:
    """base_year 값을 100으로 놓고 지수화. 기준값이 없거나 0이면 None."""
    d = df[df["year"] >= base_year].sort_values("year")
    if len(d) < 2:
        return None
    at_base = d.loc[d["year"] == base_year, value_col]
    base = at_base.iloc[0] if not at_base.empty else d[value_col].iloc[0]
    if not base:
        return None
    return pd.DataFrame({"year": d["year"].values, "idx": d[value_col].values / base * 100})


def indexed_trend_chart(price_yearly: pd.DataFrame, kosis_series: dict, *, height: int = 250) -> go.Figure | None:
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
        idx = rebase_to_100(df, col, base_year)
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
        height=height, margin=dict(l=6, r=6, t=6, b=6),
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


# ── 가격/거래량 차트 빌더 ────────────────────────────────────
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
    vol_name: str = "거래건수",
    min_label: str = "최저", avg_label: str = "평균",
    ma_label: str = "이동평균", date_fmt: str = "%Y-%m",
    height: int = 270, legend_font_size: int = 10,
) -> go.Figure:
    """가격(밴드+평균+이동평균)/거래량 2단 차트 1개. 확대·이동 불가(고정형).

    가격 종류를 알려주는 제목(예: "매매가(억)·주 단위")은 Plotly 안에 넣지 않는다 —
    Plotly의 subplot_titles 주석은 위쪽 범례와 같은 자리를 다투는데, 폭이 좁아지면(모바일)
    범례가 여러 줄로 접히면서 제목 글자와 겹쳐버린다. 대신 호출부에서 차트 위에
    st.caption()으로 표시하면 항상 별도 줄이라 절대 겹치지 않는다.
    """
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.72, 0.28], vertical_spacing=0.05,
    )
    _price_band_traces(fig, stats, color, row=1, name_min=min_label, name_avg=avg_label,
                        ma_label=ma_label, date_fmt=date_fmt)
    _volume_bar_trace(fig, stats, color, row=2, name=vol_name, date_fmt=date_fmt)

    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=20, b=4),
        plot_bgcolor="white", paper_bgcolor="white",
        legend=dict(orientation="h", x=0, y=1.16, font=dict(size=legend_font_size)),
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


def pick_one(label: str, options: list[str], key: str, default: str | None = None) -> str:
    default = default if default in options else options[0]
    if hasattr(st, "segmented_control"):
        sel = st.segmented_control(label, options, default=default, key=key)
        return sel or default
    return st.radio(label, options, horizontal=True, key=key, index=options.index(default))
