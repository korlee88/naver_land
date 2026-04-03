"""
visited.py  ─  방문 매물 기록
부동산업자로부터 받은 추천 매물을 기록하고 핵심 추천 점수 기준으로 순위를 표시합니다.
"""

import re
import pandas as pd
import streamlit as st

from db import init_db, insert_visited, read_visited, delete_visited, read_listings, load_view_scores
from utils_style import inject_korean_font
from utils_auth import require_auth
from utils_graph import (
    build_df,
    _floor_score, _direction_score, _area_score, _memo_score, _view_score,
    RANK_EMOJIS,
)

inject_korean_font()
require_auth()
init_db()

# ── 옵션 목록 (시스템에어컨 제외 — 별도 대수 입력) ──
OPTION_LIST = [
    "에어컨", "냉장고", "세탁기", "건조기", "식기세척기",
    "붙박이장", "인덕션/가스레인지", "오븐",
    "리모델링", "채광 좋음", "조망 좋음",
]

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
# 금액 파싱 (저장된 텍스트 → 억 단위 float)
# ══════════════════════════════════════════════
def _parse_eok(text: str):
    """
    저장 포맷: "3.90억" (number_input으로 입력 후 저장)
    구버전 포맷도 처리: "3억 8,000", "38000만", 원단위(390000000)
    """
    if not text:
        return None
    t = str(text).replace(",", "").replace(" ", "")

    # "N억..." 패턴
    m = re.search(r"(\d+\.?\d*)억\s*(\d+)?", t)
    if m:
        eok  = float(m.group(1))
        rest = float(m.group(2) or 0)
        if rest >= 1000:
            eok += rest / 10000
        elif rest >= 100:
            eok += rest / 1000
        elif rest > 0:
            eok += rest / 10
        return round(eok, 4)

    # "N만" 패턴
    m = re.search(r"(\d+)\s*만", t)
    if m:
        return round(int(m.group(1)) / 10000, 4)

    # 단독 숫자
    m = re.search(r"(\d+\.?\d*)", t)
    if m:
        v = float(m.group(1))
        if v >= 100_000_000:      # 원 단위 (1억 이상)
            return round(v / 100_000_000, 4)
        if v >= 1_000:            # 만원 단위
            return round(v / 10_000, 4)
        return round(v, 4)        # 억 단위

    return None


# ══════════════════════════════════════════════
# DB에서 동 정보 조회 (층/방향/평형)
# ══════════════════════════════════════════════
@st.cache_data(show_spinner=False, ttl=300)
def _listing_by_dong() -> dict:
    """
    {(complex_name_lower, dong): {"floor": ..., "direction": ..., "area": ...}}
    동 내 매물이 여러 개면 last_seen 기준 가장 최근 1건 사용.
    """
    try:
        rows = read_listings()
    except Exception:
        return {}
    result = {}
    for r in rows:
        cn   = str(r.get("complex_name") or "").strip().lower()
        dong = str(r.get("dong") or "").strip()
        key  = (cn, dong)
        if key not in result:
            result[key] = {
                "floor":     r.get("floor"),
                "direction": r.get("direction"),
                "area":      r.get("area"),
            }
    return result


# ══════════════════════════════════════════════
# 단일 방문 매물 점수 계산
# ══════════════════════════════════════════════
def _score_visited(row: dict, listing_map: dict, view_map: dict):
    """반환: (total_score, breakdown_dict)"""
    eok  = _parse_eok(row.get("price_text", ""))
    cn   = str(row.get("complex_name") or "").strip().lower()
    dong = str(row.get("dong") or "").strip()

    info      = listing_map.get((cn, dong)) or {}
    floor     = info.get("floor")
    direction = info.get("direction")
    area      = info.get("area")
    memo      = row.get("memo") or ""

    s_price = round((4.0 - eok) / 0.1 * 5, 1) if eok is not None else 0.0
    s_floor = _floor_score(floor)
    s_dir   = _direction_score(direction)
    s_area  = _area_score(area)
    s_memo  = _memo_score(memo)
    s_view  = _view_score(
        {"complex_name": row.get("complex_name"), "dong": dong, "floor": floor},
        view_map,
    )

    total = round(s_price + s_floor + s_dir + s_area + s_memo + s_view, 1)

    return total, {
        "eok": eok, "floor": floor, "direction": direction, "area": area,
        "db_matched": bool(info),
        "score_price": s_price, "score_floor": s_floor, "score_dir": s_dir,
        "score_area": s_area, "score_memo": s_memo, "score_view": s_view,
    }


