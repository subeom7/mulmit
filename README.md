# 물밑 · mulmit

[mulmit.com](https://mulmit.com)

글로벌 자산·거시·유동성·주말 파생시장 신호를 모은 시장 모니터(`/`)와
개별 티커의 **CAPM 지표 · 최대낙폭(MDD) · 미래 MDD 확률분포**를 보는
분석 화면(`/analytics`)을 제공하는 FastAPI 서비스다. `/monitor`는 시장
모니터의 별칭이며 두 화면 모두 한국어와 영어를 지원한다.

공개 배포에서는 라이선스 경계가 불명확한 레거시 가격 경로를 기본으로 끈다.
따라서 `/analytics`의 계산 API, 저장된 섹터 ETF 스냅샷과 상관관계 API는
`LEGACY_PRICE_DATA_ENABLED=true`로 명시적으로 허용한 사설 환경에서만 열린다.

다음 세션에서 라이선스 연결과 미연결 카드를 이어서 작업할 때는 아래 두 문서를
먼저 읽는다.

- **[다음 세션 인수인계](docs/NEXT_SESSION_HANDOFF.md)** — 우선순위, 코드 위치, API 계약, 테스트·배포 완료 기준
- **[데이터 공급자·권리 등록부](docs/DATA_SOURCE_REGISTER.md)** — 공급자별 공개 표시·캐시·재배포 판정, 예산, 카드 매핑
- **[HIP-3 권리 문의 초안](docs/INQUIRY_HYPERLIQUID_TRADE_XYZ.md)** — 발송 전. 회신이 자산 카드 차트를 여는 열쇠

공개 화면의 법적 고지는 `/privacy`(개인정보처리방침), `/terms`(이용약관),
`/disclaimer`(면책 고지)에 있다. 세 페이지 모두 KO/EN 본문을 DOM에 함께 담아
스크립트 없이도 읽히고, 어떤 데이터 lane이 닫혀 있어도 항상 200으로 응답한다.
개인정보처리방침은 boilerplate가 아니라 이 사이트가 실제로 하는 일(접속 로그,
레이트리밋용 IP, localStorage 설정, TradingView 위젯의 제3자 전달)만 적는다.
동작이 바뀌면 문서를 먼저 고친다.

이름은 **언더워터(underwater)** 에서 왔다. 낙폭 분석에서 전고점 아래에 잠겨 있는
구간을 부르는 말이고, 이 서비스의 핵심 차트가 그 언더워터 곡선이다.
"얼마나 올랐나"가 아니라 **"얼마나 잠겨 있었고, 앞으로 얼마나 잠길 수 있나"** 를
보는 도구다.

```
pip install -r requirements-dev.txt
python -m uvicorn app.main:app --reload
# http://127.0.0.1:8000
```

저장소는 SQLite(`.data/stock.db`)로 자동 생성된다. 준비할 게 없다.
배포에선 `DATABASE_URL`로 Postgres를 주입한다.

터미널만 쓸 거라면:

```
python cli.py AAPL
python cli.py AAPL --horizon 36 --drift zero
python cli.py --corr AAPL MSFT GLD
```

---

## 미래 MDD 예측을 어떻게 하는가

**점 예측은 하지 않는다.** "내년에 -32% 빠진다" 같은 숫자는 의미가 없다.
대신 수익률 경로를 수천 개 시뮬레이션해서 **MDD의 확률분포**를 만들고
"1년 안에 -30% 이상 빠질 확률 15%" 형태로 제시한다.

가정이 서로 다른 세 방법을 함께 돌려서 교차검증한다. 세 값이 비슷하면 신뢰도가
올라가고, 크게 갈리면 그 자체가 신호다.

| 방법 | 하는 일 | 강점 |
|---|---|---|
| `block_bootstrap` (기본) | 과거 일간 수익률을 20일 **블록** 단위로 복원추출 | 분포 가정이 없다. 블록으로 뽑아서 변동성 군집(폭락은 몰려온다)과 꼬리 위험이 보존된다 |
| `student_t` | 과거 첨도로 자유도를 추정한 t분포 GBM | 과거에 없던 크기의 충격도 만들어내 부트스트랩을 보완 |
| `historical_windows` | 과거 실제 N거래일 구간들의 MDD 실증분포 | 드리프트 가정이 개입하지 않는 현실 기준선 |

AAPL 1년 기준 실제 출력 — 세 방법이 근접한다:

| 방법 | 중앙값 | 상위 5% 악조건 | -20% 초과 확률 |
|---|---|---|---|
| 블록 부트스트랩 | -20.9% | -37.0% | 55% |
| t분포 시뮬레이션 | -20.3% | -37.4% | 51% |
| 과거 실증 구간 | -20.4% | -38.5% | 54% |

### 수익률 가정을 반드시 확인할 것

기본값 `historical`은 **과거 추세가 그대로 이어진다**고 가정한다. 최근 급등한
종목에서는 이게 미래를 크게 낙관하게 만든다(AAPL은 연 29% 드리프트가 깔린다).
낙폭이 얕게 나오는 이유가 대부분 여기 있다. UI의 "수익률 가정"에서 바꿀 수 있다.

| 가정 | AAPL 1년 MDD 중앙값 | -20% 초과 확률 |
|---|---|---|
| 과거 추세 유지 (연 29.1%) | -20.9% | 55% |
| CAPM 기대수익률 (연 8.6%) | -23.9% | 68% |
| 0% (보수적) | -26.2% | 74% |

### 한계

세 방법 모두 **미래의 변동성 구조가 과거와 비슷하다**고 가정한다. 사업 구조가
바뀐 기업, 상장 초기 종목, 체제 전환 구간에서는 빗나간다. 표본이 3년 미만이거나
예측 구간이 표본에 비해 길면 응답의 `warnings`에 경고가 담긴다.

---

## 구조

```
app/
  main.py            FastAPI 라우트 + 레이트리밋
  macro_dashboard.py FRED 카드·차트 페이로드 조립
  market_assets.py   Hyperliquid HIP-3 합성 자산 카드
  market_sectors.py  S&P 500 섹터 ETF 기간별 스냅샷
  weekend_signals.py 한국·미국 기술주 주말 파생시장 참고 신호
  service.py         티커 -> 대시보드 페이로드 조립 + 응답 캐시
  data.py            데이터 파사드 (저장소 우선, 공급자는 최후 수단)
  store.py           가격·거시 메타데이터/관측치 Postgres/SQLite 영속 저장소
  ingest.py          허가된 거시 피드 + 명시적으로 허용한 레거시 가격 수집 배치
  config.py          환경변수 설정
  providers/
    base.py          공급자 인터페이스 (유료 API 교체 지점)
    yahoo.py         yfinance 구현
    fred.py          비공개 평가용 FRED API 어댑터(배포 기본 비활성)
    hyperliquid.py   공개 HIP-3 컨텍스트·캔들 클라이언트
    krx.py           KRX OPEN API 어댑터 (승인 전 비활성)
  metrics/           전부 순수 함수. 네트워크를 모른다.
    basic.py         수익률, 변동성, 샤프, 소르티노
    capm.py          베타/알파, 상승장·하락장 분해
    drawdown.py      MDD, 언더워터 곡선, 낙폭 구간, 얼스터 지수
    forecast.py      미래 MDD 몬테카를로
    correlation.py   티커 간 상관계수
    common.py        연율화 계수 추론
  static/
    index.html       개별 티커 한·영 분석 화면 (차트는 직접 그린 SVG)
    monitor.html     시장 모니터 문서 구조
    monitor.css      다크/라이트·반응형 모니터 스타일
    monitor.js       카드·차트·주말 신호·TradingView embed 렌더링
deploy/              Caddyfile, 배포·부트스트랩 스크립트, AWS 문서
tests/               단위·통합 테스트 (네트워크 불필요)
```

```
python -m pytest tests/ -q
python -m ruff check app tests scripts cli.py
```

### 데이터 경로: 공개 모니터와 레거시 분석 분리

모든 요청이 같은 공급자를 쓰지는 않는다. 공개 모니터의 핵심 경로는 Yahoo
캐시를 읽지 않는다. 장기 거시 시계열은 배치에서 저장하고, 짧은 TTL이 필요한
합성 파생상품 참고값만 요청 시점에 공개 API를 조회한다.

```
글로벌/한국 자산 카드  Hyperliquid HIP-3 → 프로세스 TTL·stale 캐시 → 응답
주말 참고 신호          HIP-3 컨텍스트 + 세션 기준 캔들 → 합성 참고값
거시·유동성             허가된 배치 → store → /api/market/macro
                         └ FRED 어댑터는 약관 검토로 기본 비활성
S&P 500 종목 히트맵    사용자 브라우저 → TradingView 외부 embed
섹터/상관/개별 분석     허용된 저장 스냅샷만 사용; 공개 기본값에서는 503
```

`LEGACY_PRICE_DATA_ENABLED=false`가 기본값이다. `true`로 바꾼 사설 환경에서만
기존 Yahoo/yfinance 배치, `/api/metrics`, `/api/correlation`,
`/api/market/sectors`를 사용한다. 응답 캐시에는 앱 버전과 마지막 거래일이
포함돼 계산 로직이나 데이터가 바뀌면 무효화된다.

### 월 3만원 데이터 예산

현재 공개 기본 구성의 **데이터/API 구독료는 월 0원**이다. Hyperliquid 공개 info
API와 TradingView embed를 사용한다. FRED 배치와 KRX는 권리 확인 전이라 꺼져 있다.
따라서 월 3만원 예산은 아직 사용하지 않는다. 서버·도메인·네트워크 비용은
이 계산에 포함하지 않았다.

무료 조회가 재배포 권리를 뜻하지는 않는다. `VIXCLS`, `BAMLH0A0HYM2`,
`PCOPPUSDM`처럼 원 제공자의 외부 표시 권한이 필요한 정확한 시리즈는 계약
전까지 숫자를 만들거나 우회 수집하지 않고 `license_required` 상태로 둔다.
현재 예산으로 해당 상용 라이선스까지 제공한다고 약속하지 않는다.

## 배포

EC2 한 대 + GitHub Actions. SSH를 열지 않고 SSM으로 배포한다.
자세한 절차와 비용은 **[deploy/README.md](deploy/README.md)**.

FRED 어댑터는 현행 API 약관이 API 콘텐츠의 저장·캐시·제3자 제공을 제한하므로
공개 배포에서 켜지 않는다. 서면 허가나 동일 지표의 허용된 원발행기관 피드를
확보한 사설 환경에서만 검토한다.

거시 시계열은 공급자 중립 테이블(`economic_series` / `economic_observations`)에
저장한다. 계열은 내부 안정 키(`treasury_10y`)로 식별하고, 공급자 id와 공급자의 원본
id(`fred` / `DGS10`), 그리고 권리 상태를 행에 함께 담는다. 그래서 NY Fed나 BLS를
연결하는 일이 스키마 변경이 아니라 행 변경이 된다. 레거시 `fred_*` 테이블은 남아
있고, 아직 옮기지 않은 계열만 그쪽에서 읽는다. 옮기려면:

```powershell
python -m app.ingest --migrate-macro
```

게이트는 두 겹이다. lane이 "이 공급자를 서빙해도 되는가"를, 행의 `rights_status`가
"이 계열을 서빙해도 되는가"를 답하고 둘 다 통과해야 값이 나간다. FRED lane이 열려도
`VIXCLS`는 Cboe 권리라 계속 비어 있는 이유다.

권리 플래그는 수집뿐 아니라 **서빙까지** 결정한다. `FRED_ENABLED=false`면 과거에
적재된 FRED 행이 DB에 남아 있어도 `/api/market/macro`가 값을 반환하지 않고
`macro_data_disabled` 503과 `Cache-Control: no-store`를 돌려준다. 판정은
`app/data_rights.py`에서 공급자 lane 단위로 하므로, 이후 승인된 NY Fed·BLS·EIA
lane을 추가해도 FRED lane은 닫힌 채로 남는다.

```dotenv
FRED_ENABLED=false
FRED_API_KEY=
FRED_MAX_AGE=21600
LEGACY_PRICE_DATA_ENABLED=false
HIP3_PUBLIC_DISPLAY_ENABLED=false
```

`NYFED_ENABLED`는 SOFR·EFFR·익일물 역레포를 뉴욕 연준에서 직접 받아 온다. 이
프로젝트에서 권리 근거가 가장 명확한 공급자다. NY Fed 이용약관이 자동 접근, 저장,
복제·배포, 파생 작업을 "personal or **business** purposes"로 명시적으로 허가한다.
키가 필요 없고, 조건은 지정된 출처 문구를 값과 함께 표시하는 것이라 코드가 응답의
`rights.notice`에 자동으로 싣는다.

```dotenv
NYFED_ENABLED=false
```

역레포는 **달러 단위**다. FRED의 `RRPONTSYD`는 십억 달러라 두 값을 같은 축에 두면
안 된다. 공급자가 준 원 단위를 그대로 저장하는 것이 공급자 중립 테이블의 목적이다.

한 계열을 두 lane이 이름 붙일 수 있으므로, 행을 가진 공급자가 그 계열을 계속
소유한다. FRED lane을 켜도 승인된 NY Fed 계열을 덮어쓰지 않는다.

`FEDBOARD_ENABLED`는 Federal Reserve Board의 H.15에서 미국 10년물·2년물 금리를
직접 받고, 그 둘로 장단기 금리차(10Y−2Y)를 계산한다. 키가 필요 없다.

경로 선택에 이유가 있다. Board는 Data Download Program을 폐지하고 FRED로 유도하는
중인데(1단계 2026-11-09), Mulmit은 FRED 약관 때문에 그 대체 경로를 쓸 수 없다. 같은
전환 공지에 "Historical data will remain available for download as XML files on
statistical release pages"라고 적혀 있어, DDP 질의 엔드포인트가 아니라 **릴리스 페이지
XML 아카이브**를 읽는다. 이 문장이 철회되면 lane 전체가 막히므로 등록부의 재검토일이
2026-11-01이다.

```dotenv
FEDBOARD_ENABLED=false
```

이 포맷에는 조용히 틀린 숫자를 만드는 함정이 둘 있다. 관측치의 `OBS_STATUS`가 `A`가
아니면 그 값은 `-9999`(H.15) 같은 센티넬이고 날짜는 미국 공휴일이다. 그리고 아카이브
하나에 릴리스의 모든 계열이 들어 있으므로 계열마다 받지 않고 한 번만 받아 재사용한다.

10Y−2Y는 **양쪽이 모두 게시한 날짜**로만 계산한다. 한쪽만 있는 날을 이월값과 짝지으면
없는 관측을 지어내는 셈이다.

`SEC_EDGAR_ENABLED`는 `/analytics`의 내부자거래(Form 3·4·5) 패널을 켠다. EDGAR는
미국 연방정부 공시 시스템이고 SEC는 누구나 무료로 접근·다운로드할 수 있다고
안내하지만, 자동 접근에는 연락처가 담긴 User-Agent 선언과 초당 10요청 상한이
따른다. 연락처는 배포마다 다르고 저장소에 커밋하지 않으므로
`SEC_EDGAR_USER_AGENT`가 비어 있으면 `ENABLED=true`여도 lane이 닫힌다.

```dotenv
SEC_EDGAR_ENABLED=false
SEC_EDGAR_USER_AGENT=            # 예: "Mulmit admin@example.com"
SEC_EDGAR_TICKERS=AAPL,MSFT,NVDA,GOOGL,TSLA
```

수집은 배치에서만 한다. 목록에 없는 티커를 검색하면 EDGAR를 즉석에서 부르지 않고
`queued`로 답한 뒤 다음 수집 주기가 가져간다. 표시할 때 시장 매수(`P`)·매도(`S`)와
부여(`A`)·파생 행사(`M`)·세금 상계(`F`)를 절대 합산하지 않는다. RSU 베스팅 한 건이
거대한 매매 신호처럼 보이는 것을 막기 위해서다.

`HIP3_PUBLIC_DISPLAY_ENABLED`는 Hyperliquid HIP-3 / trade.xyz 값의 공개 표시
게이트다. API가 키 없이 열려 있다는 사실은 재표시 권리가 아니므로 코드 기본값은
false이고, 서면 확인 전 현행 화면을 유지하려면 서버 `.env`에서 명시적으로 켠 뒤
그 결정을 [데이터 공급자·권리 등록부](docs/DATA_SOURCE_REGISTER.md)에 기록한다.
현재 lane 상태는 `GET /api/status`의 `data_lanes`에서 확인한다.

KRX OPEN API 어댑터와 테스트는 준비돼 있지만 공개 대시보드 이용·재배포 승인을
받지 않았으므로 기본값은 `KRX_ENABLED=false`다. 키 발급만으로 제3자 공개 권리가
생기는 것은 아니며, 정확한 이용 승인을 받기 전에는 배치에 연결하지 않는다.

```dotenv
KRX_ENABLED=false
KRX_API_KEY=
```

Hyperliquid 자산/주말 API와 TradingView embed에는 서버 API 키가 없다.
Hyperliquid 응답에는 짧은 TTL과 stale-if-error를 적용하며 공급자 약관과 기초
데이터 권리가 별도로 적용될 수 있음을 페이로드에 표시한다.

```
git push origin main
  → ruff + pytest
  → ARM 네이티브 빌드 → GHCR
  → OIDC로 AWS 위임 → SSM → docker compose up
  → 헬스체크 실패 시 자동 롤백
```

---

## API

| 엔드포인트 | 설명 |
|---|---|
| `GET /` | 글로벌·한국 자산, 거시, 유동성, 주말 신호 시장 모니터 |
| `GET /monitor` | 시장 모니터 별칭 |
| `GET /analytics` | 개별 티커 CAPM·MDD 한·영 분석 화면 |
| `GET /api/market/sectors` | 저장된 S&P 500 섹터 ETF의 1일·1주·1개월·1년 수익률 (레거시 opt-in) |
| `GET /api/market/assets?history=3y` | Hyperliquid `xyz` 합성 무기한선물 기반 핵심 자산 카드 |
| `GET /api/market/weekend` | 한국 주식·KOSPI 200·미국 기술주 합성 파생시장 주말 참고 신호 |
| `GET /api/market/macro?history=3y` | FRED 거시·유동성·스트레스 카드와 시계열 |
| `GET /api/market/macro/VIXCLS?history=3y` | 단일 FRED 시계열 상세 |
| `GET /api/metrics?ticker=AAPL` | 전체 지표 (레거시 opt-in) |
| `GET /api/correlation?tickers=AAPL,MSFT` | 상관계수 행렬 (레거시 opt-in, 최대 12개) |
| `GET /api/health` | 헬스체크 (DB 연결까지 확인) |
| `GET /api/status` | 저장된 티커 수, 마지막 수집 시각 |
| `GET /docs` | 자동 생성 API 문서 |

`/api/metrics` 파라미터: `horizon`(개월, 1~60) · `sims`(200~50000) ·
`drift`(historical\|zero\|capm\|custom) · `drift_value` · `lookback`(년) · `series`(bool)

`/api/market/assets`의 `history`는 UI 계약을 유지하기 위한 선택값이다. 현재
콜드 요청에서 상품별 캔들을 여러 번 호출하지 않도록 최신 컨텍스트만 제공하며,
`observations`는 비어 있고 역사적 ATH/drawdown은 추정하지 않는다.

`/api/market/weekend`의 한국 내부 가격발견 구간은 금요일 20:00~월요일 08:00
KST, XYZ100 기준 미국 기술주 구간은 금요일 17:00~일요일 18:00 ET다. 활성
세션에서는 세션 시작 직전 공식 5분 캔들 종가를 기준선으로 시도하고, 기준선을
구하지 못하면 24시간 변화율로 가장하지 않고 null로 둔다. 모든 값은 현물이나
월요일 시가 예측이 아니라 유동성이 얕을 수 있는 합성 무기한선물 참고 신호다.

상태 코드: `404` 없는 티커 · `429` 레이트리밋(요청 과다 또는 공급자 차단) ·
`422` 파라미터 오류 · `503` 저장소 연결 실패 또는 레거시 가격 경로 비활성

일반 시장 API 기본 제한은 IP당 분당 60회(`RATE_LIMIT`), 계산량이 큰 metrics와
correlation은 분당 20회(`RATE_LIMIT_HEAVY`)다. 현재 배포는 Cloudflare 프록시가
아닌 DNS-only + Caddy 구성이다. Caddy가 외부의 `X-Forwarded-For`를 덮어쓰고
`CF-Connecting-IP`를 제거한 뒤 FastAPI가 그 값을 레이트리밋 키로 사용한다.
Cloudflare 프록시를 켤 경우에는 신뢰할 프록시 범위와 헤더 재작성 규칙을 별도로
설계해야 하며, 현재 설정은 임의의 `CF-Connecting-IP`를 신뢰하지 않는다.

---

## 알고 있는 함정들

계산이 조용히 틀리기 쉬운 지점들이라 코드에 방어가 들어가 있다.

**거래시간이 어긋나는 시장.** 한국장은 미국장보다 먼저 닫히므로 삼성전자의
t일 수익률에는 S&P500의 t-1일 뉴스가 반영된다. 당일 회귀로는 베타가 **0.20**까지
떨어진다(비현실적). 전일 항을 넣은 지연보정(Dimson) 베타는 **0.76**. 두 값이 크게
갈리면 자동으로 보정치를 쓰고 UI에 표시한다. 같은 이유로 상승장/하락장 분해는
신뢰도가 낮을 때 결론을 내지 않는다. `correlation.py`에는 이 보정이 **아직 없으니**
서로 다른 시장 간 상관계수는 믿지 말 것.

**암호화폐는 연 365일 거래한다.** 전부 252일로 연율화하면 변동성과 수익률이
√(252/365)만큼 어긋나고 "1년 예측"이 실제로는 8개월이 된다. `common.py`가
관측 밀도에서 연율화 계수를 추론한다(주식 252 / 크립토 365).

**레거시 yfinance 경로는 공개 기본값에서 꺼져 있다.** 사설 환경에서 명시적으로
활성화하면 일봉 가격을 DB에 영속화하고 저장된 티커는 공급자를 다시 부르지
않는다. 처음 보는 티커의 온디맨드 수집은 클라우드 IP 차단의 영향을 받을 수
있다. 새 모니터의 핵심 자산 카드는 이 경로를 사용하지 않는다.

**휴장일의 빈 응답은 "없는 티커"가 아니다.** 증분 갱신은 마지막 저장일 이후만
요청하므로 주말·공휴일에는 정상적으로 빈 응답이 온다. 이걸 `DataUnavailable`로
처리해 네거티브 캐시에 넣으면 **배치가 일요일에 도는 것만으로 멀쩡한 종목이
404가 된다.** `data._fetch_and_store`가 증분 요청과 최초 요청을 구분한다.

**NaN은 JSON이 아니다.** 베타나 PER이 없는 종목에서 Starlette이 직렬화 중 500을
낸다. `service.sanitize()`가 응답 직전에 NaN/Inf를 null로 바꾼다.

---

## 데이터 출처와 면책

- 핵심 자산 카드와 주말 신호는 [Hyperliquid HIP-3 정보 API](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)에서
  조회한 trade.xyz 합성 무기한선물 참고값이다. 삼성전자는 원화 현물 종가가
  아니라 USD/USDC 환산 파생상품이며, 어떤 값도 현물가격·공식 지수 종가·월요일
  시초가 예측이 아니다. 유동성, 펀딩, 마크-오라클 괴리 때문에 크게 왜곡될 수
  있고 공급자 및 기초 데이터 조건이 별도로 적용될 수 있다. 외부 표시 권리는
  서면으로 확인하는 중이라 `HIP3_PUBLIC_DISPLAY_ENABLED` 게이트 뒤에 있고,
  꺼져 있으면 `/api/market/assets`와 `/api/market/weekend`가 `pending_rights`
  503을 반환한다.
- 거시·유동성 API 구조에는 FRED 어댑터가 남아 있지만 공개 배포에서는
  `FRED_ENABLED=false`다. 현행 [FRED API 이용 약관](https://fred.stlouisfed.org/docs/api/terms_of_use.html)이
  API 콘텐츠의 저장·캐시·제3자 제공을 제한하므로, 서면 허가나 허용된
  원발행기관 피드로 교체하기 전에는 값을 수집·공개하지 않는다. 플래그가 false면
  수집과 서빙이 모두 막혀 과거 DB 행도 공개되지 않는다.
- `VIXCLS`, `BAMLH0A0HYM2`, `PCOPPUSDM`은 현재 공개 화면에서
  `license_required`다. [FRED API 이용 약관](https://fred.stlouisfed.org/docs/api/terms_of_use.html)과
  각 원 제공자의 조건을 확인해야 한다.
- S&P 500 종목 히트맵은 Mulmit API가 아니라 사용자 브라우저에서 로드되는
  [TradingView 외부 위젯](https://www.tradingview.com/widget-docs/widgets/heatmaps/stock-heatmap)이다.
  위젯의 데이터·표시 조건은 TradingView 정책을 따른다.
- KRX OPEN API 어댑터는 구현돼 있지만 공개 표시·재배포 승인을 확인하기 전까지
  `KRX_ENABLED=false`다. 키 보유만으로 제3자 공개 권리가 생긴다고 가정하지 않는다.
- Yahoo/yfinance는 `/analytics`용 레거시 opt-in 경로에만 남아 있다. Yahoo는
  데이터를 재배포하지 말라고 안내하며 자동 수집과 재사용에는 별도 조건이
  적용되므로 공개 기본값에서는 비활성화한다. [Yahoo Finance 데이터 안내](https://help.yahoo.com/kb/yahoo-finance-plus/exchanges-data-providers-yahoo-finance-sln2310.html),
  [Yahoo 이용 약관](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html)

This product uses the FRED® API but is not endorsed or certified by the Federal
Reserve Bank of St. Louis.

이 도구의 출력은 **투자 조언이 아니다.** 미래 MDD와 주말 합성 신호는 확률·참고
지표이며 예언이 아니다. 투자 판단의 유일한 근거로 사용하지 말 것.
