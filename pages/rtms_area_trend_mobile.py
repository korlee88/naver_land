"""
pages/rtms_area_trend_mobile.py — 국토부 실거래가 기반 구/동 단위 가격동향 비교 (모바일)

PC 버전(pages/rtms_area_trend.py)과 계산 로직은 완전히 동일(utils_area_trend.py 공용).
다른 점은 레이아웃뿐이다 — 좌우 컬럼 대신 항상 1열로 쌓고, 폰트/여백을 키우고,
차트 확대·축소(핀치줌 포함)를 한 번 더 명시적으로 잠근다.
"""
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from utils_style import inject_korean_font
from utils_area_trend import (
    CHART_CONFIG, PALETTE, JEONSE_COLOR, KOSIS_CAT_LABEL, KOSIS_CAT_ICON, KOSIS_CAT_SHORT,
    lawd_label, load_data, load_jeonse, load_kosis,
    monthly_stats, weekly_stats, trend_signal,
    kosis_city_keyword, match_kosis_region, kosis_summary,
    price_year_series, price_kosis_corr, corr_label, indexed_trend_chart,
    make_chart, pick_one,
)

inject_korean_font()


def _lock_page_zoom():
    """Plotly 차트는 scrollZoom=False+fixedrange=True로 이미 잠겨있지만, 그와 별개로
    모바일 브라우저는 페이지 전체에 대해 네이티브 핀치줌을 제공한다 — 차트를 확대하려던
    손가락이 페이지 전체를 확대해버려 "차트가 또 확대된다"는 불편으로 느껴진다.
    viewport meta에 user-scalable=no를 넣어 그 네이티브 핀치줌 자체를 막는다.
    Streamlit은 <head>를 직접 조작할 API가 없어 컴포넌트 iframe에서 같은 오리진인
    부모 문서(window.parent)의 meta 태그를 찾아 고쳐 쓴다."""
    components.html(
        """
        <script>
        try {
            const doc = window.parent.document;
            let m = doc.querySelector('meta[name="viewport"]');
            if (!m) {
                m = doc.createElement('meta');
                m.setAttribute('name', 'viewport');
                doc.head.appendChild(m);
            }
            m.setAttribute('content', 'width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no');
        } catch (e) {}
        </script>
        """,
        height=0, width=0,
    )


_lock_page_zoom()

