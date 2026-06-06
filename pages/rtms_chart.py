"""
pages/rtms_chart.py — 국토부 실거래가 기반 가격 추이 차트
"""
import os
import sqlite3
from datetime import date

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from utils_style import inject_korean_font

inject_korean_font()

DB_PATH        = os.environ.get("DB_PATH", "/tmp/naver_land.db")
MY_APT_KEYWORD = "센트럴자이"
MY_APT_SUFFIX  = "2단지"
MY_PRICE       = 3.20  # 매수가 (억)

PALETTE = [
    "#4C72B0","#DD8452","#55A868","#C44E52",
    "#8172B2","#937860","#DA8BC3","#8C8C8C",
    "#CCB974","#64B5CD",
]

LAWD_NAMES: dict[str, str] = {
    "41220": "경기 평택시",
    "43113": "충북 청주시 흥덕구",
    "43114": "충북 청주시 청원구",
}


def _hex_to_rgba(hex_color: str, alpha: float = 0.12) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _is_my_apt(name: str) -> bool:
    return MY_APT_KEYWORD in name and MY_APT_SUFFIX in name


# ── 데이터 로드 ────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_data() -> pd.DataFrame:
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        df = pd.read_sql("""
            SELECT lawd_cd, apt_name, deal_year, deal_month, deal_day,
                   area, floor, price_man, cancel_yn
            FROM rtms_transactions
            ORDER BY deal_year, deal_month, deal_day
        """, conn)
        conn.close()
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return df
    df = df[df["cancel_yn"].isna() | (df["cancel_yn"] != "O")].copy()
    df["eok"] = df["price_man"] / 10000
    df["ym"]  = pd.to_datetime(
        df["deal_year"].astype(str) + df["deal_month"].astype(str).str.zfill(2),
        format="%Y%m"
    )
    def _area_label(a):
        try: v = float(a)
        except: return "기타"
        if v < 45:  return f"{round(v)}㎡"
        if v < 63:  return "59㎡"
        if v < 75:  return "72㎡"
        if v < 100: return "84㎡"
        if v < 130: return "114㎡"
        return f"{round(v)}㎡"
    df["area_label"] = df["area"].apply(_area_label)
    return df


@st.cache_data(ttl=300)
def load_jeonse() -> pd.DataFrame:
    """전월세 데이터 (있으면 로드)"""
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        df = pd.read_sql("""
            SELECT lawd_cd, apt_name, deal_year, deal_month, deposit_man
            FROM rtms_jeonse
            ORDER BY deal_year, deal_month
        """, conn)
        conn.close()
        df["deposit_eok"] = df["deposit_man"] / 10000
        df["ym"] = pd.to_datetime(
            df["deal_year"].astype(str) + df["deal_month"].astype(str).str.zfill(2),
            format="%Y%m"
        )
        return df
    except Exception:
        return pd.DataFrame()


