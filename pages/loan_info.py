# pages/loan_info.py  — 보금자리론 대출 정보
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from utils_style import inject_korean_font
from utils_auth import require_auth

inject_korean_font()
require_auth()

# ── 공통 CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* expander 아이콘(arrow_drop_down 텍스트) 숨기기 */
[data-testid="stExpander"] summary .material-icons,
[data-testid="stExpander"] summary span[class*="material"],
[data-testid="stExpander"] details summary > span:first-child {
    font-size: 0 !important;
    width: 0 !important;
    overflow: hidden !important;
    display: none !important;
}
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

st.markdown("#### 🏦 보금자리론 대출 정보")
st.caption("사전심사 기준 · 2026년 3월")

# ════════════════════════════════════════════════════════════
# [1] 사전심사 결과 KPI 카드
# ════════════════════════════════════════════════════════════
st.markdown('<div class="sec">📋 사전심사 결과</div>', unsafe_allow_html=True)
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
# [2] 대출 계산기 (대출금액·금리·기간 변경 가능)
# ════════════════════════════════════════════════════════════
st.markdown('<div class="sec">🧮 월납입금 계산기</div>', unsafe_allow_html=True)

ci1, ci2, ci3 = st.columns(3)
loan_man  = ci1.number_input("대출금액 (만원)", min_value=1000, max_value=50000,
                              value=22700, step=100)
rate_pct  = ci2.number_input("연 금리 (%)", min_value=1.0, max_value=10.0,
                              value=4.20, step=0.05, format="%.2f")
term_yr   = ci3.selectbox("대출 기간", [10, 15, 20, 25, 30, 35, 40], index=6)

P  = loan_man * 10_000       # 원 단위
r  = rate_pct / 100 / 12     # 월 이율
n  = term_yr * 12             # 총 개월


def calc_equal(P, r, n):
    """원리금균등상환 월납입금"""
    if r == 0: return P / n
    return P * r * (1 + r)**n / ((1 + r)**n - 1)


