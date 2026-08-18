# -*- coding: utf-8 -*-
# ============================================================
#  공정별 Target CD 구간에 따른 Tolerance(허용범위) 기준표
# ------------------------------------------------------------
#  사용자가 실제로 관리하는 스펙 표를 그대로 코드로 옮김.
#  Target 값이 어느 구간에 들어가는지에 따라 자동으로 Tolerance를
#  찾아줌 (Item마다 손으로 허용치를 입력할 필요 없음).
#
#  구간 표기 (lo, hi, tolerance): target이 lo 초과 ~ hi 이하이면
#  해당 tolerance 적용. 제일 낮은 구간은 lo=0으로 확장해서, 표에
#  명시 안 된 더 작은 값도 제일 타이트한 허용치를 적용하게 함.
#
#  나중에 스펙이 바뀌면 이 표만 고치면 됨.
# ============================================================

# (공정, 패턴) -> [(lo, hi, tolerance), ...]  (구간은 작은 값부터 순서대로)
TOLERANCE_TABLE = {
    ('RDL', 'L/S'): [
        (0, 4.0, 0.5),
        (4.0, 10.0, 1.0),
        (10.0, float('inf'), 2.0),
    ],
    ('RDL', 'Via Pad'): [
        (0, float('inf'), 2.0),   # 표 기준 target >= 14 구간만 있었음(그 아래는 미정)
    ],
    ('Bump', 'CD'): [
        (0, 30.0, 2.0),
        (30.0, float('inf'), 2.0),
    ],
    ('Cu Post', 'CD'): [
        (0, 100.0, 5.0),
        (100.0, float('inf'), 5.0),
    ],
    ('PI', 'Via CD'): [
        (0, 30.0, 2.0),
        (30.0, float('inf'), 2.0),
    ],
}

# 공정별로 CD류(단일값) Item의 "패턴" 이름 (Line&Space는 공정 상관없이 'L/S' 고정)
CD_PATTERN_BY_PROCESS = {
    'RDL': 'Via Pad',
    'PI': 'Via CD',
    'Bump': 'CD',
    'Cu Post': 'CD',
}


def lookup_tolerance(process, pattern, target):
    """target 값에 맞는 Tolerance를 찾아 반환. 해당 (공정,패턴) 조합이나
       구간이 없으면 None (이 경우 Cpk 계산에서 제외되고 사용자에게 알려야 함)."""
    tiers = TOLERANCE_TABLE.get((process, pattern))
    if not tiers:
        return None
    for lo, hi, tol in tiers:
        if lo < target <= hi:
            return tol
    return None
