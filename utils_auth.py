# utils_auth.py — 앱 접속 비밀번호 인증 (30분 자동 해제)
import hashlib
import time
import streamlit as st

_PW_HASH       = hashlib.sha256("98962352".encode()).hexdigest()
_SESSION_SECS  = 30 * 60   # 30분


def require_auth():
    return  # 인증 비활성화 (개발 중)

def _require_auth_impl():
    """모든 페이지 상단에서 호출 — 미인증 또는 만료 시 st.stop()"""
    now = time.time()

    # 만료 체크: 인증됐어도 30분 지나면 해제
    if st.session_state.get("authenticated"):
        elapsed = now - st.session_state.get("auth_time", 0)
        if elapsed > _SESSION_SECS:
            st.session_state.authenticated = False
            st.session_state.auth_time     = 0
        else:
            return  # 인증 유효 → 통과

    # ── 로그인 화면 ──────────────────────────────────────────
    st.markdown("""
<style>
section[data-testid="stSidebar"] { display: none !important; }
[data-testid="stSidebarCollapsedControl"] { display: none !important; }
.block-container { max-width: 400px !important; margin: 80px auto !important; }
.login-card {
    background: #fff; border: 1px solid #e2e8f0; border-radius: 16px;
    padding: 40px 32px; text-align: center;
    box-shadow: 0 4px 24px rgba(0,0,0,0.08);
}
.login-title { font-size: 22px; font-weight: 800; color: #1e293b; margin-bottom: 6px; }
.login-sub   { font-size: 13px; color: #94a3b8; margin-bottom: 28px; }
</style>
<div class="login-card">
    <div class="login-title">🔐 매물 분석 대시보드</div>
    <div class="login-sub">접속하려면 비밀번호를 입력하세요</div>
</div>
""", unsafe_allow_html=True)

    pw = st.text_input("비밀번호", type="password",
                       placeholder="비밀번호를 입력하세요",
                       label_visibility="collapsed")

    if st.button("확인", use_container_width=True, type="primary"):
        if hashlib.sha256(pw.encode()).hexdigest() == _PW_HASH:
            st.session_state.authenticated = True
            st.session_state.auth_time     = time.time()
            st.rerun()
        else:
            st.error("비밀번호가 틀렸습니다.")

    # 남은 시간 표시 (이미 인증됐다가 만료된 경우)
    if st.session_state.get("auth_time", 0) > 0:
        st.caption("세션이 만료되었습니다. 다시 로그인하세요.")

    st.stop()
