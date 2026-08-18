# -*- coding: utf-8 -*-
# ============================================================
#  템플릿 매칭 기반 OCR 핵심 로직
# ------------------------------------------------------------
#  이 계측기 사진은 글자 폰트와 색상(흰색)이 항상 고정되어 있다는
#  특징이 있음. 그래서 범용 OCR(Tesseract)로 애매하게 읽는 대신,
#  이미 정답을 확인해둔 숫자 모양(템플릿)과 비교해서 제일 비슷한
#  글자를 고르는 방식을 씀. 훨씬 정확하고 빠름.
#
#  글자 하나하나를 잘라 비교하므로, 한 줄 전체를 한번에 읽으려다
#  실패하는 예전 방식의 문제(예: 4를 2로, 6을 8로 오독)가 크게 줄어듦.
# ============================================================
import pickle
import os
import re
import math
import numpy as np
from PIL import Image
from scipy import ndimage

TEMPLATE_SIZE = (16, 24)   # 글자 하나를 이 크기로 맞춰서 비교
CONFIDENCE_THRESHOLD = 0.85  # 이보다 신뢰도가 낮으면 "확인 필요"로 표시

# [교차검증용 허용 오차]
# 한 줄에는 "값"과 "(X, Y)" 세 숫자가 있는데, 실제 사진 113줄을 분석해 보니
# 값 = √(X² + Y²), 즉 값은 좌표 벡터 (X, Y)의 길이와 같아야 함을 확인함.
# (112줄은 오차 0.012 이하로 일치, 1줄만 0.088 어긋남.)
# 값과 (X, Y)는 서로 독립적인 숫자이므로, 이 관계가 깨지면 둘 중 하나가
# 이상한 것 → 사람이 확인해야 할 줄로 봄. 두 가지 원인을 다 잡아냄:
#   (1) OCR이 값 또는 좌표를 잘못 읽은 경우
#   (2) 계측기가 값과 좌표를 서로 안 맞게 출력한 경우(원본 데이터 불일치)
# 이 값(0.05)보다 더 벌어지면 확인필요로 표시함. (정상 줄의 최대 오차 0.012와
# 이상 줄의 오차 0.088 사이를 깔끔하게 가르는 여유값.)
REDUNDANCY_TOLERANCE = 0.05

_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), 'char_templates.pkl')

# 사진 속 측정값 한 줄의 형식: "번호=값,XY=(X좌표,Y좌표)"
# (쉼표/마침표는 저해상도에서 서로 헷갈릴 수 있어 관대하게 처리)
#
# 값과 좌표 사이의 ",XY" 부분은 글자 그대로 요구하지 않고 "아무 글자 3개까지"로
# 둠. 'X'와 'Y'가 서로 맞닿게 그려지면 두 글자가 한 덩어리로 잘려 엉뚱한 글자
# (주로 '7')로 읽히는데, 예전에는 이때 줄 전체를 버렸음. 정작 번호·값·좌표는
# 멀쩡히 읽히는데도 버려서 Sample3에서는 14장 중 12장을 통째로 놓쳤음.
# 여기서 잘못 읽을 위험은 아래 "값 = √(X²+Y²)" 교차검증이 막아줌
# (더 느슨하게 풀면 실제로 오독이 생기는 것을 4개 폴더 전수 비교로 확인함).
#
# 앞의 `^`(줄 맨 앞 고정)를 2026-08-08에 뗐음. 두 라벨이 나란히 붙어 한 박스로
# 묶인 사진(LS Sample/4 (45).bmp: 폭 341 = 정상 171 x 2)은 **뒤쪽 라벨이 멀쩡한데도**
# 맨 앞부터만 보느라 통째로 버려졌음. 고정을 떼면 박스 중간에서도 찾음.
# 위험(맨 앞 글자를 오독해도 그 뒤부터 억지로 맞춰 엉뚱한 번호를 만들 수 있음)은
# 아래 "값 = √(X²+Y²)" 교차검증 + 라벨이 여러 개 섞인 박스를 확인필요로 돌리는
# MULTI_LABEL_CHARS 규칙이 함께 막아줌.
LINE_RE = re.compile(r'(\d)=(\d+\.\d).{0,3}=\((\d+\.\d)[,.](\d+\.\d)\)')

