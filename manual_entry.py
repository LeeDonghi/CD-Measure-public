# -*- coding: utf-8 -*-
# ============================================================
#  못 읽은 측정값을 사람이 직접 넣는 화면 (2026-08-07)
# ------------------------------------------------------------
#  OCR이 못 읽는 사진은 반드시 남는다. 겹쳐 찍힌 라벨처럼 원본에서 이미
#  글자가 뭉개진 경우는 **어떤 OCR로도 복원할 수 없다**(2026-08-05에 Overlay
#  9장으로 확인). 그런데 사람 눈에는 잘 보인다.
#
#  그래서 결과를 내기 전에 "못 읽은 것만 모아 보여주고 직접 입력받는" 단계를 둔다.
#  지금까지는 그 값이 그냥 사라졌고, 담당자가 엑셀을 받은 뒤에 사진 폴더를 열어
#  일일이 대조해야 했다. 사진과 입력칸을 나란히 놓으면 그 일이 몇 초로 줄고,
#  포기했던 Overlay 지표 계산도 살아난다.
#
#  ⚠️ 설계에서 지킨 것
#   - **손으로 넣은 값은 반드시 구분된다.** 엑셀 '입력방법' 칸에 "수동"으로 남고
#     '확인사유'에도 적힌다. Cpk를 뽑는 계측 데이터라 추적이 안 되면 안 됨.
#   - **정상 판독된 값은 못 고친다.** 못 읽은 칸을 채우는 것만 허용. 안 그러면
#     측정 데이터 편집 도구가 되어버림.
#   - **사람이 친 값도 기계와 똑같이 검증한다.** 값 = √(X²+Y²) 검사를 그대로
#     적용해서 한 자리 잘못 치면 즉시 걸림.
#   - 화면은 tkinter라 자동 테스트로 클릭할 수 없음. 그래서 **판단 로직**
#     (무엇을 물을지 / 입력이 맞는지 / 행을 어떻게 만들지)은 창과 분리해서
#     함수로 뺐고, 그 함수들만 따로 검증한다.
# ============================================================
import math
import os
import tkinter as tk
from tkinter import ttk, messagebox

from ocr_core import (get_text_mask, find_line_boxes, REDUNDANCY_TOLERANCE,
                      MIN_LINE_WIDTH)
from overlay_analysis import infer_known_directions, infer_forced_directions

# crop을 몇 배로 키워 보여줄지. 측정줄 글자 높이가 19px뿐이라 원본 크기로는
# 읽기 힘듦. 2배면 화면에서 편하게 읽히고 창이 지나치게 커지지도 않음.
CROP_ZOOM = 2
CROP_PAD = 8          # 위아래에 뭐가 붙었는지 보이도록 여백을 조금 둠

DIRECTIONS = ('상', '하', '좌', '우')


# ------------------------------------------------------------
#  1) 무엇을 물어볼지 정하기
# ------------------------------------------------------------
def pending_items(measured):
    """검토가 필요한 사진만 골라 [{...}, ...]로 반환.

    measured: process_folder가 1단계에서 만든
              [(경로, 파일명, 종류, 표시이름, 행목록, 추정줄수), ...]

    고르는 기준은 "읽은 값이 추정 줄 수보다 적은 사진" 하나뿐이다.
    확인필요만 붙은 행(신뢰도 낮음 등)은 값 자체는 읽혔으므로 여기서 안 물음 —
    엑셀에서 확인사유를 보고 판단하면 됨.

    Overlay는 여기서 방향까지 미리 정리해둔다(2026-08-10) —
    Overlay_X/Y가 |좌값-우값|/2, |상값-하값|/2로 절댓값을 쓰는 걸 이용하면,
    남은 자리가 하나뿐이거나 같은 축 둘뿐일 때는 어느 쪽에 뭘 배정해도
    계산 결과가 같음(overlay_analysis.infer_forced_directions). 그런 경우엔
    'forced_directions'에 채워서 화면에서 방향을 안 물어봐도 되게 한다."""
    items = []
    for path, name, category, kind, rows, line_count in measured:
        missing = line_count - len(rows)
        if missing <= 0:
            continue
        forced = None
        if category == 'overlay':
            infer_known_directions(rows)
            forced = infer_forced_directions([r.get('방향') for r in rows])
        items.append({
            'path': path, 'name': name, 'category': category, 'kind': kind,
            'rows': rows, 'line_count': line_count, 'missing': missing,
            'forced_directions': forced,
        })
    return items