# ══════════════════════════════════════════════
# 페이지
# ══════════════════════════════════════════════
st.markdown("#### 🏠 방문 매물 기록")

# ── 입력 폼 ───────────────────────────────────
with st.form("visited_form", clear_on_submit=True):
    st.markdown("**📋 매물 정보 입력**")

    r1c1, r1c2, r1c3 = st.columns([1, 2, 2])
    visit_date   = r1c1.date_input("방문일자", value=pd.Timestamp.today())
    complex_name = r1c2.selectbox("단지명", options=complex_names, index=0 if complex_names else 0)
    office_name  = r1c3.text_input("부동산", placeholder="예) 더샵공인중개사")

    r2c1, r2c2, r2c3, r2c4 = st.columns(4)
    dong      = r2c1.text_input("동",   placeholder="예) 101")
    floor_txt = r2c2.text_input("층수", placeholder="예) 15")
    ho        = r2c3.text_input("호수", placeholder="예) 1502  (모르면 공란)")
    price_eok = r2c4.number_input(
        "금액 (억 단위)",
        min_value=0.0, max_value=100.0, step=0.01, value=0.0,
        format="%.2f",
        help="예: 3억 8천만 → 3.80 입력",
    )

    st.markdown("**✅ 확인된 옵션**")

    # 시스템 에어컨 대수 (별도 입력)
    ac_col1, ac_col2 = st.columns([1, 3])
    ac_col1.markdown(
        "<div style='padding-top:8px;font-size:13px;'>🌀 시스템에어컨</div>",
        unsafe_allow_html=True,
    )
    sys_ac_count = ac_col2.number_input(
        "시스템에어컨 대수", min_value=0, max_value=10, step=1, value=0,
        label_visibility="collapsed",
        help="0 = 없음",
    )
    if sys_ac_count > 0:
        ac_col2.caption(f"✅ {sys_ac_count}대 설치")

    # 나머지 옵션 체크박스 (4열)
    opt_cols = st.columns(4)
    selected_options = []
    for idx, opt in enumerate(OPTION_LIST):
        if opt_cols[idx % 4].checkbox(opt, key=f"opt_{opt}"):
            selected_options.append(opt)

    memo = st.text_area("기타 메모", placeholder="층간소음, 수압, 주변 환경, 집주인 성향 등 자유롭게 기록", height=80)

    submitted = st.form_submit_button("💾 저장", type="primary", use_container_width=True)

if submitted:
    if not complex_name:
        st.warning("단지명을 선택해 주세요.")
    elif not dong:
        st.warning("동을 입력해 주세요.")
    elif price_eok <= 0:
        st.warning("금액을 입력해 주세요.")
    else:
        # 시스템에어컨 옵션 추가
        if sys_ac_count > 0:
            selected_options.append(f"시스템에어컨 {sys_ac_count}대")

        insert_visited({
            "visit_date":   str(visit_date),
            "complex_name": complex_name,
            "dong":         dong,
            "ho":           ho,
            "area":         floor_txt,     # 층수 저장
            "unit_type":    office_name,   # 부동산 이름 저장
            "direction":    "",
            "price_text":   f"{price_eok:.2f}억",
            "options":      selected_options,
            "memo":         memo,
        })
        ho_str = f" {ho}호" if ho else ""
        floor_str = f" {floor_txt}층" if floor_txt else ""
        st.success(f"✅ '{complex_name}' {dong}동{ho_str}{floor_str} ({price_eok:.2f}억) 기록이 저장되었습니다.")
        st.cache_data.clear()
        st.rerun()

# ── 기록 목록 ─────────────────────────────────
st.divider()

records = read_visited()
if not records:
    st.caption("아직 기록된 방문 매물이 없습니다.")
    st.stop()

# 점수 계산 및 순위 정렬
listing_map = _listing_by_dong()
view_map    = load_view_scores()

scored = []
for r in records:
    score, bd = _score_visited(r, listing_map, view_map)
    scored.append({**r, "score": score, **bd})

scored.sort(key=lambda x: x["score"], reverse=True)

# ── 순위 카드 ──────────────────────────────────
st.markdown(
    "**🏆 추천 순위**"
    '<span style="font-size:11px;color:#94a3b8;margin-left:8px;">'
    "핵심추천 기본 점수 기준 (가격·층수·방향·평형·메모·조망)"
    "</span>",
    unsafe_allow_html=True,
)

def _fmt_score(v, lbl):
    if not v:
        return ""
    color = "#16a34a" if v > 0 else "#dc2626"
    sign  = "+" if v > 0 else ""
    return f'<span style="color:{color};font-size:10px;">{lbl}{sign}{v:.0f}</span>'

