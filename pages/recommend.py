"""
recommend.py  ─  핵심 추천 매물 (사용자 정의 점수 기준)
"""

import os
import re
from copy import deepcopy
from datetime import datetime, timedelta

import requests
import streamlit as st
import pandas as pd

from utils_style import inject_korean_font
from utils_auth  import require_auth
from utils_graph import (
    build_df, get_badges, render_sidebar,
    RANK_EMOJIS, SHARED_CSS, _RE_FLOOR,
)

inject_korean_font()
require_auth()
st.markdown(SHARED_CSS, unsafe_allow_html=True)

# ══════════════════════════════════════════════
# 기본 점수 파라미터
# ══════════════════════════════════════════════
DEFAULT_PARAMS = {
    "price_base":     4.0,
    "price_per_1000": 5.0,
    "floor_1_5":    -30,
    "floor_6_10":     0,
    "floor_11_15":   25,
    "floor_16_20":   35,
    "floor_21_up":   40,
    "dir_남향":       25,
    "dir_남동":       20,
    "dir_남서":       15,
    "dir_동":          5,
    "dir_서":          0,
    "dir_북동":       -5,
    "dir_북":        -15,
    "area_59":        10,
    "area_74":        15,
    "area_84":         0,
    "area_100up":    -20,
    "drop_max":       20,
    "new_days":        7,
    "new_score":      10,
    "conf_14d":       10,
    "conf_30d":        5,
    "memo_view":      10,
    "memo_urgent":     5,
    "memo_south":      5,
    "memo_defect":   -10,
    "choguma_score":  15,   # 초품아 점수
    "choguma_radius": 200,  # 반경(m)
}

# ── 세션 초기화 ───────────────────────────────
for k, v in DEFAULT_PARAMS.items():
    if f"sp_{k}" not in st.session_state:
        st.session_state[f"sp_{k}"] = v

if "presets" not in st.session_state:
    st.session_state.presets = [
        {"name": "프리셋 1", "params": None},
        {"name": "프리셋 2", "params": None},
        {"name": "프리셋 3", "params": None},
    ]
if "show_confirm" not in st.session_state:
    st.session_state.show_confirm = False
if "run_params"   not in st.session_state:
    st.session_state.run_params = None
if "show_results" not in st.session_state:
    st.session_state.show_results = False


# ══════════════════════════════════════════════
# 초품아 체크 (Kakao Local API)
# ══════════════════════════════════════════════
@st.cache_data(show_spinner=False, ttl=86400)
def _check_choguma(complex_name: str, kakao_key: str, radius: int) -> tuple:
    """반환: (is_choguma: bool, school_info: str)"""
    if not kakao_key:
        return False, "API 키 없음"
    headers = {"Authorization": f"KakaoAK {kakao_key}"}
    url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    try:
        # 1) 단지 좌표 검색
        r1 = requests.get(url, headers=headers,
                          params={"query": complex_name, "size": 1}, timeout=5)
        docs = r1.json().get("documents", [])
        if not docs:
            return False, "단지 위치 검색 실패"
        lng, lat = float(docs[0]["x"]), float(docs[0]["y"])

        # 2) 반경 내 초등학교 검색 (category_group_code SC4 = 학교)
        r2 = requests.get(url, headers=headers, params={
            "query": "초등학교", "x": lng, "y": lat,
            "radius": radius, "size": 5, "category_group_code": "SC4",
        }, timeout=5)
        schools = [s for s in r2.json().get("documents", [])
                   if "초등학교" in s.get("place_name", "")]
        if schools:
            info = ", ".join(f"{s['place_name']}({s.get('distance','?')}m)" for s in schools)
            return True, info
        return False, f"반경 {radius}m 내 초등학교 없음"
    except Exception as e:
        return False, f"오류: {e}"


