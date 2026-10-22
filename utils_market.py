# utils_market.py — 실거래 데이터 파생지표 + 보유 시나리오 시뮬레이션 계산 엔진
#
# pages/simulator.py가 쓰는 계산 로직. Streamlit·SQLite에 의존하지 않는 순수 함수로
# 두어 (1) 단위 테스트가 가능하고 (2) 다른 페이지에서도 그대로 재사용할 수 있게 한다.
# 차트·레이아웃은 페이지 쪽에 남긴다 (utils_area_trend.py와 같은 분리 원칙).
#
# 외부 API를 전혀 호출하지 않는다 — 이미 수집해둔 rtms_transactions / rtms_jeonse /
# kosis_stats만으로 계산한다.
import math

import pandas as pd

PYEONG = 3.3058  # 1평 = 3.3058㎡

# ── 거래비용 기본값 ───────────────────────────────────────────
# 지방세법상 6억 이하 주택(전용 85㎡ 이하, 1주택) 취득세 1.1%(지방교육세 포함),
# 중개보수는 공인중개사법 시행규칙상 2억~9억 구간 상한 0.4%.
# 사용자별로 달라질 수 있어 시뮬레이터에서 조정 가능한 값으로 노출한다.
ACQUISITION_TAX_RATE = 0.011
BROKER_FEE_RATE = 0.004


# ══════════════════════════════════════════════════════════════
# 파생지표 — 이미 수집 중이지만 지금까지 화면에서 안 쓰던 값들
# ══════════════════════════════════════════════════════════════
def add_derived(df: pd.DataFrame) -> pd.DataFrame:
    """실거래 DataFrame에 평당가·연식·층구간을 붙여 돌려준다.

    rtms_transactions는 build_year(건축년도)와 floor(층)를 수집해 저장하고 있지만
    지금까지 어느 화면에서도 읽지 않았다 — 가격을 면적·연식·층으로 나눠 보면
    "같은 동네 안에서 무엇이 더 비싼가"가 드러나므로 분석 가치가 크다.

    입력에 없는 컬럼은 건너뛴다(전월세 등 스키마가 다른 표에도 안전하게 쓰기 위함).
    """
    d = df.copy()
    if d.empty:
        return d

    # 평당가(만원) — 면적이 제각각인 거래를 한 줄에 놓고 비교하려면 단위가 필요하다
    if {"price_man", "area"}.issubset(d.columns):
        area = pd.to_numeric(d["area"], errors="coerce")
        price = pd.to_numeric(d["price_man"], errors="coerce")
        d["pyeong"] = area / PYEONG
        d["price_per_pyeong"] = (price / d["pyeong"]).where(d["pyeong"] > 0)

    # 연식 — 거래 시점 기준 경과 연수
    if {"build_year", "deal_year"}.issubset(d.columns):
        by = pd.to_numeric(d["build_year"], errors="coerce")
        dy = pd.to_numeric(d["deal_year"], errors="coerce")
        age = dy - by
        d["age"] = age.where((by > 1900) & (age >= 0))
        d["age_bucket"] = d["age"].apply(age_bucket)

    if "floor" in d.columns:
        d["floor_bucket"] = pd.to_numeric(d["floor"], errors="coerce").apply(floor_bucket)

    if "area" in d.columns:
        d["area_label"] = pd.to_numeric(d["area"], errors="coerce").apply(area_label)

    return d


def area_label(area) -> str | None:
    """전용면적 라벨. 국민주택 규격(59/72/84/114㎡)에 맞춰 묶는다 —
    pages/rtms_chart.py의 분류와 같은 경계를 쓴다(화면마다 평형 정의가 달라지면 안 됨)."""
    if area is None or (isinstance(area, float) and math.isnan(area)):
        return None
    v = float(area)
    if v < 45:
        return f"{round(v)}㎡"
    if v < 63:
        return "59㎡"
    if v < 75:
        return "72㎡"
    if v < 100:
        return "84㎡"
    if v < 130:
        return "114㎡"
    return f"{round(v)}㎡"