# 한 박스에 라벨이 두 개 이상 들어 있다고 보는 글자 수. 측정줄 한 줄은 글자가
# 20~24개고, 두 라벨이 한 박스로 묶이면 41~44개가 됨(5폴더 실측). 그 사이를 가름.
#
# 왜 확인필요로 돌리는가: 이런 박스에서 읽은 값은 두 라벨의 픽셀이 섞인 구간을
# 지날 수 있는데, 값=√(X²+Y²) 교차검증이 이걸 항상 잡아주지는 못함. X가 크고 Y가
# 작은 라벨(예: X=14.4)은 Y가 0.0이든 0.4든 둘 다 허용오차 안에 들어와서 못 가림
# (2026-08-08 Sample2/154103에서 실제로 확인). 그래서 값은 그대로 쓰되 사람이 한
# 번 보게 표시함 — 계측 프로그램에서 확인 안 된 값이 조용히 지나가면 안 되므로.
MULTI_LABEL_CHARS = 30


def load_templates():
    with open(_TEMPLATE_PATH, 'rb') as f:
        return pickle.load(f)


def get_white_mask(path, thresh=170):
    """사진에서 흰색(측정값 글자) 부분만 True로 표시한 마스크를 만듦."""
    img = Image.open(path).convert('RGB')
    arr = np.array(img)
    r, g, b = arr[:, :, 0].astype(int), arr[:, :, 1].astype(int), arr[:, :, 2].astype(int)
    return (r > thresh) & (g > thresh) & (b > thresh)


# 글자만 남았을 때 흰 픽셀은 보통 전체의 0.1% 남짓임. 이 비율을 크게 넘으면
# 사진이 밝아서 배경까지 흰색으로 잡힌 것으로 보고 기준을 올림.
MAX_WHITE_RATIO = 0.015
# 170 다음이 원래 190이었는데, 그 사이가 너무 넓어서 딱 맞는 기준을 지나쳐버리는
# 사진이 있었음(Sample2/CaptImg20260709153329.bmp: 170에서 9.4%라 실패 → 180이면
# 0.35%로 딱 맞는데 후보에 없어서 190으로 점프 → 글자가 과하게 깎여 1을 Y·4로 오독).
# 기준이 높을수록 획이 얇아져 1↔4, 1↔Y 오독이 늘고, 심하면 틀린 값이 형식 검사를
# 통과하기까지 함(이 사진을 220으로 읽으면 14.8이 44.8로 읽히고도 통과). 그래서
# 가능한 한 낮은 기준에 착지시키는 게 정확도·안전 양쪽에 유리함. (2026-08-07)
_THRESH_STEPS = (170, 180, 190, 200, 210, 220)


# "측정줄처럼 생긴 박스"의 조건. 밝기 기준을 고를 때 쓴다.
# 흰 픽셀 비율만으로는 좋은 기준과 나쁜 기준을 못 가름 — 기준 180에서
# Sample2/153329는 0.353%(글자가 제대로 나옴), Sample3/142042는 0.410%
# (글자가 배경과 붙어 뭉개짐)로 거의 같았음. 비율이 아니라 "측정줄 모양이
# 나오느냐"로 판단해야 둘이 갈림. (2026-08-07 실측)
#
# 폭 150 이상: 정상 측정줄은 189~190px이고, 기준이 나쁠 때 나오는 부스러기
#   덩어리는 100px 안팎이라 그 사이를 가름(MIN_LINE_WIDTH=100은 "측정줄이
#   아닌 것"을 거르는 더 느슨한 기준이라 여기 쓰면 부스러기가 통과함).
# 높이 15~28: 정상은 19px이고, 자국이 붙거나 두 줄이 겹치면 28px까지 커짐.
_LINE_LIKE_MIN_WIDTH = 150
_LINE_LIKE_HEIGHT = (15, 28)


def _looks_like_line(mask):
    """이 마스크에서 측정줄로 보이는 박스가 하나라도 나오는지."""
    lo, hi = _LINE_LIKE_HEIGHT
    for (y0, y1, x0, x1) in find_line_boxes(mask):
        if lo <= y1 - y0 + 1 <= hi and x1 - x0 + 1 >= _LINE_LIKE_MIN_WIDTH:
            return True
    return False


