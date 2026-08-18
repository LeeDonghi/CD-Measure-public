# -*- coding: utf-8 -*-
# ============================================================
#  측정 계획(Measurement Plan) 데이터 구조 + Target 매칭 로직
# ------------------------------------------------------------
#  공정(RDL/PI/Bump)마다 CD 종류가 다르고, 각 CD 종류 안에 여러
#  Item(예: Item1, Item2...)이 있을 수 있음. Item마다 "몇 포인트
#  측정했는지"와 "Target 값"을 미리 입력받아두고, 사진에서 읽은
#  값과 비교(편차 계산)하는 데 씀.
#
#  사진 순서로 어떤 값이 어떤 Item인지 딱 맞추기는 위험함(사진
#  순서가 뒤섞일 수 있다고 설계문서에 명시됨). 그래서 측정값마다
#  "제일 가까운 Target을 가진 Item"을 찾아 매칭하는 방식을 씀.
# ============================================================
from dataclasses import dataclass, field
import statistics


@dataclass
class CDItem:
    """CD 한 종류(Pad CD / Via CD / UBM CD)의 Item 하나."""
    name: str        # 예: "Pad CD Item 1"
    points: int       # 이 Item을 몇 포인트 측정했는지
    target: float     # Target 값
    tolerance: float = None   # Target 구간표로 자동 계산된 허용범위(±). None이면 기준표에 없음


@dataclass
class LSItem:
    """Line & Space Item 하나.

    ⚠️ Line과 Space가 반드시 쌍으로 있는 게 아님. Item마다 독립이라
    Line만 있거나 Space만 있을 수 있음 (예: Item1 = Line Target 10만,
    Item2 = Space Target 20만). 2026-08-05 실제 측정 데이터로 확인함 —
    그전에는 둘 다 필수라고 보고 입력칸도 둘 다 required였는데, 그래서
    "Space 없음"을 입력할 방법 자체가 없었고 그 사진들이 CD로 잘못
    분류돼 엉뚱한 Target과 비교됐음.

    없는 쪽은 None. 최소 한쪽은 있어야 함.
    한쪽만 있는 Item은 사진 한 장에 값이 1개만 찍히므로, 값이 2개 찍히는
    "Line+Space 쌍" Item과는 매칭 경로가 다름(아래 match_single_target).
    """
    name: str
    points: int
    target_line: float = None
    target_space: float = None
    tolerance_line: float = None    # 자동 계산됨 (없으면 None)
    tolerance_space: float = None


@dataclass
class MeasurementPlan:
    process: str                 # 'RDL' | 'PI' | 'Bump'
    cd_label: str                 # 'Pad CD' | 'Via CD' | 'UBM CD' (엑셀 표시용 이름)
    cd_items: list = field(default_factory=list)   # list[CDItem]
    ls_items: list = field(default_factory=list)   # list[LSItem] (RDL만 사용, 그 외엔 비어있음)
    overlay_points: int = 0
    customer: str = ''    # 고객 이름
    material: str = ''    # 자재 이름
    layer: str = ''       # Layer 단계


def plan_from_dict(d):
    """dataclasses.asdict(plan)으로 만든 dict에서 MeasurementPlan을 복원.

    웹에서 씀(2026-08-07) — 못 읽은 값을 사람이 입력할 동안 계획을 파일로
    저장해뒀다가(폼 제출은 나중 요청이라 메모리에 안 남아있음), 이어서 처리할
    때 다시 객체로 만들어야 함."""
    return MeasurementPlan(
        process=d['process'], cd_label=d['cd_label'],
        cd_items=[CDItem(**it) for it in d['cd_items']],
        ls_items=[LSItem(**it) for it in d['ls_items']],
        overlay_points=d['overlay_points'], customer=d['customer'],
        material=d['material'], layer=d['layer'])


# ------------------------------------------------------------
#  Target 매칭: 측정값과 제일 가까운 Item의 Target을 찾음
# ------------------------------------------------------------
def match_cd_target(value, plan):
    """CD류(1개 값) 측정값에 대해 제일 가까운 Item을 찾아
       (Item이름, Target, 편차, Tolerance) 반환. Item이 하나도 없으면 None."""
    if not plan.cd_items:
        return None
    item = min(plan.cd_items, key=lambda it: abs(value - it.target))
    return item.name, item.target, round(value - item.target, 3), item.tolerance