def age_bucket(age) -> str | None:
    """연식 구간. 신축 프리미엄이 꺾이는 지점(5년/10년)을 경계로 둔다."""
    if age is None or (isinstance(age, float) and math.isnan(age)):
        return None
    a = float(age)
    if a <= 5:
        return "신축 (5년 이하)"
    if a <= 10:
        return "준신축 (6~10년)"
    if a <= 20:
        return "중고 (11~20년)"
    return "구축 (21년 이상)"


def floor_bucket(floor) -> str | None:
    """층 구간. 이 앱의 기존 기준(중상층=11층 이상)과 어긋나지 않게 맞춘다."""
    if floor is None or (isinstance(floor, float) and math.isnan(floor)):
        return None
    f = float(floor)
    if f <= 3:
        return "저층 (1~3층)"
    if f <= 10:
        return "중층 (4~10층)"
    return "고층 (11층 이상)"


def bucket_profile(df: pd.DataFrame, by: str, value: str = "price_per_pyeong") -> pd.DataFrame:
    """구간별 평균/중앙값/건수. 표본이 적은 구간은 호출 쪽에서 걸러 쓰라고 건수를 같이 준다."""
    if df.empty or by not in df.columns or value not in df.columns:
        return pd.DataFrame(columns=[by, "건수", "평균", "중앙값"])
    g = df.dropna(subset=[by, value]).groupby(by)[value]
    if not len(g):
        return pd.DataFrame(columns=[by, "건수", "평균", "중앙값"])
    return pd.DataFrame({
        by: g.mean().index,
        "건수": g.count().values,
        "평균": g.mean().round(1).values,
        "중앙값": g.median().round(1).values,
    }).reset_index(drop=True)


def jeonse_ratio_series(trade: pd.DataFrame, jeonse: pd.DataFrame) -> pd.DataFrame:
    """월별 전세가율(%) = 전세보증금 평균 ÷ 매매가 평균.

    jeonse에는 월세가 섞여 있으므로 보증금만 있는 순수 전세(monthly_rent == 0)만 쓴다
    — 월세 보증금을 섞으면 전세가율이 실제보다 낮게 나온다(기존 rtms_chart.py와 동일 원칙).
    """
    cols = ["ym", "jeonse", "trade", "ratio"]
    if trade.empty or jeonse.empty:
        return pd.DataFrame(columns=cols)

    j = jeonse
    if "monthly_rent" in j.columns:
        j = j[pd.to_numeric(j["monthly_rent"], errors="coerce").fillna(0) == 0]
    if j.empty:
        return pd.DataFrame(columns=cols)

    t_avg = trade.groupby("ym")["price_man"].mean()
    j_avg = j.groupby("ym")["deposit_man"].mean()
    merged = pd.concat([j_avg.rename("jeonse"), t_avg.rename("trade")], axis=1).dropna()
    if merged.empty:
        return pd.DataFrame(columns=cols)
    merged["ratio"] = (merged["jeonse"] / merged["trade"] * 100).round(1)
    return merged.reset_index().rename(columns={"index": "ym"})[cols]


def momentum(series: pd.Series, window: int = 3) -> float | None:
    """최근 window구간 평균 대비 직전 window구간 평균의 변화율(%).

    가격에도 거래량에도 쓴다 — 두 값의 방향이 엇갈리는지가 판단의 핵심이라
    같은 함수로 뽑아야 비교가 공정하다.
    """
    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) < window + 1:
        return None
    recent = s.iloc[-window:].mean()
    prev = s.iloc[-2 * window:-window].mean()
    if not prev or pd.isna(prev) or pd.isna(recent):
        return None
    return float((recent - prev) / prev * 100)


# ══════════════════════════════════════════════════════════════
# 대출 상환 시뮬레이션
# ══════════════════════════════════════════════════════════════
def equal_payment(principal: float, annual_rate_pct: float, months: int) -> float:
    """원리금균등 월 납입액."""
    r = annual_rate_pct / 100 / 12
    if r == 0:
        return principal / months
    return principal * r / (1 - (1 + r) ** -months)