def get_text_mask(path):
    """밝은 사진에서는 기본 기준(170)으로 배경까지 흰색으로 잡히므로,
       기준을 단계적으로 올려가며 글자만 남는 지점을 찾음.
       (배경이 분홍빛으로 밝은 사진에서 12만 픽셀이 잡히던 문제 대응)

       기준은 **낮을수록 좋음** — 높이면 획이 얇아져 1을 4나 Y로 오독하고,
       심하면 틀린 값이 형식 검사까지 통과함(153329를 220으로 읽으면 14.8이
       44.8로 읽히고도 통과). 그래서 낮은 쪽부터 올라가며 **측정줄 모양이
       처음 나오는 기준**에서 멈춘다.

       측정줄이 아예 없는 사진(측정 전에 찍은 것 등)은 어느 기준에서도 안
       걸리므로, 그때는 예전 방식대로 흰 픽셀이 충분히 적은 첫 기준을 씀."""
    fallback = None
    for th in _THRESH_STEPS:
        mask = get_white_mask(path, thresh=th)
        if _looks_like_line(mask):
            return mask
        if fallback is None and mask.mean() <= MAX_WHITE_RATIO:
            fallback = mask
    return fallback if fallback is not None else mask


# 글자줄 묶기용 부풀리기 범위: 세로 ±2 (한 글자의 위아래 획을 잇기 위해 필요),
# 가로 ±5 (한 줄 안의 글자 사이는 잇되, 나란히 찍힌 다른 측정줄과는 안 붙게).
# 예전에는 가로 ±14였는데, 그러면 옆에 나란히 찍힌 측정줄까지 한 덩어리로
# 붙어버려 글자가 뒤섞이고 그 줄을 통째로 못 읽었음(LS Sample 7 (43).bmp 등).
LINE_DILATION = np.ones((5, 11))

# 측정줄 하나의 대략적인 가로 폭(글자 수에 따라 170~210px). 성공적으로 읽은
# 줄이 하나도 없어 기준을 못 잡을 때만 쓰는 기본값.
DEFAULT_LINE_WIDTH = 190
MIN_LINE_WIDTH = 100        # 이보다 좁으면 측정줄이 아님(화면 상단 안내문구 등)

# 측정줄 한 줄의 글자 높이는 항상 19px이고, 두 줄이 겹쳐 붙어도 28px을 넘지 않음
# (4개 폴더 187줄 전수 확인). 반면 밝은 패드(원형 무늬)가 흰색으로 잡히면 높이가
# 180px쯤 되는 큰 덩어리가 생겨서 글자줄로 오인됨 -> 이 상한으로 걸러냄.
MAX_LINE_HEIGHT = 40

# 줄박스의 표준 여백. 부풀리기(LINE_DILATION) 때문에 박스는 글자보다 위로 2행,
# 아래로 5행이 더 크게 잡히는데, 이 값이 우연이 아니라 항상 같음 — 5개 샘플
# 폴더의 정상 줄박스 239개가 예외 없이 (위 2행 / 글자 12행 / 아래 5행)이었음
# (2026-08-07 실측).
#
# 문제는 글자 아래에 흐릿한 자국이 같이 찍힌 사진(Sample4/9-1_22.png). 자국이
# 같은 덩어리로 묶여서 아래 여백이 5행이 아니라 13행이 되고, 박스가 27px로
# 커진다. 그러면 두 가지가 한꺼번에 망가진다:
#   (a) 자국 픽셀이 글자와 글자 사이 빈칸을 메워버려 _segment_chars가 이웃
#       글자를 한 덩어리로 인식함(8+7+2px 짜리 세 글자가 17px 하나로).
#   (b) _char_bitmap이 박스 높이 전체를 16x24로 줄이므로 글자가 세로로 눌려
#       템플릿과 안 맞음.
# 그래서 여백이 표준보다 많으면 표준만큼만 남기고 잘라낸다. 늘리지는 않으므로
# 정상 박스(이미 위2/아래5)와 글자가 작은 박스는 값이 그대로다.
#
# 잉크 20% 기준: 진짜 글자 행은 흰 픽셀 36~73개, 자국 행은 2~7개라 10배 차이가
# 나서 어디를 잘라도 같은 결과가 나옴. 가로로 글자를 쪼개는 방식(2026-08-07에
# 두 가지 시도)은 전부 실패했는데, 조각을 쪼개기 전에 박스 자체가 이미
# 망가져 있었던 게 원인이었음.
CORE_INK_RATIO = 0.20
CORE_PAD_TOP = 2
CORE_PAD_BOTTOM = 5