def single_sided_ls_targets(plan):
    """Line 또는 Space 中 한쪽만 입력된 L/S Item들을 펼쳐서 돌려줌.
       이런 Item은 사진 한 장에 값이 1개만 찍히므로 CD 사진과 생김새가 같음.
       반환: [(Item, 'Line'|'Space', target, tolerance), ...]"""
    out = []
    for item in plan.ls_items:
        has_line = item.target_line is not None
        has_space = item.target_space is not None
        if has_line and not has_space:
            out.append((item, 'Line', item.target_line, item.tolerance_line))
        elif has_space and not has_line:
            out.append((item, 'Space', item.target_space, item.tolerance_space))
    return out


def match_single_target(value, plan):
    """측정줄이 1개인 사진의 값을, CD Item과 "한쪽만 있는 L/S Item" 전체에서
       제일 가까운 Target에 매칭.

       줄 개수만으로는 CD인지 L/S인지 가릴 수 없어서 값으로 정한다.
       (예전에는 1줄=무조건 CD로 확정해버려서, Line만 있는 L/S 사진이
        Pad CD Target과 비교돼 스펙이탈로 잡혔음 — 2026-08-05)

       반환: (종류, 항목이름, Target, 편차, Tolerance, 애매함)
             종류는 'CD' 또는 'L/S' — 이 값이 세트 검증의 종류로도 쓰임.
       후보가 하나도 없으면 None."""
    candidates = [('CD', it.name, it.target, it.tolerance) for it in plan.cd_items]
    for item, side, target, tol in single_sided_ls_targets(plan):
        candidates.append(('L/S', f'{item.name}-{side}', target, tol))
    if not candidates:
        return None

    candidates.sort(key=lambda c: abs(value - c[2]))
    category, name, target, tolerance = candidates[0]

    # 다른 종류의 후보에도 "스펙 안에 들어와" 버리면 어느 쪽인지 확신할 수 없음.
    # 이럴 때 임의로 정하면 조용히 틀린 결과가 나오므로, 제일 가까운 쪽으로
    # 매칭하되 확인필요로 넘긴다(값=√(X²+Y²) 정합성 검사와 같은 원칙).
    ambiguous = any(
        cat != category and tol is not None and abs(value - t) <= tol
        for cat, _, t, tol in candidates[1:])

    return category, name, target, round(value - target, 3), tolerance, ambiguous


def match_ls_targets(value0, value1, plan):
    """L/S류(2개 값)에 대해, 두 값을 Line/Space로 구분하고
       제일 가까운 Item을 찾아 반환.
       반환: (Item이름, line값, line target, line편차, line Tolerance,
              space값, space target, space편차, space Tolerance)
       Item이 하나도 없으면 None."""
    # Line/Space가 둘 다 있는 Item만 후보. 한쪽만 있는 Item은 사진에 값이
    # 1개만 찍히므로 여기로 오지 않음(match_single_target이 담당).
    paired = [it for it in plan.ls_items
              if it.target_line is not None and it.target_space is not None]
    if not paired:
        return None

    best = None
    for item in paired:
        # 두 가지 배정(정방향/역방향) 중 오차가 작은 쪽을 고름
        # 배정 A: value0->line, value1->space / 배정 B: value0->space, value1->line
        err_a = abs(value0 - item.target_line) + abs(value1 - item.target_space)
        err_b = abs(value0 - item.target_space) + abs(value1 - item.target_line)
        if err_a == err_b:
            # Target만으로 못 가릴 때(Line Target == Space Target인 경우 등):
            # 1차 원칙 - Line이 Space보다 큼. 두 값 중 큰 쪽을 Line으로 배정.
            if value0 >= value1:
                cand = (item, value0, value1, err_a)
            else:
                cand = (item, value1, value0, err_b)
        elif err_a < err_b:
            cand = (item, value0, value1, err_a)
        else:
            cand = (item, value1, value0, err_b)
        if best is None or cand[3] < best[3]:
            best = cand

    item, line_val, space_val, _ = best
    return (item.name,
            line_val, item.target_line, round(line_val - item.target_line, 3), item.tolerance_line,
            space_val, item.target_space, round(space_val - item.target_space, 3), item.tolerance_space)


# ------------------------------------------------------------
#  판독 이상치 경보 (2026-08-05)
# ------------------------------------------------------------
#  OCR이 여러 밝기 기준에서 모두 같은 방향으로 틀리면 어떤 교차검증도 못 막음:
#    - 기준별 만장일치 검사 → 다 똑같이 틀렸으니 통과
#    - 값 = √(X²+Y²) 검사   → 값과 좌표를 함께 잘못 읽으면 관계식은 그대로 성립
#  실제로 밝기 기준 210에서 100.2를 400.2로 읽으면서 신뢰도 0.888을 준 사례가
#  있었음. 계측 데이터에서 제일 나쁜 실패는 "못 읽음"이 아니라 "그럴듯하게
#  틀린 값이 조용히 들어가는 것"이라, 마지막 그물이 필요함.
#
#  ⚠️ 스펙이탈과는 **다른 상태**임. 헷갈리면 안 됨:
#     스펙이탈  = 공정 결과가 규격 밖 (진짜 문제, 사람이 조치해야 함)
#     판독의심  = 이 값을 믿기 어렵다 (사진을 다시 봐야 함)
#  값을 바꾸거나 지우지 않고 표시만 한다.

