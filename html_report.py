# -*- coding: utf-8 -*-
# ============================================================
#  결과 HTML 보고서 생성기
# ------------------------------------------------------------
#  엑셀은 "데이터를 뽑아 쓰는 용도", 이 HTML은 "한눈에 보는 용도".
#  인터넷 연결이 필요 없는 완전 로컬 파일로 만듦 (외부 라이브러리/CDN
#  없이 순수 SVG를 파이썬에서 직접 그림) — 폴더 하나만 옮기면 다른
#  컴퓨터에서 이 HTML 파일만 열어도 그대로 보임.
# ============================================================
import datetime
import math
import html as _html

# 반도체 CD 측정 도메인에 맞춘 색상 팔레트 (dataviz 스킬 참고자료 기준)
COLOR = {
    'good': '#0ca30c', 'warning': '#fab219', 'serious': '#ec835a', 'critical': '#d03b3b',
    'series': '#2a78d6', 'band': 'rgba(42,120,214,0.08)',
    'target': '#898781',
}


def _cpk_status(cpk):
    if cpk is None:
        return 'muted', '—'
    if cpk < 1.0:
        return 'critical', '위험'
    if cpk < 1.33:
        return 'warning', '주의'
    return 'good', '양호'


def _esc(s):
    return _html.escape(str(s))


# ------------------------------------------------------------
#  SVG 차트: Item 하나의 Point별 추이 (Target/스펙 밴드 포함)
# ------------------------------------------------------------
def _nice_ticks(lo, hi, n=4):
    """읽기 좋은 간격의 눈금 값을 계산 (예: 0.1, 0.2, 0.5 단위처럼)."""
    span = hi - lo
    if span <= 0:
        return [lo]
    raw_step = span / n
    mag = 10 ** math.floor(math.log10(raw_step))
    step = mag
    for m in (1, 2, 2.5, 5, 10):
        step = m * mag
        if step >= raw_step:
            break
    start = math.floor(lo / step) * step
    ticks, v = [], start
    while v <= hi + step * 0.001:
        if v >= lo - step * 0.001:
            ticks.append(round(v, 6))
        v += step
    return ticks


