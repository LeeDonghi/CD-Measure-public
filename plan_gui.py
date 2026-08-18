# -*- coding: utf-8 -*-
# ============================================================
#  측정 계획 입력용 GUI (tkinter)
# ------------------------------------------------------------
#  0) 고객/자재/Layer 입력
#  1) 공정(RDL/PI/Bump/Cu Post) 선택
#  2) 공정에 맞는 CD 종류(Pad CD/Via CD/UBM CD/Cu Post CD) + (RDL이면 Line&Space도)
#     Item 개수를 입력하고 "생성" 누르면 Item별 입력칸이 만들어짐
#  3) Overlay 측정 포인트 개수 입력
#  4) "폴더 선택하고 시작" 누르면 사진 폴더를 고르고 계획을 반환함
# ============================================================
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from measurement_plan import CDItem, LSItem, MeasurementPlan
from tolerance_table import lookup_tolerance, CD_PATTERN_BY_PROCESS

# 공정별로 CD 종류 이름이 달라짐
CD_LABEL_BY_PROCESS = {
    'RDL': 'Pad CD',
    'PI': 'Via CD',
    'Bump': 'UBM CD',
    'Cu Post': 'Cu Post CD',
}


def _optional_float(text):
    """비워둘 수 있는 숫자 칸을 읽음. 빈 칸이면 None(= 그 항목 없음)."""
    text = (text or '').strip()
    return float(text) if text else None


class ItemListSection(ttk.LabelFrame):
    """'Item 개수' 입력 + 생성 버튼 + Item별 입력칸들을 담당하는 위젯.
       with_space=True 면 Line/Space Target 두 칸, 아니면 Target 한 칸."""

    def __init__(self, master, title, with_space=False):
        super().__init__(master, text=title, padding=10)
        self.with_space = with_space
        self.item_rows = []  # 각 원소: dict(points=Entry, target=Entry, target2=Entry|None)

        top = ttk.Frame(self)
        top.pack(fill='x')
        ttk.Label(top, text='Item 개수:').pack(side='left')
        self.count_entry = ttk.Entry(top, width=5)
        self.count_entry.pack(side='left', padx=5)
        ttk.Button(top, text='생성', command=self._build_rows).pack(side='left')

        self.rows_frame = ttk.Frame(self)
        self.rows_frame.pack(fill='x', pady=(8, 0))

    def _build_rows(self):
        try:
            n = int(self.count_entry.get())
            if n < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror('입력 오류', 'Item 개수는 0 이상의 숫자로 입력해주세요.')
            return

        for w in self.rows_frame.winfo_children():
            w.destroy()
        self.item_rows = []

        header = ttk.Frame(self.rows_frame)
        header.pack(fill='x')
        ttk.Label(header, text='', width=10).pack(side='left')
        ttk.Label(header, text='측정 포인트 수').pack(side='left', padx=5)
        if self.with_space:
            ttk.Label(header, text='Line Target').pack(side='left', padx=5)
            ttk.Label(header, text='Space Target').pack(side='left', padx=5)
            # Item마다 Line만 또는 Space만 있을 수 있어서 한쪽은 비워도 됨
            ttk.Label(self, text='※ Line과 Space 중 없는 쪽은 비워두세요 '
                                 '(둘 다 비우면 안 됩니다)',
                      foreground='#5c6b78').pack(anchor='w', pady=(4, 0))
        else:
            ttk.Label(header, text='Target').pack(side='left', padx=5)

        for i in range(1, n + 1):
            row = ttk.Frame(self.rows_frame)
            row.pack(fill='x', pady=2)
            ttk.Label(row, text=f'Item {i}', width=10).pack(side='left')
            points_e = ttk.Entry(row, width=10)
            points_e.pack(side='left', padx=5)
            target_e = ttk.Entry(row, width=10)
            target_e.pack(side='left', padx=5)
            target2_e = None
            if self.with_space:
                target2_e = ttk.Entry(row, width=10)
                target2_e.pack(side='left', padx=5)
            self.item_rows.append({'points': points_e, 'target': target_e, 'target2': target2_e})

    def read_items(self, name_prefix, process):
        """입력값을 (CDItem 또는 LSItem) 목록으로 변환. Tolerance는 공정별
           기준표(tolerance_table.py)에서 Target 값으로 자동 조회함.
           잘못된 값이 있으면 예외 발생."""
        items = []
        for i, row in enumerate(self.item_rows, start=1):
            points = int(row['points'].get())
            if self.with_space:
                # Line/Space는 Item마다 독립이라 한쪽만 있을 수 있음
                # (예: Item1 = Line 10만, Item2 = Space 20만). 빈 칸은 None.
                t_line = _optional_float(row['target'].get())
                t_space = _optional_float(row['target2'].get())
                if t_line is None and t_space is None:
                    raise ValueError(
                        f'{name_prefix} Item {i}: Line과 Space 중 최소 한쪽은 입력해주세요.')
                tol_line = lookup_tolerance(process, 'L/S', t_line) if t_line is not None else None
                tol_space = lookup_tolerance(process, 'L/S', t_space) if t_space is not None else None
                items.append(LSItem(f'{name_prefix} Item {i}', points, t_line, t_space,
                                     tol_line, tol_space))
            else:
                target = float(row['target'].get())
                pattern = CD_PATTERN_BY_PROCESS.get(process, 'CD')
                tolerance = lookup_tolerance(process, pattern, target)
                items.append(CDItem(f'{name_prefix} Item {i}', points, target, tolerance))
        return items


class PlanApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('CD 측정 프로그램 - 측정 계획 입력')
        self.geometry('520x600')
        self.result = None  # (MeasurementPlan, folder_path)

        self.process_var = tk.StringVar(value='RDL')
        self._customer = ''
        self._material = ''
        self._layer = ''
        self._build_step0()

    # ---------------- 0단계: 고객/자재/Layer 입력 ----------------
    def _build_step0(self):
        for w in self.winfo_children():
            w.destroy()

        frame = ttk.Frame(self, padding=20)
        frame.pack(fill='both', expand=True)

        ttk.Label(frame, text='기본 정보를 입력하세요', font=('', 13, 'bold')).pack(pady=(0, 15))

        grid = ttk.Frame(frame)
        grid.pack(fill='x')
        self.customer_entry = self._labeled_entry(grid, '고객', 0, self._customer)
        self.material_entry = self._labeled_entry(grid, '자재', 1, self._material)
        self.layer_entry = self._labeled_entry(grid, 'Layer', 2, self._layer)

        ttk.Button(frame, text='다음', command=self._go_step1).pack(pady=20)

    @staticmethod
    def _labeled_entry(parent, label, row, initial=''):
        ttk.Label(parent, text=f'{label}:', width=8).grid(row=row, column=0, sticky='w', pady=4)
        e = ttk.Entry(parent, width=30)
        e.grid(row=row, column=1, sticky='w', pady=4)
        if initial:
            e.insert(0, initial)
        return e

    def _go_step1(self):
        self._customer = self.customer_entry.get().strip()
        self._material = self.material_entry.get().strip()
        self._layer = self.layer_entry.get().strip()
        self._build_step1()

    # ---------------- 1단계: 공정 선택 ----------------
    def _build_step1(self):
        for w in self.winfo_children():
            w.destroy()

        frame = ttk.Frame(self, padding=20)
        frame.pack(fill='both', expand=True)

        ttk.Label(frame, text='공정을 선택하세요', font=('', 13, 'bold')).pack(pady=(0, 15))
        for proc in ('RDL', 'PI', 'Bump', 'Cu Post'):
            ttk.Radiobutton(frame, text=proc, value=proc, variable=self.process_var).pack(anchor='w', pady=3)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(pady=20)
        ttk.Button(btn_frame, text='뒤로', command=self._build_step0).pack(side='left', padx=5)
        ttk.Button(btn_frame, text='다음', command=self._build_step2).pack(side='left', padx=5)

    # ---------------- 2단계: Item/Target/Overlay 입력 ----------------
    def _build_step2(self):
        process = self.process_var.get()
        cd_label = CD_LABEL_BY_PROCESS[process]

        for w in self.winfo_children():
            w.destroy()

        outer = ttk.Frame(self, padding=15)
        outer.pack(fill='both', expand=True)

        ttk.Label(outer, text=f'{process} 측정 계획 입력', font=('', 13, 'bold')).pack(pady=(0, 10))

        self.ls_section = None
        if process == 'RDL':
            self.ls_section = ItemListSection(outer, 'Line & Space', with_space=True)
            self.ls_section.pack(fill='x', pady=5)

        self.cd_section = ItemListSection(outer, cd_label, with_space=False)
        self.cd_section.pack(fill='x', pady=5)

        overlay_frame = ttk.LabelFrame(outer, text='Overlay', padding=10)
        overlay_frame.pack(fill='x', pady=5)
        ttk.Label(overlay_frame, text='측정 포인트 수:').pack(side='left')
        self.overlay_entry = ttk.Entry(overlay_frame, width=10)
        self.overlay_entry.pack(side='left', padx=5)

        btn_frame = ttk.Frame(outer)
        btn_frame.pack(pady=15)
        ttk.Button(btn_frame, text='뒤로', command=self._build_step1).pack(side='left', padx=5)
        ttk.Button(btn_frame, text='폴더 선택하고 시작', command=self._finish).pack(side='left', padx=5)

        self._process = process
        self._cd_label = cd_label

    def _finish(self):
        try:
            cd_items = self.cd_section.read_items(self._cd_label, self._process)
            ls_items = self.ls_section.read_items('Line&Space', self._process) if self.ls_section else []
            overlay_points = int(self.overlay_entry.get() or 0)
        except ValueError:
            messagebox.showerror('입력 오류', '숫자 칸에 숫자가 아닌 값이 있어요. 다시 확인해주세요.')
            return

        if not cd_items and not ls_items:
            if not messagebox.askyesno('확인', 'Item을 하나도 만들지 않았어요. 그래도 계속할까요?'):
                return

        folder = filedialog.askdirectory(title='사진이 들어있는 폴더를 선택하세요')
        if not folder:
            return

        plan = MeasurementPlan(
            process=self._process,
            cd_label=self._cd_label,
            cd_items=cd_items,
            ls_items=ls_items,
            overlay_points=overlay_points,
            customer=self._customer,
            material=self._material,
            layer=self._layer,
        )
        self.result = (plan, folder)
        self.destroy()


def collect_plan_and_folder():
    """GUI를 띄워 측정 계획과 사진 폴더 경로를 입력받음.
       사용자가 취소하면 None 반환."""
    app = PlanApp()
    app.mainloop()
    return app.result