# ------------------------------------------------------------
#  2) 사람이 친 값 검증하기
# ------------------------------------------------------------
def validate_entry(value, x, y):
    """사람이 친 값이 계측기 출력으로 말이 되는지 확인.
       반환: (문제없음, 사유). 문제없음이 False여도 값은 버리지 않고 표시만 함."""
    if value <= 0:
        return False, '값이 0 이하'
    # 기계가 읽은 값에 쓰는 것과 똑같은 검사. 한 자리 잘못 치면 여기서 걸림.
    gap = abs(value - math.sqrt(x ** 2 + y ** 2))
    if gap > REDUNDANCY_TOLERANCE:
        return False, f'값과 좌표 불일치({gap:.2f})'
    return True, ''


def _axis_for_direction(direction):
    """방향에 따라 '값'이 들어갈 축(X/Y)을 정함.

    실측으로 확인한 계측기 출력 규칙(2026-08-07, 4개 폴더 115개 표본, 예외 0건):
      - CD/L&S(방향 없음): 값은 항상 X와 정확히 같음 (X≡값)
      - Overlay 상/하: 값은 Y와 같음     Overlay 좌/우: 값은 X와 같음
    반대쪽 축(오프셋)은 작은 값(보통 0~0.5)을 담는 별개 정보라 값에서
    유추할 수 없음 - 그래서 오프셋만 따로 선택 입력으로 받음."""
    return 'Y' if direction in ('상', '하') else 'X'


def build_manual_row(number, value, offset=0.0, direction=''):
    """사람이 친 값(+선택적 오프셋)을 OCR이 읽은 행과 같은 모양으로 만든다.

    ⚠️ X/Y를 둘 다 받지 않는 이유: '값과 같은 쪽 축'은 항상 값 그 자체라서
    (위 _axis_for_direction 주석의 실측 결과) 따로 입력받아도 같은 숫자를
    두 번 치는 것뿐이라 정보도, 오타 검증 효과도 없음. 대신 값에서 못
    유추하는 '오프셋'만 선택 입력으로 받고, 값이 들어갈 축은 자동 계산함.

    ⚠️ pos_x/pos_y(화면 위치)는 None이다 — 사람이 친 값에는 위치가 없음.
    그래서 Overlay 방향은 위치로 추정하지 못하고 화면에서 직접 받아야 함.
    '수동방향'에 넣는 이유: '방향'은 process_folder 2단계에서 모든 행이
    일괄로 ''로 초기화된 뒤 overlay만 assign_directions로 다시 채워지는데,
    그때 이 값을 읽어 쓰도록 overlay_analysis.py에서 미리 맞춰둠. 여기서
    '방향'에 바로 넣으면 그 초기화에 지워짐."""
    offset = offset or 0.0
    if _axis_for_direction(direction) == 'X':
        x, y = value, offset
    else:
        x, y = offset, value
    ok, reason = validate_entry(value, x, y)
    return {
        '번호': int(number),
        '값': float(value),
        'X': float(x),
        'Y': float(y),
        '신뢰도': None,          # 사람이 넣은 값이라 글자 인식 점수가 없음
        '확인필요': not ok,
        '확인사유': '수동입력' + (f' ({reason})' if reason else ''),
        '입력방법': '수동',
        'pos_y': None,
        'pos_x': None,
        '방향': direction,
        '수동방향': direction,
    }


# ------------------------------------------------------------
#  3) crop 그림 만들기
# ------------------------------------------------------------
def crop_boxes(path):
    """사진에서 측정줄로 보이는 자리의 (y0, y1, x0, x1) 목록.
       화면 상단 안내문구 같은 짧은 덩어리는 뺀다."""
    boxes = find_line_boxes(get_text_mask(path))
    return [b for b in boxes if (b[3] - b[2]) >= MIN_LINE_WIDTH]


def _crop_image(path, box):
    """줄 하나를 잘라 확대한 PhotoImage를 만든다(tkinter가 들고 있어야 안 사라짐)."""
    from PIL import Image, ImageTk
    img = _cropped_pil_image(path, box)
    return ImageTk.PhotoImage(img)


def _cropped_pil_image(path, box):
    """줄 하나를 잘라 확대한 PIL 이미지(tkinter 불필요 - 파일로 저장할 때 씀)."""
    from PIL import Image
    y0, y1, x0, x1 = box
    img = Image.open(path).crop((
        max(0, x0 - CROP_PAD), max(0, y0 - CROP_PAD),
        x1 + CROP_PAD + 1, y1 + CROP_PAD + 1))
    return img.resize((img.width * CROP_ZOOM, img.height * CROP_ZOOM), Image.LANCZOS)