# ══════════════════════════════════════════════
# 커스텀 점수 계산
# ══════════════════════════════════════════════
def _compute_custom(dfc, p, kakao_key=""):
    dc = dfc.copy()

    # 가격
    dc["score_price"] = ((p["price_base"] - dc["eok"]) / 0.1 * p["price_per_1000"]).round(1)

    # 하락폭
    if "uid" in dc.columns:
        first = dc.sort_values("uploadday").groupby("uid")["eok"].first()
        last  = dc.sort_values("uploadday").groupby("uid")["eok"].last()
        dc    = dc.merge((first - last).clip(lower=0).rename("drop_eok").reset_index(),
                         on="uid", how="left")
    else:
        dc["drop_eok"] = 0.0
    mx = dc["drop_eok"].max()
    dc["score_drop"] = (dc["drop_eok"] / mx * p["drop_max"] if mx > 0
                        else pd.Series(0.0, index=dc.index)).round(1)

    # 신규
    cut = pd.Timestamp(datetime.now() - timedelta(days=int(p["new_days"])))
    dc["score_new"] = dc["uploadday"].apply(
        lambda d: float(p["new_score"]) if pd.notna(d) and d >= cut else 0.0)

    # 확인매물
    if "confirm_age" in dc.columns:
        dc["score_conf"] = dc["confirm_age"].apply(
            lambda v: float(p["conf_14d"]) if pd.notna(v) and v <= 14
                      else (float(p["conf_30d"]) if pd.notna(v) and v <= 30 else 0.0))
    else:
        dc["score_conf"] = 0.0

    # 층수
    def _floor(fv):
        if not fv or pd.isna(fv): return 0.0
        s = str(fv).strip()
        if s.startswith(("저", "지", "반")): return float(p["floor_1_5"])
        m = _RE_FLOOR.match(s)
        if not m: return 0.0
        n = int(m.group(1))
        if n <= 5:  return float(p["floor_1_5"])
        if n <= 10: return float(p["floor_6_10"])
        if n <= 15: return float(p["floor_11_15"])
        if n <= 20: return float(p["floor_16_20"])
        return float(p["floor_21_up"])
    dc["score_floor"] = dc["floor"].apply(_floor) if "floor" in dc.columns else 0.0

    # 방향
    def _dir(dv):
        if not dv or pd.isna(dv): return 0.0
        d = str(dv).strip()
        if "남향" in d: return float(p["dir_남향"])
        if "남동" in d: return float(p["dir_남동"])
        if "남서" in d: return float(p["dir_남서"])
        if "동향" in d or d == "동": return float(p["dir_동"])
        if "서향" in d or d == "서": return float(p["dir_서"])
        if "북동" in d: return float(p["dir_북동"])
        if "북"   in d: return float(p["dir_북"])
        return 0.0
    dc["score_dir"] = dc["direction"].apply(_dir) if "direction" in dc.columns else 0.0

    # 평형
    def _area(av):
        if not av or pd.isna(av): return 0.0
        nums = re.findall(r"\d+\.?\d*", str(av))
        if not nums: return 0.0
        v = float(nums[0])
        if v < 10: v *= 3.305785
        if   50 <= v <  66: return float(p["area_59"])
        elif 66 <= v <  80: return float(p["area_74"])
        elif 80 <= v <  95: return float(p["area_84"])
        elif v >= 95:       return float(p["area_100up"])
        return 0.0
    dc["score_area"] = dc["area"].apply(_area) if "area" in dc.columns else 0.0

    # 메모
    def _memo(mv):
        if not mv or pd.isna(mv): return 0.0
        s = str(mv).lower()
        sc = 0.0
        if any(k in s for k in ["조망","뷰","view","탁트"]): sc += float(p["memo_view"])
        if any(k in s for k in ["급매","급처","급","특가"]):  sc += float(p["memo_urgent"])
        if any(k in s for k in ["남향","햇빛","일조"]):       sc += float(p["memo_south"])
        if any(k in s for k in ["하자","누수","층간소음","소음","협소"]): sc += float(p["memo_defect"])
        return sc
    dc["score_memo"] = dc["memo"].apply(_memo) if "memo" in dc.columns else 0.0

    # 초품아
    choguma_sc = float(p.get("choguma_score", 0))
    radius     = int(p.get("choguma_radius", 200))
    if kakao_key and choguma_sc > 0 and "complex_name" in dc.columns:
        cache = {}
        def _choguma(cn):
            if cn not in cache:
                ok, _ = _check_choguma(cn, kakao_key, radius)
                cache[cn] = choguma_sc if ok else 0.0
            return cache[cn]
        dc["score_choguma"] = dc["complex_name"].apply(_choguma)
    else:
        dc["score_choguma"] = 0.0

    dc["score"] = (
        dc["score_price"] + dc["score_drop"] + dc["score_new"] + dc["score_conf"]
        + dc["score_floor"] + dc["score_dir"] + dc["score_area"] + dc["score_memo"]
        + dc["score_choguma"]
    ).round(1)
    return dc


# ══════════════════════════════════════════════
# 사이드바
# ══════════════════════════════════════════════
df_all = build_df()
if df_all.empty:
    st.error("데이터 없음"); st.stop()

sel, price_sel, _ = render_sidebar(df_all, show_drop_th=False)