def _trend_svg(points, target, usl, lsl, width=640, height=230):
    """points: [(point_no, value), ...]  값 라벨을 점 위/아래에 직접 표시함."""
    pad_l, pad_r, pad_t, pad_b = 48, 20, 18, 34
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    values = [v for _, v in points]
    lo_candidates = values + ([lsl] if lsl is not None else [])
    hi_candidates = values + ([usl] if usl is not None else [])
    lo, hi = min(lo_candidates), max(hi_candidates)
    span = (hi - lo) or 1
    lo -= span * 0.18
    hi += span * 0.22
    span = hi - lo

    def ymap(v):
        return pad_t + plot_h - (v - lo) / span * plot_h

    def xmap(i):
        if len(points) == 1:
            return pad_l + plot_w / 2
        return pad_l + i / (len(points) - 1) * plot_w

    parts = [f'<svg viewBox="0 0 {width} {height}" class="trend-svg" role="img" aria-label="추이 그래프">']

    # 가로 눈금선 + Y축 값
    for t in _nice_ticks(lo, hi, 4):
        y = ymap(t)
        if y < pad_t - 1 or y > pad_t + plot_h + 1:
            continue
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" class="grid-line" />')
        parts.append(f'<text x="{pad_l - 8}" y="{y + 3:.1f}" class="axis-ytick" text-anchor="end">{t:g}</text>')

    # 스펙 밴드 (LSL~USL)
    if usl is not None and lsl is not None:
        y_usl, y_lsl = ymap(usl), ymap(lsl)
        parts.append(f'<rect x="{pad_l}" y="{y_usl:.1f}" width="{plot_w}" '
                      f'height="{(y_lsl - y_usl):.1f}" fill="{COLOR["band"]}" />')
        for label, yv in (('USL', usl), ('LSL', lsl)):
            y = ymap(yv)
            parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" class="spec-line" />')
            parts.append(f'<text x="{width - pad_r}" y="{y - 3:.1f}" class="spec-label" text-anchor="end">{label} {yv:g}</text>')

    # Target 기준선
    if target is not None:
        y = ymap(target)
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" class="target-line" />')
        parts.append(f'<text x="{pad_l + 4}" y="{y - 4:.1f}" class="spec-label">Target {target:g}</text>')

    # 데이터 선
    path_d = ' '.join(
        f'{"M" if i == 0 else "L"}{xmap(i):.1f},{ymap(v):.1f}' for i, (_, v) in enumerate(points)
    )
    parts.append(f'<path d="{path_d}" class="trend-path" />')

    # 점 + 값 직접 표시(라벨) + Point 번호(X축)
    for i, (pno, v) in enumerate(points):
        x, y = xmap(i), ymap(v)
        out = usl is not None and lsl is not None and not (lsl <= v <= usl)
        cls = 'pt pt-out' if out else 'pt'
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" class="{cls}">'
                      f'<title>Point {pno}: {v:g}</title></circle>')
        label_y = y - 9 if i % 2 == 0 else y + 15
        lbl_cls = 'pt-label pt-label-out' if out else 'pt-label'
        parts.append(f'<text x="{x:.1f}" y="{label_y:.1f}" class="{lbl_cls}" text-anchor="middle">{v:g}</text>')
        parts.append(f'<text x="{x:.1f}" y="{pad_t + plot_h + 14:.1f}" class="axis-xtick" text-anchor="middle">{pno}</text>')

    parts.append(f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{width - pad_r}" y2="{pad_t + plot_h}" class="axis-line" />')
    parts.append('</svg>')
    return ''.join(parts)


def _bar_svg(items, width=620, height=None, unit_h=34):
    """items: [(라벨, 값, 상태색), ...] 가로 막대그래프."""
    pad_l, pad_r, pad_t = 140, 50, 10
    height = height or (len(items) * unit_h + pad_t + 10)
    plot_w = width - pad_l - pad_r
    max_v = max((v for _, v, _ in items if v is not None), default=1) * 1.15 or 1

    parts = [f'<svg viewBox="0 0 {width} {height}" class="bar-svg" role="img" aria-label="Item별 비교">']
    for i, (label, v, color) in enumerate(items):
        y = pad_t + i * unit_h
        bw = 0 if v is None else max(2, v / max_v * plot_w)
        parts.append(f'<text x="{pad_l - 10}" y="{y + unit_h * 0.6:.1f}" class="bar-label" text-anchor="end">{_esc(label)}</text>')
        parts.append(f'<rect x="{pad_l}" y="{y + 6}" width="{bw:.1f}" height="{unit_h - 14}" rx="3" fill="{color}" />')
        vtxt = '—' if v is None else f'{v:g}'
        parts.append(f'<text x="{pad_l + bw + 8:.1f}" y="{y + unit_h * 0.6:.1f}" class="bar-value">{vtxt}</text>')
    parts.append('</svg>')
    return ''.join(parts)


# ------------------------------------------------------------
#  본문 조립
# ------------------------------------------------------------
def _kpi_tile(label, value, sub=''):
    return (f'<div class="tile"><div class="tile-label">{_esc(label)}</div>'
            f'<div class="tile-value">{_esc(value)}</div>'
            f'<div class="tile-sub">{_esc(sub)}</div></div>')


# 지표 스트립의 타일별 강조색. 값 자체는 본문 잉크로 두고 왼쪽 띠로만 구분함
# (숫자에 색을 입히면 색이 데이터를 뜻하는 것처럼 읽혀서 오히려 헷갈림).
_STRIP_ACCENTS = ['#2a78d6', '#d03b3b', '#0ca30c', '#fab219', '#3d4451', '#7b5ea7', '#2a78d6']


def _fmt_um(v):
    return '—' if v is None else f'{v:.3f} μm'


def _metric_cell(label, value, accent, note='', value_color=''):
    style = f' style="color:{value_color}"' if value_color else ''
    note_html = f'<div class="metric-note">{_esc(note)}</div>' if note else ''
    return (f'<div class="metric" style="--accent:{accent}">'
            f'<div class="metric-label">{_esc(label)}</div>'
            f'<div class="metric-value"{style}>{_esc(value)}</div>'
            f'{note_html}</div>')


def _metric_strip(stat):
    """항목 하나의 산포 지표들(평균/최대/최소/편차/1σ/3σ/CDU/판정)을 타일로."""
    cells = [
        _metric_cell('Mean (평균)', _fmt_um(stat.get('Avg')), _STRIP_ACCENTS[0]),
        _metric_cell('Max (최대)', _fmt_um(stat.get('Max')), _STRIP_ACCENTS[1]),
        _metric_cell('Min (최소)', _fmt_um(stat.get('Min')), _STRIP_ACCENTS[2]),
        _metric_cell('Max-Min (편차)', _fmt_um(stat.get('Range')), _STRIP_ACCENTS[3]),
        _metric_cell('표준편차 (1σ)', _fmt_um(stat.get('Std')), _STRIP_ACCENTS[4]),
        _metric_cell('3-Sigma (3σ)', _fmt_um(stat.get('3σ')), _STRIP_ACCENTS[5]),
    ]

    cdu = stat.get('CDU%')
    cells.append(_metric_cell('CDU [%]', '—' if cdu is None else f'{cdu:.2f} %',
                              _STRIP_ACCENTS[6], note='3σ / Mean × 100'))

    verdict = stat.get('판정')
    v_status = {'PASS': 'good', 'FAIL': 'critical'}.get(verdict, 'muted')
    cells.append(_metric_cell('Overall 판정', verdict or '—', f'var(--{v_status})',
                              value_color=f'var(--{v_status})'))

    return f'<div class="metric-strip">{"".join(cells)}</div>'


def _cpk_card(stat):
    status, status_label = _cpk_status(stat.get('Cpk'))
    # Avg/Std는 아래 지표 스트립에서 보여주므로, 여기엔 스펙 정보만 남김(중복 제거)
    rows = ''.join(
        f'<div class="kv"><span>{k}</span><b>{"—" if v is None else v}</b></div>'
        for k, v in [('Target', stat.get('Target')), ('USL', stat.get('USL')), ('LSL', stat.get('LSL'))]
    )
    trend = ''
    if stat.get('_trend'):
        trend = _trend_svg(stat['_trend'], stat.get('Target'), stat.get('USL'), stat.get('LSL'))
    return f'''
    <div class="card">
      <div class="card-head">
        <div class="card-title">{_esc(stat['표시명'])}</div>
        <div class="badge badge-{status}">{status_label}</div>
      </div>
      <div class="card-body">
        <div class="cpk-big">
          <div class="cpk-num" style="color:var(--{status})">{'—' if stat.get('Cpk') is None else stat['Cpk']}</div>
          <div class="cpk-caption">CPK · N={stat.get('N')}</div>
          <div class="cp-sub">CP {stat.get('Cp', '—')}</div>
        </div>
        <div class="kv-list">{rows}</div>
      </div>
      {_metric_strip(stat)}
      {f'<div class="trend-wrap">{trend}</div>' if trend else ''}
    </div>'''


def _item_breakdown_section(item_breakdown):
    """웹 결과 화면(2026-08-12)과 같은 정보 - 확인필요/스펙이탈/겹침/포인트 수
       불일치를 Item별로. 웹은 왼쪽 강조선 목록이지만, 여기 보고서는 이미
       표(table-wrap)를 쓰는 곳이 많아 같은 표 부품을 그대로 재사용함
       (문제 있는 줄만 이름 앞에 강조선을 넣어 웹 화면과 같은 신호를 줌)."""
    if not item_breakdown:
        return ''

    def num_cell(value, has_concept):
        if not has_concept:
            return '<td class="ib-dash">–</td>'
        cls = 'ib-warn' if value else 'ib-ok'
        return f'<td class="{cls}">{value}</td>'

    rows = []
    for e in item_breakdown:
        issue = e['flagged'] or e['out_of_spec'] or e['overlap'] or e['mismatch']
        rows.append(
            f'<tr class="{"ib-issue" if issue else ""}">'
            f'<td class="ib-name">{_esc(e["name"])}</td>'
            f'<td class="ib-points">{e["points"]}포인트</td>'
            + num_cell(e['flagged'], True)
            + num_cell(e['out_of_spec'], e['has_spec'])
            + num_cell(e['overlap'], True)
            + num_cell(1 if e['mismatch'] else 0, e['has_mismatch'])
            + '</tr>'
        )
    return f'''
    <h2>Item별 확인 사항</h2>
    <div class="table-wrap">
      <table class="ib-table"><thead><tr>
        <th>Item</th><th>포인트 수</th><th>확인필요</th><th>스펙이탈</th><th>겹침</th><th>포인트 수 불일치</th>
      </tr></thead><tbody>{''.join(rows)}</tbody></table>
    </div>'''


def build_report(df, overlay_df, stats_rows, plan, save_path, item_breakdown=None):
    """측정결과 df, overlay 요약 df, Cpk 통계, 계획을 받아 HTML 보고서를 저장.
       item_breakdown: measurement_plan.compute_item_breakdown()의 결과(선택) -
       없으면(예: 옛 호출부) 그 구간만 조용히 빠짐."""
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

    # 각 Item의 Point별 추이 데이터를 stats_rows에 붙임 (표시명은 compute_stats에서 이미 계산됨)
    for s in stats_rows:
        sub = df[df['항목'] == s['항목']][['Point', '측정값(um)']].sort_values('Point')
        s['_trend'] = list(sub.itertuples(index=False, name=None)) if not sub.empty else []

    total = len(df)
    n_point = df['Point'].nunique() if 'Point' in df.columns else 0
    out_of_spec = int((df['스펙이탈'] == '예').sum())
    flagged = int((df['확인필요'] == '예').sum())

    kpi_html = ''.join([
        _kpi_tile('공정', plan.process, plan.layer or plan.cd_label),
        _kpi_tile('총 측정값', f'{total}개', f'Point {n_point}개'),
        _kpi_tile('스펙이탈', f'{out_of_spec}개', 'USL/LSL 벗어남'),
        _kpi_tile('확인필요', f'{flagged}개', 'OCR 신뢰도 낮음'),
    ])

    cpk_bar = _bar_svg([
        (s['표시명'], s.get('Cpk'), f'var(--{_cpk_status(s.get("Cpk"))[0]})')
        for s in stats_rows
    ]) if stats_rows else ''

    cards_html = ''.join(_cpk_card(s) for s in stats_rows)

    overlay_section = ''
    if overlay_df is not None and not overlay_df.empty:
        ov_avg = round(overlay_df['Overlay'].mean(), 4)
        ov_max = round(overlay_df['Overlay'].max(), 4)
        pts = list(overlay_df[['Point', 'Overlay']].itertuples(index=False, name=None))
        overlay_trend = _trend_svg(pts, None, None, None)
        rows_html = ''.join(
            f'<tr><td>{r.Point}</td><td>{_esc(r.파일명)}</td><td>{r.상}</td><td>{r.하}</td>'
            f'<td>{r.좌}</td><td>{r.우}</td><td>{r.Overlay_X}</td><td>{r.Overlay_Y}</td><td><b>{r.Overlay}</b></td></tr>'
            for r in overlay_df.itertuples(index=False)
        )
        overlay_section = f'''
        <h2>Overlay</h2>
        <div class="kpi-row">
          {_kpi_tile('평균 Overlay', ov_avg)}
          {_kpi_tile('최대 Overlay', ov_max)}
        </div>
        <div class="card"><div class="card-head"><div class="card-title">Point별 Overlay 추이</div></div>
          <div class="trend-wrap">{overlay_trend}</div></div>
        <details class="table-wrap"><summary>Overlay 표 보기</summary>
          <table><thead><tr><th>Point</th><th>파일명</th><th>상</th><th>하</th><th>좌</th><th>우</th>
          <th>Overlay_X</th><th>Overlay_Y</th><th>Overlay</th></tr></thead>
          <tbody>{rows_html}</tbody></table></details>'''

    def _cell(v):
        return '—' if v is None else v

    stats_rows_html = ''.join(
        f'<tr><td>{_esc(s["표시명"])}</td><td>{s["N"]}</td><td>{_cell(s.get("Avg"))}</td>'
        f'<td>{_cell(s.get("Std"))}</td><td>{_cell(s.get("3σ"))}</td><td>{_cell(s.get("CDU%"))}</td>'
        f'<td>{_cell(s.get("Target"))}</td><td>{_cell(s.get("Tolerance"))}</td>'
        f'<td>{_cell(s.get("USL"))}</td><td>{_cell(s.get("LSL"))}</td>'
        f'<td>{_cell(s.get("Cp"))}</td><td><b>{_cell(s.get("Cpk"))}</b></td>'
        f'<td class="verdict-{ {"PASS": "good", "FAIL": "critical"}.get(s.get("판정"), "muted") }">'
        f'{_cell(s.get("판정"))}</td></tr>'
        for s in stats_rows
    )

    name_parts = [p for p in (plan.customer, plan.material, plan.layer) if p]
    title = f'{" ".join(name_parts)} Photo 측정 결과 보고서' if name_parts else 'CD 측정 결과 보고서'

    html_doc = f'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>{_esc(title)}</title>
<style>
{_CSS}
</style>
</head>
<body>
<div class="page">
  <header>
    <div class="brand">
      <span class="brand-badge">
        <svg viewBox="0 0 32 32" fill="none" aria-hidden="true">
          <rect x="2.8" y="2.8" width="26.4" height="26.4" stroke="currentColor" stroke-width="2.8"/>
          <path d="M16 9.4v13.2M9.4 16h13.2" stroke="currentColor" stroke-width="3.2"/>
        </svg>
      </span>
      <span class="brand-name"><span class="brand-metro">Metro</span><span class="brand-pilot">Pilot</span></span>
    </div>
    <h1>{_esc(title)}</h1>
    <div class="meta">생성 시각 {now} · 공정 {_esc(plan.process)}</div>
  </header>

  <div class="kpi-row">{kpi_html}</div>

  {_item_breakdown_section(item_breakdown)}

  <h2>Item별 CPK</h2>
  <div class="card"><div class="card-body-plain">{cpk_bar}</div></div>

  <div class="card-grid">{cards_html}</div>

  {overlay_section}

  <h2>전체 통계표</h2>
  <details class="table-wrap" open><summary>Item별 통계 (표로 보기)</summary>
    <table><thead><tr><th>항목</th><th>N</th><th>Avg</th><th>Std (1σ)</th><th>3σ</th><th>CDU%</th>
    <th>Target</th><th>Tol.</th><th>USL</th><th>LSL</th><th>CP</th><th>CPK</th><th>판정</th></tr></thead>
    <tbody>{stats_rows_html}</tbody></table>
  </details>

  <footer>원본 데이터/전체 측정값은 같은 폴더의 <code>측정결과.xlsx</code>를 참고하세요.</footer>
</div>
</body>
</html>'''

    with open(save_path, 'w', encoding='utf-8') as f:
        f.write(html_doc)
    return save_path


_CSS = '''
:root {
  /* 2026-08-12 - webapp/static/style.css의 MetroPilot 팔레트와 통일(브랜드
     일관성). 그 앱은 다크 모드가 없으므로 이 리포트도 다크 모드 대응을
     빼고 항상 같은 밝은 색으로 고정 - 앱과 리포트가 시스템 설정에 따라
     서로 다른 색으로 보이면 오히려 "같은 제품"처럼 안 느껴지기 때문. */
  color-scheme: light;
  --surface-1: #ffffff; --page: #eef1f3;
  --text-primary: #16212b; --text-secondary: #5c6b78; --text-muted: #8d99a4;
  --grid: #edf0f3; --border: #d8dee4;
  --good: #1a7f5a; --warning: #a45a06; --serious: #a45a06; --critical: #b3261e; --muted: #8d99a4;
  --series: #1c3f5f;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--text-primary);
  font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif;
  -webkit-font-smoothing: antialiased; }
.page { max-width: 1040px; margin: 0 auto; padding: 40px 24px 70px; }
header { margin-bottom: 28px; padding-bottom: 18px; border-bottom: 1px solid var(--border); }
.brand { display: inline-flex; align-items: center; gap: 8px; margin-bottom: 16px; }
.brand-badge { background: var(--series); color: #fff; display: inline-flex; align-items: center;
  justify-content: center; padding: 6px; border-radius: 6px; }
.brand-badge svg { width: 18px; height: 18px; display: block; }
.brand-name { font-weight: 700; font-size: 16px; letter-spacing: -0.02em; }
.brand-metro { color: var(--text-primary); }
.brand-pilot { color: var(--series); }
h1 { font-size: 24px; margin: 0 0 6px; letter-spacing: -0.01em; }
/* 2026-08-17 - 섹션 제목을 검정에서 브랜드 남색으로. 그전에는 남색이 로고
   배지에만 찍혀 있어서 리포트가 사실상 흑백 문서로 보였음(헤더 영역 픽셀을
   세어보니 강조색이 19%뿐). 색 자체를 바꾸는 대신 "이미 쓰는 색을 더 넓게
   쓰는" 쪽을 택한 것 - 판정색(초록/주황/빨강)이 이미 4종이라 색을 더 늘리면
   무엇이 신호인지 흐려지기 때문. */
h2 { font-size: 15px; margin: 34px 0 12px; color: var(--series);
  text-transform: uppercase; letter-spacing: 0.04em; font-weight: 700; }
.meta { color: var(--text-secondary); font-size: 13px; }
.kpi-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px,1fr)); gap: 12px; margin: 16px 0; }
.tile { background: var(--surface-1); border: 1px solid var(--border); border-radius: 14px;
  padding: 16px 18px; box-shadow: 0 1px 2px rgba(11,11,11,0.04), 0 8px 20px -14px rgba(11,11,11,0.18); }