# [1차] Target 대비. 개수와 무관하게 항상 적용.
# 포토 공정에서 CD가 Target의 2배가 되거나 절반이 되는 일은 없음 — 그건 공정
# 문제가 아니라 판독 문제임(100.2를 400.2로 읽는 자릿수 오독 등). 진짜 공정
# 이탈은 Tolerance의 몇 배 수준이지 배수로 가지 않으므로 서로 안 겹침.
OUTLIER_TARGET_RATIO = 2.0

# [2차] 같은 항목의 동료 값 대비. 이상치 자신에게 오염되지 않도록 평균이 아니라
# **중앙값**을 기준으로 삼음.
#
# ⚠️ 처음엔 중앙값+MAD(수정 z-점수)를 쓰려 했는데 **우리 데이터에서는 못 씀.**
# 계측기가 소수점 한 자리로 내보내서 같은 값이 반복되면 MAD가 정확히 0이 되고,
# 하한을 걸면 그 하한이 곧 산포 기준이 되어버려 0.3um 차이(Tolerance ±2 안의
# 정상 산포)까지 이상치로 잡힘. 실제로 Sample3의 40.1(중앙값 40.4)과 Sample4의
# 19.9(중앙값 19.6)가 오탐으로 걸렸음. 하한을 키우면 이번엔 진짜 오독을 놓침.
#
# 그래서 **산포 척도를 데이터에서 추정하지 않고 Tolerance를 쓴다.** Tolerance는
# "이 정도 산포는 정상"이라는 공정의 기준 그 자체라 목적에 정확히 맞고, 값이
# 반복되든 말든 흔들리지 않음. 진짜 공정 이동은 값들이 통째로 같이 움직여
# 중앙값도 따라가므로 안 걸리고, 한 값만 튀는 판독 오류만 걸림.
OUTLIER_TOL_MULTIPLE = 3.0
OUTLIER_MIN_N = 5


def _median(values):
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def find_ocr_outliers(rows):
    """판독을 의심할 행을 찾아 [(행, 사유), ...]로 반환. 값은 건드리지 않음.

    rows: 엑셀에 들어갈 딕셔너리 목록('항목','Target','측정값(um)' 필요).
    Target이 없는 행(Overlay 등)은 비교 기준이 없어 대상에서 빠짐."""
    groups = {}
    for r in rows:
        name, target = r.get('항목'), r.get('Target')
        if not name or target in (None, '') or not target:
            continue
        groups.setdefault(name, []).append(r)

    found = []
    for entries in groups.values():
        target = entries[0]['Target']

        for r in entries:
            v = r['측정값(um)']
            if v > target * OUTLIER_TARGET_RATIO or v < target / OUTLIER_TARGET_RATIO:
                found.append((r, f'판독의심: Target({target:g})의 {v / target:.1f}배'))

        # 동료 비교는 표본이 어느 정도 있어야 중앙값이 의미가 있음.
        # Tolerance가 없는 항목(기준표에 없는 Target)은 산포의 척도가 없어 건너뜀.
        tolerance = entries[0].get('Tolerance')
        if len(entries) < OUTLIER_MIN_N or tolerance in (None, ''):
            continue
        limit = tolerance * OUTLIER_TOL_MULTIPLE
        med = _median([r['측정값(um)'] for r in entries])
        for r in entries:
            gap = abs(r['측정값(um)'] - med)
            if gap > limit:
                found.append((r, f'판독의심: 같은 항목 중앙값({med:g})에서 '
                                 f'{gap:.1f} 벗어남(허용 {limit:g})'))
    return found


