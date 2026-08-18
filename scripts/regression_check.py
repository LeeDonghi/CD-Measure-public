# -*- coding: utf-8 -*-
"""회귀 검증 — 코드를 고쳤을 때 판독 결과가 달라졌는지 자동으로 대조.

왜 만들었나 (2026-08-05)
------------------------
그전에는 CLAUDE.md에 기준값이 "5.5 Space Avg=5.3923..." 처럼 **글로만** 적혀
있었고, 확인은 사람이 프로그램을 돌려 눈으로 비교하는 수동 절차였음.
문제가 두 가지였다:

  1) 기준이 너무 성김. Avg 3개와 행 수만 봐서는 **사진 한 장이 통째로 안 읽혀도
     안 걸린다.** 실제로 9-1_22.png 한 장을 못 읽었는데 Avg는 멀쩡했음.
  2) 고칠 때마다 기준값을 다시 뜨는 것부터 시작하게 됨.

그래서 **사진 한 장 한 장의 판독 결과를 통째로** 기준값으로 고정한다.
뭘 고쳤을 때 "어느 사진 어느 줄이 달라졌는지"가 한 줄로 보이는 게 목적.

쓰는 법
-------
    python scripts/regression_check.py            # 기준값과 대조 (다르면 종료코드 1)
    python scripts/regression_check.py --update   # 기준값을 지금 결과로 갱신

⚠️ --update는 **변경이 의도한 것임을 확인한 뒤에만** 쓸 것. 갱신하면 그 diff가
곧 "이번 수정으로 무엇이 달라졌는지"의 증거가 되므로 커밋에 같이 넣는다.

두 층으로 나눠 본다
-------------------
  [1층] 판독 결과 — 측정 계획과 무관하게 "사진에서 무슨 값을 읽었는가".
        샘플 폴더 **전부**에 적용. OCR을 건드리는 수정이 여기서 걸린다.
  [2층] 매칭·통계 — 계획(Target)을 아는 폴더만. Cpk·Item 매칭이 그대로인가.
        Target 매칭 로직을 건드리는 수정이 여기서 걸린다.

`LS Sample`/`Sample2`/`Sample3`는 당시 입력한 계획이 기록에 안 남아 있어서
1층만 검사한다. 계획을 알게 되면 아래 PLANS에 한 줄 추가하면 2층도 걸린다.

⚠️ process_folder에 run_dir을 주지 않는다 — 주면 samples 폴더 안에 근거 파일이
생겨서 저장소가 더러워짐. 여기서는 판독 결과만 필요하다.
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import CD측정값_엑셀변환 as core                     # noqa: E402
from ocr_core import load_templates, read_image_ex   # noqa: E402
from measurement_plan import (MeasurementPlan, CDItem, LSItem,   # noqa: E402
                              summarize_matching, compute_stats)
from tolerance_table import lookup_tolerance, CD_PATTERN_BY_PROCESS  # noqa: E402
from make_demo_images import build_demo_folder, DEMO_TARGETS  # noqa: E402

SAMPLES_DIR = os.path.join(ROOT, 'samples')
BASELINE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'regression_baseline')

# 가짜 사진 폴더. 실사진(samples/)이 없는 공개 저장소에서도 회귀 검증이 돌아가게
# 하는 것이 목적 - 사진 자체는 .gitignore 대상이고, seed가 고정이라 언제든
# 똑같이 다시 만들어진다.
DEMO_DIR = os.path.join(ROOT, 'demo_photos')

# 계획을 아는 폴더만 2층까지 검사함.
#   cd: [(포인트수, Target), ...]
#   ls: [(포인트수, Line Target, Space Target), ...]  — 없는 쪽은 None
#       ⚠️ L&S Item은 Line/Space가 쌍이 아닐 수 있음(Item마다 독립).
#          Sample4가 실제 그런 경우 — Item1은 Line만, Item2는 Space만.
#
# Sample2/Sample3의 계획은 그 폴더에 남아 있던 옛 측정결과.xlsx에서 복원함
# (2026-08-05). '측정결과' 시트의 Target 열과 '검증요약' 시트의 '예상 포인트'가
# 곧 당시 입력값이라 추측이 아님. 그 엑셀들은 .gitignore 대상이라 저장소에는
# 없고 로컬 디스크에만 있었음 — 지워지면 이 정보도 같이 사라지므로 여기 적어둠.
PLANS = {
    # 사용자가 기억하고 있던 값(2026-08-05). L&S 사진만 있는 폴더라 CD·Overlay 없음.
    # Line과 Space Target이 **둘 다 2로 같음** — 그래서 이 폴더는 과제 4의 두
    # 안전장치가 실제로 돌아가는 유일한 회귀 대상임:
    #   1차) Target으로 못 가리므로 "큰 값 = Line" 원칙으로 배정
    #   2차) 크로스헤어 밝기로 그 배정이 맞는지 확인(ls_brightness.py)
    # 실제 값도 한쪽은 2.2~2.6, 다른 쪽은 1.6~1.8로 갈려서 원칙대로 배정됨.
    # 밝기 검증 코드를 고칠 때는 반드시 이 폴더로 확인할 것.
    'LS Sample': {'process': 'RDL', 'cd': [], 'ls': [(13, 2.0, 2.0)], 'overlay': 0},
    'Sample':  {'process': 'RDL', 'cd': [(13, 14.5)],
                'ls': [(13, 9.5, 5.5)], 'overlay': 13},
    # 사진 39장 = 13포인트 x 3장(CD/L&S/Overlay)으로 딱 맞아떨어져 overlay 13.
    # 옛 엑셀에 Overlay 행이 0인 것은 그때 overlay 사진이 L&S로 둔갑하던
    # 버그(과제 5) 때문이고, 이 폴더가 바로 그 버그 재현용이었음.
    'Sample2': {'process': 'RDL', 'cd': [(13, 15.0)],
                'ls': [(13, 5.0, 10.0)], 'overlay': 13},
    # ⚠️ 계획은 13포인트인데 이 폴더에는 측정 대상 사진이 12장뿐임(샘플로 일부만
    # 가져온 폴더). 그래서 매칭이 "예상 13 / 실제 11"로 어긋나는 게 정상이며,
    # 기준값은 그 상태 그대로를 고정한다. 기준값은 '맞는 값'이 아니라
    # '지금 값'이면 되고, 달라지면 걸리는 것이 목적이므로 문제없음.
    'Sample3': {'process': 'PI', 'cd': [(13, 40.0)],
                'ls': [], 'overlay': 0},
    'Sample4': {'process': 'RDL', 'cd': [(9, 100.0)],
                'ls': [(9, 10.0, None), (9, None, 20.0)], 'overlay': 9},
    # 공개 저장소용 가짜 사진 폴더(9포인트). Target 숫자를 여기 다시 적지 않고
    # DEMO_TARGETS를 그대로 쓰는 이유: 사진을 만드는 쪽과 검증하는 쪽의 Target이
    # 어긋나면 전부 스펙이탈로 잡히는데, 숫자를 두 군데 적어두면 한쪽만 고쳤을 때
    # 조용히 어긋난다. webapp/app.py의 _build_demo_plan()도 같은 값을 쓴다.
    'Demo': {'process': 'RDL',
             'cd': [(9, DEMO_TARGETS['pad_cd'])],
             'ls': [(9, DEMO_TARGETS['line'], DEMO_TARGETS['space'])],
             'overlay': 9},
}
# 'LS Sample'은 옛 결과 엑셀이 안 남아 있어 계획을 복원하지 못함 → 1층만 검사.
# CLAUDE.md 기록상 Line/Space Target이 서로 같았던 폴더(크로스헤어 밝기 검증이
# 전수 실행됐으므로)지만, 정확한 값은 모르므로 추측해서 넣지 않는다.

CD_LABEL_BY_PROCESS = {'RDL': 'Pad CD', 'PI': 'Via CD',
                       'Bump': 'UBM CD', 'Cu Post': 'Cu Post CD'}


def build_plan(spec):
    process = spec['process']
    cd_label = CD_LABEL_BY_PROCESS[process]
    pattern = CD_PATTERN_BY_PROCESS.get(process, 'CD')

    cd_items = [CDItem(f'{cd_label} Item {i}', pts, tgt,
                       lookup_tolerance(process, pattern, tgt))
                for i, (pts, tgt) in enumerate(spec['cd'], start=1)]

    ls_items = []
    for i, (pts, t_line, t_space) in enumerate(spec['ls'], start=1):
        ls_items.append(LSItem(
            f'Line&Space Item {i}', pts, t_line, t_space,
            lookup_tolerance(process, 'L/S', t_line) if t_line is not None else None,
            lookup_tolerance(process, 'L/S', t_space) if t_space is not None else None))

    return MeasurementPlan(process=process, cd_label=cd_label,
                           cd_items=cd_items, ls_items=ls_items,
                           overlay_points=spec['overlay'],
                           customer='회귀', material='회귀', layer='회귀')


def photo_paths(folder):
    return sorted(
        (os.path.join(folder, n) for n in os.listdir(folder)
         if n.lower().endswith(core.IMAGE_EXTENSIONS)),
        key=core.natural_sort_key)


def read_layer(folder, templates):
    """[1층] 사진별 판독 결과. 계획과 무관하게 "무엇을 읽었는가"만 담는다."""
    out = {}
    for path in photo_paths(folder):
        rows, line_count = read_image_ex(path, templates)
        out[os.path.basename(path)] = {
            '줄수': line_count,
            '판독': [[r['번호'], r['값'], r['X'], r['Y'], bool(r['확인필요'])]
                     for r in rows],
        }
    return out


def match_layer(folder, templates, spec):
    """[2층] 계획을 아는 폴더의 매칭·통계."""
    plan = build_plan(spec)
    rows, _, _ = core.process_folder(photo_paths(folder), templates, plan)
    return {
        '측정값행수': len(rows),
        '스펙이탈': sum(1 for r in rows if r.get('스펙이탈') == '예'),
        '확인필요': sum(1 for r in rows if r.get('확인필요')),
        '매칭': {s['항목']: [s['예상 포인트'], s['실제 매칭']]
                 for s in summarize_matching(rows, plan)},
        '통계': {s['표시명']: [s['N'], s['Avg'], s['Std'], s['Cpk'], s['판정']]
                 for s in compute_stats(rows, plan)},
    }


def collect(folders):
    """folders = [(표시이름, 폴더경로), ...] 를 받아 판독·분석 결과를 모은다."""
    templates = load_templates()
    result = {}
    for name, folder in folders:
        entry = {'판독': read_layer(folder, templates)}
        if name in PLANS:
            entry['분석'] = match_layer(folder, templates, PLANS[name])
        result[name] = entry
    return result


def sample_folders():
    """실사진 폴더들 (Private 저장소에만 있음)."""
    # 공개 저장소에는 samples/가 아예 없다. 그대로 두면 FileNotFoundError 스택이
    # 튀어나와서 처음 온 사람에게는 "고장난 프로그램"으로 보이므로 안내로 바꾼다.
    if not os.path.isdir(SAMPLES_DIR):
        print(f'실사진 폴더가 없습니다: {SAMPLES_DIR}')
        print('공개 저장소에는 실제 계측 사진이 들어 있지 않습니다.')
        print('가짜 사진으로 검증하려면 --demo 를 붙여 실행하세요:')
        print('   python scripts/regression_check.py --demo')
        sys.exit(2)

    print('샘플 폴더를 읽는 중...\n')
    return [(n, os.path.join(SAMPLES_DIR, n))
            for n in sorted(os.listdir(SAMPLES_DIR))
            if os.path.isdir(os.path.join(SAMPLES_DIR, n))]


def demo_folders():
    """가짜 사진 폴더. 없으면 그 자리에서 만든다.

    사진을 커밋하지 않는 대신 "필요하면 다시 만든다"로 가는 것이라 처음 한 번은
    생성 시간이 걸린다. seed가 고정이라 어느 컴퓨터에서 만들어도 같은 사진이
    나오므로 기준값(Demo.json)이 컴퓨터마다 달라지지 않는다.
    """
    if not os.path.isdir(DEMO_DIR) or not photo_paths(DEMO_DIR):
        print(f'가짜 사진이 없어 새로 만듭니다: {DEMO_DIR}')
        build_demo_folder(DEMO_DIR)
        print()
    return [('Demo', DEMO_DIR)]


def summarize(name, data):
    """현재 실패율 기준선 — 고치기 전/후를 숫자로 비교할 수 있게.

    ⚠️ "측정 전 사진"을 실패로 세면 안 됨. 계측기로 측정하기 전에 찍은 사진은
    흰 글자가 아예 없어서 줄수가 0인데, 이건 정상적으로 건너뛴 것이지 판독
    실패가 아님. 실제로 Sample 77장 중 38장이 여기 해당함 — 이걸 섞으면
    실패율이 절반으로 보여서 기준선이 거짓말을 하게 됨.
    """
    photos = data['판독']
    pre = full = partial = none = 0
    for v in photos.values():
        got, want = len(v['판독']), v['줄수']
        if want == 0:
            pre += 1              # 측정 전 사진 (정상적으로 건너뜀)
        elif got == want:
            full += 1
        elif got:
            partial += 1          # 일부 줄만 읽힘 (겹침 등)
        else:
            none += 1             # 줄은 있는데 하나도 못 읽음
    flagged = sum(1 for v in photos.values() for r in v['판독'] if r[4])
    values = sum(len(v['판독']) for v in photos.values())
    missing = sum(max(0, v['줄수'] - len(v['판독'])) for v in photos.values())
    bad = sorted(n for n, v in photos.items() if len(v['판독']) < v['줄수'])
    return {'사진': len(photos), '측정전': pre, '값': values, '완전판독': full,
            '부분판독': partial, '미판독': none, '못읽은줄': missing,
            '확인필요행': flagged, '문제사진': bad}


def diff_entry(path, old, new, out):
    """기준값과 지금 결과를 재귀적으로 비교해 다른 곳만 모은다."""
    if isinstance(old, dict) and isinstance(new, dict):
        for k in sorted(set(old) | set(new)):
            if k not in old:
                out.append(f'{path}/{k}: 기준값에 없던 것이 생김 → {new[k]}')
            elif k not in new:
                out.append(f'{path}/{k}: 없어짐 (기준값 {old[k]})')
            else:
                diff_entry(f'{path}/{k}', old[k], new[k], out)
    elif old != new:
        out.append(f'{path}: 기준 {old} → 지금 {new}')


def main():
    ap = argparse.ArgumentParser(description='samples 폴더 회귀 검증')
    ap.add_argument('--update', action='store_true',
                    help='기준값을 지금 결과로 갱신 (의도한 변경일 때만)')
    ap.add_argument('--demo', action='store_true',
                    help='실사진(samples/) 대신 가짜 사진으로 검증 (공개 저장소용)')
    args = ap.parse_args()

    os.makedirs(BASELINE_DIR, exist_ok=True)
    if args.demo:
        now = collect(demo_folders())
    else:
        now = collect(sample_folders())

    print('측정전 = 측정 전에 찍혀 글자가 없는 사진(정상 건너뜀, 실패 아님)')
    print(f'{"폴더":12s} {"사진":>4s} {"측정전":>5s} {"대상":>4s} {"값":>4s} '
          f'{"완전":>4s} {"부분":>4s} {"미판독":>6s} {"못읽은줄":>7s} {"확인필요":>7s}')
    for name, data in now.items():
        s = summarize(name, data)
        target = s['사진'] - s['측정전']
        print(f'{name:12s} {s["사진"]:4d} {s["측정전"]:5d} {target:4d} {s["값"]:4d} '
              f'{s["완전판독"]:4d} {s["부분판독"]:4d} {s["미판독"]:6d} '
              f'{s["못읽은줄"]:7d} {s["확인필요행"]:7d}')
        if s['문제사진']:
            print(f'   └ 문제 사진 {len(s["문제사진"])}장: {", ".join(s["문제사진"])}')

    changed = 0
    for name, data in now.items():
        path = os.path.join(BASELINE_DIR, f'{name}.json')
        if args.update or not os.path.exists(path):
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
                f.write('\n')   # pre-commit의 end-of-file-fixer와 안 싸우도록
            print(f'\n[{name}] 기준값 {"갱신" if args.update else "생성"}')
            continue

        with open(path, encoding='utf-8') as f:
            base = json.load(f)
        diffs = []
        diff_entry(name, base, data, diffs)
        if diffs:
            changed += len(diffs)
            print(f'\n[{name}] 기준값과 다름 — {len(diffs)}곳')
            for d in diffs[:40]:
                print('   ' + d)
            if len(diffs) > 40:
                print(f'   ... 외 {len(diffs) - 40}곳')

    print()
    if args.update:
        print('기준값을 갱신했습니다. git diff로 무엇이 달라졌는지 확인하고 커밋하세요.')
        return 0
    if changed:
        print(f'회귀 검증 실패 — {changed}곳이 기준값과 다릅니다.')
        print('의도한 변경이면 --update로 기준값을 갱신하세요.')
        return 1
    print('회귀 검증 통과 — 기준값과 완전히 동일합니다.')
    return 0


if __name__ == '__main__':
    # Windows cp949 콘솔은 em-dash(—) 등을 못 그려서 print()가 죽음 - 실행 자체는
    # 끝났는데 마지막 메시지 출력에서만 크래시하는 걸 방지 (CD측정값_엑셀변환.py와 동일 처리)
    sys.stdout.reconfigure(errors='replace')
    sys.exit(main())
