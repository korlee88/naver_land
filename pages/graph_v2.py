"""
graph_v2.py  ─  단지별 가격 추이 차트 + 매물량 트렌드
"""

from datetime import datetime, timedelta

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from utils_style import inject_korean_font
from utils_auth  import require_auth
from utils_graph import (
    build_df, make_daily, render_sidebar,
    PALETTE, SHARED_CSS,
)

inject_korean_font()
require_auth()

st.markdown(SHARED_CSS, unsafe_allow_html=True)

# ── 사이드바 ─────────────────────────────────
df_all = build_df()
if df_all.empty:
    st.error("데이터 없음"); st.stop()

sel, price_sel, drop_th = render_sidebar(df_all, show_drop_th=True)

# ── 필터 적용 ────────────────────────────────
if not sel:
    st.warning("왼쪽에서 단지를 선택해 주세요."); st.stop()

df = df_all[df_all["complex_name"].isin(sel)].copy()
df = df[(df["eok"] >= price_sel[0]) & (df["eok"] <= price_sel[1])]
if df.empty:
    st.warning("조건에 맞는 데이터가 없습니다."); st.stop()

# ── 헤더 ─────────────────────────────────────
col_title, col_info = st.columns([3, 7])
with col_title:
    st.markdown(
        "#### 📊 가격 추이 차트 "
        "<span style='font-size:11px;color:#94a3b8;'>ver.2</span>",
        unsafe_allow_html=True,
    )
with col_info:
    st.markdown(
        f"<div style='font-size:11px;color:#64748b;padding-top:10px;'>"
        f"단지: {', '.join(sel)}  |  총 {len(df):,}건</div>",
        unsafe_allow_html=True,
    )

# ══════════════════════════════════════════════
# [1] 단지별 추이 차트
# ══════════════════════════════════════════════
st.markdown('<div class="sec">📊 차트</div>', unsafe_allow_html=True)

COLS_PER_ROW = 3
trend_names  = sel

for row_start in range(0, len(trend_names), COLS_PER_ROW):
    row_items  = trend_names[row_start : row_start + COLS_PER_ROW]
    chart_cols = st.columns(len(row_items), gap="small")

    for col_idx, cname in enumerate(row_items):
        idx   = row_start + col_idx
        dfc   = df[df["complex_name"] == cname]
        color = PALETTE[idx % len(PALETTE)]

        if dfc.empty:
            chart_cols[col_idx].caption(f"{cname} — 데이터 없음")
            continue

        d2   = make_daily(dfc, drop_th)
        x    = d2["uploadday"]
        mask = x.notna() & d2["min_eok"].notna()

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=x, y=d2["n"], name="건수", yaxis="y2",
            marker_color="#e2e8f0", opacity=0.5, showlegend=False,
        ))
        fig.add_trace(go.Scatter(
            x=x[mask], y=d2["min_eok"][mask],
            name="최저", line=dict(color=color, width=1.5, dash="dash"),
        ))
        fig.add_trace(go.Scatter(
            x=x[mask], y=d2["max_eok"][mask],
            name="최고", line=dict(color=color, width=1.0), opacity=0.6,
        ))
        drops = d2[d2["is_drop"]]
        if not drops.empty:
            fig.add_trace(go.Scatter(
                x=drops["uploadday"], y=drops["min_eok"],
                mode="markers", name="▼급락",
                marker=dict(symbol="triangle-down", size=8, color="#ef4444"),
            ))

        fig.update_layout(
            title=dict(text=cname, font=dict(size=11), x=0, xanchor="left"),
            height=270,
            margin=dict(l=40, r=20, t=30, b=60),
            plot_bgcolor="white",
            legend=dict(orientation="h", y=-0.28, x=0, font=dict(size=9)),
            xaxis=dict(tickfont=dict(size=8), tickangle=30),
            yaxis=dict(
                title="가격(억)", tickfont=dict(size=8),
                showgrid=True, gridcolor="#f1f5f9",
                dtick=0.5, tickformat=".1f",
            ),
            yaxis2=dict(overlaying="y", side="right", showticklabels=False, showgrid=False),
        )
        chart_cols[col_idx].plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════
# [2] 요약 통계 + 매물량 트렌드
# ══════════════════════════════════════════════
st.divider()

RECENT_DAYS = 7
cut   = pd.Timestamp(datetime.now() - timedelta(days=RECENT_DAYS))
d_now = df[df["uploadday"] >= cut]
d_prv = df[df["uploadday"] <  cut]

avg_n = d_now["eok"].mean() if not d_now.empty else None
avg_p = d_prv["eok"].mean() if not d_prv.empty else None
min_n = d_now["eok"].min()  if not d_now.empty else None
min_p = d_prv["eok"].min()  if not d_prv.empty else None

avg_delta = f"({avg_n-avg_p:+.2f}억)" if (avg_n and avg_p) else ""
avg_color = "#dc2626" if (avg_n and avg_p and avg_n > avg_p) else "#16a34a"
min_delta = f"({min_n-min_p:+.2f}억)" if (min_n and min_p) else ""
min_color = "#dc2626" if (min_n and min_p and min_n > min_p) else "#16a34a"

