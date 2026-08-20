# -*- coding: utf-8 -*-
"""케이스 스터디(docs/case-study.md)를 사이트 화면으로 변환한다.

왜 빌드 시점에 변환하나 (2026-08-20)
------------------------------------
설명하는 글이 README·케이스 스터디·아티팩트 세 군데에 흩어져 있어서, 한 곳만
고치면 나머지가 조용히 어긋났다. 그래서 **원본은 docs/case-study.md 하나**로 두고
사이트는 그것을 렌더해서 보여준다.

변환을 요청 때마다 하지 않고 여기서 미리 해두는 이유:
  - 서버(webapp/requirements.txt)에 markdown 의존성을 늘리지 않아도 된다.
    사내망에서 설치 승인 없이 돌아가야 하는 제약이 있어 의존성은 얇게 유지한다.
  - 글은 배포 사이에 바뀌지 않으므로 매 요청 변환은 낭비다.

⚠️ 이 스크립트를 돌리려면 개발 PC에 markdown이 필요하다(`pip install markdown`).
   서버에는 필요 없다. 다른 컴퓨터에서 이어받을 때는
   `집에서_이어서_작업하기.md`의 설치 안내를 볼 것.

쓰는 법
-------
    python scripts/build_case_study.py

docs/case-study.md 를 고쳤으면 이걸 다시 돌리고, 나온 템플릿까지 함께 커밋한다.
"""
import io
import os
import re
import shutil
import sys

import markdown

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'docs', 'case-study.md')
OUT = os.path.join(ROOT, 'webapp', 'templates', 'case_study.html')
IMG_SRC = os.path.join(ROOT, 'docs', 'images')
IMG_OUT = os.path.join(ROOT, 'webapp', 'static', 'case')

# 페이지 맨 위 제목은 템플릿이 <h1>으로 직접 그리므로 본문에서는 뺀다
# (안 그러면 h1이 두 개가 되어 화면에도 어색하고 문서 구조상으로도 틀림).
FIRST_H1 = '# '

# 저장소 안에서만 통하는 링크 -> 사이트에서도 열리는 주소.
# 공개 저장소 쪽을 가리킨다(Private 저장소는 방문자가 못 엶).
LINK_MAP = {
    '../README.md': 'https://github.com/LeeDonghi/CD-Measure-public#readme',
}

HEADER = """{{% extends "base.html" %}}

{{# ⚠️ 이 파일은 손으로 고치지 말 것 — scripts/build_case_study.py 가
   docs/case-study.md 로부터 만들어낸다. 글을 고치려면 그 마크다운을 고치고
   스크립트를 다시 돌릴 것. #}}

{{% block title %}}MetroPilot - 어떻게 만들었나{{% endblock %}}
{{% block body_class %}}page-case{{% endblock %}}
{{% block brand_tag %}}<span class="brand-tag">케이스 스터디</span>{{% endblock %}}

{{% block nav %}}
<a href="{{{{ url_for('demo_intro') }}}}">데모 체험</a> &nbsp;|&nbsp;
<a href="{{{{ url_for('login') }}}}">로그인</a>
{{% endblock %}}

{{% block content %}}
<h1>{title}</h1>
<nav class="case-toc" aria-label="목차">
  <span class="case-toc-label">목차</span>
  {toc}
</nav>
<div class="case-body">
{body}
</div>
{{% endblock %}}
"""


def build():
    if not os.path.isfile(SRC):
        sys.exit(f'원본이 없습니다: {SRC}')

    text = io.open(SRC, encoding='utf-8').read()

    lines = text.splitlines()
    title = ''
    for i, line in enumerate(lines):
        if line.startswith(FIRST_H1):
            title = line[len(FIRST_H1):].strip()
            lines = lines[i + 1:]
            break
    if not title:
        sys.exit('맨 위 "# 제목" 줄을 찾지 못했습니다.')

    # toc: 절마다 id를 붙여 목차에서 건너뛸 수 있게. toc_depth 2-2는 큰 절(h2)만
    # 목차에 담는다는 뜻 - 12개나 되는 절을 다 펼치면 목차가 본문만큼 길어진다.
    md = markdown.Markdown(
        # tables: 부록의 표, fenced_code: 코드 블록, sane_lists: 목록이
        # 문단으로 뭉개지지 않게
        extensions=['tables', 'fenced_code', 'sane_lists', 'toc'],
        extension_configs={'toc': {'toc_depth': '2-2'}},
        output_format='html',
    )
    body = md.convert('\n'.join(lines))
    toc = md.toc

    # 마크다운의 --- 구분선은 화면에서 큰 절 제목의 윗선과 겹쳐 구분선이 두 겹이
    # 된다. 원본에는 남겨두고(GitHub에서는 필요함) 화면에서만 뺀다.
    body = body.replace('<hr>', '')

    # 글에 들어간 이미지를 사이트가 서빙할 수 있는 자리로 복사하고 주소를 바꾼다.
    # 마크다운은 GitHub에서도 그대로 읽혀야 하므로 원본은 docs/images/ 상대경로.
    os.makedirs(IMG_OUT, exist_ok=True)
    for name in sorted(set(re.findall(r'src="images/([^"]+)"', body))):
        src_path = os.path.join(IMG_SRC, name)
        if not os.path.isfile(src_path):
            sys.exit(f'글이 가리키는 이미지가 없습니다: {src_path}')
        shutil.copy2(src_path, os.path.join(IMG_OUT, name))
        body = body.replace(f'src="images/{name}"',
                            f'src="/static/case/{name}"')

    # 못 옮긴 이미지가 남으면 사이트에서 깨진 그림이 된다.
    stray = re.findall(r'src="(?!/static/)([^"]+)"', body)
    if stray:
        sys.exit(f'사이트에서 열리지 않는 이미지가 있습니다: {stray}')

    # 저장소 안에서만 통하는 상대 링크를 사이트에서도 열리는 주소로 바꾼다.
    # (마크다운은 GitHub에서도 그대로 읽혀야 하므로 원본은 상대 링크로 둔다)
    for src_link, dst_link in LINK_MAP.items():
        body = body.replace(f'href="{src_link}"', f'href="{dst_link}"')

    # 못 바꾼 .md 링크가 남으면 사이트에서 404가 된다 - 조용히 넘기지 않는다.
    leftovers = re.findall(r'href="([^"]*\.md[^"]*)"', body)
    if leftovers:
        sys.exit(f'사이트에서 열리지 않는 링크가 있습니다: {leftovers} — '
                 'LINK_MAP에 바꿀 주소를 추가하세요.')

    # Jinja가 본문 속 {{ }} / {% %} 를 문법으로 착각하지 않도록 확인만 한다.
    # (지금 글에는 없지만, 나중에 코드 예시로 들어오면 화면이 통째로 깨진다)
    for token in ('{{', '{%'):
        if token in body:
            sys.exit(f'본문에 Jinja 문법과 겹치는 "{token}" 이 있습니다 — '
                     'raw 처리가 필요합니다.')

    html = HEADER.format(title=title, body=body, toc=toc)
    io.open(OUT, 'w', encoding='utf-8', newline='').write(html)
    print(f'{OUT} ({len(html):,} bytes) — 제목 "{title}", 본문 {len(body):,} bytes')


if __name__ == '__main__':
    build()
