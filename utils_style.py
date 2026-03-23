# utils_style.py — 전체 페이지 공통 한글 폰트 적용
import platform
import matplotlib.pyplot as plt
import streamlit as st
import plotly.io as pio

_KOREAN_CSS = "Nanum Gothic, Malgun Gothic, 맑은 고딕, sans-serif"


def _setup_matplotlib_font():
    plt.rcParams["axes.unicode_minus"] = False
    if platform.system() == "Windows":
        plt.rcParams["font.family"] = "Malgun Gothic"
    else:
        # setup_fonts.py 가 사전에 matplotlib fonts/ttf 에 설치해둠
        plt.rcParams["font.family"] = "Nanum Gothic"


def inject_korean_font():
    """Railway/Linux 한글 깨짐 방지 — 모든 페이지 상단에서 호출"""
    _setup_matplotlib_font()

    st.markdown("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Nanum+Gothic:wght@400;700;800&display=swap" rel="stylesheet">
<style>
html, body, [class*="css"], .stMarkdown, .stText, .stMetric,
div, span, p, h1, h2, h3, label, button, input, textarea, select {
    font-family: 'Nanum Gothic', 'Malgun Gothic', sans-serif !important;
}
</style>
""", unsafe_allow_html=True)

    pio.templates["korean"] = pio.templates["plotly_white"]
    pio.templates["korean"].layout.font = dict(family=_KOREAN_CSS, size=12)
    pio.templates.default = "korean"


def apply_font(fig):
    """Plotly Figure에 한글 폰트 직접 지정"""
    fig.update_layout(font=dict(family=_KOREAN_CSS, size=12))
    return fig
