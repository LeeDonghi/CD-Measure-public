# -*- coding: utf-8 -*-
# ============================================================
#  CD Measure(MetroPilot) 웹 버전
# ------------------------------------------------------------
#  로그인 → 측정 계획 입력 → 사진 업로드 → OCR/매칭/Cpk 계산 → 엑셀·HTML
#  결과까지. 계산 로직은 데스크탑판(CD측정값_엑셀변환.py)을 그대로 재사용함 —
#  두 판이 다른 결과를 내면 안 되므로.
#
#  ⚠️ 이 서버는 인터넷에 공개돼 있음(https://metropilot.duckdns.org, Caddy가
#  HTTPS 처리). 처음(2026-07-30)에는 "사내망 전용, 공인 IP 노출 금지"였지만
#  2026-08-04에 외부 배포로 바뀌었고, 2026-08-18에는 로그인 없이 쓰는 공개
#  데모(/demo)까지 열었음. 그래서 라우트를 새로 추가할 때는 @login_required를
#  빠뜨리지 않았는지 반드시 확인할 것 — 빠뜨리면 그대로 인터넷에 열린다.
# ============================================================
import dataclasses
import glob
import importlib
import json
import math
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
import uuid

import pandas as pd
from flask import (
    Flask, render_template, redirect, url_for, request, flash,
    send_from_directory, abort, jsonify,
)
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user,
)
from werkzeug.utils import secure_filename

WEBAPP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(WEBAPP_DIR)
sys.path.insert(0, WEBAPP_DIR)
sys.path.insert(0, PROJECT_DIR)  # 기존 데스크탑 프로그램 코드(ocr_core 등)를 그대로 재사용하기 위함

import users as user_store
import activity_log
# 메인 파일명이 한글이라 import 문법으로 바로 못 쓰는 환경이 있어 importlib로 불러옴
core = importlib.import_module('CD측정값_엑셀변환')
from ocr_core import load_templates
from measurement_plan import CDItem, LSItem, MeasurementPlan, plan_from_dict, compute_item_breakdown
from tolerance_table import lookup_tolerance, CD_PATTERN_BY_PROCESS
from plan_gui import CD_LABEL_BY_PROCESS
from manual_entry import pending_items, build_manual_row, save_crop_files

app = Flask(__name__)

# 인터넷에 열리면 봇이 비밀번호를 자동으로 계속 찍어보는 시도(무차별 대입, brute
# force)를 하는데, Caddy 같은 리버스 프록시 뒤에 놓이면 요청이 프록시를 거쳐
# 오므로 request.remote_addr이 실제 접속자 IP가 아니라 프록시(예: 127.0.0.1)로
# 찍힘. CD_MEASURE_TRUST_PROXY=1일 때만 Caddy가 보내는 X-Forwarded-For 헤더를
# 신뢰하도록 함(프록시 없이 이 값을 무조건 믿으면 누구나 헤더를 조작해서 IP를
# 속일 수 있어 위험 - 반드시 "프록시가 실제로 앞에 있을 때만" 켜야 함).
if os.environ.get('CD_MEASURE_TRUST_PROXY') == '1':
    from werkzeug.middleware.proxy_fix import ProxyFix
    # x_for: 실제 접속자 IP(로그인 잠금에 씀). x_proto: 실제로는 https로 들어왔다는
    # 걸 앱이 알게 함(안 하면 Caddy가 https를 http로 바꿔 넘겨준 것처럼 보여서,
    # 쿠키의 Secure 속성 등에서 나중에 문제가 될 수 있음).
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

# 업로드한 사진 + 처리 결과(엑셀/HTML)를 실행마다 폴더 하나씩 나눠 저장하는 곳.
# 데스크탑 버전은 "사용자가 고른 사진 폴더"에 결과를 저장하지만, 웹에서는 그런
# 폴더가 없으므로(파일을 업로드받는 방식) 서버 안에 임시 저장 공간을 따로 둠.
#
# CD_MEASURE_DATA_DIR이 있으면 그 아래에 둠(Docker 배포용 — 컨테이너 안에 두면
# 컨테이너를 다시 만들 때 지난 결과를 다시 내려받을 수 없게 됨).
UPLOAD_ROOT = os.path.join(
    os.environ.get('CD_MEASURE_DATA_DIR') or WEBAPP_DIR, 'uploads')
os.makedirs(UPLOAD_ROOT, exist_ok=True)

# 공개 데모용 가짜 계측기 사진(scripts/make_demo_images.py로 만듦)을 딱 한 번
# 만들어 두고 재사용하는 곳. uploads/ 안에 안 두는 이유: 그 폴더는 7일 지난
# 사진을 자동 정리하는 배치 잡 대상이라, 실행마다 쓰는 원본(demo_source)이
# 지워지면 안 되기 때문.
DEMO_SOURCE_DIR = os.path.join(
    os.environ.get('CD_MEASURE_DATA_DIR') or WEBAPP_DIR, 'demo_source')