def save_crop_files(path, out_dir):
    """사진의 측정줄을 잘라 확대한 PNG 파일로 저장(웹용).

    tkinter/ImageTk 없이 PIL만 씀 - 데스크탑은 화면에 바로 그려서 파일이
    필요 없지만(_crop_image), 웹은 브라우저가 <img>로 불러올 실제 파일이
    있어야 함. 잘라내는 규칙(여백·확대배율)은 데스크탑과 완전히 같음 -
    같은 crop_boxes()를 쓰므로 어느 쪽에서 봐도 같은 그림이 뜸.

    반환: 저장한 파일 이름 목록(row_0.png, row_1.png, ...) - 순서가 곧
    crop_boxes()가 돌려주는 순서(사진 위에서 아래로)."""
    os.makedirs(out_dir, exist_ok=True)
    names = []
    for i, box in enumerate(crop_boxes(path)):
        name = f'row_{i}.png'
        _cropped_pil_image(path, box).save(os.path.join(out_dir, name))
        names.append(name)
    return names


# ------------------------------------------------------------
#  4) 화면
# ------------------------------------------------------------
class ManualEntryDialog(tk.Toplevel):
    """사진 한 장씩 보여주며 못 읽은 값을 받는 창."""

    def __init__(self, master, items):
        super().__init__(master)
        self.title('못 읽은 측정값 직접 입력')
        self.items = items
        self.index = 0
        self.result = {}          # {사진경로: [행, ...]}
        self._photos = []         # PhotoImage 참조 유지용(안 그러면 그림이 사라짐)

        self.body = ttk.Frame(self, padding=12)
        self.body.pack(fill='both', expand=True)

        nav = ttk.Frame(self, padding=(12, 0, 12, 12))
        nav.pack(fill='x')
        self.progress = ttk.Label(nav, text='')
        self.progress.pack(side='left')
        ttk.Button(nav, text='전체 건너뛰기', command=self._skip_all).pack(side='right')
        ttk.Button(nav, text='이 사진 건너뛰기', command=self._next).pack(side='right', padx=6)
        ttk.Button(nav, text='저장하고 다음', command=self._save_and_next).pack(side='right')

        self._render()
        self.protocol('WM_DELETE_WINDOW', self._skip_all)
        self.grab_set()

    # ── 화면 그리기 ──────────────────────────────────────────
    def _render(self):
        for w in self.body.winfo_children():
            w.destroy()
        self._photos.clear()
        self.entries = []

        item = self.items[self.index]
        self.progress.config(
            text=f'{self.index + 1} / {len(self.items)}   {item["name"]}')

        head = ttk.Frame(self.body)
        head.pack(fill='x', pady=(0, 8))
        ttk.Label(head, text=f'{item["name"]}  ({item["kind"]})',
                  font=('', 11, 'bold')).pack(side='left')
        ttk.Label(head,
                  text=f'  측정줄 {item["line_count"]}개 중 {item["missing"]}개를 못 읽었어요',
                  foreground='#a45a06').pack(side='left')
        ttk.Button(head, text='사진 전체 열기',
                   command=lambda p=item['path']: _open_file(p)).pack(side='right')

        # 왼쪽: 잘라낸 줄 그림(크게). 오른쪽: 입력칸.
        panes = ttk.Frame(self.body)
        panes.pack(fill='both', expand=True)

        left = ttk.LabelFrame(panes, text='사진에서 잘라낸 측정줄', padding=8)
        left.pack(side='left', fill='both', expand=True, padx=(0, 10))
        try:
            for box in crop_boxes(item['path']):
                img = _crop_image(item['path'], box)
                self._photos.append(img)
                ttk.Label(left, image=img).pack(pady=3)
        except Exception as e:
            # 그림을 못 만들어도 입력은 할 수 있어야 하므로 창을 죽이지 않음
            ttk.Label(left, text=f'그림을 불러오지 못했어요: {e}').pack()

        right = ttk.Frame(panes)
        right.pack(side='left', fill='y')
        self._render_rows(right, item)

    def _render_rows(self, parent, item):
        # 이미 읽힌 행(참고용, 못 고침)과 새로 입력할 행의 칸 구성이 다름
        # (2026-08-07) — 새 행은 '값'만 필수고 '값과 같은 축(X 또는 방향에
        # 맞는 축)'은 실측으로 확인된 규칙(_axis_for_direction)에 따라 자동
        # 계산하므로 따로 안 물음. 반대쪽 축(오프셋)만 선택 입력으로 둠.
        is_overlay = item['category'] == 'overlay'

        if item['rows']:
            ttk.Label(parent, text='이미 읽힌 값 (참고용)',
                      font=('', 10, 'bold')).pack(anchor='w')
            header = ttk.Frame(parent)
            header.pack(anchor='w')
            for text, w in (('번호', 5), ('값', 9), ('X', 9), ('Y', 9)):
                ttk.Label(header, text=text, width=w,
                          foreground='#5c6b78').pack(side='left', padx=2)
            if is_overlay:
                ttk.Label(header, text='방향', width=6,
                          foreground='#5c6b78').pack(side='left', padx=2)
            # Overlay면 방향만 확인받음 — 4방향이 다 있어야 지표가 계산되므로.
            for r in item['rows']:
                self.entries.append(self._locked_row_widgets(parent, r, is_overlay))

        ttk.Label(parent, text='못 읽은 값 — 사진에 보이는 값만 입력해주세요',
                  font=('', 10, 'bold')).pack(anchor='w', pady=(14, 2))
        ttk.Label(parent,
                  text='예: "0=100.2,XY=(100.2,0.0)" 라면 100.2만 적으면 돼요.\n'
                       '오프셋(예의 0.0 자리)은 대부분 0이라 비워도 됩니다.',
                  foreground='#5c6b78', justify='left').pack(anchor='w', pady=(0, 6))

        new_header = ttk.Frame(parent)
        new_header.pack(anchor='w')
        ttk.Label(new_header, text='값', width=9,
                  foreground='#5c6b78').pack(side='left', padx=2)
        ttk.Label(new_header, text='오프셋(선택)', width=12,
                  foreground='#5c6b78').pack(side='left', padx=2)
        # forced_directions가 있으면(2026-08-10) 남은 방향이 소거법으로
        # 확정되는 경우라 물어볼 필요가 없음 - Overlay_X/Y가 절댓값이라
        # 좌/우(또는 상/하) 중 뭐가 뭔지는 계산에 안 쓰임(overlay_analysis.
        # infer_forced_directions 주석 참고). 그래서 그럴 땐 방향 칸을 아예
        # 안 보여주고 자동으로 채운다.
        forced = item.get('forced_directions')
        if is_overlay and forced is None:
            ttk.Label(new_header, text='방향', width=6,
                      foreground='#5c6b78').pack(side='left', padx=2)

        for i in range(item['missing']):
            auto_dir = forced[i] if forced is not None else None
            self.entries.append(self._new_row_widgets(parent, is_overlay, auto_dir))

        if is_overlay:
            if forced is not None:
                ttk.Label(parent, text='※ 방향은 자동으로 배정됐어요(값만 입력)',
                          foreground='#1a7f5a').pack(anchor='w', pady=(8, 0))
            else:
                ttk.Label(parent,
                          text='※ 상/하/좌/우가 하나씩 다 있어야 Overlay가 계산돼요',
                          foreground='#5c6b78').pack(anchor='w', pady=(8, 0))

    def _locked_row_widgets(self, parent, row, is_overlay):
        """이미 OCR로 읽힌 행. 값은 참고용으로만 보여주고 못 고침 —
           정상 판독을 임의로 바꾸지 않기 위해서(설계 원칙)."""
        line = ttk.Frame(parent)
        line.pack(anchor='w', pady=2)
        widgets = {'_locked': True, '_row': row}
        for key, width in (('번호', 5), ('값', 9), ('X', 9), ('Y', 9)):
            e = ttk.Entry(line, width=width)
            e.insert(0, str(row[key]))
            e.config(state='readonly')
            e.pack(side='left', padx=2)
            widgets[key] = e
        if is_overlay:
            cb = ttk.Combobox(line, values=DIRECTIONS, width=4, state='readonly')
            if row.get('방향'):
                cb.set(row['방향'])       # 위치로 추정된 값을 미리 채워 확인만 받음
            cb.pack(side='left', padx=2)
            widgets['방향'] = cb
        return widgets

    def _new_row_widgets(self, parent, is_overlay, auto_dir=None):
        """못 읽은 값을 새로 입력받는 행. '값'만 필수, '오프셋'은 선택.

        auto_dir가 있으면(소거법으로 방향이 확정된 경우) 드롭다운 대신
        읽기전용으로 값만 보여주고, _read_form()이 위젯 대신 이 값을 그대로
        쓴다(widgets['_forced_direction'])."""
        line = ttk.Frame(parent)
        line.pack(anchor='w', pady=2)
        widgets = {'_locked': False, '_row': None}

        value_e = ttk.Entry(line, width=9)
        value_e.pack(side='left', padx=2)
        widgets['값'] = value_e

        offset_e = ttk.Entry(line, width=12)
        offset_e.pack(side='left', padx=2)
        widgets['오프셋'] = offset_e

        if is_overlay:
            if auto_dir is not None:
                widgets['_forced_direction'] = auto_dir
                ttk.Label(line, text=f'{auto_dir}(자동)', width=8,
                          foreground='#1a7f5a').pack(side='left', padx=2)
            else:
                cb = ttk.Combobox(line, values=DIRECTIONS, width=4, state='readonly')
                cb.pack(side='left', padx=2)
                widgets['방향'] = cb

        return widgets

    # ── 버튼 동작 ────────────────────────────────────────────
    def _save_and_next(self):
        item = self.items[self.index]
        try:
            new_rows, directions = self._read_form()
        except ValueError as e:
            messagebox.showwarning('입력 확인', str(e), parent=self)
            return

        if item['category'] == 'overlay' and directions is not None:
            missing_dir = [d for d in DIRECTIONS if d not in directions]
            if missing_dir:
                if not messagebox.askyesno(
                        '방향 확인',
                        f'{", ".join(missing_dir)} 방향이 비어 있어요.\n'
                        'Overlay 지표는 계산되지 않습니다. 이대로 저장할까요?',
                        parent=self):
                    return

        self.result[item['path']] = new_rows
        self._apply_directions()
        self._next()

    def _read_form(self):
        """입력칸을 읽어 새 행 목록과 방향 목록을 만든다. 잘못됐으면 ValueError.

        번호는 사람에게 안 물음(2026-08-07) — 매칭·계산 어디에도 안 쓰이는
        표시용 값이라, 이미 읽힌 행이 쓴 번호를 피해 자동으로 채움."""
        used_numbers = {int(w['번호'].get()) for w in self.entries if w['_locked']}
        next_num = 0

        new_rows, directions = [], []
        has_direction = any('방향' in w or '_forced_direction' in w for w in self.entries)
        for w in self.entries:
            if '방향' in w:
                direction = w['방향'].get()
            else:
                direction = w.get('_forced_direction', '')
            if direction:
                directions.append(direction)
            if w['_locked']:
                continue

            value_text = w['값'].get().strip()
            offset_text = w['오프셋'].get().strip()
            if not value_text and not offset_text:
                continue          # 통째로 비워두면 그 줄은 포기한 것으로 봄
            if not value_text:
                raise ValueError('값 칸이 비어 있어요.')
            try:
                value = float(value_text)
                offset = float(offset_text) if offset_text else 0.0
            except ValueError:
                raise ValueError('숫자만 입력해주세요.')

            while next_num in used_numbers:
                next_num += 1
            used_numbers.add(next_num)
            new_rows.append(build_manual_row(next_num, value, offset, direction))
            next_num += 1
        return new_rows, (directions if has_direction else None)

    def _apply_directions(self):
        """이미 읽힌 행의 방향도 화면에서 확인받은 값을 '수동방향'에 남김
           (이유는 build_manual_row 주석 참고 - '방향'은 나중에 초기화됨)."""
        for w in self.entries:
            if w['_locked'] and w['_row'] is not None and '방향' in w:
                w['_row']['수동방향'] = w['방향'].get()

    def _next(self):
        self.index += 1
        if self.index >= len(self.items):
            self.destroy()
        else:
            self._render()

    def _skip_all(self):
        self.destroy()


def _open_file(path):
    """사진 전체를 기본 뷰어로 연다(윈도우 기준)."""
    try:
        os.startfile(path)
    except Exception:
        pass


# ------------------------------------------------------------
#  5) 바깥에서 부르는 입구
# ------------------------------------------------------------
def ask_manual_values(measured, master=None):
    """검토가 필요한 사진이 있으면 창을 띄워 값을 받고 {경로: [행,...]}을 반환.
       없으면 창을 안 띄우고 빈 dict."""
    items = pending_items(measured)
    if not items:
        return {}

    owns_root = master is None
    root = tk.Tk() if owns_root else master
    if owns_root:
        root.withdraw()
    dlg = ManualEntryDialog(root, items)
    root.wait_window(dlg)
    result = dlg.result
    if owns_root:
        root.destroy()
    return result