.tile-label { font-size: 11.5px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.03em; }
.tile-value { font-size: 26px; font-weight: 700; margin-top: 4px; font-variant-numeric: tabular-nums; letter-spacing: -0.02em; }
.tile-sub { font-size: 12px; color: var(--text-secondary); margin-top: 3px; }
.card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 16px;
  padding: 18px 20px; margin-bottom: 14px;
  box-shadow: 0 1px 2px rgba(11,11,11,0.04), 0 8px 24px -16px rgba(11,11,11,0.20);
  transition: box-shadow .15s ease; }
.card:hover { box-shadow: 0 2px 4px rgba(11,11,11,0.06), 0 14px 30px -16px rgba(11,11,11,0.26); }
.card-body-plain { overflow-x: auto; }
/* 2026-08-13 - 예전엔 카드 2개가 나란히 붙어서 정사각형처럼 보였음(사용자
   지적) - 한 줄에 하나씩, 화면 폭 전체를 쓰는 가로로 긴 카드로 바꿈. */
.card-grid { display: grid; grid-template-columns: 1fr; gap: 14px; }
.card-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;
  padding-bottom: 10px; border-bottom: 1px solid var(--grid); }
.card-title { font-weight: 700; font-size: 14.5px; }
.badge { font-size: 11.5px; padding: 3px 11px; border-radius: 999px; font-weight: 700;
  letter-spacing: 0.01em; }