def _trim_box_rows(mask, y0, y1, x0, x1):
    """박스 위아래에 붙은 '글자가 아닌' 행을 표준 여백만 남기고 잘라냄."""
    prof = mask[y0:y1 + 1, x0:x1 + 1].sum(axis=1)
    core = np.where(prof >= prof.max() * CORE_INK_RATIO)[0]
    if len(core) == 0:
        return y0, y1
    return (max(y0, y0 + int(core[0]) - CORE_PAD_TOP),
            min(y1, y0 + int(core[-1]) + CORE_PAD_BOTTOM))


def find_line_boxes(mask):
    """흰 글자 덩어리를 '한 줄' 단위로 묶어 바운딩 박스 목록을 반환."""
    dil = ndimage.binary_dilation(mask, structure=LINE_DILATION, iterations=1)
    labeled, n = ndimage.label(dil)
    boxes = []
    for i in range(1, n + 1):
        ys, xs = np.where(labeled == i)
        if len(xs) < 50:
            continue
        y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
        if (y1 - y0) < 6 or (x1 - x0) < 20:
            continue
        if (y1 - y0 + 1) > MAX_LINE_HEIGHT:
            continue      # 글자줄이 아님 (밝은 패드 무늬 등)
        y0, y1 = _trim_box_rows(mask, y0, y1, x0, x1)
        boxes.append((int(y0), int(y1), int(x0), int(x1)))
    return boxes


# 글자 하나의 최대 폭. 붙어버린 글자를 쪼갤지 판단하는 기준이다.
#  왜 13인가: 샘플 5개 폴더(Sample/Sample2/Sample3/Sample4/LS Sample)의 글자
#  덩어리 6355개 폭을 전수 조사한 결과 99.3%가 13px 이하였음. 14px 이상은
#  45개(0.7%)뿐이고 22px에 뭉치가 하나 더 있는데(26개) 그건 두 글자가 붙은 것.
#  추측이 아니라 실측으로 정한 값이므로, 폰트가 바뀌지 않는 한 건드리지 말 것.
#  2026-08-07에 13 -> 12로 낮춤: Sample3/142042는 '('(4px)와 '4'(7px)가 간격 2px로
#  붙어 정확히 13px이 되는 바람에 "13 초과"라는 조건을 1픽셀 차이로 못 넘겨 안
#  쪼개졌음. 그 한 글자 때문에 나머지가 다 맞는 줄을 통째로 버리고 있었음.
MAX_CHAR_WIDTH = 12
# 이보다 좁은 조각은 글자로 볼 수 없으므로 그런 위치에서는 안 쪼갬.
# (끝에서 1~2px만 떼어내면 글자가 아니라 획 부스러기가 됨)
MIN_CHAR_WIDTH = 3
# 쪼개기를 반복할 최대 횟수. 3번이면 한 덩어리를 최대 8조각까지 낼 수 있어
# 실제로 붙는 개수(2~3개)보다 충분히 넉넉함. 무한 재귀 방지용 안전장치.
MAX_SPLIT_DEPTH = 3