def _ensure_demo_source():
    """데모 사진 폴더가 없으면 한 번만 만든다. seed가 고정된
       build_demo_folder를 쓰므로 언제 다시 만들어도 항상 같은 36장이
       나온다. 이미 폴더가 있으면 내용을 다시 확인하지 않고 그대로 씀
       (배포 후 사람이 이 폴더를 건드릴 일이 없다는 전제).

       ⚠️ 원자성(atomicity) 보장:
       build_demo_folder는 36장을 한 줄씩 쓰므로 중단되면 불완전한
       폴더가 남는다. 일회용 임시 폴더에 다 생성한 뒤 성공하면 한 번에
       실제 폴더로 옮기는 방식(temp-then-rename 패턴)으로, 불완전한
       상태가 영구화되는 것을 방지함.

       ⚠️ 동시 워커 안전성(concurrent worker safety under gunicorn -w 4):
       배포 시 gunicorn -w 4로 4개 워커가 띄어질 때, 두 워커가 동시에
       처음 /demo를 접속하면 모두 _ensure_demo_source()에 진입할 수 있음.
       고정 경로(예: '.tmp')를 쓰면, 한 워커가 다른 워커의 진행 중인
       생성을 mid-write에 삭제해 corruption을 일으킬 수 있음.

       따라서 build_demo_folder(..., seed=고정)는 결정적이므로(같은
       내용을 반복 생성함), 두 워커 모두 성공하고 같은 내용으로
       os.replace()해도 괜찮음 - 즉, lock이 필요 없고, 고유한 임시
       경로만으로 충분함. tempfile.mkdtemp()로 워커마다 별개 임시
       폴더를 만들어 삭제 경합을 원천 차단함.

       ⚠️ os.replace() 경합 처리:
       os.replace(src_dir, dst_dir)는 dst_dir이 이미 존재하고 비어있지
       않으면 OSError를 raise함. 두 워커가 동시에 성공할 수 없으므로
       한 워커의 replace는 "다른 워커가 이미 성공했다"는 뜻 - 내용이
       결정적으로 같으니 예외를 무시하고 클린업하고 반환해도 됨.
       단, DEMO_SOURCE_DIR이 실제로 유효한지 확인 후 반환."""
    if os.path.isdir(DEMO_SOURCE_DIR) and os.listdir(DEMO_SOURCE_DIR):
        return DEMO_SOURCE_DIR

    from scripts.make_demo_images import build_demo_folder, build_preview_assets

    # 워커마다 고유한 임시 폴더를 만듦 - 동시 접속 시 삭제 경합 방지
    parent_dir = os.path.dirname(DEMO_SOURCE_DIR)
    os.makedirs(parent_dir, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(dir=parent_dir, prefix='demo_source_tmp_')

    # 성공할 때까지 임시 폴더에서만 작업 - 실제 폴더는 untouched.
    # 중간에 실패하면(디스크 용량 부족, 템플릿 로드 실패 등) 임시 폴더에
    # 이미 쓰인 부분 파일들이 남는데, 정리 안 하면 /demo가 실패할 때마다
    # 폴더가 하나씩 계속 쌓임(2026-08-18 최종 리뷰에서 발견) - 예외를 잡아
    # 임시 폴더를 지운 뒤 그대로 다시 던짐.
    try:
        build_demo_folder(tmp_dir)
        # 미리보기(preview/)도 반드시 임시 폴더 안에서 완성해야 한다. os.replace()
        # 뒤에 만들면 원자성이 깨져서, 그 사이에 끊겼을 때 '사진은 있는데 미리보기만
        # 없는' 반쪽 폴더가 영구히 고착된다(_ensure_demo_source는 폴더가 있으면
        # 그냥 반환하므로 다시 만들 기회가 없다).
        build_preview_assets(tmp_dir)
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    # build_demo_folder가 반환되었다 = 36장 다 생성 완료.
    # 이제 원자적으로 실제 위치로 이동(같은 디스크라면 rename은 원자적).
    # os.replace()는 디렉토리 자체를 이동시키므로 임시 폴더는 정리됨.
    try:
        os.replace(tmp_dir, DEMO_SOURCE_DIR)
    except OSError:
        # 다른 워커가 이미 성공적으로 replace를 완료했다는 뜻.
        # 내용이 결정적으로 동일하므로 그 워커의 폴더를 재사용해도 됨.
        # 다만 DEMO_SOURCE_DIR이 실제로 유효한지 확인하고,
        # 우리의 임시 폴더는 정리함.
        shutil.rmtree(tmp_dir, ignore_errors=True)

        # DEMO_SOURCE_DIR이 실제로 유효한지 확인
        if not (os.path.isdir(DEMO_SOURCE_DIR) and os.listdir(DEMO_SOURCE_DIR)):
            # 다른 워커의 replace도 실패했거나 아직 생성 중 → 진짜 문제
            raise

    return DEMO_SOURCE_DIR

# SECRET_KEY는 로그인 세션(쿠키)을 위·변조로부터 지키는 값이라 외부에 알려지면
# 안 됨. 코드에 그대로 박아두면 git에 남아서 위험하므로 환경변수로 받되,
# 안 넘어온 경우(로컬 테스트용)에만 임시로 무작위 값을 씀 — 이 경우 서버를
# 재시작할 때마다 로그인이 풀린다는 단점이 있어서, 실제 배포 때는 반드시
# CD_MEASURE_SECRET_KEY를 지정해야 함(README/Dockerfile 참고).
app.secret_key = os.environ.get('CD_MEASURE_SECRET_KEY') or os.urandom(24)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = '로그인이 필요합니다.'


class User(UserMixin):
    def __init__(self, username):
        self.id = username


@login_manager.user_loader
def load_user(username):
    # 매 요청마다 불리는 함수라 users.json을 다시 읽지 않고, 아이디가
    # 존재했었다는 사실(세션에 저장된 값)만으로 User 객체를 만듦.
    # 그 사이 계정이 삭제됐어도 다음 로그인 시도부터 막히면 되므로 충분함.
    return User(username)


# ------------------------------------------------------------
#  로그인 무차별 대입(brute force) 방어
#  같은 IP가 짧은 시간에 로그인을 계속 실패하면 잠깐 막음. 인터넷에 공개되면
#  봇이 흔한 비밀번호를 자동으로 계속 찍어보는 시도가 실제로 들어오므로,
#  사내망 전용일 때는 없어도 됐지만 외부 배포하는 지금은 필수로 판단함.
# ------------------------------------------------------------
LOGIN_MAX_ATTEMPTS = 5       # 이 횟수 실패하면 잠금
LOGIN_WINDOW_SECONDS = 5 * 60     # 이 시간 안의 실패만 셈(오래된 실패는 무시)
LOGIN_LOCKOUT_SECONDS = 15 * 60   # 잠기면 이만큼 기다려야 함


def _login_attempts_path():
    data_dir = os.environ.get('CD_MEASURE_DATA_DIR') or WEBAPP_DIR
    return os.path.join(data_dir, 'login_attempts.json')


def _read_login_attempts():
    path = _login_attempts_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _write_login_attempts(data):
    path = _login_attempts_path()
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f)
    os.replace(tmp, path)


def _client_ip():
    # ProxyFix(위)가 적용돼 있으면 remote_addr이 이미 실제 접속자 IP로 바뀜
    return request.remote_addr or 'unknown'


def check_login_lockout(ip):
    """잠겨 있으면 (True, 남은 초), 아니면 (False, 0)."""
    data = _read_login_attempts()
    entry = data.get(ip)
    if not entry:
        return False, 0
    remaining = entry.get('locked_until', 0) - time.time()
    if remaining > 0:
        return True, int(remaining)
    return False, 0


def record_login_failure(ip):
    data = _read_login_attempts()
    now = time.time()
    entry = data.get(ip, {'attempts': [], 'locked_until': 0})
    # 시간 창(LOGIN_WINDOW_SECONDS)을 벗어난 오래된 실패 기록은 버림
    entry['attempts'] = [t for t in entry.get('attempts', []) if now - t < LOGIN_WINDOW_SECONDS]
    entry['attempts'].append(now)
    if len(entry['attempts']) >= LOGIN_MAX_ATTEMPTS:
        entry['locked_until'] = now + LOGIN_LOCKOUT_SECONDS
        entry['attempts'] = []  # 잠갔으니 카운트는 리셋
    data[ip] = entry
    _write_login_attempts(data)


def record_login_success(ip):
    data = _read_login_attempts()
    if ip in data:
        del data[ip]
        _write_login_attempts(data)


# ------------------------------------------------------------
#  공개 데모 하루 사용량 제한
#  로그인 잠금(위)은 "짧은 시간창 안 실패 횟수"로 무차별 대입을 막는 게
#  목적이지만, 데모는 실패가 아니라 "정상 사용을 하루에 몇 번까지"를 막는
#  것(사진 처리가 서버 CPU를 쓰므로). 그래서 롤링 윈도우 대신 그날 자정
#  기준으로 카운트한다.
# ------------------------------------------------------------
DEMO_DAILY_LIMIT = 5


def _demo_attempts_path():
    data_dir = os.environ.get('CD_MEASURE_DATA_DIR') or WEBAPP_DIR
    return os.path.join(data_dir, 'demo_attempts.json')


def _read_demo_attempts():
    path = _demo_attempts_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _write_demo_attempts(data):
    path = _demo_attempts_path()
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f)
    os.replace(tmp, path)


def check_demo_limit(ip):
    """오늘 한도를 다 썼으면 (True, 오늘 실행 횟수), 아니면 (False, 그 횟수)."""
    data = _read_demo_attempts()
    today = time.strftime('%Y-%m-%d')
    entry = data.get(ip)
    count = entry['count'] if entry and entry.get('date') == today else 0
    return count >= DEMO_DAILY_LIMIT, count