.badge-good { background: color-mix(in srgb, var(--good) 16%, transparent); color: var(--good); }
.badge-warning { background: color-mix(in srgb, var(--warning) 24%, transparent); color: var(--warning); }
.badge-critical { background: color-mix(in srgb, var(--critical) 16%, transparent); color: var(--critical); }
.badge-muted { background: color-mix(in srgb, var(--muted) 16%, transparent); color: var(--text-muted); }
.card-body { display: flex; gap: 22px; align-items: center; flex-wrap: wrap; }
.cpk-big { text-align: center; min-width: 96px; }
.cpk-num { font-size: 36px; font-weight: 800; font-variant-numeric: tabular-nums; letter-spacing: -0.02em; }
.cpk-caption { font-size: 11px; color: var(--text-muted); margin-top: 2px; }
.cp-sub { font-size: 12.5px; color: var(--text-secondary); margin-top: 4px; font-weight: 600; }
.kv-list { flex: 1; min-width: 170px; }
.kv { display: flex; justify-content: space-between; font-size: 12.5px; color: var(--text-secondary);
  border-bottom: 1px solid var(--grid); padding: 4px 0; }
.kv b { color: var(--text-primary); font-variant-numeric: tabular-nums; }
.metric-strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(116px, 1fr));
  gap: 8px; margin-top: 14px; }
