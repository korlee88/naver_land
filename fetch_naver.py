"""
fetch_naver.py — 네이버 부동산 API 자동 시세 수집기

Usage:
  # 브라우저 쿠키를 .env 또는 환경변수로 전달
  python fetch_naver.py
  python fetch_naver.py --days 365
  python fetch_naver.py --cookie "NAC=xxx; NNB=yyy; ..."
  python fetch_naver.py --complex 110834 "평택센트럴자이 2단지"

단지 complexNumber 찾는 법:
  네이버 부동산 → 단지 클릭 → DevTools Network →
  complexNumber=XXXXX 숫자 확인
"""
import argparse
import os
import sqlite3
import sys
import time
from datetime import date, timedelta

import requests

# ── DB 경로 (db.py 와 동일 로직) ─────────────────
DB_PATH = os.environ.get("DB_PATH", "./naver_land.db")

# ── 단지 매핑 (complexNumber 추가 필요) ──────────
# 네이버 부동산 단지 클릭 → DevTools Network → complexNumber=숫자 확인
COMPLEX_MAP: dict[str, int] = {
    "평택센트럴자이 2단지": 110834,
    # "평택센트럴자이 1단지": 0,   ← 추후 추가
    # "평택센트럴자이 3단지": 0,
    # "평택센트럴자이 4단지": 0,
    # "평택센트럴자이 5단지": 0,
    # "더샵지제역센트럴파크(1BL)": 0,
    # "더샵지제역센트럴파크(2BL)": 0,
    # "더샵지제역센트럴파크(3BL)": 0,
    # "e편한세상지제역": 0,
    # "e편한세상평택용이2단지": 0,
}

BASE_URL = "https://fin.land.naver.com/front-api/v1"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Referer": "https://fin.land.naver.com/",
    "sec-fetch-site": "same-origin",
    "sec-fetch-mode": "cors",
}