def graduated_first_payment(principal: float, annual_rate_pct: float,
                            months: int, annual_growth_pct: float) -> float:
    """원리금체증식의 1회차 납입액.

    납입액이 12개월마다 (1+g)배로 커진다고 보고, 전체 납입액의 현재가치가 원금과
    같아지는 첫 회차 금액을 닫힌 형태로 구한다.
        P0 · Σ_y [(1+g)/(1+r)^12]^y · Σ_{m=1..12} (1+r)^-m = 원금
    """
    r = annual_rate_pct / 100 / 12
    g = annual_growth_pct / 100
    years = months / 12
    n_years = int(math.ceil(years))

    # 1년치 월납입 현재가치 계수
    if r == 0:
        year_factor = 12.0
    else:
        year_factor = (1 - (1 + r) ** -12) / r

    total = 0.0
    for y in range(n_years):
        rem = min(12, months - y * 12)          # 마지막 해는 12개월이 안 될 수 있다
        if rem <= 0:
            break
        if r == 0:
            partial = float(rem)
        else:
            partial = (1 - (1 + r) ** -rem) / r
        factor = partial if rem < 12 else year_factor
        total += ((1 + g) ** y) * factor * ((1 + r) ** (-12 * y))

    if total <= 0:
        return 0.0
    return principal / total


def amortization_schedule(principal: float, annual_rate_pct: float, months: int,
                          kind: str = "equal", annual_growth_pct: float = 0.0) -> pd.DataFrame:
    """월별 상환 스케줄.

    kind: "equal"(원리금균등) | "graduated"(원리금체증식)
    반환 컬럼: month, year, payment, interest, principal_paid, balance

    체증식은 초기 납입액이 이자보다 적을 수 있고, 그 구간에서는 잔액이 늘어난다
    (음의 상환). 숨기지 않고 그대로 계산해 호출 쪽에서 경고할 수 있게 한다.
    """
    r = annual_rate_pct / 100 / 12
    if kind == "graduated":
        base = graduated_first_payment(principal, annual_rate_pct, months, annual_growth_pct)
    else:
        base = equal_payment(principal, annual_rate_pct, months)

    rows = []
    balance = float(principal)
    for m in range(1, months + 1):
        year_idx = (m - 1) // 12
        pay = base * ((1 + annual_growth_pct / 100) ** year_idx) if kind == "graduated" else base
        interest = balance * r
        # 마지막 회차는 남은 잔액을 모두 정산한다(반올림 오차가 꼬리로 남지 않게)
        if m == months:
            pay = balance + interest
        principal_paid = pay - interest
        balance = balance - principal_paid
        rows.append({
            "month": m,
            "year": year_idx + 1,
            "payment": pay,
            "interest": interest,
            "principal_paid": principal_paid,
            "balance": max(balance, 0.0),
        })
    return pd.DataFrame(rows)


def solve_growth_for_first_payment(principal: float, annual_rate_pct: float, months: int,
                                   target_first_payment: float,
                                   lo: float = 0.0, hi: float = 20.0) -> float | None:
    """실제 1회차 납입액을 알 때 체증률(연 %)을 역산한다.

    주택금융공사 체증식의 증가율은 상품·시점마다 달라 공개 공식으로 재현하기 어렵다.
    사용자가 상환일정에서 확인한 1회차 금액을 넣으면 거기에 맞는 증가율을 이분법으로
    찾아, 이후 스케줄 전체를 실제와 가깝게 그릴 수 있다.
    증가율이 커질수록 1회차는 작아지므로 단조감소 함수다.
    """
    f_lo = graduated_first_payment(principal, annual_rate_pct, months, lo)
    f_hi = graduated_first_payment(principal, annual_rate_pct, months, hi)
    if not (f_hi <= target_first_payment <= f_lo):
        return None  # 주어진 범위에서 만들 수 없는 금액
    for _ in range(80):
        mid = (lo + hi) / 2
        if graduated_first_payment(principal, annual_rate_pct, months, mid) > target_first_payment:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def rate_scenarios(principal: float, months: int, rates, kind: str = "equal",
                   annual_growth_pct: float = 0.0, current_rate: float | None = None) -> pd.DataFrame:
    """금리별 월 납입액·총이자 비교표.

    고정금리를 쓰고 있어도 의미가 있다 — 시장금리가 내 금리보다 충분히 낮아졌는지가
    갈아타기 판단의 출발점이고, 변동금리라면 그대로 미래 부담이기 때문이다.
    """
    rows = []
    for r in rates:
        sch = amortization_schedule(principal, r, months, kind, annual_growth_pct)
        s = loan_summary(sch)
        row = {
            "금리(%)": round(r, 2),
            "1회차 납입(원)": round(sch["payment"].iloc[0]),
            "총이자(만원)": round(s["total_interest"] / 10000),
        }
        if current_rate is not None:
            base = amortization_schedule(principal, current_rate, months, kind, annual_growth_pct)
            row["현재 대비 총이자(만원)"] = round(
                (s["total_interest"] - loan_summary(base)["total_interest"]) / 10000
            )
        rows.append(row)
    return pd.DataFrame(rows)