def record_demo_run(ip):
    data = _read_demo_attempts()
    today = time.strftime('%Y-%m-%d')
    entry = data.get(ip)
    count = entry['count'] if entry and entry.get('date') == today else 0
    # 오늘 날짜가 아닌 옛 기록은 여기서 같이 정리함 - 안 지우면 한 번이라도
    # /demo/start를 호출한 IP가 영원히 파일에 쌓임(공개 인터넷 엔드포인트라
    # 방문 IP가 계속 늘어남). login_attempts.json은 로그인 성공 때
    # record_login_success로 지워지지만, 데모는 "성공/실패" 개념이 없어서
    # 그 방식을 못 쓰므로 날짜 기준으로 대신 정리함.
    data = {k: v for k, v in data.items() if v.get('date') == today}
    data[ip] = {'date': today, 'count': count + 1}
    _write_demo_attempts(data)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    if request.method == 'POST':
        ip = _client_ip()
        locked, remaining = check_login_lockout(ip)
        if locked:
            minutes = remaining // 60 + 1
            flash(f'로그인 시도가 너무 많습니다. {minutes}분 뒤 다시 시도해 주세요.')
            return render_template('login.html')

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if user_store.verify(username, password):
            record_login_success(ip)
            login_user(User(username))
            activity_log.record(username, '로그인', ip)
            return redirect(url_for('home'))
        record_login_failure(ip)
        # 실패도 남김 — 잠금용 login_attempts.json은 IP만 담고 시간이 지나면
        # 지워지므로, "누구 아이디로 시도했는지"는 여기에만 남는다.
        activity_log.record(username, '로그인실패', ip)
        flash('아이디 또는 비밀번호가 올바르지 않습니다.')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    activity_log.record(current_user.id, '로그아웃', _client_ip())
    logout_user()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def home():
    return render_template('home.html', username=current_user.id,
                           is_admin=user_store.is_admin(current_user.id))


# 임시 비밀번호를 쓰는 동안에도 접근할 수 있어야 하는 화면들.
# 이게 없으면 비밀번호를 바꾸러 가지도, 로그아웃하지도 못하고 갇힘.
_ALLOWED_WHILE_MUST_CHANGE = {'change_password', 'logout', 'login', 'static'}


@app.before_request
def _force_password_change():
    """임시 비밀번호 상태면 비밀번호 변경 화면으로 몰아넣음.

    라우트마다 검사를 넣으면 새 화면을 추가할 때 빠뜨리기 쉬워서, 모든 요청을
    한 곳에서 거른다.
    """
    if not current_user.is_authenticated:
        return None
    if request.endpoint in _ALLOWED_WHILE_MUST_CHANGE:
        return None
    if user_store.must_change_password(current_user.id):
        return redirect(url_for('change_password'))
    return None


@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    forced = user_store.must_change_password(current_user.id)
    if request.method == 'POST':
        old = request.form.get('old_password', '')
        new = request.form.get('new_password', '')
        new2 = request.form.get('new_password2', '')
        if new != new2:
            flash('새 비밀번호 두 개가 서로 다릅니다.')
        else:
            ok, message = user_store.change_password(current_user.id, old, new)
            flash(message)
            if ok:
                activity_log.record(current_user.id, '비밀번호변경', _client_ip())
                return redirect(url_for('home'))

    return render_template('change_password.html', username=current_user.id,
                           forced=forced, min_length=user_store.MIN_PASSWORD_LENGTH)


@app.route('/access_log')
@login_required
def access_log():
    """누가 언제 접속해서 무엇을 했는지 보는 화면. 관리자 전용.

    일반 사용자에게 404를 주는 이유: 403(권한 없음)을 주면 "이런 화면이 있긴
    하다"는 사실이 알려지므로, 아예 없는 주소인 것처럼 보이게 함.
    """
    if not user_store.is_admin(current_user.id):
        abort(404)
    return render_template('access_log.html', username=current_user.id,
                           entries=activity_log.read_recent())


# ------------------------------------------------------------
#  측정 계획 입력 폼(웹판 plan_gui.py) -> 업로드 -> 처리 -> 결과
# ------------------------------------------------------------
def _optional_float(text):
    """비워둘 수 있는 숫자 칸을 읽음. 빈 칸이면 None(= 그 항목 없음)."""
    text = (text or '').strip()
    return float(text) if text else None


def build_plan_from_form(form):
    """제출된 폼 값으로 MeasurementPlan을 만듦. plan_gui.py의
       ItemListSection.read_items / PlanApp._finish와 같은 로직을
       (tkinter 위젯 대신) request.form에서 그대로 반복함.
       숫자 칸에 이상한 값이 있으면 ValueError가 그대로 올라감."""
    process = form.get('process', 'RDL')
    cd_label = CD_LABEL_BY_PROCESS[process]

    cd_items = []
    cd_count = int(form.get('cd_count') or 0)
    for i in range(1, cd_count + 1):
        points = int(form[f'cd_points_{i}'])
        target = float(form[f'cd_target_{i}'])
        pattern = CD_PATTERN_BY_PROCESS.get(process, 'CD')
        tolerance = lookup_tolerance(process, pattern, target)
        cd_items.append(CDItem(f'{cd_label} Item {i}', points, target, tolerance))

    ls_items = []
    if process == 'RDL':
        ls_count = int(form.get('ls_count') or 0)
        for i in range(1, ls_count + 1):
            points = int(form[f'ls_points_{i}'])
            # Line/Space는 Item마다 독립이라 한쪽만 있을 수 있음
            # (예: Item1 = Line 10만, Item2 = Space 20만). 빈 칸은 None.
            t_line = _optional_float(form.get(f'ls_target_line_{i}'))
            t_space = _optional_float(form.get(f'ls_target_space_{i}'))
            if t_line is None and t_space is None:
                raise ValueError(f'Line&Space Item {i}: Line과 Space 중 최소 한쪽은 입력해주세요.')
            tol_line = lookup_tolerance(process, 'L/S', t_line) if t_line is not None else None
            tol_space = lookup_tolerance(process, 'L/S', t_space) if t_space is not None else None
            ls_items.append(LSItem(f'Line&Space Item {i}', points, t_line, t_space,
                                    tol_line, tol_space))

    overlay_points = int(form.get('overlay_points') or 0)

    return MeasurementPlan(
        process=process, cd_label=cd_label, cd_items=cd_items, ls_items=ls_items,
        overlay_points=overlay_points,
        customer=form.get('customer', '').strip(),
        material=form.get('material', '').strip(),
        layer=form.get('layer', '').strip(),
    )


def _progress_path(run_dir):
    return os.path.join(run_dir, '.progress.json')


def write_progress(run_dir, **state):
    # 여러 gunicorn 워커 프로세스가 있으면 메모리(dict)는 프로세스마다 따로라서
    # 공유가 안 됨 - 백그라운드 스레드가 쓴 진행률을 다른 워커가 처리하는
    # /progress 요청이 못 보게 됨. 그래서 디스크 파일(같은 /data 볼륨)로 공유함.
    # 쓰다 만 파일을 읽는 걸 막기 위해 임시 파일에 쓰고 나서 이름을 바꿈(원자적 교체).
    path = _progress_path(run_dir)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, path)


def read_progress(run_dir):
    path = _progress_path(run_dir)
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None  # 쓰는 도중에 읽었을 때 - 다음 폴링에서 다시 시도하면 됨


