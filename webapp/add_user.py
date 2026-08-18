# -*- coding: utf-8 -*-
# ============================================================
#  계정 추가/삭제용 명령줄 도구
#  (사용자별 계정을 웹 화면 없이 서버에서 직접 관리하기 위함 — 회원가입
#   화면을 따로 안 만든 이유는, 아무나 계정을 만들 수 있게 하면 안 되고
#   접근할 사람을 관리자가 직접 통제해야 하기 때문)
# ------------------------------------------------------------
#  사용법 (webapp 폴더 안에서):
#    python add_user.py add 아이디        → 비밀번호를 물어보고 계정 추가/변경
#    python add_user.py remove 아이디     → 계정 삭제
#    python add_user.py list             → 등록된 아이디 목록 보기(관리자 표시 포함)
#    python add_user.py admin 아이디      → 관리자로 지정 (접속 이력 열람 권한)
#    python add_user.py admin 아이디 off  → 관리자 해제
#    python add_user.py invite 김아무 이아무 ...
#        → 팀원 계정을 한 번에 만들고 임시 비밀번호를 화면에 뿌림.
#          받은 사람은 첫 로그인 때 비밀번호를 반드시 바꿔야 함.
# ============================================================
import secrets
import sys
import getpass
import users


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]

    if cmd == 'list':
        rows = users.list_users_detail()
        if not rows:
            print('등록된 계정 0개: (없음)')
        else:
            print(f'등록된 계정 {len(rows)}개:')
            for name, admin in rows:
                print(f'  {name}{"  [관리자]" if admin else ""}')

    elif cmd == 'invite':
        # 팀원 계정을 한 번에 여러 개 만들 때 씀. 임시 비밀번호는 무작위로 만들고
        # 받은 사람이 첫 로그인에서 반드시 바꾸게 함(must_change=True) —
        # 관리자가 정해 준 비밀번호를 계속 쓰는 상태를 남기지 않으려는 것.
        if len(sys.argv) < 3:
            print('사용법: python add_user.py invite 아이디1 아이디2 ...')
            return
        existing = set(users.list_users())
        print('아래 임시 비밀번호를 각자에게 전달하세요. 첫 로그인 때 반드시 바꿔야 합니다.')
        print('(이 화면을 닫으면 다시 볼 수 없으니 지금 적어두세요)\n')
        for name in sys.argv[2:]:
            if name in existing:
                print(f'  {name:<16} 이미 있는 계정이라 건너뜀')
                continue
            # secrets: 예측 가능한 random 대신 암호학적으로 안전한 난수를 씀
            temp = secrets.token_urlsafe(9)
            users.add_user(name, temp, must_change=True)
            print(f'  {name:<16} {temp}')

    elif cmd == 'admin':
        # 관리자는 접속 이력 보기처럼 "누가 뭘 했는지" 확인하는 권한을 가짐.
        # 비밀번호 변경과 분리해 둔 이유: 비밀번호만 바꾸려다 실수로 권한이
        # 바뀌는 일을 막기 위함(users.add_user의 is_admin 기본값도 같은 취지).
        if len(sys.argv) < 3:
            print('사용법: python add_user.py admin 아이디 [off]')
            return
        username = sys.argv[2]
        make_admin = not (len(sys.argv) > 3 and sys.argv[3].lower() in ('off', 'false', 'no'))
        if users.set_admin(username, make_admin):
            print(f'"{username}" 계정을 {"관리자로 지정" if make_admin else "일반 계정으로 변경"}했어요.')
        else:
            print(f'"{username}" 계정이 없어요.')

    elif cmd == 'add':
        if len(sys.argv) < 3:
            print('아이디를 입력하세요: python add_user.py add 아이디')
            return
        username = sys.argv[2]
        password = getpass.getpass('비밀번호 입력: ')
        password2 = getpass.getpass('비밀번호 확인: ')
        if password != password2:
            print('비밀번호가 서로 달라요. 다시 시도해주세요.')
            return
        users.add_user(username, password)
        print(f'"{username}" 계정을 추가(또는 비밀번호 변경)했어요.')

    elif cmd == 'remove':
        if len(sys.argv) < 3:
            print('아이디를 입력하세요: python add_user.py remove 아이디')
            return
        username = sys.argv[2]
        if users.remove_user(username):
            print(f'"{username}" 계정을 삭제했어요.')
        else:
            print(f'"{username}" 계정이 없어요.')

    else:
        print(__doc__)


if __name__ == '__main__':
    main()
