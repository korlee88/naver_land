# rawdata.py
import re
import requests
from datetime import datetime

import pandas as pd
import streamlit as st

from db import init_db, upsert_listing_and_history
from utils_uid import make_uid

# ── 초기화 ──────────────────────────────────────────────────────────────────
st.set_page_config(page_title="매물 입력", layout="wide")
init_db()

# ── 한글 웹폰트 (Railway/Linux 한글 깨짐 방지) ─────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Nanum+Gothic:wght@400;700;800&display=swap');
html, body, [class*="css"], .stMarkdown, .stText, .stMetric,
div, span, p, h1, h2, h3, label, button, input, textarea, select {
    font-family: 'Nanum Gothic', 'Malgun Gothic', '맑은 고딕', sans-serif !important;
}
</style>
""", unsafe_allow_html=True)

# ── 구글시트 설정 ─────────────────────────────────────────────────────────
GAS_URL        = "https://script.google.com/macros/s/AKfycbwLB0tecqN_hOgzEqo8jS9OH13llHeraXDQ7G_CZ60XDvBFmDv6sX1luG6kY5m0Z1_uug/exec"
GAS_TOKEN      = "MY_SECRET_TOKEN"
GAS_SHEET_NAME = "APT_RAWDATA"

# ── 정규식 (모듈 로드 시 1회 컴파일) ──────────────────────────────────────
_RE_COMPLEX = re.compile(
    r"(?:^|\s)(?:집주인)?\s*"
    r"(?P<name>(?=[^\s]*[가-힣])[가-힣0-9A-Za-z\(\)\-]+(?:\d+단지)?)\s*"
    r"(?P<dong>\d{2,4}동)\b"
)
_RE_TRADE   = re.compile(r"\b(매매|전세|월세)\s*([0-9억,\s~\.]+)")
_RE_AREA    = re.compile(r"(\d+[A-Z]?/\d+(?:\.\d+)?m²)")
_RE_FLOOR   = re.compile(r"(\d+/\d+층|저/\d+층|고/\d+층|중/\d+층|\d+층)")
_RE_DIR     = re.compile(r"(남동향|남서향|남향|북향|동향|서향)")
_RE_CONFIRM = re.compile(r"확인매물\s*([0-9]{2}\.[0-9]{2}\.[0-9]{2})")
_RE_PROV    = re.compile(r"([가-힣A-Za-z]+)\s*제공")
_RE_OFFICE  = re.compile(r"([가-힣0-9A-Za-z]+공인중개사사무소)")
_RE_SPACES  = re.compile(r"\s+")

_MEMO_SKIP  = ("집주인", "확인매물", "매매", "전세", "월세")
REQUIRED    = ["단지명", "동", "거래유형", "가격", "확인매물"]


# ── 파싱 함수 ─────────────────────────────────────────────────────────────
def split_blocks(text: str) -> list[str]:
    """'확인매물' 줄 기준으로 블록 분리"""
    blocks, buf = [], []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        buf.append(line)
        if line.startswith("확인매물"):
            blocks.append("\n".join(buf))
            buf = []
    if buf:
        blocks.append("\n".join(buf))
    return blocks


def parse_block(block: str) -> dict:
    s = _RE_SPACES.sub(" ", block)   # 검색용 단일 라인

    name = dong = trade = price = area = floor_ = dir_ = confirm = prov = office = None

    m = _RE_COMPLEX.search(s)
    if m:
        name = _RE_SPACES.sub(" ", m.group("name")).strip()
        dong = m.group("dong").strip()

    m = _RE_TRADE.search(s)
    if m:
        trade = m.group(1)
        price = f"{m.group(1)}{m.group(2).strip()}".replace("  ", " ")

    m = _RE_AREA.search(s);    area    = m.group(1) if m else None
    m = _RE_FLOOR.search(s);   floor_  = m.group(1) if m else None
    m = _RE_DIR.search(s);     dir_    = m.group(1) if m else None
    m = _RE_CONFIRM.search(s); confirm = m.group(1) if m else None
    m = _RE_PROV.search(s);    prov    = m.group(1) if m else None
    m = _RE_OFFICE.search(s);  office  = m.group(1) if m else None

    memo = None
    for line in block.splitlines():
        t = line.strip()
        if not t or len(t) < 6:
            continue
        if t.startswith(_MEMO_SKIP) or "제공" in t:
            continue
        if "아파트" in t and "m²" in t:
            continue
        memo = t
        break

    return {
        "단지명": name, "동": dong, "거래유형": trade, "가격": price,
        "면적": area, "층": floor_, "향": dir_, "확인매물": confirm,
        "제공처": prov, "중개사무소": office, "요약메모": memo, "원문블록": block,
    }


# ── 구글시트 전송 ──────────────────────────────────────────────────────────
def _to_gsheet_rows(records: list[dict], batch_id: str) -> list[list]:
    today = datetime.now().strftime("%Y-%m-%d")
    return [
        [today, batch_id,
         r.get("uid"), r.get("단지명"), r.get("동"), r.get("면적"),
         r.get("층"), r.get("향"), r.get("거래유형"), r.get("가격"),
         r.get("확인매물"), r.get("제공처"), r.get("중개사무소"),
         r.get("요약메모"), r.get("원문블록")]
        for r in records
    ]


def _push_gsheet(rows_2d, batch_size=200):
    ok = fail = 0
    last = ""
    for i in range(0, len(rows_2d), batch_size):
        chunk = rows_2d[i:i + batch_size]
        try:
            r = requests.post(
                GAS_URL,
                json={"token": GAS_TOKEN, "rows": chunk, "sheet_name": GAS_SHEET_NAME},
                timeout=30,
            )
            r.raise_for_status()
            last = r.text
            ok += len(chunk) if str(last).upper().startswith("OK") else 0
            fail += 0 if str(last).upper().startswith("OK") else len(chunk)
        except Exception as e:
            fail += len(chunk)
            last = str(e)
    return ok, fail, last


# ── UI ────────────────────────────────────────────────────────────────────
st.title("매물 입력 (RAW)")
st.caption("복사 → 붙여넣기 → 정리 → 저장")

raw = st.text_area(
    "매물 내용 붙여넣기",
    height=260,
    placeholder="예) 집주인... / 매매... / 확인매물 26.01.22 ...",
)

c1, c2, c3 = st.columns(3)
keep_raw   = c1.checkbox("원문블록 유지", value=True)
keep_memo  = c2.checkbox("요약메모 유지", value=True)
use_gsheet = c3.checkbox("구글시트 저장", value=True)

if st.button("정리하기", type="primary", use_container_width=True):
    blocks = split_blocks(raw) if raw else []
    if not blocks:
        st.warning("파싱할 블록을 찾지 못했습니다.")
        st.stop()

    batch_id = datetime.now().strftime("%Y-%m-%d")
    rows = [parse_block(b) for b in blocks]
    df   = pd.DataFrame(rows)
    df["uid"]      = df.apply(
        lambda r: make_uid(r["단지명"], r["동"], r["면적"], r["거래유형"], r["층"]), axis=1
    )
    df["batch_id"] = batch_id
    st.session_state["df_parsed"] = df

# ── 파싱 결과 ─────────────────────────────────────────────────────────────
df = st.session_state.get("df_parsed")
if df is None or df.empty:
    st.info("위에 붙여넣고 '정리하기'를 눌러주세요.")
    st.stop()

# 표시 컬럼 구성
hide = []
if not keep_raw:  hide.append("원문블록")
if not keep_memo: hide.append("요약메모")
view_df = df.drop(columns=[c for c in hide if c in df.columns])
st.dataframe(view_df, use_container_width=True)

# 필수값 검증
bad = df[df[REQUIRED].isna().any(axis=1)]
if not bad.empty:
    st.error(f"❌ {len(bad)}건 파싱 실패 (단지명 등 누락) — 저장 불가")
    st.dataframe(bad[REQUIRED + ["원문블록"]].head(20), use_container_width=True)
    st.stop()

st.divider()

# ── 저장 ──────────────────────────────────────────────────────────────────
if st.button("저장하기 (로컬DB / 선택: 구글시트)", use_container_width=True):
    records  = df.to_dict("records")
    inserted = updated = history = 0

    prog = st.progress(0, text="저장 중…")
    for i, r in enumerate(records):
        result, hist = upsert_listing_and_history({
            "uid":          r.get("uid"),
            "complex_name": r.get("단지명"),
            "dong":         r.get("동"),
            "area":         r.get("면적"),
            "trade_type":   r.get("거래유형"),
            "floor":        r.get("층"),
            "direction":    r.get("향"),
            "price_text":   r.get("가격"),
            "confirm_date": r.get("확인매물"),
            "provider":     r.get("제공처"),
            "office":       r.get("중개사무소"),
            "memo":         r.get("요약메모"),
            "raw_block":    r.get("원문블록"),
            "batch_id":     r.get("batch_id"),
        })
        inserted += result == "insert"
        updated  += result != "insert"
        history  += hist == "history"
        prog.progress((i + 1) / len(records), text=f"{i+1}/{len(records)} 저장 중…")

    prog.empty()
    st.success(f"✅ 로컬DB 완료 — 신규 {inserted} / 업데이트 {updated} / 히스토리 {history}")

    if use_gsheet:
        batch_id = records[0].get("batch_id", datetime.now().strftime("%Y-%m-%d"))
        try:
            rows_2d = _to_gsheet_rows(records, batch_id)
            ok, fail, last = _push_gsheet(rows_2d)
            st.success(f"구글시트 — 성공 {ok} / 실패 {fail} (응답: {last})")
        except Exception as e:
            st.warning(f"구글시트 저장 실패 (로컬DB는 저장됨): {e}")
