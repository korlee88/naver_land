# pages/policy_news.py
"""
평택 부동산 뉴스 자동 수집기
- Google News RSS 기반 무료 수집
- 개발호재 / 시세동향 / 정책·규제 / 금리·대출 / 공급·분양 / 전세·임대 카테고리 자동 분류
- 지역 태그 자동 분류 (동삭동 / 평택 / 경기도)
- JSON 누적 저장 + Markdown 출력
"""
import streamlit as st
import pandas as pd
import json, re, html
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus, urlparse
from email.utils import parsedate_to_datetime

from utils_style import inject_korean_font
from utils_auth import require_auth
inject_korean_font()
require_auth()

# ══════════════════════════════════════════════
# 상수 & 설정
# ══════════════════════════════════════════════
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36")

OUT_DIR   = Path("out")
JSON_FILE = OUT_DIR / "policy_news_merged.json"
MD_FILE   = OUT_DIR / "policy_news_for_notebooklm.md"

# ── 카테고리 정의 ──────────────────────────────
CAT_LABEL = {
    "DEV":    "🏗️ 개발호재",
    "MARKET": "📊 시세동향",
    "POLICY": "📋 정책·규제",
    "LOAN":   "💳 금리·대출",
    "SUPPLY": "🏠 공급·분양",
    "JEONSE": "🔑 전세·임대",
    "ETC":    "📌 기타",
}

CAT_KEYWORDS = {
    "DEV": [
        "삼성", "반도체", "클러스터", "산업단지", "공단",
        "gtx", "고속도로", "ic", "인터체인지", "도로", "철도",
        "신도시", "택지", "개발", "호재", "계획", "착공", "준공",
        "평택항", "브레인시티", "고덕", "지제역",
    ],
    "MARKET": [
        "매매가", "시세", "거래량", "미분양", "부동산원", "kb",
        "실거래", "지수", "통계", "하락", "상승", "반등", "침체",
    ],
    "POLICY": [
        "정책", "대책", "조정지역", "규제", "발표", "시행", "개정",
        "국토부", "국토교통부", "정부", "지자체", "평택시",
    ],
    "LOAN": [
        "금리", "기준금리", "한은", "인하", "인상", "대출",
        "dsr", "ltv", "주담대", "보금자리", "특례", "전세대출", "가계부채",
    ],
    "SUPPLY": [
        "분양", "청약", "입주", "착공", "준공", "재개발",
        "재건축", "정비", "공급", "물량", "1순위", "특공",
    ],
    "JEONSE": [
        "전세", "월세", "임대", "갱신", "보증금", "역전세",
        "전세사기", "깡통전세",
    ],
}

# ── RSS 검색 쿼리 (평택·안성 특화) ──────────────
DEFAULT_QUERIES = [
    # 개발호재
    "평택 삼성 반도체",
    "평택 산업단지 개발",
    "평택 고속도로 IC",
    "평택 GTX 교통",
    "평택 신도시 택지",
    "고덕신도시 개발",
    "브레인시티 평택",
    # 시세·분양
    "평택 동삭동 아파트",
    "평택 아파트 시세",
    "평택 청약 분양",
    "평택 전세",
    # 정책·금리
    "부동산 정책 규제 2026",
    "주택 대출 DSR LTV",
    "주택담보대출 금리",
    "국토부 주택 공급",
]

DEFAULT_POLICY_RSS = [
    "https://www.korea.kr/rss/dept_molit.xml",  # 국토교통부 보도자료
]

# ── 지역 키워드 매핑 ──────────────────────────
REGION_KEYWORDS = {
    "평택 동삭동": ["동삭동", "동삭"],
    "평택 고덕":   ["고덕", "고덕신도시", "고덕국제신도시"],
    "평택 지제":   ["지제역", "지제"],
    "평택 브레인": ["브레인시티"],
    "평택":        ["평택"],
    "경기도":      ["경기도", "경기"],
}


