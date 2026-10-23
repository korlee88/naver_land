# app.py — Streamlit 멀티페이지 진입점
import streamlit as st
import setup_fonts
from db import (
    init_db,
    is_rtms_empty, restore_rtms_from_sheet,
    is_kosis_empty, restore_kosis_from_sheet,
    is_ecos_empty, restore_ecos_from_sheet,
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
                n, err = restore_kosis_from_sheet()
                if n > 0:
                    st.success(f"✅ KOSIS 통계 복원 완료 — {n}건")
                    st.cache_data.clear()
                elif err:
                    # 첫 수집 전(시트 자체가 없음)은 정상 상황이라 조용히 넘어가고,
                    # 그 외 오류(권한/네트워크 등)만 알려준다
                    if "not found" not in err.lower():
                        st.warning(f"⚠️ KOSIS 통계 복원 실패: {err}")
            except Exception:
                pass  # 복원 실패 시 조용히 무시 (첫 수집 전일 수 있음)

# ── ECOS 금리 자동 복원 (수면 후 재시작 시 구글시트에서 복원) ──
if "ecos_restored" not in st.session_state:
    st.session_state.ecos_restored = True
    if is_ecos_empty():
        try:
            n, err = restore_ecos_from_sheet()
            if n > 0:
                st.success(f"✅ 금리 데이터 복원 완료 — {n}건")
                st.cache_data.clear()
            elif err and "not found" not in err.lower():
                st.warning(f"⚠️ 금리 데이터 복원 실패: {err}")
        except Exception:
            pass  # 첫 수집 전일 수 있음


pg = st.navigation([
    st.Page("pages/rtms_chart.py",       title="가격 추이",       icon="📊", default=True),
    st.Page("pages/rtms_area_trend.py",  title="지역별 가격동향", icon="🗺️"),
    st.Page("pages/rtms_area_trend_mobile.py", title="지역별 가격동향(모바일)", icon="📱"),
    st.Page("pages/simulator.py",        title="보유 시뮬레이터", icon="🧮"),
    st.Page("pages/market_link.py",      title="시장 연동 분석", icon="🔗"),
    st.Page("pages/rtms_fetch.py",       title="실거래가 수집",   icon="🏛️"),
    st.Page("pages/kosis_trend.py",      title="인구·주택·경제 통계", icon="📈"),
    st.Page("pages/kosis_fetch.py",      title="KOSIS 통계 수집",     icon="🏢"),
    st.Page("pages/ecos_fetch.py",       title="금리 수집(ECOS)",     icon="🏦"),
], position="hidden")

with st.sidebar:
    st.markdown("**Menu**")
    st.page_link("pages/rtms_chart.py",       label="가격 추이",       icon="📊")
    st.page_link("pages/rtms_area_trend.py",  label="지역별 가격동향", icon="🗺️")
    st.page_link("pages/rtms_area_trend_mobile.py", label="지역별 가격동향(모바일)", icon="📱")
    st.page_link("pages/simulator.py",        label="보유 시뮬레이터", icon="🧮")
    st.page_link("pages/market_link.py",      label="시장 연동 분석", icon="🔗")
    st.page_link("pages/rtms_fetch.py",       label="실거래가 수집",   icon="🏛️")
    st.page_link("pages/kosis_trend.py",      label="인구·주택·경제 통계", icon="📈")
    st.page_link("pages/kosis_fetch.py",      label="KOSIS 통계 수집",     icon="🏢")
    st.page_link("pages/ecos_fetch.py",       label="금리 수집(ECOS)",     icon="🏦")
    st.divider()

pg.run()