st.markdown(f"""
<div style="display:flex;gap:16px;flex-wrap:wrap;align-items:center;
            background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;
            padding:8px 14px;font-size:11px;color:#475569;">
  <span>📋 <b style="color:#1e293b;">총 매물</b> {len(df):,}건
    <span style="color:#6366f1;font-size:10px;">(최근7일 {len(d_now)}건)</span></span>
  <span style="color:#cbd5e1;">|</span>
  <span><b style="color:#1e293b;">최근 평균가</b> {f"{avg_n:.1f}억" if avg_n else "—"}
    <span style="color:{avg_color};font-size:10px;">{avg_delta}</span></span>
  <span style="color:#cbd5e1;">|</span>
  <span><b style="color:#1e293b;">최근 최저가</b> {f"{min_n:.1f}억" if min_n else "—"}
    <span style="color:{min_color};font-size:10px;">{min_delta}</span></span>
  <span style="color:#cbd5e1;">|</span>
  <span><b style="color:#1e293b;">분석 단지</b> {df['complex_name'].nunique()}개</span>
</div>
""", unsafe_allow_html=True)

st.markdown('<div class="sec" style="margin-top:10px;">📈 매물량 · 가격 트렌드</div>', unsafe_allow_html=True)

now_ts  = pd.Timestamp(datetime.now())
cut_now = now_ts - timedelta(weeks=1)
cut_prv = now_ts - timedelta(weeks=2)

weekly = []
for w in range(5, -1, -1):
    w_end   = now_ts - timedelta(weeks=w)
    w_start = w_end - timedelta(weeks=1)
    chunk   = df[(df["uploadday"] >= w_start) & (df["uploadday"] < w_end)]
    cnt = chunk["uid"].nunique() if "uid" in df.columns else len(chunk)
    avg_p = chunk["eok"].mean() if not chunk.empty else None
    label = w_start.strftime("%m/%d") + "~" + w_end.strftime("%m/%d")
    weekly.append({"label": label, "count": cnt, "avg_price": avg_p, "week_ago": w})

w_df      = pd.DataFrame(weekly)
w_df_data = w_df[w_df["count"] > 0].reset_index(drop=True)

curr  = int(w_df[w_df["week_ago"] == 0]["count"].values[0])
prev1 = int(w_df[w_df["week_ago"] == 1]["count"].values[0])
prev2 = int(w_df[w_df["week_ago"] == 2]["count"].values[0])

avg_this = w_df[w_df["week_ago"] == 0]["avg_price"].values[0]
avg_prev = w_df[w_df["week_ago"] == 1]["avg_price"].values[0]

active_counts = w_df_data["count"].tolist()
week_chg = curr - prev1
if len(active_counts) >= 2:
    diffs    = [active_counts[i+1] - active_counts[i] for i in range(len(active_counts)-1)]
    up_cnt   = sum(1 for d in diffs if d > 0)
    down_cnt = sum(1 for d in diffs if d < 0)
    if up_cnt > down_cnt:   trend_label, trend_color = "📈 증가 추세", "normal"
    elif down_cnt > up_cnt: trend_label, trend_color = "📉 감소 추세", "inverse"
    else:                   trend_label, trend_color = "➡️ 보합세",   "off"
else:
    week_chg = 0
    trend_label, trend_color = "➡️ 수집 중", "off"

week_chg_str = f"{week_chg:+d}건" if week_chg != 0 else "±0건"

col_bar, col_stat = st.columns([3, 1])

with col_bar:
    plot_df = w_df.copy()
    plot_df["color"] = plot_df.apply(
        lambda r: "이번 주" if r["week_ago"] == 0 else ("이전 주" if r["count"] > 0 else "데이터 없음"),
        axis=1,
    )
    fig_t = px.bar(
        plot_df, x="label", y="count", color="color",
        color_discrete_map={"이번 주": "#6366f1", "이전 주": "#93c5fd", "데이터 없음": "#f1f5f9"},
        text="count", height=200,
    )
    # 건수 텍스트: 막대 안쪽 표시, 0건은 숨김
    fig_t.update_traces(
        texttemplate="%{text}건",
        textposition="inside",
        textfont=dict(size=10, color="white"),
        insidetextanchor="middle",
    )
    fig_t.update_traces(
        selector=dict(type="bar"),
        texttemplate="%{y}건" ,
    )

    # 평균가 꺾은선 — 라벨 없이 선만, 마지막 점만 라벨
    price_valid = w_df.dropna(subset=["avg_price"])
    if not price_valid.empty:
        last_idx = price_valid.index[-1]
        texts = [
            f"{v:.2f}억" if idx == last_idx else ""
            for idx, v in zip(price_valid.index, price_valid["avg_price"])
        ]
        fig_t.add_trace(go.Scatter(
            x=price_valid["label"], y=price_valid["avg_price"],
            mode="lines+markers+text", name="평균가",
            yaxis="y2",
            line=dict(color="#f59e0b", width=2),
            marker=dict(size=5, color="#f59e0b"),
            text=texts,
            textposition="top center",
            textfont=dict(size=9, color="#b45309"),
        ))

    p_min = w_df["avg_price"].min()
    p_max = w_df["avg_price"].max()
    fig_t.update_layout(
        margin=dict(l=0, r=30, t=10, b=0),
        xaxis_title=None, yaxis_title=None, showlegend=False,
        plot_bgcolor="white",
        xaxis=dict(tickfont=dict(size=9)),
        yaxis=dict(showticklabels=False, showgrid=False),
        yaxis2=dict(
            overlaying="y", side="right", showticklabels=False, showgrid=False,
            range=[p_min * 0.95, p_max * 1.08] if w_df["avg_price"].notna().any() else None,
        ),
    )
    st.plotly_chart(fig_t, use_container_width=True)