# ══════════════════════════════════════════════
# 유틸
# ══════════════════════════════════════════════
def clean(s) -> str:
    if s is None: return ""
    s = str(s).replace("\u200b","").replace("\ufeff","")
    s = re.sub(r"\s+", " ", s.replace("\r","").replace("\t"," "))
    return s.strip()

def strip_html_tags(text: str) -> str:
    t = html.unescape(text or "")
    return clean(re.sub(r"<[^>]+>", " ", t))

def host_of(url: str) -> str:
    try: return urlparse(url).netloc.replace("www.","")
    except: return ""

def to_date_str(raw: str) -> str:
    s = clean(raw)
    if not s:
        return datetime.now().strftime("%Y-%m-%d")
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    if m: return m.group(1)
    try:
        return parsedate_to_datetime(s).date().strftime("%Y-%m-%d")
    except:
        return datetime.now().strftime("%Y-%m-%d")

def safe_dt(d: str):
    try: return datetime.strptime(d, "%Y-%m-%d")
    except: return None

def item_key(it: dict) -> str:
    return f"{clean(it.get('date'))}|{clean(it.get('title','')).lower()}"


# ══════════════════════════════════════════════
# RSS 수집
# ══════════════════════════════════════════════
def fetch_text(url: str, timeout=20) -> str:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text

def google_rss_url(query: str) -> str:
    return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=ko&gl=KR&ceid=KR:ko"

def parse_rss(xml_text: str) -> list[dict]:
    items = []
    root = ET.fromstring(xml_text.replace("\x00",""))

    for it in root.findall(".//item"):
        title   = clean(it.findtext("title"))
        link    = clean(it.findtext("link"))
        pubdate = clean(it.findtext("pubDate") or
                        it.findtext("{http://purl.org/dc/elements/1.1/}date"))
        desc    = clean(it.findtext("description"))
        items.append({"title":title,"link":link,"pubdate_raw":pubdate,"desc":desc})

    NS = "http://www.w3.org/2005/Atom"
    for en in root.findall(f".//{{{NS}}}entry"):
        title = clean(en.findtext(f"{{{NS}}}title"))
        link  = ""
        for lk in en.findall(f"{{{NS}}}link"):
            href = lk.attrib.get("href","")
            if href and lk.attrib.get("rel","") in ("alternate","","alternate"):
                link = href; break
        updated = clean(en.findtext(f"{{{NS}}}updated") or en.findtext(f"{{{NS}}}published"))
        summary = clean(en.findtext(f"{{{NS}}}summary"))
        items.append({"title":title,"link":link,"pubdate_raw":updated,"desc":summary})

    seen = {}
    for x in items:
        k = (x.get("link","")) + "|" + (x.get("title",""))
        seen[k] = x
    return list(seen.values())


# ══════════════════════════════════════════════
# 분류·태깅
# ══════════════════════════════════════════════
def classify_category(title: str, desc: str) -> str:
    s = (title + " " + desc).lower()
    for cat, kws in CAT_KEYWORDS.items():
        if any(k in s for k in kws):
            return cat
    return "ETC"

def detect_regions(text: str) -> list[str]:
    found = []
    for region, keywords in REGION_KEYWORDS.items():
        if any(k in text for k in keywords):
            found.append(region)
    # 하위 지역이 있으면 상위 '평택' 중복 추가 방지
    if any(r.startswith("평택 ") for r in found) and "평택" not in found:
        found.append("평택")
    return found if found else ["평택"]

def detect_direction(title: str, desc: str) -> str:
    s = (title + " " + desc).lower()
    up   = any(k in s for k in ["상승","강세","회복","반등","호재","완화","인하","확대","개선"])
    down = any(k in s for k in ["하락","약세","침체","악재","규제","강화","인상","축소","감소"])
    if up and down: return "혼조"
    if up:   return "긍정"
    if down: return "부정"
    return "중립"