def loan_summary(schedule: pd.DataFrame) -> dict:
    """스케줄 요약 — 총 이자, 총 상환액, 잔액이 늘어나는 구간(음의 상환) 길이."""
    if schedule.empty:
        return {"total_payment": 0.0, "total_interest": 0.0,
                "negative_amort_months": 0, "peak_balance": 0.0}
    neg = int((schedule["principal_paid"] < 0).sum())
    return {
        "total_payment": float(schedule["payment"].sum()),
        "total_interest": float(schedule["interest"].sum()),
        "negative_amort_months": neg,
        "peak_balance": float(schedule["balance"].max()),
    }


# ══════════════════════════════════════════════════════════════
# 보유 시나리오 — 가격이 ±N% 움직였을 때 내 자산이 어떻게 되는가
# ══════════════════════════════════════════════════════════════
def breakeven_price(purchase_price: float, held_interest: float = 0.0,
                    acq_tax_rate: float = ACQUISITION_TAX_RATE,
                    broker_rate: float = BROKER_FEE_RATE) -> float:
    """손익분기 매도가 — 이 가격에 팔아야 본전.

    매수가 + 취득세 + 매수·매도 중개보수 + 보유기간 이자를 모두 회수해야 한다.
    매도 중개보수는 매도가에 비례하므로 식을 정리해 역산한다:
        S·(1-b) = 매수가 + 취득세 + 매수중개 + 이자
    양도세는 1세대 1주택 2년 보유 비과세 가정으로 제외한다(실거주 목적).
    """
    cost = purchase_price * (1 + acq_tax_rate + broker_rate) + held_interest
    return cost / (1 - broker_rate)