def _split_wide_seg(col_ink, s0, s1, depth=0):
    """붙어버린 글자 덩어리를 '세로 투영 골짜기'에서 쪼갬.

    왜 이게 되는가: 이 계측기 글자는 사람이 쓴 게 아니라 소프트웨어가 그린 것이라
    폰트·글자폭·높이(19px)가 항상 똑같다. 그래서 "이 폭보다 넓으면 두 글자가
    붙은 것"이라고 단정할 수 있다.

    쪼갤 위치는 열마다 흰 픽셀 수를 세어(=세로 투영) 가장 적은 열을 고른다.
    두 글자가 맞닿은 지점은 획이 스치기만 해서 잉크가 제일 얇기 때문.
    자동차 번호판 OCR에서 쓰는 표준 기법이다.

    ⚠️ 이진화(밝기 기준 조정·Sauvola 등)로 고치려던 시도는 2026-08-05에 6가지를
    다 해보고 전부 실패했음. 우리 글자는 "흰 종이 위 검은 글자"가 아니라 "사진 위에
    덧그린 흰 글자"라 주변 밝기에 기준선이 없어서 문서용 이진화가 안 맞음.
    그래서 이진화가 아니라 '분해'를 고치는 이 방향으로 온 것 — 되돌리지 말 것.
    """
    width = s1 - s0 + 1
    if width <= MAX_CHAR_WIDTH or depth >= MAX_SPLIT_DEPTH:
        return [(s0, s1)]

    # 양 끝은 후보에서 제외한다. 끝에서 자르면 한쪽이 MIN_CHAR_WIDTH보다 좁은
    # 부스러기가 되어 오히려 글자를 망가뜨림.
    lo, hi = s0 + MIN_CHAR_WIDTH, s1 - MIN_CHAR_WIDTH
    if hi < lo:
        return [(s0, s1)]

    inner = col_ink[lo:hi + 1]
    thinnest = inner.min()
    # 제일 얇은 열이 여러 개면 가운데에 가까운 것을 고른다. 폰트가 고정이라
    # 붙은 두 글자는 대체로 반씩 차지하기 때문.
    middle = (s0 + s1) / 2
    candidates = [lo + i for i, v in enumerate(inner) if v == thinnest]
    cut = min(candidates, key=lambda c: abs(c - middle))

    # 맞닿은 열 자체는 두 글자의 획이 섞여 있으므로 어느 쪽에도 주지 않고 버린다.
    return (_split_wide_seg(col_ink, s0, cut - 1, depth + 1)
            + _split_wide_seg(col_ink, cut + 1, s1, depth + 1))


def _segment_chars(mask, y0, y1, x0, x1):
    """한 줄 안에서 글자 하나하나의 (x시작,x끝) 목록을 찾음."""
    line = mask[y0:y1 + 1, x0:x1 + 1]
    col_has = line.any(axis=0)
    # 열마다 흰 픽셀이 몇 개인지. 골짜기(제일 얇은 곳)를 찾는 데 씀.
    col_ink = line.sum(axis=0)
    segs = []
    in_char = False
    for i, v in enumerate(col_has):
        if v and not in_char:
            start = i
            in_char = True
        elif not v and in_char:
            segs.append((start, i - 1))
            in_char = False
    if in_char:
        segs.append((start, len(col_has) - 1))

    # 빈칸으로 갈라지지 않고 붙어버린 덩어리를 여기서 한 번 더 쪼갬.
    split = []
    for s0, s1 in segs:
        split.extend(_split_wide_seg(col_ink, s0, s1))
    return split


def _char_bitmap(mask, y0, y1, x0, x1, seg):
    """글자 하나를 잘라 정해진 크기의 흑백 비트맵으로 만듦."""
    sx0, sx1 = x0 + seg[0], x0 + seg[1] + 1
    glyph = mask[y0:y1 + 1, sx0:sx1]
    im = Image.fromarray((glyph * 255).astype(np.uint8))
    im = im.resize(TEMPLATE_SIZE, Image.NEAREST)
    return np.array(im) > 127


def _classify(bmp, templates):
    """글자 비트맵 하나를 템플릿들과 비교해 제일 비슷한 문자와 점수를 반환."""
    best_ch, best_score = None, -1.0
    for ch, bmps in templates.items():
        for t in bmps:
            score = (bmp == t).mean()
            if score > best_score:
                best_score, best_ch = score, ch
    return best_ch, best_score


def decode_line_text(mask, box, templates, max_chars=22):
    """줄 하나(box)를 글자별로 읽어 (읽은 글자열, 글자별 점수)를 반환.

    형식 검사(LINE_RE) 전 단계라서 **판독에 실패한 줄도 "무엇으로 읽혔는지"**를
    볼 수 있음. 원인 분석에는 이게 결정적임 — 예를 들어 9-1_22.png는
    "047=0474Y447Y474=4=4YY"로 읽혔는데, 정상 사진과 글자 폭을 나란히 놓으니
    군더더기 픽셀이 글자 두 개를 하나로 붙였다는 게 바로 드러났음(2026-08-05).
    """
    y0, y1, x0, x1 = box
    segs = _segment_chars(mask, y0, y1, x0, x1)[:max_chars]
    chars, scores = [], []
    for seg in segs:
        bmp = _char_bitmap(mask, y0, y1, x0, x1, seg)
        ch, score = _classify(bmp, templates)
        chars.append(ch if ch else '?')
        scores.append(score)
    return ''.join(chars), scores


