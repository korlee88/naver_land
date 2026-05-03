"""
utils_graph.py  ─  graph_v2 / recommend 공통 유틸
  - 상수, 정규식, 파싱 헬퍼
  - DB 로드 (build_df, make_daily)
  - 점수 계산 (compute_score, get_badges)
  - 공통 CSS 주입
"""

import re
from datetime import datetime, timedelta

import streamlit as st
import pandas as pd
import numpy as np

import db

# ── 상수 ──────────────────────────────────────
RENT_WORDS  = ("전세", "월세", "임대", "렌트", "단기", "보증금")
SKIP_KW     = ("협의", "문의", "미정", "없음", "N/A", "nan")
DROP_TH     = 0.1
RECENT_DAYS = 7

# ── 정규식 ─────────────────────────────────────
_RE_STRIP  = re.compile(r"[,\s매매전세월세]")
_RE_EOK_EX = re.compile(r"^(\d+(?:\.\d+)?)억$")
_RE_EOK    = re.compile(r"(\d+(?:\.\d+)?)억")
_RE_CHEON  = re.compile(r"(\d+(?:\.\d+)?)천")
_RE_MAN    = re.compile(r"(\d+(?:\.\d+)?)만")
_RE_DIGITS = re.compile(r"^\d+(?:\.\d+)?$")
_RE_FLOOR  = re.compile(r"^(\d+)")