# Kakao API 키 (환경변수 우선, 없으면 사이드바 입력)
with st.sidebar:
    st.divider()
    st.markdown("**🗝️ Kakao API 키**")
    _env_key = os.environ.get("KAKAO_API_KEY", "")
    if _env_key:
        st.caption("✅ 환경변수에서 로드됨")
        kakao_key = _env_key
    else:
        kakao_key = st.text_input(
            "REST API 키", type="password",
            placeholder="26ff...", label_visibility="collapsed",
            key="kakao_api_key_input",
        )
    if kakao_key:
        st.caption("초품아 자동 감지 활성화")

if not sel:
    st.warning("왼쪽에서 단지를 선택해 주세요."); st.stop()

df = df_all[df_all["complex_name"].isin(sel)].copy()
df = df[(df["eok"] >= price_sel[0]) & (df["eok"] <= price_sel[1])]
if df.empty:
    st.warning("조건에 맞는 데이터가 없습니다."); st.stop()


# ══════════════════════════════════════════════
# 헤더
# ══════════════════════════════════════════════
st.markdown("#### 🏆 핵심 추천 매물")

# ══════════════════════════════════════════════
# [상단] 프리셋 + SET 버튼
# ══════════════════════════════════════════════
p_cols = st.columns([1, 1, 1, 1])

for i in range(3):
    preset = st.session_state.presets[i]
    with p_cols[i]:
        has = preset["params"] is not None
        st.markdown(
            f"<div style='font-size:10px;font-weight:600;color:#64748b;margin-bottom:2px;'>"
            f"{'✅' if has else '⬜'} 슬롯 {i+1}</div>",
            unsafe_allow_html=True,
        )
        new_name = st.text_input(
            "이름", value=preset["name"],
            key=f"preset_name_{i}", label_visibility="collapsed",
            placeholder=f"프리셋 {i+1}",
        )
        st.session_state.presets[i]["name"] = new_name

        bc1, bc2 = st.columns(2)
        if bc1.button("저장", key=f"save_preset_{i}", use_container_width=True):
            st.session_state.presets[i]["params"] = {
                k: st.session_state[f"sp_{k}"] for k in DEFAULT_PARAMS
            }
            st.toast(f"'{new_name}' 저장 완료 💾")

        load_disabled = preset["params"] is None
        if bc2.button("불러오기", key=f"load_preset_{i}",
                      use_container_width=True, disabled=load_disabled):
            for k, v in preset["params"].items():
                st.session_state[f"sp_{k}"] = v
            st.rerun()

with p_cols[3]:
    st.markdown(
        "<div style='font-size:10px;font-weight:600;color:#64748b;margin-bottom:2px;'>추천 실행</div>",
        unsafe_allow_html=True,
    )
    if st.button("🎯 SET 실행", type="primary", use_container_width=True):
        st.session_state.run_params   = {k: st.session_state[f"sp_{k}"] for k in DEFAULT_PARAMS}
        st.session_state.show_confirm = True
        st.session_state.show_results = False

    if st.session_state.show_confirm:
        ok_col, cancel_col = st.columns(2)
        if ok_col.button("✅ 확인", type="primary", use_container_width=True, key="confirm_yes"):
            st.session_state.show_results = True
            st.session_state.show_confirm = False
            st.rerun()
        if cancel_col.button("✖ 취소", use_container_width=True, key="confirm_no"):
            st.session_state.show_confirm = False
            st.rerun()
    elif st.session_state.show_results:
        if st.button("🔄 초기화", use_container_width=True):
            st.session_state.show_results = False
            st.rerun()

st.divider()

