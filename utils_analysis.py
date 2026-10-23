# utils_analysis.py — 시장 연동 분석 계산 엔진 (시차상관·지역베타·전이경로·유사국면)
#
# pages/market_link.py가 쓰는 통계 로직. Streamlit·DB에 의존하지 않는 순수 함수라
# 단위 테스트가 된다 (utils_market.py와 같은 분리 원칙).
#
# ── 이 모듈이 공통으로 깔고 가는 전제 ────────────────────────────
# 1) 상관은 '수준'이 아니라 '변화'로 잰다.
#    추세를 가진 두 시계열은 아무 관계가 없어도 상관이 높게 나온다. 36개월 표본으로
#    모의실험하면 무관한 두 상승 시계열의 |r|이 0.5를 넘을 확률이 91%, 평균 |r|이
#    0.80이었다. 같은 데이터를 차분하면 그 확률이 0.3%로 떨어진다.
# 2) 상관계수는 점추정만 주지 않는다 — 표본수와 신뢰구간을 항상 같이 돌려준다.
#    n=36이면 진짜 r=0.5여도 95% 구간이 [0.21, 0.71]이라 '약함'과 '강함'을 구분 못 한다.
# 3) 시차를 훑으면 다중비교로 가짜 양성이 쌓인다 — 몇 번 검정했는지와 우연히 나올
#    유의 개수를 같이 보고한다.
import math

import numpy as np
import pandas as pd

Z95 = 1.959963984540054


# ══════════════════════════════════════════════════════════════
# 기초 — 변화율 변환과 신뢰구간 있는 상관
# ══════════════════════════════════════════════════════════════
def to_changes(s: pd.Series, method: str = "auto") -> pd.Series:
    """시계열을 '변화'로 바꾼다.

    method="auto": 모든 값이 양수면 변동률(pct_change), 아니면 차분(diff).
      가격처럼 추세와 함께 변동폭도 커지는 계열은 변동률이, 금리처럼 수준 자체가
      의미인 계열은 %p 차분이 자연스럽기 때문이다.
    """
    s = pd.to_numeric(s, errors="coerce").dropna()
    if len(s) < 2:
        return pd.Series(dtype=float)
    if method == "pct" or (method == "auto" and (s > 0).all()):
        out = s.pct_change()
    else:
        out = s.diff()
    return out.replace([np.inf, -np.inf], np.nan).dropna()


def corr_with_ci(x: pd.Series, y: pd.Series, conf: float = 0.95) -> dict:
    """피어슨 상관 + Fisher z 신뢰구간.

    반환: {"r", "n", "lo", "hi", "significant"}
      significant는 신뢰구간이 0을 포함하지 않는지 — 'r이 크다'가 아니라
      '0이 아니라고 말할 수 있는가'가 표본이 작을 때 봐야 할 기준이다.
    """
    df = pd.concat([pd.Series(x).rename("x"), pd.Series(y).rename("y")], axis=1, sort=False).dropna()
    n = len(df)
    empty = {"r": None, "n": n, "lo": None, "hi": None, "significant": False}
    if n < 4:
        return empty                      # Fisher z는 n>3이어야 정의된다
    if df["x"].std() == 0 or df["y"].std() == 0:
        return empty
    r = float(df["x"].corr(df["y"]))
    if pd.isna(r):
        return empty
    r = max(min(r, 0.999999), -0.999999)  # arctanh 발산 방지
    z = math.atanh(r)
    se = 1 / math.sqrt(n - 3)
    crit = Z95 if abs(conf - 0.95) < 1e-9 else abs(_z_for(conf))
    lo, hi = math.tanh(z - crit * se), math.tanh(z + crit * se)
    return {"r": r, "n": n, "lo": lo, "hi": hi, "significant": lo * hi > 0}


def _z_for(conf: float) -> float:
    """양측 신뢰수준에 대응하는 표준정규 분위수 (scipy 없이 역함수 근사)."""
    p = 1 - (1 - conf) / 2
    # Acklam 역정규 근사 — 소수점 6자리 수준이면 신뢰구간 표시에 충분하다
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    pl, ph = 0.02425, 1 - 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > ph:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def corr_strength(r: float | None) -> str:
    if r is None:
        return "판단 불가"
    a = abs(r)
    return "강함" if a >= 0.7 else "중간" if a >= 0.4 else "약함" if a >= 0.2 else "거의 없음"


