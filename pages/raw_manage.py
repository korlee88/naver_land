# pages/raw_manage.py
import streamlit as st
import pandas as pd
import requests
import io
from datetime import datetime
from db import init_db, read_history, read_listings, delete_history_by_ids, upsert_listing_and_history

from utils_style import inject_korean_font
from utils_auth import require_auth

GAS_URL   = "https://script.google.com/macros/s/AKfycbyeOnBIObdLpqfrNlERenUSdKMWXi30EuXYWpuCNbq_pb6Zg0u2HllVIl4RVaUFpGKw7w/exec"
GAS_TOKEN = "MY_SECRET_TOKEN"


def _push_to_sheet(rows_2d: list[list], sheet_name: str) -> tuple[int, int, str]:
    ok = fail = 0
    last = ""
    for i in range(0, len(rows_2d), 200):
        chunk = rows_2d[i:i + 200]
        try:
            r = requests.post(
                GAS_URL,
                json={"token": GAS_TOKEN, "rows": chunk, "sheet_name": sheet_name},
                timeout=30,
            )
            r.raise_for_status()
            last = r.text
            ok   += len(chunk) if str(last).upper().startswith("OK") else 0
            fail += 0          if str(last).upper().startswith("OK") else len(chunk)
        except Exception as e:
            fail += len(chunk)
            last = str(e)
    return ok, fail, last


