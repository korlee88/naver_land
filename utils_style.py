# utils_style.py — 전체 페이지 공통 한글 폰트 적용
import platform
import matplotlib.pyplot as plt
import streamlit as st
import plotly.io as pio

# 본문: Noto Sans KR (깔끔한 현대적 한글)
# 숫자/코드: DM Mono (가독성 좋은 모노)
_CSS_MAIN  = "'Noto Sans KR', 'Malgun Gothic', sans-serif"
_CSS_NUM   = "'DM Mono', 'Courier New', monospace"
_PLOTLY_FONT = "Noto Sans KR, Malgun Gothic, sans-serif"


def _setup_matplotlib_font():
    plt.rcParams["axes.unicode_minus"] = False
    if platform.system() == "Windows":
        plt.rcParams["font.family"] = "Malgun Gothic"
    else:
        plt.rcParams["font.family"] = "NanumGothic"


def inject_korean_font():
    """Railway/Linux 한글 깨짐 방지 + 전체 폰트 스타일링"""
    _setup_matplotlib_font()

    st.markdown("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700;900&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">

<style>
/* ── 사이드바 닫기 버튼 (열린 상태, stSidebarCollapseButton) ── */
[data-testid="stSidebarCollapseButton"] [data-testid="stIconMaterial"] {
    font-size: 0 !important;
}
[data-testid="stSidebarCollapseButton"] button {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23475569' d='M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z'/%3E%3C/svg%3E") !important;
    background-repeat: no-repeat !important;
    background-position: center !important;
    background-size: 20px 20px !important;
}
/* ── 사이드바 열기 버튼 (닫힌 상태, stSidebarCollapsedControl) ── */
[data-testid="stSidebarCollapsedControl"] [data-testid="stIconMaterial"] {
    font-size: 0 !important;
}
[data-testid="stSidebarCollapsedControl"] button {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23475569' d='M3 18h18v-2H3v2zm0-5h18v-2H3v2zm0-7v2h18V6H3z'/%3E%3C/svg%3E") !important;
    background-repeat: no-repeat !important;
    background-position: center !important;
    background-size: 20px 20px !important;
}

/* ── expander 아이콘 텍스트(arrow_drop_down) 겹침 방지 ── */
[data-testid="stExpander"] summary .material-icons,
[data-testid="stExpander"] summary span[class*="material"],
[data-testid="stExpander"] details summary > span:first-child {
    font-size: 0 !important;
    width: 0 !important;
    overflow: hidden !important;
    display: none !important;
}

/* ── Material Icons 폰트 미로드 시 아이콘 텍스트 겹침 방지 ── */
.material-icons {
    font-family: 'Material Icons' !important;
    font-size: 18px;
    line-height: 1;
    direction: ltr;
    -webkit-font-smoothing: antialiased;
    overflow: hidden;
    width: 18px;
    display: inline-block;
}
/* expander 화살표 아이콘 영역 고정 */
[data-testid="stExpander"] summary [data-testid="stExpanderToggleIcon"],
[data-testid="stExpander"] summary svg {
    min-width: 20px;
    overflow: hidden;
    flex-shrink: 0;
}

/* ── 메인 컨텐츠 전체 너비 사용 ── */
.block-container {
    max-width: 100% !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
}

/* ── 전체 기본 폰트 ── */
html, body, [class*="css"] {
    font-family: 'Noto Sans KR', 'Malgun Gothic', sans-serif !important;
    letter-spacing: -0.01em;
}

/* ── 제목류 ── */
h1, h2, h3, h4, .stTitle {
    font-family: 'Noto Sans KR', sans-serif !important;
    font-weight: 700 !important;
    letter-spacing: -0.03em;
}

/* ── 일반 텍스트 ── */
p, div, span, label, button, li, td, th,
.stMarkdown, .stText, .stCaption {
    font-family: 'Noto Sans KR', 'Malgun Gothic', sans-serif !important;
    font-weight: 400;
}

/* ── 사이드바 ── */
section[data-testid="stSidebar"] * {
    font-family: 'Noto Sans KR', sans-serif !important;
    font-size: 13px;
}
section[data-testid="stSidebar"] .stMarkdown h3 {
    font-size: 14px !important;
    font-weight: 700 !important;
}

/* ── metric 숫자값 ── */
[data-testid="stMetricValue"] {
    font-family: 'DM Mono', monospace !important;
    font-weight: 500 !important;
    letter-spacing: -0.02em;
}
[data-testid="stMetricDelta"] {
    font-family: 'Noto Sans KR', sans-serif !important;
    font-size: 12px !important;
}

/* ── dataframe/table ── */
.stDataFrame, .stDataEditor {
    font-family: 'Noto Sans KR', sans-serif !important;
    font-size: 13px !important;
}

/* ── 입력 위젯 ── */
input, textarea, select,
[data-baseweb="input"] * {
    font-family: 'Noto Sans KR', sans-serif !important;
}

/* ── 버튼 ── */
.stButton > button {
    font-family: 'Noto Sans KR', sans-serif !important;
    font-weight: 500 !important;
    letter-spacing: -0.01em;
}

/* ── 탭 ── */
[data-baseweb="tab"] {
    font-family: 'Noto Sans KR', sans-serif !important;
    font-weight: 500 !important;
}

/* ── 멀티셀렉트 태그 ── */
[data-baseweb="tag"] * {
    font-family: 'Noto Sans KR', sans-serif !important;
    font-size: 12px !important;
}
</style>
""", unsafe_allow_html=True)

    # Plotly 전역 폰트
    pio.templates["korean"] = pio.templates["plotly_white"]
    pio.templates["korean"].layout.font = dict(family=_PLOTLY_FONT, size=12)
    pio.templates.default = "korean"


def apply_font(fig):
    """Plotly Figure에 한글 폰트 직접 지정"""
    fig.update_layout(font=dict(family=_PLOTLY_FONT, size=12))
    return fig