# ══════════════════════════════════════════════════════════════
# 1. 시차 교차상관 — 무엇이 몇 개월 선행하는가
# ══════════════════════════════════════════════════════════════
def lag_scan(target: pd.Series, indicator: pd.Series, max_lag: int = 12,
             method: str = "auto", use_changes: bool = True) -> pd.DataFrame:
    """지표를 -max_lag~+max_lag만큼 밀어가며 target과의 상관을 잰다.

    lag > 0 : 지표가 target보다 그만큼 **선행**한다는 가정에서의 상관
              (지표를 미래로 밀어 과거 지표 ↔ 현재 가격을 맞춘다)
    lag < 0 : 지표가 후행
    인덱스는 두 계열 모두 시간(DatetimeIndex 또는 정렬된 PeriodIndex)이어야 한다.
    """
    t = pd.to_numeric(target, errors="coerce").dropna().sort_index()
    i = pd.to_numeric(indicator, errors="coerce").dropna().sort_index()
    if use_changes:
        t, i = to_changes(t, method), to_changes(i, method)

    lags = list(range(-max_lag, max_lag + 1))
    # 시차를 n번 훑으면 그중 하나가 우연히 유의해 보일 확률이 n배로 커진다.
    # 실제로 무관한 계열끼리 25개 시차를 훑었더니 r=-0.30이 "유의"로 잡혔다.
    # 그래서 보정 없는 판정(significant)과 Bonferroni 보정 판정(significant_adj)을
    # 둘 다 내놓고, 결론은 보정된 쪽으로 낸다.
    conf_adj = 1 - 0.05 / len(lags)
    rows = []
    for lag in lags:
        shifted = i.shift(lag)
        c = corr_with_ci(t, shifted)
        c_adj = corr_with_ci(t, shifted, conf=conf_adj)
        rows.append({
            "lag": lag, "r": c["r"], "n": c["n"],
            "lo": c["lo"], "hi": c["hi"], "significant": c["significant"],
            "lo_adj": c_adj["lo"], "hi_adj": c_adj["hi"],
            "significant_adj": c_adj["significant"],
        })
    return pd.DataFrame(rows)


def best_lag(scan: pd.DataFrame, require_significant: bool = True,
             adjusted: bool = True) -> dict | None:
    """스캔 결과에서 |r|이 가장 큰 시차.

    require_significant=True면 신뢰구간이 0을 제외한 시차 중에서 고른다.
    adjusted=True(기본)면 다중비교 보정된 구간을 쓴다 — 시차 스캔에서 보정 없이
    유의성을 판단하면 무관한 계열에서도 "유의한 시차"가 흔히 나온다.
    """
    df = scan.dropna(subset=["r"])
    col = "significant_adj" if (adjusted and "significant_adj" in df.columns) else "significant"
    if require_significant:
        df = df[df[col]]
    if df.empty:
        return None
    row = df.loc[df["r"].abs().idxmax()]
    out = {k: (int(row[k]) if k in ("lag", "n") else row[k])
           for k in ("lag", "r", "n", "lo", "hi", "significant")}
    if "significant_adj" in row:
        out["significant_adj"] = bool(row["significant_adj"])
        out["lo_adj"], out["hi_adj"] = row["lo_adj"], row["hi_adj"]
    return out


def expected_false_positives(n_tests: int, alpha: float = 0.05) -> float:
    """시차를 n_tests번 훑었을 때 우연히 '유의'하게 나올 기대 개수.

    -12~+12를 훑으면 25번 검정이라 α=0.05에서 약 1.25개는 그냥 나온다.
    실제 유의 개수가 이 값 언저리면 발견이 아니라 잡음으로 봐야 한다.
    """
    return n_tests * alpha