# ════════════════════════════════════════════════
# DB 초기화
# ════════════════════════════════════════════════
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_table():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS naver_market_prices (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                complex_name        TEXT    NOT NULL,
                complex_number      INTEGER NOT NULL,
                pyeong_label        TEXT,
                pyeong_type_number  INTEGER NOT NULL,
                cp                  TEXT    NOT NULL,
                trade_type          TEXT    NOT NULL,
                price_date          TEXT    NOT NULL,
                avg_price           INTEGER,
                max_price           INTEGER,
                min_price           INTEGER,
                fetched_at          TEXT    NOT NULL,
                UNIQUE(complex_number, pyeong_type_number, cp, trade_type, price_date)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_nmp_complex_date
            ON naver_market_prices(complex_name, trade_type, price_date)
        """)


# ════════════════════════════════════════════════
# API 호출
# ════════════════════════════════════════════════
def get_pyeong_list(session: requests.Session, complex_number: int) -> list[dict]:
    """단지 평형 목록 조회"""
    url = f"{BASE_URL}/complex/pyeong/complexPyeongList"
    try:
        resp = session.get(url, params={"complexNumber": complex_number}, timeout=10)
        data = resp.json()
        if data.get("isSuccess"):
            return data.get("result", [])
    except Exception as e:
        print(f"    pyeongList 조회 실패: {e}")
    return []


def fetch_market_prices(
    session: requests.Session,
    complex_number: int,
    pyeong_type_number: int,
    start_date: date,
    end_date: date,
) -> dict:
    """주간 호가 추이 조회"""
    url = f"{BASE_URL}/complex/marketPrice/list"
    params = {
        "complexNumber": complex_number,
        "pyeongTypeNumber": pyeong_type_number,
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "cpList": ["kab", "kbstar"],
    }
    try:
        resp = session.get(url, params=params, timeout=15)
        return resp.json()
    except Exception as e:
        print(f"    fetch 실패: {e}")
        return {}


# ════════════════════════════════════════════════
# DB 저장
# ════════════════════════════════════════════════
def save_prices(
    complex_name: str,
    complex_number: int,
    pyeong_label: str,
    pyeong_type_number: int,
    data: dict,
) -> int:
    fetched_at = date.today().isoformat()
    rows = []

    for cp_data in data.get("result", []):
        cp = cp_data.get("cp", "")

        # 매매 (deal)
        for price_date, avg_price in cp_data.get("dealPrices", {}).items():
            rng = cp_data.get("dealPriceRanges", {}).get(price_date, {})
            rows.append((
                complex_name, complex_number, pyeong_label, pyeong_type_number,
                cp, "매매", price_date, avg_price,
                rng.get("ceiling"), rng.get("floor"), fetched_at,
            ))

        # 전세 (deposit)
        for price_date, avg_price in cp_data.get("depositPrices", {}).items():
            rng = cp_data.get("depositPriceRanges", {}).get(price_date, {})
            rows.append((
                complex_name, complex_number, pyeong_label, pyeong_type_number,
                cp, "전세", price_date, avg_price,
                rng.get("ceiling"), rng.get("floor"), fetched_at,
            ))

    if not rows:
        return 0

    with get_conn() as conn:
        conn.executemany("""
            INSERT INTO naver_market_prices
              (complex_name, complex_number, pyeong_label, pyeong_type_number,
               cp, trade_type, price_date, avg_price, max_price, min_price, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(complex_number, pyeong_type_number, cp, trade_type, price_date)
            DO UPDATE SET
                avg_price  = excluded.avg_price,
                max_price  = excluded.max_price,
                min_price  = excluded.min_price,
                fetched_at = excluded.fetched_at
        """, rows)
    return len(rows)


# ════════════════════════════════════════════════
# 메인
# ════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="네이버 부동산 시세 자동 수집")
    parser.add_argument("--cookie", default=os.environ.get("NAVER_COOKIE", ""),
                        help="브라우저 Cookie 헤더 값 (또는 NAVER_COOKIE 환경변수)")
    parser.add_argument("--days", type=int, default=365, help="수집 기간(일), 기본 365")
    parser.add_argument("--complex", nargs=2, metavar=("NUMBER", "NAME"),
                        help="단일 단지 수집: --complex 110834 '평택센트럴자이 2단지'")
    args = parser.parse_args()

    init_table()

    session = requests.Session()
    session.headers.update(HEADERS)
    if args.cookie:
        session.headers["Cookie"] = args.cookie
        print("✅ 쿠키 적용됨")
    else:
        print("⚠️  쿠키 없음 — 일부 데이터 제한될 수 있음")

    end_date   = date.today()
    start_date = end_date - timedelta(days=args.days)
    print(f"📅 수집 기간: {start_date} ~ {end_date}\n")

    # 단일 단지 지정
    targets = COMPLEX_MAP.copy()
    if args.complex:
        targets = {args.complex[1]: int(args.complex[0])}

    grand_total = 0
    for complex_name, complex_number in targets.items():
        print(f"📍 {complex_name} (#{complex_number})")

        pyeong_list = get_pyeong_list(session, complex_number)
        if not pyeong_list:
            # 평형 목록 실패 시 기본 1번으로 시도
            pyeong_list = [{"pyeongTypeNo": 1, "pyeongName": "기본"}]

        for pyeong in pyeong_list:
            ptype_no = (
                pyeong.get("pyeongTypeNo")
                or pyeong.get("pyeongTypeNumber")
                or 1
            )
            plabel = str(
                pyeong.get("supplyPyeong")
                or pyeong.get("pyeongName")
                or ptype_no
            )

            print(f"  → {plabel}평 (#{ptype_no}) ...", end=" ", flush=True)
            data = fetch_market_prices(session, complex_number, ptype_no, start_date, end_date)

            if not data.get("isSuccess"):
                print("❌ 실패")
                continue

            n = save_prices(complex_name, complex_number, plabel, ptype_no, data)
            print(f"✅ {n}건")
            grand_total += n
            time.sleep(0.5)   # 과부하 방지

        print()

    print(f"🎉 완료 — 총 {grand_total}건 저장 ({DB_PATH})")


if __name__ == "__main__":
    main()
