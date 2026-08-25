"""
pages/rtms_area_trend.py — 국토부 실거래가 기반 구/동 단위 가격동향 비교 (PC)

단지별이 아니라 구/동(행정동) 단위로 실거래를 묶어 여러 지역을 나란히 비교한다.
데이터 출처는 구글시트에서 자동 복원되는 rtms_transactions / rtms_jeonse 테이블뿐이며
(pages/rtms_fetch.py의 국토부 API 수집 → 구글시트 백업 → app.py 자동복원 흐름),
이 페이지 자체는 API를 호출하지 않는다.

주의: rtms_jeonse에는 행정동(dong) 컬럼이 없어 시/구(lawd_cd) 단위로만 구분 가능하다.
모바일에서는 pages/rtms_area_trend_mobile.py를 쓴다 — 계산 로직은 utils_area_trend.py 공용.
"""
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

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
    unit_level = pick_one("단위", ["구/시 단위", "동 단위"], "area_unit_level", default="동 단위")
    if unit_level == "동 단위" and not df_jeonse_all.empty:
        st.caption("ℹ️ 전세는 행정동 구분이 없어 같은 시/구 전체 기준으로 표시됩니다.")

    df_all["region_gu"] = df_all["lawd_cd"].apply(lawd_label)
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
    sel_area = pick_one("평형", list(AREA_BUCKETS.keys()), "area_area_bucket", default="전체")
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
compare_mode = pick_one(
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
# 전폭이면 3.5:1로 납작해져 등락이 눌려 보인다 — 반폭으로 줄여 가로세로비를 맞춘다
overlay_col, _ = st.columns(2)
with overlay_col:
    st.plotly_chart(fig_overlay, use_container_width=True, config=CHART_CONFIG)

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
                    stats, color, vol_name="매매건수",
                    ma_label="4주 이동평균", date_fmt="%Y-%m-%d",
                )
                if jeonse_stats is not None:
                    # 매매+전세를 둘 다 항상 펼쳐두면 세로 공간을 두 배로 먹어 탭으로 전환
                    fig_j = make_chart(
                        jeonse_stats, JEONSE_COLOR, vol_name="전세건수",
                        min_label="전세최저", avg_label="전세평균", ma_label="3개월 이동평균",
                    )
                    tab_sale, tab_jeonse = st.tabs(["📈 매매", "🏠 전세"])
                    with tab_sale:
                        st.caption("매매가(억) · 주 단위")
                        st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key=f"price_sale_{region}")
                    with tab_jeonse:
                        st.caption("전세가(억) · 월 단위")
                        st.plotly_chart(fig_j, use_container_width=True, config=CHART_CONFIG, key=f"price_jeonse_{region}")
                else:
                    st.caption("매매가(억) · 주 단위")
                    st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key=f"price_sale_{region}")

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
                                notes.append(f"{KOSIS_CAT_ICON[cat_key]} {KOSIS_CAT_SHORT[cat_key]} 통계 없음")
                            continue
                        r, _ = price_kosis_corr(dfc_price, summary["df"])
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
                    fig_idx = indexed_trend_chart(price_yearly, series)
                    if fig_idx is None:
                        st.caption("지수 비교에 필요한 연도별 데이터가 부족합니다.")
                    else:
                        st.plotly_chart(
                            fig_idx, use_container_width=True,
                            config=CHART_CONFIG,
                            key=f"kosis_idx_{region}",
                        )

        corr_summary_rows = []
        for cat_key, rs in corr_collect.items():
            if not rs:
                continue
            avg_r = sum(rs) / len(rs)
            corr_txt, _ = corr_label(avg_r)
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