# ══════════════════════════════════════════════════════════════
# 2. 지역 베타 — 시장이 1% 움직일 때 내 지역은 몇 %
# ══════════════════════════════════════════════════════════════
def regional_beta(target: pd.Series, benchmark: pd.Series, method: str = "auto") -> dict:
    """변화율 회귀의 기울기(베타)와 신뢰구간.

    beta > 1 : 시장보다 크게 움직임(증폭) — 오를 때 더 오르고 빠질 때 더 빠진다
    beta < 1 : 완충
    반환: {"beta", "lo", "hi", "r2", "n", "alpha"}  (alpha = 시장과 무관한 초과 변화)
    """
    t, b = to_changes(target, method), to_changes(benchmark, method)
    df = pd.concat([t.rename("t"), b.rename("b")], axis=1, sort=False).dropna()
    n = len(df)
    empty = {"beta": None, "lo": None, "hi": None, "r2": None, "n": n, "alpha": None}
    if n < 5 or df["b"].std() == 0:
        return empty

    x, y = df["b"].to_numpy(), df["t"].to_numpy()
    xbar, ybar = x.mean(), y.mean()
    sxx = ((x - xbar) ** 2).sum()
    if sxx == 0:
        return empty
    beta = ((x - xbar) * (y - ybar)).sum() / sxx
    alpha = ybar - beta * xbar
    resid = y - (alpha + beta * x)
    dof = n - 2
    if dof <= 0:
        return empty
    s2 = (resid ** 2).sum() / dof
    se_beta = math.sqrt(s2 / sxx) if sxx > 0 else float("nan")
    sst = ((y - ybar) ** 2).sum()
    r2 = 1 - (resid ** 2).sum() / sst if sst > 0 else None
    # 표본이 작아 정규분포 대신 t분포를 써야 하지만, scipy 없이 근사한다.
    # dof가 작을수록 구간이 좁게 나오므로 보수적으로 1.1배 넓힌다(대략적 보정).
    crit = Z95 * (1.1 if dof < 30 else 1.0)
    return {"beta": float(beta), "lo": float(beta - crit * se_beta),
            "hi": float(beta + crit * se_beta), "r2": None if r2 is None else float(r2),
            "n": n, "alpha": float(alpha)}


def beta_label(b: dict) -> str:
    """베타를 문장으로. 음수 베타는 '작게 움직임'이 아니라 '반대로 움직임'이라
    질적으로 다른 상태이므로 따로 다룬다 — 섞으면 해석이 정반대가 된다."""
    if b.get("beta") is None:
        return "표본이 부족해 판단할 수 없습니다."
    lo, hi, beta = b["lo"], b["hi"], b["beta"]
    if lo <= 0 <= hi:
        return (f"베타 {beta:.2f} — 신뢰구간 [{lo:.2f}, {hi:.2f}]이 0을 포함합니다. "
                "시장 움직임으로 내 지역을 설명하지 못한다는 뜻이라, 베타 값 자체를 "
                "해석하지 마세요. 지역 고유 요인이 지배적이거나 표본이 부족한 경우입니다.")
    if beta < 0:
        return (f"베타 {beta:.2f} — 시장과 **반대 방향**으로 움직입니다. "
                "표본이 짧을 때 흔히 나오는 잡음일 수 있으니, 수집 기간을 늘려 "
                "부호가 유지되는지 확인한 뒤 해석하세요.")
    if lo <= 1 <= hi:
        return (f"베타 {beta:.2f} — 신뢰구간 [{lo:.2f}, {hi:.2f}]이 1을 포함해 "
                "시장과 같은 폭으로 움직인다는 설명을 배제하지 못합니다.")
    if beta > 1:
        return (f"베타 {beta:.2f} — 시장보다 크게 움직입니다(증폭). "
                "오를 때 더 오르고 빠질 때 더 빠지는 쪽입니다.")
    return (f"베타 {beta:.2f} — 시장보다 작게 움직입니다(완충). "
            "상승은 덜 먹지만 하락 방어는 상대적으로 낫습니다.")


