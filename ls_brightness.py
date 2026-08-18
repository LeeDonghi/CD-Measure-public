# -*- coding: utf-8 -*-
# ============================================================
#  L/S 배정 2차 검증: 크로스헤어 주변 밝기로 확인 (과제 4)
# ------------------------------------------------------------
#  도금 전 사진이라 Line은 PR이 없어 바닥면이 보여 어둡게, Space는
#  PR이 덮여 있어 밝게 찍힘. measurement_plan.match_ls_targets의
#  1차 원칙("큰 값 = Line")이 맞는지, 크로스헤어(초록 마커) 주변
#  밝기로 교차 확인하는 보조 신호.
#
#  크로스헤어가 밝기 경계(Line/Space 사이 경계)에 걸쳐 찍히는
#  경우가 있어 100% 일치하진 않음(LS Sample 11장 검증: 약 9/11
#  일치). 그래서 이 결과로 배정을 뒤집지 않고, 불일치할 때만
#  "확인필요" 표시로 알림.
# ============================================================
import numpy as np
from PIL import Image
from scipy import ndimage

_SAMPLE_RADIUS = 10  # 크로스헤어 중심 주변 밝기 샘플 반경(px)


def _find_crosshair_centers(arr):
    """사진에서 초록색 크로스헤어 마커들의 중심 좌표 목록을 찾음.
       화면 맨 위(y<100)는 계측기 UI의 초록 헤더 글자라 제외."""
    r, g, b = arr[:, :, 0].astype(int), arr[:, :, 1].astype(int), arr[:, :, 2].astype(int)
    green_mask = (g > 100) & (g > r + 30) & (g > b + 30)
    green_mask[:100, :] = False
    labeled, n = ndimage.label(green_mask)
    centers = []
    for i in range(1, n + 1):
        ys, xs = np.where(labeled == i)
        if len(ys) < 5:
            continue
        centers.append((xs.mean(), ys.mean()))
    return centers


def _sample_brightness(arr, cx, cy, radius=_SAMPLE_RADIUS):
    """(cx,cy) 주변 정사각형 영역의 평균 밝기(회색조). 흰 글자/초록 마커는 제외."""
    h, w, _ = arr.shape
    y0, y1 = max(0, int(cy - radius)), min(h, int(cy + radius))
    x0, x1 = max(0, int(cx - radius)), min(w, int(cx + radius))
    patch = arr[y0:y1, x0:x1].astype(int)
    r, g, b = patch[:, :, 0], patch[:, :, 1], patch[:, :, 2]
    not_white = ~((r > 170) & (g > 170) & (b > 170))
    not_green = ~((g > 100) & (g > r + 30) & (g > b + 30))
    keep = not_white & not_green
    if keep.sum() == 0:
        return None
    gray = (r + g + b) / 3
    return gray[keep].mean()


def verify_ls_brightness(image_path, line_row, space_row):
    """Line/Space 배정(1차: 큰 값=Line)이 크로스헤어 밝기와 맞는지 확인.
       line_row/space_row: 'pos_x'/'pos_y' 키가 있는 딕셔너리(ocr_core.read_image 결과).
       반환: True(밝기도 일치) / False(밝기는 반대로 나옴) / None(판단 불가)."""
    img = Image.open(image_path).convert('RGB')
    arr = np.array(img)
    centers = _find_crosshair_centers(arr)
    if not centers:
        return None

    brightness = {}
    for key, row in (('line', line_row), ('space', space_row)):
        cx, cy = row['pos_x'], row['pos_y']
        bx, by = min(centers, key=lambda c: (c[0] - cx) ** 2 + (c[1] - cy) ** 2)
        val = _sample_brightness(arr, bx, by)
        if val is None:
            return None
        brightness[key] = val

    return bool(brightness['line'] < brightness['space'])
