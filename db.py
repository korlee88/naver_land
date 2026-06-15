import json
import os
import sqlite3
import requests
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

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

        # 프리셋 저장 테이블
        cur.execute("""
        CREATE TABLE IF NOT EXISTS presets (
            slot    INTEGER PRIMARY KEY,
            name    TEXT NOT NULL,
            params  TEXT NOT NULL
        )
        """)

        # 삭제된 UID 블랙리스트 (재입력 시 복구 방지)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS deleted_uids (
            uid        TEXT PRIMARY KEY,
            deleted_at TEXT NOT NULL,
            reason     TEXT
        )
        """)

        # 최신 상태(마스터)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS listings (
            uid TEXT PRIMARY KEY,
            complex_name TEXT,
            dong TEXT,
            area TEXT,
            trade_type TEXT,
            floor TEXT,
            direction TEXT,
            price_text TEXT,
            confirm_date TEXT,
            provider TEXT,
            office TEXT,
            memo TEXT,
            raw_block TEXT,
            first_seen TEXT,
            last_seen TEXT,
            last_updated TEXT
        )
        """)

        # 변동 히스토리
        # - listings 삭제 시 history도 같이 삭제되도록 ON DELETE CASCADE
        cur.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT,
            seen_at TEXT,
            price_text TEXT,
            confirm_date TEXT,
            provider TEXT,
            office TEXT,
            memo TEXT,
            raw_block TEXT,
            batch_id TEXT,
            FOREIGN KEY(uid) REFERENCES listings(uid) ON DELETE CASCADE
        )
        """)

        # 방문 매물 기록
        cur.execute("""
        CREATE TABLE IF NOT EXISTS visited_properties (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            visit_date   TEXT,
            complex_name TEXT,
            dong         TEXT,
            ho           TEXT,
            area         TEXT,
            unit_type    TEXT,
            direction    TEXT,
            price_text   TEXT,
            options      TEXT,
            memo         TEXT,
            created_at   TEXT
        )
        """)

        # 동별 조망(뻥뷰) 점수
        cur.execute("""
        CREATE TABLE IF NOT EXISTS view_scores (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            complex_name TEXT NOT NULL,
            dong         TEXT NOT NULL,
            grade        TEXT NOT NULL,
            min_floor    INTEGER DEFAULT 0,
            notes        TEXT,
            updated_at   TEXT,
            UNIQUE(complex_name, dong)
        )
        """)

        # 네이버 API 자동 수집 시세 (주간 집계)
        cur.execute("""
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
        cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_nmp_complex_date
        ON naver_market_prices(complex_name, trade_type, price_date)
        """)

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

        # ✅ 혹시 예전 DB에 batch_id 컬럼이 없던 경우 대비 (마이그레이션)
        cur.execute("PRAGMA table_info(price_history)")
        cols = [r["name"] for r in cur.fetchall()]
        if "batch_id" not in cols:
            cur.execute("ALTER TABLE price_history ADD COLUMN batch_id TEXT")

        conn.commit()


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _get_existing(conn: sqlite3.Connection, uid: str) -> Optional[Dict[str, Any]]:
    cur = conn.cursor()
    cur.execute("SELECT * FROM listings WHERE uid = ?", (uid,))
    r = cur.fetchone()
    return dict(r) if r else None


# =========================
# Core Upsert
# =========================
def upsert_listing_and_history(row: Dict[str, Any]) -> Tuple[str, str]:
    
    """
    returns: (result, hist)
      - result: "insert" | "update"
      - hist: "history" | "no_history"
    """
    now      = _now_iso()
    # 복원 시 원본 날짜 보존: row에 seen_at이 있으면 그 값 사용
    seen_at  = row.get("seen_at") or now
    uid = row.get("uid")
    uid = row.get("uid")
    if not uid:
        raise ValueError("row['uid'] is required")

    # ✅ 필수값 방어 (단지명/동/가격/확인매물)
    complex_name = row.get("complex_name")
    dong = row.get("dong")
    price_text = row.get("price_text")
    confirm_date = row.get("confirm_date")

    def _is_blank(v):
        return v is None or str(v).strip() == "" or str(v).strip().lower() == "none"

    if _is_blank(complex_name) or _is_blank(dong):
        raise ValueError(f"invalid complex_name/dong: complex_name={complex_name!r}, dong={dong!r}")

    if _is_blank(price_text):
        raise ValueError(f"invalid price_text: {price_text!r}")

    if _is_blank(confirm_date):
        # confirm_date는 원문에 항상 있다고 했으니 강제
        raise ValueError(f"invalid confirm_date: {confirm_date!r}")

    if not uid:
        raise ValueError("row['uid'] is required")

    batch_id = row.get("batch_id")  # app.py에서 넘어오는 값 그대로 저장

    with get_conn() as conn:
        existing = _get_existing(conn, uid)
        cur = conn.cursor()

        # 삭제된 UID면 재삽입 차단
        cur.execute("SELECT 1 FROM deleted_uids WHERE uid = ?", (uid,))
        if cur.fetchone():
            return "blocked", "no_history"

        if existing is None:
            # INSERT listings
            cur.execute("""
            INSERT INTO listings (
                uid, complex_name, dong, area, trade_type, floor, direction,
                price_text, confirm_date, provider, office, memo, raw_block,
                first_seen, last_seen, last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                uid,
                row.get("complex_name"),
                row.get("dong"),
                row.get("area"),
                row.get("trade_type"),
                row.get("floor"),
                row.get("direction"),
                row.get("price_text"),
                row.get("confirm_date"),
                row.get("provider"),
                row.get("office"),
                row.get("memo"),
                row.get("raw_block"),
                seen_at, seen_at, seen_at
            ))

            # INSERT history (최초 1회)
            cur.execute("""
            INSERT INTO price_history (
                uid, seen_at, price_text, confirm_date, provider, office, memo, raw_block, batch_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                uid, seen_at,
                row.get("price_text"),
                row.get("confirm_date"),
                row.get("provider"),
                row.get("office"),
                row.get("memo"),
                row.get("raw_block"),
                batch_id
            ))

            conn.commit()
            return "insert", "history"

        # 메모 취합: 기존 메모와 새 메모를 중복 없이 합산
        existing_memo = (existing.get("memo") or "").strip()
        new_memo      = (row.get("memo") or "").strip()
        if new_memo and new_memo not in existing_memo:
            merged_memo = (existing_memo + " / " + new_memo) if existing_memo else new_memo
        else:
            merged_memo = existing_memo or new_memo or None

        # UPDATE listings
        cur.execute("""
        UPDATE listings SET
            complex_name = ?,
            dong = ?,
            area = ?,
            trade_type = ?,
            floor = ?,
            direction = ?,
            price_text = ?,
            confirm_date = ?,
            provider = ?,
            office = ?,
            memo = ?,
            raw_block = ?,
            last_seen = ?,
            last_updated = ?
        WHERE uid = ?
        """, (
            row.get("complex_name"),
            row.get("dong"),
            row.get("area"),
            row.get("trade_type"),
            row.get("floor"),
            row.get("direction"),
            row.get("price_text"),
            row.get("confirm_date"),
            row.get("provider"),
            row.get("office"),
            merged_memo,
            row.get("raw_block"),
            seen_at,
            seen_at,
            uid
        ))

        # 변동 감지: price_text 또는 confirm_date 변경 시 history 추가
        changed = (
            (existing.get("price_text") != row.get("price_text")) or
            (existing.get("confirm_date") != row.get("confirm_date"))
        )

        if changed:
            cur.execute("""
            INSERT INTO price_history (
                uid, seen_at, price_text, confirm_date, provider, office, memo, raw_block, batch_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                uid, seen_at,
                row.get("price_text"),
                row.get("confirm_date"),
                row.get("provider"),
                row.get("office"),
                row.get("memo"),
                row.get("raw_block"),
                batch_id
            ))
            conn.commit()
            return "update", "history"

        conn.commit()
        return "update", "no_history"