def _run_meta(plan):
    """실행 기록 목록(/runs)에서 보여줄 최소 정보. 진행 중/성공/실패 어느
       상태로 쓰든 이 값들은 항상 같이 남겨서, 목록에서 "누가 언제 무슨
       공정을 돌렸는지"를 상태와 상관없이 알 수 있게 함."""
    return {'customer': plan.customer, 'material': plan.material,
            'layer': plan.layer, 'process': plan.process}


def _write_failure_log(run_dir, plan, files, message, detail_lines=None):
    """core.save_run_log은 성공(df 등이 다 만들어진) 케이스만 다루므로,
       처리 자체가 실패했을 때도 웹 화면(/log)에서 원인을 볼 수 있게 최소한의
       로그 파일을 따로 남김. 성공 시 로그와 같은 이름 규칙(측정로그_시각.txt)을
       써서 /runs, /log가 성공/실패 구분 없이 같은 방식으로 찾을 수 있게 함."""
    timestamp = time.strftime('%Y%m%d_%H%M%S')
    log_path = os.path.join(run_dir, f'측정로그_{timestamp}.txt')
    lines = [
        f'실행 시각: {time.strftime("%Y-%m-%d %H:%M:%S")}',
        f'공정: {plan.process} ({plan.cd_label})',
        f'고객/자재/Layer: {plan.customer or "-"} / {plan.material or "-"} / {plan.layer or "-"}',
        f'입력 사진: {len(files)}장',
        '',
        f'*** 처리 실패: {message} ***',
    ]
    if detail_lines:
        lines += ['', '--- 상세 ---'] + list(detail_lines)
    try:
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
    except OSError:
        pass  # 로그조차 못 쓰면(디스크 문제 등) 어쩔 수 없음 - progress.json의 message는 남음


# 수동 입력 재개에 필요한 상태를 저장하는 파일 이름. .progress.json과 달리
# 폴링용이 아니라 "폼 제출이 오면 여기서 이어서 처리한다"는 내부용 데이터라
# 따로 둠. 처리가 끝나면 지움(더는 필요 없는 임시 파일).
MANUAL_STATE_FILE = '.manual_state.json'
# 데모 결과 화면이 '이 사진에서 이 값을 읽었다'를 보여줄 때 쓰는 파일.
PHOTO_READ_FILE = '사진별판독.json'


def _manual_crop_dir(run_dir, idx):
    return os.path.join(run_dir, 'manual_crops', str(idx))


def _enter_manual_input_state(run_dir, plan, files, measured, log, evidence_records,
                              operator, started, category=''):
    """OCR로 다 못 읽은 사진이 있을 때, 처리를 멈추고 사람 입력을 기다리는
       상태로 전환. 스레드는 여기서 끝나고(사람이 언제 답할지 모르니 계속
       붙잡고 있을 수 없음), 폼 제출은 별개의 나중 HTTP 요청(POST
       /manual_input/<run_id>)이 이어받는다."""
    meta = dict(_run_meta(plan), operator=operator)
    pending = pending_items(measured)

    # 화면에 보여줄 최소 정보만 pending에 담음(진행률 파일은 매 폴링마다
    # 읽히므로 너무 크면 안 됨). crop 그림은 파일로 저장하고 파일명만 남김.
    pending_summary = []
    for idx, item in enumerate(pending):
        crop_dir = _manual_crop_dir(run_dir, idx)
        crops = save_crop_files(item['path'], crop_dir)
        pending_summary.append({
            'idx': idx,
            'name': os.path.basename(item['path']),
            'category': item['category'],
            'kind': item['kind'],
            'missing': item['missing'],
            'line_count': item['line_count'],
            'crops': crops,
            # 이미 읽힌 값은 참고용으로만 보여줌(desktop과 같은 원칙 - 못 고침).
            # 5번째 자리(방향)는 위치로 추정된 값이 있으면 채워서 드롭다운을
            # 미리 선택해둠(2026-08-10, pending_items가 미리 계산해둔 것).
            'rows': [[r['번호'], r['값'], r['X'], r['Y'], r.get('방향', '')]
                    for r in item['rows']],
            # 남은 방향이 소거법으로 확정되면(overlay_analysis.
            # infer_forced_directions) 화면에서 방향을 안 물어봄 - 절댓값
            # 계산이라 좌/우(또는 상/하) 순서가 결과에 안 쓰이기 때문.
            'forced_directions': item['forced_directions'],
        })

    # 재개에 필요한 원시 데이터는 별도 파일에 저장(진행률 파일과 분리 -
    # 이건 화면이 안 읽고 POST 처리 쪽만 읽음).
    state_path = os.path.join(run_dir, MANUAL_STATE_FILE)
    with open(state_path, 'w', encoding='utf-8') as f:
        json.dump({
            'plan': dataclasses.asdict(plan),
            'files': files,
            'measured': measured,
            'log': log,
            'evidence_records': evidence_records,
            'operator': operator,
            'started': started,
            # operator처럼 재개(resume) 때 그대로 되살려야 함 - 안 남기면
            # manual_input_submit이 항상 category=''로 _finalize_and_save를
            # 불러서 실행이력.csv에 구분이 사라짐(2026-08-18 최종 리뷰,
            # 지금은 데모 폴더가 확인필요 0건으로 검증돼 있어 실제로는 이
            # 경로를 안 타지만 방어적으로 고쳐둠).
            'category': category,
        }, f, ensure_ascii=False)

    write_progress(run_dir, status='manual_input', pending=pending_summary, **meta)


