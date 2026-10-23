import os
import sqlite3
import requests
from datetime import datetime
# DB_PATH 환경변수 우선. 기본값은 /tmp (Streamlit Cloud 등 ephemeral 환경)
# 로컬 영구저장은 DB_PATH=./naver_land.db 등으로 지정
DB_PATH = os.environ.get("DB_PATH", "/tmp/naver_land.db")


# =========================
# Connection / Init
# =========================
def get_conn() -> sqlite3.Connection:
    """
    Streamlit에서 여러 rerun이 발생해도 안전하게 쓰기 위해
    check_same_thread=False 권장.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # SQLite는 foreign key 기본 OFF라서 매번 ON 필요
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    with get_conn() as conn:
        cur = conn.cursor()


        # 국토교통부 실거래가 (월별 거래)
        cur.execute("""
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
        cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_rtms_apt_date
        ON rtms_transactions(apt_name, deal_year, deal_month)
        """)

        # KOSIS(국가통계포털) 인구·주택·경제 통계
        cur.execute("""
        CREATE TABLE IF NOT EXISTS kosis_stats (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            category    TEXT    NOT NULL,
            tbl_id      TEXT    NOT NULL,
            region_name TEXT    NOT NULL,
            sub_label   TEXT,
            item_name   TEXT,
            unit_name   TEXT,
            prd_de      TEXT    NOT NULL,
            value       REAL,
            fetched_at  TEXT    NOT NULL,
            UNIQUE(category, tbl_id, region_name, sub_label, item_name, prd_de)
        )
        """)
        cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_kosis_cat_region
        ON kosis_stats(category, region_name, prd_de)
        """)

        # 한국은행 ECOS 금리·경제통계. 전국 단일 시계열이라 KOSIS와 달리 지역 컬럼이 없다.
        cur.execute("""
        CREATE TABLE IF NOT EXISTS ecos_stats (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            stat_code   TEXT    NOT NULL,
            stat_name   TEXT,
            item_name   TEXT,
            unit_name   TEXT,
            period      TEXT    NOT NULL,
            value       REAL,
            fetched_at  TEXT    NOT NULL,
            UNIQUE(stat_code, item_name, period)
        )
        """)
        cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_ecos_code_period
        ON ecos_stats(stat_code, period)
        """)


        conn.commit()


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# =========================
# Read
# =========================
# =========================
# Auto Restore from Google Sheets
# =========================
GAS_URL   = "https://script.google.com/macros/s/AKfycbxSoKgcyvWAE6TotwZsLGwTPDmYoJptMcLJTvv_7SnsBnCNwN7SfSJRVf7P_HgOAZ1g0Q/exec"
GAS_TOKEN = "MY_SECRET_TOKEN"

# "부동산" 시트(GAS_URL이 바인딩된 원래 스프레드시트)가 실거래가·매물 기록(raw "기록" 탭)만으로
# 이미 구글시트 셀 한도(통합문서당 1천만 셀)에 근접해 있다 — 탭을 나눠도 한도는 스프레드시트
# 파일 전체 합산이라 소용없어, KOSIS·RTMS 백업은 별도 스프레드시트에 함께 저장한다.
# Code.gs가 spreadsheet_id를 받으면 그 시트를 연다.
BACKUP_SHEET_ID  = "1pC4M1PIQT_aHNAgctu1p9gO1-t1aUQnuERsTaCaWAiY"
BACKUP_SHEET_URL = f"https://docs.google.com/spreadsheets/d/{BACKUP_SHEET_ID}/edit"


RTMS_TRADE_SHEET  = "RTMS매매"
RTMS_JEONSE_SHEET = "RTMS전월세"
RTMS_SHEET_ID     = BACKUP_SHEET_ID


def is_rtms_empty() -> bool:
    """rtms_transactions 테이블이 비어있으면 True"""
    try:
        with get_conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM rtms_transactions").fetchone()[0] == 0
    except Exception:
        return True


def push_rtms_to_sheet() -> tuple[int, int, str]:
    """rtms_transactions + rtms_jeonse → 구글시트 백업. 반환: (매매건수, 전월세건수, 오류메시지)"""
    try:
        with get_conn() as conn:
            trade_rows = [list(r) for r in conn.execute("""
                SELECT lawd_cd, deal_year, deal_month, deal_day,
                       apt_name, dong, floor, area, price_man,
                       build_year, road_name, cancel_yn, fetched_at
                FROM rtms_transactions ORDER BY deal_year, deal_month
            """).fetchall()]
            jeonse_rows = [list(r) for r in conn.execute("""
                SELECT lawd_cd, deal_year, deal_month, apt_name,
                       area, deposit_man, monthly_rent, contract_type, fetched_at
                FROM rtms_jeonse ORDER BY deal_year, deal_month
            """).fetchall()]

        def _push(rows, sheet_name) -> tuple[bool, str]:
            if not rows:
                return True, ""
            try:
                resp = requests.post(
                    GAS_URL,
                    json={"token": GAS_TOKEN, "rows": rows, "sheet_name": sheet_name,
                          "spreadsheet_id": RTMS_SHEET_ID},
                    timeout=300,
                )
            except requests.exceptions.RequestException as e:
                return False, f"[{sheet_name}] 요청 실패: {e}"
            if resp.status_code != 200:
                return False, f"[{sheet_name}] HTTP {resp.status_code}: {resp.text[:200]}"
            try:
                data = resp.json()
            except ValueError:
                # GAS가 성공 시 JSON이 아닌 평문 "OK"를 반환하는 경우
                text = resp.text.strip()
                if text.upper() == "OK":
                    return True, ""
                return False, f"[{sheet_name}] 비JSON 응답: {resp.text[:200]}"
            if isinstance(data, dict) and data.get("error"):
                return False, f"[{sheet_name}] {data['error']}"
            return True, ""

        ok1, err1 = _push(trade_rows,  RTMS_TRADE_SHEET)
        ok2, err2 = _push(jeonse_rows, RTMS_JEONSE_SHEET)

        if ok1 and ok2:
            return (len(trade_rows), len(jeonse_rows), "")
        return (0, 0, " / ".join(e for e in (err1, err2) if e))
    except Exception as e:
        return (0, 0, str(e))


def restore_rtms_from_sheet() -> tuple[int, int]:
    """구글시트 → rtms_transactions + rtms_jeonse 복원. 반환: (매매건수, 전월세건수)"""
    fetched_at = datetime.now().isoformat(timespec="seconds")

    def _fetch_rows(sheet_name):
        r = requests.get(GAS_URL, params={"token": GAS_TOKEN, "sheet_name": sheet_name,
                                           "spreadsheet_id": RTMS_SHEET_ID}, timeout=300)
        r.raise_for_status()
        return r.json().get("rows", [])

    def _is_header(row):
        return row and str(row[0]).strip().lower() in {"lawd_cd", "법정동코드", "날짜", "date"}

    trade_saved = jeonse_saved = 0

    # ── 매매 복원 ──
    try:
        rows = _fetch_rows(RTMS_TRADE_SHEET)
        insert_rows = []
        for row in rows:
            if not row or _is_header(row):
                continue
            try:
                insert_rows.append((
                    str(row[0]),          # lawd_cd
                    int(row[1]),          # deal_year
                    int(row[2]),          # deal_month
                    int(row[3]) if row[3] else 1,  # deal_day
                    str(row[4]),          # apt_name
                    str(row[5]) if row[5] else None,  # dong
                    int(row[6]) if row[6] else None,  # floor
                    float(row[7]) if row[7] else None,  # area
                    int(row[8]),          # price_man
                    int(row[9]) if row[9] else None,  # build_year
                    str(row[10]) if row[10] else None,  # road_name
                    str(row[11]) if row[11] else None,  # cancel_yn
                    str(row[12]) if len(row) > 12 and row[12] else fetched_at,
                ))
            except (IndexError, ValueError, TypeError):
                continue
        if insert_rows:
            with get_conn() as conn:
                cur = conn.executemany("""
                    INSERT OR IGNORE INTO rtms_transactions
                      (lawd_cd, deal_year, deal_month, deal_day, apt_name, dong, floor, area,
                       price_man, build_year, road_name, cancel_yn, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, insert_rows)
                trade_saved = cur.rowcount
    except Exception:
        pass

    # ── 전월세 복원 ──
    try:
        rows = _fetch_rows(RTMS_JEONSE_SHEET)
        insert_rows = []
        for row in rows:
            if not row or _is_header(row):
                continue
            try:
                insert_rows.append((
                    str(row[0]),          # lawd_cd
                    int(row[1]),          # deal_year
                    int(row[2]),          # deal_month
                    str(row[3]),          # apt_name
                    float(row[4]) if row[4] else None,  # area
                    int(row[5]) if row[5] else None,    # deposit_man
                    int(row[6]) if row[6] else 0,       # monthly_rent
                    str(row[7]) if row[7] else None,    # contract_type
                    str(row[8]) if len(row) > 8 and row[8] else fetched_at,
                ))
            except (IndexError, ValueError, TypeError):
                continue
        if insert_rows:
            with get_conn() as conn:
                cur = conn.executemany("""
                    INSERT OR IGNORE INTO rtms_jeonse
                      (lawd_cd, deal_year, deal_month, apt_name, area,
                       deposit_man, monthly_rent, contract_type, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, insert_rows)
                jeonse_saved = cur.rowcount
    except Exception:
        pass

    return trade_saved, jeonse_saved


KOSIS_SHEET    = "KOSIS통계"
KOSIS_SHEET_ID = BACKUP_SHEET_ID


def is_kosis_empty() -> bool:
    """kosis_stats 테이블이 비어있으면 True"""
    try:
        with get_conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM kosis_stats").fetchone()[0] == 0
    except Exception:
        return True


def push_kosis_to_sheet() -> tuple[int, str]:
    """kosis_stats → 구글시트 백업. 반환: (건수, 오류메시지)

    GAS(Code.gs)는 성공 시 평문 "OK"를, 실패 시에도 HTTP 200과 함께 "Unauthorized"/
    "No rows"/"ERR: ..." 같은 본문을 돌려준다(Apps Script는 doPost에 커스텀 상태코드를
    못 준다) — status_code만 보고 200이면 성공으로 치면 토큰이 어긋나거나 GAS 쪽에서
    예외가 나도 "백업 완료"로 오인하게 된다. 본문까지 확인해야 실제 저장 여부를 안다.
    """
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT category, tbl_id, region_name, sub_label, item_name, unit_name, prd_de, value, fetched_at
            FROM kosis_stats ORDER BY category, region_name, prd_de
        """).fetchall()
    rows_2d = [list(r) for r in rows]
    if not rows_2d:
        return 0, ""
    try:
        resp = requests.post(
            GAS_URL,
            json={"token": GAS_TOKEN, "rows": rows_2d, "sheet_name": KOSIS_SHEET,
                  "spreadsheet_id": KOSIS_SHEET_ID},
            timeout=300,
        )
    except Exception as e:
        return 0, str(e)
    if resp.status_code != 200:
        return 0, f"HTTP {resp.status_code}: {resp.text[:200]}"
    try:
        data = resp.json()
    except ValueError:
        text = resp.text.strip()
        if text.upper() == "OK":
            return len(rows_2d), ""
        return 0, f"응답: {resp.text[:200]}"
    if isinstance(data, dict) and data.get("error"):
        return 0, data["error"]
    return 0, f"예상치 못한 응답: {str(data)[:200]}"


