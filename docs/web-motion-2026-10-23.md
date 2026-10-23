# 환율 신호등 인터랙션 변경

## 변경 위치

- `fx.py`의 `year_signal()`·`signal_cell()`: 같은 최근 365일 관측에서 최저·최고·평균·오늘 위치를 정확한 분수로 계산합니다. 평균 눈금, 오늘 점, 최저·최고 값, 기존 신호 문장을 표시합니다. 120개 미만·최신일 결측은 생략하고, 최저=최고면 중앙에 표시합니다. JPY는 기존 100엔 기준입니다.
- `fx.py`의 `home()`: 통화마다 숫자 행과 범위 행을 같은 `tbody`로 묶었습니다. 비교값과 기준일은 유지합니다.
- `fx.py`의 `converter()`·`assets/site.js`: 회전 아이콘과 반대 방향의 값 전환을 추가했습니다. 방향 버튼은 기존처럼 입력 숫자를 유지한 채 환산 방향을 바꿉니다. 최종 `output`은 즉시 갱신하고, 접근성 트리에서 제외한 화면 숫자만 카운트업합니다. 두 값은 같은 grid 셀을 사용해 큰 금액도 아래 문단과 겹치지 않게 했습니다.
- `assets/site.js`: 실제 통화 페이지 링크를 유지한 채 선택 표시를 이동합니다. 이전 선택은 세션 저장소에서 전달하며 저장소를 쓸 수 없어도 링크가 작동합니다. 행과 월별 링크 묶음은 IntersectionObserver로 한 번 등장합니다.
- `assets/site.css`: 표의 열 간격과 통화 제목을 정리하고 범위는 행 전체 폭으로 뺐습니다. 이동하는 투명 박스가 가로 넘침을 만들지 않도록 범위 컨테이너에서 자릅니다. hover는 포인터 조건 안에 있고 입력은 18px입니다.

브랜드 색·의미색·본문 문구·정적 H1·JSON-LD·meta·CSP·광고·분석 스크립트는 유지했습니다. 실행 스크립트는 기존 외부 파일에만 추가했습니다.

## 모션 값

| 대상 | 값 |
| --- | --- |
| 버튼 누름 | scale .96, 검정 10% 덮개로 밝기 .9, 누름 90ms / 복귀 260ms |
| 목록·탭 누름 | 회색 배경, scale .98, 90ms / 260ms |
| 행·월별 묶음 등장 | translateY(18px)에서 0, opacity 0에서 1, 380ms, 50ms 차례 |
| 오늘 위치 점 | 평균 위치에서 오늘 위치, 650ms, 화면 진입 시 한 번 |
| 환산 결과 | 600ms, ease-out quart, 진행 중 재입력은 현재 표시값에서 다시 시작 |
| 방향 버튼 | 아이콘 180도씩 회전 380ms, 입력·결과 반대 방향 18px 전환 260ms |
| 통화 선택 표시 | transform 이동·스케일 300ms |

CSS·WAAPI 이징은 `cubic-bezier(.22,1,.36,1)`입니다. 숫자 내용 변경 외 모션 속성은 transform·opacity뿐입니다. 동작 줄이기를 켜면 즉시 최종 상태가 되고, 실행 도중 바꿔도 카운트와 WAAPI를 취소합니다. 숨김 클래스는 JS가 붙이므로 JS 없이도 콘텐츠와 최종 위치가 표시됩니다.

## 검증

`python3 -m unittest discover -s tests -v`: 68개 통과. 내부 Node 검사 11개도 통과했습니다. 정확한 범위 계산·365일 경계·동일값·빈 데이터·최신일 결측·JPY 단위·카운트 중단·방향 전환·한 번 등장·동작 줄이기·실제 링크 보존·추가 인라인 스크립트 부재를 검사합니다.

`python3 fx.py build --history tests/fixtures/history.json --output site`: 29페이지 생성 성공. 이 파일은 기존 합성 fixture이며 실제 이력으로 저장하거나 게시하지 않았습니다. `git diff --check`와 브라우저 검사 스크립트 구문 검사도 통과했습니다.

390px·1440px 검사는 `tests/browser_motion.cjs`에 남겼습니다. 임시 폴더에만 1년 합성 관측과 빈 상태를 만들고, 외부 네트워크 없이 범위·큰 금액·전환·동작 줄이기·JPY·빈 상태·JS 미사용 화면을 검사합니다. 새 패키지는 설치하지 않습니다. 기존 Playwright가 있는 환경의 실행 명령:

```sh
FX_PLAYWRIGHT_MODULE="$HOME/.agents/skills/gstack/node_modules/playwright" \
FX_CHROMIUM_EXECUTABLE="$HOME/Library/Caches/ms-playwright/chromium_headless_shell-1248/chrome-headless-shell-mac-arm64/chrome-headless-shell" \
node tests/browser_motion.cjs
```

현재 샌드박스에서는 Chromium이 `MachPortRendezvousServer ... Permission denied (1100)`로 종료됐습니다. 페이지를 열기 전에 실패했으므로 390px·1440px의 실제 가로 넘침·겹침과 실기기 터치감은 미검증입니다.

현재 브랜치 `web/motion-1023`에서 `git add`를 시도했지만 `.git/index.lock: Operation not permitted`로 차단됐습니다. 커밋은 생성되지 않았습니다. 브랜치 전환·push·배포는 하지 않았습니다. 쓰기 가능한 환경에서의 커밋 명령:

```sh
git add fx.py assets/site.css assets/site.js tests/test_fx.py tests/client_logic.cjs tests/browser_motion.cjs README.md docs/web-motion-2026-10-23.md
git commit -m "feat: animate currency signals and converter"
```

## 제외한 것

- 실제 입력 금액과 결과의 자동 교환: 기존 환산 방향 버튼의 계산 동작을 유지하고 시각 전환만 추가했습니다.
- 자료가 부족한 통화의 범위와 임의 관측 보충: 기존 신호 기준과 데이터 의미를 지켰습니다.
- 입력창 자체의 글자별 롤링: 입력·커서·선택 동작을 방해하므로 결과만 카운트업합니다.
- 그래프 반복 재생·장식 모션·애니메이션 라이브러리: 읽기 방해와 새 의존성을 피했습니다.
- UI 전용 배포 가드 완화: 기존 게시본과 표 마크업이 달라 거부되는 것이 정상입니다. README에 정기 스케줄 또는 `refresh_rates=true` 경로를 기록했습니다. 이번 작업에서 게시 명령은 실행하지 않았습니다.