.metric { border-left: 3px solid var(--accent); border-radius: 0 9px 9px 0; padding: 9px 11px;
  background: color-mix(in srgb, var(--accent) 6%, transparent); }
.metric-label { font-size: 10.5px; color: var(--text-secondary); font-weight: 700; letter-spacing: 0.01em; }
.metric-value { font-size: 15.5px; font-weight: 700; margin-top: 3px;
  font-variant-numeric: tabular-nums; letter-spacing: -0.015em; }
.metric-note { font-size: 9.5px; color: var(--text-muted); margin-top: 2px; }
.trend-wrap { margin-top: 12px; overflow-x: auto; }
.trend-svg, .bar-svg { width: 100%; height: auto; display: block; }
.trend-path { fill: none; stroke: var(--series); stroke-width: 2.25; stroke-linejoin: round; stroke-linecap: round; }
.grid-line { stroke: var(--grid); stroke-width: 1; }
.axis-ytick { font-size: 10px; fill: var(--text-muted); font-variant-numeric: tabular-nums; }
.axis-xtick { font-size: 9px; fill: var(--text-muted); }
.spec-line { stroke: var(--text-muted); stroke-width: 1; stroke-dasharray: 2 3; opacity: 0.7; }
.spec-label { font-size: 9.5px; fill: var(--text-muted); font-variant-numeric: tabular-nums; }
.target-line { stroke: var(--text-secondary); stroke-width: 1.25; stroke-dasharray: 4 3; }
.axis-line { stroke: var(--grid); stroke-width: 1; }
.pt { fill: var(--surface-1); stroke: var(--series); stroke-width: 2.25; }
.pt-out { fill: var(--critical); stroke: var(--critical); }
.pt-label { font-size: 10.5px; fill: var(--text-secondary); font-weight: 600;
  font-variant-numeric: tabular-nums; }