def _fetch_from_sheet(sheet_name: str) -> list[list]:
    r = requests.get(
        GAS_URL,
        params={"token": GAS_TOKEN, "sheet_name": sheet_name},
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    return data.get("rows", [])


def _restore_from_sheet(sheet_name: str) -> tuple[int, int, int]:
    """구글시트 탭 → 로컬 DB 복원. 반환: (inserted, updated, skipped)"""
    COL = dict(date=0, batch_id=1, uid=2, complex_name=3, dong=4, area=5,
               floor=6, direction=7, trade_type=8, price_text=9,
               confirm_date=10, provider=11, office=12, memo=13, raw_block=14)

    def _s(v):
        s = str(v).strip() if v not in (None, "") else None
        return None if s in (None, "None", "") else s

    rows = _fetch_from_sheet(sheet_name)
    inserted = updated = skipped = 0

    for row in rows:
        if len(row) < 15:
            skipped += 1
            continue
        if str(row[COL["date"]]).strip().lower() in ("날짜", "date", "저장일"):
            continue
        uid          = _s(row[COL["uid"]])
        complex_name = _s(row[COL["complex_name"]])
        dong         = _s(row[COL["dong"]])
        price_text   = _s(row[COL["price_text"]])
        confirm_date = _s(row[COL["confirm_date"]])
        if not all([uid, complex_name, dong, price_text, confirm_date]):
            skipped += 1
            continue
        try:
            result, _ = upsert_listing_and_history({
                "uid": uid, "complex_name": complex_name, "dong": dong,
                "area": _s(row[COL["area"]]), "trade_type": _s(row[COL["trade_type"]]),
                "floor": _s(row[COL["floor"]]), "direction": _s(row[COL["direction"]]),
                "price_text": price_text, "confirm_date": confirm_date,
                "provider": _s(row[COL["provider"]]), "office": _s(row[COL["office"]]),
                "memo": _s(row[COL["memo"]]), "raw_block": _s(row[COL["raw_block"]]),
                "batch_id": _s(row[COL["batch_id"]]),
            })
            if result == "insert":
                inserted += 1
            elif result in ("update", "blocked"):
                updated += 1
            else:
                skipped += 1
        except Exception:
            skipped += 1

    return inserted, updated, skipped


inject_korean_font()
require_auth()
init_db()

st.title("🧹 RAW 데이터 관리")

# ── 구글시트 백업 / 복원 ────────────────────────────────────────────────────
with st.expander("☁️ 구글시트 백업 / 복원", expanded=False):
    tab_backup, tab_restore = st.tabs(["📤 백업 (DB → 구글시트)", "📥 복원 (구글시트 → DB)"])

    # ── 백업 탭 ──
    with tab_backup:
        today_str = datetime.now().strftime("%y%m%d")
        default_sheet = f"매물등록 {today_str}"
        backup_sheet = st.text_input("저장할 시트명", value=default_sheet, key="backup_sheet")
        st.caption("구글시트에 새 탭이 생성됩니다. 기존 탭과 이름이 같으면 이어서 추가됩니다.")

        if st.button("📤 구글시트로 백업", type="primary", use_container_width=True):
            hist_all = read_history()
            lst_all  = read_listings()
            if not hist_all:
                st.warning("백업할 데이터가 없습니다.")
            else:
                df_h = pd.DataFrame(hist_all)
                df_l = pd.DataFrame(lst_all)[["uid","complex_name","dong","area","trade_type","floor","direction"]]
                df_b = df_h.merge(df_l, on="uid", how="left")

                COLS = ["seen_at","complex_name","dong","area","floor","trade_type",
                        "price_text","confirm_date","memo"]
                header = ["날짜","단지명","동","평형","층","거래유형","금액","확인매물","메모"]
                cols   = [c for c in COLS if c in df_b.columns]
                rows_2d = [header] + df_b[cols].fillna("").astype(str).values.tolist()

                with st.spinner("업로드 중…"):
                    ok, fail, last = _push_to_sheet(rows_2d, backup_sheet)
                if fail == 0:
                    st.success(f"✅ {ok}건 백업 완료 → **{backup_sheet}**")
                else:
                    st.warning(f"성공 {ok} / 실패 {fail} (응답: {last})")

    # ── 복원 탭 ──
    with tab_restore:
        restore_sheet = st.text_input("복원할 시트명", value="기록", key="restore_sheet")
        st.caption("시트명을 입력하고 복원하거나, 데이터를 CSV로 다운로드할 수 있습니다.")

        col_restore, col_download = st.columns(2)

        with col_restore:
            if st.button("📥 DB로 복원", type="primary", use_container_width=True):
                with st.spinner(f"'{restore_sheet}' 시트에서 불러오는 중…"):
                    try:
                        ins, upd, skip = _restore_from_sheet(restore_sheet)
                        st.success(f"복원 완료 — 신규 **{ins}건** / 업데이트 **{upd}건** / 스킵 {skip}건")
                        st.cache_data.clear()
                    except Exception as e:
                        st.error(f"복원 실패: {e}")

        with col_download:
            if st.button("⬇️ CSV 다운로드", use_container_width=True):
                with st.spinner(f"'{restore_sheet}' 시트 읽는 중…"):
                    try:
                        rows = _fetch_from_sheet(restore_sheet)
                        if rows:
                            df_dl = pd.DataFrame(rows[1:], columns=rows[0]) if rows else pd.DataFrame()
                            csv = df_dl.to_csv(index=False).encode("utf-8-sig")
                            st.download_button(
                                label="💾 CSV 저장",
                                data=csv,
                                file_name=f"{restore_sheet}_{today_str}.csv",
                                mime="text/csv",
                                use_container_width=True,
                            )
                        else:
                            st.warning("데이터가 없습니다.")
                    except Exception as e:
                        st.error(f"읽기 실패: {e}")

st.divider()

# ── 데이터 로드 (price_history + listings 조인) ──
hist = read_history()
lst  = read_listings()
df   = pd.DataFrame(hist) if hist else pd.DataFrame()

if df.empty:
    st.info("price_history 데이터가 없습니다.")
    st.stop()

if "id" not in df.columns:
    st.error("id 컬럼이 없어 삭제 기능을 사용할 수 없습니다.")
    st.stop()

# listings에서 단지명·동·층·호수 가져오기
if lst:
    df_lst = pd.DataFrame(lst)[["uid","complex_name","dong","floor","area","trade_type"]]
    df = df.merge(df_lst, on="uid", how="left")

# seen_at → 날짜 문자열 (YYYY-MM-DD)
if "seen_at" in df.columns:
    df["seen_at"] = pd.to_datetime(df["seen_at"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df.sort_values("seen_at", ascending=False)

# ── 필터 ──────────────────────────────────────
f1, f2, f3 = st.columns([2, 2, 3])

if "complex_name" in df.columns:
    complex_opts = sorted(df["complex_name"].dropna().astype(str).unique().tolist())
    sel_complex  = f1.multiselect("단지 (복수 선택 가능)", complex_opts, default=complex_opts)
else:
    sel_complex = []

if "dong" in df.columns:
    dong_opts = ["전체"] + sorted(df["dong"].dropna().astype(str).unique().tolist())
    sel_dong  = f2.selectbox("동", dong_opts)
else:
    sel_dong = "전체"

keyword = f3.text_input("키워드 검색", placeholder="메모 / 금액 등")

# 필터 적용
view = df.copy()
if sel_complex and "complex_name" in view.columns:
    view = view[view["complex_name"].astype(str).isin(sel_complex)]
if sel_dong != "전체" and "dong" in view.columns:
    view = view[view["dong"].astype(str) == sel_dong]
if keyword:
    mask = pd.Series(False, index=view.index)
    for col in view.select_dtypes(include="object").columns:
        mask |= view[col].str.contains(keyword, na=False, case=False)
    view = view[mask]

st.caption(f"총 {len(df):,}건 중 필터 결과: **{len(view):,}건**")

# ── 표시 컬럼 ──
SHOW_COLS = [c for c in [
    "id", "seen_at", "complex_name", "dong", "area", "floor", "price_text", "memo"
] if c in view.columns]

show_df = view[SHOW_COLS].copy().reset_index(drop=True)

st.caption("💡 행 클릭으로 선택 · Shift+클릭으로 범위 선택 · Ctrl+클릭으로 추가 선택")

event = st.dataframe(
    show_df,
    use_container_width=True,
    height=600,
    column_config={
        "seen_at":      st.column_config.TextColumn("날짜",   width="small"),
        "complex_name": st.column_config.TextColumn("단지명", width="medium"),
        "dong":         st.column_config.TextColumn("동",     width="small"),
        "area":         st.column_config.TextColumn("평형",   width="small"),
        "floor":        st.column_config.TextColumn("층",     width="small"),
        "price_text":   st.column_config.TextColumn("금액",   width="small"),
        "memo":         st.column_config.TextColumn("메모"),
        "id":           st.column_config.NumberColumn("ID",   width="small"),
    },
    hide_index=True,
    on_select="rerun",
    selection_mode="multi-row",
)

selected_rows = event.selection.rows if event and event.selection else []
selected_ids  = show_df.iloc[selected_rows]["id"].tolist() if selected_rows else []

# ── 삭제 실행 ──
d1, d2, d3 = st.columns([1, 1, 4])
d1.metric("선택", f"{len(selected_ids)}건")
confirm = d2.checkbox("삭제 확인")

if d3.button("🗑️ 선택 항목 삭제", type="primary",
             disabled=(not confirm or len(selected_ids) == 0)):
    deleted = delete_history_by_ids(selected_ids)
    st.success(f"{deleted}건 삭제 완료")
    st.rerun()