# ------------------------------------------------------------
#  검증용 요약: Item별 "예상 포인트 수" vs "실제 매칭된 개수"
# ------------------------------------------------------------
def summarize_matching(rows, plan):
    """rows: 엑셀에 들어갈 딕셔너리 목록 (각 행에 '항목' 키가 있어야 함).
       Item별로 몇 개나 매칭됐는지 세어 예상 포인트 수와 비교."""
    # Line과 Space가 둘 다 있는 Item은 한 포인트가 두 행(-Line/-Space)으로
    # 나뉘므로 Line 쪽만 세야 "포인트" 수가 맞음.
    # ⚠️ 한쪽만 있는 Item(Space만 있는 Item 등)은 그 한 행이 곧 한 포인트라
    # 건너뛰면 실제 매칭이 0으로 보임 — 2026-08-05에 실제로 이 증상이 나왔음.
    paired = {it.name for it in plan.ls_items
              if it.target_line is not None and it.target_space is not None}

    matched_count = {}
    for r in rows:
        name = r.get('항목')
        if not name:
            continue
        if name.endswith('-Line'):
            name = name[:-len('-Line')]
        elif name.endswith('-Space'):
            base = name[:-len('-Space')]
            if base in paired:
                continue          # 짝이 있는 Item은 Line 쪽에서 이미 셌음
            name = base
        matched_count[name] = matched_count.get(name, 0) + 1

    summary = []
    for item in list(plan.cd_items) + list(plan.ls_items):
        actual = matched_count.get(item.name, 0)
        summary.append({
            '항목': item.name,
            '예상 포인트': item.points,
            '실제 매칭': actual,
            '일치': '예' if actual == item.points else '아니오',
        })
    return summary


# ------------------------------------------------------------
#  화면/문서 표시용 이름: 내부 식별자(항목) 대신 'Target값 종류'로 보여줌
#  (예: "Pad CD Item 1" -> "14.5 Pad CD", "...-Line" -> "9.5 Line")
#  매칭/그룹핑용 '항목' 키 자체는 그대로 두고, 표시할 때만 이 이름을 씀.
#  Line/Space는 Target 값이 같아도 뒤에 붙는 단어(Line/Space)로 구별됨.
# ------------------------------------------------------------
def display_item_name(name, target, plan):
    if target in (None, ''):
        return name
    if name.endswith('-Line'):
        return f'{target:g} Line'
    if name.endswith('-Space'):
        return f'{target:g} Space'
    return f'{target:g} {plan.cd_label}'


# ------------------------------------------------------------
#  통계/Cpk 계산: 항목(Line&Space는 -Line/-Space 각각)별로 모아서 계산
# ------------------------------------------------------------
def compute_stats(rows, plan):
    """rows: 엑셀에 들어갈 딕셔너리 목록. 각 행에 '항목','측정값(um)','Target',
       'Tolerance' 키가 있어야 함 (Target 매칭이 안 된 행은 자동 제외).
       항목별 N/Avg/Std/Max/Min/Range/USL/LSL/Cp/Cpk/표시명 목록을 반환.
       표준편차는 표본 표준편차(n-1로 나눔, 엑셀 STDEV()와 동일)를 씀."""
    groups = {}
    for r in rows:
        name = r.get('항목')
        target = r.get('Target')
        if not name or target == '' or target is None:
            continue
        groups.setdefault(name, []).append(r)

    results = []
    for name, entries in groups.items():
        values = [e['측정값(um)'] for e in entries]
        target = entries[0]['Target']
        tolerance = entries[0].get('Tolerance')
        n = len(values)
        mean = statistics.mean(values)
        std = statistics.stdev(values) if n > 1 else 0.0  # 엑셀 STDEV()와 동일 (표본, n-1)

        usl = lsl = cp = cpk = None
        if tolerance not in (None, ''):
            usl = round(target + tolerance, 4)
            lsl = round(target - tolerance, 4)
            if std > 0:
                cp = round((usl - lsl) / (6 * std), 3)
                cpk = round(min((usl - mean) / (3 * std), (mean - lsl) / (3 * std)), 3)

        # 3-Sigma(3σ)와 CDU[%] — 산포를 평균 대비 비율로 환산한 균일도 지표.
        # 측정이 1개뿐이면 표본 표준편차 자체가 정의되지 않으므로(n>=2 필요),
        # 0으로 보여서 "산포가 없다=완벽"으로 오해하지 않도록 None으로 둠.
        sigma3 = cdu = None
        if n > 1:
            sigma3 = round(3 * std, 4)
            if mean:
                cdu = round(sigma3 / mean * 100, 2)

        # Overall 판정: 이 항목의 측정값이 하나라도 스펙(USL/LSL)을 벗어나면 FAIL.
        # Tolerance가 없어 스펙 자체를 정하지 못한 항목은 판정하지 않음(None).
        verdict = None
        if tolerance not in (None, ''):
            verdict = 'FAIL' if any(e.get('스펙이탈') == '예' for e in entries) else 'PASS'

        results.append({
            '항목': name,
            '표시명': display_item_name(name, target, plan),
            'N': n,
            'Avg': round(mean, 4),
            'Std': round(std, 4),
            'Max': round(max(values), 4),
            'Min': round(min(values), 4),
            'Range': round(max(values) - min(values), 4),
            '3σ': sigma3,
            'CDU%': cdu,
            'Target': target,
            'Tolerance': tolerance,
            'USL': usl,
            'LSL': lsl,
            'Cp': cp,
            'Cpk': cpk,
            '판정': verdict,
        })
    return results


