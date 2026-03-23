"""
graph_v2.py  ─  매물 분석 대시보드 (ver.2)
구성:
  [1] KPI 메트릭 (1줄, 컴팩트)
  [2] 단지별 추이 차트 (단지 수만큼 동적 컬럼, 소형)
  [3] 핵심 추천 매물 5개 (카드형 상세)
"""

import re
from datetime import datetime, timedelta

import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import plotly.express as px
import plotly.graph_objects as go

import db
from utils_style import inject_korean_font

# ══════════════════════════════════════════════
# 페이지 설정
# ══════════════════════════════════════════════
st.set_page_config(
    page_title="매물 분석 v2",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_korean_font()   # ← 한글 폰트 (Railway/Linux 깨짐 방지, matplotlib 포함)

plt.rcParams.update({"font.size": 7, "axes.titlesize": 8})

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Noto Sans KR', sans-serif; }

/* KPI 메트릭 카드 - 컴팩트 */
div[data-testid="metric-container"] {
    background: #f8fafc; border: 1px solid #e2e8f0;
    border-radius: 8px; padding: 6px 10px;
}
div[data-testid="metric-container"] label
    { color: #64748b !important; font-size: 10px; }
div[data-testid="metric-container"] [data-testid="metric-value"]
    { color: #1e293b !important; font-size: 1.0rem; font-weight: 700; }
div[data-testid="metric-container"] [data-testid="metric-delta"]
    { font-size: 10px; }

.sec {
    font-size: 12px; font-weight: 700; color: #1e293b;
    border-left: 3px solid #6366f1; padding-left: 7px;
    margin: 8px 0 5px 0;
}

/* 핵심 매물 카드 */
.rec-card {
    background: linear-gradient(135deg, #ffffff 0%, #f8faff 100%);
    border: 1px solid #e0e7ff;
    border-left: 4px solid #6366f1;
    border-radius: 10px;
    padding: 12px 14px;
    margin-bottom: 8px;
}
.rec-rank { font-size: 18px; font-weight: 800; color: #6366f1; }
.rec-name { font-size: 13px; font-weight: 700; color: #1e293b; }
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
.score-bar-bg {
    background: #e2e8f0; border-radius: 4px; height: 6px; margin-top: 6px;
}
.score-bar-fill {
    background: linear-gradient(90deg, #6366f1, #8b5cf6);
    border-radius: 4px; height: 6px;
}

[data-testid="stSidebar"] { background: #f8fafc; }
div[data-testid="stVerticalBlock"] > div { gap: 0.2rem; }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════
# 상수 & 정규식
# ══════════════════════════════════════════════
RENT_WORDS  = ("전세","월세","임대","렌트","단기","보증금")
SKIP_KW     = ("협의","문의","미정","없음","N/A","nan")
DROP_TH     = 0.1
RECENT_DAYS = 7
PALETTE     = px.colors.qualitative.Plotly

_RE_STRIP  = re.compile(r"[,\s매매전세월세]")
_RE_EOK_EX = re.compile(r"^(\d+(?:\.\d+)?)억$")
_RE_EOK    = re.compile(r"(\d+(?:\.\d+)?)억")
_RE_CHEON  = re.compile(r"(\d+(?:\.\d+)?)천")
_RE_MAN    = re.compile(r"(\d+(?:\.\d+)?)만")
_RE_DIGITS = re.compile(r"^\d+(?:\.\d+)?$")
_RE_FLOOR  = re.compile(r"^(\d+)")


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
    return "" if s in ("","1","None","nan","NaN","UNKNOWN") or len(s) <= 1 else s


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

    if hist.empty or not {"uid","seen_at","price_text"}.issubset(hist.columns): return pd.DataFrame()
    if lst.empty  or not {"uid","complex_name","trade_type"}.issubset(lst.columns): return pd.DataFrame()

    hist["seen_at"]   = pd.to_datetime(hist["seen_at"], errors="coerce")
    hist              = hist.dropna(subset=["seen_at"]).copy()
    hist["uploadday"] = hist["seen_at"].dt.normalize()

    want = ["uid","complex_name","trade_type","floor","direction","area","confirm_date","memo","dong"]
    cols = [c for c in want if c in lst.columns]
    df   = hist.merge(lst[cols], on="uid", how="left")
    df   = df[df["trade_type"] == "매매"].copy()
    df["complex_name"] = df["complex_name"].apply(clean_name)
    df   = df[df["complex_name"] != ""].copy()
    df["eok"]         = df["price_text"].apply(parse_price_to_eok)
    df["confirm_age"] = df["confirm_date"].apply(days_since) if "confirm_date" in df.columns else np.nan
    df   = df.dropna(subset=["eok","uploadday"]).copy()
    return df


def make_daily(dfc, drop_th=DROP_TH):
    daily = (
        dfc.groupby("uploadday")["eok"]
           .agg(min_eok="min", max_eok="max", avg_eok="mean", n="count")
           .reset_index().sort_values("uploadday")
    )
    all_days = pd.date_range(daily["uploadday"].min(), daily["uploadday"].max(), freq="D")
    d2 = daily.set_index("uploadday").reindex(all_days).rename_axis("uploadday")
    d2[["min_eok","max_eok","avg_eok"]] = d2[["min_eok","max_eok","avg_eok"]].ffill()
    d2["n"]      = d2["n"].fillna(0).astype(int)
    d2           = d2.reset_index()
    d2["min_7avg"] = d2["min_eok"].rolling(7, min_periods=3).mean().shift(1)
    d2["is_drop"]  = (d2["min_eok"] - d2["min_7avg"]) <= -drop_th
    return d2


def draw_trend_ax(ax, dfc, cname, color, drop_th):
    """단일 axes에 추이 차트 그리기 (선 위주, 컴팩트)"""
    ax2 = ax.twinx()
    d2  = make_daily(dfc, drop_th)
    x   = pd.to_datetime(d2["uploadday"])
    mn_v, mx_v, nv = d2["min_eok"], d2["max_eok"], d2["n"]
    mask = x.notna() & mn_v.notna()

    # 건수 바차트 (배경, 매우 연하게)
    ax2.bar(x, nv, width=0.5, alpha=0.08, color="#94a3b8", zorder=0)
    ax2.set_ylim(0, max(1, int(nv.max() * 3)))
    ax2.tick_params(axis="y", labelsize=4, colors="#c0c8d4")
    ax2.set_ylabel("건수", fontsize=5, color="#c0c8d4")

    # 면적 제거, 선만 표시
    ax.plot(x[mask], mn_v[mask], color=color, lw=1.2, ls="--", label="최저", zorder=3)
    ax.plot(x[mask], mx_v[mask], color=color, lw=0.9, alpha=0.6, label="최고", zorder=3)

    # 급락 마커
    drops = d2[d2["is_drop"]]
    if not drops.empty:
        ax.scatter(pd.to_datetime(drops["uploadday"]), drops["min_eok"],
                   s=18, marker="v", color="#ef4444",
                   edgecolors="white", lw=0.3, zorder=5, label="▼급락")

    ax.set_title(cname, fontsize=8, fontweight="bold", pad=2)
    ax.set_ylabel("가격(억)", fontsize=6)
    ax.legend(fontsize=5, loc="upper left", framealpha=0.5)
    ax.grid(True, alpha=0.12, lw=0.5)
    ax.tick_params(axis="both", labelsize=5)


# ══════════════════════════════════════════════
# 선호도 기반 점수 계산 (항목별 상세)
#
# [가격]    4억 기준 1000만원당 ±5점 (무제한)
# [층수]    1~5층 -30 / 6~10층 0 / 11~15층 +25 / 16~20층 +35 / 21층~ +40
# [방향]    남향+25 / 남동+20 / 남서+15 / 동+5 / 서0 / 북동-5 / 북·북서-15
# [평형]    59㎡+10 / 74㎡+15 / 84㎡+0 / 100㎡~-20
# [하락폭]  최대 20점 (비율 기반)
# [신규]    최근 7일 +10점
# [확인]    14일이내 +10 / 30일이내 +5
# [메모]    조망·뷰+10 / 급매+5 / 남향언급+5 / 하자·누수-10
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
    # ㎡ 단위로 판단
    if v < 10:           # 평 단위로 입력된 경우 (예: "24평")
        v = v * 3.305785
    if   50 <= v <  66:  return 10.0   # 59㎡ (24평)
    elif 66 <= v <  80:  return 15.0   # 74㎡ (29평) ← 최선호
    elif 80 <= v <  95:  return  0.0   # 84㎡ (34평)
    elif v >= 95:        return -20.0  # 100㎡~ (예산 초과)
    return 0.0

def _memo_score(memo_val):
    if not memo_val or pd.isna(memo_val): return 0.0
    s = str(memo_val).lower()
    score = 0.0
    # 호재 키워드
    if any(k in s for k in ["조망", "뷰", "view", "탁트"]): score += 10.0
    if any(k in s for k in ["급매", "급처", "급", "특가"]):  score +=  5.0
    if any(k in s for k in ["남향", "햇빛", "일조"]):        score +=  5.0
    # 악재 키워드
    if any(k in s for k in ["하자", "누수", "층간소음", "소음", "협소"]): score -= 10.0
    return score

def compute_score(dfc):
    dc = dfc.copy()

    # ① 가격: 4억 기준 1000만원당 ±5점
    dc["score_price"] = ((4.0 - dc["eok"]) / 0.1 * 5).round(1)

    # ② 가격 하락폭 (최대 20점)
    if "uid" in dc.columns:
        first = dc.sort_values("uploadday").groupby("uid")["eok"].first()
        last  = dc.sort_values("uploadday").groupby("uid")["eok"].last()
        dc    = dc.merge((first - last).clip(lower=0).rename("drop_eok").reset_index(),
                         on="uid", how="left")
    else:
        dc["drop_eok"] = 0.0
    mx = dc["drop_eok"].max()
    dc["score_drop"] = (dc["drop_eok"] / mx * 20 if mx > 0 else pd.Series(0.0, index=dc.index)).round(1)

    # ③ 신규등록 (10점)
    cut = pd.Timestamp(datetime.now() - timedelta(days=RECENT_DAYS))
    dc["score_new"] = dc["uploadday"].apply(lambda d: 10.0 if pd.notna(d) and d >= cut else 0.0)

    # ④ 확인매물 (최대 10점)
    if "confirm_age" in dc.columns:
        dc["score_conf"] = dc["confirm_age"].apply(
            lambda v: 10.0 if pd.notna(v) and v <= 14
                      else (5.0 if pd.notna(v) and v <= 30 else 0.0)
        )
    else:
        dc["score_conf"] = 0.0

    # ⑤ 층수 (-30 ~ +40)
    dc["score_floor"] = dc["floor"].apply(_floor_score) if "floor" in dc.columns else 0.0

    # ⑥ 방향 (-15 ~ +25)
    dc["score_dir"] = dc["direction"].apply(_direction_score) if "direction" in dc.columns else 0.0

    # ⑦ 평형 (-20 ~ +15)
    dc["score_area"] = dc["area"].apply(_area_score) if "area" in dc.columns else 0.0

    # ⑧ 메모 키워드 (-10 ~ +15)
    dc["score_memo"] = dc["memo"].apply(_memo_score) if "memo" in dc.columns else 0.0

    dc["score"] = (
        dc["score_price"] + dc["score_drop"] + dc["score_new"] + dc["score_conf"]
        + dc["score_floor"] + dc["score_dir"] + dc["score_area"] + dc["score_memo"]
    ).round(1)
    return dc


def get_badges(row):
    """매물 특성 배지 생성"""
    badges = []
    cut = pd.Timestamp(datetime.now() - timedelta(days=RECENT_DAYS))
    if pd.notna(row.get("uploadday")) and row["uploadday"] >= cut:
        badges.append(('<span class="rec-badge badge-new">신규</span>', True))
    if row.get("drop_eok", 0) > 0:
        badges.append((f'<span class="rec-badge badge-drop">▼{row["drop_eok"]:.2f}억 하락</span>', True))
    if row.get("score_new", 0) > 0 and row.get("score_drop", 0) > 15:
        badges.append(('<span class="rec-badge badge-hot">급매</span>', True))
    if row.get("score_conf", 0) > 0:
        badges.append(('<span class="rec-badge badge-conf">확인매물</span>', True))
    return "".join(b[0] for b in badges) if badges else ""


# ══════════════════════════════════════════════
# 사이드바
# ══════════════════════════════════════════════
with st.sidebar:
    st.markdown("## 🔍 필터")
    if st.button("🔄 캐시 초기화", use_container_width=True):
        st.cache_data.clear(); st.rerun()
    st.divider()

    df_all = build_df()
    if df_all.empty:
        st.error("데이터 없음"); st.stop()

    # 아파트 이름 기준 단지 목록 (괄호 전 이름으로 그룹 표시)
    complex_list = sorted(df_all["complex_name"].unique().tolist())
    sel = st.multiselect(
        "단지 선택 (최대 4개 권장)", complex_list,
        default=complex_list[:min(3, len(complex_list))],
    )

    st.markdown("**가격 범위 (억)**")
    p_lo, p_hi = float(df_all["eok"].min()), float(df_all["eok"].max())
    price_sel = st.slider("가격", p_lo, p_hi, (p_lo, p_hi),
                          step=0.1, format="%.1f억", label_visibility="collapsed")

    st.markdown("**급매 임계값 (억)**")
    drop_th_sel = st.slider("급매 기준", 0.05, 0.5, DROP_TH,
                            step=0.05, format="%.2f억", label_visibility="collapsed")


# ══════════════════════════════════════════════
# 필터 적용
# ══════════════════════════════════════════════
if not sel:
    st.warning("왼쪽에서 단지를 선택해 주세요."); st.stop()

df = df_all[df_all["complex_name"].isin(sel)].copy()
df = df[(df["eok"] >= price_sel[0]) & (df["eok"] <= price_sel[1])]
if df.empty:
    st.warning("조건에 맞는 데이터가 없습니다."); st.stop()


# ══════════════════════════════════════════════
# 헤더 (컴팩트)
# ══════════════════════════════════════════════
col_title, col_info = st.columns([3, 7])
with col_title:
    st.markdown(
        "#### 🏢 매물 분석 대시보드 "
        "<span style='font-size:11px;color:#94a3b8;'>ver.2</span>",
        unsafe_allow_html=True,
    )
with col_info:
    st.markdown(
        f"<div style='font-size:11px;color:#64748b;padding-top:10px;'>"
        f"단지: {', '.join(sel)}  |  총 {len(df):,}건</div>",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════
# [1] 단지별 추이 차트 (가로 나열, 소형)
# ══════════════════════════════════════════════
st.markdown('<div class="sec">📊 차트</div>', unsafe_allow_html=True)

COLORS = ["#3b82f6","#f59e0b","#10b981","#ef4444","#8b5cf6","#06b6d4"]
trend_names = sel[:4]
n_charts    = len(trend_names)

chart_cols = st.columns(n_charts, gap="small")

for idx, cname in enumerate(trend_names):
    dfc   = df[df["complex_name"] == cname]
    color = COLORS[idx % len(COLORS)]

    if dfc.empty:
        chart_cols[idx].caption(f"{cname} — 데이터 없음")
        continue

    d2   = make_daily(dfc, drop_th_sel)
    x    = d2["uploadday"]
    mask = x.notna() & d2["min_eok"].notna()

    import plotly.graph_objects as go
    fig = go.Figure()

    # 건수 바 (보조 y축)
    fig.add_trace(go.Bar(
        x=x, y=d2["n"],
        name="건수", yaxis="y2",
        marker_color="#e2e8f0", opacity=0.5,
        showlegend=False,
    ))
    # 최저가 선
    fig.add_trace(go.Scatter(
        x=x[mask], y=d2["min_eok"][mask],
        name="최저", line=dict(color=color, width=1.5, dash="dash"),
    ))
    # 최고가 선
    fig.add_trace(go.Scatter(
        x=x[mask], y=d2["max_eok"][mask],
        name="최고", line=dict(color=color, width=1.0), opacity=0.6,
    ))
    # 급락 마커
    drops = d2[d2["is_drop"]]
    if not drops.empty:
        fig.add_trace(go.Scatter(
            x=drops["uploadday"], y=drops["min_eok"],
            mode="markers", name="▼급락",
            marker=dict(symbol="triangle-down", size=8, color="#ef4444"),
        ))

    fig.update_layout(
        title=dict(text=cname, font=dict(size=12)),
        height=220,
        margin=dict(l=0, r=0, t=30, b=0),
        plot_bgcolor="white",
        legend=dict(orientation="h", y=1.15, x=0, font=dict(size=9)),
        xaxis=dict(tickfont=dict(size=8), tickangle=30),
        yaxis=dict(title="가격(억)", tickfont=dict(size=8), showgrid=True, gridcolor="#f1f5f9"),
        yaxis2=dict(overlaying="y", side="right", showticklabels=False, showgrid=False),
    )
    chart_cols[idx].plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════
# [3] 핵심 추천 매물 TOP 5 (카드형)
# ══════════════════════════════════════════════
st.markdown('<div class="sec">🏆 핵심 추천 매물 TOP 5</div>', unsafe_allow_html=True)
_latest_label = df["uploadday"].max().strftime("%Y-%m-%d") if not df.empty else "?"
st.caption(f"기준: 최신 업로드일({_latest_label}) 매물만 대상 | 가격(4억±1000만원당±5) · 층수(-30~+40) · 방향(-15~+25) · 평형(-20~+15) · 하락폭(+20) · 신규(+10) · 확인매물(+10) · 메모키워드(-10~+15)")

parts = [
    compute_score(df[df["complex_name"] == cn])
    for cn in sel
    if not df[df["complex_name"] == cn].empty
]

if parts:
    df_sc = pd.concat(parts, ignore_index=True)

    # 가장 최신 업로드일 기준으로만 추천 (stale 매물 제거)
    latest_day = df_sc["uploadday"].max()
    df_latest  = df_sc[df_sc["uploadday"] == latest_day].copy()

    # 같은 날 uid 중복이면 첫 번째만
    if "uid" in df_latest.columns:
        df_latest = df_latest.sort_values("score", ascending=False).drop_duplicates("uid")

    top5 = df_latest.sort_values("score", ascending=False).head(5).reset_index(drop=True)

    rank_emojis = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]

    card_cols = st.columns(5)
    for i, row in top5.iterrows():
        badges = get_badges(row)
        area_str   = f"{row['area']}" if pd.notna(row.get('area')) else ""
        floor_str  = f"{row['floor']}층" if pd.notna(row.get('floor')) else ""
        dong_str   = f"{row['dong']}동" if pd.notna(row.get('dong')) and str(row.get('dong')) not in ("", "nan") else ""
        dir_str    = f"{row['direction']}" if pd.notna(row.get('direction')) and str(row.get('direction')) not in ("", "nan") else ""
        date_str   = f"확인: {row['confirm_date']}" if pd.notna(row.get('confirm_date')) and str(row.get('confirm_date')) not in ("", "nan") else ""
        memo_str   = str(row.get('memo', ''))[:30] if pd.notna(row.get('memo')) and str(row.get('memo')) not in ("", "nan") else ""
        total_score = row['score']
        drop_txt    = f"▼{row['drop_eok']:.2f}억 하락" if row.get('drop_eok', 0) > 0 else ""

        detail_parts = [p for p in [dong_str, area_str, floor_str, dir_str] if p]
        detail_str   = "  ·  ".join(detail_parts)

        # 점수 세부 항목 (±표시)
        def _fmt(v, label):
            if v == 0: return ""
            sign = "+" if v > 0 else ""
            return f'<span style="color:{"#16a34a" if v>0 else "#dc2626"};font-size:9px;">{label}{sign}{v:.0f}</span>'

        breakdown = " ".join(filter(None, [
            _fmt(row.get("score_price", 0), "가격"),
            _fmt(row.get("score_floor", 0), "층"),
            _fmt(row.get("score_dir",   0), "방향"),
            _fmt(row.get("score_area",  0), "평형"),
            _fmt(row.get("score_drop",  0), "하락"),
            _fmt(row.get("score_memo",  0), "메모"),
        ]))

        # 바 너비: 기준 점수 100점을 50%로, 최대 100%
        bar_w = max(0, min(100, int((total_score + 50) / 150 * 100)))

        with card_cols[i]:
            st.markdown(f"""
<div class="rec-card">
  <div style="display:flex;justify-content:space-between;align-items:center;">
    <span class="rec-rank">{rank_emojis[i]}</span>
    <span style="font-size:13px;color:#6366f1;font-weight:800;">{total_score:.0f}점</span>
  </div>
  <div class="rec-name" style="margin-top:4px;">{row.get('complex_name','')}</div>
  <div class="rec-price">{row['eok']:.2f}억</div>
  <div style="margin-top:4px;">{badges}</div>
  <div class="rec-detail" style="margin-top:6px;">{detail_str}</div>
  {'<div class="rec-detail" style="color:#ef4444;">' + drop_txt + '</div>' if drop_txt else ''}
  {'<div class="rec-detail">' + date_str + '</div>' if date_str else ''}
  {'<div class="rec-detail" style="color:#475569;font-style:italic;">' + memo_str + '</div>' if memo_str else ''}
  <div style="margin-top:6px;line-height:1.8;">{breakdown}</div>
  <div class="score-bar-bg">
    <div class="score-bar-fill" style="width:{bar_w}%;"></div>
  </div>
</div>
""", unsafe_allow_html=True)
else:
    st.info("추천 점수를 계산할 데이터가 없습니다.")


# ══════════════════════════════════════════════
# [4] 요약 통계 + 매물량 트렌드 (맨 아래, 컴팩트)
# ══════════════════════════════════════════════
st.divider()

cut   = pd.Timestamp(datetime.now() - timedelta(days=RECENT_DAYS))
d_now = df[df["uploadday"] >= cut]
d_prv = df[df["uploadday"] <  cut]

avg_n = d_now["eok"].mean() if not d_now.empty else None
avg_p = d_prv["eok"].mean() if not d_prv.empty else None
min_n = d_now["eok"].min()  if not d_now.empty else None
min_p = d_prv["eok"].min()  if not d_prv.empty else None

# ── 컴팩트 KPI (인라인 HTML) ──
avg_delta = f"({avg_n-avg_p:+.2f}억)" if (avg_n and avg_p) else ""
avg_color = "#dc2626" if (avg_n and avg_p and avg_n > avg_p) else "#16a34a"
min_delta = f"({min_n-min_p:+.2f}억)" if (min_n and min_p) else ""
min_color = "#dc2626" if (min_n and min_p and min_n > min_p) else "#16a34a"

st.markdown(f"""
<div style="display:flex;gap:16px;flex-wrap:wrap;align-items:center;
            background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;
            padding:8px 14px;font-size:11px;color:#475569;">
  <span>📋 <b style="color:#1e293b;">총 매물</b> {len(df):,}건
    <span style="color:#6366f1;font-size:10px;">(최근7일 {len(d_now)}건)</span></span>
  <span style="color:#cbd5e1;">|</span>
  <span><b style="color:#1e293b;">최근 평균가</b> {f"{avg_n:.1f}억" if avg_n else "—"}
    <span style="color:{avg_color};font-size:10px;">{avg_delta}</span></span>
  <span style="color:#cbd5e1;">|</span>
  <span><b style="color:#1e293b;">최근 최저가</b> {f"{min_n:.1f}억" if min_n else "—"}
    <span style="color:{min_color};font-size:10px;">{min_delta}</span></span>
  <span style="color:#cbd5e1;">|</span>
  <span><b style="color:#1e293b;">분석 단지</b> {df['complex_name'].nunique()}개</span>
</div>
""", unsafe_allow_html=True)

# ── 매물량 트렌드 ──
st.markdown('<div class="sec" style="margin-top:10px;">📈 매물량 트렌드</div>', unsafe_allow_html=True)

# 최근 6주 주별 매물 수 집계
now_ts = pd.Timestamp(datetime.now())
weekly = []
for w in range(5, -1, -1):
    w_end   = now_ts - timedelta(weeks=w)
    w_start = w_end - timedelta(weeks=1)
    cnt     = df[(df["uploadday"] >= w_start) & (df["uploadday"] < w_end)]["uid"].nunique() \
              if "uid" in df.columns else \
              len(df[(df["uploadday"] >= w_start) & (df["uploadday"] < w_end)])
    label   = w_start.strftime("%m/%d") + "~" + w_end.strftime("%m/%d")
    weekly.append({"label": label, "count": cnt, "week_ago": w})

w_df      = pd.DataFrame(weekly)
w_df_data = w_df[w_df["count"] > 0].reset_index(drop=True)

curr  = int(w_df[w_df["week_ago"] == 0]["count"].values[0])
prev1 = int(w_df[w_df["week_ago"] == 1]["count"].values[0])
prev2 = int(w_df[w_df["week_ago"] == 2]["count"].values[0])

# 트렌드 판단: 데이터 있는 주만 기준
active_counts = w_df_data["count"].tolist()
week_chg = curr - prev1
if len(active_counts) >= 2:
    if len(active_counts) == 2:
        if week_chg > 0:
            trend_label, trend_color = "📈 증가 추세", "normal"
        elif week_chg < 0:
            trend_label, trend_color = "📉 감소 추세", "inverse"
        else:
            trend_label, trend_color = "➡️ 보합세", "off"
    else:
        diffs    = [active_counts[i+1] - active_counts[i] for i in range(len(active_counts)-1)]
        up_cnt   = sum(1 for d in diffs if d > 0)
        down_cnt = sum(1 for d in diffs if d < 0)
        if up_cnt > down_cnt:
            trend_label, trend_color = "📈 증가 추세", "normal"
        elif down_cnt > up_cnt:
            trend_label, trend_color = "📉 감소 추세", "inverse"
        else:
            trend_label, trend_color = "➡️ 보합세", "off"
else:
    week_chg   = 0
    trend_label, trend_color = "➡️ 수집 중", "off"

week_chg_str = f"{week_chg:+d}건" if week_chg != 0 else "±0건"
data_note    = f"(데이터 {len(w_df_data)}주치 기준)" if len(w_df_data) < 4 else "(최근 흐름 기준)"

# 레이아웃: 왼쪽 막대차트 / 오른쪽 지표
col_bar, col_stat = st.columns([3, 1])

with col_bar:
    # 데이터 있는 주만 plotly 막대
    plot_df = w_df.copy()
    plot_df["color"] = plot_df.apply(
        lambda r: "이번 주" if r["week_ago"] == 0 else ("이전 주" if r["count"] > 0 else "데이터 없음"),
        axis=1
    )
    fig_t = px.bar(
        plot_df, x="label", y="count",
        color="color",
        color_discrete_map={"이번 주": "#6366f1", "이전 주": "#c7d2fe", "데이터 없음": "#f1f5f9"},
        text="count",
        height=160,
    )
    fig_t.update_traces(texttemplate="%{text}건", textposition="outside", textfont_size=10)
    fig_t.update_layout(
        margin=dict(l=0, r=0, t=10, b=0),
        xaxis_title=None, yaxis_title=None,
        showlegend=False,
        plot_bgcolor="white",
        xaxis=dict(tickfont=dict(size=9)),
        yaxis=dict(showticklabels=False, showgrid=False),
    )
    st.plotly_chart(fig_t, use_container_width=True)

with col_stat:
    st.metric(label=trend_label + " " + data_note,
              value=f"이번주 {curr}건",
              delta=week_chg_str,
              delta_color=trend_color)
    st.caption(f"전주 {prev1}건" + (f" · 전전주 {prev2}건" if prev2 > 0 else ""))
