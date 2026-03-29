"""
visited.py  ─  방문 매물 기록
직접 방문/확인한 매물 정보를 입력·저장·조회합니다.
"""

import json
import pandas as pd
import streamlit as st

from db import init_db, insert_visited, read_visited, delete_visited, read_listings
from utils_style import inject_korean_font
from utils_auth import require_auth
from utils_graph import build_df, clean_name

inject_korean_font()
require_auth()
init_db()

# ── 옵션 목록 ─────────────────────────────────
OPTION_LIST = [
    "에어컨", "냉장고", "세탁기", "건조기", "식기세척기",
    "붙박이장", "시스템에어컨", "인덕션/가스레인지", "오븐",
    "엘리베이터", "주차 가능", "CCTV", "무인택배함",
    "리모델링", "신축", "채광 좋음", "조망 좋음",
]

DIRECTION_LIST = ["", "남향", "남동향", "남서향", "동향", "서향", "북동향", "북서향", "북향"]

# ── 기존 단지명 목록 (자동완성용) ──────────────
@st.cache_data(show_spinner=False, ttl=300)
def _complex_names():
    try:
        df = build_df()
        if df.empty:
            return []
        return sorted(df["complex_name"].dropna().unique().tolist())
    except Exception:
        return []

complex_names = _complex_names()

# ══════════════════════════════════════════════
st.markdown("#### 🏠 방문 매물 기록")

# ── 입력 폼 ───────────────────────────────────
with st.form("visited_form", clear_on_submit=True):
    st.markdown("**📋 매물 정보 입력**")

    r1c1, r1c2 = st.columns([1, 3])
    visit_date   = r1c1.date_input("방문일자", value=pd.Timestamp.today())
    complex_name = r1c2.selectbox(
        "단지명",
        options=["직접입력"] + complex_names,
        index=0,
    )
    if complex_name == "직접입력":
        complex_name = st.text_input("단지명 직접입력", placeholder="예) 더샵지제역센트럴파크")

    r2c1, r2c2, r2c3, r2c4 = st.columns(4)
    dong      = r2c1.text_input("동",   placeholder="예) 101")
    ho        = r2c2.text_input("호수", placeholder="예) 1502")
    area      = r2c3.text_input("평형", placeholder="예) 84A/59.7m²")
    unit_type = r2c4.text_input("타입", placeholder="예) 84A")

    r3c1, r3c2 = st.columns([1, 2])
    direction  = r3c1.selectbox("방향", DIRECTION_LIST)
    price_text = r3c2.text_input("금액", placeholder="예) 매매 3억 8,000")

    st.markdown("**✅ 확인된 옵션**")
    # 4열로 체크박스 나열
    opt_cols = st.columns(4)
    selected_options = []
    for idx, opt in enumerate(OPTION_LIST):
        if opt_cols[idx % 4].checkbox(opt, key=f"opt_{opt}"):
            selected_options.append(opt)

    memo = st.text_area("기타 메모", placeholder="층간소음, 수압, 주변 환경, 집주인 성향 등 자유롭게 기록", height=80)

    submitted = st.form_submit_button("💾 저장", type="primary", use_container_width=True)

if submitted:
    if not complex_name or complex_name == "직접입력":
        st.warning("단지명을 입력해 주세요.")
    else:
        insert_visited({
            "visit_date":   str(visit_date),
            "complex_name": complex_name,
            "dong":         dong,
            "ho":           ho,
            "area":         area,
            "unit_type":    unit_type,
            "direction":    direction,
            "price_text":   price_text,
            "options":      selected_options,
            "memo":         memo,
        })
        st.success(f"✅ '{complex_name}' 방문 기록이 저장되었습니다.")
        st.rerun()

# ── 기록 목록 ─────────────────────────────────
st.divider()
st.markdown("**📂 방문 기록 목록**")

records = read_visited()
if not records:
    st.caption("아직 기록된 방문 매물이 없습니다.")
    st.stop()

df_v = pd.DataFrame(records)
df_v["옵션"] = df_v["options"].apply(lambda x: ", ".join(x) if x else "-")
df_v = df_v.rename(columns={
    "id": "ID", "visit_date": "방문일", "complex_name": "단지명",
    "dong": "동", "ho": "호수", "area": "평형", "unit_type": "타입",
    "direction": "방향", "price_text": "금액", "memo": "메모",
})

show_cols = ["방문일", "단지명", "동", "호수", "평형", "타입", "방향", "금액", "옵션", "메모"]
show_cols = [c for c in show_cols if c in df_v.columns]

st.dataframe(df_v[show_cols], use_container_width=True, hide_index=True)

# ── 삭제 ──────────────────────────────────────
with st.expander("🗑️ 기록 삭제"):
    id_options = {f"{r['방문일']} | {r['단지명']} {r.get('동','')}동 {r.get('호수','')}호": r["ID"]
                  for r in df_v.to_dict("records")}
    sel_label = st.selectbox("삭제할 항목 선택", list(id_options.keys()))
    if st.button("삭제 확인", type="primary"):
        delete_visited(id_options[sel_label])
        st.success("삭제되었습니다.")
        st.rerun()