def _finalize_and_save(run_dir, plan, files, all_data, overlay_summaries, log,
                       operator, started, category=''):
    """core.main()의 엑셀/HTML 생성 부분과 동일한 로직(데스크탑 버전과 웹
       버전이 다른 결과를 내면 안 되므로 core의 함수를 그대로 재사용).
       처음부터 끝까지 자동으로 끝난 경우와, 사람이 입력을 마치고 재개한
       경우 둘 다 여기서 마무리함."""
    meta = dict(_run_meta(plan), operator=operator)

    if not all_data:
        message = '어떤 사진에서도 측정값을 읽지 못했습니다.'
        _write_failure_log(run_dir, plan, files, message, log)
        write_progress(run_dir, status='error', message=message, **meta)
        return

    df = pd.DataFrame(all_data)[
        # ⚠️ 데스크탑판(CD측정값_엑셀변환.py)의 열 목록과 반드시 같아야 함 —
        # 두 판이 다른 엑셀을 내면 안 되므로. '확인사유'는 2026-08-05,
        # '입력방법'은 2026-08-07 추가.
        ['Point', '파일명', '종류', '항목', '방향', '번호', '측정값(um)', 'Target', '편차',
         'Tolerance', 'USL', 'LSL', '스펙이탈', 'X(um)', 'Y(um)', '확인필요', '확인사유',
         '입력방법', '신뢰도']
    ]
    summary_df = pd.DataFrame(core.summarize_matching(all_data, plan))
    stats_rows = core.compute_stats(all_data, plan)
    overlay_df = pd.DataFrame(overlay_summaries)[
        ['Point', '파일명', '상', '하', '좌', '우', 'Overlay_X', 'Overlay_Y', 'Overlay']
    ] if overlay_summaries else pd.DataFrame()

    save_path = os.path.join(run_dir, '측정결과.xlsx')
    with pd.ExcelWriter(save_path, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='측정결과', index=False)
        core.style_result_sheet(writer, df)
        if not summary_df.empty:
            summary_df.to_excel(writer, sheet_name='검증요약', index=False)
        if not overlay_df.empty:
            overlay_df.to_excel(writer, sheet_name='Overlay요약', index=False)
        core.add_cpk_sheet(writer, stats_rows)
        core.add_trend_sheet(writer, df, plan)

    flagged = int((df['확인필요'] == '예').sum())
    out_of_spec = int((df['스펙이탈'] == '예').sum())
    unread = sum(1 for line in log if core.UNREAD_MARK in line)
    mismatch_item = int((summary_df['일치'] == '아니오').sum()) if not summary_df.empty else 0
    # 결과 화면·HTML 리포트는 이 넷을 실행 전체 합계 하나가 아니라 Item별로
    # 나눠서 보여줌(2026-08-12) - 위 flagged/out_of_spec/unread/mismatch_item은
    # 실행이력.csv·완료 안내에 계속 쓰이므로 그대로 둠.
    item_breakdown = compute_item_breakdown(all_data, plan, core.unread_by_file(log))

    # 데모 결과 화면이 "이 사진에서 이 값을 읽었다"를 보여주려면 파일 단위로 묶은
    # 값이 필요하다. df에 이미 다 들어 있어 새로 계산할 것은 없다.
    # ⚠️ 미리 계산해 둔 값을 쓰면 안 된다 — 판독이 깨져도 화면은 멀쩡해 보인다.
    # 데모에서만 저장: 실제 실행의 결과 폴더 구조를 지금 건드릴 이유가 없음.
    if category == '데모':
        def _clean(v):
            # Target을 못 찾은 행은 NaN이다. 그대로 두면 화면에 'nan'이 뜨고
            # json.dump도 표준이 아닌 NaN 리터럴을 쓴다.
            return None if isinstance(v, float) and math.isnan(v) else v

        by_file = {}
        for row in df.to_dict('records'):
            by_file.setdefault(row['파일명'], []).append({
                'Point': _clean(row['Point']), '항목': row['항목'],
                '번호': _clean(row['번호']), '측정값': _clean(row['측정값(um)']),
                'Target': _clean(row['Target']), 'USL': _clean(row['USL']),
                'LSL': _clean(row['LSL']), '스펙이탈': row['스펙이탈'],
                '방향': row['방향'],
            })
        with open(os.path.join(run_dir, PHOTO_READ_FILE), 'w', encoding='utf-8') as f:
            json.dump({'파일': by_file}, f, ensure_ascii=False)

    report_path = os.path.join(run_dir, '측정결과.html')
    core.build_report(df, overlay_df, stats_rows, plan, report_path, item_breakdown=item_breakdown)

    # 데스크탑 실행과 같은 실행이력.csv에 웹 실행도 같이 누적(어느 쪽으로 돌렸든
    # 한곳에서 추세를 볼 수 있어야 하므로). '폴더' 칸에는 이 서버의 임시 업로드
    # 경로가 남음 - 실제 원본 사진 폴더 경로는 웹에서는 알 수 없음.
    core.save_run_log(run_dir, plan, files, log, df, summary_df, out_of_spec, flagged, unread,
                      operator=operator, elapsed_sec=time.time() - started, category=category)

    write_progress(
        run_dir, status='done',
        total=len(df), points=int(df['Point'].nunique()),
        flagged=flagged, out_of_spec=out_of_spec, unread=unread,
        mismatch_item=mismatch_item, item_breakdown=item_breakdown, **meta,
    )

    # 재개용 임시 파일은 이제 필요 없으므로 정리(있으면)
    state_path = os.path.join(run_dir, MANUAL_STATE_FILE)
    if os.path.exists(state_path):
        os.remove(state_path)


def run_processing(run_dir, files, plan, operator='', category=''):
    """실제 OCR/Target매칭/엑셀·HTML 생성을 백그라운드 스레드에서 수행.
       요청(request) 맥락 밖에서 돌아가므로 flash()를 못 쓰고, 대신 진행률
       파일에 상태를 남겨서 /progress 폴링과 /result 페이지가 읽게 함.

       operator는 이 스레드가 request 맥락 밖이라 current_user를 못 읽기 때문에
       호출하는 쪽에서 미리 꺼내 넘겨받는다.

       ⚠️ 못 읽은 사진이 있으면 여기서 처리를 멈추고 스레드가 끝남 - 스레드는
       브라우저의 폼 제출(사람 입력)을 기다릴 수 없기 때문. 이어받는 처리는
       manual_input_submit()이 별개의 요청으로 함(2026-08-07)."""
    meta = dict(_run_meta(plan), operator=operator)
    started = time.time()
    try:
        templates = load_templates()

        def on_progress(done, total):
            write_progress(run_dir, status='processing', done=done, total=total, **meta)

        # 판독 근거를 run_dir에 남김 — 글(OCR근거.json)은 로그처럼 계속 남고,
        # 줄 그림(ocr_evidence/)은 사진과 함께 7일 자동 정리에 딸려 나감
        measured, log, evidence_records = core.read_measured(
            files, templates, plan, on_progress, run_dir=run_dir)

        if pending_items(measured):
            _enter_manual_input_state(run_dir, plan, files, measured, log,
                                      evidence_records, operator, started,
                                      category=category)
            return

        all_data, overlay_summaries, log = core.finish_processing(
            measured, plan, log, evidence_records, run_dir)
        _finalize_and_save(run_dir, plan, files, all_data, overlay_summaries, log,
                           operator, started, category=category)
    except Exception as e:
        # 어디서든 예외가 나면 화면이 그냥 멈춘 것처럼 보이면 안 되므로,
        # 무조건 진행률 파일에 에러로 남기고, 원인을 나중에 코드에서 찾을 수
        # 있게 traceback까지 로그 파일에 남김(사용자가 "오류 부분을 수정하고
        # 프로그램 업데이트"하려면 이게 있어야 함 - 메시지 한 줄로는 부족함).
        message = f'처리 중 오류가 발생했습니다: {e}'
        _write_failure_log(run_dir, plan, files, message, traceback.format_exc().splitlines())
        write_progress(run_dir, status='error', message=message, **meta)


@app.route('/new', methods=['GET', 'POST'])
@login_required
def new_run():
    if request.method == 'GET':
        return render_template('new_run.html')

    try:
        plan = build_plan_from_form(request.form)
    except (ValueError, KeyError):
        flash('입력값을 다시 확인해 주세요 (숫자 칸에 숫자가 아닌 값이 있을 수 있습니다).')
        return redirect(url_for('new_run'))

    uploaded = [f for f in request.files.getlist('photos') if f and f.filename]
    if not uploaded:
        flash('사진을 1장 이상 올려 주세요.')
        return redirect(url_for('new_run'))

    # 실행마다 폴더를 새로 나눔(동시에 여러 명이 써도 서로 안 섞이도록)
    run_id = time.strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6]
    run_dir = os.path.join(UPLOAD_ROOT, run_id)
    os.makedirs(run_dir, exist_ok=True)
    for f in uploaded:
        # webkitdirectory로 폴더째 선택하면 파일명에 상위 폴더 경로가 섞여
        # 들어올 수 있어(예: "Sample/CaptImg....bmp") secure_filename으로
        # 한 번 정리하되, 실제 파일명(마지막 조각)만 남김.
        name = secure_filename(os.path.basename(f.filename))
        f.save(os.path.join(run_dir, name))

    files = []
    for ext in core.IMAGE_EXTENSIONS:
        files += glob.glob(os.path.join(run_dir, f'*{ext}'))
        files += glob.glob(os.path.join(run_dir, f'*{ext.upper()}'))
    files = sorted(set(files), key=core.natural_sort_key)

    if not files:
        flash(f'올린 파일 중 읽을 수 있는 사진이 없습니다 ({" / ".join(core.IMAGE_EXTENSIONS)} 형식만 가능).')
        return redirect(url_for('new_run'))

    write_progress(run_dir, status='processing', done=0, total=len(files),
                   operator=current_user.id, **_run_meta(plan))
    activity_log.record(current_user.id, '측정실행', _client_ip(),
                        f'{run_id} / {plan.process} / 사진 {len(files)}장')
    # current_user는 요청 맥락에서만 읽을 수 있으므로 스레드에 넘기기 전에 꺼내 둠
    thread = threading.Thread(target=run_processing,
                              args=(run_dir, files, plan, current_user.id), daemon=True)
    thread.start()

    # 업로드 진행률을 보여주려고 브라우저가 XHR로 보낸 경우에는 화면 대신 run_id만 돌려줌.
    # 브라우저가 그걸 받아 /processing/<run_id>로 이동하므로 주소창에 주소가 남아
    # 새로고침해도 진행 화면이 유지됨. 자바스크립트가 꺼져 있으면 아래 기존 방식으로 동작.
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'run_id': run_id})
    return render_template('processing.html', run_id=run_id, total=len(files), is_demo=False)