for rank, r in enumerate(scored):
    emoji    = RANK_EMOJIS[rank] if rank < len(RANK_EMOJIS) else f"**{rank+1}위**"
    eok      = r.get("eok")
    # floor: DB매칭 결과 우선, 없으면 직접 입력한 층수(area 필드에 저장)
    floor    = r.get("floor") or r.get("area") or "-"
    direc    = r.get("direction") or "-"
    area     = "-"  # 평형은 DB매칭에서만 표시
    opts        = ", ".join(r.get("options") or []) or "-"
    memo_txt    = (r.get("memo") or "")[:50]
    office_txt  = r.get("unit_type") or ""

    eok_str  = f"{eok:.2f}억" if eok is not None else r.get("price_text", "-")
    db_badge = (
        '<span style="font-size:9px;background:#e0f2fe;color:#0369a1;'
        'border-radius:3px;padding:1px 5px;">DB매칭</span>'
        if r.get("db_matched") else
        '<span style="font-size:9px;background:#fef3c7;color:#92400e;'
        'border-radius:3px;padding:1px 5px;">금액기준</span>'
    )

    breakdown_html = " &nbsp;".join(filter(None, [
        _fmt_score(r.get("score_price", 0), "가격"),
        _fmt_score(r.get("score_floor", 0), "층"),
        _fmt_score(r.get("score_dir",   0), "방향"),
        _fmt_score(r.get("score_area",  0), "평형"),
        _fmt_score(r.get("score_memo",  0), "메모"),
        _fmt_score(r.get("score_view",  0), "조망"),
    ]))

    with st.container(border=True):
        c1, c2, c3 = st.columns([1, 5, 2])
        c1.markdown(
            f"<div style='font-size:28px;text-align:center;padding-top:6px;'>{emoji}</div>",
            unsafe_allow_html=True,
        )
        ho_disp = f" {r.get('ho','')}호" if r.get("ho") else ""
        c2.markdown(
            f"**{r['complex_name']}** &nbsp; {r.get('dong','')}동{ho_disp} &nbsp; {db_badge}"
            + (f" &nbsp;<span style='font-size:10px;color:#0369a1;'>🏢 {office_txt}</span>" if office_txt else "") + "<br>"
            f"<span style='color:#6366f1;font-weight:700;font-size:15px;'>{eok_str}</span>"
            f" &nbsp;|&nbsp; 층 {floor} &nbsp;|&nbsp; {direc} &nbsp;|&nbsp; {area}<br>"
            f"<span style='font-size:10px;color:#64748b;'>옵션: {opts}</span>"
            + (f"<br><span style='font-size:10px;color:#475569;'>📝 {memo_txt}</span>" if memo_txt else ""),
            unsafe_allow_html=True,
        )
        c3.markdown(
            f"<div style='text-align:right;'>"
            f"<div style='font-size:24px;font-weight:800;color:#6366f1;'>{r['score']:.0f}점</div>"
            f"<div style='font-size:10px;color:#94a3b8;'>{r.get('visit_date','')}</div>"
            f"<div style='margin-top:4px;line-height:2;'>{breakdown_html}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

# ── 전체 테이블 (접힌 상태) ───────────────────
with st.expander("📋 전체 목록 (표)"):
    rows_for_df = []
    for rank, r in enumerate(scored):
        eok = r.get("eok")
        rows_for_df.append({
            "순위":   rank + 1,
            "점수":   r["score"],
            "단지명": r["complex_name"],
            "동":     r.get("dong", ""),
            "호수":   r.get("ho", ""),
            "금액":   r.get("price_text", ""),
            "층":     r.get("floor") or "-",
            "방향":   r.get("direction") or "-",
            "평형":   r.get("area") or "-",
            "부동산": r.get("unit_type") or "-",
            "옵션":   ", ".join(r.get("options") or []) or "-",
            "메모":   (r.get("memo") or "")[:30],
            "방문일": r.get("visit_date", ""),
        })
    st.dataframe(pd.DataFrame(rows_for_df), use_container_width=True, hide_index=True)

# ── 삭제 ──────────────────────────────────────
with st.expander("🗑️ 기록 삭제"):
    id_options = {
        f"{r['visit_date']} | {r['complex_name']} {r.get('dong','')}동 {r.get('ho','')}호": r["id"]
        for r in records
    }
    sel_label = st.selectbox("삭제할 항목 선택", list(id_options.keys()))
    if st.button("삭제 확인", type="primary"):
        delete_visited(id_options[sel_label])
        st.success("삭제되었습니다.")
        st.cache_data.clear()
        st.rerun()
