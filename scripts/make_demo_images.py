# -*- coding: utf-8 -*-
# ============================================================
#  데모용 가짜 계측기 사진 생성기
# ------------------------------------------------------------
#  왜 필요한가:
#    이 저장소의 samples/ 폴더에는 실제 공정에서 찍은 사진이 들어 있어서
#    포트폴리오나 공개 데모에 그대로 쓸 수 없음. 그래서 "진짜처럼 생겼지만
#    내용은 전부 가짜"인 사진을 만들어 대신 쓴다.
#
#  어떻게 가능한가 (핵심 아이디어):
#    우리 OCR은 범용 OCR이 아니라 '템플릿 매칭'이라, 계측기가 쓰는 그 폰트가
#    아니면 한 글자도 못 읽는다. 그런데 그 글자 모양이 char_templates.pkl에
#    이미 들어 있으므로, **템플릿을 거꾸로 사진에 붙이면** 진짜 OCR을 통과하는
#    사진을 만들 수 있다. (build_templates.py가 사진 -> 템플릿이면, 이 파일은
#    템플릿 -> 사진으로 반대 방향)
#
#  ⚠️ 여기서 한 번 크게 막혔던 부분 (2026-08-17):
#    처음에 글자를 19행에 꽉 채워 그렸더니 **한 글자도 못 읽었음.**
#    원인은 템플릿이 '글자'가 아니라 **'줄박스 전체'**를 24행으로 늘려 저장한
#    것이기 때문. 정상 줄박스는 예외 없이
#        (위 여백 2행 / 글자 12행 / 아래 여백 5행) = 19행
#    이고(ocr_core.py:153~156 주석 참고), 아래 5행은 쉼표·괄호가 밑으로 내려간
#    부분이다. 그래서 템플릿을 **통째로 19행으로 되돌려** 붙여야 여백 비율까지
#    재현되어 그대로 읽힌다. 글자만 잘라 붙이면 안 됨.
#
#  겉모습의 근거 (2026-08-17, 실제 사진 3장을 열어 픽셀로 실측):
#    samples/Sample/CaptImg20260619094329.bmp (CD, 패드 배열)
#    samples/Sample/CaptImg20260619092310.bmp (Line&Space)
#    samples/Sample/CaptImg20260619103208.bmp (Overlay, 상자 안 십자)
#    이 사진들은 SEM이 아니라 **광학 현미경** 사진이라 전체적으로 흐릿하고
#    대비가 아주 낮다(전 채널 80~150 범위). 아래 색 상수는 전부 실측값이다.
# ============================================================
import json
import math
import os
import sys
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# 이 파일은 scripts/ 안에 있으므로, 프로젝트 최상위를 import 경로에 추가해야
# ocr_core 같은 모듈을 불러올 수 있음.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ocr_core  # noqa: E402


# ══ 사진 규격 ════════════════════════════════════════════════════════
IMG_W, IMG_H = 1280, 1024

LINE_H = 19                  # 측정줄 박스 높이. 위 2 + 글자 12 + 아래 5
CHAR_W = 8                   # 글자 하나의 폭
CHAR_GAP = 2                 # 글자와 글자 사이 빈 칸
# 간격이 2px 이상 필요한 이유: ocr_core._segment_chars는 **흰 픽셀이 하나도 없는
# 열**을 경계로 글자를 나눈다. 그러니 글자 사이에 완전히 빈 열이 반드시 있어야
# 함. 1px로 하면 템플릿을 줄이는 과정에서 획이 번져 옆 글자와 붙을 위험이 있음.


# ══ 색 (전부 실제 사진 실측값) ════════════════════════════════════════
# ⛔ 절대 지켜야 할 제약: 배경은 **어느 채널도 170을 넘으면 안 된다.**
# ocr_core.get_white_mask가 `R>170 & G>170 & B>170`인 픽셀만 글자로 보기 때문.
# 배경이 이 선을 넘으면 무늬가 글자 덩어리로 잡혀 줄 수 판별이 틀어지고, 밝기
# 기준이 190·200으로 밀려 올라가면서 획이 얇아져 오독까지 생긴다.
# 다행히 실제 사진도 최대 150 언저리라 이 제약이 사실성을 해치지 않는다.
MAX_BG_BRIGHT = 160

# 잡티(픽셀 단위 노이즈)의 세기. 사실감에는 도움이 되지만 **PNG 용량을 크게
# 키운다** — PNG는 비슷한 픽셀이 이어질수록 잘 줄어드는데 잡티가 그걸 방해하기
# 때문(2.5일 때 36장 73MB → 1.2로 낮추니 57MB). 눈에 보이는 만큼만 남김.
# 판독에는 어느 값이든 영향 없음(배경은 전부 170 아래라 흰 글자 마스크에 안 잡힘).
#
# ⛔ 용량을 더 줄이겠다고 **팔레트(색 수 제한)로 저장하면 안 된다.** 실제로
# 해보니 64색·32색 모두 측정 사진 27장 전부에서 판독이 깨졌음 — 흰 글자가
# 전체 픽셀의 0.1%뿐이라 색 축약 과정에서 팔레트 자리를 못 받고 회색으로
# 밀려나서 밝기 기준 170을 못 넘긴다. (2026-08-17 실측, 다시 시도하지 말 것)
NOISE_SIGMA = 1.2

CD_SURFACE = (141, 82, 75)      # CD 사진의 분홍 표면
CD_PAD = (116, 68, 63)          # 패드 안쪽(표면보다 어두움)
CD_PAD_RIM = (70, 40, 36)       # 패드 테두리 그림자
CD_PAD_HILIGHT = (156, 95, 86)  # 패드 위쪽 가장자리에 도는 밝은 테(볼록해 보이게)
CD_OUTSIDE = (122, 78, 77)      # 패드 영역 바깥(좌우 물결 경계 너머)

OVERLAY_BG = (81, 45, 38)       # Overlay 사진의 빈 배경
OVERLAY_BOX = (97, 60, 54)      # 바깥 상자 안쪽(배경보다 살짝 밝음)
OVERLAY_MARK = (68, 41, 37)     # 상자 안 십자 무늬(어두움)
OVERLAY_HALO = (118, 76, 68)    # 단차 가장자리가 빛을 되쏘아 밝게 빛나는 테

LS_SPACE = (118, 84, 95)        # Space(PR이 덮여 밝음)
LS_LINE = (86, 58, 68)          # Line(도금 전이라 바닥면이 보여 어두움)
LS_EDGE = (60, 40, 48)          # 구조물 경계의 그림자선