# ── 월별 집계 ──────────────────────────────────────────────────
def monthly_stats(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("ym")["eok"]
    stats = pd.DataFrame({
        "ym":    g.min().index,
        "min":   g.min().values,
        "avg":   g.mean().values,
        "max":   g.max().values,
        "count": g.count().values,
    }).reset_index(drop=True)
    # 3개월 이동평균
    stats["ma3"] = stats["avg"].rolling(3, min_periods=2).mean()
    return stats


# ── 트렌드 신호 ────────────────────────────────────────────────
def trend_signal(stats: pd.DataFrame) -> tuple[str, str, str]:
    """
    최근 3개월 vs 이전 3개월 평균 비교
    반환: (이모지, 설명, 색상)
    """
    if len(stats) < 4:
        return "─", "데이터 부족", "#888"
    n = len(stats)
    recent = stats["avg"].iloc[max(n-3, 0):].mean()
    prev   = stats["avg"].iloc[max(n-6, 0):max(n-3, 0)].mean()
    if prev == 0:
        return "─", "보합", "#f39c12"
    pct = (recent - prev) / prev * 100
    if pct >= 2:
        return "🔺", f"상승세 (+{pct:.1f}%)", "#27ae60"
    elif pct <= -2:
        return "🔻", f"하락세 ({pct:.1f}%)", "#e74c3c"
    else:
        return "➡️", f"보합 ({pct:+.1f}%)", "#f39c12"


# ── 차트 (가격 + 거래량 서브플롯) ─────────────────────────────
def make_chart(stats: pd.DataFrame, cname: str, color: str,
               jeonse_stats: pd.DataFrame | None = None) -> go.Figure:
    has_jeonse = jeonse_stats is not None and not jeonse_stats.empty
    rows   = 3 if has_jeonse else 2
    r_h    = [0.60, 0.15, 0.25] if has_jeonse else [0.72, 0.28]
    titles = ["가격(억)", "", "전세가율(%)"] if has_jeonse else ["가격(억)", ""]

    fig = make_subplots(
        rows=rows, cols=1,
        shared_xaxes=True,
        row_heights=r_h,
        vertical_spacing=0.04,
        subplot_titles=titles,
    )

    # ── Row1: 가격 ──
    # 범위 음영
    fig.add_trace(go.Scatter(
        x=pd.concat([stats["ym"], stats["ym"][::-1]]),
        y=pd.concat([stats["max"], stats["min"][::-1]]),
        fill="toself", fillcolor=_hex_to_rgba(color, 0.10),
        line=dict(color="rgba(0,0,0,0)"), hoverinfo="skip",
        showlegend=False, name="범위",
    ), row=1, col=1)
    # 최저선
    fig.add_trace(go.Scatter(
        x=stats["ym"], y=stats["min"], name="최저",
        line=dict(color=color, width=1.5, dash="dot"),
        hovertemplate="%{x|%Y-%m} 최저 %{y:.2f}억<extra></extra>",
    ), row=1, col=1)
    # 평균선
    fig.add_trace(go.Scatter(
        x=stats["ym"], y=stats["avg"], name="평균",
        line=dict(color=color, width=2.5),
        marker=dict(size=5),
        hovertemplate="%{x|%Y-%m} 평균 %{y:.2f}억<extra></extra>",
    ), row=1, col=1)
    # 3개월 이동평균
    if stats["ma3"].notna().sum() >= 2:
        fig.add_trace(go.Scatter(
            x=stats["ym"], y=stats["ma3"], name="3개월 MA",
            line=dict(color="#888", width=1.5, dash="dash"),
            hovertemplate="%{x|%Y-%m} MA3 %{y:.2f}억<extra></extra>",
        ), row=1, col=1)
    # 매수가 기준선
    if _is_my_apt(cname):
        fig.add_hline(y=MY_PRICE, row=1,
            line=dict(color="#e74c3c", width=1.5, dash="dash"),
            annotation_text=f"내 매수가 {MY_PRICE}억",
            annotation_position="top left",
            annotation_font=dict(color="#e74c3c", size=11),
        )

    # ── Row2: 거래량 막대 ──
    vol_colors = [
        _hex_to_rgba(color, 0.8) if c >= stats["count"].median() else _hex_to_rgba(color, 0.4)
        for c in stats["count"]
    ]
    fig.add_trace(go.Bar(
        x=stats["ym"], y=stats["count"], name="거래건수",
        marker_color=vol_colors,
        hovertemplate="%{x|%Y-%m} %{y}건<extra></extra>",
    ), row=2, col=1)

    # ── Row3: 전세가율 (데이터 있을 때만) ──
    if has_jeonse:
        merged = stats[["ym","avg"]].merge(
            jeonse_stats.groupby("ym")["deposit_eok"].mean().reset_index(),
            on="ym", how="inner"
        )
        merged["ratio"] = (merged["deposit_eok"] / merged["avg"] * 100).round(1)
        fig.add_trace(go.Scatter(
            x=merged["ym"], y=merged["ratio"], name="전세가율",
            line=dict(color="#8172B2", width=2),
            fill="toself", fillcolor=_hex_to_rgba("#8172B2", 0.08),
            hovertemplate="%{x|%Y-%m} 전세가율 %{y:.1f}%<extra></extra>",
        ), row=3, col=1)
        fig.add_hline(y=60, row=3,
            line=dict(color="#e74c3c", width=1, dash="dot"),
            annotation_text="60% 기준", annotation_position="right",
            annotation_font=dict(color="#e74c3c", size=10),
        )

    base_h = 420 if not has_jeonse else 520
    fig.update_layout(
        height=base_h,
        margin=dict(l=8, r=8, t=24, b=8),
        plot_bgcolor="white", paper_bgcolor="white",
        legend=dict(orientation="h", x=0, y=1.05, font=dict(size=10)),
        hovermode="x unified",
    )
    fig.update_xaxes(tickformat="%y.%m", showgrid=True, gridcolor="#f0f0f0", tickfont=dict(size=10))
    fig.update_yaxes(tickfont=dict(size=10), showgrid=True, gridcolor="#f0f0f0")
    fig.update_yaxes(ticksuffix="억", row=1)
    fig.update_yaxes(title_text="건", row=2, title_font=dict(size=9))
    if has_jeonse:
        fig.update_yaxes(ticksuffix="%", row=3)
    return fig


# ══════════════════════════════════════════════════════════════
# 페이지
# ══════════════════════════════════════════════════════════════
df_all = load_data()
df_jeonse = load_jeonse()
has_jeonse = not df_jeonse.empty

st.title("실거래가 가격 추이")

if df_all.empty:
    st.warning("수집된 실거래가 데이터가 없습니다. 먼저 **🏛️ 실거래가 수집** 메뉴에서 수집을 실행해주세요.")
    st.stop()

if not has_jeonse:
    st.info("💡 **전세가율**을 보려면 실거래가 수집 페이지에서 **전월세 데이터도 수집**하세요. 전세가율 60% 이상이면 가격 하락 방어력이 높습니다.", icon="ℹ️")

# ── 사이드바 ───────────────────────────────────────────────────
with st.sidebar:
    # 지역 필터
    avail_lawds = sorted(df_all["lawd_cd"].dropna().unique())
    lawd_label_map = {LAWD_NAMES.get(c, c): c for c in avail_lawds}
    if len(lawd_label_map) > 1:
        st.markdown("**지역**")
        sel_lawd_labels = st.multiselect(
            "지역", list(lawd_label_map.keys()),
            default=list(lawd_label_map.keys()),
            key="rtms_lawd",
            label_visibility="collapsed",
        )
        sel_lawd_codes = [lawd_label_map[l] for l in sel_lawd_labels]
        st.divider()
    else:
        sel_lawd_codes = avail_lawds

    # 단지 선택 (선택 지역만)
    st.markdown("**단지 선택**")
    df_filtered = df_all[df_all["lawd_cd"].isin(sel_lawd_codes)] if sel_lawd_codes else df_all.iloc[:0]

    all_apts = sorted(df_filtered["apt_name"].unique())
    priority = [a for a in all_apts if _is_my_apt(a)]
    rest     = [a for a in all_apts if a not in priority]
    apt_list = priority + rest

    selected = st.multiselect(
        "단지", apt_list,
        default=apt_list[:min(4, len(apt_list))],
        key="rtms_sel",
    )
    st.divider()
    st.markdown("**평형 필터**")
    all_areas = sorted(df_all["area_label"].unique())
    sel_areas = st.multiselect(
        "평형 (비우면 전체)", all_areas, default=[],
        key="rtms_area", placeholder="전체",
    )
    st.divider()
    st.markdown("**기간**")
    period = st.selectbox(
        "", ["전체", "최근 6개월", "최근 1년", "최근 2년"],
        index=2, key="rtms_period", label_visibility="collapsed",
    )

if not selected:
    st.info("왼쪽 사이드바에서 단지를 선택하세요.")
    st.stop()

# 기간 필터
cutoff = None
today  = pd.Timestamp(date.today())
if period == "최근 6개월":
    cutoff = today - pd.DateOffset(months=6)
elif period == "최근 1년":
    cutoff = today - pd.DateOffset(months=12)
elif period == "최근 2년":
    cutoff = today - pd.DateOffset(months=24)


def _filter(df, cname):
    dfc = df[df["apt_name"] == cname].copy()
    if sel_areas:
        dfc = dfc[dfc["area_label"].isin(sel_areas)]
    if cutoff is not None:
        dfc = dfc[dfc["ym"] >= cutoff]
    return dfc


# ── 실거주 단지 KPI ────────────────────────────────────────────
_my = next((a for a in selected if _is_my_apt(a)), None)
if _my:
    dfc   = _filter(df_filtered,_my)
    stats = monthly_stats(dfc) if not dfc.empty else pd.DataFrame()
    if len(stats) >= 2:
        cur     = stats["avg"].iloc[-1]
        prev    = stats["avg"].iloc[-2]
        cur_min = stats["min"].iloc[-1]
        emoji, trend_txt, trend_color = trend_signal(stats)

        st.markdown(f"### 🏠 {_my}")

        # 트렌드 요약 카드
        st.markdown(
            f"""<div style='background:{_hex_to_rgba(trend_color,0.12)};border-left:4px solid {trend_color};
            padding:10px 16px;border-radius:4px;margin-bottom:12px'>
            <span style='font-size:22px'>{emoji}</span>
            <strong style='font-size:16px;color:{trend_color}'>  {trend_txt}</strong>
            <span style='color:#555;font-size:13px'> &nbsp;(최근 3개월 평균 vs 이전 3개월 평균)</span>
            </div>""",
            unsafe_allow_html=True,
        )

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("이번 달 평균", f"{cur:.2f}억",    f"{cur-prev:+.2f}억")
        k2.metric("이번 달 최저", f"{cur_min:.2f}억")
        k3.metric("내 매수가",    f"{MY_PRICE:.2f}억", f"{cur_min-MY_PRICE:+.2f}억 (최저 기준)")
        k4.metric("이번 달 거래", f"{int(stats['count'].iloc[-1])}건")

        # 전세가율 KPI (데이터 있을 때)
        if has_jeonse:
            jdf = df_jeonse[df_jeonse["apt_name"] == _my]
            if cutoff is not None:
                jdf = jdf[jdf["ym"] >= cutoff]
            if not jdf.empty:
                latest_ym = stats["ym"].iloc[-1]
                j_latest  = jdf[jdf["ym"] == latest_ym]
                if not j_latest.empty:
                    jeonse_avg = j_latest["deposit_eok"].mean()
                    ratio = jeonse_avg / cur * 100
                    ratio_color = "#27ae60" if ratio >= 60 else "#e74c3c"
                    st.markdown(
                        f"""<div style='background:#f8f8f8;border-radius:4px;padding:8px 16px;margin-top:8px'>
                        전세가율 <strong style='color:{ratio_color};font-size:18px'>{ratio:.1f}%</strong>
                        &nbsp; (전세평균 {jeonse_avg:.2f}억 ÷ 매매평균 {cur:.2f}억)
                        &nbsp; {'✅ 60% 이상 — 가격 방어력 양호' if ratio>=60 else '⚠️ 60% 미만 — 하락 리스크 주의'}
                        </div>""",
                        unsafe_allow_html=True,
                    )
        st.divider()

# ── 차트 ──────────────────────────────────────────────────────
COLS = 2
rows_layout = [selected[i:i+COLS] for i in range(0, len(selected), COLS)]

for row in rows_layout:
    cols = st.columns(len(row))
    for col, cname in zip(cols, row):
        with col:
            dfc   = _filter(df_filtered,cname)
            color = PALETTE[apt_list.index(cname) % len(PALETTE)]

            if dfc.empty:
                st.markdown(f"**{cname}**")
                st.caption("해당 조건 데이터 없음")
                continue

            stats = monthly_stats(dfc)
            latest = stats.iloc[-1]

            emoji, trend_txt, trend_color = trend_signal(stats)
            st.markdown(
                f"**{cname}** &nbsp; "
                f"<span style='color:{trend_color};font-size:13px'>{emoji} {trend_txt}</span>",
                unsafe_allow_html=True,
            )
            area_set = dfc["area_label"].unique()
            area_str = " · ".join(sorted(area_set)) if len(area_set) <= 4 else f"{len(area_set)}종"
            st.caption(
                f"{area_str}  |  "
                f"최저 {latest['min']:.2f}억 · 평균 {latest['avg']:.2f}억 · 최고 {latest['max']:.2f}억"
            )

            # 전세 데이터 필터
            j_sub = None
            if has_jeonse:
                j_sub = df_jeonse[df_jeonse["apt_name"] == cname].copy()
                if cutoff is not None:
                    j_sub = j_sub[j_sub["ym"] >= cutoff]

            fig = make_chart(stats, cname, color, j_sub)
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

# ── 요약 테이블 ────────────────────────────────────────────────
st.divider()
st.subheader("단지별 최근 거래 요약")

summary_rows = []
for cname in selected:
    dfc = _filter(df_filtered,cname)
    if dfc.empty:
        continue
    stats = monthly_stats(dfc)
    latest_ym = dfc["ym"].max()
    latest    = dfc[dfc["ym"] == latest_ym]
    emoji, trend_txt, _ = trend_signal(stats)
    summary_rows.append({
        "단지명":    cname,
        "트렌드":    f"{emoji} {trend_txt}",
        "최근거래":  latest_ym.strftime("%Y.%m"),
        "최저(억)":  round(latest["eok"].min(), 2),
        "평균(억)":  round(latest["eok"].mean(), 2),
        "최고(억)":  round(latest["eok"].max(), 2),
        "거래건수":  len(latest),
    })

if summary_rows:
    summary_df = pd.DataFrame(summary_rows).sort_values("최저(억)")
    st.dataframe(summary_df, use_container_width=True, hide_index=True)
