# pages/loan_info.py  — 보금자리론 대출 정보
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from utils_style import inject_korean_font

st.set_page_config(page_title="보금자리론 대출 정보", layout="wide")
inject_korean_font()

# ── 공통 CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* keyboard_double 버튼 숨기기 */
[data-testid="stBaseButton-headerNoPadding"],
button[aria-label="keyboard_double_arrow_left"],
button[aria-label="keyboard_double_arrow_right"],
[kind="headerNoPadding"] { display: none !important; }

.sec {
    font-size: 15px; font-weight: 700; color: #1e293b;
    border-left: 4px solid #6366f1; padding-left: 8px;
    margin: 18px 0 10px 0;
}
.kpi-card {
    background: #fff; border: 1px solid #e2e8f0; border-radius: 10px;
    padding: 14px 16px; text-align: center;
}
.kpi-label { font-size: 11px; color: #94a3b8; margin-bottom: 4px; }
.kpi-value { font-size: 20px; font-weight: 800; color: #1e293b; }
.kpi-sub   { font-size: 11px; color: #64748b; margin-top: 3px; }
.badge-ok  { background:#dcfce7; color:#16a34a; border-radius:4px;
             padding:2px 8px; font-size:12px; font-weight:700; }
.repay-row { border-bottom: 1px solid #f1f5f9; }
.memo-box  {
    background: #fefce8; border: 1px solid #fde047;
    border-left: 4px solid #eab308;
    border-radius: 8px; padding: 14px 18px; margin-top: 6px;
}
.memo-title { font-size: 13px; font-weight: 700; color: #92400e; margin-bottom: 8px; }
.memo-row   { font-size: 13px; color: #78350f; margin-bottom: 5px; line-height: 1.6; }
</style>
""", unsafe_allow_html=True)

st.title("🏦 보금자리론 대출 정보")
st.caption("사전심사 기준 · 2026년 3월")

# ════════════════════════════════════════════════════════════
# [1] 사전심사 결과 KPI 카드
# ════════════════════════════════════════════════════════════
st.markdown('<div class="sec">📋 사전심사 결과</div>', unsafe_allow_html=True)

# 대출 가능 배지
st.markdown('<span class="badge-ok">✅ 대출 가능</span>', unsafe_allow_html=True)
st.write("")

c1, c2, c3, c4, c5, c6 = st.columns(6)

def kpi(col, label, value, sub=""):
    col.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{value}</div>
        {"<div class='kpi-sub'>" + sub + "</div>" if sub else ""}
    </div>""", unsafe_allow_html=True)

kpi(c1, "최대 대출금액",   "2억 2,750만원",  "227,500,000원")
kpi(c2, "실행 대출금액",   "2억 2,700만원",  "227,000,000원")
kpi(c3, "금리",            "4.20%",           "고정 · 40년")
kpi(c4, "LTV",             "69.85%",          "담보인정비율")
kpi(c5, "DTI",             "18.91%",          "총부채상환비율")
kpi(c6, "선택 상환방식",   "체증식",           "월 부담 최소화")

# ════════════════════════════════════════════════════════════
# [2] 상환방식 비교
# ════════════════════════════════════════════════════════════
st.markdown('<div class="sec">📊 상환방식 비교</div>', unsafe_allow_html=True)

col_tbl, col_chart = st.columns([1, 1])

with col_tbl:
    repay = pd.DataFrame([
        {"방식": "체감식",     "월 납입금":      "128만~47만원",         "총 이자": "191,106,592원",
         "이자_정렬": 191_106_592, "선택": ""},
        {"방식": "원리금균등", "월 납입금":      "977,150원 (고정)",     "총 이자": "242,186,477원",
         "이자_정렬": 242_186_477, "선택": ""},
        {"방식": "체증식",     "월 납입금":      "809,736~1,564,743원",  "총 이자": "271,643,161원",
         "이자_정렬": 271_643_161, "선택": "✅ 선택"},
    ])
    st.dataframe(
        repay[["방식", "월 납입금", "총 이자", "선택"]],
        use_container_width=True,
        hide_index=True,
    )
    st.caption("※ 체감식이 총 이자 가장 적음 · 체증식은 초기 월 부담 가장 낮음")

with col_chart:
    methods  = ["체감식", "원리금균등", "체증식"]
    interest = [191_106_592, 242_186_477, 271_643_161]
    colors   = ["#94a3b8", "#94a3b8", "#6366f1"]   # 선택 항목 강조

    fig = go.Figure(go.Bar(
        x=methods, y=interest,
        marker_color=colors,
        text=[f"{v/1e8:.2f}억" for v in interest],
        textposition="outside",
    ))
    fig.update_layout(
        title="총 이자 비교 (40년 기준)",
        yaxis_title="원",
        yaxis_tickformat=",",
        plot_bgcolor="white",
        height=280,
        margin=dict(l=0, r=0, t=40, b=0),
        showlegend=False,
    )
    fig.update_yaxes(showgrid=True, gridcolor="#f1f5f9")
    st.plotly_chart(fig, use_container_width=True)

# ════════════════════════════════════════════════════════════
# [3] 월납입금 흐름 비교 (체증식 vs 원리금균등)
# ════════════════════════════════════════════════════════════
st.markdown('<div class="sec">📈 월납입금 흐름 (40년)</div>', unsafe_allow_html=True)

years = list(range(1, 41))

# 체증식: 809,736 → 1,564,743 (선형 근사)
cheujeung = [int(809_736 + (1_564_743 - 809_736) / 39 * (y - 1)) for y in years]

# 체감식: 1,280,000 → 470,000 (선형 근사)
cheugam   = [int(1_280_000 + (470_000 - 1_280_000) / 39 * (y - 1)) for y in years]

# 원리금균등: 고정
equal     = [977_150] * 40

fig2 = go.Figure()
fig2.add_trace(go.Scatter(x=years, y=cheujeung, name="체증식 (선택)",
                           line=dict(color="#6366f1", width=2.5)))
fig2.add_trace(go.Scatter(x=years, y=equal,     name="원리금균등",
                           line=dict(color="#f59e0b", width=1.5, dash="dash")))
fig2.add_trace(go.Scatter(x=years, y=cheugam,   name="체감식",
                           line=dict(color="#94a3b8", width=1.5, dash="dot")))

# 3년 / 5년 매도 구간 표시
fig2.add_vrect(x0=0, x1=3, fillcolor="#fee2e2", opacity=0.25, line_width=0,
               annotation_text="3년↓ 수수료", annotation_position="top left",
               annotation_font_size=10)
fig2.add_vrect(x0=3, x1=5, fillcolor="#fef9c3", opacity=0.3, line_width=0,
               annotation_text="3~5년 목표", annotation_position="top left",
               annotation_font_size=10)

fig2.update_layout(
    xaxis_title="경과 연수", yaxis_title="월납입금 (원)",
    yaxis_tickformat=",",
    plot_bgcolor="white",
    height=300,
    margin=dict(l=0, r=0, t=20, b=0),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
)
fig2.update_yaxes(showgrid=True, gridcolor="#f1f5f9")
st.plotly_chart(fig2, use_container_width=True)

# ════════════════════════════════════════════════════════════
# [4] 투자 전략 메모
# ════════════════════════════════════════════════════════════
st.markdown('<div class="sec">💡 투자 전략 메모</div>', unsafe_allow_html=True)

st.markdown("""
<div class="memo-box">
    <div class="memo-title">📝 나의 투자 전략 (2026.03 기준)</div>
    <div class="memo-row">📅 <b>보유 기간</b> &nbsp;·&nbsp; 3~5년 단기 매도 목표</div>
    <div class="memo-row">📌 <b>전략</b> &nbsp;·&nbsp; 체증식 선택으로 초기 월 부담 최소화 → 전세 수익 활용 → 시세차익 매도</div>
    <div class="memo-row">⚠️ <b>주의 (3년 이내 매도)</b> &nbsp;·&nbsp; 중도상환수수료 최대 <b>0.5%</b> 발생
        &nbsp;→&nbsp; 대출 2.27억 기준 약 <b>113만원</b></div>
    <div class="memo-row">✅ <b>3년 이후 매도</b> &nbsp;·&nbsp; 중도상환수수료 <b>없음</b> → 3년 이후 매도 권장</div>
</div>
""", unsafe_allow_html=True)

# ── 중도상환수수료 계산기 ────────────────────────────────────────────────
st.write("")
with st.expander("🧮 중도상환수수료 간이 계산기"):
    c_left, c_right = st.columns(2)
    with c_left:
        loan_amt = st.number_input("대출 잔액 (만원)", value=22700, step=100)
    with c_right:
        hold_yr = st.slider("보유 기간 (년)", 0, 5, 2)

    st.divider()
    if hold_yr < 3:
        rate = 0.005 * (3 - hold_yr) / 3
        fee  = int(loan_amt * 10000 * rate)
        st.error(f"⚠️ 예상 수수료: **{fee:,}원** (약 {fee/10000:.0f}만원) — {hold_yr}년 보유 기준")
    else:
        st.success("✅ 3년 이상 보유 시 중도상환수수료 없음")