# =========================
# Read
# =========================
def read_listings() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM listings ORDER BY last_seen DESC")
        return [dict(r) for r in cur.fetchall()]


def read_history(uid: str = None) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        cur = conn.cursor()
        if uid:
            cur.execute("SELECT * FROM price_history WHERE uid = ? ORDER BY seen_at DESC", (uid,))
        else:
            cur.execute("SELECT * FROM price_history ORDER BY seen_at DESC")
        return [dict(r) for r in cur.fetchall()]


# =========================
# Auto Restore from Google Sheets
# =========================
GAS_URL   = "https://script.google.com/macros/s/AKfycbyeOnBIObdLpqfrNlERenUSdKMWXi30EuXYWpuCNbq_pb6Zg0u2HllVIl4RVaUFpGKw7w/exec"
GAS_TOKEN = "MY_SECRET_TOKEN"

def is_db_empty() -> bool:
    """price_history 테이블이 비어있으면 True"""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM price_history")
            return cur.fetchone()[0] == 0
    except Exception:
        return True


def restore_from_sheet(sheet_name: str) -> tuple:
    """구글시트 → DB 복원. 반환: (inserted, updated, skipped)"""
    HEADER_MAP = {
        "날짜": "date", "배치id": "batch_id", "uid": "uid",
        "단지명": "complex_name", "동": "dong", "평형": "area",
        "층": "floor", "방향": "direction", "거래유형": "trade_type",
        "금액": "price_text", "확인매물": "confirm_date",
        "공인중개사": "provider", "부동산": "office", "메모": "memo",
        "raw블록": "raw_block",
    }
    HEADER_MAP_LEGACY = {
        "날짜": "date", "단지명": "complex_name", "동": "dong",
        "평형": "area", "층": "floor", "거래유형": "trade_type",
        "금액": "price_text", "확인매물": "confirm_date", "메모": "memo",
    }

    def _s(v):
        s = str(v).strip() if v not in (None, "") else None
        return None if s in (None, "None", "") else s

    r = requests.get(GAS_URL, params={"token": GAS_TOKEN, "sheet_name": sheet_name}, timeout=60)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    rows = data.get("rows", [])

    inserted = updated = skipped = 0
    col_idx = None
    SKIP_HEADERS = {"날짜", "date", "저장일"}

    for row in rows:
        if not row or not str(row[0]).strip():
            continue
        first = str(row[0]).strip()
        if first.lower() in {h.lower() for h in SKIP_HEADERS}:
            col_idx = {}
            for i, cell in enumerate(row):
                key = str(cell).strip().lower()
                if key in HEADER_MAP:
                    col_idx[HEADER_MAP[key]] = i
                elif key in HEADER_MAP_LEGACY:
                    col_idx[HEADER_MAP_LEGACY[key]] = i
            continue

        def _get(field):
            if col_idx and field in col_idx:
                idx = col_idx[field]
                return _s(row[idx]) if idx < len(row) else None
            fixed = dict(date=0, batch_id=1, uid=2, complex_name=3, dong=4,
                         area=5, floor=6, direction=7, trade_type=8, price_text=9,
                         confirm_date=10, provider=11, office=12, memo=13, raw_block=14)
            idx = fixed.get(field)
            return _s(row[idx]) if idx is not None and idx < len(row) else None

        if not col_idx and len(row) < 15:
            skipped += 1
            continue

        uid = _get("uid"); complex_name = _get("complex_name")
        dong = _get("dong"); price_text = _get("price_text")
        confirm_date = _get("confirm_date")

        if not all([uid, complex_name, dong, price_text, confirm_date]):
            skipped += 1
            continue
        try:
            result, _ = upsert_listing_and_history({
                "uid": uid, "complex_name": complex_name, "dong": dong,
                "area": _get("area"), "trade_type": _get("trade_type"),
                "floor": _get("floor"), "direction": _get("direction"),
                "price_text": price_text, "confirm_date": confirm_date,
                "provider": _get("provider"), "office": _get("office"),
                "memo": _get("memo"), "raw_block": _get("raw_block"),
                "batch_id": _get("batch_id"), "seen_at": _get("date"),
            })
            if result == "insert": inserted += 1
            elif result in ("update", "blocked"): updated += 1
            else: skipped += 1
        except Exception:
            skipped += 1

    return inserted, updated, skipped


