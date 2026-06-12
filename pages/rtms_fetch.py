"""
pages/rtms_fetch.py — 국토교통부 아파트 실거래가 자동 수집 (웹앱 내장)

네이버와 달리 국토부 공공 API는 클라우드 서버에서도 호출 가능하므로,
Streamlit Cloud에 배포된 웹앱에서 버튼만 누르면 바로 수집됩니다.
"""
import os
import sqlite3
import time
import xml.etree.ElementTree as ET
from datetime import date

import requests
import streamlit as st

from db import push_rtms_to_sheet, restore_rtms_from_sheet, GAS_URL, GAS_TOKEN
from utils_style import inject_korean_font

inject_korean_font()

DB_PATH = os.environ.get("DB_PATH", "/tmp/naver_land.db")

API_URL       = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
API_URL_RENT  = "https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"

# 지역별 키워드 설정 — 빈 리스트이면 해당 지역 전체 수집
REGION_KEYWORDS: dict[str, list[str]] = {
    "41220": ["센트럴자이", "더샵지제역", "e편한세상", "동문굿모닝힐", "동문디이스트", "우미린", "공도"],
    "43113": [],  # 청주 흥덕구 — 전체 수집 (단지 미지정)
    "43114": [],  # 청주 청원구 — 전체 수집 (단지 미지정)
}

# 법정동 코드 (앞 5자리) → 표시명
LAWD_OPTIONS: dict[str, str] = {
    "경기 평택시":      "41220",
    "충북 청주시 흥덕구": "43113",
    "충북 청주시 청원구": "43114",
}

_KEY_SS = "rtms_api_key"