def read_value_line(mask, box, templates, max_chars=48):
    """줄 하나(box)를 글자별로 읽어서 {번호,값,X,Y,신뢰도,확인필요} 형태로 반환.
       형식에 안 맞으면(측정값 줄이 아니면) None 반환.

       max_chars가 22가 아니라 48인 이유: 두 라벨이 한 박스로 묶이면 글자가
       41~44개가 되는데, 22에서 끊으면 앞쪽 라벨까지만 보고 뒤쪽은 아예 못 읽음."""
    y0, y1, x0, x1 = box
    text, scores = decode_line_text(mask, box, templates, max_chars)
    m = LINE_RE.search(text)
    if not m:
        return None

    n, v, x, y = m.groups()

    # 신뢰도는 "실제로 값으로 쓰는 글자"(번호·값·X·Y)만 보고 판단함.
    # 값과 좌표 사이의 ",XY" 자리는 내용을 안 쓰고 건너뛰는 부분인데,
    # 'X'와 'Y'가 붙어 뭉개지면 점수가 크게 떨어짐. 그 점수까지 반영하면
    # 값이 멀쩡한데도 무더기로 "확인필요"로 표시되어 진짜 이상한 값이 묻힘.
    used_idx = []
    for gi in (1, 2, 3, 4):
        used_idx.extend(range(m.start(gi), m.end(gi)))
    picked = [scores[i] for i in used_idx if i < len(scores)]
    min_score = min(picked) if picked else 0.0

    # 읽은 숫자들을 float으로 변환
    value = float(v)
    px, py = float(x), float(y)

    # [교차검증 ①: 값-좌표 정합성]
    # 측정 원리상 "값"은 좌표 벡터 (X, Y)의 길이 √(X²+Y²)와 같아야 함.
    # 값과 좌표는 줄에서 서로 다른 위치에 따로 찍혀 독립적으로 읽히므로,
    # 이 관계가 허용 오차보다 크게 깨지면 값이나 좌표 중 하나가 이상한 것
    # (OCR 오독이거나 원본 데이터 불일치) → 확인필요로 표시(값은 안 바꿈).
    coord_distance = math.sqrt(px ** 2 + py ** 2)
    consistency_gap = abs(value - coord_distance)
    consistency_failed = consistency_gap > REDUNDANCY_TOLERANCE

    # [줄 중간에서 찾은 값은 교차검증을 통과해야만 인정]
    # 맨 앞에서 시작하는 매칭은 "줄의 형식 자체"가 보증이 되지만, 중간에서 건진
    # 것은 뭉개진 글자들이 우연히 형식과 맞아떨어진 것일 수 있음 — 실제로
    # Sample4/9-4_2.png(겹쳐 찍힌 사진)에서 없는 측정값 [9, 5.5, X=15.5, Y=0.0]이
    # 만들어졌음(2026-08-08). 확인필요로 표시는 되지만, 계측 프로그램이 없는
    # 측정을 만들어내는 건 안 되므로 아예 버림.
    if m.start() > 0 and consistency_failed:
        return None

    # 글자 신뢰도가 낮거나(기존 검증), 값-좌표 정합성이 깨졌거나(새 검증) 둘 중
    # 하나라도 해당하면 확인필요로 표시.
    # 사유를 같이 남기는 이유: '확인필요'만 보면 무엇을 확인해야 하는지 모름.
    # 엑셀의 '확인사유' 칸으로 그대로 나감(2026-08-05).
    reasons = []
    if min_score < CONFIDENCE_THRESHOLD:
        reasons.append(f'글자 신뢰도 낮음({min_score:.2f})')
    if consistency_failed:
        reasons.append(f'값과 좌표 불일치({consistency_gap:.2f})')
    if len(text) > MULTI_LABEL_CHARS:
        reasons.append('한 박스에 라벨이 여러 개 섞임')
    need_check = bool(reasons)

    return {
        '번호': int(n),
        '확인사유': ', '.join(reasons),
        '값': value,
        'X': px,
        'Y': py,
        '신뢰도': round(min_score, 3),
        '확인필요': need_check,
        # 사진 속 이 글자가 찍힌 화면 위치(중심점). 값 자체(X,Y)는 항상 양수라
        # 상/하/좌/우 방향을 알 수 없어서, 방향 판별에는 이 화면 위치를 씀.
        'pos_y': (y0 + y1) / 2,
        'pos_x': (x0 + x1) / 2,
    }