def restore_kosis_from_sheet() -> tuple[int, str]:
    """구글시트 → kosis_stats 복원. 반환: (복원 건수, 오류메시지)

    GAS doGet은 시트 탭이 아예 없으면 {"error": "Sheet not found"}를 돌려주는데,
    이걸 안 걸러내면 .get("rows", [])가 빈 리스트로 넘어가 "시트가 비어있다"와
    "탭 자체가 없다"를 구분 못 하게 된다.
    """
    try:
        r = requests.get(GAS_URL, params={"token": GAS_TOKEN, "sheet_name": KOSIS_SHEET,
                                           "spreadsheet_id": KOSIS_SHEET_ID}, timeout=300)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return 0, str(e)
    if isinstance(data, dict) and data.get("error"):
        return 0, data["error"]
    rows = data.get("rows", []) if isinstance(data, dict) else []

    fetched_at = _now_iso()
    insert_rows = []
    for row in rows:
        if not row or len(row) < 8:
            continue
        if str(row[0]).strip().lower() == "category":
            continue
        try:
            value = float(row[7]) if row[7] not in (None, "") else None
            insert_rows.append((
                str(row[0]), str(row[1]), str(row[2]),
                str(row[3]) if row[3] not in (None, "") else None,
                str(row[4]) if row[4] not in (None, "") else None,
                str(row[5]) if row[5] not in (None, "") else None,
                str(row[6]), value,
                str(row[8]) if len(row) > 8 and row[8] else fetched_at,
            ))
        except (ValueError, TypeError, IndexError):
            continue
    if not insert_rows:
        return 0, ""

    with get_conn() as conn:
        cur = conn.executemany("""
            INSERT OR IGNORE INTO kosis_stats
              (category, tbl_id, region_name, sub_label, item_name, unit_name, prd_de, value, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, insert_rows)
        conn.commit()
        return cur.rowcount, ""


ECOS_SHEET = "ECOS금리"


def is_ecos_empty() -> bool:
    """ecos_stats 테이블이 비어있으면 True"""
    try:
        with get_conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM ecos_stats").fetchone()[0] == 0
    except Exception:
        return True


def push_ecos_to_sheet() -> tuple[int, str]:
    """ecos_stats → 구글시트 백업. 반환: (건수, 오류메시지)

    GAS는 실패해도 HTTP 200에 평문 본문을 돌려주므로 본문까지 확인해야 한다
    (push_kosis_to_sheet와 같은 이유).
    """
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT stat_code, stat_name, item_name, unit_name, period, value, fetched_at
            FROM ecos_stats ORDER BY stat_code, item_name, period
        """).fetchall()
    rows_2d = [list(r) for r in rows]
    if not rows_2d:
        return 0, ""
    try:
        resp = requests.post(
            GAS_URL,
            json={"token": GAS_TOKEN, "rows": rows_2d, "sheet_name": ECOS_SHEET,
                  "spreadsheet_id": BACKUP_SHEET_ID},
            timeout=300,
        )
    except Exception as e:
        return 0, str(e)
    if resp.status_code != 200:
        return 0, f"HTTP {resp.status_code}: {resp.text[:200]}"
    try:
        data = resp.json()
    except ValueError:
        text = resp.text.strip()
        if text.upper() == "OK":
            return len(rows_2d), ""
        return 0, f"응답: {resp.text[:200]}"
    if isinstance(data, dict) and data.get("error"):
        return 0, data["error"]
    return 0, f"예상치 못한 응답: {str(data)[:200]}"