# ── DB ────────────────────────────────────────────────────────
def _init_table():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rtms_jeonse (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            lawd_cd      TEXT    NOT NULL,
            deal_year    INTEGER NOT NULL,
            deal_month   INTEGER NOT NULL,
            apt_name     TEXT    NOT NULL,
            area         REAL,
            deposit_man  INTEGER,
            monthly_rent INTEGER,
            contract_type TEXT,
            fetched_at   TEXT    NOT NULL,
            UNIQUE(lawd_cd, deal_year, deal_month, apt_name, area, deposit_man, monthly_rent)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_jeonse_apt_date
        ON rtms_jeonse(apt_name, deal_year, deal_month)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rtms_transactions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            lawd_cd       TEXT    NOT NULL,
            deal_year     INTEGER NOT NULL,
            deal_month    INTEGER NOT NULL,
            deal_day      INTEGER NOT NULL,
            apt_name      TEXT    NOT NULL,
            dong          TEXT,
            floor         INTEGER,
            area          REAL,
            price_man     INTEGER NOT NULL,
            build_year    INTEGER,
            road_name     TEXT,
            cancel_yn     TEXT,
            fetched_at    TEXT    NOT NULL,
            UNIQUE(lawd_cd, deal_year, deal_month, deal_day, apt_name, dong, floor, area, price_man)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_rtms_apt_date
        ON rtms_transactions(apt_name, deal_year, deal_month)
    """)
    conn.commit()
    conn.close()


def _ym_list(months: int) -> list[str]:
    """오늘 기준 최근 N개월 YYYYMM 리스트"""
    today = date.today()
    out = []
    y, m = today.year, today.month
    for _ in range(months):
        out.append(f"{y}{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return out


def _fetch_month(api_key: str, lawd_cd: str, ym: str, page: int, num_rows: int = 100) -> dict:
    params = {
        "serviceKey": api_key,
        "LAWD_CD":    lawd_cd,
        "DEAL_YMD":   ym,
        "pageNo":     page,
        "numOfRows":  num_rows,
    }
    try:
        resp = requests.get(API_URL, params=params, timeout=20)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        code = root.findtext(".//resultCode", "")
        if code not in ("00", "000"):
            msg = root.findtext(".//resultMsg", "알 수 없는 오류")
            return {"error": f"[{code}] {msg}", "totalCount": 0, "items": []}

        total = int(root.findtext(".//totalCount", "0") or 0)
        items = []
        for item in root.findall(".//item"):
            def g(*tags):
                """한글/영문 태그 모두 시도 — 신형 Dev API는 영문 태그 사용"""
                for tag in tags:
                    v = item.findtext(tag, "")
                    if v and v.strip():
                        return v.strip()
                return ""
            items.append({
                "apt_name":   g("아파트", "aptNm"),
                "dong":       g("법정동", "umdNm"),
                "floor":      g("층", "floor"),
                "area":       g("전용면적", "excluUseAr"),
                "price_man":  g("거래금액", "dealAmount").replace(",", ""),
                "build_year": g("건축년도", "buildYear"),
                "deal_day":   g("일", "dealDay"),
                "road_name":  g("도로명", "roadNm"),
                "cancel_yn":  g("해제여부", "cdealType"),
            })
        return {"error": "", "totalCount": total, "items": items}
    except Exception as e:
        return {"error": str(e), "totalCount": 0, "items": []}


def _save_items(lawd_cd: str, ym: str, items: list) -> int:
    year, month = int(ym[:4]), int(ym[4:])
    fetched_at  = date.today().isoformat()
    keywords    = REGION_KEYWORDS.get(lawd_cd, [])
    rows = []
    for it in items:
        if keywords and not any(kw in it["apt_name"] for kw in keywords):
            continue
        try:
            price_man = int(it["price_man"]) if it["price_man"] else None
            floor     = int(it["floor"])     if it["floor"]     else None
            area      = float(it["area"])    if it["area"]      else None
            build_yr  = int(it["build_year"]) if it["build_year"] else None
            day       = int(it["deal_day"])  if it["deal_day"]  else 1
        except (ValueError, TypeError):
            continue
        if price_man is None:
            continue
        rows.append((
            lawd_cd, year, month, day,
            it["apt_name"], it["dong"], floor, area, price_man,
            build_yr, it["road_name"], it["cancel_yn"] or None, fetched_at,
        ))
    if not rows:
        return 0
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cur = conn.executemany("""
        INSERT OR IGNORE INTO rtms_transactions
          (lawd_cd, deal_year, deal_month, deal_day, apt_name, dong, floor, area,
           price_man, build_year, road_name, cancel_yn, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()
    saved = cur.rowcount
    conn.close()
    return saved


def _fetch_rent_month(api_key: str, lawd_cd: str, ym: str, page: int, num_rows: int = 100) -> dict:
    """전월세 한 달치 조회"""
    params = {
        "serviceKey": api_key, "LAWD_CD": lawd_cd,
        "DEAL_YMD": ym, "pageNo": page, "numOfRows": num_rows,
    }
    try:
        resp = requests.get(API_URL_RENT, params=params, timeout=20)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        code = root.findtext(".//resultCode", "")
        if code not in ("00", "000"):
            return {"error": root.findtext(".//resultMsg", "오류"), "totalCount": 0, "items": []}
        total = int(root.findtext(".//totalCount", "0") or 0)
        items = []
        for item in root.findall(".//item"):
            def g(*tags):
                for tag in tags:
                    v = item.findtext(tag, "")
                    if v and v.strip(): return v.strip()
                return ""
            items.append({
                "apt_name":      g("아파트", "aptNm"),
                "area":          g("전용면적", "excluUseAr"),
                "deposit":       g("보증금액", "deposit").replace(",", ""),
                "monthly_rent":  g("월세금액", "monthlyRent").replace(",", ""),
                "contract_type": g("계약구분", "contractType"),
            })
        return {"error": "", "totalCount": total, "items": items}
    except Exception as e:
        return {"error": str(e), "totalCount": 0, "items": []}


def _save_rent_items(lawd_cd: str, ym: str, items: list) -> int:
    year, month = int(ym[:4]), int(ym[4:])
    fetched_at  = date.today().isoformat()
    keywords    = REGION_KEYWORDS.get(lawd_cd, [])
    rows = []
    for it in items:
        if keywords and not any(kw in it["apt_name"] for kw in keywords):
            continue
        try:
            deposit = int(it["deposit"]) if it["deposit"] else None
            rent    = int(it["monthly_rent"]) if it["monthly_rent"] else 0
            area    = float(it["area"]) if it["area"] else None
        except (ValueError, TypeError):
            continue
        if deposit is None:
            continue
        rows.append((
            lawd_cd, year, month, it["apt_name"], area,
            deposit, rent, it["contract_type"] or None, fetched_at,
        ))
    if not rows:
        return 0
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cur = conn.executemany("""
        INSERT OR IGNORE INTO rtms_jeonse
          (lawd_cd, deal_year, deal_month, apt_name, area,
           deposit_man, monthly_rent, contract_type, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()
    saved = cur.rowcount
    conn.close()
    return saved


# ── 페이지 UI ─────────────────────────────────────────────────
_init_table()

st.title("국토부 실거래가 자동 수집")
st.caption("실제 거래 완료된 가격 (국토교통부 공식). 네이버 호가보다 정확하며, 클라우드에서 바로 수집됩니다.")

# API 키 입력
default_key = st.session_state.get(_KEY_SS, os.environ.get("RTMS_API_KEY", ""))
api_key = st.text_input(
    "공공데이터포털 API 인증키",
    value=default_key,
    type="password",
    help="data.go.kr 마이페이지 → 일반 인증키(Decoding)",
)
if api_key:
    st.session_state[_KEY_SS] = api_key

col1, col2 = st.columns(2)
with col1:
    sel_regions = st.multiselect(
        "지역 (복수 선택 가능)",
        list(LAWD_OPTIONS.keys()),
        default=["경기 평택시"],
    )
with col2:
    months = st.number_input("수집 개월 수", min_value=1, max_value=60, value=24, step=6)

if sel_regions:
    selected_lawds = [LAWD_OPTIONS[r] for r in sel_regions]
    kw_parts = []
    for r in sel_regions:
        lcd = LAWD_OPTIONS[r]
        kws = REGION_KEYWORDS.get(lcd, [])
        kw_parts.append(f"{r}: {', '.join(kws) if kws else '전체'}")
    st.caption("  |  ".join(kw_parts))
else:
    selected_lawds = []
    st.caption("지역을 하나 이상 선택하세요.")

also_rent = st.checkbox(
    "전월세 데이터도 함께 수집 (전세가율 계산에 필요)",
    value=True,
    help="국토부 전월세 실거래가 API를 추가로 호출합니다. 전세가율 = 전세보증금 ÷ 매매가"
)

st.divider()

if st.button("▶ 지금 수집 시작", type="primary", disabled=not api_key or not selected_lawds):
    yms = _ym_list(int(months))
    total_steps = len(yms) * len(selected_lawds)
    progress = st.progress(0.0)
    status = st.empty()
    log = st.container()
    total_saved = 0
    first_error = None
    sample_names: set[str] = set()
    step = 0

    for lawd_cd in selected_lawds:
        region_name = next(k for k, v in LAWD_OPTIONS.items() if v == lawd_cd)
        for i, ym in enumerate(yms):
            status.markdown(f"**수집 중...** [{region_name}] {ym} ({step+1}/{total_steps})")

            all_items = []
            page = 1
            while True:
                res = _fetch_month(api_key, lawd_cd, ym, page)
                if res["error"]:
                    if first_error is None:
                        first_error = res["error"]
                    break
                all_items.extend(res["items"])
                if len(all_items) >= res["totalCount"] or not res["items"]:
                    break
                page += 1
                time.sleep(0.2)

            for it in all_items:
                if len(sample_names) < 300:
                    sample_names.add(it.get("apt_name", "") or "(빈값)")

            saved = _save_items(lawd_cd, ym, all_items)
            total_saved += saved
            with log:
                st.caption(f"  [{region_name}] {ym} → 전체 {len(all_items)}건 중 {saved}건 저장")
            step += 1
            progress.progress(step / total_steps)
            time.sleep(0.1)

    # 전월세 수집
    rent_saved = 0
    if also_rent and not first_error:
        status2 = st.empty()
        step = 0
        for lawd_cd in selected_lawds:
            region_name = next(k for k, v in LAWD_OPTIONS.items() if v == lawd_cd)
            for i, ym in enumerate(yms):
                status2.markdown(f"**전월세 수집 중...** [{region_name}] {ym} ({step+1}/{total_steps})")
                all_items = []
                page = 1
                while True:
                    res = _fetch_rent_month(api_key, lawd_cd, ym, page)
                    if res["error"] or not res["items"]:
                        break
                    all_items.extend(res["items"])
                    if len(all_items) >= res["totalCount"]:
                        break
                    page += 1
                    time.sleep(0.2)
                rent_saved += _save_rent_items(lawd_cd, ym, all_items)
                step += 1
                time.sleep(0.1)
        status2.empty()

    status.empty()

    # 진단 패널
    if sample_names:
        all_kws: list[str] = []
        for lcd in selected_lawds:
            all_kws.extend(REGION_KEYWORDS.get(lcd, []))
        matched = ([n for n in sorted(sample_names) if any(kw in n for kw in all_kws)]
                   if all_kws else sorted(sample_names))
        with st.expander(f"🔍 진단: 받은 단지명 {len(sample_names)}종 (필터 매칭 {len(matched)}종)", expanded=(total_saved == 0)):
            st.markdown("**키워드 매칭된 단지:**")
            st.write(matched if matched else "(매칭된 단지 없음 — 키워드 수정 필요)")
            st.markdown("**받은 전체 단지명 (가나다순):**")
            st.write(sorted(sample_names))
    if first_error:
        st.error(f"API 오류: {first_error}\n\n인증키가 올바른지, 활용신청이 승인됐는지 확인하세요.")
    if total_saved > 0 or rent_saved > 0:
        st.success(f"🎉 수집 완료 — 매매 **{total_saved}건** / 전월세 **{rent_saved}건** 저장")

        # 구글시트 자동 백업
        with st.spinner("☁️ 구글시트에 자동 백업 중..."):
            t, j, err = push_rtms_to_sheet()
            if err:
                st.error(
                    f"⚠️ 구글시트 백업 실패: {err}\n\n"
                    "→ 스프레드시트에 **RTMS매매**, **RTMS전월세** 탭이 있는지 확인하세요. "
                    "백업이 안 되면 앱이 잠든 뒤 데이터가 사라집니다. "
                    "아래 '☁️ 데이터 영구 저장' 섹션에서 수동 백업을 다시 시도할 수 있습니다."
                )
            else:
                st.success(f"☁️ 구글시트 백업 완료 — 매매 {t}건 / 전월세 {j}건 (앱 재시작 시 자동 복원됨)")
    elif not first_error:
        st.warning("저장된 건이 없습니다. (해당 기간 대상 단지 거래가 없었을 수 있음)")

    st.cache_data.clear()

# ── 수집 현황 ─────────────────────────────────────────────────
st.divider()
st.subheader("저장된 실거래가 현황")
try:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT apt_name,
               COUNT(*) AS cnt,
               MIN(printf('%04d-%02d', deal_year, deal_month)) AS from_ym,
               MAX(printf('%04d-%02d', deal_year, deal_month)) AS to_ym,
               MIN(price_man) AS min_man,
               MAX(price_man) AS max_man
        FROM rtms_transactions
        GROUP BY apt_name
        ORDER BY cnt DESC
    """).fetchall()
    conn.close()
    if rows:
        import pandas as pd
        df = pd.DataFrame([dict(r) for r in rows])
        df["min_man"] = (df["min_man"] / 10000).round(2).astype(str) + "억"
        df["max_man"] = (df["max_man"] / 10000).round(2).astype(str) + "억"
        df.columns = ["단지명", "거래건수", "시작", "종료", "최저가", "최고가"]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.caption("아직 수집된 실거래가가 없습니다. 위에서 수집을 시작하세요.")
except Exception as e:
    st.caption(f"현황 조회 오류: {e}")

# ── 데이터 영구 저장 (구글시트 백업/복원) ─────────────────────
st.divider()
st.subheader("☁️ 데이터 영구 저장 (구글시트)")
st.caption(
    "이 앱의 DB는 서버가 잠들면 사라지는 임시 저장소(`/tmp`)입니다. "
    "**저장 흐름**: 수집 완료 → 구글시트 `RTMS매매`/`RTMS전월세` 탭에 자동 백업 → "
    "앱이 다시 켜질 때 시트에서 자동 복원. "
    "1달 주기로 수집만 하면 됩니다 — 백업·복원은 자동입니다. 아래는 수동 확인/실행용 버튼입니다."
)

# 현재 DB 건수
def _db_counts() -> tuple[int, int]:
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        n_t = conn.execute("SELECT COUNT(*) FROM rtms_transactions").fetchone()[0]
        n_j = conn.execute("SELECT COUNT(*) FROM rtms_jeonse").fetchone()[0]
        conn.close()
        return n_t, n_j
    except Exception:
        return 0, 0

n_trade, n_jeonse = _db_counts()
m1, m2 = st.columns(2)
m1.metric("현재 DB — 매매", f"{n_trade:,}건")
m2.metric("현재 DB — 전월세", f"{n_jeonse:,}건")

b1, b2, b3 = st.columns(3)

with b1:
    if st.button("☁️ 지금 시트로 백업", use_container_width=True, disabled=(n_trade == 0 and n_jeonse == 0)):
        with st.spinner("구글시트로 백업 중..."):
            t, j, err = push_rtms_to_sheet()
        if err:
            st.error(f"백업 실패: {err}\n\n시트에 RTMS매매/RTMS전월세 탭이 있는지 확인하세요.")
        else:
            st.success(f"백업 완료 — 매매 {t}건 / 전월세 {j}건")

with b2:
    if st.button("📥 시트에서 복원", use_container_width=True):
        with st.spinner("구글시트에서 복원 중..."):
            t, j = restore_rtms_from_sheet()
        if t > 0 or j > 0:
            st.success(f"복원 완료 — 매매 {t}건 / 전월세 {j}건 (중복은 자동 제외)")
            st.cache_data.clear()
        else:
            st.warning("복원된 데이터가 없습니다. 시트가 비어있거나 이미 모두 DB에 있는 데이터입니다.")

with b3:
    if st.button("🔍 시트 저장 상태 확인", use_container_width=True):
        with st.spinner("구글시트 조회 중..."):
            for sheet in ("RTMS매매", "RTMS전월세"):
                try:
                    r = requests.get(
                        GAS_URL,
                        params={"token": GAS_TOKEN, "sheet_name": sheet},
                        timeout=30,
                    )
                    rows = r.json().get("rows", []) if r.status_code == 200 else []
                    if r.status_code == 200:
                        st.info(f"**{sheet}** 탭: {len(rows):,}행 저장됨")
                    else:
                        st.error(f"**{sheet}** 탭: HTTP {r.status_code} — 탭이 없거나 GAS 설정 확인 필요")
                except Exception as e:
                    st.error(f"**{sheet}** 탭 조회 실패: {e}")
