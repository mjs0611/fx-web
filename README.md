# 환율 기록 · web edition

## 기존 게시 데이터로 UI만 배포하기

공식 `Daily ECB reference rates` 워크플로를 수동 실행할 때 `refresh_rates=false`로 지정하면 신규 환율 조회를 생략합니다. 최신 `gh-pages`의 사이트·이력을 복원한 뒤 `ops/rebuild_ui.py`가 기존 관측만으로 화면을 만듭니다. 이력이 없거나 비어 있으면 시작하지 않으며, 공개 데이터·도메인·비 UI 파일 해시와 금융 표·차트·금액·본문·광고 마크업이 달라지면 게시 전에 실패합니다. 갱신 가능한 비 HTML 파일은 `assets/site.css`, `assets/site.js`, `assets/og.png`뿐입니다. fixture로 운영 이력을 대체하지 않습니다.

기존 스케줄과 `refresh_rates=true` 수동 실행은 종전 수집·배포 동작을 유지합니다. 권한과 Pages·DNS·광고 설정은 변경하지 않습니다.

이번 Cloudflare Web Analytics 도입은 개인정보처리방침 본문을 변경하므로 **정기 스케줄 또는 `refresh_rates=true` 수동 실행으로 반영해야 합니다.** `refresh_rates=false` UI 전용 경로는 본문 보존 가드가 이 변경을 거부하므로 사용할 수 없습니다.

`https://fx.ditoaxis.com/`용 정적 사이트입니다. USD, JPY(100엔), EUR, CNY, GBP의 원화 환율, 월별 기록, 브라우저 계산기를 제공합니다. 은행 환율이나 실시간 시세가 아닌 **하루 한 번 발표하는 ECB 참고 환율**입니다.

## 실행 환경과 단일 검증 명령

Python 3.11+, Node.js 20+, Bash가 필요합니다. 생성기는 Python 표준 라이브러리만 사용하며, Node는 클라이언트 테스트에만 사용합니다. pip/npm 패키지를 설치할 필요가 없습니다.

저장소 루트에서 실행하는 **단일 proof 명령**:

```sh
python3 -m unittest discover -s tests -v
```

네트워크 없이 합성 fixture로 환산 정밀도, 월평균·최저·최고, 주말·휴일·결측 무보간, 비교일, 백필·증분 수집·실패 보존, 주말 중복 실행, 페이지 title/canonical/OG/sitemap, 빈 상태, 광고 설정을 검사합니다. Node 기본 테스트 러너로 실제 계산기·차트 스크립트도 실행합니다. 배포 가드 테스트는 가짜 `git` 실행 파일만 사용하므로 **실제 커밋·푸시가 없습니다**.

브라우저 레이아웃·스크린샷·실제 API·GitHub Pages 검증은 이 명령에 포함되지 않습니다. 360px·390px·데스크톱에서 별도 확인해야 합니다. 코디네이터의 외부 검토에서는 실제 Frankfurter 환산·월 통계·무보간·워크플로·게시 가드를 확인했습니다. 이 로컬 환경에서는 DNS 제한으로 실데이터 수집을 완료하지 못했고, Chromium 실행도 macOS 권한 오류로 막혀 수정 후 390px 레이아웃을 실측하지 못했습니다.

## 로컬 생성

실제 이력이 아직 없으면 빈 상태 8페이지와 `404.html`을 생성합니다. 환율을 만들어 넣지 않으며 자료가 없는 환율 페이지는 `noindex` 처리합니다.

```sh
python3 fx.py build
python3 -m http.server 8000 --directory site
```

합성 자료로 기능을 검토하려면 다음과 같이 생성합니다. fixture는 **실제 환율이 아니므로 게시하지 않습니다**. 이 명령은 fixture를 운영 이력 파일로 복사하지 않습니다.

```sh
python3 fx.py build --history tests/fixtures/history.json --output site
```

실제 백필은 코디네이터가 실행합니다. 이력이 없으면 2015-01-01부터 연도별로 받고, 이력이 있으면 마지막 관측일의 7일 전부터 다시 확인해 늦은 자료·정정을 반영합니다. 파일 저장은 모든 응답 검증 후 한 번에 교체합니다.

```sh
python3 fx.py update --history site/data/history.json
python3 fx.py build --history site/data/history.json --output site
```

전체 기간을 다시 확인할 필요가 있으면 `update --backfill`을 사용합니다. 이전 값은 API 응답에서 빠졌다고 지우지 않습니다. 따라서 공급자가 과거 관측을 철회한 경우에는 별도 검토가 필요합니다. 연결 오류·잘못된 응답·7일 이상 구간의 빈 응답은 실패로 종료하며 기존 이력을 보존합니다. API가 일부 날짜·통화를 누락한 경우 그 사실을 휴일로 단정하지 않습니다.

