# pages/notebooklm.py
"""
NotebookLM 전용 내보내기
- 버튼 1회 클릭으로 뉴스 수집 + 매물 정리 → 복붙용 텍스트 생성
"""
import streamlit as st
import pandas as pd
import requests
import xml.etree.ElementTree as ET
import re, html
from datetime import datetime, timedelta
from urllib.parse import quote_plus
from email.utils import parsedate_to_datetime

from utils_style import inject_korean_font
from utils_auth  import require_auth
from utils_graph import build_df

inject_korean_font()
require_auth()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36")

NEWS_QUERIES = [
    "평택 삼성 반도체", "평택 산업단지 개발", "평택 GTX 교통",
    "평택 신도시 택지", "고덕신도시 개발", "브레인시티 평택",
    "평택 동삭동 아파트", "평택 아파트 시세", "평택 청약 분양",
    "평택 전세", "부동산 정책 규제 2026", "주택담보대출 금리",
]

CAT_KEYWORDS = {
    "개발호재": ["삼성","반도체","클러스터","산업단지","gtx","고속도로","신도시","택지","개발","착공","브레인","고덕","지제역"],
    "시세동향": ["매매가","시세","거래량","미분양","실거래","하락","상승","반등","침체"],
    "정책·규제": ["정책","대책","조정지역","규제","발표","시행","국토부","평택시"],
    "금리·대출": ["금리","기준금리","인하","인상","대출","dsr","ltv","주담대","보금자리"],
    "공급·분양": ["분양","청약","입주","재개발","재건축","공급","1순위"],
    "전세·임대": ["전세","월세","임대","갱신","역전세","전세사기"],
}


# ══════════════════════════════════════════════
# 뉴스 수집
# ══════════════════════════════════════════════
def _clean(s) -> str:
    if not s: return ""
    s = str(s).replace("\u200b", "").replace("\ufeff", "")
    return re.sub(r"\s+", " ", s.replace("\r","").replace("\t"," ")).strip()

def _strip_html(t) -> str:
    return _clean(re.sub(r"<[^>]+>", " ", html.unescape(str(t or ""))))

def _to_date(raw) -> str:
    s = _clean(raw)
    if not s: return datetime.now().strftime("%Y-%m-%d")
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    if m: return m.group(1)
    try: return parsedate_to_datetime(s).date().strftime("%Y-%m-%d")
    except: return datetime.now().strftime("%Y-%m-%d")

def _classify(title, desc) -> str:
    s = (title + " " + desc).lower()
    for cat, kws in CAT_KEYWORDS.items():
        if any(k in s for k in kws):
            return cat
    return "기타"

def fetch_news(max_per_query=8) -> list[dict]:
    results = []
    seen = set()
    for q in NEWS_QUERIES:
        try:
            url = f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=ko&gl=KR&ceid=KR:ko"
            r = requests.get(url, headers={"User-Agent": UA}, timeout=15)
            root = ET.fromstring(r.text.replace("\x00",""))
            items = root.findall(".//item")[:max_per_query]
            for it in items:
                title = _clean(it.findtext("title"))
                link  = _clean(it.findtext("link"))
                date  = _to_date(it.findtext("pubDate"))
                desc  = _strip_html(it.findtext("description"))
                key   = title.lower()[:50]
                if not title or key in seen: continue
                seen.add(key)
                results.append({
                    "date": date, "title": title, "link": link,
                    "desc": desc, "cat": _classify(title, desc),
                })
        except Exception:
            continue
    results.sort(key=lambda x: x["date"], reverse=True)
    return results