def normalize_entry(entry: dict) -> dict:
    title   = clean(entry.get("title",""))
    url     = clean(entry.get("link",""))
    date    = to_date_str(entry.get("pubdate_raw",""))
    desc    = strip_html_tags(entry.get("desc",""))
    cat     = classify_category(title, desc)
    regions = detect_regions(title + " " + desc)
    direction = detect_direction(title, desc)

    # 요약 문장 추출 (description에서 최대 3문장)
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+|(?<=다\.)\s*", desc) if s.strip()]
    bullets = sents[:3] if sents else ([title] if title else [])

    return {
        "date":      date,
        "title":     title,
        "category":  cat,
        "direction": direction,
        "regions":   regions,
        "bullets":   bullets,
        "publisher": host_of(url) or "RSS",
        "url":       url,
    }


# ══════════════════════════════════════════════
# 저장 / 불러오기 / 중복제거
# ══════════════════════════════════════════════
def load_saved() -> list[dict]:
    if JSON_FILE.exists():
        try:
            data = json.loads(JSON_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except: return []
    return []

def save_and_merge(new_items: list[dict], append: bool) -> list[dict]:
    existing = load_saved() if append else []
    all_items = existing + new_items
    seen = {}
    for it in all_items:
        seen[item_key(it)] = it
    merged = sorted(seen.values(),
                    key=lambda x: safe_dt(x.get("date","")) or datetime(1900,1,1),
                    reverse=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged

def to_markdown(items: list[dict]) -> str:
    lines = [
        "# 평택 부동산 뉴스 브리핑",
        f"\n생성일: {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  총 {len(items)}건\n",
    ]
    by_cat: dict[str, list] = {}
    for it in items:
        by_cat.setdefault(it.get("category","ETC"), []).append(it)

    for cat in ["DEV","MARKET","POLICY","LOAN","SUPPLY","JEONSE","ETC"]:
        if cat not in by_cat: continue
        label = CAT_LABEL.get(cat, cat)
        lines.append(f"\n## {label}\n")
        for it in by_cat[cat]:
            lines.append(f"### {it.get('date','')} · {it.get('title','')}")
            lines.append(f"- 방향: **{it.get('direction','—')}** | 지역: {', '.join(it.get('regions',[]))}")
            lines.append(f"- 출처: [{it.get('publisher','')}]({it.get('url','')})")
            for b in it.get("bullets",[])[:3]:
                lines.append(f"  - {b}")
            lines.append("")
    return "\n".join(lines)


# ══════════════════════════════════════════════
# Streamlit UI
# ══════════════════════════════════════════════
st.markdown("#### 🏙️ 평택 부동산 뉴스 수집기")
st.caption("Google News RSS 기반 무료 자동 수집 | 개발호재 / 시세 / 정책·규제 / 금리·대출 자동 분류")

# ── 설정 바 ────────────────────────────────────
with st.expander("⚙️ 수집 설정", expanded=False):
    sc1, sc2, sc3, sc4 = st.columns(4)
    days          = sc1.selectbox("수집 기간", [1,3,7,14,30], index=2, key="days")
    max_per_query = sc2.slider("쿼리당 기사 수", 5, 40, 15, key="mpq")
    append_mode   = sc3.toggle("기존 데이터 누적", value=True, key="append")
    timeout_sec   = sc4.slider("요청 timeout(초)", 5, 40, 20, key="timeout")

tab_auto, tab_saved = st.tabs(["🔎 자동 수집", "📂 저장된 뉴스 보기"])

# ══════════════════════════════════════════════
# Tab 1: 자동 수집
# ══════════════════════════════════════════════
with tab_auto:
    col_q, col_run = st.columns([3, 1], gap="large")

    with col_q:
        st.markdown("##### 검색 쿼리 (한 줄에 하나)")
        queries_text = st.text_area(
            "queries", label_visibility="collapsed",
            value="\n".join(DEFAULT_QUERIES), height=260,
        )
        st.markdown("##### 정책 RSS URL (선택)")
        policy_rss_text = st.text_area(
            "policy_rss", label_visibility="collapsed",
            value="\n".join(DEFAULT_POLICY_RSS), height=60,
        )

    with col_run:
        st.markdown("##### 카테고리 필터")
        sel_cats = {}
        for cat, label in CAT_LABEL.items():
            sel_cats[cat] = st.checkbox(label, value=True, key=f"cat_{cat}")

        st.markdown("---")
        run_btn = st.button("🚀 수집 시작", use_container_width=True, type="primary")

    if run_btn:
        queries    = [clean(x) for x in queries_text.splitlines() if clean(x)]
        policy_rss = [clean(x) for x in policy_rss_text.splitlines() if clean(x)]

        if not queries and not policy_rss:
            st.warning("쿼리 또는 RSS URL을 1개 이상 입력해주세요.")
            st.stop()

        cutoff   = datetime.now() - timedelta(days=int(days))
        raw_entries: list[dict] = []
        errors: list[str] = []

        progress = st.progress(0, text="수집 중...")
        total_sources = len(queries) + len(policy_rss)

        for i, q in enumerate(queries):
            try:
                url = google_rss_url(q)
                xml = fetch_text(url, timeout=int(timeout_sec))
                entries = parse_rss(xml)
                entries.sort(
                    key=lambda e: safe_dt(to_date_str(e.get("pubdate_raw",""))) or datetime(1900,1,1),
                    reverse=True
                )
                raw_entries.extend(entries[:int(max_per_query)])
            except Exception as e:
                errors.append(f"쿼리 '{q}': {e}")
            progress.progress((i+1)/total_sources, text=f"수집 중... [{q}]")

        for j, rss_url in enumerate(policy_rss):
            try:
                xml = fetch_text(rss_url, timeout=int(timeout_sec))
                raw_entries.extend(parse_rss(xml))
            except Exception as e:
                errors.append(f"RSS '{rss_url}': {e}")
            progress.progress((len(queries)+j+1)/total_sources, text=f"정책 RSS 수집 중...")

        progress.empty()

        # 정규화 + 날짜 필터
        normalized = []
        for e in raw_entries:
            it = normalize_entry(e)
            dt = safe_dt(it["date"]) or datetime.now()
            if dt >= cutoff and it.get("title"):
                normalized.append(it)

        # 중복 제거 (같은 title+date)
        seen_tmp: dict[str, dict] = {}
        for it in normalized:
            seen_tmp[item_key(it)] = it
        normalized = list(seen_tmp.values())

        if not normalized:
            st.info("수집된 기사가 없습니다. 기간을 늘리거나 쿼리를 바꿔보세요.")
        else:
            merged = save_and_merge(normalized, append=bool(append_mode))
            md_text = to_markdown(merged)
            MD_FILE.write_text(md_text, encoding="utf-8")

            st.session_state["merged"] = merged
            st.session_state["md_text"] = md_text
            st.session_state["sel_cats"] = sel_cats

            st.success(f"수집 완료: {len(normalized)}건 신규 | 누적 총 {len(merged)}건")

        if errors:
            with st.expander(f"⚠️ 오류 {len(errors)}건"):
                for err in errors:
                    st.caption(err)

    # ── 결과 테이블 ──────────────────────────────
    if "merged" in st.session_state:
        merged   = st.session_state["merged"]
        sel_cats = st.session_state.get("sel_cats", {cat: True for cat in CAT_LABEL})
        md_text  = st.session_state.get("md_text","")

        # 카테고리별 탭
        st.divider()
        st.markdown(f"#### 📋 전체 결과 ({len(merged)}건)")

        # 필터 적용
        allowed = [cat for cat, on in sel_cats.items() if on]
        disp = [it for it in merged if it.get("category","ETC") in allowed]

        # 테이블로 표시
        if disp:
            rows = []
            for it in disp:
                rows.append({
                    "날짜":     it.get("date",""),
                    "카테고리": CAT_LABEL.get(it.get("category","ETC"), "기타"),
                    "방향":     it.get("direction","—"),
                    "지역":     " / ".join(it.get("regions",[])),
                    "제목":     it.get("title",""),
                    "출처":     it.get("publisher",""),
                    "링크":     it.get("url",""),
                })
            df = pd.DataFrame(rows)

            # 제목 클릭 → 링크 열리도록 column_config 사용
            st.dataframe(
                df,
                column_config={
                    "링크": st.column_config.LinkColumn("링크", display_text="🔗"),
                    "날짜": st.column_config.TextColumn("날짜", width="small"),
                    "카테고리": st.column_config.TextColumn("카테고리", width="medium"),
                    "방향": st.column_config.TextColumn("방향", width="small"),
                    "지역": st.column_config.TextColumn("지역", width="medium"),
                },
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("선택한 카테고리에 해당하는 기사가 없습니다.")

        # ── 카테고리별 요약 ──────────────────────
        st.divider()
        st.markdown("#### 📊 카테고리별 현황")
        cat_counts = {}
        for it in merged:
            c = CAT_LABEL.get(it.get("category","ETC"), "기타")
            cat_counts[c] = cat_counts.get(c, 0) + 1

        cols = st.columns(len(cat_counts)) if cat_counts else []
        for i, (cat, cnt) in enumerate(sorted(cat_counts.items(), key=lambda x: -x[1])):
            if i < len(cols):
                cols[i].metric(cat, f"{cnt}건")

        # ── NotebookLM용 Markdown ─────────────────
        st.divider()
        st.markdown("#### 🧠 NotebookLM / AI 분석용 Markdown")
        st.caption(f"저장 경로: `{MD_FILE}` | Ctrl+A → Ctrl+C 후 NotebookLM에 붙여넣기")
        st.text_area("markdown_out", value=md_text, height=300, label_visibility="collapsed")


# ══════════════════════════════════════════════
# Tab 2: 저장된 뉴스 보기
# ══════════════════════════════════════════════
with tab_saved:
    saved = load_saved()
    if not saved:
        st.info("저장된 뉴스가 없습니다. [자동 수집] 탭에서 먼저 수집해 주세요.")
    else:
        st.markdown(f"**총 {len(saved)}건** | 저장 파일: `{JSON_FILE}`")

        # 필터
        fc1, fc2, fc3 = st.columns(3)
        cat_opts = ["전체"] + [CAT_LABEL[c] for c in CAT_LABEL if any(it.get("category")==c for it in saved)]
        sel_cat_filter = fc1.selectbox("카테고리", cat_opts, key="saved_cat")
        dir_opts = ["전체","긍정","부정","혼조","중립"]
        sel_dir = fc2.selectbox("방향", dir_opts, key="saved_dir")
        keyword = fc3.text_input("키워드 검색", placeholder="제목/지역 검색", key="saved_kw")

        filtered = saved
        if sel_cat_filter != "전체":
            cat_key = {v:k for k,v in CAT_LABEL.items()}.get(sel_cat_filter)
            filtered = [it for it in filtered if it.get("category") == cat_key]
        if sel_dir != "전체":
            filtered = [it for it in filtered if it.get("direction") == sel_dir]
        if keyword:
            kw = keyword.lower()
            filtered = [it for it in filtered
                        if kw in it.get("title","").lower()
                        or kw in " ".join(it.get("regions",[])).lower()]

        st.caption(f"필터 결과: {len(filtered)}건")

        rows = []
        for it in filtered:
            rows.append({
                "날짜":     it.get("date",""),
                "카테고리": CAT_LABEL.get(it.get("category","ETC"), "기타"),
                "방향":     it.get("direction","—"),
                "지역":     " / ".join(it.get("regions",[])),
                "제목":     it.get("title",""),
                "출처":     it.get("publisher",""),
                "링크":     it.get("url",""),
            })

        st.dataframe(
            pd.DataFrame(rows),
            column_config={
                "링크": st.column_config.LinkColumn("링크", display_text="🔗"),
                "날짜": st.column_config.TextColumn("날짜", width="small"),
                "카테고리": st.column_config.TextColumn("카테고리", width="medium"),
                "방향": st.column_config.TextColumn("방향", width="small"),
            },
            use_container_width=True,
            hide_index=True,
        )

        # 삭제 버튼
        if st.button("🗑️ 저장된 데이터 전체 초기화", type="secondary"):
            JSON_FILE.unlink(missing_ok=True)
            MD_FILE.unlink(missing_ok=True)
            st.success("초기화 완료. 새로고침 해주세요.")