def push_to_sheet(sheet_name: str = "기록") -> tuple[int, str]:
    """현재 DB 전체를 Google Sheets로 push. 반환: (ok_cnt, err_msg)"""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT h.seen_at, h.batch_id, l.uid, l.complex_name, l.dong, l.area,
                   l.floor, l.direction, l.trade_type, h.price_text, h.confirm_date,
                   l.provider, l.office, l.memo, l.raw_block
            FROM price_history h JOIN listings l ON l.uid = h.uid
            ORDER BY h.seen_at
        """).fetchall()
    rows_2d = [list(r) for r in rows]
    try:
        resp = requests.post(
            GAS_URL,
            json={"token": GAS_TOKEN, "rows": rows_2d, "sheet_name": sheet_name},
            timeout=60,
        )
        if resp.status_code == 200:
            return (len(rows_2d), "")
        return (0, f"HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        return (0, str(e))


RTMS_TRADE_SHEET  = "RTMS매매"
RTMS_JEONSE_SHEET = "RTMS전월세"


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
                    json={"token": GAS_TOKEN, "rows": rows, "sheet_name": sheet_name},
                    timeout=120,
                )
            except requests.exceptions.RequestException as e:
                return False, f"[{sheet_name}] 요청 실패: {e}"
            if resp.status_code != 200:
                return False, f"[{sheet_name}] HTTP {resp.status_code}: {resp.text[:200]}"
            try:
                data = resp.json()
            except ValueError:
                return False, f"[{sheet_name}] JSON 응답 아님: {resp.text[:200]}"
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
        r = requests.get(GAS_URL, params={"token": GAS_TOKEN, "sheet_name": sheet_name}, timeout=60)
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


# =========================
# Visited Properties
# =========================
# =========================
# View Scores (동별 조망)
# =========================
GRADE_SCORE = {"S": 25, "A": 15, "B": 5, "C": 0}

def upsert_view_score(complex_name: str, dong: str, grade: str,
                      min_floor: int = 0, notes: str = "") -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO view_scores (complex_name, dong, grade, min_floor, notes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(complex_name, dong) DO UPDATE SET
                grade=excluded.grade, min_floor=excluded.min_floor,
                notes=excluded.notes, updated_at=excluded.updated_at
        """, (complex_name, dong, grade, min_floor, notes, _now_iso()))
        conn.commit()