@app.route('/progress/<run_id>')
@login_required
def progress(run_id):
    run_dir = os.path.join(UPLOAD_ROOT, secure_filename(run_id))
    state = read_progress(run_dir)
    if state is None:
        return jsonify({'status': 'unknown'}), 404
    return jsonify(state)


@app.route('/result/<run_id>')
@login_required
def result(run_id):
    run_dir = os.path.join(UPLOAD_ROOT, secure_filename(run_id))
    state = read_progress(run_dir)
    if not state or state.get('status') != 'done':
        # 아직 안 끝났으면(새로고침 등) 처리 중 화면으로 돌려보냄
        return redirect(url_for('processing_page', run_id=run_id))
    return render_template('result.html', run_id=run_id, username=current_user.id, **state)


# ------------------------------------------------------------
#  공개 데모 (로그인 없이 체험)
# ------------------------------------------------------------
def _read_json(path):
    """없거나 깨졌으면 None. 화면이 그 구역을 감추는 근거가 된다."""
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# 소개 화면 예시 사진의 주석 좌표. 저장소에 커밋된 고정 파일이라 프로세스마다
# 한 번만 읽어 캐시한다. 파일이 없으면 None -> 템플릿이 사진 구역을 통째로
# 감춘다(사진 없이 화살표만 뜨는 상태를 만들지 않기 위함).
_example_cache = None


def _demo_examples():
    global _example_cache
    if _example_cache is None:
        _example_cache = _read_json(
            os.path.join(app.static_folder, 'demo', 'annotations.json')) or False
    return _example_cache or None


def _build_demo_plan():
    """데모 사진의 실제 값 기준(scripts/make_demo_images.DEMO_TARGETS)과
       반드시 같아야 함: RDL / Pad CD 100 / Line 10 / Space 20 / Overlay."""
    cd_pattern = CD_PATTERN_BY_PROCESS['RDL']
    cd_target = 100.0
    ls_target_line = 10.0
    ls_target_space = 20.0
    return MeasurementPlan(
        process='RDL', cd_label=CD_LABEL_BY_PROCESS['RDL'],
        cd_items=[CDItem('Pad CD Item 1', 9, cd_target,
                         lookup_tolerance('RDL', cd_pattern, cd_target))],
        ls_items=[LSItem('Line&Space Item 1', 9, ls_target_line, ls_target_space,
                         lookup_tolerance('RDL', 'L/S', ls_target_line),
                         lookup_tolerance('RDL', 'L/S', ls_target_space))],
        overlay_points=9,
        customer='데모', material='데모', layer='데모',
    )


def _is_demo_run_id(run_id):
    # secure_filename으로 한 번 걸러도 그대로면 경로 조작 문자가 없다는 뜻.
    # demo_ 접두사 확인은 로그인 없는 /demo/* 경로가 실제 실행 데이터를
    # 실수로 보여주지 않게 하는 유일한 안전장치라 반드시 같이 확인한다.
    return run_id.startswith('demo_') and secure_filename(run_id) == run_id


@app.route('/about')
def about():
    """케이스 스터디(어떻게 만들었나). 로그인 없이 열리는 경로다.

    내용은 docs/case-study.md 하나가 원본이고, scripts/build_case_study.py 가
    배포 전에 템플릿으로 변환해 둔다 - 설명하는 글이 여러 벌로 갈라지지 않게
    하려는 것. 이 라우트는 고정된 글만 내보내므로 실행 데이터에 닿지 않는다.
    """
    return render_template('case_study.html')


@app.route('/demo')
def demo_intro():
    _ensure_demo_source()
    limited, count = check_demo_limit(_client_ip())
    return render_template('demo.html', limited=limited, count=count,
                           limit=DEMO_DAILY_LIMIT,
                           examples=_demo_examples(), plan=_build_demo_plan())


@app.route('/demo/start', methods=['POST'])
def demo_start():
    ip = _client_ip()
    limited, _ = check_demo_limit(ip)
    if limited:
        flash(f'오늘 데모 실행 횟수({DEMO_DAILY_LIMIT}회)를 모두 사용했습니다. 내일 다시 시도해 주세요.')
        return redirect(url_for('demo_intro'))

    # 카운트를 최대한 일찍 올림(check-then-copy-then-record라 원래
    # 여기부터 record_demo_run까지가 경합 창이었음 - 같은 IP가 짧은
    # 간격으로 여러 요청을 동시에 보내면 전부 같은(증가 전) count를 읽고
    # 통과할 수 있음). 완벽한 동시성 안전(락)까진 필요 없고, 사진 36장
    # 복사 + CPU를 많이 쓰는 OCR 스레드를 시작하기 전에 카운트부터
    # 올려서 그 창을 최대한 좁히는 정도로 충분함(2026-08-18 최종 리뷰).
    record_demo_run(ip)

    source_dir = _ensure_demo_source()
    run_id = 'demo_' + time.strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6]
    run_dir = os.path.join(UPLOAD_ROOT, run_id)
    os.makedirs(run_dir, exist_ok=True)
    for name in os.listdir(source_dir):
        src = os.path.join(source_dir, name)
        if not os.path.isfile(src):
            continue          # preview/ 같은 하위 폴더는 실행 폴더로 안 옮김
        shutil.copy2(src, os.path.join(run_dir, name))

    files = []
    for ext in core.IMAGE_EXTENSIONS:
        files += glob.glob(os.path.join(run_dir, f'*{ext}'))
        files += glob.glob(os.path.join(run_dir, f'*{ext.upper()}'))
    files = sorted(set(files), key=core.natural_sort_key)

    plan = _build_demo_plan()
    write_progress(run_dir, status='processing', done=0, total=len(files),
                   operator='데모방문자', **_run_meta(plan))
    thread = threading.Thread(
        target=run_processing,
        args=(run_dir, files, plan, '데모방문자'),
        kwargs={'category': '데모'}, daemon=True)
    thread.start()
    return redirect(url_for('demo_processing_page', run_id=run_id))


