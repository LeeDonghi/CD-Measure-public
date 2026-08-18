# CD Measure — Claude 작업 규칙

> 사용자는 **코딩 초보인 반도체 photo 엔지니어**. 설명은 쉽게, 단계별로.
> 깊은 배경/과제 히스토리는 `프로젝트_설계문서.md`, 다른 컴퓨터 이어받기는
> `집에서_이어서_작업하기.md` 참고 (이 파일은 "매 세션 지켜야 할 규칙"만 담음).

## 무조건 지킬 것

1. **응답마다 알림.** `.claude/settings.json`의 Stop 훅이 자동으로
   `scripts/notify-toast.ps1`을 실행함. 훅이 안 뜨는 게 확인되면(새로 생긴
   설정이라 감시가 늦게 붙는 경우 등) 수동으로도 호출해서 절대 빠뜨리지 않기.
2. **코드 바꾸면 커밋+푸시까지.** 사용자가 "커밋해줘" 안 해도 변경할 때마다
   바로 진행. 단, `git add -A`/`.` 금지 — 실제로 건드린 파일만 지정.
3. **GUI를 직접 클릭할 수 없음.** `plan_gui.py`는 tkinter 창이라 마우스 클릭이
   안 됨. 검증은 `plan_gui.PlanApp`의 진짜 콜백(`_go_step1`, `_build_step2`,
   `ItemListSection._build_rows`, `_finish`)을 스크립트로 직접 호출하고,
   `filedialog.askdirectory`/`messagebox.*`만 monkeypatch해서 실제 `main()`을
   끝까지 돌리는 방식. 세부 예시는 이 대화(또는 git log 커밋 메시지) 참고.
   `manual_entry.py`(못 읽은 값 수동 입력 창)도 같은 문제라 같은 방식 —
   `ManualEntryDialog`를 실제로 생성해서(`root=tk.Tk(); root.withdraw()`)
   위젯에 값을 직접 넣고 진짜 콜백(`_save_and_next`)을 호출해 `dlg.result`를
   확인하는 식으로 검증함(2026-08-07). ⚠️ 겪은 함정 두 가지:
   - `timeout N python ...`으로 감싸면 Windows에서 자식 tk 프로세스 정리가
     안 돼 그냥 걸어놓은 것처럼 보임(실제로 겪음) — `timeout` 없이 그냥
     실행하고 tool 자체의 timeout 파라미터를 쓸 것.
   - **`measured`를 검증 스크립트에서 따로 만들어 쓰면 안 됨.** `manual_input_cb`
     는 `process_folder`가 "그 순간 자신이 읽은" measured를 그대로 넘겨줌 —
     콜백이 대화상자를 만들 때도 그 리스트를 그대로 써야 함(`ask_manual_values`
     처럼). 검증 스크립트가 사진을 따로 한 번 더 읽어서 별개의 row 객체로
     대화상자를 띄우면, 이미 읽힌 행에 확인받은 방향(`수동방향`)을 남겨도
     그건 딴 객체라 실제 `process_folder` 호출에 안 들어가서 Overlay 지표가
     0건으로 나옴(2026-08-07 실제로 겪음 — 원인 찾는 데 시간 걸림). 콜백은
     반드시 `process_folder(files, templates, plan, manual_input_cb=cb)`
     **한 번의 호출** 안에서, `cb(measured)`로 넘어온 그 리스트로 대화상자를
     만들 것.
   - `Toplevel`을 닫아 끝내는 창은 `root.wait_window(dlg)`로 기다릴 것 —
     `root.mainloop()`을 쓰면 `dlg.destroy()`만으로는 안 끝나고 빈 `root`가
     계속 떠서 결과를 못 받고 멈춘 것처럼 보임(2026-08-07 실제로 겪음,
     `ask_manual_values`는 처음부터 `wait_window`라 이 문제가 없었음).
4. **회귀 검증은 `samples/Sample` 폴더 기준값으로.** 뭘 고치든 최종 확인은 Sample
   폴더(77장)로 다시 돌려서 Cpk요약이 그대로인지 체크:
   `5.5 Space Avg=5.3923 / 9.5 Line Avg=9.4154 / 14.5 Pad CD Avg=14.9538`,
   측정결과 시트 92행. 하나라도 달라지면 의도한 변경인지 반드시 확인.
