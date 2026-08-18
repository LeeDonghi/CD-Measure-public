# -*- coding: utf-8 -*-
# ============================================================
#  사용자 계정 저장/확인
# ------------------------------------------------------------
#  users.json에 "아이디: 비밀번호 해시" 형태로 저장함. 비밀번호를 그대로
#  저장하면 이 파일이 유출됐을 때 바로 뚫리므로, 반드시 해시(되돌릴 수
#  없게 섞은 값)로만 저장함 (werkzeug.security 표준 방식).
#  users.json은 .gitignore에 들어있어 git에는 절대 올라가지 않음 —
#  서버에만 따로 두고 관리할 것(배포된 서버에서는 /data 볼륨 안에 있음).
# ============================================================
import json
import os
from werkzeug.security import generate_password_hash, check_password_hash

# CD_MEASURE_DATA_DIR이 있으면 그 폴더에 둠(Docker 배포용 — 컨테이너 안에 두면
# 이미지를 새로 만들 때 계정이 전부 사라짐). 없으면 이 파일 옆에 둠.
_DATA_DIR = os.environ.get('CD_MEASURE_DATA_DIR') or os.path.dirname(os.path.abspath(__file__))
USERS_PATH = os.path.join(_DATA_DIR, 'users.json')


def _load():
    if not os.path.exists(USERS_PATH):
        return {}
    with open(USERS_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save(users):
    with open(USERS_PATH, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def _record(value):
    """저장된 값 하나를 {'password_hash':..., 'is_admin':...} 형태로 통일해서 돌려줌.

    2026-08-04에 관리자 구분을 넣으면서 저장 형식이 바뀜:
        옛 형식: "아이디": "해시문자열"
        새 형식: "아이디": {"password_hash": "해시문자열", "is_admin": false}
    이미 만들어 둔 계정을 못 쓰게 되면 안 되므로, 옛 형식(문자열)도 그대로 읽어
    관리자가 아닌 일반 계정으로 취급한다. 비밀번호를 바꾸거나 관리자로 지정할 때
    자연스럽게 새 형식으로 바뀐다.
    """
    if isinstance(value, str):
        return {'password_hash': value, 'is_admin': False}
    return value or {}


# 사내 도구라 복잡한 조합 규칙 대신 길이만 봄. 너무 까다롭게 하면 메모지에
# 적어두는 부작용이 더 커서, 최소 길이만 강제한다.
MIN_PASSWORD_LENGTH = 8


def check_password_rule(password):
    """(통과여부, 안내문)."""
    if len(password or '') < MIN_PASSWORD_LENGTH:
        return False, f'비밀번호는 {MIN_PASSWORD_LENGTH}자 이상이어야 해요.'
    return True, ''


def add_user(username, password, is_admin=None, must_change=False):
    """새 계정을 추가(또는 비밀번호 변경).

    is_admin을 안 주면 기존 관리자 여부를 그대로 둠 — 비밀번호만 바꾸려다
    실수로 관리자 권한이 풀리는 일을 막기 위함.

    must_change=True면 그 계정은 다음 로그인 때 비밀번호를 반드시 바꿔야 함.
    관리자가 임시 비밀번호로 팀원 계정을 만들어 줄 때 쓴다 — 관리자가 정한
    비밀번호를 본인이 계속 쓰는 상태를 막기 위함.
    """
    users = _load()
    old = _record(users.get(username))
    users[username] = {
        'password_hash': generate_password_hash(password),
        'is_admin': old.get('is_admin', False) if is_admin is None else bool(is_admin),
        'must_change': bool(must_change),
    }
    _save(users)


def change_password(username, old_password, new_password):
    """본인이 비밀번호를 바꿈. 현재 비밀번호가 맞아야 하고 성공하면 must_change가 풀림.

    돌려주는 값: (성공여부, 안내문). 실패 이유를 화면에 그대로 보여주려고
    문구까지 여기서 정한다.
    """
    if not verify(username, old_password):
        return False, '현재 비밀번호가 맞지 않아요.'
    ok, msg = check_password_rule(new_password)
    if not ok:
        return False, msg
    if verify(username, new_password):
        return False, '지금 쓰는 비밀번호와 같아요. 다른 걸로 바꿔주세요.'

    users = _load()
    rec = _record(users.get(username))
    rec['password_hash'] = generate_password_hash(new_password)
    rec['must_change'] = False
    users[username] = rec
    _save(users)
    return True, '비밀번호를 바꿨어요.'


def must_change_password(username):
    """다음 로그인 때 비밀번호를 바꿔야 하는 계정이면 True."""
    return bool(_record(_load().get(username)).get('must_change'))


def remove_user(username):
    users = _load()
    if username in users:
        del users[username]
        _save(users)
        return True
    return False


def verify(username, password):
    """아이디+비밀번호가 맞으면 True."""
    stored_hash = _record(_load().get(username)).get('password_hash')
    if not stored_hash:
        return False
    return check_password_hash(stored_hash, password)


def is_admin(username):
    """관리자면 True. 접속 이력 보기처럼 관리자만 할 일에 씀."""
    return bool(_record(_load().get(username)).get('is_admin'))


def set_admin(username, flag=True):
    """관리자 지정/해제. 계정이 없으면 False."""
    users = _load()
    if username not in users:
        return False
    rec = _record(users[username])
    rec['is_admin'] = bool(flag)
    users[username] = rec
    _save(users)
    return True


def list_users():
    return list(_load().keys())


def list_users_detail():
    """[(아이디, 관리자여부), ...] — 계정 목록 표시에 씀."""
    return [(name, bool(_record(v).get('is_admin'))) for name, v in _load().items()]