# 계측기가 화면에 덧그리는 표시들. 사진이 아니라 UI라서 흐리지 않고 선명함.
UI_GREEN = (0, 255, 0)          # 실측값 그대로 (순수 초록)
UI_RED = (255, 0, 0)
MARK_ARM = 5                    # 측정 끝점 X 표시의 팔 길이
CROSSHAIR_MIN_Y = 100           # 이보다 위는 계측기 UI 헤더로 취급돼 무시됨


# ══ 글자 그리기 ══════════════════════════════════════════════════════
def render_char(ch, templates):
    """글자 하나를 (LINE_H x CHAR_W) 크기의 True/False 그림으로 만듦.

    템플릿은 (24행 x 16열) bool 배열이고, 이걸 그대로 19x8로 줄인다.
    NEAREST(가장 가까운 픽셀)로 줄이는 이유: 획이 흐려지면 안 되기 때문.
    흐릿한 회색이 생기면 밝기 기준(170)에 못 미쳐 글자가 갉아먹힘.
    """
    bmp = templates[ch][0]          # 같은 글자 여러 개 중 첫 번째를 대표로 씀
    im = Image.fromarray((bmp * 255).astype(np.uint8))
    im = im.resize((CHAR_W, LINE_H), Image.NEAREST)
    return np.array(im) > 127


def render_line(text, templates):
    """측정줄 한 줄(예: "0=15.1,XY=(15.1,0.0)")을 그림으로 만듦.

    반환: (LINE_H x 폭) 크기의 True/False 배열. True인 자리에 흰 글자가 찍힘.
    """
    glyphs = [render_char(ch, templates) for ch in text]
    width = len(glyphs) * CHAR_W + (len(glyphs) - 1) * CHAR_GAP
    line = np.zeros((LINE_H, width), dtype=bool)
    x = 0
    for g in glyphs:
        line[:, x:x + CHAR_W] = g
        x += CHAR_W + CHAR_GAP
    return line


def format_line(no, value, x, y):
    r"""숫자들을 계측기가 찍는 문자열 형식으로 바꿈: "번호=값,XY=(X,Y)"

    소수점 한 자리로 고정하는 이유: 실제 사진의 판독값이 전부 0~1자리이고,
    형식 검사(ocr_core.LINE_RE)가 `\d+\.\d` 즉 소수점 뒤 한 자리를 요구함.

    ⚠️ 실제 라벨은 끝에 단위 'um'이 더 붙지만 여기서는 안 붙인다 — 템플릿에
    'u'와 'm' 모양이 없기 때문(build_templates.py가 단위를 빼고 학습시킴).
    판독에는 영향이 없다(LINE_RE는 줄 안에서 형식을 '찾는' 방식이라 뒤에 뭐가
    더 붙어도 통과함).
    """
    return f'{no}={value:.1f},XY=({x:.1f},{y:.1f})'