# ------------------------------------------------------------
#  결과 화면용 Item별 분류 (확인필요/스펙이탈/겹침/포인트 수 불일치)
# ------------------------------------------------------------
def compute_item_breakdown(rows, plan, unread_by_file):
    """확인필요·스펙이탈·겹침·포인트 수 불일치를 실행 전체 합계 하나가 아니라
       Item별로 나눠서 반환한다(2026-08-12, 결과 화면 개편 요청).

       rows: 엑셀에 들어갈 딕셔너리 목록(각 행에 '항목'·'종류'·'파일명'·
             '확인필요'·'스펙이탈' 키가 있어야 함).
       unread_by_file: {파일명: True} - "[겹침]"으로 표시된(줄 일부를 못 읽은)
             사진의 파일명 집합. 이 함수가 로그 문자열 형식을 몰라도 되도록
             호출하는 쪽(core.unread_by_file)에서 미리 구조화해서 넘긴다.

       이름은 Cpk표(display_item_name)와 통일해서 "100 Pad CD"/"10 Line"
       처럼 보여준다 - 검증요약에서 쓰는 "Pad CD Item 1"과는 다른 이름이라
       사용자가 헷갈리지 않도록 여기서도 같은 함수를 그대로 씀.

       ⚠️ 알려진 한계: 사진 한 장을 글자 하나도 못 읽으면(rows가 아예 비어서)
       어느 Item 사진이었는지 알 수 없어 겹침 카운트에서 빠진다(OCR이 실패해야
       종류 판별도 같이 실패하므로). samples 5개 폴더 전부 이 경우(완전
       미판독)가 0건이라 지금까지는 실사용에 영향이 없었다."""
    matching = {s['항목']: s for s in summarize_matching(rows, plan)}

    def make_entry(raw_name, display_name, points, mismatch_key):
        sub = [r for r in rows if r.get('항목') == raw_name]
        flagged = sum(1 for r in sub if r.get('확인필요') == '예')
        out_of_spec = sum(1 for r in sub if r.get('스펙이탈') == '예')
        files = {r['파일명'] for r in sub}
        overlap = sum(1 for name in files if name in unread_by_file)
        m = matching.get(mismatch_key)
        return {
            'name': display_name, 'points': points,
            'flagged': flagged, 'out_of_spec': out_of_spec, 'overlap': overlap,
            'mismatch': bool(m) and m['일치'] == '아니오',
            'has_spec': True, 'has_mismatch': True,
        }

    entries = []
    for item in plan.cd_items:
        entries.append(make_entry(
            item.name, display_item_name(item.name, item.target, plan),
            item.points, item.name))
    for item in plan.ls_items:
        # Line/Space 표시명은 서로 다르지만("10 Line"/"20 Space"), 포인트 수
        # 불일치는 원래 Item(둘을 합친 것) 하나로만 판단한다 - 사진 한 장이
        # 곧 포인트 하나라 Line/Space로 나눠 셀 수 없기 때문(둘 다 있는
        # Item일 때 특히 중요 - summarize_matching과 같은 원칙).
        if item.target_line is not None:
            entries.append(make_entry(
                f'{item.name}-Line',
                display_item_name(f'{item.name}-Line', item.target_line, plan),
                item.points, item.name))
        if item.target_space is not None:
            entries.append(make_entry(
                f'{item.name}-Space',
                display_item_name(f'{item.name}-Space', item.target_space, plan),
                item.points, item.name))

    if plan.overlay_points:
        # Overlay는 Target/Tolerance가 없는 항목이라 스펙이탈·포인트 수
        # 불일치 개념 자체가 없음(has_spec/has_mismatch=False, 화면에서 "–").
        overlay_rows = [r for r in rows if r.get('종류') == 'Overlay']
        flagged = sum(1 for r in overlay_rows if r.get('확인필요') == '예')
        files = {r['파일명'] for r in overlay_rows}
        overlap = sum(1 for name in files if name in unread_by_file)
        entries.append({
            'name': 'Overlay', 'points': plan.overlay_points,
            'flagged': flagged, 'out_of_spec': 0, 'overlap': overlap,
            'mismatch': False, 'has_spec': False, 'has_mismatch': False,
        })

    return entries