5. **작업 환경/자료는 항상 두 컴퓨터에서 동일하게 쓸 수 있도록 한다.**
   프로젝트 폴더 안의 것(코드·문서·샘플)은 커밋+푸시로 충분. 컴퓨터 전역
   설치(Node.js, 플러그인, 앱 등 프로젝트 밖 설정)는 git으로 자동 동기화가
   안 되니 `집에서_이어서_작업하기.md`에 설치법을 반드시 적어서 다른
   컴퓨터에서 재현 가능하게 한다. **단, API 키·비밀번호 같은 비밀값은
   절대 커밋하지 않는다** (문서에는 "발급받아서 넣으세요" 안내만).
6. **테스트/실험 파일은 스크래치패드에.** 프로젝트 폴더에 `test_*.py`,
   `exp_*.py` 같은 걸 남기지 않기.
7. **큰 걸 한 번에 만들지 말고, 작게 보여주고 확인받으며 진행.**
8. **위험하거나 되돌리기 어려운 작업(설치 프로그램 실행, 전역 설정 변경,
   git force-push 등)은 먼저 확인받고 진행.** 특히 스타 수가 비정상적인
   저장소처럼 신뢰도가 의심되면 설치 전 코드 내용부터 검토.
9. **초보자가 이해하기 어려운 부분엔 반드시 주석을 남긴다** — 왜 이 값을
   골랐는지, 왜 이 방식을 썼는지, 숨겨진 제약/과거 버그 이력 등. 반대로
   **코드만 봐도 알 수 있는 내용(변수명으로 뻔한 것)은 주석을 안 단다** —
   노이즈가 되고 나중에 코드 바뀌면 거짓말하는 주석이 됨.

## 도메인 지식 요약 (자세한 근거는 설계문서 참고)

- 계측기 사진 한 Point = 3장(overlay/CD/L-S), 시간순 정렬 후 3장씩 묶음.
- OCR은 Tesseract가 아니라 **템플릿 매칭**(`ocr_core.py`) — 글자 폰트·색이
  고정이라 가능한 방식. `char_templates.pkl` 손보려면 `build_templates.py`.
- 종류 판별은 "읽은 값 개수"가 아니라 **박스 폭으로 추정한 실제 줄 개수**
  (겹쳐 찍힌 라벨 대응, `count_lines_in_boxes`).
- Target 매칭은 사진 순서가 아니라 **가장 가까운 Target**에 매칭
  (`measurement_plan.py`). L/S는 Target이 같으면 큰 값=Line 원칙 +
  크로스헤어 밝기로 2차 검증(`ls_brightness.py`).
- **L&S Item은 Line/Space가 쌍이 아닐 수 있음** — Item마다 독립이라 Line만
  있거나 Space만 있기도 함(예: Item1 = Line Target 10만, Item2 = Space
  Target 20만). 한쪽만 있는 Item은 사진 한 장에 값이 **1개만** 찍혀서 CD
  사진과 생김새가 같으므로, 줄 개수만으로 종류를 정하면 안 됨 →
  값으로 CD/L&S를 가림(`match_single_target`). 두 종류의 스펙에 모두
  들어와 확신할 수 없으면 `확인필요` 표시. 2026-08-05에 실제 데이터로 확인
  (그전엔 `1줄=무조건 CD`여서 Line 사진이 Pad CD Target과 비교돼 스펙이탈로 잡혔음).
- Overlay 방향(상/하/좌/우)은 측정값이 아니라 **화면 픽셀 위치**로 판별
  (`overlay_analysis.py`).
- 값-좌표 정합성(`값=√(X²+Y²)`)으로 OCR 오독·원본 데이터 불일치를 함께 검출.
- 표준편차는 **표본표준편차**(n-1, 엑셀 STDEV()와 동일). Cpk/CDU% 등 계산식은
  전부 사용자가 실제 쓰던 엑셀 수식 기준으로 맞춤 — 임의로 통계 공식 바꾸지 말 것.
- 지원 사진 형식: `.bmp`/`.png`/`.jpg`/`.jpeg` (`IMAGE_EXTENSIONS`). JPG는
  손실압축이라 오독 위험 있음 — 이미 확인필요로 걸러지긴 하나 BMP/PNG 권장.

## 파일 위치 감각

- 실행 결과(`측정결과.xlsx/html`, `측정로그_*.txt`)는 **사진 폴더 안**에 생김 → gitignore 대상.
- **`실행이력.csv`**는 프로그램 폴더에 고정 — 여러 Lot을 넘나드는 누적
  통계라 사진 폴더가 아니라 여기 둠. **이건 지우면 안 되는 데이터, git 추적함.**
- `samples/Sample`/`samples/LS Sample`/`samples/Sample2`/`samples/Sample3`는
  실제 측정 사진(버그 재현용) — 전부 git에 커밋되어 있음(Private repo, 사용자
  명시적 승인됨). 2026-07-29에 최상위에서 `samples/` 밑으로 정리함.