# ══════════════════════════════════════════════
# 점수 기준 입력 폼 (접힌 상태로)
# ══════════════════════════════════════════════
with st.expander("⚙️ 점수 기준 입력 (클릭해서 열기)", expanded=False):
    c1, c2, c3, c4, c5 = st.columns(5)

    with c1:
        st.caption("**💰 가격**")
        st.number_input("기준가(억)",       min_value=1.0,  max_value=20.0, step=0.5, key="sp_price_base")
        st.number_input("1천만원당 ±점",    min_value=0.0,  max_value=50.0, step=1.0, key="sp_price_per_1000")
        st.caption("**📐 평형**")
        st.number_input("59㎡",             min_value=-100, max_value=100,  step=5,   key="sp_area_59")
        st.number_input("74㎡",             min_value=-100, max_value=100,  step=5,   key="sp_area_74")
        st.number_input("84㎡",             min_value=-100, max_value=100,  step=5,   key="sp_area_84")
        st.number_input("100㎡+",           min_value=-100, max_value=100,  step=5,   key="sp_area_100up")

    with c2:
        st.caption("**🏢 층수**")
        st.number_input("1~5층",            min_value=-100, max_value=100,  step=5,   key="sp_floor_1_5")
        st.number_input("6~10층",           min_value=-100, max_value=100,  step=5,   key="sp_floor_6_10")
        st.number_input("11~15층",          min_value=-100, max_value=100,  step=5,   key="sp_floor_11_15")
        st.number_input("16~20층",          min_value=-100, max_value=100,  step=5,   key="sp_floor_16_20")
        st.number_input("21층+",            min_value=-100, max_value=100,  step=5,   key="sp_floor_21_up")

    with c3:
        st.caption("**🧭 방향**")
        st.number_input("남향",             min_value=-50,  max_value=100,  step=5,   key="sp_dir_남향")
        st.number_input("남동",             min_value=-50,  max_value=100,  step=5,   key="sp_dir_남동")
        st.number_input("남서",             min_value=-50,  max_value=100,  step=5,   key="sp_dir_남서")
        st.number_input("동향",             min_value=-50,  max_value=100,  step=5,   key="sp_dir_동")
        st.number_input("서향",             min_value=-50,  max_value=100,  step=5,   key="sp_dir_서")
        st.number_input("북동",             min_value=-100, max_value=100,  step=5,   key="sp_dir_북동")
        st.number_input("북/북서",          min_value=-100, max_value=100,  step=5,   key="sp_dir_북")

    with c4:
        st.caption("**📉 하락폭**")
        st.number_input("최대점수",         min_value=0,    max_value=100,  step=5,   key="sp_drop_max")
        st.caption("**🆕 신규등록**")
        st.number_input("기간(일)",         min_value=1,    max_value=60,   step=1,   key="sp_new_days")
        st.number_input("점수",             min_value=0,    max_value=100,  step=5,   key="sp_new_score")
        st.caption("**✅ 확인매물**")
        st.number_input("14일 이내",        min_value=0,    max_value=100,  step=5,   key="sp_conf_14d")
        st.number_input("30일 이내",        min_value=0,    max_value=100,  step=5,   key="sp_conf_30d")

    with c5:
        st.caption("**📝 메모**")
        st.number_input("조망·뷰",          min_value=-50,  max_value=100,  step=5,   key="sp_memo_view")
        st.number_input("급매",             min_value=-50,  max_value=100,  step=5,   key="sp_memo_urgent")
        st.number_input("남향언급",         min_value=-50,  max_value=100,  step=5,   key="sp_memo_south")
        st.number_input("하자(감점)",       min_value=-100, max_value=0,    step=5,   key="sp_memo_defect")
        st.caption("**🏫 초품아**")
        st.number_input("초품아 점수",      min_value=0,    max_value=100,  step=5,   key="sp_choguma_score")
        st.number_input("반경(m)",          min_value=100,  max_value=1000, step=50,  key="sp_choguma_radius")
        if not kakao_key:
            st.caption("⚠️ API키 없으면 0점")


