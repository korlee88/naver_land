import hashlib
import re

def _norm(s) -> str:
    # pandas NaN(float)·None 모두 빈 문자열로 정규화
    if s is None or (isinstance(s, float) and s != s):
        s = ""
    s = str(s).strip().lower()
    s = re.sub(r"\s+", "", s)          # 공백 제거
    s = s.replace("㎡", "m²")          # 혹시 단위 흔들리면 통일
    return s

def make_uid(complex_name: str, dong: str, area: str, trade_type: str, direction: str):
    """
    추천 UID(동향 분석용):
    단지명 + 동 + 면적(타입/전용) + 거래유형 + 향
    (층 제외: 같은 타입 그룹으로 가격 동향 보기 좋게)
    """
    base = "|".join([
        _norm(complex_name),
        _norm(dong),
        _norm(area),
        _norm(trade_type),
        _norm(direction),
    ])
    return hashlib.sha1(base.encode("utf-8")).hexdigest()

def make_uid_label(complex_name: str, dong: str, area: str, trade_type: str, direction: str):
    return f"{complex_name}-{dong}-{area}-{trade_type}-{direction}"