def count_lines_in_boxes(boxes, parsed_widths):
    """박스 폭으로 "실제 측정줄이 몇 줄인지"를 추정.

    계측기가 두 측정줄을 서로 겹치게 그리면 글자가 물리적으로 뭉개져서
    그 줄은 아예 못 읽음. 그러면 4줄짜리 사진이 2줄로 읽혀 종류 판별이
    틀어짐(overlay가 Line&Space로 둔갑). 값은 못 살려도 "몇 줄이었는지"는
    박스 폭으로 알 수 있으므로, 종류 판별에는 이 추정값을 씀.
    기준 폭은 그 사진에서 제대로 읽힌 줄의 폭을 씀(글자 수에 따라 폭이
    달라지므로 사진마다 따로 잡아야 정확함)."""
    typical = (sorted(parsed_widths)[len(parsed_widths) // 2]
               if parsed_widths else DEFAULT_LINE_WIDTH)
    total = 0
    for (_, _, x0, x1) in boxes:
        w = x1 - x0
        if w < MIN_LINE_WIDTH:
            continue          # 화면 상단 안내문구 등 측정줄이 아닌 것
        total += max(1, round(w / typical))
    return total


def read_image_ex(path, templates):
    """사진 한 장을 읽어 (측정값 목록, 실제 측정줄 추정 개수)를 반환.
       겹쳐 그려진 줄이 있으면 앞의 개수보다 뒤의 추정치가 큼."""
    mask = get_text_mask(path)
    boxes = find_line_boxes(mask)
    rows, parsed_widths = [], []
    for box in boxes:
        row = read_value_line(mask, box, templates)
        if row:
            rows.append(row)
            parsed_widths.append(box[3] - box[2])
    rows.sort(key=lambda r: r['번호'])
    return rows, count_lines_in_boxes(boxes, parsed_widths)


# ── 근거 저장용: 여러 밝기 기준으로도 읽어보기 ────────────────────────
# ⚠️ 지금은 **기록만** 함. 판정에는 여전히 read_image_ex(get_text_mask)의 결과만 씀.
# 어느 기준이 안전한지는 4개 샘플셋 전체로 실측한 뒤에 정할 것 — 지금까지 확인된
# 근거는 사진 두 장뿐임(9-1_22는 180에서 정상 판독, 210에서는 100.2를 400.2로
# 오독). 표본 2장으로 상수를 박으면 안 되므로, 우선 기록만 쌓는다. 2026-08-05.
EVIDENCE_THRESHOLDS = (170, 180, 190, 200, 210)


def read_image_attempts(path, templates, thresholds=EVIDENCE_THRESHOLDS):
    """밝기 기준을 바꿔가며 읽어본 결과를 전부 돌려줌 (원인 분석·근거 저장용).

    반환: [{'method', 'line_count', 'boxes', 'rows', 'texts'}, ...]
      method     — 어떤 방법으로 읽었는지. 나중에 다른 엔진(PaddleOCR 등)을
                   더해도 같은 칸에 들어가도록 문자열로 둠
      line_count — 박스 폭으로 추정한 실제 측정줄 수
      rows       — 형식 검사를 통과한 줄
      texts      — 통과 못 한 줄까지 포함해 "무엇으로 읽혔는지"

    ⚠️ 기준 하나당 사진을 다시 읽으므로 그만큼 느려짐. 실행 때는 문제가 있는
    사진에만 쓰고, 전수 조사는 별도 분석에서 할 것.
    """
    out = []
    for th in thresholds:
        mask = get_white_mask(path, thresh=th)
        boxes = find_line_boxes(mask)
        rows, widths, texts = [], [], []
        for box in boxes:
            text, _ = decode_line_text(mask, box, templates)
            texts.append(text)
            row = read_value_line(mask, box, templates)
            if row:
                rows.append(row)
                widths.append(box[3] - box[2])
        rows.sort(key=lambda r: r['번호'])
        out.append({
            'method': f'template@{th}',
            'line_count': count_lines_in_boxes(boxes, widths),
            'boxes': boxes,
            'rows': rows,
            'texts': texts,
        })
    return out


def read_image(path, templates):
    """사진 한 장에서 측정값 줄들을 모두 읽어 번호 순으로 반환."""
    return read_image_ex(path, templates)[0]