def draw_texts(img, lines, templates):
    """완성된 배경 사진 위에 흰 측정줄 글자를 얹음.

    글자는 **항상 맨 마지막에** 얹는다. 배경을 흐리게 만드는 처리(_finish_scene)
    보다 먼저 그리면 글자까지 흐려져서 한 글자도 안 읽힌다.

    lines: [(줄 문자열, 중심 x, 중심 y), ...]
    """
    arr = np.array(img)
    for text, cx, cy in lines:
        strip = render_line(text, templates)
        h, w = strip.shape
        y0, x0 = int(cy - h // 2), int(cx - w // 2)
        y1, x1 = min(y0 + h, IMG_H), min(x0 + w, IMG_W)
        y0, x0 = max(y0, 0), max(x0, 0)
        arr[y0:y1, x0:x1][strip[:y1 - y0, :x1 - x0]] = (255, 255, 255)
    return Image.fromarray(arr)


# ══ 계측기 화면 요소 ═════════════════════════════════════════════════
def _ui_font(size):
    """계측기 UI 글씨용 폰트. 없는 환경에서도 죽지 않게 기본 폰트로 넘어감."""
    for name in ('arialbd.ttf', 'arial.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_ui_chrome(img, mag='x50', bar_label='20um', bar_px=155):
    """실제 사진에 항상 찍혀 있는 계측기 화면 요소를 그림.

    위쪽의 초록 헤더('SNAP-SHOT MEASURE MODE')와 왼쪽 아래 빨간 스케일바.
    둘 다 흰색이 아니므로(초록/빨강) OCR의 흰 글자 마스크에는 안 잡힌다.
    헤더가 y<100에 있는 것도 중요한데, ls_brightness가 그 영역의 초록색을
    '계측기 UI'로 보고 일부러 무시하기 때문(green_mask[:100,:] = False).
    """
    d = ImageDraw.Draw(img)
    d.rectangle([645, 4, 673, 21], fill=UI_GREEN)
    d.text((648, 5), 'Live', fill=(20, 20, 20), font=_ui_font(12))
    d.text((710, 4), 'SNAP-SHOT MEASURE MODE', fill=UI_GREEN, font=_ui_font(15))

    d.line([(10, 905), (10, 1016)], fill=UI_RED, width=2)          # 세로 눈금
    d.line([(10, 1014), (10 + bar_px, 1014)], fill=UI_RED, width=2)  # 가로 스케일바
    d.text((22, 996), mag, fill=UI_RED, font=_ui_font(13))
    d.text((10 + bar_px - 40, 1000), bar_label, fill=UI_RED, font=_ui_font(13))


def draw_measure_mark(img, p0, p1):
    """측정 구간 표시 — 양 끝의 X와 그 사이를 잇는 선. **전부 초록으로** 그림.

    전부 초록으로 그리는 게 왜 중요한가:
      ls_brightness는 초록 덩어리 하나하나의 **중심 좌표**를 구한 뒤 그 주변
      ±10px의 평균 밝기를 잰다. X와 선이 서로 붙어 한 덩어리가 되면 중심이
      '측정 구간의 한가운데'가 되고, 그러면 재려는 그 특징(Line 또는 Space)
      **안쪽에서** 밝기를 재게 되어 판정이 안정적이다.
      X만 따로 찍으면 중심이 특징의 '경계'에 놓여서 밝은 쪽과 어두운 쪽이
      반반 섞여버린다(그래서 Line/Space 밝기 차이가 사라짐).
    실제 사진도 선분 + 양 끝 X 모양이며, 선이 초록인 것과 빨강인 것이 섞여 있다.
    """
    for (x, y) in (p0, p1):
        if y < CROSSHAIR_MIN_Y:
            raise ValueError(f'측정 표시를 y={y}에 그릴 수 없음 '
                             f'(y<{CROSSHAIR_MIN_Y}은 UI 헤더로 무시됨)')
    d = ImageDraw.Draw(img)
    d.line([p0, p1], fill=UI_GREEN, width=2)
    for (x, y) in (p0, p1):
        d.line([(x - MARK_ARM, y - MARK_ARM), (x + MARK_ARM, y + MARK_ARM)],
               fill=UI_GREEN, width=2)
        d.line([(x - MARK_ARM, y + MARK_ARM), (x + MARK_ARM, y - MARK_ARM)],
               fill=UI_GREEN, width=2)


def _finish_scene(img, blur, seed):
    """구조물을 다 그린 뒤 '광학 현미경 사진'처럼 만드는 마무리.

    흐리게(GaussianBlur) + 아주 약한 잡티. 실제 사진은 초점 심도 때문에
    경계가 부드럽게 번져 있고 픽셀 단위 잡티가 조금 있다.
    seed를 고정하는 이유: 데모 사진을 다시 만들어도 문서·스크린샷과 어긋나지
    않게 하려고. clip으로 위쪽을 MAX_BG_BRIGHT에 묶는 게 중요한데, 잡티 하나가
    우연히 171이 되면 그 픽셀이 글자로 잡힐 수 있기 때문.
    """
    img = img.filter(ImageFilter.GaussianBlur(blur))
    rng = np.random.default_rng(seed)
    arr = np.array(img).astype(float)

    # 비네팅(가장자리가 어두워지는 현상). 렌즈를 통해 찍은 사진이면 반드시
    # 생기는 것이라, 이게 없으면 아무리 잘 그려도 '그림' 티가 난다.
    # 중심에서 멀수록 어둡게. 밝기 검증에 쓰는 두 지점은 둘 다 화면 가운데
    # 근처라 이 감쇠를 거의 같게 받으므로 Line/Space 비교에는 영향이 없다.
    yy, xx = np.mgrid[0:IMG_H, 0:IMG_W]
    r = np.sqrt(((xx - IMG_W / 2) / (IMG_W / 2)) ** 2
                + ((yy - IMG_H / 2) / (IMG_H / 2)) ** 2)
    arr *= (1.0 - 0.16 * np.clip(r, 0, 1.4) ** 2)[:, :, None]

    arr += rng.normal(0, NOISE_SIGMA, (IMG_H, IMG_W, 3))
    return Image.fromarray(np.clip(arr, 0, MAX_BG_BRIGHT).astype(np.uint8))


# ══ 사진 3종 ═════════════════════════════════════════════════════════
#  한 Point는 사진 3장(CD / Line&Space / Overlay)으로 이뤄진다.

# ── CD: 둥근 패드가 격자로 깔린 사진, 패드 하나의 지름을 잼 ──
CD_PAD_STEP = 145               # 패드 사이 간격
CD_PAD_RADIUS = 52
CD_MEASURED_PAD = (640, 635)    # 이 패드를 가로질러 재는 것으로 그림
CD_TEXT_POS = (640, 598)        # 라벨은 측정선 바로 위 (실제 사진과 같은 배치)


def _wavy_edge_band(d, x_center, amp, to_left):
    """패드 영역의 좌우 끝에 있는 물결 모양 경계를 그림.

    실제 CD 사진을 보면 패드가 깔린 영역이 화면을 꽉 채우지 않고, 좌우 끝이
    구불구불한 경계로 잘려 있고 그 바깥은 색이 다르다. 이게 없으면 패드가
    무한히 반복되는 벽지처럼 보인다.
    """
    pts = [(x_center + amp * math.sin(y / 90.0), y) for y in range(-20, IMG_H + 21, 6)]
    edge = -30 if to_left else IMG_W + 30
    pts = [(edge, -20)] + pts + [(edge, IMG_H + 20)] if to_left else \
          pts + [(edge, IMG_H + 20), (edge, -20)]
    d.polygon(pts, fill=CD_OUTSIDE, outline=CD_PAD_RIM)


def cd_photo(value, templates, annotate=True):
    """CD 사진: 밝은 분홍 표면 위에 볼록한 둥근 패드들 + 가로 측정선 1개.

    annotate=False면 측정 표시와 글자를 빼고 배경만 낸다 — 실제 폴더에 섞여
    있는 '측정 전 사진'을 만들 때 쓴다. 프로그램은 흰 글자가 하나도 없는
    사진을 측정 전 사진으로 보고 버린다(CD측정값_엑셀변환.py의 line_count==0).
    """
    img = Image.new('RGB', (IMG_W, IMG_H), CD_SURFACE)
    d = ImageDraw.Draw(img)
    for j in range(-1, IMG_H // CD_PAD_STEP + 2):
        # 줄마다 살짝 어긋나게 놓아야 실제 배열처럼 보임
        offset = 20 if j % 2 else 0
        for i in range(-1, IMG_W // CD_PAD_STEP + 2):
            cx = 60 + CD_PAD_STEP * i + offset
            cy = 55 + CD_PAD_STEP * j
            # 동심원 3겹으로 '볼록한' 느낌을 냄: 바깥 그림자 테 -> 위로 살짝
            # 올린 밝은 테 -> 아래로 살짝 내린 어두운 안쪽 면. 위가 밝고
            # 아래가 어두우면 사람 눈은 그걸 튀어나온 것으로 읽는다.
            for rad, dy, color in ((CD_PAD_RADIUS, 0, CD_PAD_RIM),
                                   (CD_PAD_RADIUS - 4, -3, CD_PAD_HILIGHT),
                                   (CD_PAD_RADIUS - 8, 2, CD_PAD)):
                d.ellipse([cx - rad, cy + dy - rad, cx + rad, cy + dy + rad], fill=color)
    _wavy_edge_band(d, 70, 26, to_left=True)
    _wavy_edge_band(d, IMG_W - 70, 26, to_left=False)
    img = _finish_scene(img, blur=3.0, seed=1)

    draw_ui_chrome(img)
    if not annotate:
        return img
    px, py = CD_MEASURED_PAD
    draw_measure_mark(img, (px - CD_PAD_RADIUS, py), (px + CD_PAD_RADIUS, py))
    # 값을 X축에 싣고 Y는 0으로 둠. 이래야 교차검증(값 = √(X²+Y²))을 통과함.
    return draw_texts(img, [(format_line(0, value, value, 0.0), *CD_TEXT_POS)], templates)


# ── Line&Space: 가로 줄무늬. Line은 어둡고 Space는 밝음 ──
#  ls_brightness가 "Line이 Space보다 어두운지"로 배정을 2차 검증하므로
#  이 명암이 실제로 들어가 있어야 한다.
#
#  띠 두께를 Line 70 / Space 40으로 다르게 준 이유: 재는 값이 Line 쪽이
#  더 크기 때문(원칙적으로 Line > Space). 눈으로 봐도 값과 앞뒤가 맞음.
LS_BAND_H = 60                  # 어두운 Line 띠의 두께
LS_GAP_H = 100                  # 그 사이 밝은 Space 틈의 두께
LS_LINE_BAND = (380, 440)       # Line으로 잴 어두운 띠 (위 y, 아래 y)
LS_SPACE_BAND = (455, 525)      # Space로 잴 밝은 틈 (틈 440~540 안쪽)
# 틈(Space)을 띠(Line)보다 두껍게 잡은 이유: 데모 계획이 Line Target 10 /
# Space Target 20이라 Space 값이 더 크다. 그림에서도 Space 쪽이 넓어야 값과
# 앞뒤가 맞는다. 재는 구간을 틈 한가운데에 두고 양쪽에 15px씩 여유를 남긴 것은
# 밝기 재는 범위가 ±10px이라 경계가 섞이면 판정이 무너지기 때문.
LS_LINE_X, LS_SPACE_X = 500, 760    # 두 측정선의 가로 위치(서로 떨어뜨림)
LS_TEXT_GAP = 55                # 라벨을 측정 구간 위쪽으로 이만큼 띄움


def ls_photo(line_value, space_value, templates, annotate=True, space_band=None):
    """Line&Space 사진: 45° 모서리 배선 + 세로 측정선 2개(Line/Space 각각).

    annotate=False면 측정 표시·글자 없이 배경만 (측정 전 사진용).
    space_band는 Space를 재는 구간을 일부러 옮겨보고 싶을 때만 준다
    (케이스 스터디 6절 그림 — 마커가 밝기 경계에 걸치면 어떻게 되는지 보여주는 용도).
    기본값 None이면 LS_SPACE_BAND를 그대로 쓰므로 기존 동작은 변하지 않는다.
    """
    img = Image.new('RGB', (IMG_W, IMG_H), LS_SPACE)
    d = ImageDraw.Draw(img)
    # 실제 배선은 직각이 아니라 **모서리가 45°로 잘린** 모양이고, 띠마다 끝나는
    # 위치가 조금씩 다르다. 그래서 좌우 끝을 번갈아 안쪽으로 들이고 모서리를
    # 깎는다 — 균일한 줄무늬로 두면 실제 사진과 가장 크게 달라 보이는 부분.
    def _chamfer_bar(x0, y0, x1, y1, c=16):
        d.polygon([(x0 + c, y0), (x1 - c, y0), (x1, y0 + c), (x1, y1 - c),
                   (x1 - c, y1), (x0 + c, y1), (x0, y1 - c), (x0, y0 + c)],
                  fill=LS_LINE, outline=LS_EDGE, width=3)

    # Line(어두운 띠)을 일정 간격으로 깔되, 재려는 띠는 LS_LINE_BAND에 맞춤
    top = LS_LINE_BAND[0]
    band_h = LS_LINE_BAND[1] - LS_LINE_BAND[0]
    # 주기 = 어두운 띠 두께 + 밝은 틈 두께. 이렇게 맞춰야 LS_SPACE_BAND가 정확히
    # '띠와 띠 사이의 틈'에 떨어진다. (처음에 주기를 더 크게 잡았다가 Space로
    # 재려던 구간이 어두운 띠 위에 놓여 명암이 뒤집혔고, 밝기 검증이 False로
    # 나왔음 — 2026-08-17에 실제로 겪음)
    period = band_h + LS_GAP_H
    for k in range(-3, 8):
        y0 = top + period * k
        # 띠마다 한쪽 끝을 안쪽으로 들여 배선이 끝나는 모습을 만듦.
        # 재는 두 구간(LS_LINE_X, LS_SPACE_X 부근)은 항상 띠가 지나가야 하므로
        # 들이는 정도는 화면 끝 200px 안쪽으로만 제한한다.
        inset = 130 if k % 3 == 0 else (60 if k % 3 == 1 else 0)
        x0, x1 = (-30, IMG_W - inset) if k % 2 else (-30 + inset, IMG_W + 30)
        _chamfer_bar(x0, y0, x1, y0 + band_h)
    # 실제 사진처럼 한쪽 구석에 팔각형 패드를 하나 놓아 단조로움을 깸
    d.regular_polygon((1090, 880, 78), n_sides=8, rotation=22,
                      fill=LS_LINE, outline=LS_EDGE)
    img = _finish_scene(img, blur=2.5, seed=2)

    draw_ui_chrome(img, mag='x100', bar_label='10um')
    if not annotate:
        return img

    marks = [(LS_LINE_X, LS_LINE_BAND), (LS_SPACE_X, space_band or LS_SPACE_BAND)]
    lines = []
    for idx, (value, (mx, (y0, y1))) in enumerate(zip((line_value, space_value), marks)):
        draw_measure_mark(img, (mx, y0), (mx, y1))
        lines.append((format_line(idx, value, value, 0.0), mx, y0 - LS_TEXT_GAP))
    return draw_texts(img, lines, templates)


# ── Overlay: 바깥 상자 안에 십자 무늬. 네 방향 틈을 각각 잼 ──
#  ⚠️ 라벨 위치가 곧 정답이다 — overlay_analysis.assign_directions는 값이 아니라
#  네 라벨의 화면 위치를 네 라벨의 중심과 비교해 상/하/좌/우를 정하기 때문
#  (세로 차이가 가로 차이보다 크면 상/하, 아니면 좌/우). 실제 사진의 배치를
#  그대로 본떴다.
OVERLAY_BOX_RECT = (460, 285, 900, 730)         # 바깥 상자 (좌, 위, 우, 아래)
OVERLAY_CROSS_V = (605, 345, 755, 670)          # 십자의 세로 막대
OVERLAY_CROSS_H = (515, 430, 845, 585)          # 십자의 가로 막대
OVERLAY_TEXT_POS = {                            # 라벨 중심 위치
    '상': (750, 272), '하': (750, 742), '좌': (530, 470), '우': (930, 470),
}


def overlay_photo(up, down, left, right, templates, annotate=True):
    """Overlay 사진: 상자 안 십자 + 네 방향 틈을 재는 측정선 4개.

    annotate=False면 측정 표시·글자 없이 배경만 (측정 전 사진용).
    """
    bx0, by0, bx1, by1 = OVERLAY_BOX_RECT
    vx0, vy0, vx1, vy1 = OVERLAY_CROSS_V
    hx0, hy0, hx1, hy1 = OVERLAY_CROSS_H

    img = Image.new('RGB', (IMG_W, IMG_H), OVERLAY_BG)
    d = ImageDraw.Draw(img)
    d.rectangle([bx0, by0, bx1, by1], fill=OVERLAY_BOX, outline=OVERLAY_MARK, width=4)
    # 어두운 구조물 바깥에 한 겹 밝은 테를 먼저 깔아 둔다. 광학 사진에서는
    # 단차 가장자리가 빛을 되쏘아 밝게 빛나는데(실제 사진의 십자 둘레가 그렇다),
    # 흐리게 처리하면 이 밝은 테가 번져서 그 느낌이 그대로 난다.
    for pad, color in ((7, OVERLAY_HALO), (0, OVERLAY_MARK)):
        d.rounded_rectangle([vx0 - pad, vy0 - pad, vx1 + pad, vy1 + pad],
                            radius=26, fill=color)
        d.rounded_rectangle([hx0 - pad, hy0 - pad, hx1 + pad, hy1 + pad],
                            radius=26, fill=color)
    img = _finish_scene(img, blur=3.5, seed=3)

    draw_ui_chrome(img, mag='x50', bar_label='20um')
    if not annotate:
        return img

    mid_x, mid_y = (vx0 + vx1) // 2, (hy0 + hy1) // 2
    # 각 방향마다 (측정선 시작점, 끝점). 상자 안쪽 변에서 십자 변까지의 틈.
    spans = {
        '상': ((mid_x, by0 + 10), (mid_x, vy0)),
        '하': ((mid_x, vy1), (mid_x, by1 - 10)),
        '좌': ((bx0 + 5, mid_y), (hx0, mid_y)),
        '우': ((hx1, mid_y), (bx1 - 5, mid_y)),
    }
    # 상/하는 값을 Y축에, 좌/우는 X축에 싣는다 — 실제 사진이 그렇게 찍히고
    # 교차검증 값=√(X²+Y²)도 그대로 통과함.
    # ⚠️ 번호(0~3)와 방향은 **일부러 아무 관계도 없게** 둔다. 실제 사진에서도
    # 번호->방향 매핑이 고정이 아니었고, 코드도 화면 위치로만 방향을 정한다.
    values = {'상': up, '하': down, '좌': left, '우': right}
    lines = []
    for idx, direction in enumerate(('상', '하', '좌', '우')):
        p0, p1 = spans[direction]
        draw_measure_mark(img, p0, p1)
        v = values[direction]
        on_y = direction in ('상', '하')
        lines.append((format_line(idx, v, 0.0 if on_y else v, v if on_y else 0.0),
                      *OVERLAY_TEXT_POS[direction]))
    return draw_texts(img, lines, templates)


# ── 케이스 스터디용: 겹쳐 찍힌 라벨 재현 ──────────────────────────
#  실제로 겪은 현상(계측기가 라벨 두 개를 픽셀 단위로 겹쳐 찍음)을 글로만
#  설명하면 와닿지 않는다. 그렇다고 실제 사진을 공개 문서에 넣을 수는 없으므로
#  같은 현상을 합성 이미지로 재현한다.
#  ⚠️ 캡션에 "실제 사진"이라고 쓰면 안 된다 - 재현한 그림이다.
OVERLAP_POS = {'좌': (700, 470), '우': (762, 470)}   # 두 라벨을 겹쳐 놓을 자리
OVERLAP_CROP = (545, 432, 925, 508)                  # 겹친 부분 확대 범위
NORMAL_CROP = (600, 246, 900, 300)                   # 비교용 정상 라벨(상)
CROP_ZOOM = 3


def overlap_example(templates, values=(1.2, 1.1, 1.3, 1.0)):
    """겹쳐 찍힌 라벨을 재현한 사진과 확대 그림 두 장을 만든다.

    배경·측정선은 보통 Overlay 사진과 같고, 좌/우 라벨만 서로 붙여 놓아
    글자가 섞이게 한다. 반환: (전체 사진, 겹친 부분 확대, 정상 부분 확대)
    """
    up, down, left, right = values
    bx0, by0, bx1, by1 = OVERLAY_BOX_RECT
    vx0, vy0, vx1, vy1 = OVERLAY_CROSS_V
    hx0, hy0, hx1, hy1 = OVERLAY_CROSS_H
    mid_x, mid_y = (vx0 + vx1) // 2, (hy0 + hy1) // 2

    img = overlay_photo(up, down, left, right, templates, annotate=False)
    spans = {
        '상': ((mid_x, by0 + 10), (mid_x, vy0)),
        '하': ((mid_x, vy1), (mid_x, by1 - 10)),
        '좌': ((bx0 + 5, mid_y), (hx0, mid_y)),
        '우': ((hx1, mid_y), (bx1 - 5, mid_y)),
    }
    values_by_dir = {'상': up, '하': down, '좌': left, '우': right}
    lines = []
    for idx, direction in enumerate(('상', '하', '좌', '우')):
        p0, p1 = spans[direction]
        draw_measure_mark(img, p0, p1)
        v = values_by_dir[direction]
        on_y = direction in ('상', '하')
        pos = OVERLAP_POS.get(direction, OVERLAY_TEXT_POS[direction])
        lines.append((format_line(idx, v, 0.0 if on_y else v, v if on_y else 0.0), *pos))
    full = draw_texts(img, lines, templates)

    def _zoom(box):
        w, h = box[2] - box[0], box[3] - box[1]
        return full.crop(box).resize((w * CROP_ZOOM, h * CROP_ZOOM), Image.NEAREST)

    return full, _zoom(OVERLAP_CROP), _zoom(NORMAL_CROP)


def build_overlap_images(out_dir):
    """케이스 스터디에 넣을 이미지 3장을 만들고, 실제 판독기로 결과를 확인한다.

    확인까지 하는 이유: "겹치면 못 읽는다"고 글에 적으려면 그 그림이 정말로
    판독에 실패해야 한다. 멀쩡히 읽히는 그림을 붙여놓고 설명만 그렇게 쓰면
    문서가 거짓말을 하게 된다.
    """
    os.makedirs(out_dir, exist_ok=True)
    full, overlap_crop, normal_crop = overlap_example(templates=ocr_core.load_templates())

    width = EXAMPLE_WIDTH
    height = int(IMG_H * width / IMG_W)
    paths = {}
    full_path = os.path.join(out_dir, 'overlap-full.jpg')
    full.resize((width, height), Image.LANCZOS).save(full_path, quality=82, optimize=True)
    paths['전체'] = full_path
    for name, im in (('overlap-crop.png', overlap_crop), ('normal-crop.png', normal_crop)):
        path = os.path.join(out_dir, name)
        im.save(path, optimize=True)
        paths[name] = path

    # 재현이 실제로 "안 읽히는" 상태인지 원본 크기로 확인
    tmp = os.path.join(tempfile.gettempdir(), 'cd_overlap_check.png')
    full.save(tmp)
    rows, line_count = ocr_core.read_image_ex(tmp, ocr_core.load_templates())
    flagged = sum(1 for r in rows if r['확인필요'])
    print(f'  재현 확인: 줄 수 {line_count} / 읽은 값 {len(rows)}개 / 확인필요 {flagged}건')
    if len(rows) >= 4 and flagged == 0:
        print('  ⚠️ 겹쳤는데도 4개가 멀쩡히 읽혔습니다 - OVERLAP_POS를 더 붙이세요.')
    for key, path in paths.items():
        print(f'  {key}: {path} ({os.path.getsize(path):,} bytes)')
    return paths


# ── 케이스 스터디 6절: 밝기로 Line/Space를 가리는 장면 ──────────────
#  마커가 어디에 놓이느냐로 밝기 차이가 어떻게 달라지는지 보여준다.
#  ⚠️ 2026-08-20 실험으로 확인한 것(추측 금지):
#     판정이 **반대로 뒤집히지는 않는다.** Space 마커가 어두운 띠 쪽으로
#     갈수록 두 밝기가 가까워져 차이가 0에 수렴할 뿐이다
#     (틈 한가운데 28.8 → 경계 9.8 → 띠 안쪽 0.1). Line 마커도 같은
#     어두운 띠 위에 있어서 Space가 그보다 더 어두워질 수는 없기 때문.
BRIGHT_OK_CENTER = 490      # 밝은 틈(440~540) 한가운데 - 정상 사례
BRIGHT_EDGE_CENTER = 440    # 어두운 띠와 밝은 틈의 경계 - 무너지는 사례
BRIGHT_CROP = (430, 340, 830, 570)   # 두 마커가 같이 보이는 영역(두 장 같은 자리)


def _brightness_shot(center, templates, out_path, tmp_path):
    """마커 중심을 center에 놓은 L&S 사진을 만들고, 실제 판독기·밝기 검증기로 확인.

    반환: (판정, Line 밝기, Space 밝기)
    """
    import ls_brightness
    import numpy as np
    from PIL import Image as _Image

    half = (LS_SPACE_BAND[1] - LS_SPACE_BAND[0]) // 2
    img = ls_photo(9.4, 5.3, templates, space_band=(center - half, center + half))
    img.save(tmp_path)

    rows, _ = ocr_core.read_image_ex(tmp_path, templates)
    if len(rows) < 2:
        raise SystemExit(f'값을 2개 읽어야 하는데 {len(rows)}개만 읽혔습니다: {tmp_path}')
    line_row, space_row = rows[0], rows[1]
    verdict = ls_brightness.verify_ls_brightness(tmp_path, line_row, space_row)

    # 캡션에 적을 밝기 숫자 — 검증기가 실제로 쓰는 함수를 그대로 호출한다
    # (따로 계산하면 글의 숫자와 프로그램의 숫자가 갈라진다).
    arr = np.array(_Image.open(tmp_path).convert('RGB'))
    centers = ls_brightness._find_crosshair_centers(arr)
    vals = []
    for r in (line_row, space_row):
        bx, by = min(centers, key=lambda c: (c[0] - r['pos_x']) ** 2 + (c[1] - r['pos_y']) ** 2)
        vals.append(ls_brightness._sample_brightness(arr, bx, by))

    img.crop(BRIGHT_CROP).save(out_path, optimize=True)
    return verdict, vals[0], vals[1]


def build_brightness_images(out_dir):
    """6절 그림 2장을 만들고 밝기 검증기로 실제 결과를 확인한다."""
    os.makedirs(out_dir, exist_ok=True)
    templates = ocr_core.load_templates()
    tmp = tempfile.gettempdir()
    out = {}
    for name, center in (('ls-bright-ok.png', BRIGHT_OK_CENTER),
                         ('ls-bright-edge.png', BRIGHT_EDGE_CENTER)):
        path = os.path.join(out_dir, name)
        verdict, b_line, b_space = _brightness_shot(
            center, templates, path, os.path.join(tmp, f'cd_{name}'))
        gap = b_space - b_line
        print(f'  {name}: 마커 중심 y={center} / 판정={verdict} / '
              f'Line {b_line:.1f} vs Space {b_space:.1f} (차이 {gap:.1f}) '
              f'/ {os.path.getsize(path):,} bytes')
        out[name] = (verdict, b_line, b_space, gap)

    ok_gap = out['ls-bright-ok.png'][3]
    edge_gap = out['ls-bright-edge.png'][3]
    if not ok_gap > edge_gap * 2:
        print('  ⚠️ 경계 사례의 밝기 차이가 충분히 줄지 않았습니다 - '
              'BRIGHT_EDGE_CENTER를 띠 쪽으로 더 옮기세요.')
    return out


# ══ 폴더 통째 만들기 ═════════════════════════════════════════════════
#  실제 폴더를 그대로 흉내낸다. 한 Point는 사진 3장(overlay/CD/L-S)이고,
#  프로그램은 파일을 이름순(=시간순)으로 정렬한 뒤 3장씩 묶어 Point로 본다.
#  중간중간 '측정 전 사진'(글자 없는 사진)이 섞여 있지만, 프로그램이
#  line_count==0인 사진을 먼저 버리므로 묶음은 흐트러지지 않는다.
#
#  ⚠️ Target은 아무 숫자나 쓰면 안 된다 — Tolerance 조회표에 등록된 값이라야
#  스펙(USL/LSL)이 잡힌다. 그래서 실제로 쓰던 Sample4와 같은 틀을 빌려 씀:
#      RDL / Pad CD 100 / Line 10 / Space 20 / Overlay
#  이 폴더로 프로그램을 돌릴 때도 계획을 이 값으로 입력해야 한다.
DEMO_TARGETS = {'pad_cd': 100.0, 'line': 10.0, 'space': 20.0}
DEMO_START = (2026, 8, 17, 9, 0, 0)     # 첫 사진 촬영 시각(파일명에 들어감)
DEMO_INTERVAL_SEC = 37                  # 사진 사이 간격


# ── 소개 화면(/demo)용 예시 사진 ────────────────────────────────────
#  값은 Target 근처 대표값 하나로 고정한다(폴더 생성과 달리 난수를 쓰지 않음) —
#  소개 화면 문구·스크린샷과 사진 속 숫자가 어긋나면 안 되기 때문.
EXAMPLE_VALUES = {'cd': 100.2, 'line': 10.1, 'space': 20.0,
                  'overlay': (1.2, 1.1, 1.3, 1.0)}
EXAMPLE_WIDTH = 640          # 웹에 올릴 가로 크기(원본 1280의 절반)


def example_annotations():
    """예시 사진 위에 겹칠 주석의 좌표와 문구.

    좌표는 전부 **원본 픽셀 기준**이고, 그림을 그릴 때 쓴 상수에서 가져온다.
    눈대중으로 적으면 그림을 조금만 고쳐도 화살표가 엉뚱한 곳을 가리키게 된다.
    '라벨'은 글자를 놓을 자리라 사진을 가리지 않는 빈 곳으로 사람이 고른 값이다.

    화면에서 이 좌표를 쓰는 쪽은 webapp/templates/demo.html의 SVG이고,
    viewBox가 (IMG_W, IMG_H)와 같아서 여기 적은 값이 그대로 들어간다.
    """
    ls_line_mid = (LS_LINE_BAND[0] + LS_LINE_BAND[1]) // 2
    ls_space_mid = (LS_SPACE_BAND[0] + LS_SPACE_BAND[1]) // 2
    return {
        '크기': [IMG_W, IMG_H],
        '사진': [
            {'키': 'cd', '파일': 'cd.jpg', '제목': 'CD — 패드 하나의 폭',
             '설명': '값이 한 줄로 표시됩니다.',
             '주석': [
                 # 측정선과 라벨은 세로로 37px밖에 안 떨어져 있어서, 둘 다
                 # 중심을 가리키면 화살표 두 개가 한 점에 겹쳐 보인다(실제로
                 # 겪음). 측정선은 오른쪽 X 표시를, 라벨은 글자 왼쪽 끝을
                 # 가리켜 좌우로 갈라놓는다.
                 {'대상': [CD_MEASURED_PAD[0] + CD_PAD_RADIUS, CD_MEASURED_PAD[1]],
                  '라벨': [995, 850], '글': '측정 구간'},
                 {'대상': [CD_TEXT_POS[0] - 130, CD_TEXT_POS[1]],
                  '라벨': [120, 300], '글': '이 숫자를 읽습니다'},
             ]},
            {'키': 'ls', '파일': 'ls.jpg', '제목': 'Line & Space — 선과 틈',
             '설명': '값이 두 줄로 표시됩니다.',
             '주석': [
                 {'대상': [LS_LINE_X, ls_line_mid], '라벨': [180, 200],
                  '글': 'Line — 선폭'},
                 {'대상': [LS_SPACE_X, ls_space_mid], '라벨': [1010, 790],
                  '글': 'Space — 간격'},
             ]},
            {'키': 'overlay', '파일': 'overlay.jpg', '제목': 'Overlay — 정렬 오차',
             '설명': '상·하·좌·우 각 방향의 값이 표시됩니다.',
             '주석': [
                 {'대상': list(OVERLAY_TEXT_POS['상']), '라벨': [1000, 140],
                  '글': '네 방향 간격을 각각 측정'},
                 {'대상': list(OVERLAY_TEXT_POS['좌']), '라벨': [130, 870],
                  '글': '방향은 라벨의 위치로 구분'},
             ]},
        ],
    }


def build_example_shots(out_dir):
    """소개 화면용 예시 사진 3장(JPEG)과 주석 좌표 파일을 만든다.

    JPEG로 줄이는 이유: 원본 PNG는 장당 약 2MB(잡티 때문에 압축이 안 먹음)라
    소개 화면 한 번에 6MB가 나간다. 이 사진들은 **판독에 쓰지 않고 보여주기만**
    하므로 손실 압축이어도 상관없다(판독용은 여전히 원본 PNG).
    """
    os.makedirs(out_dir, exist_ok=True)
    templates = ocr_core.load_templates()
    shots = {
        'cd': cd_photo(EXAMPLE_VALUES['cd'], templates),
        'ls': ls_photo(EXAMPLE_VALUES['line'], EXAMPLE_VALUES['space'], templates),
        'overlay': overlay_photo(*EXAMPLE_VALUES['overlay'], templates),
    }
    saved = {}
    height = int(IMG_H * EXAMPLE_WIDTH / IMG_W)
    for key, img in shots.items():
        path = os.path.join(out_dir, f'{key}.jpg')
        img.resize((EXAMPLE_WIDTH, height), Image.LANCZOS).save(
            path, quality=82, optimize=True)
        saved[key] = path
    ann_path = os.path.join(out_dir, 'annotations.json')
    with open(ann_path, 'w', encoding='utf-8') as f:
        json.dump(example_annotations(), f, ensure_ascii=False, indent=2)
    saved['annotations'] = ann_path
    return saved


def build_demo_folder(out_dir, points=9, seed=20260817):
    """데모용 사진 폴더를 통째로 만든다.

    seed를 고정하는 이유: 다시 만들어도 같은 숫자가 나와야 문서·스크린샷과
    어긋나지 않기 때문. 값은 Target 주변에 흩뿌리되 Item마다 산포를 다르게
    줘서 Cpk 막대에 초록·주황이 섞여 보이게 한다(전부 완벽하면 오히려 도구가
    무엇을 잡아내는지 안 보임).
    """
    import datetime

    os.makedirs(out_dir, exist_ok=True)
    templates = ocr_core.load_templates()
    rng = np.random.default_rng(seed)
    stamp = datetime.datetime(*DEMO_START)
    made = []

    def _save(img):
        nonlocal stamp
        path = os.path.join(out_dir, f'CaptImg{stamp:%Y%m%d%H%M%S}.png')
        img.save(path)
        stamp += datetime.timedelta(seconds=DEMO_INTERVAL_SEC)
        made.append(path)

    for _ in range(points):
        # Point 하나 = 측정 전 사진 1장 + 측정 사진 3장(overlay -> CD -> L&S).
        # 측정 전 사진은 계측기가 자리를 잡을 때 찍히는 것이라 실제 폴더에도 섞여 있음.
        ov = [round(float(v), 1) for v in rng.normal(1.2, 0.25, 4)]
        cd = round(float(rng.normal(DEMO_TARGETS['pad_cd'] + 0.2, 0.55)), 1)
        ln = round(float(rng.normal(DEMO_TARGETS['line'] + 0.1, 0.28)), 1)
        sp = round(float(rng.normal(DEMO_TARGETS['space'], 0.20)), 1)

        _save(overlay_photo(*ov, templates, annotate=False))
        _save(overlay_photo(*ov, templates))
        _save(cd_photo(cd, templates))
        _save(ls_photo(ln, sp, templates))

    return made


def build_preview_assets(folder):
    """데모 사진 폴더 옆에 웹 표시용 미리보기(preview/)를 만든다.

    - 축소 JPEG: 원본 PNG는 장당 약 2MB(잡티 때문에 압축이 안 먹음)라 결과
      화면에서 한 포인트(3장)를 여는 데만 6MB가 나간다.
    - boxes.json: 화면에 "여기를 읽었다"고 표시할 영역. 축소본을 만들려고
      어차피 사진을 여는 김에 crop_boxes()를 부르는 것이라 좌표가 거의 공짜다.

    ⚠️ manual_entry는 맨 위에서 tkinter를 불러온다. 서버 컨테이너에는
    python3-tk가 들어 있으므로(webapp/Dockerfile) import가 실패하지 않는다.
    """
    from manual_entry import crop_boxes

    out_dir = os.path.join(folder, 'preview')
    os.makedirs(out_dir, exist_ok=True)
    boxes = {}
    height = int(IMG_H * EXAMPLE_WIDTH / IMG_W)
    for name in sorted(os.listdir(folder)):
        if not name.lower().endswith('.png'):
            continue
        path = os.path.join(folder, name)
        Image.open(path).convert('RGB').resize(
            (EXAMPLE_WIDTH, height), Image.LANCZOS).save(
            os.path.join(out_dir, os.path.splitext(name)[0] + '.jpg'),
            quality=82, optimize=True)
        boxes[name] = [list(b) for b in crop_boxes(path)]
    with open(os.path.join(out_dir, 'boxes.json'), 'w', encoding='utf-8') as f:
        json.dump({'크기': [IMG_W, IMG_H], '박스': boxes}, f, ensure_ascii=False)
    return len(boxes)


def verify_demo_folder(paths, templates):
    """만든 폴더를 **실제 판독기로 전부 다시 읽어** 이상이 없는지 확인.

    확인하는 것: 측정 전 사진이 정말 0줄로 나오는지, 측정 사진은 종류별
    줄 수(1/2/4)가 맞는지, 확인필요가 하나도 없는지.
    """
    kinds, flagged, unread = [], 0, 0
    for p in paths:
        rows, line_count = ocr_core.read_image_ex(p, templates)
        kinds.append(line_count)
        flagged += sum(1 for r in rows if r['확인필요'])
        if line_count and len(rows) != line_count:
            unread += 1
    counts = {k: kinds.count(k) for k in sorted(set(kinds))}
    print(f'  사진 {len(paths)}장 → 줄 수별 장수 {counts}')
    print(f'  측정 전(0줄) {kinds.count(0)}장 / 확인필요 {flagged}건 / 못 읽은 사진 {unread}장')
    return flagged == 0 and unread == 0


# ══ 자체 점검 ════════════════════════════════════════════════════════
def _check(name, img, expect_count, templates):
    """만든 사진을 **진짜 OCR로 다시 읽어** 결과를 출력.

    생성기를 고칠 때마다 이걸 돌려서 "여전히 읽히는지"를 확인한다.
    가짜 사진이라도 판독은 실제 파이프라인(read_image_ex)을 그대로 쓴다 —
    생성기만 통과하고 실제 프로그램에서는 안 읽히면 아무 소용이 없으므로.
    """
    path = os.path.join(tempfile.gettempdir(), f'cd_demo_{name}.bmp')
    img.save(path)
    rows, line_count = ocr_core.read_image_ex(path, templates)

    ok = (line_count == expect_count and len(rows) == expect_count
          and not any(r['확인필요'] for r in rows))
    print(f'[{"OK" if ok else "실패"}] {name} : 줄 수 {line_count}/{expect_count}, '
          f'판독 {len(rows)}개')
    for r in rows:
        print(f'    번호={r["번호"]} 값={r["값"]:>5} X={r["X"]:>5} Y={r["Y"]:>5} '
              f'신뢰도={r["신뢰도"]:.3f} 확인필요={r["확인필요"]}')
    return path, rows, ok


if __name__ == '__main__':
    import overlay_analysis
    import ls_brightness

    # 소개 화면용 예시 사진만 따로 만드는 길 (저장소에 커밋하는 고정 자산)
    if len(sys.argv) > 2 and sys.argv[1] == '--overlap':
        build_overlap_images(sys.argv[2])
        sys.exit(0)

    if len(sys.argv) > 2 and sys.argv[1] == '--brightness':
        build_brightness_images(sys.argv[2])
        sys.exit(0)

    if len(sys.argv) > 2 and sys.argv[1] == '--examples':
        saved = build_example_shots(sys.argv[2])
        for key, path in saved.items():
            print(f'  {key}: {path} ({os.path.getsize(path):,} bytes)')
        sys.exit(0)

    # 폴더 경로를 주면 데모 폴더를 통째로 만들고, 안 주면 사진 3종만 자체 점검함
    if len(sys.argv) > 1:
        out_dir = sys.argv[1]
        made = build_demo_folder(out_dir)
        print(f'데모 폴더 생성 완료: {out_dir} ({len(made)}장)')
        ok = verify_demo_folder(made, ocr_core.load_templates())
        print('판독 확인:', 'OK' if ok else '실패')
        sys.exit(0 if ok else 1)

    templates = ocr_core.load_templates()

    _check('CD', cd_photo(15.1, templates), 1, templates)
    ls_path, ls_rows, _ = _check('LS', ls_photo(9.4, 5.3, templates), 2, templates)
    _, rows, _ = _check('Overlay', overlay_photo(1.2, 1.5, 0.8, 1.1, templates), 4, templates)

    # Overlay는 값이 읽히는 것만으로는 부족하고 **방향이 의도대로 배정돼야** 함 —
    # 그게 이 사진의 존재 이유이므로 여기서 같이 확인한다.
    overlay_analysis.assign_directions(rows)
    got = {r['방향']: r['값'] for r in rows}
    want = {'상': 1.2, '하': 1.5, '좌': 0.8, '우': 1.1}
    print(f'[{"OK" if got == want else "실패"}] Overlay 방향 : {got}')

    # L/S는 줄무늬 명암이 2차 검증(초록 표시 주변 밝기)을 통과해야 함.
    # True면 "큰 값=Line" 1차 배정과 밝기가 서로 맞다는 뜻.
    line_row, space_row = ls_rows[0], ls_rows[1]     # 9.4가 Line, 5.3이 Space
    agrees = ls_brightness.verify_ls_brightness(ls_path, line_row, space_row)
    print(f'[{"OK" if agrees is True else "실패"}] L/S 밝기 검증 : {agrees} '
          f'(True여야 함. None이면 초록 표시를 못 찾은 것)')
