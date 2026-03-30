import json
import sqlite3
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

DB_PATH = "naver_land.db"


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
    now = _now_iso()
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
                now, now, now
            ))

            # INSERT history (최초 1회)
            cur.execute("""
            INSERT INTO price_history (
                uid, seen_at, price_text, confirm_date, provider, office, memo, raw_block, batch_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                uid, now,
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
            now,
            now,
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
                uid, now,
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
# Visited Properties
# =========================
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