def restore_ecos_from_sheet() -> tuple[int, str]:
    """구글시트 → ecos_stats 복원. 반환: (복원 건수, 오류메시지)"""
    try:
        r = requests.get(GAS_URL, params={"token": GAS_TOKEN, "sheet_name": ECOS_SHEET,
                                          "spreadsheet_id": BACKUP_SHEET_ID}, timeout=300)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return 0, str(e)
    if isinstance(data, dict) and data.get("error"):
        return 0, data["error"]
    rows = data.get("rows", []) if isinstance(data, dict) else []

    fetched_at = _now_iso()
    insert_rows = []
    for row in rows:
        if not row or len(row) < 6:
            continue
        if str(row[0]).strip().lower() in ("stat_code", "통계표코드"):
            continue
        try:
            value = float(row[5]) if row[5] not in (None, "") else None
        except (TypeError, ValueError):
            continue
        insert_rows.append((
            str(row[0]),
            str(row[1]) if row[1] not in (None, "") else None,
            str(row[2]) if row[2] not in (None, "") else None,
            str(row[3]) if row[3] not in (None, "") else None,
            str(row[4]), value,
            str(row[6]) if len(row) > 6 and row[6] else fetched_at,
        ))
    if not insert_rows:
        return 0, ""

    with get_conn() as conn:
        cur = conn.executemany("""
            INSERT OR IGNORE INTO ecos_stats
              (stat_code, stat_name, item_name, unit_name, period, value, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, insert_rows)
        conn.commit()
        return cur.rowcount, ""


# 백업 스프레드시트 셀 사용량 — 통합문서당 1천만 셀 한도를 넘기면 백업이 통째로 실패한다
# (2026-09 실제 발생: "부동산" 시트가 한도에 닿아 RTMS·KOSIS 백업이 모두 실패).
# 백업 버튼을 누른 뒤에야 알게 되지 않도록 각 수집 페이지가 평소에 이 값을 표시한다.
SHEET_CELL_LIMIT = 10_000_000
_BACKUP_TABLES = [
    # (표시명, 테이블, 백업 컬럼 수 — push_*_to_sheet()의 SELECT 컬럼 수와 반드시 일치)
    ("RTMS 매매",   "rtms_transactions", 13),
    ("RTMS 전월세", "rtms_jeonse",        9),
    ("KOSIS 통계",  "kosis_stats",        9),
    ("ECOS 금리",   "ecos_stats",         7),
]


def backup_sheet_usage() -> dict:
    """백업 스프레드시트의 예상 셀 사용량.

    반환: {"cells": 예상 셀 수, "limit": 한도, "ratio": 0~1, "rows": [(표시명, 행수, 셀수), ...]}

    시트를 조회하지 않고 DB 행수 × 백업 컬럼 수로 계산한다 — 백업은 매번 DB 전체
    스냅샷으로 덮어쓰므로, 이 값이 곧 다음 백업 직후 시트가 차지할 셀 수다.
    """
    detail, total = [], 0
    with get_conn() as conn:
        for label, table, ncol in _BACKUP_TABLES:
            try:
                n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except Exception:
                n = 0   # 아직 생성 전인 테이블 (첫 수집 이전)
            total += n * ncol
            detail.append((label, n, n * ncol))
    return {
        "cells": total,
        "limit": SHEET_CELL_LIMIT,
        "ratio": total / SHEET_CELL_LIMIT,
        "rows": detail,
    }


# =========================
# View Scores (동별 조망)
# =========================

# =========================
# Presets
# =========================
