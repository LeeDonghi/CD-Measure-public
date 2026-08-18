# -*- coding: utf-8 -*-
# ============================================================
#  글자 템플릿(char_templates.pkl) 만드는 스크립트
# ------------------------------------------------------------
#  이미 눈으로 정답을 확인해둔 사진 속 줄들에서 0~9 숫자와 기호
#  모양을 잘라내 저장해둠. ocr_core.py가 이 파일을 읽어서 사용함.
#
#  나중에 오독이 잦은 숫자가 생기면, KNOWN 목록에 (파일명, 박스,
#  정답문자열)을 하나 더 추가하고 이 스크립트를 다시 실행하면
#  템플릿이 보강됨.
# ============================================================
import pickle
import os
from ocr_core import get_white_mask, _segment_chars, _char_bitmap, find_line_boxes

SAMPLE_DIR = os.path.join(os.path.dirname(__file__), 'samples', 'Sample')

# (파일명, 텍스트 줄 박스(y0,y1,x0,x1), 정답 문자열 — 'um' 단위는 제외)
# 박스 좌표는 find_line_boxes()로 찾은 값을 그대로 사용함.
KNOWN = [
    ('CaptImg20260619103208.bmp', (272, 290, 654, 843), '2=6.8,XY=(0.0,6.8)'),
    ('CaptImg20260619103208.bmp', (490, 508, 439, 627), '1=7.2,XY=(7.2,0.0)'),
    ('CaptImg20260619103208.bmp', (492, 510, 830, 1019), '0=7.0,XY=(7.0,0.0)'),
    ('CaptImg20260619103208.bmp', (704, 722, 654, 843), '3=6.5,XY=(0.2,6.5)'),
    ('CaptImg20260619094329.bmp', (721, 739, 413, 620), '0=15.1,XY=(15.1,0.0)'),
    ('CaptImg20260619092310.bmp', (394, 412, 752, 941), '0=5.2,XY=(0.0,5.2)'),
    ('CaptImg20260619092310.bmp', (451, 469, 858, 1046), '1=9.4,XY=(0.0,9.4)'),
]


def build():
    templates = {}
    for fname, box, truth in KNOWN:
        path = os.path.join(SAMPLE_DIR, fname)
        mask = get_white_mask(path)
        y0, y1, x0, x1 = box
        segs = _segment_chars(mask, y0, y1, x0, x1)
        chars = list(truth)
        if len(segs) < len(chars):
            print(f'[경고] {fname} {box}: 조각 부족 (조각 {len(segs)} < 정답 {len(chars)}) -> 건너뜀')
            continue
        segs = segs[:len(chars)]  # 뒤에 붙는 'um' 잔여 조각은 버림
        for seg, ch in zip(segs, chars):
            bmp = _char_bitmap(mask, y0, y1, x0, x1, seg)
            templates.setdefault(ch, []).append(bmp)
    return templates


if __name__ == '__main__':
    templates = build()
    out_path = os.path.join(os.path.dirname(__file__), 'char_templates.pkl')
    with open(out_path, 'wb') as f:
        pickle.dump(templates, f)
    print(f'저장 완료: {out_path}')
    print('템플릿 종류:', sorted(templates.keys()))
    for ch, bmps in sorted(templates.items()):
        print(f'  {repr(ch)}: {len(bmps)}개')
