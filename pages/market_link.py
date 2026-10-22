"""
pages/market_link.py — 시장 연동 분석 (시차상관·지역베타·전이경로·유사국면)

"전세계 부동산과 평택이 얼마나 연동되는가"를 하나의 상관지수로 답하지 않는다.
36개월 표본에서는 아무 관계 없는 두 상승 계열의 |r|이 0.5를 넘을 확률이 91%라,
그런 숫자는 "둘 다 올랐다"는 말일 뿐이기 때문이다.

대신 (1) 변화율로 상관을 재고 (2) 신뢰구간과 표본수를 항상 같이 보여주고
(3) 시차를 훑을 때 생기는 다중비교를 보정한다. 계산은 utils_analysis.py에 있다.
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils_style import inject_korean_font
from utils_area_trend import (
    CHART_CONFIG, PALETTE, lawd_label, load_data, load_jeonse, load_kosis, load_ecos,
    kosis_city_keyword, match_kosis_region, kosis_summary,
)
import utils_analysis as A
import utils_ecos as ec
import utils_market as mk

inject_korean_font()

st.title("시장 연동 분석")
st.caption(
    "금리·공급·인구 같은 지표가 **몇 개월 선행해서** 가격을 움직이는지, 내 지역이 "
    "시장보다 **크게 움직이는지 작게 움직이는지**를 잽니다. 모든 상관은 수준이 아니라 "
    "**변화율** 기준이고, 신뢰구간과 표본수를 항상 함께 표시합니다."
)

df_all = load_data()
if df_all.empty:
    st.warning("수집된 실거래가가 없습니다. **🏛️ 실거래가 수집** 메뉴에서 먼저 수집해주세요.")
    st.stop()

df_all = df_all.assign(region=df_all["lawd_cd"].apply(lawd_label))
df_jeonse = load_jeonse()
df_kosis = load_kosis()
df_ecos = load_ecos()

with st.sidebar:
    st.markdown("**분석 대상**")
    regions = sorted(df_all["region"].dropna().unique())
    default_idx = next((i for i, r in enumerate(regions) if "평택" in r), 0)
    region = st.selectbox("지역", regions, index=default_idx)
    max_lag = st.slider("시차 탐색 범위 (±개월)", 3, 18, 12)
    st.caption(f"시차 {2 * max_lag + 1}개를 훑습니다 — 다중비교 보정이 자동 적용됩니다.")

dfr = df_all[df_all["region"] == region]

# ── 공통 월별 시계열 ──────────────────────────────────────────
price = dfr.groupby("ym")["price_man"].mean().sort_index()
volume = dfr.groupby("ym").size().sort_index().astype(float)

jr = mk.jeonse_ratio_series(
    dfr, df_jeonse[df_jeonse["lawd_cd"].isin(dfr["lawd_cd"].unique())] if not df_jeonse.empty else pd.DataFrame()
)
jeonse_ratio = jr.set_index("ym")["ratio"] if not jr.empty else pd.Series(dtype=float)

# ECOS 금리 — 월별
rate_series = {}
if not df_ecos.empty:
    e = df_ecos.copy()
    e["date"] = pd.to_datetime(
        [ec.period_to_date(p, "M") for p in e["period"]], errors="coerce"
    )
    e = e.dropna(subset=["date"])
    for item, grp in e.groupby(e["item_name"].fillna("(미상)")):
        s = grp.set_index("date")["value"].sort_index()
        if len(s) >= 6:
            rate_series[item] = s

n_months = len(price)
c = st.columns(4)
c[0].metric("분석 대상", region)
c[1].metric("월별 표본", f"{n_months}개월")
c[2].metric("전세가율 표본", f"{len(jeonse_ratio)}개월")
c[3].metric("금리 계열", f"{len(rate_series)}종")

if n_months < 12:
    st.warning(
        f"월별 표본이 **{n_months}개월**뿐이라 어떤 분석도 신뢰하기 어렵습니다. "
        "**🏛️ 실거래가 수집**에서 수집 범위를 **60개월**로 늘려 한 번 돌려주세요."
    )

# 분석에 쓸 지표 모음
indicators: dict[str, pd.Series] = {"거래량": volume}
if len(jeonse_ratio) >= 6:
    indicators["전세가율"] = jeonse_ratio
for name, s in rate_series.items():
    indicators[f"금리·{name[:20]}"] = s

tab1, tab2, tab3, tab4 = st.tabs(["① 시차 교차상관", "② 지역 베타", "③ 전이 경로", "④ 유사 국면"])

# ══════════════════════════════════════════════════════════════
# ① 시차 교차상관
# ══════════════════════════════════════════════════════════════
with tab1:
    st.markdown("#### 무엇이 몇 개월 선행하는가")
    st.caption(
        "지표를 앞뒤로 밀어가며 가격 변화와의 상관을 잽니다. **lag > 0 이면 지표가 "
        "그만큼 선행**한다는 뜻입니다. 막대는 상관계수, 세로선은 95% 신뢰구간입니다."
    )
    if not indicators:
        st.info("비교할 지표가 아직 없습니다. 전세가율은 전월세 수집이, 금리는 ECOS 수집이 필요합니다.")
    else:
        pick = st.selectbox("지표", list(indicators), key="ml_ind")
        ind = indicators[pick]
        scan = A.lag_scan(price, ind, max_lag=max_lag)
        valid = scan.dropna(subset=["r"])

        if valid.empty:
            st.warning("겹치는 기간이 없어 상관을 계산할 수 없습니다.")
        else:
            best_raw = A.best_lag(scan, require_significant=False)
            best_adj = A.best_lag(scan, require_significant=True, adjusted=True)
            n_sig_raw = int(valid["significant"].sum())
            n_sig_adj = int(valid["significant_adj"].sum())
            exp_fp = A.expected_false_positives(len(valid))

            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=valid["lag"], y=valid["r"],
                marker_color=[PALETTE[0] if s else "#c9c9c9" for s in valid["significant_adj"]],
                error_y=dict(type="data", symmetric=False,
                             array=(valid["hi_adj"] - valid["r"]).clip(lower=0),
                             arrayminus=(valid["r"] - valid["lo_adj"]).clip(lower=0),
                             color="#888", thickness=1),
                hovertemplate="lag %{x}개월<br>r %{y:.3f}<extra></extra>", name="상관",
            ))
            fig.add_hline(y=0, line=dict(color="#666", width=1))
            fig.update_layout(
                height=300, margin=dict(l=8, r=8, t=8, b=8), showlegend=False,
                plot_bgcolor="white", paper_bgcolor="white",
                xaxis=dict(title="시차(개월) — 양수면 지표가 선행", showgrid=True,
                           gridcolor="#f0f0f0", fixedrange=True),
                yaxis=dict(title="상관계수(변화율 기준)", showgrid=True,
                           gridcolor="#f0f0f0", fixedrange=True, range=[-1, 1]),
            )
            st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key="ml_scan")
            st.caption("진한 막대 = 다중비교 보정 후에도 0이 아니라고 말할 수 있는 시차")

            if best_adj:
                lead = ("선행" if best_adj["lag"] > 0 else "후행" if best_adj["lag"] < 0 else "동행")
                st.success(
                    f"**{pick}**이 가격보다 **{abs(best_adj['lag'])}개월 {lead}** — "
                    f"r = {best_adj['r']:+.2f} "
                    f"(보정 95% 구간 [{best_adj['lo_adj']:.2f}, {best_adj['hi_adj']:.2f}], "
                    f"표본 {best_adj['n']}개) · 강도 **{A.corr_strength(best_adj['r'])}**"
                )
            else:
                msg = (f"가장 큰 상관은 lag {best_raw['lag']}에서 r={best_raw['r']:+.2f}였지만, "
                       f"다중비교 보정 후에는 **0과 구분되지 않습니다**." if best_raw else
                       "유의한 시차가 없습니다.")
                st.info(msg + " 관계가 없다는 뜻일 수도, 표본이 부족한 것일 수도 있습니다.")

            st.caption(
                f"검정 {len(valid)}회 · 보정 전 유의 {n_sig_raw}개 / 보정 후 {n_sig_adj}개 · "
                f"우연히 나올 기대 개수 {exp_fp:.1f}개. "
                "보정 전 유의 개수가 기대 개수 언저리면 발견이 아니라 잡음입니다."
            )

            with st.expander("수준상관과 비교 — 왜 변화율로 재는가"):
                lv = A.corr_with_ci(price, ind.reindex(price.index).ffill())
                ch = A.corr_with_ci(A.to_changes(price),
                                    A.to_changes(ind.reindex(price.index).ffill()))
                cmp_df = pd.DataFrame([
                    {"방식": "수준(원계열)", "r": None if lv["r"] is None else round(lv["r"], 3),
                     "표본": lv["n"], "유의": lv["significant"]},
                    {"방식": "변화율(차분)", "r": None if ch["r"] is None else round(ch["r"], 3),
                     "표본": ch["n"], "유의": ch["significant"]},
                ])
                st.dataframe(cmp_df, use_container_width=True, hide_index=True)
                st.caption(
                    "둘 다 추세를 가지면 수준상관은 관계가 없어도 높게 나옵니다. "
                    "36개월 모의실험에서 무관한 두 상승 계열의 |r|이 0.5를 넘을 확률이 "
                    "**수준 91% vs 변화 0.3%** 였습니다 — 이 페이지가 변화율을 쓰는 이유입니다."
                )

# ══════════════════════════════════════════════════════════════
# ② 지역 베타
# ══════════════════════════════════════════════════════════════
with tab2:
    st.markdown("#### 시장이 1% 움직일 때 내 지역은 몇 %")
    others = sorted([r for r in regions if r != region])
    if not others:
        st.info("비교할 다른 지역이 없습니다. 실거래가 수집에서 지역을 더 추가해보세요.")
    else:
        bench_sel = st.multiselect(
            "벤치마크 지역 (선택한 지역들의 평균을 시장으로 봅니다)", others,
            default=[r for r in others if any(k in r for k in ("수원", "화성", "오산", "안성"))] or others[:3],
        )
        if not bench_sel:
            st.info("벤치마크로 쓸 지역을 하나 이상 선택하세요.")
        else:
            bench = (df_all[df_all["region"].isin(bench_sel)]
                     .groupby("ym")["price_man"].mean().sort_index())
            b = A.regional_beta(price, bench)
            k = st.columns(3)
            k[0].metric("베타", "-" if b["beta"] is None else f"{b['beta']:.2f}")
            k[1].metric("설명력 R²", "-" if b["r2"] is None else f"{b['r2']:.2f}")
            k[2].metric("표본", f"{b['n']}개월")
            st.info(A.beta_label(b))

            if b["beta"] is not None:
                tc, bc = A.to_changes(price), A.to_changes(bench)
                mg = pd.concat([tc.rename("t"), bc.rename("b")], axis=1).dropna()
                fig2 = go.Figure()
                fig2.add_trace(go.Scatter(
                    x=mg["b"] * 100, y=mg["t"] * 100, mode="markers",
                    marker=dict(color=PALETTE[0], size=7, opacity=0.7), name="월별",
                    hovertemplate="시장 %{x:.1f}% → 내 지역 %{y:.1f}%<extra></extra>"))
                xs = np.linspace(mg["b"].min(), mg["b"].max(), 50)
                fig2.add_trace(go.Scatter(
                    x=xs * 100, y=(b["alpha"] + b["beta"] * xs) * 100, mode="lines",
                    line=dict(color=PALETTE[3], width=2), name=f"베타 {b['beta']:.2f}"))
                fig2.add_trace(go.Scatter(
                    x=xs * 100, y=xs * 100, mode="lines",
                    line=dict(color="#aaa", width=1, dash="dash"), name="베타 1 (시장과 동일)"))
                fig2.update_layout(
                    height=320, margin=dict(l=8, r=8, t=8, b=8),
                    plot_bgcolor="white", paper_bgcolor="white",
                    legend=dict(orientation="h", x=0, y=1.12, font=dict(size=11)),
                    xaxis=dict(title="시장 월간 변화율(%)", showgrid=True, gridcolor="#f0f0f0", fixedrange=True),
                    yaxis=dict(title=f"{region} 월간 변화율(%)", showgrid=True, gridcolor="#f0f0f0", fixedrange=True))
                st.plotly_chart(fig2, use_container_width=True, config=CHART_CONFIG, key="ml_beta")
                st.caption(
                    f"벤치마크: {', '.join(bench_sel)} · R²는 시장으로 설명되는 비율입니다 — "
                    "낮으면 내 지역이 시장과 따로 논다는 뜻이고, 그만큼 지역 고유 요인"
                    "(공급·개발호재 등)이 크게 작용합니다."
                )

# ══════════════════════════════════════════════════════════════
# ③ 전이 경로
# ══════════════════════════════════════════════════════════════
with tab3:
    st.markdown("#### 신호가 어디서 끊기는가")
    st.caption(
        "글로벌 금리 → 한국 금리 → 주담대 금리 → 거래량 → 내 지역 가격처럼 경로가 긴 관계는 "
        "양끝만 맞대보면 중간이 다 섞여 해석이 안 됩니다. **인접 단계끼리만** 재야 "
        "어느 고리가 약한지 드러납니다."
    )
    stages = []
    for name, s in list(rate_series.items())[:2]:
        stages.append((f"금리·{name[:16]}", s))
    stages.append(("거래량", volume))
    stages.append((f"{region} 가격", price))

    if len(stages) < 3:
        st.warning(
            "금리 데이터가 없어 경로가 **거래량 → 가격** 한 고리뿐입니다. "
            "**🏦 금리 수집(ECOS)** 메뉴에서 기준금리·주담대금리를 수집하면 "
            "글로벌·한국 금리 단계가 채워집니다."
        )
    chain = A.transmission_chain(stages, max_lag=max_lag)
    if chain.empty:
        st.info("단계를 구성할 데이터가 부족합니다.")
    else:
        st.dataframe(chain, use_container_width=True, hide_index=True)
        weak = chain[~chain["유의"]]
        if not weak.empty:
            st.info(
                "**끊긴 고리**: " + ", ".join(weak["단계"].tolist()) +
                " — 이 구간에서 신호가 통계적으로 확인되지 않습니다. 관계가 없을 수도, "
                "지역 고유 요인(공급·개발호재)에 묻혔을 수도, 표본이 부족할 수도 있습니다."
            )
        st.caption(
            "'유의'는 다중비교 보정을 거친 판정입니다. 보정 없이 25개 시차를 훑으면 "
            "무관한 계열끼리도 68% 확률로 '유의한 시차'가 나옵니다 (보정 시 4%)."
        )

# ══════════════════════════════════════════════════════════════
# ④ 유사 국면
# ══════════════════════════════════════════════════════════════
with tab4:
    st.markdown("#### 지금과 비슷했던 과거, 그 뒤엔 어떻게 됐나")
    st.caption(
        "**예측이 아니라 사례 제시입니다.** 지금 국면과 지표 구성이 비슷했던 과거 구간을 찾아 "
        "그 뒤 가격이 어떻게 움직였는지 보여줍니다. 표본이 짧으면 사례가 1~2개뿐일 수 있고, "
        "그조차 우연일 수 있습니다."
    )
    cfg = st.columns(3)
    window = cfg[0].slider("국면 길이 (개월)", 3, 12, 6)
    horizon = cfg[1].slider("이후 관찰 기간 (개월)", 3, 24, 12)
    topk = cfg[2].slider("사례 개수", 1, 5, 3)

    feat_parts = {"가격변화": price.pct_change(), "거래량": volume}
    if len(jeonse_ratio) >= 6:
        feat_parts["전세가율"] = jeonse_ratio
    for nm, s in list(rate_series.items())[:2]:
        feat_parts[f"금리{nm[:8]}"] = s.reindex(price.index).ffill()

    feats = pd.DataFrame(feat_parts).reindex(price.index)
    need = window + horizon + window
    if len(price) < need:
        st.warning(
            f"국면 비교에는 최소 **{need}개월**이 필요한데 현재 **{len(price)}개월**입니다 "
            f"(국면 {window} + 이후 {horizon} + 비교대상 {window}). "
            "수집 범위를 60개월로 늘리거나 국면/관찰 기간을 줄여보세요."
        )
    else:
        matches = A.find_similar_regimes(feats, price, window=window, horizon=horizon, top_k=topk)
        if matches.empty:
            st.info("비슷한 구간을 찾지 못했습니다.")
        else:
            show = matches.copy()
            for col in ("시작", "종료"):
                show[col] = pd.to_datetime(show[col]).dt.strftime("%Y-%m")
            st.dataframe(show, use_container_width=True, hide_index=True)
            st.info(A.regime_summary(matches, horizon))
            st.caption(
                "'거리'는 지표 구성이 얼마나 닮았는지입니다 — 0에 가까울수록 닮았고, "
                "값이 크면 사실 닮지 않은 구간입니다. 사용한 지표: "
                + ", ".join(feats.columns)
            )