def calc_cheugam_schedule(P, r, n):
    """체감식(원금균등) 연도별 월납입금 (첫달, 마지막달)"""
    principal = P / n
    rows = []
    for yr in range(1, n // 12 + 1):
        month = (yr - 1) * 12 + 1
        rem   = P - principal * (month - 1)
        pay   = principal + rem * r
        rows.append(round(pay))
    return rows


def calc_cheujeung_schedule(P, r, n, g_annual=0.03):
    """체증식: 연 g_annual 비율로 월납입금 증가, NPV = P 유지"""
    g = (1 + g_annual) ** (1/12) - 1   # 월 증가율
    years = n // 12
    # 첫달 납입금 P1 계산: sum P1*(1+g)^t / (1+r)^t = P
    denom = sum(((1+g)/(1+r))**t for t in range(n))
    P1 = P / denom if denom else 0
    rows = []
    for yr in range(years):
        t   = yr * 12
        pay = P1 * (1+g)**t
        rows.append(round(pay))
    return rows


# ── 계산 ─────────────────────────────────────
equal_monthly  = calc_equal(P, r, n)
cheugam_rows   = calc_cheugam_schedule(P, r, n)
cheujeung_rows = calc_cheujeung_schedule(P, r, n)

# 총이자
total_equal    = equal_monthly * n - P
total_cheugam  = sum(
    P/n + (P - P/n*(m-1)) * r
    for m in range(1, n+1)
) - P
total_cheujeung = sum(
    calc_equal(P, r, n) * (1.03**(t/12)) * 1  # 근사
    for t in range(n)
)
# 정확한 총이자는 실제 스케줄 합산
g = (1.03)**(1/12) - 1
P1 = P / sum(((1+g)/(1+r))**t for t in range(n))
total_cheujeung = sum(P1*(1+g)**t for t in range(n)) - P

# ── 요약 표 ──────────────────────────────────
st.markdown("##### 상환방식 비교 요약")
col_tbl, col_chart = st.columns([3, 2])

with col_tbl:
    summary = pd.DataFrame([
        {
            "상환방식": "체감식 (원금균등)",
            "첫달 납입금": f"{cheugam_rows[0]:,}원",
            "마지막달 납입금": f"{cheugam_rows[-1]:,}원",
            "총 이자": f"{total_cheugam/1e4:.0f}만원",
        },
        {
            "상환방식": "원리금균등",
            "첫달 납입금": f"{equal_monthly:,.0f}원",
            "마지막달 납입금": f"{equal_monthly:,.0f}원",
            "총 이자": f"{total_equal/1e4:.0f}만원",
        },
        {
            "상환방식": "체증식 ✅",
            "첫달 납입금": f"{cheujeung_rows[0]:,}원",
            "마지막달 납입금": f"{cheujeung_rows[-1]:,}원",
            "총 이자": f"{total_cheujeung/1e4:.0f}만원",
        },
    ])
    st.dataframe(summary, use_container_width=True, hide_index=True)
    st.caption("※ 체감식 총이자 최소 · 체증식 초기 부담 최소")

with col_chart:
    fig = go.Figure(go.Bar(
        x=["체감식", "원리금균등", "체증식"],
        y=[total_cheugam, total_equal, total_cheujeung],
        marker_color=["#94a3b8", "#f59e0b", "#6366f1"],
        text=[f"{v/1e4:.0f}만원" for v in [total_cheugam, total_equal, total_cheujeung]],
        textposition="outside",
    ))
    fig.update_layout(
        title="총 이자 비교",
        yaxis_tickformat=",", plot_bgcolor="white",
        height=240, margin=dict(l=0, r=0, t=40, b=0), showlegend=False,
    )
    fig.update_yaxes(showgrid=True, gridcolor="#f1f5f9")
    st.plotly_chart(fig, use_container_width=True)

# ── 연도별 월납입금 상세 표 ───────────────────
st.markdown("##### 연도별 월납입금 상세")
years_list = list(range(1, term_yr + 1))
detail_df  = pd.DataFrame({
    "연차":         [f"{y}년차" for y in years_list],
    "체감식 (원금균등)": [f"{v:,}" for v in cheugam_rows],
    "원리금균등":   [f"{round(equal_monthly):,}"] * term_yr,
    "체증식":       [f"{v:,}" for v in cheujeung_rows],
})
st.dataframe(detail_df, use_container_width=True, hide_index=True, height=280)

# ── 월납입금 흐름 차트 ────────────────────────
st.markdown('<div class="sec">📈 월납입금 흐름</div>', unsafe_allow_html=True)

fig2 = go.Figure()
fig2.add_trace(go.Scatter(x=years_list, y=cheujeung_rows, name="체증식 ✅",
                           line=dict(color="#6366f1", width=2.5)))
fig2.add_trace(go.Scatter(x=years_list, y=[round(equal_monthly)]*term_yr, name="원리금균등",
                           line=dict(color="#f59e0b", width=1.5, dash="dash")))
fig2.add_trace(go.Scatter(x=years_list, y=cheugam_rows, name="체감식",
                           line=dict(color="#94a3b8", width=1.5, dash="dot")))

if term_yr >= 3:
    fig2.add_vrect(x0=0, x1=3, fillcolor="#fee2e2", opacity=0.2, line_width=0,
                   annotation_text="3년↓ 수수료", annotation_position="top left",
                   annotation_font_size=10)
if term_yr >= 5:
    fig2.add_vrect(x0=3, x1=5, fillcolor="#fef9c3", opacity=0.25, line_width=0,
                   annotation_text="3~5년 목표", annotation_position="top left",
                   annotation_font_size=10)

fig2.update_layout(
    xaxis_title="경과 연수", yaxis_title="월납입금 (원)",
    yaxis_tickformat=",", plot_bgcolor="white",
    height=300, margin=dict(l=0, r=0, t=20, b=0),
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
st.markdown("#### 🧮 중도상환수수료 간이 계산기")

c_left, c_right = st.columns(2)
with c_left:
    loan_amt = st.number_input("대출 잔액 (만원)", value=int(loan_man), step=100)
with c_right:
    hold_yr = st.slider("보유 기간 (년)", 0, 5, 2)

if hold_yr < 3:
    rate = 0.005 * (3 - hold_yr) / 3
    fee  = int(loan_amt * 10000 * rate)
    st.error(f"⚠️ 예상 수수료: **{fee:,}원** (약 {fee/10000:.0f}만원) — {hold_yr}년 보유 기준")
else:
    st.success("✅ 3년 이상 보유 시 중도상환수수료 없음")