st.markdown("""
<style>
.block-container { padding: 0.6rem 0.7rem !important; }
[data-testid="stExpander"] summary p { font-size: 15px !important; font-weight: 600; }
[data-baseweb="tab"] { font-size: 14px !important; padding: 8px 4px !important; }
[data-testid="stMultiSelect"] label, [data-testid="stSelectbox"] label { font-size: 12px !important; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# 페이지
# ══════════════════════════════════════════════════════════════
st.markdown("#### 📱 지역별 가격동향 (모바일)")
st.caption(
    "국토부 실거래가 기준 — 구/동 전체를 합친 매매·전세 시세를 비교합니다. "
    "PC에서 더 넓게 보려면 **지역별 가격동향** 메뉴를 이용하세요."
)

df_all = load_data()
if df_all.empty:
    st.warning("수집된 실거래가 데이터가 없습니다. **실거래가 수집** 메뉴에서 먼저 수집해주세요.")
    st.stop()

df_jeonse_all = load_jeonse()

# ── 필터 (사이드바 — 모바일에서는 좌상단 »로 열림) ──────────────
with st.sidebar:
    st.markdown("**비교 단위**")
    unit_level = pick_one("단위", ["구/시 단위", "동 단위"], "am_unit_level", default="동 단위")

    df_all["region_gu"] = df_all["lawd_cd"].apply(lawd_label)
    if unit_level == "구/시 단위":
        df_all["region_key"] = df_all["region_gu"]
    else:
        df_all["region_key"] = df_all["region_gu"] + " " + df_all["dong"].fillna("(동 미상)")

    region_options = sorted(df_all["region_key"].dropna().unique())

    st.markdown("**지역 선택**")
    # 모바일 화면 폭에서는 카드가 세로로 쌓이므로 기본 지역 수를 PC보다 적게 잡는다
    default_regions = (
        [r for r in region_options if "동삭동" in r]
        or region_options[:min(2, len(region_options))]
    )
    if "am_region_sel" in st.session_state:
        st.session_state.am_region_sel = [r for r in st.session_state.am_region_sel if r in region_options]
    selected_regions = st.multiselect("지역", region_options, default=default_regions, key="am_region_sel")
    st.divider()

    st.markdown("**평형**")
    PYEONG = 3.3058
    area_max = float(df_all["area"].max())
    AREA_BUCKETS = {
        "전체": (0.0, area_max + 1), "10평대": (10 * PYEONG, 15 * PYEONG),
        "15평대": (15 * PYEONG, 20 * PYEONG), "20평대": (20 * PYEONG, 25 * PYEONG),
        "25평대": (25 * PYEONG, 30 * PYEONG), "30평대": (30 * PYEONG, 35 * PYEONG),
        "35평 이상": (35 * PYEONG, area_max + 1),
    }
    sel_area = pick_one("평형", list(AREA_BUCKETS.keys()), "am_area_bucket", default="전체")
    lo, hi = AREA_BUCKETS[sel_area]
    st.divider()

    st.markdown("**기간**")
    period = st.selectbox("", ["전체", "최근 6개월", "최근 1년", "최근 2년"],
                           index=0, key="am_period", label_visibility="collapsed")

if not selected_regions:
    st.info("왼쪽 상단 » 를 눌러 비교할 지역을 선택하세요.")
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


# ── 종합 비교 차트 ───────────────────────────────────────────
st.markdown("##### 종합 비교 — 매매 평균가")
compare_mode = pick_one("표시 방식", ["변동률(%)", "절대가격(억)"], "am_compare_mode", default="변동률(%)")
if compare_mode == "변동률(%)":
    st.caption("ℹ️ 첫 주를 100으로 놓은 변동률입니다.")

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
        hover = f"{region}<br>" + "%{x|%y.%m.%d} %{y:.1f}<extra></extra>"
    else:
        y_vals = stats["avg"]
        hover = f"{region}<br>" + "%{x|%y.%m.%d} %{y:.2f}억<extra></extra>"
    fig_overlay.add_trace(go.Scatter(
        x=stats["ym"], y=y_vals, name=region,
        line=dict(color=color, width=2), marker=dict(size=3),
        hovertemplate=hover,
    ))
fig_overlay.update_layout(
    height=260, margin=dict(l=6, r=6, t=6, b=6),
    plot_bgcolor="white", paper_bgcolor="white",
    legend=dict(orientation="h", x=0, y=1.22, font=dict(size=10)),
    hovermode="x unified",
)
fig_overlay.update_xaxes(tickformat="%y.%m", showgrid=True, gridcolor="#f0f0f0",
                          tickfont=dict(size=10), fixedrange=True)
if compare_mode == "변동률(%)":
    fig_overlay.add_hline(y=100, line=dict(color="#999", width=1, dash="dot"))
    fig_overlay.update_yaxes(showgrid=True, gridcolor="#f0f0f0", tickfont=dict(size=10), fixedrange=True)
else:
    fig_overlay.update_yaxes(ticksuffix="억", showgrid=True, gridcolor="#f0f0f0",
                              tickfont=dict(size=10), fixedrange=True)
st.plotly_chart(fig_overlay, use_container_width=True, config=CHART_CONFIG)

st.divider()

# ── 지역별 상세 (1열 · 매매/전세 탭) ─────────────────────────
with st.expander("📊 지역별 상세 — 매매·전세", expanded=len(selected_regions) == 1):
    for region in selected_regions:
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
        cap = f"단지 {n_complex}개 · 최저 {latest['min']:.2f}억 · 평균 {latest['avg']:.2f}억 · 최고 {latest['max']:.2f}억"
        if jeonse_stats is not None:
            j_latest = jeonse_stats.iloc[-1]
            cap += f" · 전세평균 {j_latest['avg']:.2f}억"
        st.caption(cap)

        fig = make_chart(
            stats, color, vol_name="매매건수", ma_label="4주 이동평균",
            date_fmt="%y.%m.%d", height=250, legend_font_size=10,
        )
        if jeonse_stats is not None:
            fig_j = make_chart(
                jeonse_stats, JEONSE_COLOR, vol_name="전세건수",
                min_label="전세최저", avg_label="전세평균", ma_label="3개월 이동평균",
                height=250, legend_font_size=10,
            )
            tab_sale, tab_jeonse = st.tabs(["📈 매매", "🏠 전세"])
            with tab_sale:
                st.caption("매매가(억) · 주 단위")
                st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key=f"m_sale_{region}")
            with tab_jeonse:
                st.caption("전세가(억) · 월 단위")
                st.plotly_chart(fig_j, use_container_width=True, config=CHART_CONFIG, key=f"m_jeonse_{region}")
        else:
            st.caption("매매가(억) · 주 단위")
            st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key=f"m_sale_{region}")
        st.divider()

# ── 지역 통계 (인구·주택·경제, KOSIS) — 1열 ───────────────────
with st.expander("🏘️ 지역 통계 — 인구·주택·경제 (KOSIS)", expanded=False):
    st.caption(
        "기준연도를 100으로 놓은 지수로 매매가와 KOSIS 지표를 한 축에 겹쳤습니다. "
        "선이 나란히 갈수록 가격과 함께 움직였다는 뜻이고, 범례의 r이 그 정도를 나타냅니다."
    )
    st.caption("⚠️ 주택 인허가실적은 아파트 외 단독·연립·다세대까지 합친 값입니다.")

    df_kosis_all = load_kosis()
    if df_kosis_all.empty:
        st.info("아직 수집된 KOSIS 통계가 없습니다.")
        st.page_link("pages/kosis_fetch.py", label="KOSIS 통계 수집 메뉴로 이동", icon="🏢")
    else:
        shown_cats = st.multiselect(
            "함께 볼 지표", list(KOSIS_CAT_LABEL),
            default=list(KOSIS_CAT_LABEL), key="am_kosis_cats",
            format_func=lambda c: f"{KOSIS_CAT_ICON[c]} {KOSIS_CAT_LABEL[c]}",
        )

        corr_collect: dict[str, list[float]] = {k: [] for k in KOSIS_CAT_LABEL}
        for region in selected_regions:
            st.markdown(f"**{region}**")
            city, gu = kosis_city_keyword(region)
            dfc_price = _filter(region)
            price_yearly = (
                price_year_series(dfc_price) if not dfc_price.empty
                else pd.DataFrame(columns=["year", "price"])
            )

            series, notes = {}, []
            for cat_key in KOSIS_CAT_LABEL:
                cat_df = df_kosis_all[df_kosis_all["category"] == cat_key]
                matched = match_kosis_region(city, gu, sorted(cat_df["region_name"].dropna().unique()))
                summary = kosis_summary(cat_df, matched) if matched else None
                if not summary:
                    if cat_key in shown_cats:
                        notes.append(f"{KOSIS_CAT_ICON[cat_key]} {KOSIS_CAT_SHORT[cat_key]} 없음")
                    continue
                r, _ = price_kosis_corr(dfc_price, summary["df"])
                if r is not None:
                    corr_collect[cat_key].append(r)
                if cat_key in shown_cats:
                    series[cat_key] = {"df": summary["df"], "r": r}
                    unit_s = cat_df.loc[cat_df["region_name"] == matched, "unit_name"].dropna()
                    unit = unit_s.iloc[0] if not unit_s.empty else ""
                    yoy = f" ({summary['yoy']:+.1f}%)" if summary["yoy"] is not None else ""
                    notes.append(f"{KOSIS_CAT_ICON[cat_key]} {summary['latest_value']:,.0f}{unit}{yoy}")

            st.caption("  ·  ".join(notes) if notes else "매칭되는 통계 없음")
            fig_idx = indexed_trend_chart(price_yearly, series, height=230)
            if fig_idx is None:
                st.caption("지수 비교에 필요한 연도별 데이터가 부족합니다.")
            else:
                st.plotly_chart(fig_idx, use_container_width=True, config=CHART_CONFIG, key=f"m_kosis_idx_{region}")
            st.divider()

        corr_summary_rows = []
        for cat_key, rs in corr_collect.items():
            if not rs:
                continue
            avg_r = sum(rs) / len(rs)
            corr_txt, _ = corr_label(avg_r)
            corr_summary_rows.append({
                "지표": f"{KOSIS_CAT_ICON[cat_key]} {KOSIS_CAT_SHORT[cat_key]}",
                "평균r": f"{avg_r:+.2f}", "해석": corr_txt,
            })
        if corr_summary_rows:
            st.markdown("**📎 종합 상관관계**")
            st.dataframe(pd.DataFrame(corr_summary_rows), use_container_width=True, hide_index=True)

# ── 요약 표 ────────────────────────────────────────────────
st.divider()
st.markdown("##### 지역별 최근 거래 요약")

summary_rows = []
for region in selected_regions:
    dfc = _filter(region)
    if dfc.empty:
        continue
    stats = region_stats.get(region) if region in region_stats else weekly_stats(dfc)
    latest_ym = dfc["ym"].max()
    latest = dfc[dfc["ym"] == latest_ym]
    emoji, trend_txt, _ = trend_signal(stats, window=4)
    summary_rows.append({
        "지역": region, "트렌드": f"{emoji} {trend_txt}",
        "매매평균(억)": round(latest["eok"].mean(), 2),
        "매매건수": len(latest),
    })

if summary_rows:
    summary_df = pd.DataFrame(summary_rows).sort_values("매매평균(억)")
    st.dataframe(summary_df, use_container_width=True, hide_index=True)