Frankfurter 응답은 요청 시작일이 휴일·주말이면 그 이전 마지막 관측을 포함할 수 있습니다. `from` 이전 행은 날짜·통화·숫자 형식을 검증한 뒤 제외하며, stderr에 요청 구간과 제외한 관측 행 수(날짜·통화 쌍)를 기록합니다. 날짜를 바꾸거나 이력에 새로 저장하지 않고, 이미 보관한 범위 밖 기록도 덮어쓰지 않습니다. 이 규칙은 최초 백필과 마지막 관측일−7일의 증분 수집에 똑같이 적용합니다. 구간 안의 주말 관측, `to` 이후 날짜, 숫자가 아닌 값은 계속 거부합니다. `tests/fixtures/pre_window_response.json`은 이 경계를 재현하는 합성 API 응답입니다.

제외할 수 있는 시작일 이전 관측은 `from`으로부터 7일 이내의 **한 날짜**뿐입니다. 같은 날짜의 여러 통화 행은 허용합니다. 서로 다른 경계 날짜가 둘 이상이거나 7일보다 오래된 행이 있으면 오류로 종료하고 기존 이력을 보존합니다.

`build`는 지정한 출력 폴더의 통화별 생성 페이지를 교체합니다. 전용 출력 폴더를 사용해주세요. `data/`와 `.git`은 보존합니다. 실행 경로는 현재 체크아웃 기준이며 다른 원본 저장소에 의존하지 않습니다.

## 이력과 계산 기준

이력은 **gh-pages 브랜치의 `data/history.json`**에 보관합니다. 소스 브랜치의 일일 변경을 피하고, 관측 JSON과 그 관측으로 만든 페이지를 하나의 커밋으로 보존하려는 선택입니다. 로컬에서는 `site/data/history.json`이며 `site/`는 소스 Git에서 제외합니다. 운영 이력과 생성 페이지는 공개 파일입니다.

JSON은 `schema: 1`, `base: EUR`, `provider: ECB`, `rates: { YYYY-MM-DD: { KRW: "…", USD: "…", ... } }` 형식입니다. 숫자를 소수 문자열로 저장하여 원자료의 자릿수를 보존합니다.

