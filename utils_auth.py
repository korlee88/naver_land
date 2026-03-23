# utils_auth.py — 앱 접속 비밀번호 인증
import hashlib
import streamlit as st

# 비밀번호 해시 (평문 저장 방지)
_PW_HASH = hashlib.sha256("98962352".encode()).hexdigest()


def require_auth():
    """모든 페이지 상단에서 호출 — 인증 안 되면 st.stop()"""
    if st.session_state.get("authenticated"):
        return  # 이미 인증됨

    st.markdown("""
    <style>
    .login-wrap {
        max-width: 360px; margin: 120px auto; text-align: center;
        padding: 40px 32px; border-radius: 16px;
        background: #fff; border: 1px solid #e2e8f0;
        box-shadow: 0 4px 24px rgba(0,0,0,0.07);
    }
    .login-title { font-size: 22px; font-weight: 800; color: #1e293b; margin-bottom: 4px; }
    .login-sub   { font-size: 13px; color: #94a3b8; margin-bottom: 24px; }
    </style>
    <div class="login-wrap">
        <div class="login-title">🔐 매물 분석 대시보드</div>
        <div class="login-sub">접속하려면 비밀번호를 입력하세요</div>
    </div>
    """, unsafe_allow_html=True)

    pw = st.text_input("비밀번호", type="password", placeholder="비밀번호 입력")

    if st.button("확인", use_container_width=True):
        if hashlib.sha256(pw.encode()).hexdigest() == _PW_HASH:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("비밀번호가 틀렸습니다.")

    st.stop()