# ══════════════════════════════════════════════
# 텍스트 생성
# ══════════════════════════════════════════════
def make_text(df: pd.DataFrame, news: list[dict]) -> str:
    now      = datetime.now()
    cut7     = pd.Timestamp(now - timedelta(days=7))
    lines    = []

    # ── 헤더 ─────────────────────────────────
    lines += [
        "=" * 62,
        "  평택 부동산 주간 브리핑  (NotebookLM / AI 분석용)",
        "=" * 62,
        f"생성일시: {now.strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    # ── [1] 뉴스 ─────────────────────────────
    lines += ["─" * 62, "■ 1. 최근 1주간 부동산 뉴스", "─" * 62]
    cutoff_str = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    recent_news = [n for n in news if n["date"] >= cutoff_str]
    if not recent_news:
        recent_news = news[:30]

    by_cat: dict[str, list] = {}
    for n in recent_news:
        by_cat.setdefault(n["cat"], []).append(n)

    for cat in ["개발호재","시세동향","정책·규제","금리·대출","공급·분양","전세·임대","기타"]:
        items = by_cat.get(cat, [])
        if not items: continue
        lines.append(f"\n[{cat}]")
        for n in items[:6]:
            lines.append(f"  • {n['date']}  {n['title']}")
            if n["desc"] and n["desc"] != n["title"]:
                lines.append(f"    └ {n['desc'][:80]}")
    lines.append("")

    # ── [2] 최근 1주 매물 현황 ────────────────
    lines += ["─" * 62, "■ 2. 최근 1주간 매물 현황 (단지별)", "─" * 62]

    df_week = df[df["uploadday"] >= cut7].copy()
    complexes = sorted(df["complex_name"].dropna().unique().tolist())

    for cn in complexes:
        sub_all  = df[df["complex_name"] == cn]
        sub_week = df_week[df_week["complex_name"] == cn]
        if sub_all.empty: continue

        use = sub_week if not sub_week.empty else sub_all.tail(30)
        mn  = use["eok"].min()
        avg = use["eok"].mean()
        mx  = use["eok"].max()
        cnt = len(use)
        prev = sub_all[sub_all["uploadday"] < cut7]
        prev_min = prev["eok"].min() if not prev.empty else None
        chg = f"  (전주比 최저 {'▲' if mn > prev_min else '▼'}{abs(mn - prev_min):.2f}억)" if prev_min else ""

        lines.append(f"\n【{cn}】  {cnt}건")
        lines.append(f"  최저 {mn:.2f}억  /  평균 {avg:.2f}억  /  최고 {mx:.2f}억{chg}")

        # 개별 매물 목록 - 마지막 업로드 일자의 매물 전체
        last_day = use["uploadday"].max()
        top = use[use["uploadday"] == last_day].sort_values("eok")
        for _, row in top.iterrows():
            dong  = str(row.get("dong","")).strip()
            floor = str(row.get("floor","")).strip()
            direc = str(row.get("direction","")).strip()
            area  = str(row.get("area","")).strip()
            memo  = str(row.get("memo",""))[:40].strip() if pd.notna(row.get("memo")) else ""
            conf  = str(row.get("confirm_date","")).strip() if pd.notna(row.get("confirm_date")) else ""
            day   = row["uploadday"].strftime("%m/%d") if pd.notna(row.get("uploadday")) else ""

            parts = [p for p in [
                f"{dong}동" if dong not in ("","nan") else "",
                area if area not in ("","nan") else "",
                f"{floor}층" if floor not in ("","nan") else "",
                direc if direc not in ("","nan") else "",
            ] if p]
            detail = " · ".join(parts)
            conf_txt = f"확인:{conf}" if conf else ""
            memo_txt = f"메모:{memo}" if memo else ""
            extra = "  ".join(p for p in [conf_txt, memo_txt] if p)

            lines.append(f"    {row['eok']:.2f}억  {detail}  [{day}]"
                         + (f"  {extra}" if extra else ""))
    lines.append("")

    # ── [3] 가격 하락 매물 ────────────────────
    lines += ["─" * 62, "■ 3. 가격 하락 매물 (등록 후 인하)", "─" * 62]
    if "uid" in df.columns:
        drops = []
        for uid, g in df.groupby("uid"):
            g = g.sort_values("uploadday")
            if len(g) < 2: continue
            first_p = g["eok"].iloc[0]
            last_p  = g["eok"].iloc[-1]
            if last_p < first_p:
                last_row = g.iloc[-1]
                drops.append({
                    "단지": last_row.get("complex_name",""),
                    "동":   str(last_row.get("dong","")).strip(),
                    "층":   str(last_row.get("floor","")).strip(),
                    "현재가": last_p,
                    "하락폭": round(first_p - last_p, 2),
                    "날짜": last_row["uploadday"].strftime("%m/%d") if pd.notna(last_row.get("uploadday")) else "",
                })
        drops.sort(key=lambda x: x["하락폭"], reverse=True)
        for d in drops[:15]:
            dong = f"{d['동']}동" if d["동"] not in ("","nan") else ""
            floor = f"{d['층']}층" if d["층"] not in ("","nan") else ""
            lines.append(f"  {d['단지']}  {dong} {floor}  {d['현재가']:.2f}억  "
                         f"▼{d['하락폭']:.2f}억 하락  [{d['날짜']}]")
    else:
        lines.append("  (UID 정보 없음)")
    lines.append("")

    # ── [4] AI 분석 제안 질문 ─────────────────
    lines += ["─" * 62, "■ 4. AI 분석 제안 질문", "─" * 62]
    lines += [
        "  Q1. 위 데이터 기준으로 지금 매수 적기인지 판단해줘.",
        "  Q2. 최근 뉴스의 개발호재가 평택 아파트 가격에 미칠 영향은?",
        "  Q3. 가격 하락 매물 중 실거주 가치가 높은 매물의 특징은?",
        "  Q4. 단지별 매물량 변화로 볼 때 시장 분위기는?",
        "  Q5. 3.5~4억 예산으로 가장 유리한 단지와 조건은?",
        "",
    ]

    lines.append("=" * 62)
    return "\n".join(lines)


# ══════════════════════════════════════════════
# UI
# ══════════════════════════════════════════════
st.markdown("#### 📒 NotebookLM 브리핑 생성")
st.caption("버튼 1회 클릭으로 최근 1주 매물 + 뉴스를 수집해 복붙용 텍스트를 만듭니다.")

df_all = build_df()
if df_all.empty:
    st.error("매물 데이터가 없습니다.")
    st.stop()

complexes = sorted(df_all["complex_name"].dropna().unique().tolist())
sel = st.multiselect(
    "분석 단지 선택",
    complexes,
    default=complexes[:4] if len(complexes) >= 4 else complexes,
)

if not sel:
    st.warning("단지를 1개 이상 선택하세요.")
    st.stop()

df = df_all[df_all["complex_name"].isin(sel)].copy()
cut7 = pd.Timestamp(datetime.now() - timedelta(days=7))

# 요약 지표
m1, m2, m3 = st.columns(3)
m1.metric("분석 단지", f"{len(sel)}개")
m2.metric("전체 매물", f"{len(df):,}건")
m3.metric("최근 7일 매물", f"{len(df[df['uploadday'] >= cut7]):,}건")

st.divider()

if st.button("🚀 뉴스 수집 + 브리핑 생성", type="primary", use_container_width=True):
    with st.spinner("뉴스 수집 중... (10~20초 소요)"):
        news = fetch_news()
    st.session_state["nlm_news"]  = news
    st.session_state["nlm_text"]  = make_text(df, news)
    st.session_state["nlm_time"]  = datetime.now().strftime("%Y-%m-%d %H:%M")
    st.toast(f"✅ 뉴스 {len(news)}건 수집 완료!")

if "nlm_text" in st.session_state:
    st.caption(f"생성: {st.session_state.get('nlm_time','')}  |  "
               f"뉴스 {len(st.session_state.get('nlm_news',[]))}건")

    st.markdown("**📋 복사용 텍스트** — 전체선택(Ctrl+A) → 복사(Ctrl+C) 후 NotebookLM에 붙여넣기")
    st.text_area(
        label="nlm_out",
        label_visibility="collapsed",
        value=st.session_state["nlm_text"],
        height=700,
    )
    st.download_button(
        "⬇️ .txt 파일로 다운로드",
        data=st.session_state["nlm_text"].encode("utf-8"),
        file_name=f"평택부동산브리핑_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
        mime="text/plain",
        use_container_width=True,
    )
