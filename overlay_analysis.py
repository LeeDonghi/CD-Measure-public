# -*- coding: utf-8 -*-
# ============================================================
#  Overlay 방향 매칭 + Overlay_X/Y/Overlay 계산 (과제 2)
# ------------------------------------------------------------
#  overlay 사진 한 장에는 십자 마크의 상/하/좌/우 4개 값이 찍혀 있음.
#  글자 안의 "값"은 항상 양수라 그것만으로는 방향을 알 수 없어서,
#  글자가 사진에서 실제로 찍힌 화면 위치(pos_y, pos_x)를 보고
#  4개 값의 중심을 기준으로 상/하/좌/우를 판별함.
#
#  정의:
#   Overlay_X = |좌값 - 우값| / 2
#   Overlay_Y = |상값 - 하값| / 2
#   Overlay   = sqrt(Overlay_X^2 + Overlay_Y^2)
# ============================================================


def assign_directions(rows):
    """overlay 값 4개(rows, 각각 'pos_y'/'pos_x' 필요)에 '방향'
       ('상'/'하'/'좌'/'우') 키를 붙임. 4개가 아니면 전부 빈 값으로 둠.

    ⚠️ 사람이 직접 입력한 값(manual_entry.py)은 화면에 찍힌 적이 없어
    pos_y/pos_x가 None임 - 위치로 방향을 추정할 방법이 없음. 그런 값이 섞여
    있으면(하나라도 None) 대신 입력 화면에서 사람이 직접 확인한 '수동방향'을
    그대로 씀 - OCR로 읽힌 행도 그 화면에서 같이 방향을 확인받으므로 4개 다
    이 값을 갖고 있음."""
    if len(rows) != 4:
        for r in rows:
            r['방향'] = ''
        return

    if any(r.get('pos_y') is None or r.get('pos_x') is None for r in rows):
        for r in rows:
            r['방향'] = r.get('수동방향', '')
        return

    cy = sum(r['pos_y'] for r in rows) / 4
    cx = sum(r['pos_x'] for r in rows) / 4

    for r in rows:
        dy = r['pos_y'] - cy   # 사진 좌표는 아래로 갈수록 y가 커짐
        dx = r['pos_x'] - cx
        if abs(dy) > abs(dx):
            r['방향'] = '상' if dy < 0 else '하'
        else:
            r['방향'] = '좌' if dx < 0 else '우'


_AXIS = {'상': 'y', '하': 'y', '좌': 'x', '우': 'x'}


def infer_known_directions(rows):
    """일부만 읽힌 Overlay 행들(2~3개, 화면 위치 pos_y/pos_x 있음)에서
    위치로 방향을 추정할 수 있으면 각 행의 '방향'을 채움(제자리에서 수정).

    assign_directions()는 4개가 다 모여야만 동작하는데, 수동 입력 화면에
    들어올 때는 아직 2~3개만 읽힌 상태라 그전엔 아예 방향을 안 채웠음.
    그런데 이미 읽힌 행들끼리의 중점만으로도 축(상하/좌우)은 충분히
    가늠됨 - 문제 사진 22장 전수 확인(2026-08-10, 겹침 실패가 항상 좌/우
    라벨 쪽이라 이미 읽힌 두 줄은 항상 같은 축이었음). 2개뿐이고 서로 다른
    축처럼 보이는 경우엔(중점이 진짜 중심과 다를 수 있어 신뢰 못 함) 아무
    것도 안 채우고 사람이 고르게 둔다 - 틀린 값을 미리 채워 넣는 것보다
    안전."""
    known = [r for r in rows
              if r.get('pos_y') is not None and r.get('pos_x') is not None]
    if len(known) < 2:
        return
    cy = sum(r['pos_y'] for r in known) / len(known)
    cx = sum(r['pos_x'] for r in known) / len(known)
    for r in known:
        dy = r['pos_y'] - cy
        dx = r['pos_x'] - cx
        r['방향'] = (('상' if dy < 0 else '하') if abs(dy) > abs(dx)
                     else ('좌' if dx < 0 else '우'))


def infer_forced_directions(known_directions):
    """이미 정해진 방향들(0~4개)에서 남은 자리가 강제로 정해지는지 판단.

    Overlay_X = |좌값-우값|/2, Overlay_Y = |상값-하값|/2로 절댓값을 쓰기
    때문에, 남은 두 자리가 같은 축(좌/우끼리 또는 상/하끼리)이면 어느 쪽에
    뭘 배정하든 계산 결과가 똑같음(2026-08-10, 사용자 지적으로 확인). 그래서
    남은 자리가 1개(무조건 확정)거나, 2개면서 같은 축(순서 무관하게 확정)일
    때만 자동으로 채우고, 그 외(축이 섞였거나 3개 이상 남음)에는 사람이
    직접 골라야 하므로 None을 돌려준다.

    반환: 자동으로 채울 수 있으면 남은 방향 리스트(순서는 의미 없음),
          사람이 골라야 하면 None.

    ⚠️ 같은 방향이 중복으로 들어오면(예: ['상','하','하']) 무조건 None을
    반환한다. 위치 추정(infer_known_directions)이 3개 중 하나를 잘못
    분류했다는 뜻이라 - 3개 읽힌 사진 실측(2026-08-10)에서 실제로 겹친
    경우가 나왔음 - 조용히 무시하면 진짜로는 1개만 남았는데 2개 남은
    것처럼 착각해서 잘못 자동배정하게 됨."""
    filled = [d for d in known_directions if d]
    if len(set(filled)) != len(filled):
        return None
    known = set(filled)
    missing = [d for d in ('상', '하', '좌', '우') if d not in known]
    if len(missing) == 0:
        return []
    if len(missing) == 1:
        return missing
    if len(missing) == 2 and _AXIS[missing[0]] == _AXIS[missing[1]]:
        return missing
    return None


def compute_overlay_metrics(rows):
    """방향이 배정된 값들에서 Overlay_X/Overlay_Y/Overlay를 계산.
       상/하/좌/우가 하나씩 다 있어야 계산되고, 아니면 None."""
    by_dir = {r['방향']: r['값'] for r in rows if r.get('방향')}
    if not all(d in by_dir for d in ('상', '하', '좌', '우')):
        return None

    left, right = by_dir['좌'], by_dir['우']
    up, down = by_dir['상'], by_dir['하']
    overlay_x = abs(left - right) / 2
    overlay_y = abs(up - down) / 2
    overlay = (overlay_x ** 2 + overlay_y ** 2) ** 0.5

    return {
        '상': up, '하': down, '좌': left, '우': right,
        'Overlay_X': round(overlay_x, 4),
        'Overlay_Y': round(overlay_y, 4),
        'Overlay': round(overlay, 4),
    }
