# pages/notebooklm.py
"""
NotebookLM / AI 분석용 텍스트 내보내기
- 뉴스 요약 (policy_news_merged.json)
- 추천 매물 TOP 5 (graph_v2 동일 점수 기준)
- 매물 동향 (주간 매물량 추이)
- 금액대 분석 (단지별 최저·평균·최고)
- 전체를 하나의 텍스트로 묶어 복사
"""
import streamlit as st
import pandas as pd
import json, re
from pathlib import Path
from datetime import datetime, timedelta

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db

from utils_style import inject_korean_font
from utils_auth import require_auth
inject_korean_font()
require_auth()

# ══════════════════════════════════════════════
# 상수
# ══════════════════════════════════════════════
NEWS_JSON   = Path(__file__).resolve().parent.parent / "out" / "policy_news_merged.json"
RECENT_DAYS = 7

CAT_LABEL = {
    "DEV":    "개발호재",
    "MARKET": "시세동향",
    "POLICY": "정책·규제",
    "LOAN":   "금리·대출",
    "SUPPLY": "공급·분양",
    "JEONSE": "전세·임대",
    "ETC":    "기타",
}

RENT_WORDS = ["전세", "월세", "보증금"]
SKIP_KW    = ["단지", "동", "호"]
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
def parse_eok(t):
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
    s = str(x).replace("\u200b","").strip()
    return "" if s in ("","1","None","nan","NaN","UNKNOWN") or len(s)<=1 else s

def floor_score(floor_val):
    if not floor_val or pd.isna(floor_val): return 0.0
    s = str(floor_val).strip()
    if s.startswith(("저","지")): return 0.0
    m = _RE_FLOOR.match(s)
    if not m: return 0.0
    n = int(m.group(1))
    if n <= 10: return 0.0
    if n <= 20: return 10.0
    return 20.0

def days_since(confirm_text):
    if not confirm_text: return None
    try:
        y, mo, d = str(confirm_text).strip().split(".")
        return (datetime.now() - datetime(2000+int(y), int(mo), int(d))).days
    except: return None


# ══════════════════════════════════════════════
# 데이터 로드
# ══════════════════════════════════════════════
@st.cache_data(show_spinner=False, ttl=60)
def load_df():
    try: db.init_db()
    except: pass
    hist = pd.DataFrame(db.read_history())
    lst  = pd.DataFrame(db.read_listings())
    if hist.empty or lst.empty: return pd.DataFrame()

    hist["seen_at"]   = pd.to_datetime(hist["seen_at"], errors="coerce")
    hist              = hist.dropna(subset=["seen_at"]).copy()
    hist["uploadday"] = hist["seen_at"].dt.normalize()

    want = ["uid","complex_name","trade_type","floor","direction","area","confirm_date","memo","dong"]
    cols = [c for c in want if c in lst.columns]
    df   = hist.merge(lst[cols], on="uid", how="left")
    df   = df[df["trade_type"] == "매매"].copy()
    df["complex_name"] = df["complex_name"].apply(clean_name)
    df   = df[df["complex_name"] != ""].copy()
    df["eok"]         = df["price_text"].apply(parse_eok)
    df["confirm_age"] = df["confirm_date"].apply(days_since) if "confirm_date" in df.columns else None
    df   = df.dropna(subset=["eok","uploadday"]).copy()
    return df