- 자료 주소: [Frankfurter ECB 전용 시계열 API](https://frankfurter.dev/). `/v2/providers/ecb/rates?base=EUR&quotes=CNY,GBP,JPY,KRW,USD&from=...&to=...`를 사용합니다. 여러 공급자를 혼합하는 기본 주소를 사용하지 않습니다.
- 외화 1단위의 원화 금액 = 같은 관측일의 `EUR→KRW / EUR→외화`. EUR는 `EUR→KRW`, JPY 표시값은 100배입니다. 계산기에는 실제 엔 금액을 입력합니다.
- 서버의 환산·평균·증감은 `Fraction`으로 계산하고, 표시할 때만 소수 둘째 자리로 반올림합니다. 브라우저 계산은 반올림 전 분수를 JavaScript 숫자로 나눈 뒤 마지막에 표시 자릿수를 정합니다.
- 월평균은 관측된 날짜만의 산술평균입니다. 최저·최고 동률이면 가장 이른 날짜를 표시합니다. 모든 월에 관측 수와 수집 범위를 표시하며 완전한 월이라고 단정하지 않습니다.
- 홈의 최신 관측일에 특정 통화가 없으면 그 통화는 자료 대기입니다. 통화 페이지는 그 통화의 실제 마지막 관측일을 표시합니다.
- 전일 비교는 직전 관측일입니다. 주간은 7일 전, 연간은 전년 같은 날짜(윤년 2월 29일은 전년 2월 28일) 또는 그 이전 7일 안의 마지막 관측을 사용합니다. 실제 비교 날짜를 항상 표시하며 자료가 부족하면 비교를 보류합니다.
- 표·차트에는 관측점만 포함합니다. 주말·휴일·결측값을 만들지 않으며 빈 날짜를 선으로 잇지 않습니다. 차트 범위는 마지막 관측일을 포함한 최근 30·90·365일 또는 전체입니다.

원자료는 [ECB에서 무료 제공](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html)합니다. 출처 표시, 정확한 재현, 가공 사실 표시, 유료 재배포 시 무료 원자료 고지, 프레임을 사용하지 않는 상업적 링크 등의 [ECB 재사용 조건](https://www.ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html)을 `/about/`에 안내합니다.

## 페이지와 화면

`/`, `/<cur>/`, `/<cur>/<YYYY-MM>/`, `/about/`, `/privacy/`를 생성합니다. 통화 코드는 소문자입니다. 관측이 있는 달만 월별 페이지를 만듭니다. 각 페이지에 canonical·OG·설명을 넣고, 검색 가능한 페이지의 `sitemap.xml`, `robots.txt`, `CNAME`, `.nojekyll`을 생성합니다. `404.html`은 같은 스타일과 홈 링크를 제공하며 `noindex`로 지정하고 사이트맵에서는 제외합니다. 모든 페이지에서 로컬 SVG 파비콘을 사용합니다.

모든 HTML(`404.html` 포함)의 head에는 AdSense 바로 옆에 공용 `<script defer src="https://ditoaxis.com/m.js"></script>`가 정확히 1개 있습니다. 분석 토큰은 회사 홈의 공용 로더에서만 관리합니다. 토큰이 비어 있거나 호스트가 `ditoaxis.com` 또는 그 하위 도메인이 아니면 비콘을 로드하지 않습니다.

공유 미리보기는 모든 HTML의 공통 head에서 `https://fx.ditoaxis.com/assets/og.png`를 사용합니다. `assets/og.png`는 기존 흰 바탕·잉크색·구분선과 Apple SD Gothic Neo 글꼴로 만든 정적 1200×630 PNG입니다. OG 이미지 크기·유형·대체 텍스트와 Twitter 큰 이미지 카드의 제목·설명·이미지를 함께 선언합니다. 빌드할 때 이미지를 복사하므로 생성기에 이미지 패키지는 필요하지 않습니다.

kospi-relay의 잉크색·비교표 스타일을 기준으로 흰 바탕, `#10172A` 잉크, `#DFE2E7` 구분선, 상승 적색·하락 청색을 사용합니다. 1120px 본문 비교표는 좁은 화면에서 통화별 비교 행으로 바뀝니다. 글자 크기 하한은 12px이며 폰트·차트 라이브러리를 외부에서 받지 않습니다. 정적 차트·표는 JavaScript 없이도 볼 수 있고, 계산기와 기간 버튼만 JavaScript로 활성화합니다.

차트는 데스크톱에서 `900:240`, 600px 이하 화면에서 `900:600` 비율로 표시합니다. 정적 차트와 기간 선택 후 차트 모두 SVG가 늘어난 높이를 채우도록 설정합니다. CSS 계산상 390px 화면에서는 차트 영역 약 233px·실제 최저~최고 관측 범위 175px, 360px에서는 약 213px·160px입니다. 좁은 화면의 관측점에는 축소되지 않는 3px 테두리를 적용합니다. 실제 화면과 스크린샷은 코디네이터가 확인합니다.

## 광고

`ads.txt`는 루트 도메인 `ditoaxis.com/ads.txt`에서 관리합니다. 이 생성기는 서브도메인용 파일을 만들지 않으며, 이전 버전이 만든 출력 폴더의 `ads.txt`도 재생성할 때 제거합니다.

모든 페이지 head에 `ca-pub-4557219410513767` AdSense 로더가 있습니다. 광고 단위는 기본적으로 생략합니다. 아래 환경변수 또는 GitHub repository variable `ADSENSE_SLOT`에 숫자 슬롯 ID를 설정하면 페이지당 1개 표시합니다.

```sh
ADSENSE_SLOT=1234567890 python3 fx.py build
```

계산기 금액은 브라우저 안에서만 계산하며 저장·전송하지 않습니다. 방문 통계에는 쿠키나 기기 식별자를 사용하지 않는 Cloudflare Web Analytics 비콘을 사용합니다. 공용 로더가 조건을 충족하면 `static.cloudflareinsights.com`에서 비콘 스크립트를 불러오고 `cloudflareinsights.com`으로 통계를 전송합니다. Google 광고 스크립트, GitHub 호스팅과 Cloudflare 방문 통계의 정보 처리는 `/privacy/`에 설명합니다.

## 코디네이터의 게시 설정

이 작업에서는 커밋·푸시·원격 생성·게시를 실행하지 않습니다. 아래는 검토 후 코디네이터가 사용할 구성입니다.

1. GitHub 저장소에 검토한 소스를 반영하고, Pages source를 **GitHub Actions**로 설정합니다. Pages custom domain은 `fx.ditoaxis.com`으로 설정하고 DNS를 구성합니다. `CNAME` 파일만으로 GitHub 설정과 DNS가 완료되는 것은 아닙니다.
2. `Daily ECB reference rates` 워크플로를 수동 실행합니다. 첫 실행은 없는 `gh-pages`를 만들고 실제 백필을 수행합니다. 기존 브랜치가 있으면 기록을 복원합니다. 원격 조회 오류를 없는 브랜치로 처리하지 않습니다.
3. 실제 자료와 360·390·1440px 화면, 계산기 양방향 및 100엔 단위, 월 통계, custom domain·HTTPS·광고를 확인합니다.

워크플로는 매일 **15:30 UTC, 18:30 UTC**에 실행하며 수동 실행도 지원합니다. 순서는 proof → 이력 복원 → 수집 → 생성 → 변경이 있는 경우만 gh-pages 커밋·푸시 → Pages artifact 게시입니다. 주말에도 빠진 금요일 자료를 복구할 수 있도록 수집하며, 신규 관측·정정·소스 변경이 없으면 빈 커밋을 만들지 않습니다. Pages 게시 단계는 변경이 없어도 다시 실행해 이전 게시 실패를 복구할 수 있습니다. 동시 실행은 직렬화하며 강제 푸시는 하지 않습니다.

`ops/publish.sh`의 실제 실행은 게시 작업이므로 이 구현 검토 중에는 실행하지 않습니다. 소스나 광고 설정을 바꿨다면 수동 실행으로 새 화면을 반영할 수 있습니다.