with col_stat:
    # 매물량 변화
    vol_delta_color = "inverse" if week_chg < 0 else ("normal" if week_chg > 0 else "off")
    st.markdown(f"""
<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 10px;margin-bottom:6px;">
  <div style="font-size:10px;color:#64748b;">📦 이번주 매물량 <span style="color:#94a3b8;font-size:9px;">{trend_label.split()[1] if len(trend_label.split())>1 else ''}</span></div>
  <div style="font-size:20px;font-weight:700;color:#1e293b;margin:2px 0;">{curr}건</div>
  <div style="font-size:11px;color:{'#dc2626' if week_chg < 0 else '#16a34a' if week_chg > 0 else '#64748b'};">
    {'▼' if week_chg < 0 else '▲' if week_chg > 0 else '➡'} 전주 대비 {abs(week_chg)}건
  </div>
  <div style="font-size:10px;color:#94a3b8;margin-top:2px;">전주 {prev1}건 · 전전주 {prev2}건</div>
</div>
""", unsafe_allow_html=True)

    # 주간 평균가 변화
    if avg_this is not None:
        price_chg = (avg_this - avg_prev) if avg_prev is not None else None
        chg_txt = ""
        chg_color = "#64748b"
        if price_chg is not None and abs(price_chg) >= 0.01:
            chg_txt   = f"{'▲' if price_chg > 0 else '▼'} 전주 대비 {abs(price_chg):.2f}억"
            chg_color = "#dc2626" if price_chg > 0 else "#16a34a"
        elif price_chg is not None:
            chg_txt   = "전주와 동일"
            chg_color = "#94a3b8"
        st.markdown(f"""
<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 10px;">
  <div style="font-size:10px;color:#64748b;">💰 이번주 평균가</div>
  <div style="font-size:20px;font-weight:700;color:#1e293b;margin:2px 0;">{avg_this:.2f}억</div>
  <div style="font-size:11px;color:{chg_color};">{chg_txt}</div>
</div>
""", unsafe_allow_html=True)

# ── 단지별 현재 최저가 비교 ───────────────────────────────────────────────
price_rows = []
for cname in sel:
    dfc = df[df["complex_name"] == cname]
    if dfc.empty:
        continue
    now_chunk = dfc[dfc["uploadday"] >= pd.Timestamp(datetime.now() - timedelta(days=14))]
    prv_chunk = dfc[dfc["uploadday"] <  pd.Timestamp(datetime.now() - timedelta(days=14))]
    cur_min = now_chunk["eok"].min() if not now_chunk.empty else dfc["eok"].min()
    prv_min = prv_chunk["eok"].min() if not prv_chunk.empty else None
    chg     = round(cur_min - prv_min, 2) if prv_min is not None else None
    price_rows.append({"단지": cname, "cur_min": cur_min, "chg": chg})

if price_rows:
    price_rows.sort(key=lambda x: x["cur_min"])
    rank_icons = ["🥇", "🥈", "🥉"] + [""] * 10
    medals = ["gold", "silver", "#cd7f32"] + [""] * 10
    border_colors = ["#fbbf24", "#94a3b8", "#cd7f32"] + ["#e2e8f0"] * 10

    st.markdown('<div class="sec" style="margin-top:8px;">🏷️ 단지별 현재 최저가 (최근 2주)</div>', unsafe_allow_html=True)
    cols_p = st.columns(len(price_rows))
    for i, row in enumerate(price_rows):
        chg = row["chg"]
        if chg is not None and abs(chg) >= 0.01:
            chg_html = f"<span style='color:{'#dc2626' if chg > 0 else '#16a34a'};font-size:10px;'>{'▲' if chg > 0 else '▼'} {abs(chg):.2f}억</span>"
        else:
            chg_html = "<span style='color:#94a3b8;font-size:10px;'>변동 없음</span>"
        cols_p[i].markdown(f"""
<div style="background:#f8fafc;border:1px solid {border_colors[i]};border-radius:8px;
            padding:8px 10px;text-align:center;">
  <div style="font-size:11px;color:#64748b;">{rank_icons[i]} {row['단지']}</div>
  <div style="font-size:18px;font-weight:700;color:#1e293b;margin:3px 0;">{row['cur_min']:.2f}억</div>
  {chg_html}
</div>""", unsafe_allow_html=True)