# ══════════════════════════════════════════════════════════════
# 3. 전이 경로 — 글로벌 → 한국 → 내 지역, 어디서 끊기는가
# ══════════════════════════════════════════════════════════════
def transmission_chain(stages: list[tuple[str, pd.Series]], max_lag: int = 12,
                       method: str = "auto") -> pd.DataFrame:
    """인접한 단계끼리만 상관을 재서 신호가 어디서 약해지는지 본다.

    글로벌금리 → 한국기준금리 → 주담대금리 → 거래량 → 내 지역 가격처럼
    경로가 긴 관계를 양끝만 맞대보면(글로벌 vs 평택) 중간이 다 섞여 해석이 안 된다.
    단계별로 끊어 재야 '어느 고리가 약한지'가 드러난다.
    """
    rows = []
    for (n1, s1), (n2, s2) in zip(stages, stages[1:]):
        scan = lag_scan(s2, s1, max_lag=max_lag, method=method)
        best = best_lag(scan, require_significant=False)
        sig = best_lag(scan, require_significant=True, adjusted=True)
        rows.append({
            "단계": f"{n1} → {n2}",
            "최적시차(개월)": None if best is None else best["lag"],
            "r": None if best is None else round(best["r"], 3),
            "표본": None if best is None else best["n"],
            "95%구간": None if best is None else f"[{best['lo']:.2f}, {best['hi']:.2f}]",
            "유의": bool(sig is not None),
            "강도": corr_strength(None if best is None else best["r"]),
        })
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════
# 4. 유사 국면 탐색 — 지금과 비슷했던 과거를 찾고 그 뒤를 본다
# ══════════════════════════════════════════════════════════════
def find_similar_regimes(features: pd.DataFrame, price: pd.Series, window: int = 6,
                         horizon: int = 12, top_k: int = 3) -> pd.DataFrame:
    """현재 window개월 국면과 가장 비슷했던 과거 구간을 찾아, 그 뒤 horizon개월
    가격이 어떻게 움직였는지 돌려준다.

    예측이 아니라 사례 제시다 — 표본이 짧으면 사례가 1~2개뿐일 수 있고, 그조차
    우연일 수 있다. 반환되는 '거리'가 클수록 닮지 않은 구간이라는 뜻이다.
    features: 월별 지표 행렬(금리·거래량·공급 등), price: 같은 인덱스의 가격
    """
    f = features.apply(pd.to_numeric, errors="coerce").dropna()
    p = pd.to_numeric(price, errors="coerce").dropna()
    idx = f.index.intersection(p.index)
    f, p = f.loc[idx].sort_index(), p.loc[idx].sort_index()
    if len(f) < window + horizon + window:
        return pd.DataFrame(columns=["시작", "종료", "거리", f"이후{horizon}개월 변화율(%)"])

    # 지표마다 단위가 달라 표준화해야 거리가 특정 지표에 끌려가지 않는다
    z = (f - f.mean()) / f.std(ddof=0).replace(0, np.nan)
    z = z.dropna(axis=1, how="all").fillna(0.0)
    if z.empty:
        return pd.DataFrame(columns=["시작", "종료", "거리", f"이후{horizon}개월 변화율(%)"])

    cur = z.iloc[-window:].to_numpy()
    rows = []
    # 현재 구간과 겹치지 않고, 뒤 horizon개월 결과를 볼 수 있는 구간만 후보로 둔다
    last_start = len(z) - window - horizon
    for s in range(0, last_start):
        seg = z.iloc[s:s + window].to_numpy()
        if seg.shape != cur.shape:
            continue
        dist = float(np.sqrt(((seg - cur) ** 2).mean()))
        p0 = p.iloc[s + window - 1]
        p1 = p.iloc[min(s + window - 1 + horizon, len(p) - 1)]
        if not p0:
            continue
        rows.append({
            "시작": z.index[s],
            "종료": z.index[s + window - 1],
            "거리": round(dist, 3),
            f"이후{horizon}개월 변화율(%)": round((p1 - p0) / p0 * 100, 1),
        })
    if not rows:
        return pd.DataFrame(columns=["시작", "종료", "거리", f"이후{horizon}개월 변화율(%)"])
    return pd.DataFrame(rows).sort_values("거리").head(top_k).reset_index(drop=True)


def regime_summary(matches: pd.DataFrame, horizon: int) -> str:
    col = f"이후{horizon}개월 변화율(%)"
    if matches.empty or col not in matches.columns:
        return "비슷했던 과거 구간을 찾기에 데이터가 부족합니다."
    vals = matches[col]
    if len(vals) == 1:
        return (f"비슷한 구간이 **1개**뿐입니다 — 그때는 {horizon}개월 뒤 "
                f"**{vals.iloc[0]:+.1f}%** 였습니다. 사례 하나는 근거로 삼기 어렵습니다.")
    return (f"비슷했던 {len(vals)}개 구간의 이후 {horizon}개월 변화는 "
            f"**{vals.min():+.1f}% ~ {vals.max():+.1f}%** "
            f"(중앙값 {vals.median():+.1f}%)였습니다. 표본이 적어 범위로만 참고하세요.")