@st.cache_data(show_spinner=False)
def load_news():
    if not NEWS_JSON.exists(): return []
    try:
        data = json.loads(NEWS_JSON.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except: return []


# ══════════════════════════════════════════════
# 추천 점수 계산 (graph_v2 동일 기준)
# ══════════════════════════════════════════════
def compute_scores(df: pd.DataFrame) -> pd.DataFrame:
    dc = df.copy()
    mn  = dc["eok"].min(); rng = dc["eok"].max() - mn
    dc["score_price"] = (1 - (dc["eok"] - mn) / rng) * 40 if rng > 0 else 40.0

    # 가격 하락폭 (30점)
    if "uid" in dc.columns:
        try:
            first = dc.groupby("uid")["eok"].first()
            last  = dc.groupby("uid")["eok"].last()
            dc = dc.merge((first - last).clip(lower=0).rename("drop_eok").reset_index(),
                          on="uid", how="left")
        except: dc["drop_eok"] = 0.0
    else:
        dc["drop_eok"] = 0.0
    mx = dc["drop_eok"].max()
    dc["score_drop"] = (dc["drop_eok"] / mx * 30) if mx > 0 else 0.0

    # 신규등록 (20점)
    cut = pd.Timestamp(datetime.now() - timedelta(days=RECENT_DAYS))
    dc["score_new"] = dc["uploadday"].apply(lambda d: 20.0 if pd.notna(d) and d >= cut else 0.0)

    # 확인매물 (10점)
    dc["score_confirm"] = dc["confirm_age"].apply(
        lambda a: 10.0 if pd.notna(a) and a <= 14 else 0.0
    ) if "confirm_age" in dc.columns else 0.0

    # 층수 (20점)
    dc["score_floor"] = dc["floor"].apply(floor_score) if "floor" in dc.columns else 0.0

    dc["score"] = (dc["score_price"] + dc["score_drop"] + dc["score_new"]
                   + dc["score_confirm"] + dc["score_floor"])
    return dc


# ══════════════════════════════════════════════
# 텍스트 생성 함수들
# ══════════════════════════════════════════════
def make_news_section(news: list, days: int) -> str:
    if not news:
        return "※ 수집된 뉴스 없음 (policy_news 탭에서 먼저 수집해 주세요)\n"

    cutoff = datetime.now() - timedelta(days=days)
    recent = [n for n in news
              if n.get("date","") >= cutoff.strftime("%Y-%m-%d")]
    if not recent:
        recent = news[:20]

    by_cat: dict[str, list] = {}
    for n in recent:
        by_cat.setdefault(n.get("category","ETC"), []).append(n)

    lines = []
    for cat in ["DEV","MARKET","POLICY","LOAN","SUPPLY","JEONSE","ETC"]:
        items = by_cat.get(cat, [])
        if not items: continue
        lines.append(f"[{CAT_LABEL.get(cat, cat)}]")
        for n in items[:5]:
            title  = n.get("title","")
            date   = n.get("date","")
            region = " / ".join(n.get("regions",[]))
            dir_   = n.get("direction","")
            bullet = n.get("bullets",[""])[0] if n.get("bullets") else ""
            lines.append(f"  • {date} [{dir_}] {title}")
            if region: lines.append(f"    지역: {region}")
            if bullet and bullet != title: lines.append(f"    내용: {bullet}")
        lines.append("")
    return "\n".join(lines)


def make_top5_section(df: pd.DataFrame, sel: list) -> str:
    parts = []
    for cn in sel:
        sub = df[df["complex_name"] == cn]
        if sub.empty: continue
        parts.append(compute_scores(sub))
    if not parts:
        return "※ 추천 점수 계산 가능한 데이터 없음\n"

    df_sc = pd.concat(parts, ignore_index=True)
    if "uid" in df_sc.columns:
        df_sc = df_sc.sort_values("uploadday").groupby("uid", as_index=False).last()
    top5 = df_sc.sort_values("score", ascending=False).head(5).reset_index(drop=True)

    lines = []
    ranks = ["1위","2위","3위","4위","5위"]
    for i, row in top5.iterrows():
        name    = row.get("complex_name","")
        eok     = row.get("eok", 0)
        score   = row.get("score", 0)
        max_s   = 120
        score_pct = min(int(score * 100 / max_s), 100)
        drop    = row.get("drop_eok", 0)
        floor_  = str(row.get("floor","")) + "층" if row.get("floor") else ""
        area    = str(row.get("area",""))
        dong    = str(row.get("dong","")) + "동" if row.get("dong") and str(row.get("dong")) not in ("","nan") else ""
        dir_    = str(row.get("direction",""))
        confirm = f"확인: {row.get('confirm_date','')}" if row.get("confirm_date") else ""
        memo    = str(row.get("memo",""))[:40] if row.get("memo") and str(row.get("memo")) not in ("","nan") else ""
        drop_txt = f"▼{drop:.2f}억 하락" if drop > 0 else ""

        detail = " · ".join(p for p in [dong, area, floor_, dir_] if p)
        lines.append(f"  {ranks[i]}  {name}  {eok:.2f}억  (추천점수 {score_pct}점/100점)")
        if detail: lines.append(f"       {detail}")
        if drop_txt: lines.append(f"       {drop_txt}")
        if confirm:  lines.append(f"       {confirm}")
        if memo:     lines.append(f"       메모: {memo}")
    return "\n".join(lines)


def make_trend_section(df: pd.DataFrame) -> str:
    now_ts = pd.Timestamp(datetime.now())
    rows = []
    for w in range(5, -1, -1):
        w_end   = now_ts - timedelta(weeks=w)
        w_start = w_end - timedelta(weeks=1)
        cnt = df[(df["uploadday"] >= w_start) & (df["uploadday"] < w_end)]["uid"].nunique() \
              if "uid" in df.columns else \
              len(df[(df["uploadday"] >= w_start) & (df["uploadday"] < w_end)])
        label = w_start.strftime("%m/%d") + "~" + w_end.strftime("%m/%d")
        rows.append((label, cnt, w))

    active = [(l, c) for l, c, w in rows if c > 0]
    lines = []
    for label, cnt, _ in rows:
        bar = "█" * min(int(cnt / max(c for _, c in active) * 20), 20) if active and cnt > 0 else ""
        lines.append(f"  {label}  {cnt:>4}건  {bar}")

    # 트렌드 판단
    counts = [c for _, c in active]
    if len(counts) >= 2:
        chg = counts[-1] - counts[-2]
        if chg > 0:   trend = f"▲ 증가 추세 (전주 대비 +{chg}건)"
        elif chg < 0: trend = f"▼ 감소 추세 (전주 대비 {chg}건)"
        else:         trend = "→ 보합"
        lines.append(f"\n  [트렌드] {trend}")
    return "\n".join(lines)


def make_price_section(df: pd.DataFrame, sel: list) -> str:
    cut = pd.Timestamp(datetime.now() - timedelta(days=RECENT_DAYS))
    recent = df[df["uploadday"] >= cut]
    lines = []
    for cn in sel:
        sub = recent[recent["complex_name"] == cn]
        if sub.empty:
            sub = df[df["complex_name"] == cn].tail(30)
        if sub.empty:
            lines.append(f"  {cn}: 데이터 없음")
            continue
        mn  = sub["eok"].min()
        avg = sub["eok"].mean()
        mx  = sub["eok"].max()
        cnt = len(sub)
        lines.append(f"  {cn}")
        lines.append(f"    최저 {mn:.2f}억  /  평균 {avg:.2f}억  /  최고 {mx:.2f}억  ({cnt}건)")

        # 가격대별 분포
        bins = [(0, 3.5, "~3.5억"), (3.5, 4.0, "3.5~4억"), (4.0, 4.5, "4~4.5억"),
                (4.5, 5.0, "4.5~5억"), (5.0, 99, "5억~")]
        dist = []
        for lo, hi, label in bins:
            n = len(sub[(sub["eok"] >= lo) & (sub["eok"] < hi)])
            if n > 0: dist.append(f"{label} {n}건")
        if dist: lines.append(f"    분포: {' | '.join(dist)}")
    return "\n".join(lines)


def make_full_text(df: pd.DataFrame, news: list, sel: list, news_days: int) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    date_range = ""
    if not df.empty and "uploadday" in df.columns:
        mn = df["uploadday"].min(); mx = df["uploadday"].max()
        date_range = f"{mn.strftime('%Y-%m-%d')} ~ {mx.strftime('%Y-%m-%d')}"

    lines = []

    lines += [
        "=" * 60,
        "  평택·안성 부동산 분석 요약 (NotebookLM / AI 분석용)",
        "=" * 60,
        f"생성일시: {now}",
        f"분석 단지: {', '.join(sel)}",
        f"매물 데이터 기간: {date_range}",
        f"총 매물 레코드: {len(df):,}건  |  뉴스: {len(news)}건",
        "",
    ]

    lines += ["─" * 60, "■ 뉴스 요약", "─" * 60]
    lines.append(make_news_section(news, news_days))

    lines += ["─" * 60, "■ 핵심 추천 매물 TOP 5", "─" * 60]
    lines.append("기준: 저가격(40점) + 가격하락폭(30점) + 신규등록(20점) + 확인매물(10점) + 층수(20점, 저층0·중층10·고층20)")
    lines.append(make_top5_section(df, sel))
    lines.append("")

    lines += ["─" * 60, "■ 매물량 주간 동향", "─" * 60]
    lines.append(make_trend_section(df))
    lines.append("")

    lines += ["─" * 60, "■ 금액대 분석 (최근 7일 기준)", "─" * 60]
    lines.append(make_price_section(df, sel))
    lines.append("")

    lines += ["─" * 60, "■ 단지별 현황 요약", "─" * 60]
    for cn in sel:
        sub = df[df["complex_name"] == cn]
        if sub.empty: continue
        total = len(sub)
        recent_cnt = len(sub[sub["uploadday"] >= pd.Timestamp(datetime.now() - timedelta(days=RECENT_DAYS))])
        mn = sub["eok"].min(); avg = sub["eok"].mean()
        drop_cnt = 0
        if "uid" in sub.columns:
            for uid, g in sub.groupby("uid"):
                if len(g) >= 2:
                    first_p = g.sort_values("uploadday")["eok"].iloc[0]
                    last_p  = g.sort_values("uploadday")["eok"].iloc[-1]
                    if last_p < first_p: drop_cnt += 1
        lines.append(f"  {cn}")
        lines.append(f"    전체 {total}건  |  최근 7일 {recent_cnt}건  |  가격하락 매물 {drop_cnt}건")
        lines.append(f"    최저가 {mn:.2f}억  /  평균가 {avg:.2f}억")
    lines.append("")

    lines += ["─" * 60, "■ AI 분석 제안 질문", "─" * 60]
    lines += [
        "  1. 위 데이터를 바탕으로 2026년 7월 매수 시 가장 유리한 단지와 매물은?",
        "  2. 최근 뉴스의 개발호재가 평택 아파트 가격에 미칠 영향은?",
        "  3. 가격 하락 매물 중 실거주 가치가 높은 매물의 특징은?",
        "  4. 현재 금액대(1.3억 투자)로 접근 가능한 매물 조건은?",
        "  5. 매물량 추이로 볼 때 시장 분위기는 매수자 우위인가 매도자 우위인가?",
        "",
    ]

    lines.append("=" * 60)
    return "\n".join(lines)


# ══════════════════════════════════════════════
# UI
# ══════════════════════════════════════════════
st.title("📒 NotebookLM 내보내기")
st.caption("뉴스 요약 · 추천 매물 · 매물 동향 · 금액대 분석을 하나의 텍스트로 묶어 복사합니다.")

df_all = load_df()
news   = load_news()

if df_all.empty:
    st.error("매물 데이터가 없습니다. rawdata 탭에서 먼저 데이터를 입력해 주세요.")
    st.stop()

# ── 옵션 ──────────────────────────────────────
c1, c2, c3 = st.columns([3, 1, 1])

complexes = sorted(df_all["complex_name"].dropna().unique().tolist())
sel = c1.multiselect("분석 단지 선택", complexes,
                     default=complexes[:4] if len(complexes) >= 4 else complexes)
news_days = c2.selectbox("뉴스 기간", [7, 14, 30, 60], index=1, format_func=lambda x: f"최근 {x}일")
if c3.button("🔄 캐시 초기화"):
    st.cache_data.clear(); st.rerun()

if not sel:
    st.warning("단지를 1개 이상 선택하세요.")
    st.stop()

df = df_all[df_all["complex_name"].isin(sel)].copy()

# ── 요약 카드 ─────────────────────────────────
m1, m2, m3, m4 = st.columns(4)
cut7 = pd.Timestamp(datetime.now() - timedelta(days=7))
m1.metric("총 매물 레코드", f"{len(df):,}건")
m2.metric("최근 7일 매물", f"{len(df[df['uploadday'] >= cut7]):,}건")
m3.metric("수집 뉴스", f"{len(news)}건")
m4.metric("분석 단지", f"{len(sel)}개")

# ── 텍스트 생성 + 표시 ────────────────────────
st.divider()
with st.spinner("텍스트 생성 중..."):
    full_text = make_full_text(df, news, sel, news_days)

st.markdown("#### 📋 복사용 텍스트")
st.caption("전체 선택(Ctrl+A) → 복사(Ctrl+C) 후 NotebookLM에 붙여넣기")

st.text_area(
    label="notebooklm_text",
    label_visibility="collapsed",
    value=full_text,
    height=600,
)

st.download_button(
    "⬇️ .txt 파일로 다운로드",
    data=full_text.encode("utf-8"),
    file_name=f"ptk_summary_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
    mime="text/plain",
    use_container_width=True,
)
