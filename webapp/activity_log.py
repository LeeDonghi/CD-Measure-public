# -*- coding: utf-8 -*-
# ============================================================
#  접속·활동 이력 기록
# ------------------------------------------------------------
#  "누가 언제 접속해서 무엇을 했는지"를 남김. 기존 login_attempts.json은
#  **실패한 로그인만** 담고 그것도 잠금(brute force 방어) 판단용이라,
#  성공한 로그인이나 다운로드 같은 정상 활동은 어디에도 안 남았음.
#
#  실행 결과 통계는 실행이력.csv가 따로 담당함. 여기는 "사람의 행동"만 담는다.
#
#  보관 기간 90일 — 사용자가 정한 값(2026-08-04). IP와 개인별 활동이 무한정
#  쌓이는 걸 막기 위함이며, 기록할 때마다 오래된 줄을 함께 지운다.
# ============================================================
import csv
import datetime
import os
import threading

_DATA_DIR = os.environ.get('CD_MEASURE_DATA_DIR') or os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(_DATA_DIR, '접속이력.csv')
HEADERS = ['시각', '아이디', '동작', 'IP', '비고']
RETENTION_DAYS = 90

# 여러 워커(gunicorn -w 4)가 동시에 같은 파일에 쓰면 줄이 섞일 수 있어 잠금을 검.
# 프로세스가 다르면 이 잠금만으론 부족하지만, 한 줄 append는 짧아 실제 충돌
# 가능성이 매우 낮고, 기록이 하나 빠지더라도 서비스가 멈추면 안 되는 성격이라
# 파일 잠금(fcntl)까지는 쓰지 않음.
_lock = threading.Lock()


def record(username, action, ip='', note=''):
    """활동 한 줄을 남김. 기록 실패가 서비스를 멈추면 안 되므로 예외를 삼킨다."""
    try:
        with _lock:
            _prune()
            is_new = not os.path.exists(LOG_PATH)
            # utf-8-sig: 엑셀에서 바로 열어도 한글이 안 깨지게 함(실행이력.csv와 동일)
            with open(LOG_PATH, 'a', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f)
                if is_new:
                    w.writerow(HEADERS)
                w.writerow([
                    datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    username or '-', action, ip or '-', note,
                ])
    except Exception:
        pass


def _prune():
    """보관 기간이 지난 줄을 지움. 줄 수가 적어 통째로 다시 쓰는 방식으로 충분함."""
    if not os.path.exists(LOG_PATH):
        return
    cutoff = datetime.datetime.now() - datetime.timedelta(days=RETENTION_DAYS)
    rows = read_all()
    keep = []
    for r in rows:
        try:
            if datetime.datetime.strptime(r['시각'], '%Y-%m-%d %H:%M:%S') >= cutoff:
                keep.append(r)
        except (ValueError, KeyError):
            keep.append(r)      # 시각을 못 읽는 줄은 함부로 지우지 않음
    if len(keep) == len(rows):
        return
    with open(LOG_PATH, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=HEADERS)
        w.writeheader()
        w.writerows(keep)


def read_all():
    """[{'시각':..., '아이디':..., ...}, ...] 오래된 것부터."""
    if not os.path.exists(LOG_PATH):
        return []
    try:
        with open(LOG_PATH, 'r', newline='', encoding='utf-8-sig') as f:
            return [r for r in csv.DictReader(f) if r.get('시각')]
    except Exception:
        return []


def read_recent(limit=300):
    """최근 것부터 limit개."""
    return list(reversed(read_all()))[:limit]