def load_view_scores() -> Dict[tuple, Dict]:
    """반환: {(complex_name_lower, dong): {"grade": .., "min_floor": .., "score": ..}}"""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM view_scores")
        rows = [dict(r) for r in cur.fetchall()]
    result = {}
    for r in rows:
        key = (r["complex_name"].strip().lower(), str(r["dong"]).strip())
        result[key] = {
            "grade":     r["grade"],
            "min_floor": r["min_floor"] or 0,
            "score":     GRADE_SCORE.get(r["grade"], 0),
            "notes":     r["notes"] or "",
        }
    return result


def read_view_scores() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM view_scores ORDER BY complex_name, dong")
        return [dict(r) for r in cur.fetchall()]


def delete_view_score(row_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM view_scores WHERE id = ?", (row_id,))
        conn.commit()


def insert_visited(row: Dict[str, Any]) -> int:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO visited_properties
              (visit_date, complex_name, dong, ho, area, unit_type,
               direction, price_text, options, memo, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            row.get("visit_date"), row.get("complex_name"), row.get("dong"),
            row.get("ho"), row.get("area"), row.get("unit_type"),
            row.get("direction"), row.get("price_text"),
            json.dumps(row.get("options", []), ensure_ascii=False),
            row.get("memo"), _now_iso(),
        ))
        conn.commit()
        return cur.lastrowid