def equity_scenarios(purchase_price: float, current_price: float, loan_balance: float,
                     changes=(-30, -20, -10, 0, 10, 20, 30),
                     held_interest: float = 0.0,
                     acq_tax_rate: float = ACQUISITION_TAX_RATE,
                     broker_rate: float = BROKER_FEE_RATE) -> pd.DataFrame:
    """가격 변동 시나리오별 순자산·LTV·세후 손익.

    current_price를 기준(0%)으로 잡는다 — 매수가가 아니라 "지금 시세"에서
    얼마나 더 움직이는가가 앞으로의 의사결정에 쓰는 축이기 때문이다.
    """
    be = breakeven_price(purchase_price, held_interest, acq_tax_rate, broker_rate)
    rows = []
    for c in changes:
        price = current_price * (1 + c / 100)
        net_sale = price * (1 - broker_rate)              # 매도 시 손에 쥐는 금액
        equity = net_sale - loan_balance                   # 대출 갚고 남는 돈
        profit = net_sale - (purchase_price * (1 + acq_tax_rate + broker_rate) + held_interest)
        rows.append({
            "변동률": f"{c:+d}%",
            "매도가(억)": round(price / 10000, 2),
            "대출잔액(억)": round(loan_balance / 10000, 2),
            "순자산(억)": round(equity / 10000, 2),
            "손익(억)": round(profit / 10000, 2),
            "LTV(%)": round(loan_balance / price * 100, 1) if price > 0 else None,
            "손익분기대비": "▲ 이익" if price >= be else "▼ 손실",
        })
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════
# 신호 종합 — 수집된 지표를 모아 "지금 무엇을 보고 있나"를 문장으로
# ══════════════════════════════════════════════════════════════
def assess_market(price_mom: float | None, volume_mom: float | None,
                  jeonse_ratio: float | None, permit_mom: float | None,
                  population_mom: float | None) -> list[dict]:
    """지표별 해석을 (수준, 제목, 설명) 목록으로 돌려준다.

    단일 점수로 뭉개지 않는 이유: 지표마다 신뢰도와 시차가 달라(인허가는 2~3년 선행,
    거래량은 동행, 전세가율은 수급) 하나로 합치면 근거가 사라진다. 사용자가
    각 줄을 따로 보고 판단하도록 둔다.
    """
    out = []

    def lv(cond_good, cond_bad):
        return "good" if cond_good else ("bad" if cond_bad else "neutral")

    if price_mom is not None:
        out.append({
            "level": lv(price_mom >= 2, price_mom <= -2),
            "title": f"가격 모멘텀 {price_mom:+.1f}%",
            "detail": "최근 3개월 평균가가 직전 3개월 대비 움직인 폭입니다. "
                      "±2% 안쪽이면 보합으로 봅니다.",
        })

    if volume_mom is not None and price_mom is not None:
        if volume_mom <= -20 and price_mom > 0:
            lvl, note = "bad", "거래량이 줄면서 가격만 오르는 구간 — 호가 위주 상승이라 되돌림 위험이 있습니다."
        elif volume_mom >= 20 and price_mom > 0:
            lvl, note = "good", "거래량과 가격이 함께 오르는 구간 — 실수요가 받쳐주는 상승입니다."
        elif volume_mom >= 20 and price_mom < 0:
            lvl, note = "neutral", "거래량이 늘며 가격이 빠지는 구간 — 급매 소화 국면일 수 있습니다."
        else:
            lvl, note = "neutral", "거래량과 가격이 뚜렷한 방향을 같이 만들지는 않고 있습니다."
        out.append({"level": lvl, "title": f"거래량 모멘텀 {volume_mom:+.1f}%", "detail": note})

    if jeonse_ratio is not None:
        if jeonse_ratio >= 70:
            lvl, note = "good", "전세가가 매매가를 70% 이상 받치고 있어 하방이 두껍습니다."
        elif jeonse_ratio >= 60:
            lvl, note = "good", "60%를 넘겨 하락 방어력이 양호한 편입니다."
        elif jeonse_ratio >= 50:
            lvl, note = "neutral", "50~60% 구간 — 보통 수준입니다."
        else:
            lvl, note = "bad", "전세가 받침이 얇아 가격이 빠질 때 지지선이 약합니다."
        out.append({"level": lvl, "title": f"전세가율 {jeonse_ratio:.1f}%", "detail": note})

    if permit_mom is not None:
        if permit_mom >= 30:
            lvl, note = "bad", "주택 인허가가 크게 늘었습니다 — 2~3년 뒤 입주물량으로 돌아와 공급 부담이 됩니다."
        elif permit_mom <= -30:
            lvl, note = "good", "인허가가 줄어 중기 공급 부담이 완화되는 방향입니다."
        else:
            lvl, note = "neutral", "인허가 물량에 큰 변화가 없습니다."
        out.append({
            "level": lvl,
            "title": f"주택 인허가 {permit_mom:+.1f}%",
            "detail": note + " (아파트 외 단독·연립 포함 전체 유형 기준이라 해석에 유의)",
        })

    if population_mom is not None:
        out.append({
            "level": lv(population_mom > 0, population_mom < -1),
            "title": f"인구 증감 {population_mom:+.1f}%",
            "detail": "실수요의 바탕입니다. 인구가 줄어드는 지역은 장기 수요가 약해집니다.",
        })

    return out
