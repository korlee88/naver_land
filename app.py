# app.py — Streamlit 멀티페이지 진입점
import streamlit as st

st.set_page_config(
    page_title="매물 분석 대시보드",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded",
)

pg = st.navigation([
    st.Page("pages/graph_v2.py",    title="가격 추이 차트",  icon="📊", default=True),
    st.Page("pages/recommend.py",   title="추천 매물",       icon="🏆"),
    st.Page("rawdata.py",           title="매물 입력",       icon="📝"),
    st.Page("pages/visited.py",     title="방문 매물 기록",  icon="🏠"),
    st.Page("pages/view_manage.py", title="조망 관리",       icon="🌅"),
    st.Page("pages/raw_manage.py",  title="RAW 관리",        icon="🧹"),
    st.Page("pages/policy_news.py", title="부동산 뉴스",     icon="📰"),
    st.Page("pages/loan_info.py",   title="보금자리론",      icon="🏦"),
    st.Page("pages/notebooklm.py",  title="NotebookLM",     icon="🤖"),
], position="hidden")

with st.sidebar:
    st.markdown("**Menu**")
    st.page_link("pages/graph_v2.py",    label="가격 추이 차트",    icon="📊")
    st.page_link("pages/recommend.py",   label="핵심 추천 매물",    icon="🏆")
    st.page_link("rawdata.py",           label="매물 데이터 입력",   icon="📝")
    st.page_link("pages/visited.py",     label="방문 매물 기록",     icon="🏠")
    st.page_link("pages/view_manage.py", label="조망 관리",          icon="🌅")
    st.page_link("pages/raw_manage.py",  label="데이터 관리",        icon="🗂️")
    st.page_link("pages/policy_news.py", label="부동산 뉴스",        icon="📰")
    st.page_link("pages/loan_info.py",   label="보금자리론 정보",    icon="🏦")
    st.page_link("pages/notebooklm.py",  label="AI 분석 내보내기",   icon="🤖")
    st.divider()

pg.run()