def read_visited() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM visited_properties ORDER BY visit_date DESC, id DESC")
        rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        try:
            r["options"] = json.loads(r["options"] or "[]")
        except Exception:
            r["options"] = []
    return rows


def delete_visited(row_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM visited_properties WHERE id = ?", (row_id,))
        conn.commit()


# =========================
# Delete
# =========================
def delete_history_by_batch(batch_id: str) -> int:
    """price_history에서 batch_id로 삭제. 삭제된 행 수 반환"""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM price_history WHERE batch_id = ?", (batch_id,))
        deleted = cur.rowcount
        conn.commit()
        return deleted


def delete_listing_by_uid(uid: str, reason: str = "") -> int:
    """
    listings + price_history에서 uid로 완전 삭제.
    삭제된 uid는 deleted_uids 블랙리스트에 기록해 재입력 시 복구 방지.
    """
    with get_conn() as conn:
        cur = conn.cursor()

        # history 먼저 카운트
        cur.execute("SELECT COUNT(*) AS cnt FROM price_history WHERE uid = ?", (uid,))
        hist_cnt = int(cur.fetchone()["cnt"])

        # listings 삭제 (CASCADE로 history도 자동 삭제됨)
        cur.execute("DELETE FROM listings WHERE uid = ?", (uid,))
        list_cnt = cur.rowcount

        # 블랙리스트에 등록
        cur.execute("""
            INSERT OR REPLACE INTO deleted_uids (uid, deleted_at, reason)
            VALUES (?, ?, ?)
        """, (uid, _now_iso(), reason))

        conn.commit()
        return hist_cnt + list_cnt


def delete_history_by_ids(ids: List[int]) -> int:
    """price_history에서 id 목록 삭제 + 해당 uid 블랙리스트 등록 (재입력 방지)"""
    if not ids:
        return 0

    placeholders = ",".join(["?"] * len(ids))
    with get_conn() as conn:
        cur = conn.cursor()

        # 삭제할 uid 먼저 수집
        cur.execute(f"SELECT DISTINCT uid FROM price_history WHERE id IN ({placeholders})", ids)
        uids = [r["uid"] for r in cur.fetchall()]

        # price_history 삭제
        cur.execute(f"DELETE FROM price_history WHERE id IN ({placeholders})", ids)
        deleted = cur.rowcount

        # uid별 처리: 블랙리스트 등록 + 남은 history 없으면 listings도 삭제
        for uid in uids:
            cur.execute("SELECT COUNT(*) AS cnt FROM price_history WHERE uid = ?", (uid,))
            remaining = int(cur.fetchone()["cnt"])
            if remaining == 0:
                cur.execute("DELETE FROM listings WHERE uid = ?", (uid,))
            cur.execute("""
                INSERT OR REPLACE INTO deleted_uids (uid, deleted_at, reason)
                VALUES (?, ?, ?)
            """, (uid, _now_iso(), "RAW 관리에서 삭제"))

        conn.commit()
        return deleted


# =========================
# Presets
# =========================
def load_presets() -> List[Dict[str, Any]]:
    """슬롯 0~2의 프리셋을 DB에서 로드. 없는 슬롯은 기본값 반환."""
    defaults = [
        {"name": f"프리셋 {i+1}", "params": None} for i in range(3)
    ]
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT slot, name, params FROM presets WHERE slot IN (0,1,2)")
        for row in cur.fetchall():
            slot = row["slot"]
            defaults[slot] = {
                "name":   row["name"],
                "params": json.loads(row["params"]),
            }
    return defaults


def save_preset(slot: int, name: str, params: Dict[str, Any]) -> None:
    """슬롯에 프리셋 저장 (upsert)."""
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO presets (slot, name, params)
            VALUES (?, ?, ?)
            ON CONFLICT(slot) DO UPDATE SET name=excluded.name, params=excluded.params
        """, (slot, name, json.dumps(params)))
        conn.commit()
