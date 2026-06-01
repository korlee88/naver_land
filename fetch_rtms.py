"""
fetch_rtms.py — 국토교통부 아파트 매매 실거래가 수집기

사용법:
  python fetch_rtms.py --key YOUR_API_KEY
  python fetch_rtms.py --key YOUR_API_KEY --months 24
  python fetch_rtms.py --key YOUR_API_KEY --months 12 --lawd 41220

법정동 코드(LAWD_CD):
  경기도 평택시 = 41220
  code.go.kr 에서 다른 지역 코드 확인 가능

API: 국토교통부_아파트매매 실거래 상세 자료
  https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev
"""
import argparse
import os
import sqlite3
import time
import xml.etree.ElementTree as ET
from datetime import date
from dateutil.relativedelta import relativedelta

import requests

DB_PATH = os.environ.get("DB_PATH", "./naver_land.db")

# 수집할 단지명 키워드 (포함 여부로 필터링, 빈 리스트 = 전체 저장)
TARGET_KEYWORDS = [
    "센트럴자이",
    "더샵지제역",
    "e편한세상",
    "동문굿모닝힐",
    "동문디이스트",
    "우미린",
    "공도",
]

API_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"


# ── DB 초기화 ──────────────────────────────────────────────────
def init_table():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
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


# ── API 호출 ───────────────────────────────────────────────────
def fetch_month(api_key: str, lawd_cd: str, ym: str, page: int = 1, num_rows: int = 100) -> dict:
    """한 달치 데이터 한 페이지 조회. 반환: {totalCount, items: [...]}"""
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

        result_code = root.findtext(".//resultCode", "")
        if result_code != "00":
            msg = root.findtext(".//resultMsg", "알 수 없는 오류")
            print(f"    API 오류: [{result_code}] {msg}")
            return {"totalCount": 0, "items": []}

        total = int(root.findtext(".//totalCount", "0") or 0)
        items = []
        for item in root.findall(".//item"):
            def g(tag):
                v = item.findtext(tag, "")
                return v.strip() if v else ""

            items.append({
                "apt_name":   g("아파트"),
                "dong":       g("법정동"),
                "floor":      g("층"),
                "area":       g("전용면적"),
                "price_man":  g("거래금액").replace(",", ""),
                "build_year": g("건축년도"),
                "deal_day":   g("일"),
                "road_name":  g("도로명"),
                "cancel_yn":  g("해제여부"),
            })
        return {"totalCount": total, "items": items}

    except Exception as e:
        print(f"    요청 실패: {e}")
        return {"totalCount": 0, "items": []}


# ── 저장 ──────────────────────────────────────────────────────
def save_items(lawd_cd: str, year: int, month: int, items: list) -> tuple[int, int]:
    """반환: (saved, skipped)"""
    fetched_at = date.today().isoformat()
    rows = []

    for it in items:
        # 키워드 필터
        if TARGET_KEYWORDS and not any(kw in it["apt_name"] for kw in TARGET_KEYWORDS):
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
        return 0, len(items)

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
    return saved, len(items) - saved


# ── 메인 ──────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="국토부 아파트 매매 실거래가 수집")
    parser.add_argument("--key",    required=True, help="공공데이터포털 API 인증키")
    parser.add_argument("--lawd",   default="41220", help="법정동 코드 앞 5자리 (기본: 41220 평택시)")
    parser.add_argument("--months", type=int, default=24, help="수집 개월 수 (기본: 24)")
    args = parser.parse_args()

    init_table()

    today = date.today()
    grand_saved = grand_skip = 0

    print(f"📍 법정동: {args.lawd}  |  최근 {args.months}개월 수집\n")

    for m in range(args.months):
        target = today - relativedelta(months=m)
        ym = target.strftime("%Y%m")

        # 첫 페이지로 totalCount 확인
        result = fetch_month(args.key, args.lawd, ym)
        total  = result["totalCount"]
        items  = result["items"]
        print(f"  {ym}  전체 {total}건", end=" ")

        # 페이지가 여러 개면 추가 조회
        page = 2
        while len(items) < total:
            more = fetch_month(args.key, args.lawd, ym, page=page)
            if not more["items"]:
                break
            items.extend(more["items"])
            page += 1
            time.sleep(0.3)

        saved, skipped = save_items(args.lawd, target.year, target.month, items)
        print(f"→ 저장 {saved}건 / 스킵 {skipped}건")
        grand_saved += saved
        grand_skip  += skipped
        time.sleep(0.5)

    print(f"\n🎉 완료 — 저장 {grand_saved}건 / 스킵 {grand_skip}건 ({DB_PATH})")


if __name__ == "__main__":
    main()