.pt-label-out { fill: var(--critical); font-weight: 700; }
/* CPK 막대 그래프의 항목 이름. 원래 회색(--text-secondary, 흰 배경 대비
   5.5:1)이라 바로 옆 숫자(--text-primary, 16.3:1)보다 연했음 - "이름이 값보다
   흐린" 뒤바뀐 위계였음(2026-08-17 사용자 지적). 숫자와 같은 색·굵기로 맞춤. */
.bar-label { font-size: 12.5px; fill: var(--text-primary); font-weight: 700; }
.bar-value { font-size: 12.5px; fill: var(--text-primary); font-weight: 700; font-variant-numeric: tabular-nums; }
table { border-collapse: collapse; width: 100%; font-size: 12.5px; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--grid); white-space: nowrap; }
/* 표 머리글도 남색 계열로(2026-08-17). 단 11.5px로 작아서 진한 남색을 그대로
   쓰면 정작 봐야 할 데이터보다 머리글이 튐 - 흰색을 30% 섞어 색상은 같고
   밝기만 올린 남색을 씀. color-mix는 "이 색에 저 색을 몇 % 섞어라"는 뜻. */
th { color: color-mix(in srgb, var(--series) 70%, var(--surface-1)); font-weight: 700; font-size: 11.5px; text-transform: uppercase; letter-spacing: 0.02em; }
td { font-variant-numeric: tabular-nums; }
tbody tr:hover { background: color-mix(in srgb, var(--series) 6%, transparent); }
.verdict-good { color: var(--good); font-weight: 700; }
.verdict-critical { color: var(--critical); font-weight: 700; }
.verdict-muted { color: var(--text-muted); }
/* Item별 확인 사항(2026-08-12) - 문제 있는 줄만 이름 앞에 강조선(웹 결과
   화면의 왼쪽 강조선과 같은 신호). 강조선 없는 줄도 폭이 안 흔들리게
   투명 테두리를 기본값으로 둠. */
.ib-name { font-weight: 700; border-left: 3px solid transparent; padding-left: 7px; }
tr.ib-issue .ib-name { border-left-color: var(--warning); }
.ib-points { color: var(--text-muted); }
.ib-warn { color: var(--warning); font-weight: 700; }
.ib-ok { color: var(--good); }
.ib-dash { color: var(--text-muted); }
.table-wrap { background: var(--surface-1); border: 1px solid var(--border); border-radius: 14px;
  padding: 14px 18px; margin-top: 12px; overflow-x: auto;
  box-shadow: 0 1px 2px rgba(11,11,11,0.04), 0 8px 20px -16px rgba(11,11,11,0.18); }
summary { cursor: pointer; font-weight: 700; font-size: 13px; }
footer { margin-top: 36px; font-size: 12px; color: var(--text-muted); }
code { background: var(--grid); padding: 2px 6px; border-radius: 5px; font-size: 11.5px; }
'''
