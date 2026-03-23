# utils_style.py — 전체 페이지 공통 한글 폰트 적용
import streamlit as st
import plotly.io as pio

_KOREAN_FONT = "Nanum Gothic, Malgun Gothic, 맑은 고딕, sans-serif"

def inject_korean_font():
    """Railway(Linux) 한글 깨짐 방지 — 모든 페이지 상단에서 호출"""
    st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Nanum+Gothic:wght@400;700;800&display=swap');
html, body, [class*="css"], .stMarkdown, .stText, .stMetric,
div, span, p, h1, h2, h3, label, button, input, textarea, select {{
    font-family: {_KOREAN_FONT} !important;
}}
</style>
""", unsafe_allow_html=True)

    # Plotly 전역 한글 폰트
    pio.templates["korean"] = pio.templates["plotly_white"]
    pio.templates["korean"].layout.font = dict(family=_KOREAN_FONT)
    pio.templates.default = "korean"
