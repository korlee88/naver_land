# app.py — Streamlit 멀티페이지 진입점
import streamlit as st

st.set_page_config(
    page_title="매물 분석 대시보드",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded",
)

pg = st.navigation([
    st.Page("pages/graph_v2.py",    title="매물 분석",        icon="📊", default=True),
    st.Page("rawdata.py",           title="매물 입력",        icon="📝"),
    st.Page("pages/raw_manage.py",  title="RAW 관리",         icon="🧹"),
    st.Page("pages/policy_news.py", title="부동산 뉴스",      icon="📰"),
    st.Page("pages/loan_info.py",   title="보금자리론",       icon="🏦"),
    st.Page("pages/notebooklm.py",  title="NotebookLM",      icon="🤖"),
])

pg.run()
