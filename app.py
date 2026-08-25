# app.py — Streamlit 멀티페이지 진입점
import os
import streamlit as st
import setup_fonts
from db import (
    init_db, is_db_empty, restore_from_sheet,
    is_rtms_empty, restore_rtms_from_sheet,
    is_kosis_empty, restore_kosis_from_sheet,
)

# 폰트 초기화 (Streamlit Cloud: packages.txt 설치 폰트 우선, 없으면 다운로드)
if "fonts_initialized" not in st.session_state:
    setup_fonts.main()
    st.session_state.fonts_initialized = True

st.set_page_config(
    page_title="매물 분석 대시보드",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── DB 초기화 (항상 실행 — 테이블 없으면 생성) ──
init_db()

# ── RTMS 실거래가 자동 복원 (수면 후 재시작 시 구글시트에서 복원) ──
if "rtms_restored" not in st.session_state:
    st.session_state.rtms_restored = True
    if is_rtms_empty():
        with st.spinner("📥 실거래가 데이터 복원 중..."):
            try:
                t, j = restore_rtms_from_sheet()
                if t > 0 or j > 0:
                    st.success(f"✅ 실거래가 복원 완료 — 매매 {t}건 / 전월세 {j}건")
                    st.cache_data.clear()
            except Exception:
                pass  # 복원 실패 시 조용히 무시 (첫 수집 전일 수 있음)

# ── KOSIS 통계 자동 복원 (수면 후 재시작 시 구글시트에서 복원) ──
if "kosis_restored" not in st.session_state:
    st.session_state.kosis_restored = True
    if is_kosis_empty():
        with st.spinner("📥 KOSIS 통계 복원 중..."):
            try:
                n = restore_kosis_from_sheet()
                if n > 0:
                    st.success(f"✅ KOSIS 통계 복원 완료 — {n}건")
                    st.cache_data.clear()
            except Exception:
                pass  # 복원 실패 시 조용히 무시 (첫 수집 전일 수 있음)

# ── 수동입력 DB 자동 복원 (배포 후 DB가 비어있을 때 구글시트에서 자동 복원) ──
_auto_sheet = os.environ.get("AUTO_RESTORE_SHEET", "")
if _auto_sheet and "auto_restored" not in st.session_state:
    st.session_state.auto_restored = True
    if is_db_empty():
        with st.spinner(f"📥 DB가 비어있습니다. '{_auto_sheet}' 시트에서 자동 복원 중..."):
            try:
                ins, upd, skip = restore_from_sheet(_auto_sheet)
                st.success(f"✅ 자동 복원 완료 — 신규 {ins}건 / 업데이트 {upd}건")
                st.cache_data.clear()
            except Exception as e:
                st.warning(f"⚠️ 자동 복원 실패: {e}  |  RAW 관리 페이지에서 수동 복원해주세요.")

pg = st.navigation([
    st.Page("pages/rtms_chart.py",       title="가격 추이",       icon="📊", default=True),
    st.Page("pages/rtms_area_trend.py",  title="지역별 가격동향", icon="🗺️"),
    st.Page("pages/rtms_fetch.py",       title="실거래가 수집",   icon="🏛️"),
    st.Page("pages/kosis_trend.py",      title="인구·주택·경제 통계", icon="📈"),
    st.Page("pages/kosis_fetch.py",      title="KOSIS 통계 수집",     icon="🏢"),
], position="hidden")

with st.sidebar:
    st.markdown("**Menu**")
    st.page_link("pages/rtms_chart.py",       label="가격 추이",       icon="📊")
    st.page_link("pages/rtms_area_trend.py",  label="지역별 가격동향", icon="🗺️")
    st.page_link("pages/rtms_fetch.py",       label="실거래가 수집",   icon="🏛️")
    st.page_link("pages/kosis_trend.py",      label="인구·주택·경제 통계", icon="📈")
    st.page_link("pages/kosis_fetch.py",      label="KOSIS 통계 수집",     icon="🏢")
    st.divider()

pg.run()