@app.route('/demo/processing/<run_id>')
def demo_processing_page(run_id):
    if not _is_demo_run_id(run_id):
        abort(404)
    run_dir = os.path.join(UPLOAD_ROOT, run_id)
    state = read_progress(run_dir) or {}
    return render_template('processing.html', run_id=run_id,
                           total=state.get('total', 0), is_demo=True)


@app.route('/demo/progress/<run_id>')
def demo_progress(run_id):
    if not _is_demo_run_id(run_id):
        abort(404)
    run_dir = os.path.join(UPLOAD_ROOT, run_id)
    state = read_progress(run_dir)
    if state is None:
        return jsonify({'status': 'unknown'}), 404
    return jsonify(state)


@app.route('/demo/result/<run_id>')
def demo_result(run_id):
    if not _is_demo_run_id(run_id):
        abort(404)
    run_dir = os.path.join(UPLOAD_ROOT, run_id)
    state = read_progress(run_dir)
    if not state or state.get('status') != 'done':
        return redirect(url_for('demo_processing_page', run_id=run_id))
    # 사진 구역에 필요한 두 가지. 하나라도 없으면 템플릿이 구역을 통째로 감춘다
    # (옛 실행 폴더에는 사진별판독.json이 없다 — 값 없는 사진만 뜨면 고장으로 보임).
    photo_reads = _read_json(os.path.join(run_dir, PHOTO_READ_FILE))
    boxes = _read_json(os.path.join(DEMO_SOURCE_DIR, 'preview', 'boxes.json'))
    return render_template('result.html', run_id=run_id, username=None,
                           is_demo=True, photo_reads=photo_reads, boxes=boxes,
                           **state)


@app.route('/demo/photo/<filename>')
def demo_photo(filename):
    """데모 사진 미리보기(축소 JPEG). 로그인 없이 열리는 경로다.

    run_id를 아예 받지 않는 것이 방어의 핵심 — 미리보기는 실행과 무관한 고정
    자산이라, 이 라우트에서 실행 데이터(업로드 폴더)에 닿을 경로 자체가 없다.
    """
    if secure_filename(filename) != filename or not filename.endswith('.jpg'):
        abort(404)
    preview_dir = os.path.join(DEMO_SOURCE_DIR, 'preview')
    if not os.path.isfile(os.path.join(preview_dir, filename)):
        abort(404)
    return send_from_directory(preview_dir, filename)


@app.route('/processing/<run_id>')
@login_required
def processing_page(run_id):
    run_dir = os.path.join(UPLOAD_ROOT, secure_filename(run_id))
    state = read_progress(run_dir) or {}
    return render_template('processing.html', run_id=run_id,
                           total=state.get('total', 0), is_demo=False)


@app.route('/manual_input/<run_id>')
@login_required
def manual_input_form(run_id):
    run_dir = os.path.join(UPLOAD_ROOT, secure_filename(run_id))
    state = read_progress(run_dir)
    if not state or state.get('status') != 'manual_input':
        # 이미 다른 사람이 입력을 끝냈거나, 새로고침 타이밍 문제 - 진행 화면이
        # 알아서 최신 상태로 다시 보내줌
        return redirect(url_for('processing_page', run_id=run_id))
    return render_template('manual_input.html', run_id=run_id,
                           pending=state.get('pending', []), username=current_user.id)


@app.route('/manual_input/<run_id>/crop/<int:idx>/<filename>')
@login_required
def manual_input_crop(run_id, idx, filename):
    run_dir = os.path.join(UPLOAD_ROOT, secure_filename(run_id))
    crop_dir = _manual_crop_dir(run_dir, idx)
    safe_name = secure_filename(filename)
    if not os.path.isfile(os.path.join(crop_dir, safe_name)):
        abort(404)
    return send_from_directory(crop_dir, safe_name)


@app.route('/manual_input/<run_id>/photo/<filename>')
@login_required
def manual_input_photo(run_id, filename):
    """'사진 전체 열기' 링크용 - 원본 업로드 사진을 그대로 보여줌."""
    run_dir = os.path.join(UPLOAD_ROOT, secure_filename(run_id))
    safe_name = secure_filename(filename)
    if (not safe_name.lower().endswith(core.IMAGE_EXTENSIONS)
            or not os.path.isfile(os.path.join(run_dir, safe_name))):
        abort(404)
    return send_from_directory(run_dir, safe_name)


@app.route('/manual_input/<run_id>', methods=['POST'])
@login_required
def manual_input_submit(run_id):
    """폼 제출을 받아 나머지 처리(Target 매칭부터 끝까지)를 이어서 함.

    run_processing()이 사람 입력을 기다리며 멈춰둔 지점을 여기서 재개함.
    저장해둔 .manual_state.json에서 measured/plan 등을 그대로 복원해서 쓰므로,
    OCR을 다시 돌리지 않고 이 요청 안에서 빠르게 끝남."""
    run_dir = os.path.join(UPLOAD_ROOT, secure_filename(run_id))
    state = read_progress(run_dir)
    if not state or state.get('status') != 'manual_input':
        abort(404)

    state_path = os.path.join(run_dir, MANUAL_STATE_FILE)
    with open(state_path, encoding='utf-8') as f:
        saved = json.load(f)
    plan = plan_from_dict(saved['plan'])
    files = saved['files']
    measured = [tuple(m) for m in saved['measured']]
    log = saved['log']
    evidence_records = saved['evidence_records']
    operator = saved['operator']
    started = saved['started']
    # 옛날에 저장된 .manual_state.json(이 필드가 없던 버전)을 읽을 수도
    # 있으니 .get으로 기본값을 둠 - operator는 처음부터 있었지만 category는
    # 이번에 추가된 필드라서.
    category = saved.get('category', '')

    # 폼 필드 이름 규칙: val_<idx>_<j> / off_<idx>_<j> / dir_<idx>_<j>(Overlay만)
    # idx는 pending 안에서 이 사진의 순번, j는 그 사진 안에서 못 읽은 줄의 순번.
    # 이미 읽힌(locked) 행의 방향 확인은 dir_locked_<idx>_<그 행의 순번>.
    manual_by_path = {}
    for item in state.get('pending', []):
        idx = item['idx']
        found = next((m for m in measured if os.path.basename(m[0]) == item['name']), None)
        if found is None:
            continue
        path, name, category, kind, rows, line_count = found
        is_overlay = category == 'overlay'
        forced = item.get('forced_directions')

        if is_overlay:
            for j, r in enumerate(rows):
                d = request.form.get(f'dir_locked_{idx}_{j}', '')
                if d:
                    r['수동방향'] = d

        new_rows = []
        for j in range(item['missing']):
            val = request.form.get(f'val_{idx}_{j}', '').strip()
            off = request.form.get(f'off_{idx}_{j}', '').strip()
            # 남은 방향이 소거법으로 확정된 경우(forced) 화면에 드롭다운
            # 자체가 없으므로 폼에서 안 오고, 여기서 직접 채움
            # (2026-08-10, overlay_analysis.infer_forced_directions).
            if is_overlay and forced is not None:
                direction = forced[j]
            else:
                direction = request.form.get(f'dir_{idx}_{j}', '') if is_overlay else ''
            if not val and not off:
                continue  # 비워두면 그 줄은 포기한 것으로 봄(데스크탑과 같은 원칙)
            if not val:
                flash(f'{item["name"]}: 값 칸이 비어 있습니다.')
                return redirect(url_for('manual_input_form', run_id=run_id))
            try:
                new_rows.append(build_manual_row(
                    j, float(val), float(off) if off else 0.0, direction))
            except ValueError:
                flash(f'{item["name"]}: 숫자만 입력해 주세요.')
                return redirect(url_for('manual_input_form', run_id=run_id))
        if new_rows:
            manual_by_path[path] = new_rows

    measured, log = core.merge_manual_entries(measured, manual_by_path, plan, log)
    all_data, overlay_summaries, log = core.finish_processing(
        measured, plan, log, evidence_records, run_dir)

    activity_log.record(current_user.id, '수동입력', _client_ip(), run_id)
    _finalize_and_save(run_dir, plan, files, all_data, overlay_summaries, log,
                       operator, started, category=category)
    return redirect(url_for('result', run_id=run_id))


