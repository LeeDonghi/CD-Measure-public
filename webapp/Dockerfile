# CD Measure(MetroPilot) 웹 버전 컨테이너.
# 인터넷에 공개된 서버에서 돎 — 이 컨테이너의 5000번은 호스트에 직접 열지 말고
# 반드시 Caddy(HTTPS 처리)를 거치게 할 것(docker-compose.yml이 그렇게 돼 있음).
#
# 빌드는 반드시 "프로젝트 최상위 폴더"에서 실행해야 함(webapp 폴더 안이 아님) -
# 웹 버전이 기존 데스크탑 코드(ocr_core.py 등)를 그대로 가져다 쓰기 때문.
# 실제 명령과 계정 만드는 방법은 webapp/배포방법.md 참고.
#
# -v로 연결하는 /data 폴더에 계정(users.json), 실행이력.csv, 업로드/결과 파일이
# 쌓임. 이걸 빼먹으면 컨테이너를 다시 만들 때(이미지 업데이트 등) 그 데이터가
# 전부 사라지므로 반드시 붙일 것.
FROM python:3.12-slim

# 기존 데스크탑 코드(CD측정값_엑셀변환.py, plan_gui.py)가 파일 맨 위에서
# tkinter를 불러옴(실제 창은 안 띄우고 상수 하나만 쓰지만, import 자체가
# 안 되면 웹 서버도 못 뜸). python3-tk는 pip가 아니라 시스템 패키지라
# apt로 따로 설치해야 함.
# tzdata: docker-compose.yml에서 준 TZ=Asia/Seoul이 실제로 먹히려면 시간대 자료가
# 이미지 안에 있어야 함. 없으면 TZ를 줘도 컨테이너가 UTC로 남아서 실행이력.csv의
# 시각이 9시간 어긋남.
RUN apt-get update && apt-get install -y --no-install-recommends python3-tk tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY webapp/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 웹 서버 코드
COPY webapp/ ./webapp/
# 재사용하는 기존 데스크탑 프로그램 코드 (사진 폴더는 용량이 커서 제외)
COPY *.py ./
COPY char_templates.pkl ./
# scripts/*.py(데모용 가짜 사진 생성기 make_demo_images.py 등) - 위 "COPY *.py ./"는
# 글롭이 "/"를 못 건너뛰어서 하위 폴더까지는 안 긁어옴. 이걸 빠뜨리면 이미지 안에
# scripts 폴더 자체가 없어서 app.py의 "from scripts.make_demo_images import ..."가
# ModuleNotFoundError를 내고 /demo가 통째로 500이 됨(2026-08-18 실제로 겪음).
COPY scripts/ ./scripts/

WORKDIR /app/webapp

# 오래 보관해야 하는 데이터(계정, 실행이력, 업로드/결과 파일)는 전부 /data 밑에
# 모아둠. 컨테이너 안쪽 파일은 컨테이너를 지우면 같이 사라지므로, 실행할 때
# `-v <서버폴더>:/data`로 바깥 폴더를 연결해서 그쪽에 쌓이게 하는 것이 전제.
# (users.json을 이미지에 구워 넣지 않는 이유도 같음 — 이미지를 받은 사람이
#  비밀번호 해시를 꺼내볼 수 있게 되면 안 됨)
ENV CD_MEASURE_DATA_DIR=/data
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 5000

# 개발용 서버(app.run)는 실제 운영에 부적합(느리고 동시 요청 처리 약함)해서
# 운영에는 gunicorn(WSGI 서버)을 씀. -w 4: 요청을 동시에 처리할 프로세스 4개
# (사내 5명 정도가 같이 쓰는 걸 기준으로 잡음 - 서버 코어 수에 여유가 있으면
# 늘려도 됨. 처리 자체는 백그라운드 스레드로 도니 워커 수가 "동시에 몇 명이
# OCR 처리 중일 수 있냐"를 직접 정하진 않고, 그보다는 "동시에 몇 명이 페이지를
# 열거나 진행률을 확인할 수 있냐"에 더 가까움).
#
# --timeout 900(15분)은 지금 구조에선 예전만큼 절실하진 않음(처리를 백그라운드
# 스레드로 넘기고 요청 자체는 바로 끝내므로) - 그래도 만약을 대비해 넉넉하게 둠.
CMD ["gunicorn", "-w", "4", "--timeout", "900", "-b", "0.0.0.0:5000", "app:app"]
