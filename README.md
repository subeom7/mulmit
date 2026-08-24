# 물밑 · mulmit

[mulmit.com](https://mulmit.com)

한국·미국 시장의 **공개 기록**으로만 만든 시장 모니터다. 장이 닫혀 있는 시간의
합성 무기한선물 참고가, 거시·유동성·스트레스 지표, 공시(내부자·대량보유·연금·미
의원 거래), 경제 캘린더, 크립토 파생 지표, 바이오 임상·승인 기록, 종목별 재무제표와
내부자 거래를 한 사이트에서 본다. 모든 화면이 한국어와 영어를 함께 담는다.

FastAPI + 정적 HTML/JS(프레임워크 없음) + Postgres/SQLite.

| 화면 | 무엇을 보나 |
|---|---|
| `/` | 랜딩 — 한국 야간 참고가와 '지금 일어나는 일' 통합 피드 |
| `/kr` | 한국 — 야간 참고가, 코스피 지수군, ETF 보드, 주요사항보고, 국민연금·대량보유 5%, 주말 신호 |
| `/us` | 미국·글로벌 — S&P 500 히트맵, 스트레스·심리 지수, 의원 거래(PTR), 8-K, 경제 캘린더, 섹터·상관 |
| `/crypto` | 크립토 — 퍼프 시세, 김치프리미엄, 공포·탐욕, 도미넌스·스테이블코인, 펀딩·OI, 전체 시장 보드, 가스, 실현 변동성, 코인 태깅 헤드라인 |
| `/bio` | 바이오 — 임상 파이프라인(+PubMed 서지), FDA 자문위 공고, FDA 승인, 식약처 품목허가 |
| `/crypto/{심볼}` | 코인 상세 — 캔들 차트, 국면 신호(heat·direction), 업비트 상장 코인의 원화 시세·김치프리미엄, 관련 헤드라인 |
| `/analytics` | 종목 찾기 — 코인·국내·미국을 한 입력창에서 찾아 종목 화면으로 보낸다 |
| `/stock/{코드\|티커}` | 종목 화면 — 재무제표·내부자 거래·공시·보유 공시. 양국이 같은 구성이고 머리 지표만 나라가 공개하는 것에 맞춘다. 서버가 제목·설명을 렌더한다 |
| `/news` | 신호 피드 전용 페이지 — 서버 렌더(색인용) |
| `/glossary` | 용어 사전 — 이 화면들이 쓰는 말의 뜻 |
| `/monitor` | 페이지 분리 전의 통합 모니터. 페이지 레이어의 기준 구현으로 남겨 둔다 |

## 이 저장소의 제약은 기술이 아니라 권리다

**도달 가능 ≠ 재배포 가능.** 키 없이 열려 있는 API라는 사실은 그 값을 공개 화면에
다시 표시해도 된다는 뜻이 아니다. 그래서 모든 데이터 경로가 lane 게이트 뒤에 있고
코드 기본값은 전부 꺼짐이다(fail-closed). 값이 없으면 만들지 않는다 — 비슷한 다른
계열로 대체하거나 추정하지 않고 비운다. 판정과 근거는 공급자별로 등록부에 적고,
상태를 바꾸는 PR에 플래그 변경을 함께 넣는다.

- **[로드맵 · 판정표](docs/ROADMAP.md)** — 실행 순서의 **단일 진실**. 무엇이 라이브고, 무엇이 왜 막혀 있는지
- **[데이터 공급자·권리 등록부](docs/DATA_SOURCE_REGISTER.md)** — 공급자별 판정·근거·재검토일·예산
- 섹션 계획 — [사이트 분리](docs/PLAN_SITE_SPLIT.md) · [한국](docs/PLAN_KR_SECTIONS.md) · [크립토](docs/PLAN_CRYPTO_SECTION.md) · [바이오](docs/PLAN_BIO_SECTION.md)
- 문의 기록 — [크립토 소스](docs/INQUIRY_CRYPTO_SOURCES.md) · [HIP-3](docs/INQUIRY_HYPERLIQUID_TRADE_XYZ.md) · [STLFSI](docs/INQUIRY_STLOUISFED_STLFSI.md) · [미국 EOD 벤더](docs/INQUIRY_US_EOD_VENDORS.md) · [EDGAR 광고 병행](docs/INQUIRY_SEC_EDGAR_ADS.md)
- [`docs/NEXT_SESSION_HANDOFF.md`](docs/NEXT_SESSION_HANDOFF.md)는 2026-08-16 시점의 기록이다. 현재 상태는 로드맵을 본다.

공개 화면의 법적 고지는 `/privacy`(개인정보처리방침), `/terms`(이용약관),
`/disclaimer`(면책 고지)에 있다. 세 페이지 모두 KO/EN 본문을 DOM에 함께 담아
스크립트 없이도 읽히고, 어떤 데이터 lane이 닫혀 있어도 항상 200으로 응답한다.
개인정보처리방침은 boilerplate가 아니라 이 사이트가 실제로 하는 일(접속 로그,
레이트리밋용 IP, localStorage 설정, TradingView 위젯의 제3자 전달)만 적는다.
동작이 바뀌면 문서를 먼저 고친다.

이름은 **언더워터(underwater)** 에서 왔다. 낙폭 분석에서 전고점 아래에 잠겨 있는
구간을 부르는 말이고, 시작은 그 곡선을 그리는 도구였다 — "얼마나 올랐나"가 아니라
**"얼마나 잠겨 있었나"** 를 보려던 것이다.

지금은 이름이 **유래로만** 남는다. 사이트가 하는 일이 넓어져 공시·재무제표·거시·
크립토·바이오가 화면의 대부분이고, 언더워터 곡선을 그리는 화면은 없다(아래
"미래 MDD 시뮬레이션" 절). 낙폭은 국내 종목 화면 머리의 숫자 둘 — 전고점 대비와
5년 최대 낙폭 — 로 남아 있고, 미국은 가격 lane이 없어 그것도 없다. 용어 자체의
설명은 `/glossary`의 "언더워터 곡선" 항목에 있다.

```
pip install -r requirements-dev.txt
python -m uvicorn app.main:app --reload
# http://127.0.0.1:8000
```

저장소는 SQLite(`.data/stock.db`)로 자동 생성된다. 준비할 게 없다. 배포에선
`DATABASE_URL`로 Postgres를 주입한다. 로컬 기본값은 **모든 lane이 꺼진 상태**라
페이지는 뜨지만 값은 비어 있다 — 게이트를 켜려면 아래 [데이터 lane과 권리
게이트](#데이터-lane과-권리-게이트)를 본다.

PR 전에는 둘 다 통과해야 한다. 린트가 깨지면 배포 파이프라인이 조용히 멈춘다.

```
python -m pytest tests/ -q
python -m ruff check app tests scripts cli.py
```

터미널만 쓸 거라면:

```
python cli.py AAPL
python cli.py AAPL --horizon 36 --drift zero
python cli.py --corr AAPL MSFT GLD
```

---

## 미래 MDD 시뮬레이션 — 지금은 API만 남아 있다

`/api/metrics`와 그 뒤의 계산(`app/analysis/forecast.py`의 블록 부트스트랩·정규·
t분포 세 방법, 낙폭 구간, 얼스터 지수)은 그대로 있다. **화면은 2026-08-24에
지웠다.**

이유는 이 저장소의 다른 결정과 같다 — 그 화면은 `legacy_price_data` lane에
매달려 있고 그 lane은 재배포 라이선스가 없어 꺼져 있다. 즉 운영에서 이미 보이지
않는 화면이었고, 보이지 않는 2,000줄을 린트·테스트·자산 해시가 계속 끌고 다녔다.

되살리는 조건과 코드 위치(`git show 278ae61:app/static/index.html`, 관련 함수
이름)는 `docs/ROADMAP.md` §3에 적어 두었다. 조건은 **승인된 미국 가격 공급자**이고,
그때는 별도 페이지가 아니라 종목 화면 안에 양국 동형으로 붙인다.

---

## 구조

```
app/
  main.py             FastAPI 라우트 · 레이트리밋 · SEO(종목 허브, 사이트맵)
  config.py           환경변수와 lane 게이트 정의
  data_rights.py      lane 판정과 구조화된 503. 모든 공개 API가 여기를 지난다
  store.py            Postgres/SQLite 영속 저장소 (가격·거시·공시·섹션 blob)
  data.py             데이터 파사드 (저장소 우선, 공급자는 최후 수단)
  ingest.py           lane별 수집 배치 (`--migrate-macro` 등 CLI 포함)
  service.py          티커 -> 분석 페이로드 조립 + 응답 캐시

  macro_dashboard.py  거시·유동성 카드와 시계열 조립
  stress_index.py     Mulmit 유동성·스트레스 지수 (자체 산출)
  sentiment_index.py  Mulmit 시장 심리 게이지 (실험)
  market_assets.py    HIP-3 합성 자산 카드
  hip3_history.py     HIP-3 일봉 이력 — 실현 변동성·상관의 입력
  market_sectors.py   S&P 500 섹터 ETF 스냅샷 (레거시 opt-in)
  market_calendar.py  KRX·NYSE 휴장 달력
  weekend_signals.py  주말 파생시장 참고 신호
  econ_calendar.py    경제 캘린더 — FRED 릴리스 일정 + 검증된 정책회의 큐레이션
  news_feed.py        GDELT 영문 뉴스 헤드라인 — 종목·코인 닫힌 사전 태깅
  signal_feed.py      통합 신호 피드 — 공시·뉴스·급변을 시간순으로 병합

  kr_stocks.py        한국 로스터·공식 종가·지수군·ETF
  kr_overnight.py     야간 참고가 (퍼프 ↔ 마지막 공식 종가 대조)
  kr_insider.py       DART 임원·주요주주 소유상황 보고
  kr_holdings.py      DART 대량보유(5%) 보고
  kr_pension.py       국민연금 대량보유 공시
  kr_fundamentals.py  DART 주요계정 재무제표
  kr_events.py        DART 주요사항보고 속보
  kr_press.py         정부 보도자료 헤드라인 (뉴스의 한국어 축)

  insider_filings.py  SEC EDGAR Form 3·4·5
  us_fundamentals.py  SEC EDGAR XBRL 재무제표
  us_events.py        8-K 이벤트 피드 (내부자 수집 응답 재사용)
  us_ptr.py           미 하원 PTR (STOCK Act)
  fundamental_ratios.py 공시값 산술로만 만드는 재무비율 — 양국 lane 공유

  crypto_market.py    퍼프 시세·펀딩·OI·예상펀딩
  crypto_board.py     전체 시장 보드 (급등락·OI·거래대금·펀딩 극단값)
  crypto_structure.py 도미넌스·총시총·스테이블코인 공급
  crypto_kimchi.py    업비트 원화 시세와 김치프리미엄 (코인 페이지에도 붙는다)
  crypto_gas.py       가스·수수료 스트립 (운영자 RPC 계정)
  crypto_coin.py      코인 상세 — 시장 컨텍스트 + 캔들 이력
  crypto_signal.py    시장 국면 읽기 — heat 0~100, direction −100~+100
  crypto_regime.py    시장 전체 국면, 과열도·OI 시계열, 포지션 흐름, 캔들 파트 캐시

  bio.py              임상·FDA 승인·자문위 공고·식약처 품목허가 조립

  providers/          공급자 어댑터. base.py 인터페이스가 교체 지점이다
    hyperliquid  fred  nyfed  fedboard  bls  ofr  ecos  fsc  krx  yahoo
    dart  sec_edgar  house_fd  gdelt
    coinmarketcap  upbit  alternative_me  evm_rpc
    clinicaltrials  openfda  pubmed  federal_register  mfds
    http_cache.py     조건부 요청·백오프 공용 캐시

  metrics/            전부 순수 함수. 네트워크를 모른다
    basic.py          수익률, 변동성, 샤프, 소르티노
    capm.py           베타/알파, 상승장·하락장 분해
    drawdown.py       MDD, 언더워터 곡선, 낙폭 구간, 얼스터 지수
    forecast.py       미래 MDD 몬테카를로
    correlation.py    티커 간 상관계수
    common.py         연율화 계수 추론

  static/
    landing.html kr.html us.html crypto.html bio.html   페이지별 골격
    crypto-coin.html  코인 상세 템플릿 (서버가 치환)
    analytics.html    종목 찾기 (통합 검색 → 종목 화면 링크. 데이터는 그리지 않는다)
    stock.html        종목 허브 템플릿 (서버가 치환)
    monitor.html      분리 전 통합 모니터
    monitor.js        전 페이지 공용 렌더러. `window.MULMIT_PAGE`로 분기한다
    monitor.css       다크/라이트·반응형
    privacy.html terms.html disclaimer.html   법적 고지 3종
    legal.css legal.js                        위 3종 전용
    analytics.html glossary.html news.html    검색·사전·신호 피드
    search.js                                 마스트헤드 통합 검색 (전 페이지 자가 마운트)
deploy/               Caddyfile, 배포·부트스트랩 스크립트, env.example, AWS 문서
docs/                 로드맵·권리 등록부·섹션 계획·문의 기록
tests/                단위·통합 테스트 (네트워크 불필요)
```

정적 자산은 쿼리 버전(`?v=20260822-14`)으로 캐시를 깬다. `monitor.js`나
`monitor.css`를 고치면 **모든 페이지의 버전을 같이 올린다.** 한 페이지만 올리면
나머지는 옛 JS로 새 마크업을 그린다.

### 데이터 경로: 공개 lane과 레거시 분리

모든 요청이 같은 공급자를 쓰지는 않는다. 공개 화면의 핵심 경로는 Yahoo 캐시를
읽지 않는다. 긴 시계열과 공시는 배치가 저장하고, 짧은 TTL이 필요한 합성 파생상품
참고값만 요청 시점에 공개 API를 조회한다.

```
자산 카드·야간 참고가   Hyperliquid HIP-3 → 프로세스 TTL·stale 캐시 → 응답
주말 참고 신호           HIP-3 컨텍스트 + 세션 기준 캔들 → 합성 참고값
거시·유동성·스트레스     허가된 배치 → economic_series/observations → /api/market/*
한국 공식 시세·재무      FSC·DART 배치 → store → /api/kr/*
미국 공시·재무           SEC EDGAR·하원 서기국 배치 → store → /api/us/*, /api/insider/*
크립토                   HL 실시간 + CMC·업비트·RPC 배치 blob → /api/crypto/*
바이오                   ClinicalTrials·openFDA·PubMed·Federal Register·식약처 배치 → /api/bio/*
S&P 500 종목 히트맵      사용자 브라우저 → TradingView 외부 embed
섹터·상관·미국 개별분석  허용된 저장 스냅샷만 사용; 공개 기본값에서는 503
```

`LEGACY_PRICE_DATA_ENABLED=false`가 기본값이다. `true`로 바꾼 사설 환경에서만
기존 Yahoo/yfinance 배치, `/api/metrics`, `/api/correlation`,
`/api/market/sectors`를 사용한다. 응답 캐시에는 앱 버전과 마지막 거래일이
포함돼 계산 로직이나 데이터가 바뀌면 무효화된다.

### 데이터 예산

예산은 **데이터·API 구독료 월 50,000원 이내**다(2026-08-17에 30,000원에서 상향).
서버·도메인·네트워크 비용은 여기에 넣지 않는다.

**현재 구독 지출은 0원이다.** 라이브 lane은 전부 공공 데이터(공공데이터포털,
연준·BLS·OFR·SEC·하원 서기국·Federal Register·ClinicalTrials·openFDA·PubMed·
식약처), 상업 이용이 명시된 무료 티어(CoinMarketCap Basic, alternative.me),
또는 운영자 본인 계정의 무료 티어(가스 lane의 RPC)다.

무료 조회가 재배포 권리를 뜻하지는 않는다. `VIXCLS`, `BAMLH0A0HYM2`,
`PCOPPUSDM`처럼 원 제공자의 외부 표시 권한이 필요한 계열은 계약 전까지 숫자를
만들거나 우회 수집하지 않고 `license_required` 상태로 둔다. 미국 가격 데이터
재배포 최저가는 조사 결과 월 $150(Tiingo Bootstrap Pilot)로 확인돼 예산 밖이고,
개인 열람용 싼 티어를 공개 재표시에 쓰는 것은 클래스 착오라 구매하지 않는다.

---

## 데이터 lane과 권리 게이트

게이트는 **두 겹**이다. lane이 "이 공급자를 서빙해도 되는가"를, 행의
`rights_status`가 "이 계열을 서빙해도 되는가"를 답하고 둘 다 통과해야 값이 나간다.
FRED lane이 열려도 `VIXCLS`가 계속 비어 있는 이유다.

권리 플래그는 수집뿐 아니라 **서빙까지** 결정한다. lane이 꺼지면 과거에 적재된
행이 DB에 남아 있어도 API가 값을 반환하지 않고 구조화된 503과
`Cache-Control: no-store`를 돌려준다. 판정은 전부 `app/data_rights.py`에서 lane
단위로 한다. 현재 lane 상태는 `GET /api/status`의 `data_lanes`에서 확인한다.

**코드 기본값은 전부 `false`다.** 아래 "판정"은 등록부의 권리 상태이지 배포에서
켜져 있다는 뜻이 아니다. 어떤 lane이 실제로 열려 있는지는 `GET /api/status`의
`data_lanes`가 유일한 진실이다.

| lane | 게이트 (env) | 받는 것 | 권리 근거 요지 | 판정 |
|---|---|---|---|---|
| Hyperliquid HIP-3 / trade.xyz | `HIP3_PUBLIC_DISPLAY_ENABLED`, `HIP3_HISTORY_ENABLED` | 합성·자체 무기한선물 마크·펀딩·OI, 일봉 이력 | 키 없이 열려 있으나 재표시 서면 확인은 진행 중 | `pending_rights` — 게이트로 관리 |
| FRED | `FRED_ENABLED`, `FRED_API_KEY` | 미국 거시·유동성 시계열 | 지정 인용문과 **접근일**을 함께 표시, 이 시리즈 접근을 유료화하지 않음 | **조건부 승인** (2026-08-18 서면) |
| NY Fed | `NYFED_ENABLED` | SOFR·EFFR·익일물 역레포 | 약관이 자동 접근·저장·복제·배포를 **업무 목적**으로 명시 허가. 조건은 출처 문구 동반 | `approved` |
| Federal Reserve Board | `FEDBOARD_ENABLED` | H.15 금리(10Y·2Y·10Y−2Y), H.10 공식 환율 | DDP 폐지 공지가 남긴 **릴리스 페이지 XML 아카이브**를 읽는다 | `approved` (재검토 2026-11-01) |
| BLS | `BLS_ENABLED`, `BLS_API_KEY`(선택) | 실업률 | 발행물 전체가 public domain, 조건은 출처 표기뿐 | `approved` |
| OFR (미 재무부) | `OFR_ENABLED` | 금융스트레스지수 종합·범주 | 연방 저작물, 저작권 주장 없음. 재무부 인장·로고 사용 금지 | `approved` (`DS-2026-009`) |
| 한국은행 ECOS | `ECOS_ENABLED`, `ECOS_API_KEY` | 한국 거시 시계열 | 인증키를 **"영리" 이용형태로 승인**(2026-08-20) | `approved` (2026-08-20) |
| 금융위 공공데이터 | `FSC_ENABLED`, `FSC_API_KEY` | 코스피·코스닥 지수군, 전 종목 공식 종가, ETF | data.go.kr 이용허락범위 **"제한 없음"**·무료 | `approved` |
| 국민연금공단 (공공데이터포털 파일) | **게이트 없음** — 저장소 내 CSV | 국내주식 1,200종목 평가액·자산군 내 비중·지분율(연말) | data.go.kr 이용허락범위 **"제한 없음"**. 연 1회 갱신이라 API 없이 파일로 싣는다 | `approved` (`DS-2026-023`) |
| 금감원 Open DART | `DART_ENABLED`, `DART_API_KEY` | 내부자·5% 대량보유·연금·재무제표·주요사항보고 | 법정 공시 개방 API. 재배포 금지 조항 없이 허용량 제한만 | `approved` (범위 한정) |
| SEC EDGAR | `SEC_EDGAR_ENABLED`, `SEC_EDGAR_USER_AGENT` | Form 3·4·5, XBRL 재무제표, 8-K | 연방 공시 시스템. 연락처 담긴 User-Agent + 초당 10요청 상한 | `approved` (범위 한정) |
| 미 하원 서기국 PTR | `US_PTR_ENABLED` | STOCK Act 거래보고 | 법정 공시. EIGA §105(c) 고지를 응답에 동봉 | `approved` — 상원 eFD는 **보류** |
| GDELT | `GDELT_ENABLED` | 영문 뉴스 메타데이터 | 약관이 상업·재배포를 명시 허용 | `approved` (2026-08-19 조사 종결) |
| 정부 보도자료 RSS | `KR_PRESS_ENABLED` | 제목·기관·원문 링크만 | 공공기관 배포자료. 본문 재게시는 하지 않는다 | 배포 (2026-08-20, 제목·링크 한정) |
| 크립토 섹션 | `CRYPTO_SECTION_ENABLED` | `/crypto`와 `/api/crypto/*` 노출 | 퍼프 값은 HIP-3 게이트를 그대로 따른다 | 섹션 스위치 |
| alternative.me | `ALTERNATIVE_ME_ENABLED` | 크립토 공포·탐욕 지수 | 출처를 **값 바로 옆에** 표시하면 상업 이용 허용 | `approved` (`DS-2026-010`) |
| CoinMarketCap | `CMC_ENABLED`, `CMC_API_KEY` | BTC·ETH 도미넌스, 총시총, USDT·USDC 공급 | 무료 Basic 티어에 상업 이용권 포함. 출처 표시·단독 재배포 금지 | `approved` (`DS-2026-011`) |
| 업비트(두나무) | `UPBIT_ENABLED` | 원화 시세, 김치프리미엄 | 약관 §5가 허가도 금지도 하지 않음 → **운영자 위험수용 기록 후 개방** | `pending_rights` + **운영자 위험수용** (`DS-2026-012`) |
| 가스·수수료 | `CHAIN_GAS_ENABLED`, `CHAIN_RPC_*_URL` | 이더리움·Base·Arbitrum 가스 | 퍼블릭 RPC는 약관상 쓰지 않고 **운영자 본인 RPC 계정 URL을 주입** | `public_chain_state` (`DS-2026-013`) |
| 바이오 섹션 | `BIO_SECTION_ENABLED` | `/bio`와 `/api/bio/*` 노출 | 개별 소스 게이트가 따로 있다 | 섹션 스위치 |
| ClinicalTrials.gov | `CLINICALTRIALS_ENABLED` | 워치리스트 임상 갱신 | 약관 4조건(출처·최신성·처리일·수정 명시)을 응답에 동봉 | `approved` (`DS-2026-014`) |
| openFDA | `OPENFDA_ENABLED`, `OPENFDA_API_KEY`(선택) | 최근 NDA·BLA 원 신청 승인 | 공개 도메인 CC0 | `approved` (`DS-2026-015`) |
| PubMed (NCBI) | `PUBMED_ENABLED`, `NCBI_EMAIL`, `NCBI_API_KEY`(선택) | 임상별 논문 **서지만** | NCBI 정책 — tool/email 식별, 3 req/s, 야간 창. 초록 비표시 | `approved` (`DS-2026-017`, 메타데이터 한정) |
| Federal Register | `FEDERAL_REGISTER_ENABLED` | FDA 자문위원회 회의 공고 | 공개 도메인. NARA/OFR 로고·인장 사용 금지 | `approved` (`DS-2026-016`) |
| 식약처 품목허가 | `MFDS_ENABLED`, `MFDS_API_KEY`(없으면 `FSC_API_KEY`) | 최근 30일 의약품 품목허가 | data.go.kr 이용허락범위 제한 없음 | `approved` (`DS-2026-018`) |
| Coinalyze | `COINALYZE_ENABLED`, `COINALYZE_API_KEY` | 청산 집계·미결제약정 | 무료 티어 회신 대기 중 수용 범위 내 이용. 응답한 거래소 합계임을 명시 | 등록부 §3.27 `DS-2026-019` |
| YouTube Data API | `YOUTUBE_ENABLED`, `YOUTUBE_API_KEY` | 못 박은 뉴스 채널의 최근 업로드 | 저장 30일 상한(코드로 강제), 출처 표시, 플레이어 규칙. 썸네일은 URL만 나르고 바이트는 나르지 않는다 | 등록부 §3.28 `DS-2026-020` |
| 네이버 데이터랩 | `NAVER_DATALAB_ENABLED`, `NAVER_DATALAB_CLIENT_*` | 종목 검색어 관심도 | 검색 특약이 적용되지 않는 API. 무저장 설계로 캐싱 조항을 피한다 | 등록부 §3.29 |
| KRX OPEN API | `KRX_ENABLED`, `KRX_API_KEY` | — | 어댑터·테스트는 준비돼 있으나 공개 이용 승인이 없다 | `pending_rights` |
| 레거시 가격(Yahoo) | `LEGACY_PRICE_DATA_ENABLED` | 미국 일봉, 섹터 ETF, 상관 | Yahoo가 재배포하지 말라고 안내 | `private_only` |

`deploy/env.example`이 운영용 템플릿이다. 아래는 실제 값이 아니라 형태 예시다.

```dotenv
LEGACY_PRICE_DATA_ENABLED=false
HIP3_PUBLIC_DISPLAY_ENABLED=false
FRED_ENABLED=false
FRED_API_KEY=
SEC_EDGAR_ENABLED=false
SEC_EDGAR_USER_AGENT=            # 예: "Mulmit admin@example.com"
FSC_ENABLED=false
FSC_API_KEY=                     # 인코딩·디코딩 키 모두 동작
DART_ENABLED=false
DART_API_KEY=
CRYPTO_SECTION_ENABLED=false
BIO_SECTION_ENABLED=false
YOUTUBE_ENABLED=false
YOUTUBE_API_KEY=
NAVER_DATALAB_ENABLED=false
```

### 판정이 왜 이렇게 됐는가

**FRED는 "조건부 승인"이지 자유 이용이 아니다.** 2026-08-18 서면 회신으로
STLFSI4 계열의 공개 표시가 열렸다. 조건이 셋이다 — 지정 인용문을 **접근일과 함께**
표시할 것(경제 시계열은 개정되므로 접근일이 인용의 일부다), 이 시리즈에 대한
접근을 유료화하지 않을 것(광고 유무와 무관), 금지 용도 목록을 지킬 것. 그래서
`public_web=True`로 표시된 계열만 수집·서빙하고 제3자 권리 계열(`VIXCLS`,
`BAMLH0A0HYM2`, `PCOPPUSDM`)은 lane이 열려 있어도 `license_required`로 남는다.

거시 시계열은 공급자 중립 테이블(`economic_series` / `economic_observations`)에
저장한다. 계열은 내부 안정 키(`treasury_10y`)로 식별하고, 공급자 id와 공급자의 원본
id(`fred` / `DGS10`), 그리고 권리 상태를 행에 함께 담는다. 그래서 NY Fed나 BLS를
연결하는 일이 스키마 변경이 아니라 행 변경이 된다. 한 계열을 두 lane이 이름 붙일 수
있으므로 **행을 가진 공급자가 그 계열을 계속 소유한다** — FRED lane을 켜도 승인된
NY Fed 계열을 덮어쓰지 않는다. 레거시 `fred_*` 테이블에서 옮기려면:

```powershell
python -m app.ingest --migrate-macro
```

**Fed Board 경로 선택에는 이유가 있다.** Board는 Data Download Program을 폐지하고
FRED로 유도하는 중인데(1단계 2026-11-09), 같은 전환 공지에 "Historical data will
remain available for download as XML files on statistical release pages"라고 적혀
있어 DDP 질의 엔드포인트가 아니라 **릴리스 페이지 XML 아카이브**를 읽는다. 이 문장이
철회되면 lane 전체가 막히므로 등록부의 재검토일이 2026-11-01이다. 같은 lane이 H.10의
공식 환율(원·엔·위안·유로·파운드 대 달러)도 받는데, H.10은 호가 방향이 두 가지고
계열명이 유일한 단서라(`$US`가 있으면 외화당 달러) 방향을 `units`에 문장으로 적어
저장한다. 이 값들은 HIP-3 합성 FX와 별도 key(`fx_*`)다.

**Mulmit 유동성·스트레스 지수**(`/api/market/stress`)는 CNN Fear & Greed를
복제하지 않는다. 그 지수의 입력 대부분(변동성, 풋/콜, 하이일드)이 우리가 표시할
권리가 없는 것이라, 남은 것으로 만들면 심리 지수가 아니라 유동성·거시 스트레스
지수가 된다. 그래서 측정하는 것의 이름을 붙였다. 각 입력을 최근 5년 자기 이력
안의 백분위로 점수화하고 방향을 맞춰 동일 가중 평균한다. 결측 입력은 채우지 않고
제외하며, 표시할 권리가 없는 계열은 입력에서 빠진다 — **합성 지수로 withheld 계열을
세탁해 내보내지 않기 위해서다.** 입력이 3개 미만이면 지수를 아예 내지 않는다.
VIX·하이일드 카드를 숨긴 뒤의 대체 3종(OFR 스트레스, 실현 변동성, 심리 게이지)도
같은 규칙을 따르고, 실현 변동성 카드에는 "VIX 아님"을 붙인다.

DOL 신규 실업수당은 **보류**했다. 기계판독 파일은 컬럼이 `c1`~`c23`으로 익명이고
전국 계절조정 헤드라인은 HTML·PDF에만 있다. 컬럼을 추측하거나 페이지를 스크래핑하는
건 이 프로젝트가 금지한 방식이라 `initial_claims`는 빈 상태로 둔다.

**한국 공식 시세는 금융위 공공데이터 lane이다.** 원 데이터는 한국거래소가 만들지만,
금융위원회가 공공데이터로 개방하며 data.go.kr에 이용허락범위 "제한 없음", 비용
무료로 등록했다. 대가는 신선도다 — 기준일 **다음 영업일 13시 이후**에 공개되는 장
마감 확정값이라 금요일 종가는 월요일에 온다. 이 lane 위에 실시간이라고 쓴 화면을
올리지 않는다. 공식 종가는 HIP-3 합성값과 **다른 카드**에 붙는다(`samsung_exact`는
원화 마감값, `samsung`은 USD 환산 합성 무기한선물). 두 값을 한 시계열로 잇지 않는다.

같은 lane 위에 `/analytics`의 국내 종목 검색·분석이 있다. 전 종목 하루 스냅샷(약
2,900종목)을 로스터로 저장해 검색은 로컬에서만 돌고, 종목을 고르면 공식 종가 5년치로
수익률·낙폭·MDD·변동성을 계산한다. 미수집 종목은 잠금 아래에서 한 번 즉시 수집하고
이후 요청은 전부 DB 읽기다.

KRX OPEN API 어댑터와 테스트는 준비돼 있지만 공개 대시보드 이용·재배포 승인을 받지
않았으므로 `KRX_ENABLED=false`다. **FSC lane이 이걸 대신 열어 주지 않는다** — 다른
데이터셋에 대한 별개의 허락이지, KRX 승인이 다른 경로로 도착한 게 아니다.

**미국 공시 lane은 수집을 배치로만 한다.** EDGAR 목록에 없는 티커를 검색하면 즉석에서
EDGAR를 부르지 않고 `queued`로 답한 뒤 다음 주기가 가져간다. 표시할 때 시장
매수(`P`)·매도(`S`)와 부여(`A`)·파생 행사(`M`)·세금 상계(`F`)를 **절대 합산하지
않는다** — RSU 베스팅 한 건이 거대한 매매 신호처럼 보이는 것을 막기 위해서다.
하원 PTR은 전자 제출 PDF를 엄격 매칭으로만 파싱하고, 상원 eFD는 봇 차단(403)이라
**우회하지 않고 보류**한다.

**크립토에서 "규제가 적다"는 반만 맞다.** 라이선스 요금은 0이지만 거래소 약관이
공개 재표시를 명시적으로 금지하는 경우가 많다(Binance·OKX·Coinbase·Deribit·Bybit).
CoinGecko·DefiLlama·Etherscan 무료 티어는 비상업이다. 그래서 이 섹션은 (a) 재표시
조건이 명시된 소스(alternative.me, CoinMarketCap Basic), (b) 이미 게이트가 있는
HIP-3, (c) 운영자 본인 계정으로 읽는 체인 상태만 쓴다. 업비트는 약관이 허가도 금지도
하지 않아 `pending_rights`였고, 운영자 위험수용을 등록부에 기록한 뒤 열었다. 가스
lane은 퍼블릭 RPC를 쓰지 않는다 — 검토한 엔드포인트들이 재배포를 금지하거나
"not suitable for production traffic"이라고 안내하기 때문이고, 대신 운영자 RPC 계정
URL을 env로 주입한다(URL에 키가 들어가므로 응답·로그에 절대 싣지 않는다).
Deribit DVOL과 Coinalyze 청산 집계는 문의 회신(기한 2026-09-16) 전까지 코드가 없다.

**바이오는 전부 공공 기록이지만 조건이 서로 다르다.** ClinicalTrials.gov는 약관
4조건(출처·데이터 최신성·처리일·수정 여부 명시)을 응답에 동봉해야 하고, openFDA는
CC0, Federal Register는 공개 도메인이되 NARA/OFR 로고·인장을 쓸 수 없다. PubMed는
NCBI 정책에 따라 tool/email로 신원을 밝히고 3 req/s·야간 창을 지키며 **서지만**
가져온다(초록은 표시하지 않는다). 식약처는 data.go.kr 계정 단위로 키가 발급돼
`MFDS_API_KEY`가 비면 `FSC_API_KEY`를 그대로 쓴다. 한국어 표시명과 상장 라벨은
원 데이터가 아니라 **Mulmit이 붙인 참고 라벨**이라고 화면에 적는다.

---

## 배포

EC2 한 대 + GitHub Actions. SSH를 열지 않고 SSM으로 배포한다.
자세한 절차와 비용은 **[deploy/README.md](deploy/README.md)**.

```
git push origin main
  → ruff + pytest
  → ARM 네이티브 빌드 → GHCR
  → OIDC로 AWS 위임 → SSM → docker compose up
  → 헬스체크 실패 시 자동 롤백
```

main 머지가 곧 배포다. **린트나 테스트가 실패하면 파이프라인이 조용히 멈추므로**
PR 전에 `ruff`와 `pytest`를 로컬에서 돌린다. 게이트 값은 이미지가 아니라 서버
`.env`에 있으므로, lane을 켜고 끄는 것은 재배포가 아니라 운영자 작업이다.

---

## API

문서는 `/docs`(자동 생성)에 있다. 모든 응답은 lane 게이트를 통과한 값만 담고,
닫힌 lane은 구조화된 503(`code`, `status`, `message`)과 `Cache-Control: no-store`를
돌려준다.

| 엔드포인트 | 설명 |
|---|---|
| `GET /api/health` | 헬스체크 (DB 연결까지 확인) |
| `GET /api/search?q=` | 통합 검색 — 코인·국내 상장·미국 티커 로스터. 저장된 로스터만 읽는다 |
| `GET /api/status` | 저장 티커 수, 마지막 수집 시각, **lane별 상태(`data_lanes`)** |
| `GET /api/market/assets?history=3y` | HIP-3 합성 무기한선물 기반 핵심 자산 카드 |
| `GET /api/market/weekend` | 한국 주식·KOSPI 200·미국 기술주 주말 참고 신호 |
| `GET /api/market/macro?history=3y` | 거시·유동성 카드와 시계열 |
| `GET /api/market/macro/{series_id}` | 단일 거시 계열 상세 |
| `GET /api/market/stress` | Mulmit 유동성·스트레스 지수 (산식·입력 동봉) |
| `GET /api/market/sentiment` | Mulmit 시장 심리 게이지 (실험) |
| `GET /api/market/sectors` | S&P 500 섹터 ETF 기간별 수익률 (레거시 opt-in) |
| `GET /api/kr/search?q=` | 한국 종목 검색 (로컬 로스터) |
| `GET /api/kr/stock/{code}` | 한국 종목 분석 — 공식 종가 5년, 낙폭·변동성 |
| `GET /api/kr/indices` | 코스피 지수군·섹터 지수 장 마감값 |
| `GET /api/kr/etf` | ETF 보드 |
| `GET /api/kr/overnight` | 야간 참고가 (퍼프 ↔ 마지막 공식 종가) |
| `GET /api/kr/fundamentals/{code}` | DART 주요계정 재무제표·비율 |
| `GET /api/kr/insider/{code}` | 임원·주요주주 소유상황 보고 |
| `GET /api/kr/holdings` | 대량보유(5%) 보고 |
| `GET /api/kr/pension` | 국민연금 대량보유 공시 |
| `GET /api/kr/pension-portfolio` | 국민연금 국내주식 포트폴리오(연말 스냅샷, 저장소 내 파일) |
| `GET /api/kr/events` | DART 주요사항보고 속보 |
| `GET /api/kr/press` | 정부 보도자료 헤드라인 |
| `GET /api/kr/search-interest` | 종목 검색어 관심도 (네이버 데이터랩, 무저장) |
| `GET /api/us/fundamentals/{ticker}` | SEC XBRL 재무제표·비율 (`concepts_used` 동봉) |
| `GET /api/us/events` | 8-K 이벤트 피드 |
| `GET /api/us/overnight` | 미국 대형주 장 밖 참고 신호 — 정규장이 닫혔을 때만 |
| `GET /api/us/ptr` | 미 하원 의원 거래(STOCK Act) — §105(c) 고지 동봉 |
| `GET /api/insider/{ticker}` | SEC Form 3·4·5 (거래 성격별 분리) |
| `GET /api/crypto/overview` | 퍼프 시세 카드 |
| `GET /api/crypto/board` | 전체 시장 보드 — 24h 급등락·OI·거래대금·펀딩 극단값 |
| `GET /api/crypto/structure` | 도미넌스·총시총·스테이블코인 공급 |
| `GET /api/crypto/sentiment` | 크립토 공포·탐욕 지수 |
| `GET /api/crypto/volatility` | 실현 변동성(√365)과 합성자산 상관 |
| `GET /api/crypto/kimchi` | 업비트 원화 시세·김치프리미엄 |
| `GET /api/crypto/gas` | 이더리움·Base·Arbitrum 가스 |
| `GET /api/crypto/coin/{symbol}` | 코인 상세 — 시장 컨텍스트, 캔들, 국면 신호(`signal`) |
| `GET /api/crypto/regime` | 시장 전체 국면 — 쏠림 폭·상승 폭·기준 코인 과열도·공포탐욕 |
| `GET /api/crypto/liquidations` | 강제청산 24시간 집계·미결제약정 (응답한 거래소 합계) |
| `GET /api/crypto/news?symbol=&limit=` | 코인 태그가 붙은 헤드라인 (저장된 GDELT 블롭) |
| `GET /api/bio/trials` | 워치리스트 임상 갱신 (+PubMed 서지) |
| `GET /api/bio/fda` | 최근 FDA 원 신청 승인 (NDA·BLA) |
| `GET /api/bio/adcomm` | FDA 자문위원회 회의 공고 |
| `GET /api/bio/mfds` | 식약처 최근 의약품 품목허가 |
| `GET /api/calendar` | 경제 캘린더 (지표 릴리스 + 정책회의) |
| `GET /api/news/videos` | 못 박은 뉴스 채널의 최근 업로드 — 제목·채널·시각·썸네일 URL. 플레이어는 클릭 전 로드되지 않는다 |
| `GET /api/feed` | 통합 신호 피드 (공시·뉴스·급변 시간순) |
| `GET /api/news` | 영문 뉴스 헤드라인 |
| `GET /api/metrics?ticker=AAPL` | 전체 분석 지표 (레거시 opt-in) |
| `GET /api/correlation?tickers=AAPL,MSFT` | 상관계수 행렬 (레거시 opt-in, 최대 12개) |
| `GET /api/stats/traffic` | 접속 통계 요약 |
| `POST /api/presence`, `POST /api/pageview` | 익명 접속 하트비트·페이지뷰 비콘 |

`/api/metrics` 파라미터: `horizon`(개월, 1~60) · `sims`(200~50000) ·
`drift`(historical/zero/capm/custom) · `drift_value` · `lookback`(년) · `series`(bool)

`/api/market/weekend`의 한국 내부 가격발견 구간은 금요일 20:00~월요일 08:00
KST, XYZ100 기준 미국 기술주 구간은 금요일 17:00~일요일 18:00 ET다. 활성
세션에서는 세션 시작 직전 공식 5분 캔들 종가를 기준선으로 시도하고, 기준선을
구하지 못하면 24시간 변화율로 가장하지 않고 null로 둔다.

`/api/presence`는 익명 무작위 id의 30초 하트비트로 90초 창의 **열린 브라우저 수**를
센다. 사람 수가 아니며 화면에도 그렇게 적는다.

상태 코드: `404` 없는 티커·종목 · `429` 레이트리밋(요청 과다 또는 공급자 차단) ·
`422` 파라미터 오류 · `503` 저장소 연결 실패 또는 **닫힌 lane**

일반 API 기본 제한은 IP당 분당 60회(`RATE_LIMIT`), 계산량이 큰 metrics와
correlation은 분당 20회(`RATE_LIMIT_HEAVY`)다. 현재 배포는 Cloudflare 프록시가
아닌 DNS-only + Caddy 구성이다. Caddy가 외부의 `X-Forwarded-For`를 덮어쓰고
`CF-Connecting-IP`를 제거한 뒤 FastAPI가 그 값을 레이트리밋 키로 사용한다.
Cloudflare 프록시를 켤 경우에는 신뢰할 프록시 범위와 헤더 재작성 규칙을 별도로
설계해야 하며, 현재 설정은 임의의 `CF-Connecting-IP`를 신뢰하지 않는다.

---

## 알고 있는 함정들

값이 조용히 틀리기 쉬운 지점들이라 코드에 방어가 들어가 있다. 대부분 실측에서
나왔다.

**거래시간이 어긋나는 시장.** 한국장은 미국장보다 먼저 닫히므로 삼성전자의
t일 수익률에는 S&P500의 t-1일 뉴스가 반영된다. 당일 회귀로는 베타가 **0.20**까지
떨어진다(비현실적). 전일 항을 넣은 지연보정(Dimson) 베타는 **0.76**. 두 값이 크게
갈리면 자동으로 보정치를 쓰고 UI에 표시한다. 같은 이유로 상승장/하락장 분해는
신뢰도가 낮을 때 결론을 내지 않는다. `correlation.py`에는 이 보정이 **아직 없으니**
서로 다른 시장 간 상관계수는 믿지 말 것.

**암호화폐는 연 365일 거래한다.** 전부 252일로 연율화하면 변동성과 수익률이
√(252/365)만큼 어긋나고 "1년 예측"이 실제로는 8개월이 된다. `common.py`가
관측 밀도에서 연율화 계수를 추론한다(주식 252 / 크립토 365).

**XBRL 재무제표에는 조용한 함정이 셋 있다.** ① 회사마다 같은 항목에 다른 태그를
쓰고(`Revenues` vs `RevenueFromContractWithCustomer…`), 심지어 **쓰던 태그를 중간에
버린다**(NVIDIA는 그 태그의 마지막 기간이 2022년이었다). "존재하는 첫 태그"를 고르면
몇 년 묵은 표가 되므로 사다리의 태그 전부에서 **마지막 보고 기간을 비교해** 고르고,
실제 사용한 태그를 `concepts_used`로 응답에 싣는다. ② 10-Q의 흐름 항목은 분기값과
연초누계(YTD)가 한 시계열에 섞여 오므로 기간 길이로 갈라낸다. ③ `fy`는 회계연도가
아니라 **제출 연도**라 성장률을 `fy`로 매칭하면 어긋난 사례가 나온다 — 기간 종료
연도로 맞춘다.

**지수명은 유일하지 않다.** FSC 지수 데이터에서 "IT 서비스" 같은 이름이 KOSPI와
KOSDAQ 시리즈에 동시에 존재한다. 이름만으로 집으면 다른 시장의 지수가 섞이므로
분류를 고정해서 조회한다.

**H.15/H.10 아카이브의 센티넬.** 관측치의 `OBS_STATUS`가 `A`가 아니면 그 값은
`-9999` 같은 센티넬이고 날짜는 미국 공휴일이다. 그대로 저장하면 금리가 마이너스
1만 퍼센트가 된다. 그리고 아카이브 하나에 릴리스의 모든 계열이 들어 있으므로
계열마다 받지 않고 한 번만 받아 재사용한다. 10Y−2Y는 **양쪽이 모두 게시한 날짜**로만
계산한다 — 한쪽만 있는 날을 이월값과 짝지으면 없는 관측을 지어내는 셈이다.

**단위는 공급자마다 다르다.** 뉴욕 연준의 역레포는 **달러 단위**인데 FRED의
`RRPONTSYD`는 십억 달러다. 두 값을 같은 축에 두면 안 된다. 공급자가 준 원 단위를
그대로 저장하는 것이 공급자 중립 테이블의 목적이다.

**같은 이름의 필드가 다른 것을 뜻하기도 한다.** CoinMarketCap 글로벌 메트릭의
`stablecoin_24h_percentage_change`(그리고 같은 이름의 defi·derivatives 필드)는
시가총액 변화가 아니라 **24시간 거래대금 변화**다. 실측에서 +22.6%가 나왔는데 같은
시각 스테이블 시총은 $282B로 거의 움직이지 않았다. 시총 카드에 붙이면 조용히 틀린다.

**펀딩 APR에는 0이 아닌 바닥이 있다.** Hyperliquid 펀딩에는 8시간당 0.01%의 고정
이자 성분이 있어 **프리미엄이 0인 시장도 +10.95% APR**을 찍는다(유동 110개 시장의
|APR| 최솟값 실측 10.9%). 그래서 쏠림·과열을 판단할 때 |APR|을 그대로 점수화하면
중립인 시장까지 전부 과열로 잡힌다. 기준선(+10.95%)과의 **거리**로 재야 한다 —
이 보정으로 BTC 75→60, HYPE 80→50으로 내려가고 실제로 쏠린 책(ZEC +259%,
XMR +330%)만 100에 남았다.

**data.go.kr 키는 두 형태로 발급된다.** 인코딩 키(`%2F`)와 디코딩 키(`/`)가 있고,
이미 인코딩된 키를 한 번 더 인코딩하면 `%252F`가 되어 "등록되지 않은 서비스키"로
거절된다. 오류 메시지가 인코딩을 가리키지 않아 원인을 찾기 어렵다. 어느 쪽을 넣어도
같은 형태로 정규화한다.

**휴장일의 빈 응답은 "없는 티커"가 아니다.** 증분 갱신은 마지막 저장일 이후만
요청하므로 주말·공휴일에는 정상적으로 빈 응답이 온다. 이걸 `DataUnavailable`로
처리해 네거티브 캐시에 넣으면 **배치가 일요일에 도는 것만으로 멀쩡한 종목이
404가 된다.** `data._fetch_and_store`가 증분 요청과 최초 요청을 구분한다.

**NaN은 JSON이 아니다.** 베타나 PER이 없는 종목에서 Starlette이 직렬화 중 500을
낸다. `service.sanitize()`가 응답 직전에 NaN/Inf를 null로 바꾼다.

**뉴스 태깅은 오태깅보다 무태깅이 낫다.** 헤드라인의 종목·코인 매칭은 닫힌 사전과
단어 경계로만 한다. 그런데 티커 중에는 평범한 영어 단어이거나 다른 기관을 가리키는
것이 있다 — `SOL`(스페인어 "해"), `LINK`, `SUI`, `HYPE`, `ETH`(취리히 공대), 그리고
`DOGE`는 2025년 이후 미 정부효율부를 더 자주 뜻한다("DOGE cuts 2,000 federal jobs").
이런 심볼은 사전에서 아예 빼고 정식 명칭(`Dogecoin`, `Chainlink`, `Solana`)으로만
잡는다. 한 건 더 태깅하는 이득보다 엉뚱한 종목 칩이 붙는 손해가 크다.

**표본 하나는 변화가 아니다.** 시계열을 막 쌓기 시작한 lane에서 직전 값이 없는데
차이를 계산하면 "변화 0.0%"가 나가고, 화면에서는 "움직이지 않았다"로 읽힌다.
표본이 부족하면 0을 내지 말고 `status: collecting`으로 답한다.

**임포트 시점에 DB를 건드리는 테스트는 CI에서만 깨진다.** 테스트 모듈 최상단에서
`news_feed._tags_for()` 같은 함수를 부르면 수집(collection) 단계에 로스터 조회가
일어나고, 빈 DB로 도는 CI에서 테스트가 아니라 **수집 자체가** 실패한다. 로컬에서는
DB가 채워져 있어 재현되지 않는다. 이런 호출은 픽스처 안으로 넣어 지연 생성한다.

**날짜를 고정한 테스트 픽스처는 언젠가 깨진다.** 실제로 고정 날짜 행이 만료되어
배포가 막힌 적이 있다. 캘린더·매크로 픽스처는 오늘 기준 상대 날짜로 만든다.

---

## 데이터 출처와 면책

- 자산 카드·야간 참고가·주말 신호는 [Hyperliquid 정보 API](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)에서
  조회한 **합성 무기한선물 참고값**이다. 삼성전자는 원화 현물 종가가 아니라
  USD/USDC 환산 파생상품이며, 어떤 값도 현물가격·공식 지수 종가·월요일 시초가
  예측이 아니다. 유동성, 펀딩, 마크-오라클 괴리 때문에 크게 왜곡될 수 있고 공급자
  및 기초 데이터 조건이 별도로 적용될 수 있다. 외부 표시 권리는 서면 확인 중이라
  `HIP3_PUBLIC_DISPLAY_ENABLED` 게이트 뒤에 있고, 꺼져 있으면 관련 API가
  `pending_rights` 503을 반환한다.
- 거시·유동성 값은 FRED(조건부 승인), 뉴욕 연준, 연준 이사회 통계 릴리스, BLS,
  미 재무부 OFR, 한국은행 ECOS에서 온다. FRED 계열은 지정 인용문과 **접근일**을
  함께 표시하며, 이 시리즈에 대한 접근을 유료화하지 않는다.
  [FRED API 이용 약관](https://fred.stlouisfed.org/docs/api/terms_of_use.html)
- `VIXCLS`, `BAMLH0A0HYM2`, `PCOPPUSDM`은 원 제공자(Cboe·ICE 등)의 라이선스
  영역이라 공개 화면에서 `license_required`로 비워 두고, 대체 지표(OFR 금융스트레스,
  실현 변동성, Mulmit 심리 게이지)를 대신 표시한다. 대체 지표는 원 지수의 근사치가
  아니며 그렇게 표시하지 않는다.
- 한국 공식 종가·지수·ETF는 금융위원회 공공데이터(data.go.kr)의 **다음 영업일
  확정값**이다. 실시간 시세가 아니다. 공시는 금융감독원 Open DART, 미국 공시는
  SEC EDGAR와 미 하원 서기국 재정공시(§105(c) 고지 동봉)에서 온다.
- 크립토 섹션의 공포·탐욕 지수는 [alternative.me](https://alternative.me/crypto/fear-and-greed-index/),
  도미넌스·총시총·스테이블코인 공급은 CoinMarketCap(무료 Basic, 출처 표시 조건),
  원화 시세는 업비트, 가스는 운영자 RPC 계정으로 읽은 체인 상태다. 코인 상세의
  캔들과 시장 국면 신호(heat·direction)는 같은 Hyperliquid 스냅샷에서 자체
  계산한 값이고, **매매 신호가 아니라 조건 서술**이라 모든 입력과 기여도를 함께
  표시한다. 외부 차트 위젯이나 제3자 가격 피드를 끼워 넣지 않는다. 헤드라인은
  GDELT lane의 제목·출처·링크뿐이고, 붙는 코인 칩은 뉴스 공급자가 준 것이 아니라
  Mulmit의 닫힌 사전이 제목에서 잡아낸 참고 라벨이다.
- 바이오 섹션은 ClinicalTrials.gov(약관 4조건 동봉), openFDA(CC0), PubMed(서지만),
  Federal Register, 식약처 공공데이터의 **공개 기록 그대로**다. 임상 등록 정보는
  결과가 아니고, 한국어 표시명·상장 라벨은 Mulmit이 붙인 참고 라벨이다.
- S&P 500 종목 히트맵은 Mulmit API가 아니라 사용자 브라우저에서 로드되는
  [TradingView 외부 위젯](https://www.tradingview.com/widget-docs/widgets/heatmaps/stock-heatmap)이다.
  위젯의 데이터·표시 조건은 TradingView 정책을 따른다.
- KRX OPEN API 어댑터는 구현돼 있지만 공개 표시·재배포 승인을 확인하기 전까지
  `KRX_ENABLED=false`다. 키 보유만으로 제3자 공개 권리가 생긴다고 가정하지 않는다.
- Yahoo/yfinance는 `/analytics`의 미국 종목용 레거시 opt-in 경로에만 남아 있다.
  Yahoo는 데이터를 재배포하지 말라고 안내하며 자동 수집과 재사용에는 별도 조건이
  적용되므로 공개 기본값에서는 비활성화한다. [Yahoo Finance 데이터 안내](https://help.yahoo.com/kb/yahoo-finance-plus/exchanges-data-providers-yahoo-finance-sln2310.html),
  [Yahoo 이용 약관](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html)

This product uses the FRED® API but is not endorsed or certified by the Federal
Reserve Bank of St. Louis.

이 도구의 출력은 **투자 조언이 아니다.** 미래 MDD, 주말 합성 신호, 스트레스·심리
지수, 크립토 국면 신호는 확률·참고 지표이며 예언이 아니다. 임상·승인 기록은 성패 예측이나 주가 해석이
아니다. 투자 판단의 유일한 근거로 사용하지 말 것.

## 라이선스

코드는 [`LICENSE`](LICENSE)를 따른다. 저장소가 공개돼 있다는 사실이 이용 허락은
아니다 — 이 프로젝트가 데이터에 대해 지키는 원칙과 같다.

라이선스는 **코드에만** 적용된다. 화면에 나오는 수치는 이 저장소가 재라이선스할
수 있는 것이 아니고 각 원 발행기관의 조건을 따른다. fork해도 그 안의 데이터
lane을 쓸 권리는 따라오지 않는다. 권리는 코드가 아니라 각 공급자와의 관계에서
나오고, 그 관계의 현재 상태는
[데이터 공급자·권리 등록부](docs/DATA_SOURCE_REGISTER.md)에 공급자별로 적혀 있다.