# ══════════════════════════════════════════════
# 결과 출력
# ══════════════════════════════════════════════
if st.session_state.show_results and st.session_state.run_params:
    p = st.session_state.run_params

    # 초품아 검사 결과 미리 표시
    if kakao_key and p.get("choguma_score", 0) > 0:
        with st.spinner("🏫 초품아 여부 확인 중..."):
            choguma_info = {}
            for cn in sel:
                ok, info = _check_choguma(cn, kakao_key, int(p["choguma_radius"]))
                choguma_info[cn] = (ok, info)
        cols_ch = st.columns(len(sel))
        for i, cn in enumerate(sel):
            ok, info = choguma_info[cn]
            icon = "🏫✅" if ok else "🏫❌"
            cols_ch[i].markdown(
                f"<div style='font-size:11px;padding:6px;background:"
                f"{'#dcfce7' if ok else '#f1f5f9'};border-radius:6px;'>"
                f"<b>{icon} {cn}</b><br>{info}</div>",
                unsafe_allow_html=True,
            )
    else:
        choguma_info = {}

    parts = [
        _compute_custom(df[df["complex_name"] == cn].copy(), p, kakao_key)
        for cn in sel if not df[df["complex_name"] == cn].empty
    ]
    if not parts:
        st.info("계산할 데이터가 없습니다."); st.stop()

    df_sc      = pd.concat(parts, ignore_index=True)
    latest_day = df_sc["uploadday"].max()
    df_latest  = df_sc[df_sc["uploadday"] == latest_day].copy()
    if "uid" in df_latest.columns:
        df_latest = df_latest.sort_values("score", ascending=False).drop_duplicates("uid")

    top5 = df_latest.sort_values("score", ascending=False).head(5).reset_index(drop=True)

    # ── TOP 5 카드 ──────────────────────────
    st.markdown(
        f'<div class="sec">🥇 TOP 5 추천 매물 '
        f'<span style="font-size:10px;color:#94a3b8;">'
        f'기준일: {latest_day.strftime("%Y-%m-%d")}</span></div>',
        unsafe_allow_html=True,
    )

    card_cols = st.columns(5)
    for i, row in top5.iterrows():
        badges   = get_badges(row)
        parts_d  = [p_str for p_str in [
            f"{row['dong']}동"   if pd.notna(row.get("dong"))      and str(row.get("dong"))      not in ("","nan") else "",
            f"{row['area']}"     if pd.notna(row.get("area"))                                                       else "",
            f"{row['floor']}층"  if pd.notna(row.get("floor"))                                                      else "",
            f"{row['direction']}"if pd.notna(row.get("direction")) and str(row.get("direction")) not in ("","nan") else "",
        ] if p_str]
        drop_txt  = f"▼{row['drop_eok']:.2f}억 하락" if row.get("drop_eok", 0) > 0 else ""
        date_str  = f"확인: {row['confirm_date']}" if pd.notna(row.get("confirm_date")) and str(row.get("confirm_date")) not in ("","nan") else ""
        memo_str  = str(row.get("memo",""))[:25] if pd.notna(row.get("memo")) and str(row.get("memo")) not in ("","nan") else ""

        def _fmt(v, lbl):
            if not v: return ""
            return f'<span style="color:{"#16a34a" if v>0 else "#dc2626"};font-size:9px;">{lbl}{"+" if v>0 else ""}{v:.0f}</span>'

        choguma_badge = (
            '<span class="rec-badge badge-new">🏫 초품아</span>'
            if row.get("score_choguma", 0) > 0 else ""
        )
        breakdown = " ".join(filter(None, [
            _fmt(row.get("score_price",   0),"가격"),
            _fmt(row.get("score_floor",   0),"층"),
            _fmt(row.get("score_dir",     0),"방향"),
            _fmt(row.get("score_area",    0),"평형"),
            _fmt(row.get("score_drop",    0),"하락"),
            _fmt(row.get("score_memo",    0),"메모"),
            _fmt(row.get("score_choguma", 0),"초품아"),
        ]))
        bar_w = max(0, min(100, int((row["score"] + 50) / 150 * 100)))

        with card_cols[i]:
            st.markdown(f"""
<div class="rec-card">
  <div style="display:flex;justify-content:space-between;align-items:center;">
    <span class="rec-rank">{RANK_EMOJIS[i]}</span>
    <span style="font-size:13px;color:#6366f1;font-weight:800;">{row['score']:.0f}점</span>
  </div>
  <div class="rec-name" style="margin-top:4px;">{row.get('complex_name','')}</div>
  <div class="rec-price">{row['eok']:.2f}억</div>
  <div style="margin-top:4px;">{badges}{choguma_badge}</div>
  <div class="rec-detail" style="margin-top:6px;">{"  ·  ".join(parts_d)}</div>
  {'<div class="rec-detail" style="color:#ef4444;">' + drop_txt + '</div>' if drop_txt else ''}
  {'<div class="rec-detail">' + date_str + '</div>' if date_str else ''}
  {'<div class="rec-detail" style="color:#475569;font-style:italic;">' + memo_str + '</div>' if memo_str else ''}
  <div style="margin-top:6px;line-height:1.8;">{breakdown}</div>
  <div class="score-bar-bg"><div class="score-bar-fill" style="width:{bar_w}%;"></div></div>
</div>""", unsafe_allow_html=True)

    # ── 전체 순위표 (compact) ───────────────
    st.markdown('<div class="sec" style="margin-top:14px;">📋 전체 순위</div>', unsafe_allow_html=True)

    want = ["complex_name","eok","score","score_price","score_floor","score_dir",
            "score_area","score_drop","score_new","score_conf","score_memo",
            "floor","direction","area","dong"]
    show_cols = [c for c in want if c in df_latest.columns]
    df_show = df_latest[show_cols].sort_values("score", ascending=False).reset_index(drop=True)
    df_show.index += 1
    df_show.rename(columns={
        "complex_name":"단지","eok":"가격(억)","score":"총점",
        "score_price":"가격점","score_floor":"층수점","score_dir":"방향점",
        "score_area":"평형점","score_drop":"하락점","score_new":"신규점",
        "score_conf":"확인점","score_memo":"메모점",
        "floor":"층","direction":"방향","area":"평형","dong":"동",
    }, inplace=True)

    st.dataframe(df_show, use_container_width=True, height=320)
