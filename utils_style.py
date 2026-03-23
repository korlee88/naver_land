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

<style>
/* ── 사이드바 접기 버튼(keyboard_double) 숨기기 ── */
[data-testid="stBaseButton-headerNoPadding"],
button[aria-label="keyboard_double_arrow_left"],
button[aria-label="keyboard_double_arrow_right"],
[kind="headerNoPadding"] { display: none !important; }

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