RANK_EMOJIS = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
PALETTE     = ["#3b82f6", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#06b6d4"]

# ── 공통 CSS ───────────────────────────────────
SHARED_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Noto Sans KR', sans-serif; }

div[data-testid="metric-container"] {
    background: #f8fafc; border: 1px solid #e2e8f0;
    border-radius: 8px; padding: 6px 10px;
}
div[data-testid="metric-container"] label { color: #64748b !important; font-size: 10px; }
div[data-testid="metric-container"] [data-testid="metric-value"]
    { color: #1e293b !important; font-size: 1.0rem; font-weight: 700; }
div[data-testid="metric-container"] [data-testid="metric-delta"] { font-size: 10px; }

.sec {
    font-size: 12px; font-weight: 700; color: #1e293b;
    border-left: 3px solid #6366f1; padding-left: 7px;
    margin: 8px 0 5px 0;
}

.rec-card {
    background: linear-gradient(135deg, #ffffff 0%, #f8faff 100%);
    border: 1px solid #e0e7ff; border-left: 4px solid #6366f1;
    border-radius: 10px; padding: 12px 14px; margin-bottom: 8px;
}
.rec-rank  { font-size: 18px; font-weight: 800; color: #6366f1; }
.rec-name  { font-size: 13px; font-weight: 700; color: #1e293b; }
.rec-price { font-size: 20px; font-weight: 800; color: #dc2626; }
.rec-badge {
    display: inline-block; font-size: 10px; font-weight: 600;
    padding: 2px 7px; border-radius: 20px; margin: 2px 2px 0 0;
}
.badge-new  { background: #dcfce7; color: #16a34a; }
.badge-drop { background: #fee2e2; color: #dc2626; }
.badge-hot  { background: #fef3c7; color: #d97706; }
.badge-conf { background: #ede9fe; color: #7c3aed; }
.rec-detail { font-size: 11px; color: #64748b; margin-top: 4px; }
.score-bar-bg  { background: #e2e8f0; border-radius: 4px; height: 6px; margin-top: 6px; }
.score-bar-fill {
    background: linear-gradient(90deg, #6366f1, #8b5cf6);
    border-radius: 4px; height: 6px;
}
[data-testid="stSidebar"] { background: #f8fafc; }
div[data-testid="stVerticalBlock"] > div { gap: 0.2rem; }
</style>
"""


# ══════════════════════════════════════════════
# 파싱 헬퍼
# ══════════════════════════════════════════════
def parse_price_to_eok(t):
    if not t: return None
    s = str(t).strip()
    if not s or any(w in s for w in RENT_WORDS) or any(k in s for k in SKIP_KW): return None
    s = _RE_STRIP.sub("", s)
    m = _RE_EOK_EX.fullmatch(s)
    if m: return float(m.group(1))
    m = _RE_EOK.search(s)
    if m:
        eok = float(m.group(1)); rest = s[m.end():]
        if not rest: return eok
        if _RE_DIGITS.fullmatch(rest): return eok + float(rest) / 10000
        mc = _RE_CHEON.search(rest)
        if mc: return eok + float(mc.group(1)) / 10
        mm = _RE_MAN.search(rest)
        if mm: return eok + float(mm.group(1)) / 10000
        return None
    m = _RE_MAN.fullmatch(s)
    return float(m.group(1)) / 10000 if m else None


def clean_name(x):
    if x is None: return ""
    s = str(x).replace("\u200b", "").strip()
    return "" if s in ("", "1", "None", "nan", "NaN", "UNKNOWN") or len(s) <= 1 else s


def days_since(confirm_text):
    if not confirm_text: return None
    try:
        y, mo, d = str(confirm_text).strip().split(".")
        return (datetime.now() - datetime(2000 + int(y), int(mo), int(d))).days
    except Exception: return None


# ══════════════════════════════════════════════
# DB 로드
# ══════════════════════════════════════════════
@st.cache_data(show_spinner=False, ttl=60)
def build_df():
    try: db.init_db()
    except Exception: pass
    hist = pd.DataFrame(db.read_history())
    lst  = pd.DataFrame(db.read_listings())

    if hist.empty or not {"uid", "seen_at", "price_text"}.issubset(hist.columns): return pd.DataFrame()
    if lst.empty  or not {"uid", "complex_name", "trade_type"}.issubset(lst.columns): return pd.DataFrame()

    hist["seen_at"] = pd.to_datetime(hist["seen_at"], errors="coerce", utc=True).dt.tz_convert(None)

    # seen_at 없는 경우 batch_id 앞 날짜(YYYY-MM-DD)로 보완
    if "batch_id" in hist.columns:
        nat_mask = hist["seen_at"].isna()
        if nat_mask.any():
            batch_dates = hist.loc[nat_mask, "batch_id"].astype(str).str.extract(r"^(\d{4}-\d{2}-\d{2})", expand=False)
            hist.loc[nat_mask, "seen_at"] = pd.to_datetime(batch_dates, errors="coerce")

    hist              = hist.dropna(subset=["seen_at"]).copy()
    hist["uploadday"] = hist["seen_at"].dt.floor("D")  # 날짜만 (시간 제거)

    want = ["uid", "complex_name", "trade_type", "floor", "direction", "area", "confirm_date", "memo", "dong"]
    cols = [c for c in want if c in lst.columns]
    df   = hist.merge(lst[cols], on="uid", how="left")
    # hist와 lst 모두 memo 컬럼을 가질 경우 merge 후 memo_x/memo_y로 분리됨 → lst의 memo 우선 사용
    if "memo_y" in df.columns:
        df["memo"] = df["memo_y"].fillna(df.get("memo_x"))
        df.drop(columns=[c for c in ["memo_x", "memo_y"] if c in df.columns], inplace=True)
    elif "memo_x" in df.columns:
        df.rename(columns={"memo_x": "memo"}, inplace=True)
    df   = df[df["trade_type"] == "매매"].copy()
    df["complex_name"] = df["complex_name"].apply(clean_name)
    df   = df[df["complex_name"] != ""].copy()
    df["eok"]         = df["price_text"].apply(parse_price_to_eok)
    df["confirm_age"] = df["confirm_date"].apply(days_since) if "confirm_date" in df.columns else np.nan
    df   = df.dropna(subset=["eok", "uploadday"]).copy()
    return df


def make_daily(dfc, drop_th=DROP_TH):
    daily = (
        dfc.groupby("uploadday")["eok"]
           .agg(min_eok="min", max_eok="max", avg_eok="mean", n="count")
           .reset_index().sort_values("uploadday")
    )
    all_days = pd.date_range(daily["uploadday"].min(), daily["uploadday"].max(), freq="D")
    d2 = daily.set_index("uploadday").reindex(all_days).rename_axis("uploadday")
    d2[["min_eok", "max_eok", "avg_eok"]] = d2[["min_eok", "max_eok", "avg_eok"]].ffill()
    d2["n"]       = d2["n"].fillna(0).astype(int)
    d2            = d2.reset_index()
    d2["min_7avg"] = d2["min_eok"].rolling(7, min_periods=3).mean().shift(1)
    d2["is_drop"]  = (d2["min_eok"] - d2["min_7avg"]) <= -drop_th
    return d2


# ══════════════════════════════════════════════
# 점수 계산
# ══════════════════════════════════════════════
def _floor_score(floor_val):
    if not floor_val or pd.isna(floor_val): return 0.0
    s = str(floor_val).strip()
    if s.startswith(("저", "지", "반")): return -30.0
    m = _RE_FLOOR.match(s)
    if not m: return 0.0
    n = int(m.group(1))
    if n <= 5:  return -30.0
    if n <= 10: return   0.0
    if n <= 15: return  25.0
    if n <= 20: return  35.0
    return 40.0


def _direction_score(dir_val):
    if not dir_val or pd.isna(dir_val): return 0.0
    d = str(dir_val).strip()
    if "남향" in d:              return 25.0
    if "남동" in d:              return 20.0
    if "남서" in d:              return 15.0
    if "동향" in d or d == "동": return  5.0
    if "서향" in d or d == "서": return  0.0
    if "북동" in d:              return -5.0
    if "북" in d:                return -15.0
    return 0.0


def _area_score(area_val):
    if not area_val or pd.isna(area_val): return 0.0
    s = str(area_val)
    nums = re.findall(r"\d+\.?\d*", s)
    if not nums: return 0.0
    v = float(nums[0])
    if v < 10: v = v * 3.305785
    if   50 <= v <  66: return  10.0
    elif 66 <= v <  80: return  15.0
    elif 80 <= v <  95: return   0.0
    elif v >= 95:       return -20.0
    return 0.0


def _memo_score(memo_val):
    if not memo_val or pd.isna(memo_val): return 0.0
    s = str(memo_val).lower()
    score = 0.0
    if any(k in s for k in ["조망", "뷰", "view", "탁트"]): score += 10.0
    if any(k in s for k in ["급매", "급처", "급", "특가"]):  score +=  5.0
    if any(k in s for k in ["남향", "햇빛", "일조"]):        score +=  5.0
    if any(k in s for k in ["하자", "누수", "층간소음", "소음", "협소"]): score -= 10.0
    return score


def _view_score(row, view_map):
    """동별 조망 점수: DB의 view_scores 기준, 층수 미달 시 0점"""
    cn   = str(row.get("complex_name") or "").strip().lower()
    dong = str(row.get("dong") or "").strip()
    info = view_map.get((cn, dong))
    if not info:
        return 0.0
    floor_n = _parse_floor_n(row.get("floor"))
    if floor_n is not None and floor_n < info["min_floor"]:
        return 0.0
    return float(info["score"])


def _parse_floor_n(val):
    if not val or (isinstance(val, float) and val != val): return None
    m = _RE_FLOOR.match(str(val).strip())
    return int(m.group(1)) if m else None


def compute_score(dfc):
    dc = dfc.copy()
    dc["score_price"] = ((4.0 - dc["eok"]) / 0.1 * 5).round(1)

    if "uid" in dc.columns:
        first = dc.sort_values("uploadday").groupby("uid")["eok"].first()
        last  = dc.sort_values("uploadday").groupby("uid")["eok"].last()
        dc    = dc.merge((first - last).clip(lower=0).rename("drop_eok").reset_index(),
                         on="uid", how="left")
    else:
        dc["drop_eok"] = 0.0
    mx = dc["drop_eok"].max()
    dc["score_drop"] = (dc["drop_eok"] / mx * 20 if mx > 0 else pd.Series(0.0, index=dc.index)).round(1)

    cut = pd.Timestamp(datetime.now() - timedelta(days=RECENT_DAYS))
    dc["score_new"] = dc["uploadday"].apply(lambda d: 10.0 if pd.notna(d) and d >= cut else 0.0)

    if "confirm_age" in dc.columns:
        dc["score_conf"] = dc["confirm_age"].apply(
            lambda v: 10.0 if pd.notna(v) and v <= 14
                      else (5.0 if pd.notna(v) and v <= 30 else 0.0)
        )
    else:
        dc["score_conf"] = 0.0

    dc["score_floor"] = dc["floor"].apply(_floor_score)         if "floor"     in dc.columns else 0.0
    dc["score_dir"]   = dc["direction"].apply(_direction_score)  if "direction" in dc.columns else 0.0
    dc["score_area"]  = dc["area"].apply(_area_score)            if "area"      in dc.columns else 0.0
    dc["score_memo"]  = dc["memo"].apply(_memo_score)            if "memo"      in dc.columns else 0.0

    try:
        from db import load_view_scores
        view_map = load_view_scores()
        dc["score_view"] = dc.apply(lambda r: _view_score(r, view_map), axis=1)
    except Exception:
        dc["score_view"] = 0.0

    dc["score"] = (
        dc["score_price"] + dc["score_drop"] + dc["score_new"] + dc["score_conf"]
        + dc["score_floor"] + dc["score_dir"] + dc["score_area"] + dc["score_memo"]
        + dc["score_view"]
    ).round(1)
    return dc


def get_badges(row):
    badges = []
    cut = pd.Timestamp(datetime.now() - timedelta(days=RECENT_DAYS))
    if pd.notna(row.get("uploadday")) and row["uploadday"] >= cut:
        badges.append('<span class="rec-badge badge-new">신규</span>')
    if row.get("drop_eok", 0) > 0:
        badges.append(f'<span class="rec-badge badge-drop">▼{row["drop_eok"]:.2f}억 하락</span>')
    memo_txt = str(row.get("memo", "") or "").lower()
    is_urgent = (any(k in memo_txt for k in ["급매", "급처", "급!", "특가"]) or
                 (row.get("score_new", 0) > 0 and row.get("score_drop", 0) > 15))
    if is_urgent:
        badges.append('<span class="rec-badge badge-hot">급매</span>')
    if row.get("score_conf", 0) > 0:
        badges.append('<span class="rec-badge badge-conf">확인매물</span>')
    return "".join(badges)


# ══════════════════════════════════════════════
# 공통 사이드바 필터
# ══════════════════════════════════════════════
def render_sidebar(df_all, show_drop_th=False):
    """사이드바 필터 렌더링. (sel, price_sel, drop_th) 반환"""
    with st.sidebar:
        st.markdown("## 🔍 필터")
        if st.button("🔄 캐시 초기화", use_container_width=True):
            st.cache_data.clear(); st.rerun()
        st.divider()

        complex_list = sorted(df_all["complex_name"].unique().tolist())
        sel = st.multiselect(
            "단지 선택 (최대 4개 권장)", complex_list,
            default=complex_list[:min(4, len(complex_list))],
            key="sidebar_sel_complexes",
        )

        st.markdown("**가격 범위 (억)**")
        p_lo = float(df_all["eok"].min())
        p_hi = float(df_all["eok"].max())
        price_sel = st.slider(
            "가격", p_lo, p_hi, (p_lo, p_hi),
            step=0.1, format="%.1f억", label_visibility="collapsed",
            key="sidebar_price_sel",
        )

        drop_th = DROP_TH
        if show_drop_th:
            st.markdown("**급매 감지 기준 (억)**")
            drop_th = st.slider(
                "급매 기준", 0.05, 0.5, DROP_TH,
                step=0.05, format="%.2f억", label_visibility="collapsed",
                key="sidebar_drop_th",
            )
            st.caption(f"차트에서 최저가가 7일 평균 대비 {drop_th:.2f}억 이상 하락하면 ▼급락 표시")

    return sel, price_sel, drop_th
