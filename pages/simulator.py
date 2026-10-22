"""
pages/simulator.py — 보유 시나리오 시뮬레이터 & 시장 신호 종합

이미 수집해둔 실거래(rtms_transactions/rtms_jeonse)와 KOSIS 통계만으로,
"지금 내 자산이 어떤 상태이고 앞으로 무엇을 보고 판단해야 하는가"를 계산한다.
외부 API를 호출하지 않으므로 수집 주기와 무관하게 언제든 열어볼 수 있다.

계산 로직은 utils_market.py(순수 함수)에 있고 이 파일은 입력·레이아웃만 담당한다.
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils_style import inject_korean_font
from utils_area_trend import (
    CHART_CONFIG, PALETTE, JEONSE_COLOR, KOSIS_CAT_ICON, KOSIS_CAT_SHORT,
    lawd_label, load_data, load_jeonse, load_kosis, load_ecos,
    monthly_stats, kosis_city_keyword, match_kosis_region, kosis_summary,
)
import utils_market as mk

inject_korean_font()

# CLAUDE.md에 기록된 실제 보유 조건을 기본값으로 둔다 — 매번 입력하지 않아도
# 열자마자 내 상황이 나오고, 조건을 바꿔보고 싶을 때만 건드리면 된다.
DEFAULT_APT_KEYWORD = "센트럴자이"
DEFAULT_APT_SUFFIX = "2단지"
DEFAULT_PURCHASE_EOK = 3.20
DEFAULT_LOAN_EOK = 1.00
DEFAULT_RATE = 4.75
DEFAULT_MONTHS = 480
DEFAULT_FIRST_PAYMENT = 335_000   # 체증식 1회차(추정) — 실제 상환일정표 값으로 바꾸면 정확해짐

LEVEL_STYLE = {
    "good":    ("✅", "#16a34a", "#dcfce7"),
    "neutral": ("➖", "#a16207", "#fef9c3"),
    "bad":     ("⚠️", "#dc2626", "#fee2e2"),
}

st.title("보유 시나리오 시뮬레이터")
st.caption(
    "수집된 실거래·통계만으로 **대출 상환**, **가격 시나리오별 손익**, **시장 신호**를 계산합니다. "
    "외부 API를 호출하지 않으니 수집을 돌리지 않아도 바로 볼 수 있습니다."
)

df_all = load_data()
if df_all.empty:
    st.warning("수집된 실거래가가 없습니다. **🏛️ 실거래가 수집** 메뉴에서 먼저 수집해주세요.")
    st.stop()

df_jeonse_all = load_jeonse()
df_all = mk.add_derived(df_all)

# ══════════════════════════════════════════════════════════════
# 사이드바 — 내 단지와 보유 조건
# ══════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("**분석 대상 단지**")
    apt_list = sorted(df_all["apt_name"].dropna().unique())
    default_apt = next(
        (a for a in apt_list if DEFAULT_APT_KEYWORD in a and DEFAULT_APT_SUFFIX in a),
        apt_list[0] if apt_list else None,
    )
    apt = st.selectbox("단지", apt_list, index=apt_list.index(default_apt) if default_apt else 0)

    dfc_all_area = df_all[df_all["apt_name"] == apt]
    areas = sorted(dfc_all_area["area"].dropna().round(1).unique())
    area_opts = ["전체"] + [f"{a:.1f}㎡ ({a / mk.PYEONG:.0f}평)" for a in areas]
    sel_area_label = st.selectbox("평형", area_opts, index=0)
    if sel_area_label == "전체":
        dfc = dfc_all_area
    else:
        target = areas[area_opts.index(sel_area_label) - 1]
        dfc = dfc_all_area[dfc_all_area["area"].round(1) == target]

    st.divider()
    st.markdown("**매수 조건**")
    purchase_eok = st.number_input("매수가 (억)", 0.5, 50.0, DEFAULT_PURCHASE_EOK, 0.05)
    acq_pct = st.number_input("취득세율 (%)", 0.0, 15.0, mk.ACQUISITION_TAX_RATE * 100, 0.1,
                              help="6억 이하·전용 85㎡ 이하 1주택 기준 1.1%(지방교육세 포함)")
    broker_pct = st.number_input("중개보수율 (%)", 0.0, 2.0, mk.BROKER_FEE_RATE * 100, 0.05,
                                 help="2억~9억 구간 상한 0.4%. 매수·매도 양쪽에 적용됩니다.")

    st.divider()
    st.markdown("**대출 조건**")
    loan_eok = st.number_input("대출금 (억)", 0.0, 20.0, DEFAULT_LOAN_EOK, 0.05)
    rate = st.number_input("금리 (연 %)", 0.0, 15.0, DEFAULT_RATE, 0.05)
    months = int(st.number_input("기간 (개월)", 12, 600, DEFAULT_MONTHS, 12))
    repay_kind = st.radio("상환방식", ["원리금체증식", "원리금균등"], horizontal=True)
    first_pay = None
    if repay_kind == "원리금체증식":
        first_pay = st.number_input(
            "1회차 납입액 (원)", 0, 5_000_000, DEFAULT_FIRST_PAYMENT, 5_000,
            help="주택금융공사 상환일정표의 실제 1회차 금액을 넣으면 체증률을 역산해 "
                 "이후 스케줄을 실제와 가깝게 그립니다.",
        )

    st.divider()
    # 손익분기와 시나리오가 같은 전제 위에서 계산되도록 보유기간은 한 곳에서만 받는다
    held_years = st.slider("보유 기간 (년)", 0, 40, 5,
                           help="이 기간 동안 낸 이자를 비용에 넣고, 그 시점의 대출잔액으로 손익을 계산합니다.")

purchase = purchase_eok * 10000      # 만원 단위로 통일 (실거래 price_man과 같은 단위)
loan = loan_eok * 10000
acq_rate, brk_rate = acq_pct / 100, broker_pct / 100

if dfc.empty:
    st.warning(f"**{apt}** — 선택한 평형의 거래 데이터가 없습니다. 사이드바에서 평형을 넓혀보세요.")
    st.stop()

# ── 대출 스케줄은 손익분기(1장)와 시나리오(3장) 양쪽이 쓰므로 먼저 한 번만 계산한다 ──
sched = eq_sched = pd.DataFrame()
growth = None
if loan > 0:
    principal_won = loan * 10000        # 만원 → 원
    if repay_kind == "원리금체증식":
        growth = mk.solve_growth_for_first_payment(principal_won, rate, months, first_pay)
        if growth is None:
            st.error(
                f"1회차 {first_pay:,}원은 이 조건(원금 {loan_eok}억 · {rate}% · {months}개월)에서 "
                "만들 수 없는 금액입니다. 사이드바에서 금액을 조정해주세요."
            )
            st.stop()
        sched = mk.amortization_schedule(principal_won, rate, months, "graduated", growth)
    else:
        sched = mk.amortization_schedule(principal_won, rate, months, "equal")
    eq_sched = mk.amortization_schedule(principal_won, rate, months, "equal")

# 보유기간 시점의 누적이자와 대출잔액 (원 → 만원)
held_interest, balance_at = 0.0, loan
if not sched.empty and held_years > 0:
    upto = sched[sched["month"] <= held_years * 12]
    if not upto.empty:
        held_interest = float(upto["interest"].sum()) / 10000
        balance_at = float(upto["balance"].iloc[-1]) / 10000

# ══════════════════════════════════════════════════════════════
# 1. 현재 시세와 손익
# ══════════════════════════════════════════════════════════════
stats = monthly_stats(dfc)
recent = dfc[dfc["ym"] >= dfc["ym"].max() - pd.DateOffset(months=6)]
market_price = float(recent["price_man"].median()) if not recent.empty else float(dfc["price_man"].median())

st.subheader("1. 현재 시세와 손익")
c = st.columns(4)
c[0].metric("최근 6개월 중앙값", f"{market_price / 10000:.2f}억",
            f"{(market_price - purchase) / 10000:+.2f}억 (매수가 대비)")
c[1].metric("거래 건수", f"{len(recent):,}건", help="최근 6개월 기준")

be = mk.breakeven_price(purchase, held_interest, acq_rate, brk_rate)
c[2].metric(f"손익분기 매도가 ({held_years}년 보유)", f"{be / 10000:.2f}억",
            help="취득세·중개보수에 보유기간 이자까지 회수하려면 최소 이 가격에 팔아야 본전입니다.")
gap = market_price - be
c[3].metric("손익분기까지", f"{gap / 10000:+.2f}억",
            delta=("이익 구간" if gap >= 0 else "손실 구간"),
            delta_color="normal" if gap >= 0 else "inverse")

st.caption(
    f"현재 시세는 **{apt}**의 최근 6개월 실거래 중앙값입니다 (평균은 특이 거래에 끌려다녀 중앙값을 씁니다). "
    f"손익분기에는 취득세·중개보수(양방)와 **{held_years}년치 이자 {held_interest:,.0f}만원**이 들어가 있고, "
    "1세대 1주택 2년 보유 양도세 비과세를 가정해 양도세는 제외했습니다."
)

# ══════════════════════════════════════════════════════════════
# 2. 대출 상환 시뮬레이션
# ══════════════════════════════════════════════════════════════
st.divider()
st.subheader("2. 대출 상환 시뮬레이션")

if sched.empty:
    st.info("대출금이 0이라 상환 시뮬레이션을 건너뜁니다.")
else:
    summ, eq_summ = mk.loan_summary(sched), mk.loan_summary(eq_sched)

    k = st.columns(4)
    k[0].metric("1회차 납입액", f"{sched['payment'].iloc[0]:,.0f}원")
    k[1].metric("최종회차 납입액", f"{sched['payment'].iloc[-2]:,.0f}원" if len(sched) > 1 else "-")
    k[2].metric("총 이자", f"{summ['total_interest'] / 10000:,.0f}만원")
    if repay_kind == "원리금체증식":
        k[3].metric("균등상환 대비", f"{(summ['total_interest'] - eq_summ['total_interest']) / 10000:+,.0f}만원",
                    delta="이자 더 냄", delta_color="inverse")
    else:
        k[3].metric("월 납입액", f"{sched['payment'].iloc[0]:,.0f}원")

    if growth is not None:
        st.caption(f"역산된 체증률: **연 {growth:.2f}%** (1회차 {first_pay:,}원 기준)")

    # 체증식의 핵심 리스크 — 초기 납입액이 이자보다 적으면 잔액이 오히려 늘어난다.
    if summ["negative_amort_months"] > 0:
        yrs = summ["negative_amort_months"] / 12
        st.warning(
            f"⚠️ **초기 {summ['negative_amort_months']}개월({yrs:.1f}년) 동안 원금이 줄지 않고 늘어납니다.** "
            f"납입액이 이자({principal_won * rate / 100 / 12:,.0f}원/월)보다 적은 구간이기 때문입니다. "
            f"잔액은 최대 **{summ['peak_balance'] / 10000:,.0f}만원**까지 늘었다가 줄기 시작합니다 "
            f"(원금 {loan_eok}억). 이 기간에 집을 팔면 갚아야 할 돈이 처음 빌린 돈보다 많습니다."
        )

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=sched["month"], y=sched["balance"] / 10000, name="대출잔액",
                             line=dict(color=PALETTE[0], width=2),
                             hovertemplate="%{x}회차 잔액 %{y:,.0f}만원<extra></extra>"))
    fig.add_trace(go.Scatter(x=sched["month"], y=sched["payment"] / 10000, name="월 납입액",
                             yaxis="y2", line=dict(color=PALETTE[1], width=2),
                             hovertemplate="%{x}회차 납입 %{y:,.1f}만원<extra></extra>"))
    if repay_kind == "원리금체증식":
        fig.add_trace(go.Scatter(x=eq_sched["month"], y=eq_sched["payment"] / 10000, name="균등상환(비교)",
                                 yaxis="y2", line=dict(color="#999", width=1.5, dash="dash"),
                                 hovertemplate="%{x}회차 균등 %{y:,.1f}만원<extra></extra>"))
    fig.update_layout(
        height=300, margin=dict(l=8, r=8, t=8, b=8),
        plot_bgcolor="white", paper_bgcolor="white",
        legend=dict(orientation="h", x=0, y=1.12, font=dict(size=11)),
        hovermode="x unified",
        yaxis=dict(title="잔액(만원)", showgrid=True, gridcolor="#f0f0f0", fixedrange=True),
        yaxis2=dict(title="월 납입(만원)", overlaying="y", side="right", showgrid=False, fixedrange=True),
        xaxis=dict(title="회차(개월)", showgrid=True, gridcolor="#f0f0f0", fixedrange=True),
    )
    st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG, key="sim_loan")
    st.caption(
        "잔액(왼쪽 축)과 월 납입액(오른쪽 축)은 단위가 달라 축을 나눴습니다 — 두 선의 "
        "높낮이를 서로 비교하지 마시고, 각자의 기울기만 보세요."
    )

    # ── 금리 시나리오 — 수집한 ECOS 금리를 내 대출 조건에 직접 대본다 ──
    st.markdown("**금리가 바뀌면**")
    df_ecos = load_ecos()
    market_rate = None
    if not df_ecos.empty:
        loan_rows = df_ecos[df_ecos["item_name"].fillna("").str.contains("주택담보|대출금리", regex=True)]
        if not loan_rows.empty:
            latest = loan_rows.sort_values("period").iloc[-1]
            market_rate = float(latest["value"])
            diff = rate - market_rate
            st.caption(
                f"수집된 시장금리: **{latest['item_name']} {market_rate:.2f}%** ({latest['period']}) · "
                f"내 금리 {rate:.2f}% → **{diff:+.2f}%p** "
                + ("— 시장금리가 더 낮습니다. 갈아타기 시 중도상환수수료·한도를 따져볼 만합니다."
                   if diff > 0.3 else "— 지금 금리가 시장보다 불리하지 않습니다.")
            )
    if market_rate is None:
        st.caption(
            "💡 **🏦 금리 수집(ECOS)** 메뉴에서 금리를 수집하면 여기에 시장금리와 내 금리를 "
            "나란히 비교해 드립니다."
        )

    cand = sorted({round(rate + d, 2) for d in (-1.5, -1.0, -0.5, 0, 0.5, 1.0, 1.5)}
                  | ({round(market_rate, 2)} if market_rate else set()))
    rs = mk.rate_scenarios(principal_won, months, [r for r in cand if r > 0],
                           kind="graduated" if repay_kind == "원리금체증식" else "equal",
                           annual_growth_pct=growth or 0.0, current_rate=rate)
    st.dataframe(rs, use_container_width=True, hide_index=True)
    st.caption(
        f"현재 금리 **{rate:.2f}%** 기준으로 비교한 값입니다. 고정금리라도 "
        "시장금리가 충분히 내려가면 갈아타기를 검토할 근거가 됩니다 "
        "(실제 판단에는 중도상환수수료와 대출 한도를 함께 봐야 합니다)."
    )

# ══════════════════════════════════════════════════════════════
# 3. 가격 시나리오
# ══════════════════════════════════════════════════════════════
st.divider()
st.subheader("3. 가격 시나리오별 손익")

sc = mk.equity_scenarios(purchase, market_price, balance_at,
                         held_interest=held_interest, acq_tax_rate=acq_rate, broker_rate=brk_rate)
st.dataframe(sc, use_container_width=True, hide_index=True)
st.caption(
    f"**{held_years}년 보유** 기준 — 그동안 낸 이자 **{held_interest:,.0f}만원**을 비용에 넣고, "
    f"그 시점 대출잔액 **{balance_at / 10000:.2f}억**을 갚는다고 가정했습니다. "
    "변동률은 매수가가 아니라 **현재 시세** 기준입니다. 양도세는 1세대 1주택 비과세 가정으로 제외했습니다."
)

# ══════════════════════════════════════════════════════════════
# 4. 시장 신호 종합
# ══════════════════════════════════════════════════════════════
st.divider()
st.subheader("4. 시장 신호 종합")

region_key = lawd_label(dfc["lawd_cd"].iloc[0])
price_mom = mk.momentum(stats["avg"], 3)
vol_mom = mk.momentum(stats["count"], 3)

jr = mk.jeonse_ratio_series(
    dfc, df_jeonse_all[df_jeonse_all["apt_name"] == apt] if not df_jeonse_all.empty else pd.DataFrame()
)
jeonse_now = float(jr["ratio"].iloc[-1]) if not jr.empty else None

permit_mom = pop_mom = None
df_kosis = load_kosis()
if not df_kosis.empty:
    city, gu = kosis_city_keyword(region_key)
    for cat, slot in (("housing", "permit"), ("population", "pop")):
        cat_df = df_kosis[df_kosis["category"] == cat]
        matched = match_kosis_region(city, gu, sorted(cat_df["region_name"].dropna().unique()))
        summary = kosis_summary(cat_df, matched) if matched else None
        if summary is not None and len(summary["df"]) >= 4:
            v = mk.momentum(summary["df"]["value"], 2)   # 연 단위라 2년 vs 2년
            if slot == "permit":
                permit_mom = v
            else:
                pop_mom = v

signals = mk.assess_market(price_mom, vol_mom, jeonse_now, permit_mom, pop_mom)
if not signals:
    st.info("신호를 계산할 데이터가 아직 부족합니다. 수집 기간이 늘어나면 자동으로 채워집니다.")
else:
    for s in signals:
        icon, fg, bg = LEVEL_STYLE[s["level"]]
        st.markdown(
            f"<div style='background:{bg};border-left:4px solid {fg};border-radius:6px;"
            f"padding:10px 14px;margin-bottom:8px'>"
            f"<strong style='color:{fg}'>{icon} {s['title']}</strong><br>"
            f"<span style='color:#444;font-size:13px'>{s['detail']}</span></div>",
            unsafe_allow_html=True,
        )
    st.caption(
        f"대상 지역: **{region_key}** · 가격·거래량은 **{apt}** 기준, 인허가·인구는 시/군 전체 기준입니다. "
        "지표마다 시차가 달라(인허가 2~3년 선행, 거래량 동행) 하나의 점수로 합치지 않았습니다 — "
        "각 줄을 따로 보고 판단하세요."
    )

# ══════════════════════════════════════════════════════════════
# 5. 파생 분석 — 평당가 / 연식 / 층
# ══════════════════════════════════════════════════════════════
st.divider()
st.subheader("5. 무엇이 가격을 가르는가 (평당가·연식·층)")
st.caption(
    "수집은 해왔지만 지금까지 어느 화면에서도 쓰지 않던 **건축년도·층** 정보를 평당가와 함께 봅니다. "
    f"비교 범위는 **{region_key}** 전체 거래입니다 — 단지 하나만 보면 표본이 적어 층·연식 차이가 묻힙니다."
)

region_df = df_all[df_all["lawd_cd"] == dfc["lawd_cd"].iloc[0]]
tabs = st.tabs(["연식별", "층별", "평형별"])
for tab, col, label in zip(tabs, ["age_bucket", "floor_bucket", "area_label"], ["연식", "층", "평형"]):
    with tab:
        prof = mk.bucket_profile(region_df, col)
        if prof.empty:
            st.caption(f"{label} 정보를 가진 거래가 없습니다.")
            continue
        prof = prof[prof["건수"] >= 5].sort_values("중앙값", ascending=False)
        if prof.empty:
            st.caption(f"표본 5건 이상인 {label} 구간이 없습니다.")
            continue
        fig_b = go.Figure(go.Bar(
            x=prof[col], y=prof["중앙값"], marker_color=PALETTE[2],
            text=[f"{v:,.0f}" for v in prof["중앙값"]], textposition="outside",
            hovertemplate="%{x}<br>중앙값 %{y:,.0f}만원/평<extra></extra>",
        ))
        fig_b.update_layout(
            height=260, margin=dict(l=8, r=8, t=8, b=8),
            plot_bgcolor="white", paper_bgcolor="white", showlegend=False,
            yaxis=dict(title="평당가(만원)", showgrid=True, gridcolor="#f0f0f0", fixedrange=True),
            xaxis=dict(fixedrange=True),
        )
        st.plotly_chart(fig_b, use_container_width=True, config=CHART_CONFIG, key=f"sim_prof_{col}")
        st.dataframe(prof.rename(columns={col: label, "평균": "평균(만원/평)", "중앙값": "중앙값(만원/평)"}),
                     use_container_width=True, hide_index=True)