@app.route('/runs')
@login_required
def runs():
    """지금까지 실행한 목록(성공/처리중/실패 전부) - 오류 파악하고 프로그램을
       고치려면 서버에 직접 안 들어가도 여기서 확인할 수 있어야 하므로 만듦.
       run_id에 시각이 맨 앞에 붙어있어서, 이름 역순 정렬이 곧 최신순임."""
    entries = []
    if os.path.isdir(UPLOAD_ROOT):
        for run_id in sorted(os.listdir(UPLOAD_ROOT), reverse=True):
            # 데모 실행(demo_ 접두사)은 진짜 고객 작업 기록이 아니라 이 목록에
            # 섞이면 안 됨 - 접두사가 다르면 "이름 역순 정렬 = 최신순" 전제도
            # 깨짐(demo_ 실행이 실제 최신순 위치가 아닌 곳에 끼어들어 보임).
            if run_id.startswith('demo_'):
                continue
            run_dir = os.path.join(UPLOAD_ROOT, run_id)
            if not os.path.isdir(run_dir):
                continue
            state = read_progress(run_dir) or {'status': 'unknown'}
            has_log = bool(glob.glob(os.path.join(run_dir, '측정로그_*.txt')))
            # run_id 맨 앞 "YYYYMMDD_HHMMSS"를 사람이 읽기 쉬운 형태로 변환
            try:
                when = time.strftime(
                    '%Y-%m-%d %H:%M:%S',
                    time.strptime(run_id[:15], '%Y%m%d_%H%M%S'))
            except ValueError:
                when = run_id
            entries.append({'run_id': run_id, 'has_log': has_log, 'when': when, **state})
    return render_template('runs.html', entries=entries, username=current_user.id)


@app.route('/log/<run_id>')
@login_required
def view_log(run_id):
    run_dir = os.path.join(UPLOAD_ROOT, secure_filename(run_id))
    matches = glob.glob(os.path.join(run_dir, '측정로그_*.txt'))
    if not matches:
        abort(404)
    log_path = matches[0]  # 실행 하나당 로그 파일은 항상 하나뿐
    with open(log_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return render_template('log_view.html', run_id=run_id, content=content,
                            filename=os.path.basename(log_path))


#  다운로드 가능한 파일명은 이 두 가지뿐(우리 코드가 만든 결과 파일).
DOWNLOADABLE_FILES = {'측정결과.xlsx', '측정결과.html'}


@app.route('/download/<run_id>/<filename>')
@login_required
def download(run_id, filename):
    # run_id는 우리가 만든 값(타임스탬프+영숫자)이라 secure_filename으로 걸러도
    # 안전하게 그대로 남음. 반면 filename은 항상 한글("측정결과.xlsx")인데,
    # secure_filename은 비-ASCII 글자를 전부 지워버려서("측정결과.xlsx" ->
    # "xlsx") 오히려 파일을 못 찾게 만듦 - 그래서 filename은 정해진 두 개
    # 이름과 정확히 일치하는지만 검사(다른 값이면 경로 조작 시도로 보고 차단).
    safe_run_id = secure_filename(run_id)
    if filename not in DOWNLOADABLE_FILES:
        abort(404)
    run_dir = os.path.join(UPLOAD_ROOT, safe_run_id)
    if not os.path.isfile(os.path.join(run_dir, filename)):
        abort(404)
    as_attachment = filename.endswith('.xlsx')
    activity_log.record(current_user.id, '결과다운로드', _client_ip(), f'{run_id} / {filename}')
    return send_from_directory(run_dir, filename, as_attachment=as_attachment)


@app.route('/demo/download/<run_id>/<filename>')
def demo_download(run_id, filename):
    """download()의 로그인 없는 버전 - 데모의 핵심인 엑셀/HTML 리포트를
       익명 방문자가 받을 수 있어야 하는데 download()는 @login_required라
       로그인 화면으로 튕겨냈음(2026-08-18 최종 리뷰에서 발견). run_id를
       _is_demo_run_id로 한 번 더 검증하는 게 핵심 - 로그인 없는 /demo/*
       경로가 실수로 실제(비-데모) 실행 데이터를 내려주지 않게 막는
       유일한 안전장치라서 반드시 필요함(demo_result 등과 같은 패턴)."""
    if not _is_demo_run_id(run_id):
        abort(404)
    if filename not in DOWNLOADABLE_FILES:
        abort(404)
    run_dir = os.path.join(UPLOAD_ROOT, run_id)
    if not os.path.isfile(os.path.join(run_dir, filename)):
        abort(404)
    as_attachment = filename.endswith('.xlsx')
    # 익명 요청이라 current_user가 없음 - activity_log.record(current_user.id, ...)를
    # 쓰면 그대로 크래시나므로 호출하지 않음(데모 다운로드는 관리자가 굳이
    # 추적할 필요 없는 이벤트로 판단).
    return send_from_directory(run_dir, filename, as_attachment=as_attachment)


@app.route('/delete_photos/<run_id>', methods=['POST'])
@login_required
def delete_photos(run_id):
    """원본 사진만 지우고 결과(엑셀/HTML/로그)는 남김. 서버가 외부에 있을 때
       민감한 원본 이미지를 계속 쌓아두지 않으려는 목적. "확인필요"로 표시된
       값은 사진을 직접 봐야 검증할 수 있으니, 자동으로 지우지 않고 사용자가
       엑셀을 확인한 뒤 이 버튼을 눌러야 지워지게 함."""
    run_dir = os.path.join(UPLOAD_ROOT, secure_filename(run_id))
    state = read_progress(run_dir)
    if not state or state.get('status') != 'done':
        abort(404)

    deleted = 0
    for name in os.listdir(run_dir):
        path = os.path.join(run_dir, name)
        if not os.path.isfile(path):
            continue
        # 결과 파일(엑셀/HTML)과 진행 상태, 상세 로그(텍스트라 사진처럼 민감하지
        # 않음)는 남기고, 그 외(원본 사진)만 지움
        if name in DOWNLOADABLE_FILES or name == '.progress.json' or name.startswith('측정로그_'):
            continue
        os.remove(path)
        deleted += 1

    state['photos_deleted'] = True
    write_progress(run_dir, **state)
    activity_log.record(current_user.id, '사진삭제', _client_ip(), f'{run_id} / {deleted}장')
    flash(f'원본 사진 {deleted}장을 삭제했습니다.')
    return redirect(url_for('result', run_id=run_id))


if __name__ == '__main__':
    # host='0.0.0.0'으로 열어야 같은 사내망의 다른 컴퓨터에서 접속 가능함
    # (기본값 127.0.0.1은 이 컴퓨터 자기 자신에서만 열림).
    app.run(host='0.0.0.0', port=5000, debug=True)
