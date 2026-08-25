"""
pages/kosis_trend.py — KOSIS(국가통계포털) 인구·주택·경제 통계 트렌드

pages/kosis_fetch.py로 수집한 kosis_stats(인구·세대수 / 주택 인허가실적 /
가동사업자 현황)를 지역별로 비교하는 추이 차트.

주의: 어느 분류축(C1_NM/C2_NM)이 지역명인지는 kosis_fetch.py에서 휴리스틱으로
판단해 저장한 값(region_name)을 그대로 쓴다. 항목(item_name)·세부구분(sub_label)이
여러 값일 수 있어 사용자가 직접 골라야 원하는 지표가 나온다.
"""
import os
import sqlite3

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils_style import inject_korean_font

inject_korean_font()

DB_PATH = os.environ.get("DB_PATH", "/tmp/naver_land.db")

PALETTE = [
    "#4C72B0", "#DD8452", "#55A868", "#C44E52",
    "#8172B2", "#937860", "#DA8BC3", "#8C8C8C",
    "#CCB974", "#64B5CD",
]

CATEGORY_LABELS = {
    "population": "인구·세대수",
    "housing":    "주택 인허가실적",
    "business":   "가동사업자 현황(시군구)",
}

# 지역 다중선택의 기본값 — 이 앱이 다루는 관심 지역
DEFAULT_REGION_KEYWORDS = ["평택", "안성", "오산", "화성", "수원", "청주"]


@st.cache_data(ttl=300)
def load_data() -> pd.DataFrame:
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        df = pd.read_sql("""
            SELECT category, region_name, sub_label, item_name, unit_name, prd_de, value
            FROM kosis_stats
            ORDER BY category, region_name, prd_de
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


def _pick_one(label: str, options: list[str], key: str, default: str | None = None) -> str:
    default = default if default in options else options[0]
    if hasattr(st, "segmented_control"):
        sel = st.segmented_control(label, options, default=default, key=key)
        return sel or default
    return st.radio(label, options, horizontal=True, key=key, index=options.index(default))


st.title("인구·주택·경제 통계 트렌드")
st.caption(
    "KOSIS(국가통계포털) 기준 — 지역별 인구·세대수, 주택 인허가실적, 가동사업자 현황을 "
    "여러 지역 나란히 비교합니다. 부동산 실거래가 추이(**가격 추이**, **지역별 가격동향** 메뉴)와 "
    "함께 보면 수요·공급 배경을 가늠하는 데 도움이 됩니다."
)

df_all = load_data()
if df_all.empty:
    st.warning("수집된 KOSIS 통계가 없습니다. 먼저 **KOSIS 통계 수집** 메뉴에서 수집을 실행해주세요.")
    st.stop()

avail_categories = [c for c in CATEGORY_LABELS if c in df_all["category"].unique()]

with st.sidebar:
    st.markdown("**통계 종류**")
    cat_label = _pick_one(
        "종류", [CATEGORY_LABELS[c] for c in avail_categories], "kosis_cat", default=CATEGORY_LABELS[avail_categories[0]],
    )
    category = next(c for c in avail_categories if CATEGORY_LABELS[c] == cat_label)

    df_cat = df_all[df_all["category"] == category]

    st.divider()
    items = sorted(df_cat["item_name"].dropna().unique())
    items = [i for i in items if i]
    if len(items) > 1:
        item_name = st.selectbox("항목", items, key="kosis_item")
        df_cat = df_cat[df_cat["item_name"] == item_name]
    elif len(items) == 1:
        item_name = items[0]
        st.caption(f"항목: {item_name}")
    else:
        item_name = None

    sub_labels = sorted(df_cat["sub_label"].dropna().unique())
    sub_labels = [s for s in sub_labels if s]
    if len(sub_labels) > 1:
        sub_label = st.selectbox("세부 구분", sub_labels, key="kosis_sub")
        df_cat = df_cat[df_cat["sub_label"] == sub_label]
    elif sub_labels:
        st.caption(f"세부 구분: {sub_labels[0]}")

    unit_name = df_cat["unit_name"].dropna().iloc[0] if not df_cat["unit_name"].dropna().empty else ""

    st.divider()
    st.markdown("**지역 선택 (나란히 비교)**")
    region_options = sorted(df_cat["region_name"].dropna().unique())
    default_regions = (
        [r for r in region_options if any(kw in r for kw in DEFAULT_REGION_KEYWORDS)][:6]
        or region_options[:min(4, len(region_options))]
    )
    if "kosis_region_sel" in st.session_state:
        st.session_state.kosis_region_sel = [r for r in st.session_state.kosis_region_sel if r in region_options]
    selected_regions = st.multiselect(
        "지역", region_options, default=default_regions, key="kosis_region_sel",
    )

    st.divider()
    yr_min, yr_max = int(df_cat["year"].min()), int(df_cat["year"].max())
    if yr_min < yr_max:
        sel_yr = st.slider("기간", min_value=yr_min, max_value=yr_max, value=(yr_min, yr_max), key="kosis_year")
    else:
        sel_yr = (yr_min, yr_max)
        st.caption(f"기간: {yr_min}")

if not selected_regions:
    st.info("왼쪽 사이드바에서 비교할 지역을 선택하세요.")
    st.stop()

df_period = df_cat[(df_cat["year"] >= sel_yr[0]) & (df_cat["year"] <= sel_yr[1])]

# ── 비교 차트 ────────────────────────────────────────────────
st.subheader(f"종합 비교 — {cat_label}" + (f" ({item_name})" if item_name else ""))
fig = go.Figure()
for i, region in enumerate(selected_regions):
    dfc = df_period[df_period["region_name"] == region].sort_values("year")
    if dfc.empty:
        continue
    color = PALETTE[i % len(PALETTE)]
    fig.add_trace(go.Scatter(
        x=dfc["year"], y=dfc["value"], name=region,
        line=dict(color=color, width=2.5), marker=dict(size=6),
        hovertemplate=f"{region}<br>" + "%{x} " + f"{unit_name}<br>" + "%{y:,.1f}<extra></extra>",
    ))
fig.update_layout(
    height=440,
    margin=dict(l=8, r=8, t=8, b=8),
    plot_bgcolor="white", paper_bgcolor="white",
    legend=dict(orientation="h", x=0, y=1.08, font=dict(size=11)),
    hovermode="x unified",
)
fig.update_xaxes(dtick=1, showgrid=True, gridcolor="#f0f0f0", fixedrange=True)
fig.update_yaxes(title_text=unit_name, showgrid=True, gridcolor="#f0f0f0", fixedrange=True, tickformat=",")
st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False, "scrollZoom": False, "staticPlot": False})

# ── 요약 테이블 ────────────────────────────────────────────────
st.divider()
st.subheader("지역별 최근 값 요약")

summary_rows = []
for region in selected_regions:
    dfc = df_period[df_period["region_name"] == region].sort_values("year")
    if dfc.empty:
        continue
    latest = dfc.iloc[-1]
    row = {"지역": region, "최근연도": int(latest["year"]), f"값({unit_name})": latest["value"]}
    if len(dfc) >= 2:
        prev = dfc.iloc[-2]
        delta = latest["value"] - prev["value"]
        pct = (delta / prev["value"] * 100) if prev["value"] else 0
        row["전년 대비"] = f"{delta:+,.1f} ({pct:+.1f}%)"
    else:
        row["전년 대비"] = "-"
    summary_rows.append(row)

if summary_rows:
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
