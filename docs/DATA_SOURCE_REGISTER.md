# Mulmit 데이터 공급자·권리 등록부

작성 기준일: 2026-08-16 (Asia/Seoul)  
대상 서비스: <https://mulmit.com/>  
예산 기준: 데이터/API 구독료 월 50,000원 이내(2026-08-17 30,000원에서 상향, 사용자 확인), 서버·도메인 비용 제외

이 문서는 Mulmit이 어떤 데이터를 어디서 받아 어떤 조건으로 표시할 수 있는지 기록하는 운영 원장이다. API가 기술적으로 열려 있다는 사실과 공개 웹 재표시 권리는 별개다. 법률 자문이 아니며, 실제 활성화 결정은 공급자 또는 원 권리자의 서면 답변과 최신 약관을 기준으로 한다.

비밀키, 계약서 원문, 담당자 개인정보, 비공개 견적은 이 파일에 넣지 않는다. 그런 자료는 접근 통제된 별도 보관소에 두고 여기에는 문서 식별자와 승인 범위만 기록한다.

## 1. 상태 정의

| 상태 | 뜻 | 공개 API/화면 동작 |
|---|---|---|
| `approved` | 현재 사용 방식에 대한 근거가 확인됨 | 승인 범위 안에서만 표시 |
| `provider_widget` | 공급자가 직접 렌더링하는 공식 위젯만 허용 | iframe/widget만 표시하고 숫자를 추출하지 않음 |
| `pending_rights` | 기술 연결은 가능하지만 외부 표시 권리가 미확인 | 기본 비활성, 값 비공개. UI는 `license_required`나 `missing`이 아니라 `권리 확인 중`으로 표시 |
| `pending_review` | 후보 공급자이며 정확한 endpoint·약관 검토 전 | 구현·수집 시작 금지 |
| `license_required` | 별도 계약 또는 원 권리자 허가가 필요 | 값·변화·관측치·차트 모두 비움 |
| `private_only` | 개인/사설 분석 범위로만 유지 | 공개 배포에서는 503 또는 disabled |
| `disabled` | 사용하지 않기로 결정했거나 대체 완료 | 네트워크 호출과 공개 값 모두 없음 |

상태는 공급자 전체가 아니라 사용 사례별로 판정한다. 예를 들어 화면에 위젯을 넣는 권리와 서버가 같은 값을 저장해 자체 API로 반환하는 권리는 서로 다를 수 있다.

Mulmit의 `/api/market/*`는 인증 없이 열려 있으므로 누구나 응답 JSON을 그대로
내려받아 저장할 수 있다. “CSV 내보내기 버튼이 없다”와 “데이터를 다운로드할 수
없다”는 다른 말이다. 공급자에게 문의할 때는 전용 다운로드 UI가 없다는 사실이
아니라, 값이 공개 JSON 엔드포인트로 나간다는 사실을 그대로 적는다.

## 2. 공개 활성화 필수 조건

하나라도 확인되지 않으면 `approved`로 바꾸지 않는다.

- 서비스 형태: 로그인 없는 공개 웹사이트
- 사용자 범위: 불특정 다수와 예상 지역
- 데이터 종류: 실시간, 지연, EOD, 역사 시계열, 메타데이터
- 표시 방식: 카드, 차트, 그리고 브라우저가 직접 호출할 수 있는 **공개 JSON API**로의 전달
- 저장 방식: DB 저장 기간, 프로세스 캐시 TTL, stale fallback
- 가공 방식: 변화율, drawdown, 상관관계, 섹터 집계, 합성 신호
- attribution: 공급자명, 원 발행기관, 링크, 로고 또는 고정 문구
- 상업 범위: 현재 비상업, 향후 광고·후원·유료화 가능성
- 하위 권리: 거래소·지수 제공자·원 기초 데이터의 별도 조건
- 종료 처리: 계약 만료, 약관 변경, 키 정지 시 fail-closed 동작

## 3. 현재 공급자 결정표

### 3.1 Hyperliquid HIP-3 / trade.xyz

| 항목 | 기록 |
|---|---|
| 내부 ID | `hyperliquid_hip3_trade_xyz` |
| 현재 상태 | `pending_rights` |
| 코드 위치 | `app/providers/hyperliquid.py`, `app/market_assets.py`, `app/weekend_signals.py` |
| 현재 사용 | `xyz`/`mkts` meta/context, mark, oracle, funding, OI, 24h notional, 일부 5분 기준 캔들, **자산 카드 일봉 이력(`candleSnapshot` 1d, 1년, 6시간 주기 — 2026-08-21부터, `app/hip3_history.py`)** |
| 기술 비용 | API 키·구독료 없음 |
| 캐시 | 자산 30초/300초 stale, 주말 5분/30분 stale, 프로세스 로컬. 일봉 이력은 report blob(`hip3_history_daily_v1`) 1개, 서빙 TTL 7일 |
| 공개 결정 | 서면 확인 전 권리 게이트 추가가 최우선 |
| 표시 경계 | 합성 무기한선물 참고값이며 현물·공식 지수 종가·월요일 예측이 아님 |
| 상장 주체 구분 | `xyz:` 접두사는 trade.xyz가 HIP-3로 배포한 상품, 접두사 없는 심볼(`BTC`)은 Hyperliquid 자체 DEX 상품이다. 같은 API·같은 게이트를 쓰지만 publisher가 다르므로 응답에서 구분한다 |
| 공식 근거 | [Hyperliquid info API](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint), [rate limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits), [trade.xyz API](https://docs.trade.xyz/api/overview), [Korea products](https://docs.trade.xyz/asset-directory/korea), [trade.xyz Terms](https://trade.xyz/terms) |

확인이 필요한 질문:

1. 공개 웹에 원 응답의 일부를 재표시해도 되는가?
2. Mulmit 서버가 짧게 캐시하고 브라우저용 JSON API로 전달해도 되는가?
3. 변화율·세션 기준 변화·가중 합성 신호를 계산해도 되는가?
4. trade.xyz가 사용하는 한국 주식·지수 입력 데이터의 외부 표시 권리까지 포함되는가?
5. 광고가 붙거나 서비스가 유료화되면 조건이 달라지는가?

권장 fail-closed 설정:

```dotenv
HIP3_PUBLIC_DISPLAY_ENABLED=false
```

서면 승인 전에는 `/api/market/assets`와 `/api/market/weekend`가 `pending_rights` 또는 구조화된 503을 반환한다(구현 완료). 공개 API 접근 자체를 재표시 허가로 기록하지 않는다.

문의 초안은 [`docs/INQUIRY_HYPERLIQUID_TRADE_XYZ.md`](INQUIRY_HYPERLIQUID_TRADE_XYZ.md)에 있다. 수신처가 **둘**임에 주의한다 — `xyz:` 상품은 trade.xyz가, 접두사 없는 `BTC`는 Hyperliquid가 상장했다. 양쪽에 각각 보내고 회신을 별도 `decision_id`로 기록한다. 확인된 주소는 XYZ Ltd `legal@xyzltd.xyz`(Terms §7.3·§9.3·§10.6), Hyperliquid Corp. `support@hyperliquid.zendesk.com`(Terms §11.3)다.

**2026-08-17 약관 정독 결과 — 위험의 위치가 바뀌었다.** 양쪽 약관을 실제로 읽어
보니 규율 대상이 **인터페이스**이고 프로토콜 데이터가 아니다.

- XYZ Ltd Terms §7.1: “the Protocol is not subject to our control, and
  accordingly, **no intellectual property rights are granted to the Protocol**”
- XYZ Ltd Terms §4.1.5: 스크래핑 금지의 대상이 “content or information **from
  the Interface**”다. Mulmit은 `app.trade.xyz` 화면이 아니라
  `api.hyperliquid.xyz/info`를 호출한다
- Hyperliquid Corp. Terms §1.1–1.2: “**does not own, control, or operate
  Hyperliquid**”, HIP-3 시장은 “not reviewed, verified, or approved by the
  Company”

즉 두 약관 모두 데이터 재배포를 **금지하지 않는다.** 동시에 **허가하지도 않는다.**
침묵을 허가로 읽지 않는다는 이 등록부의 원칙은 그대로다.

바뀐 것은 우선순위다. 실제 위험은 두 회사가 아니라 **기초 자산의 원 권리자** 쪽에
있다. XYZ Ltd Terms §1.4가 “data partners, oracles”를 Third-Party Service로
명시하고 “owned by their respective licensors … comply with all terms”를 요구하는데,
`xyz:KR200`·`xyz:SMSN`의 기초는 한국 주식·지수다. 문의 본문에서 이 질문을 0번으로
올린 이유다.

`HIP3_PUBLIC_DISPLAY_ENABLED=true`라는 현재 결정은 유지한다. 이 정독이 근거를
약화시키지 않고 오히려 명시적 금지가 없음을 확인했지만, 그것이 승인은 아니므로
`recheck_at: 2026-09-16`도 그대로다.

**2026-08-21 개정 — 무응답의 의미를 바꾼다.** 발송(08-17) 후 Hyperliquid Corp.는
"permissionless, 공개 API는 누구나 조회 가능, HIP-3 피드는 xyz에 문의"라고 답했고
XYZ Ltd는 무응답이다. 원래 기록은 "재검토일까지 회신이 없으면 공개값을 false로
되돌린다"였는데, 이 규칙대로면 광고 출시 직후 자산 카드 전부를 꺼야 한다. 저장소
소유자는 다음으로 개정했다:

- **명시적 거절 → 즉시 OFF** (`HIP3_PUBLIC_DISPLAY_ENABLED=false`, 이력 블롭 삭제).
- **무응답 → 운영자 위험 수용 계속.** 근거: 양사 약관 모두 재배포를 금지하지 않음,
  XYZ §7.1은 프로토콜 데이터에 IP를 주장하지 않음, Hyperliquid 공식 채널의
  "permissionless" 답변, 전 카드의 합성·비현물 표기와 권리 고지. `recheck_at`은
  "자동 OFF일"이 아니라 "재검토일"이다.
- **이력 저장도 같은 위험 수용으로 연다** (`historical_storage: true`). 별도 게이트
  `HIP3_HISTORY_ENABLED`(기본 false, 서버 .env에서만 true), `candleSnapshot` 1d·1년·
  6시간 주기, 자산당 가중치 약 26(20 + 366/60)·11자산 ≈ 290/회로 한도(1,200/분)의
  한참 아래. 요청 경로는 저장 블롭만 읽는다(라이브 캔들 호출 없음). 거절 회신이
  오면 플래그 하나로 끄고 블롭을 지운다.
- 재발송 검토일 2026-08-31은 유지한다.

```yaml
decision_id: DS-2026-001
provider_id: hyperliquid_hip3_trade_xyz
status: pending_rights
reviewed_at: 2026-08-16
reviewer: repository owner
evidence_type: official_terms
evidence_reference: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
approved_scope:
  public_display: unconfirmed
  server_json_relay: unconfirmed
  cache_ttl_seconds: 30
  stale_seconds: 300
  historical_storage: true   # 2026-08-21 개정: 일봉 1년, HIP3_HISTORY_ENABLED 별도 게이트
  derived_metrics: unconfirmed
  advertising: unconfirmed
attribution: "Hyperliquid HIP-3 / trade.xyz"
expires_at: null
recheck_at: 2026-09-16
notes: >
  코드 기본값은 HIP3_PUBLIC_DISPLAY_ENABLED=false, HIP3_HISTORY_ENABLED=false.
  서면 답변 도착 전까지 현행 공개 화면과 일봉 이력을 유지하기로 저장소 소유자가
  결정하여 서버 .env에서만 둘 다 true로 둔다. 이는 승인 근거가 아니라 명시적으로
  기록된 운영자 위험 수용이다. 2026-08-21 개정: 명시적 거절 회신이 오면 즉시
  false로 되돌리고 이력 블롭을 지운다. 무응답은 OFF 사유가 아니며 recheck_at은
  재검토일이다(근거는 바로 위 "2026-08-21 개정" 단락).
```

**2026-08-21 크립토 섹션(Phase 1) — 같은 게이트, 네이티브 퍼프.** `/api/crypto/overview`는
접두사 없는 Hyperliquid 자체 상장 퍼프(BTC·ETH·SOL·XRP·BNB·DOGE·HYPE·SUI·LINK·AVAX)의
`metaAndAssetCtxs`(마크·오라클·prevDayPx·funding·OI·거래대금)와 `predictedFundings`
(HlPerp·BinPerp·BybitPerp 예상 펀딩 + interval)를 같은 `HIP3_PUBLIC_DISPLAY_ENABLED` 게이트와
같은 위험수용(DS-2026-001 개정) 아래 전달한다. Binance·Bybit 값은 Hyperliquid가 산출·공표하는
2차 데이터이며 Mulmit은 두 거래소를 조회하지 않는다 — 응답 `relayed_by: "Hyperliquid"`,
화면은 "Hyperliquid 전달값" 라벨·보조 행·로고 없음·레퍼럴 링크 없음(`PLAN_CRYPTO_SECTION.md`
§5). 이력 lane(`HIP3_HISTORY_ENABLED`)은 섹션이 켜진 동안 SOL 일봉을 추가 저장한다
(코인당 가중치 ≈26, 한도 대비 미미) — `/api/crypto/volatility`의 실현 변동성(√365)·BTC 대
합성자산 상관은 이 저장값의 산술 파생이다. **BTC·ETH와 `xyz:SKHX`는 2026-08-22부터 자산
목록(`ASSETS`)에 상시로 있다** — 홈 보드가 크립토 섹션 스위치와 무관하게 쓰는 대표 시세라
같은 lane·같은 게이트로 항상 수집한다(추가 마켓 1개, 상류 호출 +1/패스). 페이지 노출 스위치는 `CRYPTO_SECTION_ENABLED`
(기본 false). 소스별 판정표는 `docs/PLAN_CRYPTO_SECTION.md` §3.

### 3.2 TradingView 공식 위젯

> **2026-08-22 판단(크립토 코인 페이지)**: 코인 상세 차트에 이 위젯을 쓰지 않기로 했다. 권리는 이미 열려 있으나(아래 허용 범위), 위젯이 그리는 값은
> 다른 거래소의 **현물**이라 "Hyperliquid 무기한선물 참고가"로 표시되는 페이지와 거래소가 어긋나고, 코인마다 iframe이 사용자 IP·URL을 제3자에 넘긴다.
> 대신 같은 HL `candleSnapshot`을 릴레이해 자체 SVG로 그린다(`docs/PLAN_CRYPTO_SECTION.md` §7.6). 드로잉 툴 수요가 생기면 이 항목 범위 안에서
> 선택형 토글로 다시 검토한다.

| 항목 | 기록 |
|---|---|
| 내부 ID | `tradingview_stock_heatmap_widget` |
| 현재 상태 | `provider_widget` |
| 현재 사용 | S&P 500 stock heatmap, 1D·1W·1M·1Y |
| 데이터 흐름 | 사용자 브라우저가 TradingView 공식 스크립트/iframe 로드 |
| 서버 저장 | 없음 |
| 자체 API 재전달 | 없음 |
| 허용 범위 | 공식 embed 코드, 브랜드, 링크, attribution을 유지하는 위젯 범위 |
| 금지 | iframe 숫자 추출, 스크래핑, 서버 fallback, TradingView 데이터처럼 보이는 자체 API 생성 |
| 공식 근거 | [Widgets](https://www.tradingview.com/widget/), [Stock Heatmap docs](https://www.tradingview.com/widget-docs/widgets/heatmaps/stock-heatmap/), [Widget data FAQ](https://www.tradingview.com/widget-docs/faq/data/), [Policies](https://www.tradingview.com/policies/) |

후속 작업:

- ~~Privacy 문서에 외부 위젯이 페이지 URL, 위젯 종류·심볼, IP 등 공급자 문서에 적힌 정보를 처리할 수 있음을 알린다.~~ **완료 (2026-08-17).** `/privacy` §4에 위젯이 사용자 브라우저에서 직접 로드되며 TradingView가 IP·페이지 URL·브라우저 정보를 받는다는 사실과 차단 방법을 기재했다.
- 외부 스크립트 실패 시 명시적 unavailable fallback을 추가한다.
- 광고·유료화 전 상업 사용 조건을 다시 확인한다.

### 3.3 FRED

| 항목 | 기록 |
|---|---|
| 내부 ID | `fred_legacy_adapter` |
| 현재 상태 | **조건부 승인 — 2026-08-18 활성화 결정** (아래 서면 회신) |
| 코드 위치 | `app/providers/fred.py`, `app/macro_dashboard.py`, `app/store.py`, `app/ingest.py` |
| 배포 기본값 | `FRED_ENABLED=false` (운영은 .env에서 명시적으로 켠다) |
| 현재 위험 | 수집 플래그가 false여도 DB에 과거 행이 있으면 macro route가 읽어 공개할 수 있음 — `data_rights` lane 게이트로 해소됨 |
| 공개 결정 | STLFSI4 서면 허가 수신(2026-08-18). `public_web=True` 계열만 수집·서빙, 제3자 권리 계열(VIXCLS·BAMLH0A0HYM2·PCOPPUSDM)은 `license_required` 유지 |
| 공식 근거 | [FRED API Terms](https://fred.stlouisfed.org/docs/api/terms_of_use.html), [FRED Terms](https://fred.stlouisfed.org/legal/terms/), [금지 용도](https://fred.stlouisfed.org/legal#prohibitions) |

**서면 회신 (2026-08-18, FRED Team, 이메일 원문은 운영자 메일함에 보관 —
회신 자체를 인용·공표하지 않는다는 푸터 조건에 따라 여기엔 요지만 적는다):**
2026-08-17 발송한 STLFSI4 공개 표시 문의에 대한 답. ① 우리 사용 방식은
acceptable, 금지 용도 목록 준수. ② 접근은 FRED API로. ③ 지정 인용문을 접근일과
함께 표기 — 경제 시계열은 개정되므로 접근일이 인용의 일부다. ④ **이 시리즈에
대한 접근을 유료화할 수 없다**(광고·스폰서 유무와 무관). ⑤ 세인트루이스 연은의
로고·상표 사용 금지, 보증·추천 암시 금지.

구현 반영: `FredSeriesSpec.citation`(STLFSI4)이 접근일을 채워
`rights.citation`으로 나가고, 모니터 attribution 블록이 이를 표기한다. Mulmit은
무료 접근이며(광고는 조건과 무관하게 허용됨), 연은 로고·마크는 쓰지 않고 텍스트
출처 표기만 한다.

lane을 켠 뒤 실측(2026-08-18 운영 반영): fred 소유로 새로 서빙된 계열은
**넷** — `STLFSI4`(이번 허가), `ICSA`(DOL ETA), `DCOILWTICO`(EIA), 그리고
`IORB`(연준 이사회 데이터 — 어느 lane에도 저장분이 없어 owner guard가 비어
있었고, 미 연방정부 저작물이라 권리 문제 없음). 나머지는 owner guard(연준
이사회 16·NY Fed 3·BLS 1·FSC 4 계열 소유 유지)로 막혔다. 부수 효과: FRED
카탈로그의 `license_required` 플레이스홀더 3장(VIXCLS·BAMLH0A0HYM2·PCOPPUSDM)이
값 없는 "라이선스 필요" 카드로 노출된다 — 값·관측치는 계속 비어 있으며, 이는
§5.5의 의도된 표시다.

즉시 필요한 수정:

1. `FRED_ENABLED=false`이면 seeded DB가 있어도 overview/detail에서 FRED 행의 값·관측치를 반환하지 않는다.
2. 비활성 응답에는 공개 캐시 헤더를 붙이지 않는다.
3. 운영 DB의 기존 FRED 행은 purge 또는 quarantine 방침을 정한다.
4. 거시 테이블을 공급자 중립 구조로 전환하고 원 발행기관 피드를 사용한다.

이 차단은 FRED lane에만 적용한다. 승인된 NY Fed·BLS·EIA lane이 추가되면 그
lane은 `FRED_ENABLED`와 무관하게 자기 플래그로 판정하고, macro route는 서빙
가능한 lane이 하나라도 있으면 200을 유지한다. macro 엔드포인트 전체를 끄는
단일 스위치로 만들면 P2에서 되돌려야 한다.

고정 `license_required` 계열:

- `VIXCLS` — 원 Cboe 권리
- `BAMLH0A0HYM2` — 원 ICE/BofA 권리
- `PCOPPUSDM` — IMF/원 권리 조건

이 세 계열은 어떤 fallback 레코드가 있더라도 `latest`, `previous`, `change`, `observations`를 비워야 한다. FRED 페이지에 값이 보인다는 사실을 승인 근거로 삼지 않는다.

### 3.4 KRX OPEN API

| 항목 | 기록 |
|---|---|
| 내부 ID | `krx_open_api` |
| 현재 상태 | `pending_rights` |
| 코드 위치 | `app/providers/krx.py`, `tests/test_krx_provider.py` |
| 배포 기본값 | `KRX_ENABLED=false` |
| 구현 상태 | adapter와 fixture 테스트만 있고 store/ingest/API 연결 없음 |
| 후보 데이터 | KOSPI/KOSDAQ 지수, 삼성전자 `005930`, SK하이닉스 `000660` |
| 공개 결정 | API별 관리자 승인과 공개 제3자 표시 범위의 서면 확인 전 off |
| attribution | 출처 표기는 선택이 아니라 필수 전제로 본다. 정확한 문구·표기 위치는 승인 회신으로 확정하고, 확정 전까지 `한국거래소` 출처 표기 없이 어떤 KRX 유래 값도 화면에 넣지 않는다 |
| 재배포 제한 | KRX 정보를 제3자에게 제공·재판매하거나 이를 기초로 한 파생 정보를 배포하는 행위는 별도 승인 대상으로 본다. Mulmit의 공개 JSON API는 이 “제3자 제공”에 해당할 수 있으므로 회신에서 명시적으로 확인받는다 |
| 공식 근거 | [KRX OPEN API](https://openapi.krx.co.kr/contents/OPP/MAIN/main/index.cmd), [이용약관](https://openapi.krx.co.kr/contents/OPP/INFO/OPPINFO002.jsp), [신청·승인 절차](https://openapi.krx.co.kr/contents/OPP/INFO/OPPINFO003.jsp) |

키 발급과 공개 재표시 권리는 같은 승인이 아니다. 별도 데이터 분배 계약이 필요하면 공개 가격과 예산을 받은 뒤 사용자 승인 없이는 구매하지 않는다.

KRX 승인이 나더라도 KRX 공식 종가는 HIP-3 `xyz:KR200`·`xyz:SMSN`과 별도 series
key로 저장한다. 같은 카드 안에서 두 값을 번갈아 채우거나 한 시계열로 이어 붙이지
않는다.

**이 lane이 막혀 있는 동안에도 코스피·코스닥·삼성전자·SK하이닉스의 장 마감값은
표시된다.** 금융위원회가 같은 자료를 공공데이터로 개방했고 그 이용허락범위가
“제한 없음”이기 때문이다(§3.9, `DS-2026-006`). 다만 그것은 T+1 장 마감값이고,
실시간 시세와 KRX 통계정보 전체는 여전히 이 lane의 승인 대상이다. §3.9가 열렸다고
`KRX_ENABLED`를 켜지 않는다.

### 3.5 SEC EDGAR (Form 3/4/5 지분공시)

| 항목 | 기록 |
|---|---|
| 내부 ID | `sec_edgar` |
| 현재 상태 | `approved` (아래 승인 범위 한정) |
| 코드 위치 | `app/providers/sec_edgar.py`, `app/insider_filings.py`, `app/us_fundamentals.py`, `app/store.py`, `app/ingest.py` |
| 배포 기본값 | `SEC_EDGAR_ENABLED=false`, `SEC_EDGAR_USER_AGENT=` (미설정이면 lane이 닫힘) |
| 현재 사용 | 티커→CIK 매핑, 회사 submissions, Form 3/4/5 원본 XML의 보고 항목, **XBRL companyconcept 재무제표**(`/api/us/fundamentals/{ticker}` — 10-K·10-Q의 매출·영업이익·순이익·EPS·자산·자본) |
| 기술 비용 | 무료. API 키 없음 |
| 접근 조건 | 연락처가 담긴 User-Agent 선언 필수, 초당 10요청 상한(사용자 단위, 기기 수 무관) |
| 표시 경계 | 공시된 값을 가공 없이 전달. 부여(A)·파생 행사(M)·세금 상계(F)를 시장 매수(P)·매도(S)와 합산하지 않음 |
| 공식 근거 | [Accessing EDGAR data](https://www.sec.gov/os/accessing-edgar-data), [EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), [Privacy and Security Policy](https://www.sec.gov/about/privacy-information) |

다른 공급자와 조건이 다른 이유는 EDGAR가 상용 벤더 피드가 아니라 미국 연방정부의
공시 시스템이기 때문이다. SEC는 “Anyone can access and download this information
for free”라고 명시하고, 라이선스 게이트가 아니라 운영 규칙(선언된 User-Agent,
요청 상한)을 둔다. 미 연방정부 저작물에는 저작권이 없다.

그렇다고 무조건이라고 적지는 않는다. 확인된 범위는 아래로 한정한다.

```yaml
decision_id: DS-2026-002
provider_id: sec_edgar
status: approved
reviewed_at: 2026-08-17
reviewer: repository owner
evidence_type: official_terms
evidence_reference: https://www.sec.gov/os/accessing-edgar-data
approved_scope:
  public_display: true
  server_json_relay: true
  cache_ttl_seconds: 300
  stale_seconds: 0
  historical_storage: true
  derived_metrics: true       # 공시된 값의 합계까지. 예측·등급은 포함하지 않음
  advertising: true           # 2026-08-19 판정 — 아래 노트 참조
attribution: "U.S. Securities and Exchange Commission · EDGAR"
expires_at: null
recheck_at: 2027-02-17
notes: >
  운영 조건은 라이선스가 아니라 fair access다. 초당 10요청 상한을 provider가
  자체적으로 강제하고, 연락처가 없는 User-Agent면 lane을 열지 않는다. SEC는
  정책 변경 가능성을 명시하므로 recheck_at에 재확인한다. 차단은 IP 단위로
  이뤄지므로 fail-closed 동작이 실질적으로 중요하다.
```

표시 규칙:

- Form 4의 거래 코드를 원문 그대로 표시하고 라벨만 번역한다.
- `P`(시장 매수)와 `S`(시장 매도)만 합계에 넣는다. `A`(부여), `M`(파생 행사), `F`(세금 원천징수 상계)는 개별 행으로만 보여 준다. 이걸 합치면 RSU 베스팅 한 건이 거대한 매매 신호처럼 보인다.
- 단가가 없는 공시(무상 부여 등)의 금액은 0이 아니라 빈 값이다.
- 요청 경로에서 EDGAR를 호출하지 않는다. 수집되지 않은 티커는 `queued`로 답하고 다음 배치가 가져간다.

재무제표(2026-08-19 추가) 표시 규칙:

- 회사마다 같은 항목의 XBRL 태그가 다르고 **갈아타기도 한다**(실측: NVIDIA는
  RevenueFromContractWithCustomer…를 2022년에 끊음). 태그 사다리에서 "가장 최신
  보고 기간을 가진" 태그를 고르고, 실제 사용 태그를 응답 `concepts_used`에 싣는다.
  매출 사다리에는 세금 포함 변형(…IncludingAssessedTax)도 있다 — CRWD는 이
  변형으로만 신고한다(2026-08-20 실측).
- **함정 4호 — 엔드포인트 불일치**(2026-08-20, KO 실측): companyconcept API가
  200 + 빈 USD 배열을 주는데 같은 태그(Revenues)가 companyfacts API에는 연간
  24행으로 존재한다. 사다리 전체가 비면 태그가 아니라 **경로를 폴백**한다 —
  companyfacts 1파일에서 같은 사다리를 다시 찾고, 출처를 `concepts_used`에
  "(companyfacts)" 접미로 남긴다. 그래도 없으면 기존대로 실패(fail-closed).
- 10-Q의 흐름 항목은 분기값과 YTD가 섞여 온다. 보고 기간 길이로 분류하고
  (분기 75~105일, 연간 340~380일) YTD는 어느 표에도 넣지 않는다. 같은 기간의
  정정 공시는 최신 제출분이 이긴다.
- 파생값은 마진 둘뿐이다(영업·순이익 ÷ 매출, 같은 보고서의 두 값) — 위
  `derived_metrics` 범위("공시된 값의 합계까지") 안이며 산식을 basis로 응답에
  명시한다. 가격 의존 지표(PER 등)는 미국 가격 표시 권리가 없어 만들지 않는다.
- 매출 개념이 없는 제출사(IFRS 등)는 캐시하지 않고 실패로 남겨 재시도한다 —
  빈 표가 12시간 캐시를 차지하면 안 된다.

### 3.6 New York Fed markets API (SOFR·EFFR·역레포)

| 항목 | 기록 |
|---|---|
| 내부 ID | `nyfed` |
| 현재 상태 | `approved` |
| 코드 위치 | `app/providers/nyfed.py`, `app/ingest.py`, `app/macro_dashboard.py` |
| 배포 기본값 | `NYFED_ENABLED=false` |
| 현재 사용 | SOFR, EFFR(reference rates), 익일물 역레포 총 낙찰금액 |
| 기술 비용 | 무료. API 키 없음 |
| 접근 조건 | 사이트 기능을 방해하지 않는 범위의 자동 접근. 요청 간격 0.2초 적용 |
| attribution | **필수.** 아래 문구가 응답의 `rights.notice`로 값과 함께 나감 |
| 공식 근거 | [Terms of Use](https://www.newyorkfed.org/privacy/termsofuse), [Reference Rates](https://www.newyorkfed.org/markets/reference-rates), [Markets API](https://markets.newyorkfed.org/static/docs/markets-api.html) |

이 프로젝트에서 가장 명확한 권리 근거다. 추론이 아니라 약관이 직접 열거한다.

> The New York Fed grants you a non-exclusive license... to use, copy, and
> distribute Content for your personal or business purposes. You may: Access
> the Content, manually or **through an automated process or device**...;
> **Download, store, and use** Content in any format or media; **Copy and
> distribute** the Content in any format or media; and **Modify and create
> derivative works** from the Content.

Mulmit이 하는 모든 일이 여기 포함된다 — 배치 수집, 사설 DB 히스토리, 공개 JSON API,
변화율 계산. "business purposes"라 향후 광고 도입도 별도 확인이 필요 없다.

라이선스는 조건부다. 복제·배포할 때 지정된 출처 식별자를 반드시 포함해야 한다.

```text
© [year] Federal Reserve Bank of New York. Content from the New York Fed
subject to the Terms of Use at newyorkfed.org.
```

문구를 문서에만 두면 렌더링 시점에 아무도 읽지 않으므로, 코드가 계열마다
`rights.notice`에 실어 보낸다.

```yaml
decision_id: DS-2026-003
provider_id: nyfed
status: approved
reviewed_at: 2026-08-17
reviewer: repository owner
evidence_type: official_terms
evidence_reference: https://www.newyorkfed.org/privacy/termsofuse
approved_scope:
  public_display: true
  server_json_relay: true
  cache_ttl_seconds: 300
  stale_seconds: 0
  historical_storage: true
  derived_metrics: true
  advertising: true        # "personal or business purposes"에 포함
attribution: "© [year] Federal Reserve Bank of New York. Content from the New York Fed subject to the Terms of Use at newyorkfed.org."
expires_at: null
recheck_at: 2027-08-17
notes: >
  약관 최종 개정 2023-06-09 기준. 조건은 출처 표기이며 코드가 rights.notice로
  자동 포함한다. 역레포는 FRED의 RRPONTSYD(십억 달러)와 달리 원 단위가 달러이므로
  재환산하지 않고 그대로 저장한다.
```

표시 규칙:

- 역레포는 **달러 단위**다. FRED `RRPONTSYD`는 십억 달러라 두 값을 같은 축에 두지 않는다.
- 하루에 두 건 이상 운영이 있으면 합산하고, 기간물(`Repo`)은 익일물 계열에 넣지 않는다.
- 게시된 날짜에 금리가 없으면 0이 아니라 결측으로 둔다.
- 이 lane이 소유한 계열은 FRED가 다시 가져가지 못한다(`_series_owner` 가드).

### 3.7 Federal Reserve Board 통계 릴리스 (H.15 등)

| 항목 | 기록 |
|---|---|
| 내부 ID | `federal_reserve` |
| 현재 상태 | `approved` (아래 근거의 성격에 주의) |
| 코드 위치 | `app/providers/fedboard.py`, `app/ingest.py` |
| 배포 기본값 | `FEDBOARD_ENABLED=false` |
| 현재 사용 | H.15 금리, 계산된 10Y−2Y, H.10 환율 5종, H.4.1 유동성 3종, H.6 통화량 2종 |
| 기술 비용 | 무료. API 키 없음 |
| 접근 경로 | 릴리스 페이지 XML 아카이브 (`/releases/h15/data/FRB_h15_xml.zip`) |
| attribution | 표준 출처 표기를 `rights.notice`로 함께 전달 |
| 공식 근거 | [DDP–FRED 전환 공지](https://www.federalreserve.gov/data/data-download-fred-information.htm), [H.15 릴리스](https://www.federalreserve.gov/releases/h15/), [H.10 릴리스](https://www.federalreserve.gov/releases/h10/) |

**NY Fed와 근거의 성격이 다르다.** NY Fed는 저작권을 주장하고 명시적 라이선스를
부여한다(연방기관이 아니므로). Board of Governors는 **연방기관**이라 그 저작물에
저작권이 성립하지 않는다(17 U.S.C. §105). 즉 여기서는 "허가를 받았다"가 아니라
"허가가 필요한 대상이 아니다"가 근거다. 릴리스 페이지에도 이용 제한 문구가 없다.
법률 자문이 아닌 개발상 판단이며, 그래서 재검토일을 짧게 잡았다.

**폐지 예정 경로를 피했다.** Board는 Data Download Program을 단계적으로 없애고
FRED로 유도하고 있다.

> the Board plans to remove the "Build Your Package" option from the Data
> Download Program the week of **November 9, 2026** ... including the eventual
> **retirement of the DDP**

Mulmit은 FRED 약관 때문에 그 대체 경로를 쓸 수 없다. 다만 같은 공지에 열린 문이
하나 있고 이 구현은 그쪽을 쓴다.

> **Historical data will remain available for download as XML files on
> statistical release pages.**

DDP 질의 엔드포인트가 아니라 릴리스 페이지 아카이브를 읽는 이유다. 이 문장이
철회되면 이 lane 전체가 막히므로 `recheck_at`을 2026-11-01로 잡았다.

```yaml
decision_id: DS-2026-004
provider_id: federal_reserve
status: approved
reviewed_at: 2026-08-17
reviewer: repository owner
evidence_type: official_terms
evidence_reference: https://www.federalreserve.gov/data/data-download-fred-information.htm
approved_scope:
  public_display: true
  server_json_relay: true
  cache_ttl_seconds: 300
  stale_seconds: 0
  historical_storage: true
  derived_metrics: true       # 10Y−2Y 스프레드를 두 공식 계열로 계산
  advertising: true
attribution: "Source: Board of Governors of the Federal Reserve System (US), statistical releases."
expires_at: null
recheck_at: 2026-11-01
notes: >
  근거는 명시적 라이선스가 아니라 연방기관 저작물에 저작권이 없다는 점이다(17 USC 105).
  DDP 폐지 일정(2026-11-09 1단계)이 있으므로 릴리스 페이지 XML 경로가 유지되는지
  recheck_at에 반드시 확인한다. 이 경로가 사라지면 Board 직접 연결은 불가능해진다.
```

표시 규칙:

- `OBS_STATUS`가 `A`가 아닌 관측치는 버린다. 값이 `-9999`(H.15) 또는 `-999999`(H.4.1) 센티넬이고 날짜는 미국 공휴일이다. 이걸 저장하면 차트가 파괴된다.
- 10Y−2Y는 **양쪽이 모두 게시한 날짜**로만 계산한다. 한쪽만 있는 날은 이월하지 않고 버린다.
- 아카이브는 릴리스당 한 번만 내려받아 그 안의 모든 계열에 재사용한다.
- 좁은 `Accept`(예: `application/zip`)에는 406으로 응답하므로 `*/*`를 보낸다.
- **H.10은 호가 방향이 두 가지고 계열명이 유일한 단서다.** 이름에 `$US`가 있으면
  "외화 한 단위당 달러"(EUR 1.1559), 없으면 "달러 한 단위당 외화"(KRW 1409.94)다.
  반대로 읽으면 환율이 뒤집히므로 방향을 `units`에 문장으로 적어 저장한다.
- H.10은 주 1회 게시되어 관측일이 며칠 지연된다. 정상이며 `freshness`가 `stale`로
  표시된다.
- 이 환율은 HIP-3 합성 FX(`xyz:JPY` 등)와 **별도 key**(`fx_*`)다. 공식값과 합성값을
  같은 카드에 섞지 않는다.
- **릴리스마다 단위 배율이 다르다.** H.4.1은 백만 달러, H.6은 십억 달러다. 한쪽으로
  통일하면 1,000배 어긋나면서도 여전히 숫자처럼 보인다. 각자의 원 단위로 저장하고
  화면이 `units` 문자열만 보고 $B/$T로 환산한다.
- **H.4.1의 `_Fnn` 접미사는 연준 지구(District)이지 세부 항목이 아니다.** 합계는
  `DISTRIBUTION=TOT`인 접미사 없는 계열이다. 재무부 계정은 전부 2지구(뉴욕)에 있어
  `RESPPLLDT_F02`가 지금은 총계와 같지만, 지구가 나뉘는 순간 조용히 틀려진다.
- 계열 식별은 값 교차검증으로 확인했다: 총자산 6.76T, 지급준비금 2.95T, TGA 0.96T.
  `RESMO14A_N.M`은 값이 5.49T라 MMF처럼 보이지만 실제로는 **본원통화**다. 설명
  주석(`AnnotationText`)을 확인하지 않으면 이런 오라벨이 난다.

### 3.8 U.S. Bureau of Labor Statistics

| 항목 | 기록 |
|---|---|
| 내부 ID | `bls` |
| 현재 상태 | `approved` |
| 코드 위치 | `app/providers/bls.py`, `app/ingest.py` |
| 배포 기본값 | `BLS_ENABLED=false`, `BLS_API_KEY=`(선택) |
| 현재 사용 | 실업률 `LNS14000000` (계절조정 월간) |
| 접근 조건 | 키 없이 하루 25회·10년, 키 등록 시 500회·20년 |
| attribution | 출처 표기 요청. `rights.notice`로 전달 |
| 공식 근거 | [Linking and Copyright](https://www.bls.gov/bls/linksite.htm), [Developers](https://www.bls.gov/developers/home.htm) |

이 프로젝트에서 권리 근거가 **가장 직접적으로 명시된** 공급자다. Fed Board는
연방기관 저작물이라는 §105 추론이었지만, BLS는 자기 페이지에 직접 쓴다.

> The Bureau of Labor Statistics (BLS) is a Federal government agency and
> everything that we publish, both in hard copy and electronically, **is in the
> public domain**... You are free to use our public domain material **without
> specific permission**, although we do ask that you **cite the Bureau of Labor
> Statistics as the source**.

```yaml
decision_id: DS-2026-005
provider_id: bls
status: approved
reviewed_at: 2026-08-17
reviewer: repository owner
evidence_type: official_terms
evidence_reference: https://www.bls.gov/bls/linksite.htm
approved_scope:
  public_display: true
  server_json_relay: true
  cache_ttl_seconds: 300
  stale_seconds: 0
  historical_storage: true
  derived_metrics: true
  advertising: true
attribution: "Source: U.S. Bureau of Labor Statistics."
expires_at: null
recheck_at: 2027-08-17
notes: >
  공개 도메인이 명시돼 있고 조건은 출처 표기뿐이다. BLS 엠블럼은 등록상표이므로
  로고는 사용하지 않는다. 월간 자료의 M13은 연평균이며 월 관측치가 아니므로 제외한다.
```

### 3.9 금융위원회 공공데이터 (data.go.kr)

| 항목 | 기록 |
|---|---|
| 내부 ID | `fsc` |
| 현재 상태 | `approved` |
| 코드 위치 | `app/providers/fsc.py`, `app/ingest.py`, `tests/test_fsc_provider.py` |
| 배포 기본값 | `FSC_ENABLED=false`, `FSC_API_KEY=` |
| 현재 사용 | 코스피·코스닥 지수 종가, 삼성전자·SK하이닉스 카드, **전 종목 하루 스냅샷**(검색 로스터, 일 1회), **요청 기반 개별 종목 5년 종가**(`/api/kr/*` 분석), **ETF 하루 스냅샷**(`/api/kr/etf` 보드 — 종가·NAV·괴리율, 일 1회) |
| 기술 비용 | 무료. data.go.kr 활용신청으로 키 발급 |
| 갱신 | 일 1회. 기준일 **다음 영업일 13시(KST) 이후** 공개. 실시간 아님 |
| attribution | `출처: 금융위원회 (공공데이터포털 data.go.kr)`. `rights.notice`로 전달 |
| 공식 근거 | [주식시세정보](https://www.data.go.kr/data/15094808/openapi.do), [지수시세정보](https://www.data.go.kr/data/15094807/openapi.do), [KRX상장종목정보](https://www.data.go.kr/data/15094775/openapi.do), [증권상품시세정보](https://www.data.go.kr/data/15094806/openapi.do) |
| 예비 승인분 | 금융위원회_채권시세정보·금융위원회_일반상품시세정보 — 2026-08-18 활용신청 승인(만료 2028-08-18), 아직 미사용. 국고채·금현물 카드 후보(구현 시 데이터셋 URL·스펙 검증 후 이 표에 승격) |

**§3.4의 KRX lane과 혼동하지 않는다.** 원 데이터는 같은 거래소에서 나오지만 허락의
근거가 다르다. KRX OPEN API 약관은 비상업 이용으로 한정하고 제3자 제공을 금지하며,
Mulmit의 공개 JSON API가 바로 그 “제3자 제공”에 해당할 수 있어 아직
`pending_rights`다. 금융위원회는 같은 장 마감 자료를 연계받아 공공데이터로
개방했고, 위 세 데이터셋 모두 포털에 이용허락범위 **“제한 없음”**, 비용 **“무료”**로
등록돼 있다. 포털이 부여하는 가장 넓은 등급이고, 이 lane이 기대는 근거는 그것이다.

이 lane을 여는 것은 KRX 승인이 아니다. 실시간 시세와 KRX 통계정보 전체는 여전히
별도 계약 영역이고 `KRX_ENABLED`는 계속 `false`다. 두 게이트는 서로를 열지 않으며
`tests/test_fsc_provider.py::test_opening_this_lane_does_not_open_the_krx_lane`이
이를 고정한다.

공식 종가는 HIP-3 합성값과 **별도 key**로 저장한다(§5.1·§5.2 참조). `samsung` 카드의
alias에서 `005930`을 제거했다 — 그 코드는 이제 공식 원화 종가를 식별하므로,
alias를 그대로 두면 하나의 레코드가 합성 무기한선물 카드와 공식 종가 카드에 동시에
붙어 서로 다른 측정값이 한 카드에서 섞인다.

```yaml
decision_id: DS-2026-006
provider_id: fsc
status: approved
reviewed_at: 2026-08-17
reviewer: repository owner
evidence_type: official_terms
evidence_reference: https://www.data.go.kr/data/15094808/openapi.do
approved_scope:
  public_display: true
  server_json_relay: true
  cache_ttl_seconds: 300
  stale_seconds: 0
  historical_storage: true
  derived_metrics: true
  advertising: true
attribution: "출처: 금융위원회 (공공데이터포털 data.go.kr)"
expires_at: null
recheck_at: 2027-08-17
notes: >
  이용허락범위 "제한 없음"은 포털의 최광의 등급이며 상업적 이용과 재배포를 별도로
  제한하지 않는다. 다만 개방 자료는 T+1 장 마감값이므로 실시간이라고 표기하지
  않는다. LIKE 계열 필터(likeSrtnCd)는 요청 전송량을 줄이는 용도이고, 저장 전에
  srtnCd/idxNm을 정확히 재확인한다. 같은 식별자·같은 날짜에 서로 다른 종가가
  둘 이상 오면 하나를 고르지 않고 그 계열을 실패시킨다. 예외적으로 이 lane은
  요청 경로에서도 provider를 부른다(app/kr_stocks.py) — 사용자가 방금 검색한
  종목이 시간당 배치를 기다릴 수 없기 때문이며, 프로세스 전역 잠금과 실패
  메모, 동일 스로틀 아래 캐시 미스에서만 단발 조회하고 결과는 store에 저장해
  이후 요청은 전부 DB 읽기다. 파생 통계(수익률·낙폭·MDD·변동성)는
  approved_scope.derived_metrics: true 범위 안이다.
```

### 3.10 금융감독원 Open DART (임원·주요주주 소유상황 보고)

| 항목 | 기록 |
|---|---|
| 내부 ID | `dart` |
| 현재 상태 | `approved` (아래 근거·범위 한정) |
| 코드 위치 | `app/providers/dart.py`, `app/kr_insider.py`, `tests/test_kr_insider.py` |
| 배포 기본값 | `DART_ENABLED=false`, `DART_API_KEY=` (미설정이면 lane이 닫힘) |
| 현재 사용 | `corpCode.xml`(매핑), `elestock.json`(소유상황 보고), `list.json`+`majorstock.json`(대량보유 5% — 국민연금 `/api/kr/pension` + **전체 보고자 `/api/kr/holdings`**, 2026-08-20 일반화: 같은 크롤의 두 산출물), **`fnlttSinglAcnt.json`(연간 주요계정 재무제표 — `/api/kr/fundamentals/{code}`)** |

재무제표(2026-08-19 추가) 표시 규칙: **연간(사업보고서)만** 다룬다 — 분기
손익은 누적·분기 구분이 API 응답에 없어 추측 대신 범위를 좁혔다. 연결(CFS)
우선·없으면 별도(OFS)이며 어느 쪽인지 응답에 명시한다. 금융사는 매출액·영업수익
계정 자체가 없는 것이 사실이므로(실측: KB금융) 매출·마진을 비운 채 영업이익·
순이익·자산·자본만 싣는다. 파생값은 마진 둘뿐(같은 보고서의 이익 ÷ 매출).
| 접근 조건 | 발급 키 필수. 허용량은 약관 제10조 ④ "홈페이지 게시" 방식 — 스로틀 유지, 요청 기반 조회만 |
| 표시 경계 | 보고된 값을 **가공 없이 전달**. elestock은 보고서 단위 소유수량·순증감이며 개별 매매·단가가 아님 — 화면 basis 문구로 명시. 합산 요약을 만들지 않음 |
| attribution | `출처: 금융감독원 전자공시시스템(DART)` + 공시 원문 링크(`dsaf001/main.do?rcpNo=`)를 행마다 제공 |
| 공식 근거 | [Open DART 소개](https://opendart.fss.or.kr/intro/main.do), [이용약관](https://opendart.fss.or.kr/intro/terms.do) |

SEC EDGAR(§3.5)와 같은 클래스다: 자본시장법상 법정 공시를 담는 공공기관의
공시 시스템이고, Open DART는 그것을 "누구나 활용"하도록 연 채널이다. 약관
(2026-08-17 정독)은 재배포 금지 조항 없이 다음을 둔다 — 제10조 ④ 허용량 제한,
제16조 ① 저작권은 **서비스·프로그램**에 대해 금감원 소유(공시정보 자체가 아님),
제23조 공시정보의 정확성·완전성 비보장(제출인 책임). 침묵을 백지수표로 읽지
않기 위해 승인 범위를 아래로 한정하고, EDGAR와 동일하게 원문 그대로의 전달과
출처·원문 링크를 조건으로 삼는다.

```yaml
decision_id: DS-2026-008
provider_id: dart
status: approved
reviewed_at: 2026-08-17
reviewer: repository owner
evidence_type: official_terms
evidence_reference: https://opendart.fss.or.kr/intro/terms.do
approved_scope:
  public_display: true          # 보고된 값의 원문 그대로 표시
  server_json_relay: true
  cache_ttl_seconds: 300
  stale_seconds: 43200          # 보고 목록 캐시 반나절
  historical_storage: true      # 법인코드 매핑·보고 목록 캐시
  derived_metrics: false        # 합산·순매수 등 파생 요약을 만들지 않음
  advertising: unconfirmed      # 광고 도입 전 허용량·조건 재확인
attribution: "출처: 금융감독원 전자공시시스템(DART)"
expires_at: null
recheck_at: 2027-02-17
notes: >
  허용량이 약관 본문이 아니라 "홈페이지 게시" 방식이므로 반기마다 게시값을
  재확인한다. corpCode.xml은 비상장 포함 전 법인을 담으므로 종목코드가 있는
  상장사만 매핑에 저장한다. "-"는 0이 아니라 미보고로 파싱한다.
```

### 3.11 DOL ETA 신규 실업수당 — **보류**

| 항목 | 기록 |
|---|---|
| 내부 ID | `dol_eta` |
| 현재 상태 | `pending_review` |
| 대상 카드 | `initial_claims` (계속 빈 상태) |

기계판독 경로가 요구 조건을 만족하지 못해 연결하지 않았다.

- `oui.doleta.gov/unemploy/csv/ar539.csv`는 열리지만 **주(州)별**이고 컬럼이
  `c1`~`c23`으로 익명이다. 어느 열이 신규 청구인지 추측하면 틀린 숫자가 나온다.
- 전국 **계절조정** 헤드라인(예: 209,000)은 `data.asp` HTML 페이지와 PDF에만 있다.
  HTML 스크래핑은 §10에서 금지한 방식이다.
- 주별 합계는 계절조정 전 값이라 FRED `ICSA`와 다른 계열이며, 같은 것처럼 표시할 수 없다.

연결하려면 ETA 539 레코드 레이아웃 문서를 확보하거나, 전국 계열의 CSV/JSON 경로를
찾아야 한다.

### 3.12 Yahoo Finance / yfinance

| 항목 | 기록 |
|---|---|
| 내부 ID | `yahoo_legacy` |
| 현재 상태 | `private_only` |
| 배포 기본값 | `LEGACY_PRICE_DATA_ENABLED=false` |
| 남은 기능 | `/analytics`, `/api/metrics`, `/api/correlation`, `/api/market/sectors`의 레거시 opt-in |
| 공개 결정 | 서면 라이선스 전 공개 배포에서 계속 503 |
| 공식 근거 | [Yahoo data providers and redistribution notice](https://help.yahoo.com/kb/yahoo-finance-plus/exchanges-data-providers-yahoo-finance-sln2310.html), [Yahoo Terms](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html) |

yfinance 패키지가 공개 표시·저장·재배포 권리를 부여한다고 해석하지 않는다. 401/429를 스크래핑 엔드포인트로 우회하지 않는다.

### 3.13 Cboe, ICE, IMF

| 공급자/권리자 | 대상 | 상태 | 현재 결정 | 공식 근거 |
|---|---|---|---|---|
| Cboe | VIX, SKEW, VVIX, OVX, Put/Call Ratio | `license_required` | 값·차트 비공개 | [Market data document library](https://www.cboe.com/market_data_services/document_library), [Information License Request](https://cdn.cboe.com/resources/us/indices/Information_License_Request_Form.pdf) |
| ICE Data Indices / BofA | High Yield OAS (`BAMLH0A0HYM2`의 원 권리자) | `license_required` | 값·차트 비공개 | [ICE Data Indices](https://www.ice.com/market-data/indices), [ICE Data Services](https://www.ice.com/market-data) |
| IMF | 정확한 구리 계열 (Primary Commodity Price System) | `pending_review` | HIP-3 copper proxy와 분리, IMF 직접 배포처의 이용조건 확인 | [IMF Primary Commodity Prices](https://www.imf.org/en/Research/commodity-prices), [IMF Data](https://data.imf.org/), [Copyright and Usage](https://www.imf.org/en/about/copyright-and-terms) |

2026-08-17 재확인. Cboe는 지수값을 콕 집어 서면 허가 대상으로 적어 두었다. “값이
공개 웹에 보인다”와 “재게시해도 된다”가 다르다는 것을 공급자가 직접 쓴 사례다.

> No data, values, or other content contained in this document (**including
> without limitation, index values or information**, ratings, credit-related
> analyses and data, research, valuations, strategies, methodologies, and
> models) or any part thereof may be modified, reverse-engineered, reproduced,
> or **distributed in any form or by any means**, or stored in a database or
> retrieval system, **without the prior written permission of Cboe**.
>
> — <https://www.cboe.com/us_disclaimers/>

따라서 VIX·SKEW·VVIX·OVX·Put/Call은 우회 경로를 찾지 않는다. 무료 CSV가 열려
있다는 사실도 근거가 아니다. 이 다섯은 계약 전까지 계속 빈 카드로 둔다.

`BAMLH0A0HYM2`의 원 권리자는 ICE Data Indices, LLC다. `ice.com/iba`는 ICE Benchmark
Administration(LIBOR·ICE Swap Rate 등) 페이지로 지수 라이선스 창구가 아니다.
문의는 ICE Data Indices/ICE Data Services 쪽으로 보낸다.

IMF 구리 계열은 FRED의 `PCOPPUSDM`을 경유하지 않고 IMF Primary Commodity Price
System 원본에서 직접 받는 경로만 검토한다. IMF 자료도 무조건 자유 이용이 아니며,
계열에 따라 원 데이터 제공자(거래소 등)의 별도 조건이 붙을 수 있다.

월 30,000원 예산 안에 외부 공개 표시 계약이 가능하다는 근거가 없으므로 견적을 추정하지 않는다. HIP-3 VIX-linked/Copper-linked 값은 해당 공식 지표의 대체 “정답”이 아니라 별도 합성 참고값이다.

### 3.14 미 하원 서기국 재정공시 — PTR (STOCK Act)

| 항목 | 기록 |
|---|---|
| 내부 ID | `house_fd` |
| 현재 상태 | `approved` (아래 §105(c) 분석 조건부) |
| 코드 위치 | `app/providers/house_fd.py`, `app/us_ptr.py`, `tests/test_us_ptr.py` |
| 배포 기본값 | `US_PTR_ENABLED=false` (키 없음, 게이트만) |
| 현재 사용 | `/api/us/ptr` — 최근 45일 주기거래보고: 인덱스(구조화 XML) + 전자 제출 PDF의 거래 표 |
| 수집 | ingest 배치 전용. 연간 인덱스 zip 1요청 + 신규 PDF 건당 1요청(1초 간격, 주기당 25건 상한, doc_id 증분 재사용) |
| attribution | `Source: Clerk of the U.S. House of Representatives, Financial Disclosure Reports.` + 건별 원문 PDF 링크 |
| 공식 근거 | [Clerk Financial Disclosure](https://disclosures-clerk.house.gov/FinancialDisclosure), 5 U.S.C. app. §105(c) |

**EIGA §105(c) 사용 제한 분석 (2026-08-18).** 법은 보고서를 ① 불법 목적,
② 상업 목적, ③ 개인 신용평가, ④ 정치·자선 자금모집에 쓰는 것을 금지하되,
②에서 "**news and communications media의 일반 공중 배포**"를 명시적으로
제외한다. Mulmit의 표시는 무료 공개 사이트에서 출처·원문 링크와 함께 공시
내용을 일반 공중에 전달하는 것으로 그 제외 사유의 기능에 해당한다고 판단한다
(동일 구조의 선례: 뉴스 매체·공익 추적 사이트들). 광고 수익은 뉴스 매체의
통상 모델과 같다. ③·④에 해당하는 이용은 하지 않으며, **같은 제한을 API
응답과 화면에 원문 고지로 실어** 다운스트림 이용자에게도 전달한다.

**파싱 정직성.** 전자 제출 PDF만 거래 표를 추출한다(실검증: 8건 중 7건 완전
추출, 스캔 수기 1건은 추출 불가로 분류). 서명(유형+거래일+신고일+금액 구간)이
엄격히 일치하는 행만 싣고, 자산명이 비면 그 거래는 버리고 상태로 보고한다 —
이름이 걸린 데이터에서 추측하지 않는다. 금액은 구간 문자열 그대로다.

**상원(eFD)은 보류.** efdsearch.senate.gov는 비브라우저 클라이언트에 403을
반환한다(Akamai, 2026-08-18 실측 — 로컬·EC2 모두). TLS 지문 위장으로 우회하지
않는다는 원칙에 따라 상원은 수집하지 않으며, 화면 문구가 하원 한정임을
명시한다. 공식 접근 경로가 생기면 재검토한다.

```yaml
provider_id: house_fd
status: approved
reviewed_at: 2026-08-18
reviewer: repository owner
evidence_type: statute_and_official_portal
evidence_reference: 5 U.S.C. app. §105(c); https://disclosures-clerk.house.gov/FinancialDisclosure
approved_scope:
  public_display: true
  server_json_relay: true
  cache_ttl_seconds: 300
  stale_seconds: 0
  historical_storage: true
  derived_metrics: false
  advertising: true
attribution: "Source: Clerk of the U.S. House of Representatives, Financial Disclosure Reports."
expires_at: null
recheck_at: 2027-08-18
notes: >
  §105(c) 금지 목적(신용평가·자금모집 등)의 이용을 하지 않고, 제한 고지를
  응답에 동봉한다. 상원 eFD는 봇 차단으로 보류 — 우회하지 않는다.
```

### 3.15 뉴욕 연방준비은행 — 침체 확률 연구 데이터 (국채 스프레드 모델)

- **시리즈**: `recession_prob` — "Probability of U.S. Recession Predicted by
  Treasury Spread, Twelve Months Ahead". 월별, 1959~. **날짜는 예측 대상 월**이라
  최신 관측치가 12개월 미래에 찍히는 것이 정상이다.
- **원본 파일**: `newyorkfed.org/medialibrary/media/research/capital_markets/allmonth.xls`
  (구형 BIFF .xls, 시트 `rec_prob`). 함정 실측(2026-08-19): 미디어 서버는
  **확장자를 무시**한다 — `.csv` URL도 같은 OLE2 바이너리를 주고, `Prob_Rec.xls`는
  실제로는 차트 **PDF**다. allmonth가 유일한 실데이터.
- **권리 (2026-08-19 약관 전문 검토)**: Terms of Use(newyorkfed.org/privacy/termsofuse)가
  "personal or business purposes"의 사용·복사·배포·파생을 명시 허용. Use
  Restrictions 목록(블로그·레퍼런스 금리·스태프 리포트·HHDC·SCE)에 연구 지표
  데이터는 **없음** → 일반 허용 라이선스 적용. 기존 nyfed lane(SOFR·EFFR·RRP)과
  같은 근거, 같은 게이트(NYFED_ENABLED).
- **조건**: ① 지정 인용문 동봉("© [연도] Federal Reserve Bank of New York.
  Content from the New York Fed subject to the Terms of Use at newyorkfed.org.")
  — 기존 attribution 기계가 자동 처리. ② 원문 왜곡 금지 — 원자료는 소수(0.152)이고
  연은 자신의 페이지가 퍼센트로 말하므로 **×100 표기 변환만** 하고 그 사실을 코드에
  기록. ③ **연은 이름 광고 사용 금지** — 광고 도입 시 광고 소재에 NY Fed 명칭
  불사용을 체크리스트에 포함할 것. ④ 보증 시사 금지.
- **경위**: Polymarket 침체 베팅 대체 검토(2026-08-19, 방심위 차단으로 ❌ 유지)
  에서 나온 대안. CME FedWatch는 재게시가 CME 라이선스 대상이라 배제.

```yaml
provider: nyfed
series: recession_prob
status: approved
rights:
  store: true
  cache: true
  display_values: true
  redistribute_api: true
  derived_metrics: false
  advertising: true  # 단, 광고 소재에 NY Fed 명칭 사용 금지
attribution: "© [year] Federal Reserve Bank of New York. Content from the New York Fed subject to the Terms of Use at newyorkfed.org."
expires_at: null
recheck_at: 2027-08-19
notes: >
  값은 소수→퍼센트 ×100 표기 변환만. 날짜는 예측 대상 월(미래 날짜 정상).
  allmonth.xls만 실데이터(확장자 무시 서버, Prob_Rec는 PDF).
```

### 3.16 한국은행 경제통계시스템 (ECOS) — 한국 거시 lane

- **상태**: **✅ 활성화 (2026-08-20)** — 운영자 인증키 도착("영리" 이용형태로 승인 =
  상업 이용 증빙), 키 라이브 검증(기준금리 2026-07 = 2.75%) 후 서버 투입.
  첫 수집 3시리즈·360관측치, /api/market/macro 서빙·출처표기 확인. 가입 화면
  약관 전문은 미보관 — 영리 카테고리 승인이 1차 증빙이며, 조건 문구 발견 시 보강.
- **시리즈 (라이브 검증 2026-08-19, sample 키)**: `kr_base_rate` 722Y001/0101000
  (월, 연%) · `kr_cpi` 901Y009/0 (월, 2020=100) · `kr_unemployment` 901Y027/I61BC
  (월, %). 가계신용(151Y002)은 분기 주기 지원 확장 후 후속.
- **신청 기록 (2026-08-19)**: 운영자가 인증키 신청 제출 — **이용형태 "영리(정보판매
  등의 상업적 이용)" 명시 선택**, 이용목적 "홈페이지 서비스". 승인 시 이 선택
  자체가 상업 이용 승인 증빙이다. MyPage 고지 실측: 인증키 타인 양도 불가,
  허용량 초과·비정상 트래픽 시 사전 통보 없이 중단 가능, 발급 키는 한국은행
  모든 Open API에 사용 가능. sample 키는 호출당 10건 제한(실측).
- **API 실측**: StatisticSearch 경로 `{stat}/{cycle}/{from}/{to}/{item}`, 월 주기
  TIME=YYYYMM, 발표 전 달은 DATA_VALUE 빈 문자열(결측 처리), 오류는 200 응답의
  RESULT 봉투(CODE/MESSAGE).
- **활성화 체크리스트**:
  1. 운영자가 ecos.bok.or.kr/api 에서 인증키 발급 (회원가입 필요)
  2. **발급 화면의 이용약관 전문을 캡처·보관** → 이 문서에 인용 기록 (출처표시
     조건·상업 이용 문구 확인이 목적)
  3. 서버 .env에 ECOS_API_KEY + ECOS_ENABLED=true (타임스탬프 백업 후)
  4. 첫 수집 후 /kr '한국 매크로' 섹션 검증
- 약관에 공개 재배포를 막는 문구가 있으면 lane은 켜지 않는다 — fail-closed.

### 3.17 미 재무부 금융연구국(OFR) — 금융스트레스지수 (변동성·신용 범주 포함)

- **상태**: **✅ 승인·활성화 (2026-08-21)** — 연방정부 저작물. 숨긴 VIX·하이일드 카드의
  역할을 권리 깨끗한 한 lane으로 대신한다(변동성 범주 = 내재·실현 변동성 계열,
  신용 범주 = 스프레드 계열). `DS-2026-009`.
- **코드**: `app/providers/ofr.py`, `app/ingest.py::refresh_ofr`, 카탈로그 `OFR_*`
  (`app/providers/fred.py`, 소유권은 저장 행 provider_id=`ofr`), 게이트 `OFR_ENABLED`
  (기본 false). 카드 `ofr_fsi`·`ofr_fsi_volatility`·`ofr_fsi_credit`; 자금조달·안전자산·
  주식 밸류에이션 범주도 수집·API 서빙(카드 미배치).
- **데이터**: <https://www.financialresearch.gov/financial-stress-index/data/fsi.csv>
  — 열 `Date, OFR FSI, Credit, Equity valuation, Safe assets, Funding, Volatility,
  United States, Other advanced economies, Emerging markets`, 2000-01-03부터 일별.
  라이브 확인 2026-08-21: 최신 행 2026-08-18(페이지 고지 "publishes with data that is
  current from two business days prior"). 33개 시장 변수 기반, 0 = 평균 스트레스.
- **권리 근거 (Legal Notices, 접근 2026-08-21, <https://www.financialresearch.gov/legal-notices/>)**:
  > "Copyright Status — **No copyright may be claimed for any work on this website
  > that was created by a federal employee in the course of his or her duties.
  > However, credit is requested** if you reproduce or copy any such work. If
  > copyrighted material appears on the site, or is reached through a link on this
  > site, the copyright holder must be consulted before the material may be reproduced."
  >
  > "Official Seal, Names and Symbols — **Federal law prohibits use of any symbol,
  > emblem, seal, insignia, or badge** of any entity of the Department of Treasury …"
  >
  > "Disclaimer of Endorsement — The OFR does not endorse any commercial product,
  > service, process, or enterprise."
  페이지의 Suggested Citation: *Office of Financial Research, "OFR Financial Stress
  Index," refreshed daily, https://www.financialresearch.gov/financial-stress-index/
  (accessed …).* — 접근일을 채워 `rights.citation`으로 모든 값에 동봉한다.
- **판단**: 지수·범주값은 OFR 직원이 산출한 연방 저작물(공공 영역). 입력 변수 일부는
  상용 벤더 출처지만 CSV에는 OFR의 산출값만 있다 — STLFSI와 같은 구조이며, 여기선
  발행기관이 저작권을 주장조차 않는다. 조건: 텍스트 출처표기+인용문(접근일), 재무부
  인장·로고 미사용, OFR 보증 암시 금지. 광고 동반 표시를 막는 문구 없음.

```yaml
decision_id: DS-2026-009
provider_id: ofr
status: approved
reviewed_at: 2026-08-21
reviewer: repository owner
evidence_type: official_terms
evidence_reference: https://www.financialresearch.gov/legal-notices/
approved_scope:
  public_display: true
  server_json_relay: true
  cache_ttl_seconds: 21600
  historical_storage: true
  derived_metrics: true   # 변화율·차트 등 공시값 산술만
  advertising: true        # 연방 저작물, 제한 문구 없음; OFR 보증 암시 금지
attribution: "Office of Financial Research, OFR Financial Stress Index (credit requested; no Treasury seal)"
citation: 'Office of Financial Research, "OFR Financial Stress Index," refreshed daily, https://www.financialresearch.gov/financial-stress-index/ (accessed {date}).'
expires_at: null
recheck_at: 2027-02-21
```

### 3.18 alternative.me — 크립토 공포·탐욕 지수 (Crypto Fear & Greed Index)

| 항목 | 기록 |
|---|---|
| 내부 ID | `alternative_me` |
| 현재 상태 | **`approved` (official_terms, 2026-08-21)** — `DS-2026-010` |
| 코드 위치 | `app/providers/alternative_me.py`, `app/crypto_market.py`(`refresh_crypto_sentiment`·`build_crypto_sentiment`), `app/ingest.py::refresh_crypto_sentiment`, 라우트 `/api/crypto/sentiment` |
| 게이트 | `CRYPTO_SECTION_ENABLED` + `ALTERNATIVE_ME_ENABLED` (기본 false, web·ingest 공통) |
| 현재 사용 | `GET https://api.alternative.me/fng/?limit=N&format=json` — 일별 값·분류·타임스탬프·다음 갱신까지 초. ingest가 1시간 주기로 확인해 blob(`crypto_fear_greed_v1`, 최근 366일)으로 저장하고 요청 경로는 blob만 읽는다. 화면: 현재값·분류·1d/7d/30d 변화·90일 차트·발행자 공개 가중치 |
| 기술 비용 | 키·구독료 없음 |
| 공식 근거 | [Crypto Fear & Greed Index](https://alternative.me/crypto/fear-and-greed-index/) (API 안내와 이용조건이 같은 페이지) |
| 표시 경계 | 발행자 지수를 그대로 전달한다(명칭 변경·자체 지수화 금지). 비트코인 중심 지표이며 `Mulmit Market Sentiment Gauge`(§5.4.2)·CNN F&G와 정의가 달라 비교 불가 고지를 동봉한다 |

약관 원문(접근 2026-08-21):

> "Commercial use is allowed as long as the attribution is given right next to the
> display of the data."
>
> "You must properly acknowledge the source of the data and prominently reference
> it accordingly."
>
> "You may not use our data to impersonate us or to create a service that could be
> confused with our offering."

조건 구현: 응답 `attribution{text: "Crypto Fear & Greed Index — alternative.me", url,
placement: "adjacent_to_value", required: true}`, 화면은 점수 바로 아래 `#cfng-attribution`에
문구+링크를 고정한다. 자체 게이지와 나란히 둘 때 "정의가 달라 비교 대상 아님" 문구를 둔다.

```yaml
decision_id: DS-2026-010
provider_id: alternative_me
status: approved
reviewed_at: 2026-08-21
reviewer: repository owner
evidence_type: official_terms
evidence_reference: https://alternative.me/crypto/fear-and-greed-index/
approved_scope:
  public_display: true
  server_json_relay: true
  cache_ttl_seconds: 3600
  stale_seconds: 172800
  historical_storage: true   # 최근 366일 blob, 차트용
  derived_metrics: true      # 1d/7d/30d 포인트 변화만, 지수 재산출 없음
  advertising: true          # 약관이 상업 이용을 출처표기 조건으로 명시
attribution: "Crypto Fear & Greed Index — alternative.me (값 바로 옆, 링크 포함)"
expires_at: null
recheck_at: 2026-11-21
notes: "발행자 약관 페이지 문구 기반. 약관 변경 시 ALTERNATIVE_ME_ENABLED=false로 즉시 OFF. 명칭·브랜드 복제 금지 조항 준수."
```

### 3.19 업비트(두나무) Open API — 원화 시세 relay (김치프리미엄)

| 항목 | 기록 |
|---|---|
| 내부 ID | `upbit` |
| 현재 상태 | **`pending_rights` + 운영자 위험수용 (2026-08-22, `DS-2026-012`)** — 서버 게이트 `UPBIT_ENABLED=true`로 개방, 라이브 확인 00:5x KST(USDT/KRW 1,375·테더 프리미엄 −1.29%·BTC USDT 기준 −0.12%). 두나무 1:1 문의는 기록용으로 발송(회신 시 이 블록 갱신, 거절이면 즉시 OFF) |
| 코드 위치 | `app/providers/upbit.py`, `app/crypto_kimchi.py`, 라우트 `/api/crypto/kimchi` |
| 게이트 | `CRYPTO_SECTION_ENABLED` + `UPBIT_ENABLED` (+ HIP-3 표시 게이트: 오라클 참고가) |
| 현재 사용(설계) | `GET /v1/ticker?markets=KRW-BTC,KRW-ETH,KRW-SOL,KRW-XRP,KRW-DOGE,KRW-USDT` — 서버 relay, 15초 단일 비행 캐시·300초 stale, 호출량 ≈ 4/분/프로세스(한도 IP당 600/분의 1%). 브라우저 직결 없음(Origin 요청은 10초 1회 제한). 표시: 원화 최근 체결가·24h, 테더 프리미엄(KRW-USDT ÷ ECOS 일별 고시 − 1, 날짜 표시), 코인 프리미엄 USDT 기준((KRW-코인 ÷ KRW-USDT) ÷ HL 오라클 − 1)·공식환율 기준 |
| 기술 비용 | 키·구독료 없음 |
| 공식 근거 | [Open API 이용약관 2023-12-15](https://static.upbit.com/terms/legacy/openapi_agreement_20231215.html), [티커 API 문서](https://docs.upbit.com/kr/reference/ticker), [요청 한도](https://docs.upbit.com/kr/reference/rate-limits) |
| 표시 경계 | 업비트 최근 체결가(호가·수수료·출금 조건 미반영), 차익거래 가능성 아님, 로고 미사용, 출처 문구 "시세: 업비트(두나무)" |

약관 원문(접근 2026-08-21): §2 정의 "…시세 및 잔고 조회…", **§5(저작권) "Open API 서비스상에서
제공되는 모든 데이터 및 내용에 대한 저작권은 두나무에 있으므로 사용자는 이를 무단으로 사용하거나
변경하여서는 안 됩니다."**, §6③ 프로그램의 유상 양도·배포 금지. 공개 웹 재표시를 허가하는 조항도
금지하는 조항도 없다 — 침묵을 허가로 읽지 않는다. 시세 API는 인증 없이 제공되고(IP당 10회/초) 국내
다수 사이트가 같은 방식으로 표시하지만 그 사실은 근거가 아니다.

**2026-08-22 운영자 결정 — 위험수용 개방.** 근거는 HL 선례(DS-2026-001 개정: 무응답 ≠ OFF, 명시적 거절만 OFF)와
같다: ① 약관에 공개 재표시 금지 조항 없음(§5 저작권 주장뿐) ② 인증 없는 공개 시세 API(IP당 10회/초) ③ 출처 문구
"시세: 업비트(두나무)" 고정, 로고 미사용 ④ 서버 relay 15초 캐시(한도의 1%), 브라우저 직결 없음 ⑤ 원화 최근 체결가·
파생 프리미엄만 표시, 호가·체결 내역 미전달 ⑥ 거절 회신 시 `UPBIT_ENABLED=false`로 즉시 OFF. 두나무 1:1 문의
([`INQUIRY_CRYPTO_SOURCES.md`](INQUIRY_CRYPTO_SOURCES.md) §2)는 기록용으로 발송하고 회신을 이 블록에 반영한다.

```yaml
decision_id: DS-2026-012
provider_id: upbit
status: pending_rights            # 운영자 위험수용 — 서면 승인 시 approved로 갱신
reviewed_at: 2026-08-22
reviewer: repository owner
evidence_type: official_terms
evidence_reference: https://static.upbit.com/terms/legacy/openapi_agreement_20231215.html (§2 시세 조회 정의, §5 저작권, 재표시 허가·금지 조항 없음) + https://docs.upbit.com/kr/reference/rate-limits
approved_scope:
  public_display: true
  server_json_relay: true
  cache_ttl_seconds: 15
  stale_seconds: 300
  historical_storage: false
  derived_metrics: true     # 테더 프리미엄·코인 프리미엄 = 표시값 산술
  advertising: true
attribution: "시세: 업비트(두나무)"
expires_at: null
recheck_at: 2026-09-16
notes: "운영자 위험수용(2026-08-22). 명시적 금지 없음 + 공개 시세 API + 출처 표기 + 서버 relay 저호출 + 로고 미사용. 거절 회신 시 즉시 OFF. 문의 발송일과 회신은 §4.1에 기록."
```

### 3.20 CoinMarketCap API — 글로벌 메트릭(BTC·ETH 도미넌스, 총시총)·스테이블코인 공급

| 항목 | 기록 |
|---|---|
| 내부 ID | `coinmarketcap` |
| 현재 상태 | **`approved` (2026-08-21, `DS-2026-011`)** — 운영자가 Basic 키 발급 시 Commercial User Terms 수락, 서버 게이트 ON(2026-08-21 23:29 KST 첫 blob 저장·라이브 확인: BTC 59.83%·ETH 11.13%·총시총 $2.59T) |
| 코드 위치 | `app/providers/coinmarketcap.py`, `app/crypto_structure.py`, `app/ingest.py::refresh_crypto_structure`·`refresh_crypto_stablecoins`, 라우트 `/api/crypto/structure` |
| 게이트 | web: `CRYPTO_SECTION_ENABLED` + `CMC_ENABLED`; ingest 수집: + `CMC_API_KEY`(ingest 전용 env) |
| 현재 사용(설계) | `GET /v1/global-metrics/quotes/latest?convert=USD` 1크레딧/회, `CMC_MAX_AGE`(기본 900초) 주기 → 월 ≈ 2,900크레딧(Basic 15,000의 1/5). blob 저장, 요청 경로는 blob만. 표시: BTC·ETH 도미넌스(24h 변화 p), 기타 = 100 − BTC − ETH, 총시총·24h, 스테이블코인 시총(24h 변화 없음 — CMC `stablecoin_24h_percentage_change`는 **거래대금** 변화, 실측 2026-08-22 +22.6% vs 시총 $282B; 거래대금 카드에 표시), 24h 거래대금. **2026-08-22 추가**: `GET /v2/cryptocurrency/quotes/latest?id=825,3408&convert=USD`(USDT·USDC 유통 공급, 1크레딧/회, `CMC_STABLECOIN_MAX_AGE` 기본 3600초 → 월 ≈ 720 추가, 합계 ≈ 3,600/15,000) — 표시: 유통 공급·페그 편차·스테이블 비중(= 스테이블 시총 ÷ 총시총, 산술)·7d/30d 공급 변화(Mulmit 자체 일별 누적, 시작일 표시). 같은 키·같은 Commercial Terms·같은 1-product 표시 |
| 기술 비용 | Basic 무료(예산 0원) |
| 공식 근거 | [Pricing](https://coinmarketcap.com/api/pricing/) — "Commercial use rights — the free Basic tier included", 15,000 credits/월, 50 req/분(접근 2026-08-21); [Commercial Terms](https://pro.coinmarketcap.com/user-agreement-commercial/)(키 발급 시 원문 확인: 출처 문구, 1 product/100k users 한도, 독립 재배포 금지) |
| 표시 경계 | 출처 문구(`CMC_ATTRIBUTION_TEXT`, 기본 "Data provided by CoinMarketCap" + 링크)를 값 바로 옆에, 도미넌스는 "CMC 유니버스 기준" 고지, 로고 미사용 |

가격표 재확인(2026-08-21 23:2x KST): 비교표의 "Commercial use"가 Basic~Professional 전 플랜에 표시되고,
라이선스는 "limited, non-exclusive and non-transferable, and covers one product with up to 100k users",
"may not redistribute or resell it as a standalone service, whether through your own API or as part of a data
distribution product" — Mulmit은 대시보드 안의 통합 표시(1 product)이며 독립 재배포가 아니다. 가입 드롭다운의
"Startup — For commercial use" 라벨은 크레딧 규모 안내로 보고 Basic을 선택했다(예산 0원). 약관 변경 시
`CMC_ENABLED=false`로 즉시 OFF.

```yaml
decision_id: DS-2026-011
provider_id: coinmarketcap
status: approved
reviewed_at: 2026-08-21
reviewer: repository owner
evidence_type: official_terms
evidence_reference: https://coinmarketcap.com/api/pricing/ (Commercial use — Basic 포함, 1 product/100k users, standalone 재배포 금지) + 키 발급 시 수락한 Commercial User Terms
approved_scope:
  public_display: true
  server_json_relay: true
  cache_ttl_seconds: 900
  stale_seconds: 43200
  historical_storage: false     # 최신 blob 1개만
  derived_metrics: true         # 기타 = 100 − BTC − ETH 산술
  advertising: true
attribution: "Data provided by CoinMarketCap" (링크, 값 바로 아래)
expires_at: null
recheck_at: 2026-11-21
notes: "Basic 무료 15,000 credits/월 중 ≈2,900 사용. 키는 ingest 전용 env. 도미넌스는 CMC 유니버스 기준 고지."
```

### 3.21 가스·온체인 수수료 스트립 — 조사 결과 **보류** (2026-08-21)

| 후보 | 확인 내용(접근 2026-08-21) | 판정 |
|---|---|---|
| Etherscan 무료 API | 출처표기 필수 + 상업 이용 사전 동의 필요(PLAN §3) | `license_required` |
| PublicNode(Allnodes) 퍼블릭 RPC | ToS가 "copying, distributing or disclosing any part of the Service … scraping"을 금지하고 상업·요율 조항은 없음 | 불명확 → 미사용 |
| Base 공식 `mainnet.base.org` | 문서: "The public endpoints above are rate-limited and not suitable for production traffic. For production use, connect through a node provider." | 프로덕션 부적합 → 미사용 |
| Arbitrum 공식 퍼블릭 RPC | 같은 취지(rate-limited, 프로덕션은 provider 권장) | 미사용 |
| mempool.space API | 무료 사용은 비상업 취지, 상업·고량은 Enterprise/유료(Pro 20 EUR/월) | 예산 내지만 가치 대비 보류 |
| Alchemy/Infura 등 키 발급형 무료 티어 | 약관상 프로덕션 허용(계정·키 필요) | **운영자가 가입하면** env 주입형 lane으로 재개 |

결론(1차): 퍼블릭 엔드포인트로는 열지 않는다.

**2026-08-21 후속 — lane 코드 추가, 게이트 OFF, 운영자 RPC 계정 URL 주입형.** `/api/crypto/gas`
(`app/crypto_gas.py`, `app/providers/evm_rpc.py`): `eth_feeHistory`(1블록·p50)로 다음 블록 기본 수수료·우선
수수료, 미지원 체인은 `eth_gasPrice`; 단순 전송(21,000 gas) 비용을 ETH·USD(HL ETH 오라클)로 환산, L2는 L1 데이터
수수료 제외 명시. 게이트 `CHAIN_GAS_ENABLED` + `CHAIN_RPC_{ETHEREUM,BASE,ARBITRUM}_URL`(web 전용 env, 키 내장 →
응답·로그 비노출, 호스트명만 표시). 권장 계정: **Alchemy 무료 티어** — 지원 문서(접근 2026-08-21) 월 30M CU·
500 CUPS, "sufficient for development and low-traffic production apps"; 대안 Infura/MetaMask Developer 무료
Core(일 3M 크레딧, 500/초). 우리 호출량 ≈ 체인당 2,880/일(30초 캐시) ≪ 한도. 가스 값은 공개 체인 상태이고
제공자 약관은 계정 소유자(운영자)에게 적용되므로 권리 항목은 `public_chain_state`로 기록한다.

**2026-08-22 활성화 — 운영자 Alchemy 무료 티어 계정(`DS-2026-013`).** 서버 `.env`에 `CHAIN_GAS_ENABLED=true`,
`CHAIN_RPC_PROVIDER_NAME=Alchemy`, `CHAIN_RPC_{ETHEREUM,BASE,ARBITRUM}_URL` 추가(web 전용). 라이브 확인 00:5x KST:
이더리움 유효 0.21 gwei(기본 0.11·p50 0.09, 전송 ≈ $0.01). **Base·Arbitrum은 Alchemy 앱의 네트워크가 당시 비활성**
(RPC 403 "BASE_MAINNET is not enabled for this app … /apps/<id>/networks") — **2026-08-22 15:1x KST 운영자 계정 대시보드에서 Base Mainnet·Arbitrum Mainnet 활성화 → 같은 URL로 즉시 복구(라이브: Base 0.012 gwei·전송 ≈ $0.0006, Arbitrum 0.020 gwei·≈ $0.001, 이더리움 0.65 gwei·≈ $0.03).** 원문 메모: 대시보드에서 두 네트워크를 켜면 같은
URL로 자동 복구(서버 30초 쿨다운 후 재시도). 응답에 키 미노출(호스트명만) 재확인.

```yaml
decision_id: DS-2026-013
provider_id: chain_gas
status: approved
reviewed_at: 2026-08-22
reviewer: repository owner
evidence_type: official_terms
evidence_reference: https://www.alchemy.com/support/free-tier-details (월 30M CU·500 CUPS, "sufficient for development and low-traffic production apps") + 운영자 Alchemy 계정 약관 수락
approved_scope:
  public_display: true          # 공개 체인 상태(기본 수수료·우선 수수료·가스 가격)의 파생 표시
  server_json_relay: true
  cache_ttl_seconds: 30
  stale_seconds: 300
  historical_storage: false
  derived_metrics: true         # 유효 가스 가격·21,000 gas 전송 비용·USD 환산(HL ETH 오라클)
  advertising: true
attribution: "RPC: Alchemy (운영자 계정)" — 로고 없음, URL·키 비노출
expires_at: null
recheck_at: 2026-11-22
notes: "퍼블릭 RPC 미사용. 제공자 약관은 운영자 계정에 귀속. Base·Arbitrum은 앱 네트워크 활성화 후 자동 표시."
```

### 3.22 ClinicalTrials.gov API v2 — 워치리스트 임상 파이프라인 (바이오 섹션)

| 항목 | 기록 |
|---|---|
| 내부 ID | `clinicaltrials` |
| 현재 상태 | **`approved` (2026-08-22, `DS-2026-014`)** — 미 연방(NIH/NLM) 공공 데이터베이스, 약관의 4가지 표시 의무를 응답·화면에 구현. **서버 게이트 ON(2026-08-22 13:52 KST 첫 블롭: 34 스폰서·오류 0·처리일 2026-08-21, 라이브 확인)** |
| 코드 위치 | `app/providers/clinicaltrials.py`, `app/bio.py`(`refresh_bio_trials`·`build_bio_trials`·`WATCHLIST`), `app/ingest.py::refresh_bio_trials`, 라우트 `/api/bio/trials`, 페이지 `/bio` |
| 게이트 | web·ingest: `BIO_SECTION_ENABLED` + `CLINICALTRIALS_ENABLED`(키 없음) |
| 현재 사용 | `GET /api/v2/studies?query.lead=<스폰서>&sort=LastUpdatePostDate:desc&pageSize=25&fields=<구조화 필드만>&countTotal=true` 워치리스트 34곳 × 6시간 주기(요청 간격 0.6초) + `GET /api/v2/version`(`dataTimestamp` = 처리일). blob 저장, 요청 경로는 blob만. 표시: 최근 14일 갱신 중재 2·3상(상태·단계·일자·적응증·중재·등록 인원), 스폰서별 등록 임상 수. **서술 텍스트(요약문 등)는 요청하지 않음** |
| 기술 비용 | 0원(공개 API, 키 없음). 공식 속도 제한 수치 미게시 — 호출 ≈ 34회/6시간으로 보수 운용 |
| 공식 근거 | [Terms and Conditions](https://clinicaltrials.gov/about-site/terms-conditions) (Last updated 2023-01-31): "ClinicalTrials.gov data are available to all requesters, both within and outside the United States, at no charge." / "In any publication or distribution of these data, you should: Attribute the source of the data as ClinicalTrials.gov; Update the data such that they are current at all times; Clearly display the date the data were processed by ClinicalTrials.gov; State any modifications made to the content of the data, along with a complete description of the modifications" / "You shall not assert any proprietary rights to any portion of the database" / "The ClinicalTrials.gov data carry an international copyright outside the United States … Some ClinicalTrials.gov data may be subject to the copyright of third parties" |
| 표시 경계 | ① 출처 "Source: ClinicalTrials.gov" 값 옆·푸터 ② 6시간 갱신·`freshness` ③ `processed_date`(dataTimestamp) 표시 ④ `modifications`(워치리스트 한정·25건 샘플·2/3상 필터·필드 부분집합·한국어 표시명·상장 라벨은 Mulmit 참고 라벨) 명시. 로고 미사용, 제3자 저작 가능 서술문 비표시, 결과 해석·주가 연결 문구 금지 |

```yaml
decision_id: DS-2026-014
provider_id: clinicaltrials
status: approved
reviewed_at: 2026-08-22
reviewer: repository owner
evidence_type: official_terms
evidence_reference: https://clinicaltrials.gov/about-site/terms-conditions (2023-01-31 — 무료·국내외 이용 가능, 배포 시 출처·최신성·처리일·수정 명시 의무)
approved_scope:
  public_display: true
  server_json_relay: true
  narrative_text: false
conditions:
  - attribution "ClinicalTrials.gov" adjacent to values and in footer
  - data refreshed on a fixed 6h cadence with freshness shown
  - date processed by ClinicalTrials.gov shown with the values
  - modifications (watchlist filter, phase filter, field subset, Mulmit labels) stated in the payload and on the page
  - no proprietary claim; no narrative text; no outcome or price interpretation
gate: BIO_SECTION_ENABLED + CLINICALTRIALS_ENABLED
recheck_on: 2026-11-22
```

### 3.23 openFDA — `drug/drugsfda` 원 신청 승인 (바이오 섹션)

| 항목 | 기록 |
|---|---|
| 내부 ID | `openfda` |
| 현재 상태 | **`approved` (2026-08-22, `DS-2026-015`)** — 공개 도메인(CC0 1.0). **서버 게이트 ON(2026-08-22 13:52 KST 첫 블롭: 60일 창 ORIG 140건·7페이지, 라이브 확인)** |
| 코드 위치 | `app/providers/openfda.py`, `app/bio.py`(`refresh_bio_fda`·`build_bio_fda`), `app/ingest.py::refresh_bio_fda`, 라우트 `/api/bio/fda` |
| 게이트 | web·ingest: `BIO_SECTION_ENABLED` + `OPENFDA_ENABLED`; 선택 `OPENFDA_API_KEY`(ingest 전용, 무료) |
| 현재 사용 | `GET https://api.fda.gov/drug/drugsfda.json?search=submissions.submission_status:AP+AND+submissions.submission_type:ORIG+AND+submissions.submission_status_date:[start TO end]&limit=100` 최근 60일 창, 하루 1회(최대 5페이지). 표시: NDA·BLA 원 신청 승인 목록(승인일·신청번호·브랜드/성분·스폰서·제출 분류·심사 우선순위·Drugs@FDA 링크), ANDA는 건수 |
| 기술 비용 | 0원. 한도: 키 없음 240 req/분·1,000/일(IP), 키 240/분·120,000/일 |
| 공식 근거 | [License](https://open.fda.gov/license/) (2014-05-27): "the content, data, documentation, code, and related materials on openFDA is public domain and made available with a Creative Commons CC0 1.0 Universal dedication." [Terms](https://open.fda.gov/terms/): "You can copy, modify, distribute, and perform the work, even for commercial purposes, all without asking permission." / "While not required … we ask that proper credit be given." 응답 meta.disclaimer: "Do not rely on openFDA to make decisions regarding medical care. … you should assume all results are unvalidated." 단 GMDN(의료기기 용어)은 별도 라이선스 — 의약품 데이터만 사용 |
| 표시 경계 | 출처 "Source: openFDA (U.S. FDA) — public domain, CC0 1.0" + 라이선스 링크 + 게시자 면책 문구 동봉, 로고 미사용, 매출·주가 해석 금지 |

```yaml
decision_id: DS-2026-015
provider_id: openfda
status: approved
reviewed_at: 2026-08-22
reviewer: repository owner
evidence_type: official_terms
evidence_reference: https://open.fda.gov/license/ (CC0 1.0 Universal) + https://open.fda.gov/terms/ (commercial use allowed without permission; credit requested)
approved_scope:
  public_display: true
  server_json_relay: true
conditions:
  - credit "openFDA (U.S. FDA)" with the license link adjacent to values
  - relay the publisher disclaimer with the values
  - drug data only (no GMDN device terminology)
gate: BIO_SECTION_ENABLED + OPENFDA_ENABLED
recheck_on: 2026-11-22
```

### 3.24 Federal Register API — FDA 자문위원회 회의 공고 (바이오 섹션 Phase 2)

| 항목 | 기록 |
|---|---|
| 내부 ID | `federal_register` |
| 현재 상태 | **`approved` (2026-08-22, `DS-2026-016`)** — 미 정부 간행물(연방관보, OFR/NARA·GPO)로 저작권 없음(17 U.S.C. §105). **서버 게이트 ON(2026-08-22 14:27 KST 첫 블롭: 공고 11건·예정 2, 라이브 확인)** |
| 코드 위치 | `app/providers/federal_register.py`, `app/bio.py`(`refresh_bio_adcomm`·`build_bio_adcomm`), `app/ingest.py::refresh_bio_adcomm`, 라우트 `/api/bio/adcomm` |
| 게이트 | web·ingest: `BIO_SECTION_ENABLED` + `FEDERAL_REGISTER_ENABLED`(키 없음) |
| 현재 사용 | `GET /api/v1/documents.json?conditions[agencies][]=food-and-drug-administration&conditions[type][]=NOTICE&conditions[term]="advisory committee"&conditions[publication_date][gte]=<240일 전>&per_page=100&fields[]=…` 6시간 주기 1~3페이지. 제목에 위원회명+회의 공고 문구가 있는 건만, 회의일은 DATES 단락에서 추출. 표시: 예정 회의·최근 30일 종료·날짜 미기재 공고(제목·위원회·공고일·링크) |
| 기술 비용 | 0원 |
| 공식 근거 | [Developer Resources](https://www.federalregister.gov/reader-aids/developer-resources/rest-api) (접근 2026-08-22): "No API keys are needed; all you need is an HTTP client or browser." / "Usage Restrictions: Republishers of Federal Register material are not permitted to use official NARA or OFR logos or seals." 연방관보 문서는 미 정부 저작물 |
| 표시 경계 | 출처 "Federal Register (Office of the Federal Register, NARA)" + 공고 링크, 로고·인장 미사용, 자문위 결론·승인·주가 해석 금지 |
| 왜 FDA 사이트가 아닌가 | fda.gov 자문위 달력 페이지는 봇 감지(abuse-detection/excessive-requests apology 리다이렉트, robots.txt도 동일) → "봇차단 우회 금지" 원칙상 서버 수집 보류. RSS 없음. 연방관보가 같은 공고의 1차 출처 |

```yaml
decision_id: DS-2026-016
provider_id: federal_register
status: approved
reviewed_at: 2026-08-22
reviewer: repository owner
evidence_type: official_terms
evidence_reference: https://www.federalregister.gov/reader-aids/developer-resources/rest-api (키 불요, 로고·인장 금지만; 미 정부 간행물)
approved_scope:
  public_display: true
  server_json_relay: true
conditions:
  - attribution to the Federal Register with a link to each notice
  - no NARA or OFR logos or seals
  - schedule only; no committee-outcome or price interpretation
gate: BIO_SECTION_ENABLED + FEDERAL_REGISTER_ENABLED
recheck_on: 2026-11-22
```

### 3.25 NCBI E-utilities (PubMed) — 임상별 논문 서지 (바이오 섹션 Phase 2)

| 항목 | 기록 |
|---|---|
| 내부 ID | `pubmed` |
| 현재 상태 | **`approved` (2026-08-22, `DS-2026-017`, 메타데이터 한정)** — 서지 정보(제목·저널·일자·출판 유형·PMID/DOI)만, 초록 미요청. **서버 게이트 ON(2026-08-22 14:27 KST 첫 패스: 150건 검색·적중 34·실패 0, ET 주말 창, 라이브 확인)** |
| 코드 위치 | `app/providers/pubmed.py`, `app/bio.py`(`refresh_bio_pubmed`·`pubmed_window_open`·임상 표 병합), `app/ingest.py::refresh_bio_pubmed`, 응답 `/api/bio/trials`의 `recent[].publications`·`pubmed` |
| 게이트 | web·ingest: `BIO_SECTION_ENABLED` + `CLINICALTRIALS_ENABLED` + `PUBMED_ENABLED`; 선택 `NCBI_EMAIL`(정책상 연락처)·`NCBI_API_KEY`(10 req/s) — ingest 전용 |
| 현재 사용 | 임상 표의 행(≤150건)마다 `esearch.fcgi?db=pubmed&term=NCT…[si]&retmax=3&sort=pub_date&tool=mulmit[&email]` + `esummary.fcgi`(PMID 50개 묶음) — 하루 1회, **ET 21~05시·주말 창에서만**(`PUBMED_OFFPEAK_ONLY`), 요청 간격 0.4초. 60일 내 이전 결과는 이월 |
| 기술 비용 | 0원 |
| 공식 근거 | [E-utilities Usage Guidelines](https://www.ncbi.nlm.nih.gov/books/NBK25497/): "post no more than three URL requests per second"(키 있으면 10) / "limit large jobs to either weekends or between 9:00 PM and 5:00 AM Eastern time during weekdays" / tool·email 등록 / "abstracts in PubMed may incorporate material that may be protected by U.S. and foreign copyright laws. All persons reproducing, redistributing, or making commercial use of this information are expected to adhere to the terms and conditions asserted by the copyright holder." |
| 표시 경계 | 출처 "PubMed (NCBI / NLM)" 값 옆·푸터, **초록 비표시**, 논문 건수·상위 1건 제목/저널/일자 + PubMed 검색 링크(`?term=NCT…[si]`), 해석 문구 금지 |

```yaml
decision_id: DS-2026-017
provider_id: pubmed
status: approved
reviewed_at: 2026-08-22
reviewer: repository owner
evidence_type: official_policy
evidence_reference: https://www.ncbi.nlm.nih.gov/books/NBK25497/ (3 req/s, 야간 창, tool/email; 초록 저작권 주의)
approved_scope:
  public_display: true
  server_json_relay: true
  abstracts: false
conditions:
  - citation metadata only (title, journal, dates, publication types, identifiers); no abstracts
  - requests identified with tool (and email when configured), paced at or below 3 per second, run in NCBI's off-peak window
  - attribution "PubMed (NCBI / NLM)" next to the values
gate: BIO_SECTION_ENABLED + CLINICALTRIALS_ENABLED + PUBMED_ENABLED
recheck_on: 2026-11-22
```

### 3.26 식품의약품안전처 의약품 제품 허가정보 (공공데이터포털) — 바이오 섹션 Phase 2

| 항목 | 기록 |
|---|---|
| 내부 ID | `mfds_drug_permit` |
| 현재 상태 | **`approved` (2026-08-22, `DS-2026-018`)** — 운영자 활용신청 승인(2026-08-22, 개발계정 자동승인), 같은 계정 키로 실측 완료. **서버 게이트 ON(2026-08-22 15:3x KST 첫 블롭: 30일 112품목·허가 72·신고 40·신약 1·희귀 2·실패 0, 라이브 확인)** |
| 코드 위치(Coinalyze) | `app/providers/coinalyze.py`, `app/crypto_liquidations.py`, `app/ingest.py::refresh_crypto_liquidations`, 라우트 `/api/crypto/liquidations`, `/crypto` 청산 집계 섹션 |
| 실측 (2026-08-22) | BTC 24h 롱 $63.6M·숏 $51.8M(롱 55.1%), ETH 롱 $76.9M·숏 $91.6M. 청산 응답 거래소 **Binance·Bybit·OKX·Huobi·BitMEX**, OI 응답 **Binance·Bybit·OKX·Hyperliquid**. BTC 퍼프 시장은 28개인데 청산을 주는 곳은 이 5곳뿐이고 나머지는 `200 []` |
| 코드 위치 | `app/providers/mfds.py`, `app/bio.py`(`refresh_bio_mfds`·`build_bio_mfds`), `app/ingest.py::refresh_bio_mfds`, 라우트 `/api/bio/mfds` |
| 게이트 | web·ingest: `BIO_SECTION_ENABLED` + `MFDS_ENABLED`; ingest 수집: + `MFDS_API_KEY`(비우면 `FSC_API_KEY` 사용 — data.go.kr 키는 계정 단위) |
| 데이터셋 | [식품의약품안전처_의약품 제품 허가정보](https://www.data.go.kr/data/15095677/openapi.do) (수정일 2025-10-31, 활용신청 5,350건). Base URL `apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService07`, 엔드포인트 `GET /getDrugPrdtPrmsnInq07`(의약품 제품 허가 목록)·`/getDrugPrdtPrmsnDtlInq06`(상세)·`/getDrugPrdtMcpnDtlInq07`(주성분), JSON/XML |
| 이용 조건(포털 표기, 접근 2026-08-22) | 비용 **무료**, 이용허락범위 **"이용허락범위 제한 없음"**(§3.9 FSC와 동일 등급), 심의 "개발단계: 자동승인 / 운영단계: 심의승인", 트래픽 개발계정 10,000/일 |
| 현재 사용 | `GET /getDrugPrdtPrmsnDtlInq06?type=json&numOfRows=100&pageNo=n&item_permit_date=YYYYMMDD` — 한국시간 기준 최근 30일을 하루씩(≈30회/일, 바쁜 날 페이징) 하루 1회. 실측(서버 ingest, 2026-08-22): 목록 엔드포인트는 날짜 필터 무시·날짜순 아님, **상세 엔드포인트만 `item_permit_date` 필터 동작**(06-30 → 62건, 08-21 → 9건, 08-20 → 2건); 오류는 `OpenAPI_ServiceResponse.cmmMsgHeader.returnReasonCode`(30 미등록 키, 22 호출 초과) 또는 `header.resultCode`. 표시: 허가일·품목명(영문)·업체·전문/일반·허가/신고·신약 구분·희귀 여부·주성분(성분코드 제거)·취하/취소, 의약품안전나라 상세 링크(`nedrug.mfds.go.kr/pbp/CCBBB01/getItemDetailCache?cacheSeq=`) |
| 기술 비용 | 0원(개발계정 10,000/일 중 ≈30) |
| 표시 경계 | 출처 "식품의약품안전처 의약품 제품 허가정보 (공공데이터포털)" + 데이터셋 링크를 값 옆·푸터에, 등록값 그대로(신약 여부는 식약처 구분), 매출·주가 해석 금지 |

```yaml
decision_id: DS-2026-018
provider_id: mfds_drug_permit
status: approved
reviewed_at: 2026-08-22
reviewer: repository owner
evidence_type: official_terms
evidence_reference: https://www.data.go.kr/data/15095677/openapi.do (비용 무료 · 이용허락범위 제한 없음 · 개발단계 자동승인; 운영자 활용신청 승인 2026-08-22)
approved_scope:
  public_display: true
  server_json_relay: true
conditions:
  - source attribution with the dataset link next to the values
  - registered values relayed as published; no outcome or price interpretation
  - key stays in the ingest process; ≈30 calls per day
gate: BIO_SECTION_ENABLED + MFDS_ENABLED (+ MFDS_API_KEY or FSC_API_KEY in ingest)
recheck_on: 2026-11-22
```

### 3.27 Coinalyze — 거래소 집계 청산·미결제약정 (크립토 섹션)

| 항목 | 기록 |
|---|---|
| 내부 ID | `coinalyze` |
| 현재 상태 | **`approved` (2026-08-22, `DS-2026-019`)** — 운영자 문의(2026-08-21 15:05Z)에 대한 **서면 회신**(contact@coinalyze.net, 2026-08-22 08:59Z). 키 발급 후 실측하고 **레인 구현 완료**(2026-08-22), 게이트는 기본 OFF |
| 회신 원문 | "Yes, you can use our API for your project. Regarding the attribution, the link(s) to Coinalyze website must be a **dofollow** link." |
| 승인된 범위 | 문의에 열거한 그대로다. ① 거래소 집계 청산 합계(최근 1h/24h, 롱·숏 분리)와 미결제약정을 BTC·ETH 등 소수 코인에 대해 5분 주기로 표시 ② 우리 서버 JSON 엔드포인트로 중계(비인증·벌크 내보내기 없음), 최대 5분 캐시, 차트용 일별 집계는 **비공개 저장** ③ 값 옆 "Data: Coinalyze" + 사이트 링크 ④ 광고가 붙어도 동일 |
| 조건 | **링크는 dofollow여야 한다** — `rel`에 `nofollow`·`ugc`·`sponsored`를 붙이지 않는다. 현 코드베이스의 외부 링크는 전부 `rel="noopener noreferrer"`(dofollow)이라 이미 충족하며, 회귀를 막는 테스트를 뒀다(`tests/test_outbound_links.py`) |
| 회신이 **다루지 않은 것** | 문의 4항(집계 대상 거래소들이 이런 공개 표시에 조건을 두는지)에는 따로 답하지 않았다. 이 승인은 **Coinalyze 자신의 API에 대한 것**이며, 하위 거래소 권리를 이전하거나 면책한 것이 아니다. 우리가 싣는 것은 특정 거래소의 원시 피드가 아니라 **Coinalyze가 계산한 집계값**이라는 전제로 진행하고, 재확인일에 다시 본다 |
| 게이트 | `CRYPTO_SECTION_ENABLED` + `COINALYZE_ENABLED` + `COINALYZE_API_KEY` (기본 OFF, 키는 ingest 프로세스에만) |
| 기술 비용 | 0원. 키당 **40 call/분**. ⚠️ **심볼 1개 = 호출 1회** — `symbols`는 콤마로 최대 20개를 받지만 문서상 "each symbol consume one API call"이다. 코인 10종을 한 번에 물으면 요청은 1건이어도 예산은 10회가 빠진다. 수집 틱(`INGEST_INTERVAL` 기본 15분)마다 2코인 약 19회라 분당 1.3회꼴로 여유가 있으나, **거래소별 심볼을 합산해 집계를 만들 생각이면 비용이 심볼 수만큼 곱해진다** — 집계 심볼이 따로 있는지는 키가 있어야 `/future-markets`로 확인된다 |
| 측정된 API 계약 (2026-08-22, 스펙 원문) | base `https://api.coinalyze.net/v1`. 인증은 `api_key` **헤더 또는 쿼리 파라미터**(문서: "The name of the header/query parameter is api_key"). 키는 **로그인 후 `/v1/doc/` 페이지에서 생성**한다. `GET /liquidation-history?symbols=&interval=&from=&to=&convert_to_usd=` → `[{symbol, history:[{t(초), l(롱 청산량), s(숏 청산량)}]}]`. `GET /open-interest?symbols=&convert_to_usd=` → `[{symbol, value, update(ms)}]`. `GET /open-interest-history` → `[{symbol, history:[{t,o,h,l,c}]}]`. `interval` enum: 1min·5min·15min·30min·1hour·2hour·4hour·6hour·12hour·daily. `/future-markets` → `{symbol, exchange, base_asset, quote_asset, is_perpetual, oi_lq_vol_denominated_in(BASE_ASSET|QUOTE_ASSET|CONTRACTS), …}` — **단위가 심볼마다 다르므로 `convert_to_usd=true`로 통일하고, 그 사실을 값 옆에 적는다** |
| 표시 경계 | **집계값이며 틱 피드가 아니다** — "지난 1분 청산액" 같은 실시간 표기를 하지 않고, 집계 주기와 지연을 값 옆에 적는다(§PLAN_CRYPTO_SECTION.md #6에서 Binance 직결을 기각한 것과 같은 이유). 값은 받은 그대로, 해석·예측 없이 |

```yaml
decision_id: DS-2026-019
provider_id: coinalyze
status: approved
reviewed_at: 2026-08-22
reviewer: repository owner
evidence_type: written_permission
evidence_reference: email from contact@coinalyze.net, 2026-08-22T08:59:24Z, replying to the operator's five-point question of 2026-08-21T15:05:41Z
approved_scope:
  public_display: true
  server_json_relay: true
  private_daily_aggregates: true
  advertising_supported_site: true
conditions:
  - attribution link to coinalyze.net must be dofollow (no nofollow, ugc or sponsored)
  - aggregates only, labelled as aggregates with their interval and lag; never presented as a live tick feed
  - cache at most five minutes; no bulk export endpoint
  - key stays in the ingest process; 40 calls per minute per key
open_questions:
  - sub-exchange conditions were asked about and not separately answered; this grant is Coinalyze's own
gate: CRYPTO_SECTION_ENABLED + COINALYZE_ENABLED + COINALYZE_API_KEY
recheck_on: 2026-11-22
```

## 4. 원 발행기관 후보

아래 표의 `pending_review`는 무료라고 단정하는 표시가 아니다. 다음 세션에서 정확한 endpoint, 이용조건, attribution, 저장·캐시·제3자 표시 범위를 다시 확인한 뒤 series 단위로 승인한다.

| 내부 provider 후보 | 대상 카드/계열 | 예상 형식 | 상태 | 공식 시작점 | 구현 우선순위 |
|---|---|---|---|---|---:|
| `nyfed` | SOFR, EFFR, RRP | CSV/XML/API 후보 | `pending_review` | [Reference Rates](https://www.newyorkfed.org/markets/reference-rates), [Terms](https://www.newyorkfed.org/privacy/termsofuse.html) | 1 |
| `bls` | 미국 실업률 | JSON API | `pending_review` | [BLS Public Data API](https://www.bls.gov/developers/home.htm) | 1 |
| `eia` | WTI 일간 현물 | JSON API v2 | `pending_review` | [EIA API documentation](https://www.eia.gov/opendata/documentation.php), [Terms](https://www.eia.gov/opendata/terms-of-service.php) | 1 |
| `federal_reserve` | 2Y/10Y, IORB, H.4.1, H.6 후보 | XML/CSV | `pending_review` | [Federal Reserve Data Download](https://www.federalreserve.gov/data.htm), [DDP transition notice](https://www.federalreserve.gov/data/data-download-fred-information.htm) | 2 |
| `dol_eta` | 신규 실업수당 | CSV/Excel/API 후보 | `pending_review` | [DOL ETA UI data](https://oui.doleta.gov/unemploy/claims.asp) | 2 |
| `treasury_fiscal_data` | TGA/재정 데이터 후보 | JSON API | `pending_review` | [Fiscal Data](https://fiscaldata.treasury.gov/) | 2 |
| `ofr` | 금융스트레스지수(종합·변동성·신용 등) | CSV | **`approved` (§3.17, 2026-08-21)** | [OFR FSI](https://www.financialresearch.gov/financial-stress-index/), [Legal Notices](https://www.financialresearch.gov/legal-notices/) | 완료 |
| `bok_ecos` | USD/KRW와 한국 거시 후보 | JSON/XML | `pending_review` | [한국은행 ECOS](https://ecos.bok.or.kr/api/) | 3 |

Fed Board DDP의 일부 데이터 전달 경로는 전환 공지가 있으므로 신규 구현 시 종료 일정과 공식 대체 경로를 다시 확인한다. 특정 FRED series ID를 그대로 복제하는 것이 아니라 원 발행기관의 원 series와 단위를 검증한다.

### 4.1 서면 문의 대기 목록

코드로 풀 수 없고 회신이 있어야 열리는 항목만 모았다. 우선순위는 회신이 열어 주는
화면의 크기 순이다.

| 수신처 | 막고 있는 것 | 상태 | 초안 |
|---|---|---|---|
| trade.xyz **및** Hyperliquid (수신처 2곳) | 자산 카드 전체의 역사 차트. `historical_storage: false`라 현재는 최신값만 보인다 | **Hyperliquid 지원팀 회신 2026-08-18**: 플랫폼은 permissionless이며 공개 API 조회는 누구나 가능, 기술 문의는 Discord, **HIP-3 피드 관련은 xyz 팀에 직접 문의하라고 안내** — 권리 판단을 바꾸는 명시적 허락은 아니다. **xyz 회신 대기 유지**. 2026-08-21 운영자 재확인 — 발송(08-17) 후 4일째 무응답, 같은 메일을 xyz 허가로 오인하지 않도록 여기 명시. 같은 날 DS-2026-001 개정: 무응답은 OFF 사유가 아니고 명시적 거절만 OFF, 이력 차트는 운영자 위험 수용으로 개방(§3.1). 재발송 검토일 2026-08-31(+14일). `recheck_at: 2026-09-16`은 재검토일 | [`INQUIRY_HYPERLIQUID_TRADE_XYZ.md`](INQUIRY_HYPERLIQUID_TRADE_XYZ.md) |
| Federal Reserve Bank of St. Louis | `financial_stress`(STLFSI4). 뉴욕 연준과 같은 구조 — 연방기관이 아니라 저작권을 주장하지만, 명시적 이용허락을 주는지가 관건이다. 시리즈 태그가 "Copyrighted: Citation Required"(2026-08-17 확인)라 인용이 완결 조건인지 서면으로 묻는다. FRED 경유 복제는 하지 않는다 | **회신 수신 2026-08-18 — 조건부 승인** (조건과 구현은 §3.3에 기록). 이 항목은 종결 | [`INQUIRY_STLOUISFED_STLFSI.md`](INQUIRY_STLOUISFED_STLFSI.md) |
| 한국거래소 | 실시간 시세와 KRX 통계정보 전체(§3.4). 장 마감값은 §3.9로 이미 해결됨 | 초안 없음. 우선순위 낮아짐 | — |
| Cboe | VIX·SKEW·VVIX·OVX·Put/Call | 서면 허가가 명시적으로 필요하고 월 예산 안의 근거가 없어 **문의하지 않기로** 결정 | — |
| Deribit (info@deribit.com) | BTC·ETH DVOL(크립토 내재변동성). ToS §4.6 "Market Data … is for personal use only … without explicit approval from us" — 서면 승인 전 `pending_rights`, 값 비공개 | **발송 2026-08-22 (운영자 Gmail)**. 무응답 시 위험수용 안 함(약관이 개인 용도를 명시). 회신 기한 2026-09-16 | [`INQUIRY_CRYPTO_SOURCES.md`](INQUIRY_CRYPTO_SOURCES.md) §1 |
| 두나무(업비트 Open API) | KRW 시세·김치프리미엄(USDT 분모로 실시간 환율 소거). Open API 이용약관(2023-12-15) §5 저작권 조항, 공개 표시 허가·금지 조항 없음. Origin 요청 10초 1회라 서버 relay 전제 | **운영자 위험수용으로 개방(2026-08-22, DS-2026-012, §3.19)**. 1:1 문의는 기록용 발송(지원센터 폼) — 회신 시 갱신, 거절 시 즉시 OFF | [`INQUIRY_CRYPTO_SOURCES.md`](INQUIRY_CRYPTO_SOURCES.md) §2 |
| Coinalyze (contact@coinalyze.net) | 거래소 집계 청산(1h/24h)·OI 히스토리 | ✅ **회신·승인 2026-08-22** — 조건은 dofollow 링크 하나. 하위 거래소 권리는 답하지 않음. §3.27 `DS-2026-019` | [`INQUIRY_CRYPTO_SOURCES.md`](INQUIRY_CRYPTO_SOURCES.md) §3 |

뉴욕 연준 사례가 이 목록의 근거다. 약관을 실제로 읽기 전에는 “연준 계열이니
공개겠지”와 “저작권을 주장하니 못 쓰겠지” 둘 다 추측이었고, 실제 약관은 저작권을
주장하면서 동시에 우리가 필요한 범위를 명시적으로 허락하고 있었다.

## 5. 카드별 source 계획

`UI key`는 `app/static/monitor.js`의 `METRICS` 항목 키와 정확히 같은 문자열이다.
프런트가 API 레코드를 카드에 붙일 때 쓰는 `aliases`도 함께 적었다. 이 표의 키를
임의로 줄여 쓰면 카드가 영원히 `missing`으로 남는다.

### 5.1 자산 카드

| UI key | 매칭 alias | 현재 소스 | 정확성/권리 상태 | 다음 결정 |
|---|---|---|---|---|
| `sp500` | `sp500`, `spy` | `xyz:SP500` | 합성 proxy, HIP-3 권리 확인 중 | 승인 시 proxy 유지; exact 지수/ETF 가격은 별도 라이선스 |
| `nasdaq` | `nasdaq`, `qqq` | `xyz:XYZ100` | Nasdaq 대용 합성값 | 공식 Nasdaq Composite/100으로 표기 금지 |
| `gold` | `gold`, `xauusd` | `xyz:GOLD` | 합성 proxy | 승인 범위 확인 |
| `bitcoin` | `bitcoin`, `btc` | 없음 | missing | HIP-3 main DEX BTC 경로와 외부 표시 권리를 함께 검토 |
| `kospi` | `kospi`, `^ks11` | `xyz:KR200` | KOSPI 200 대용 합성값 | 공식 종가는 `kospi_exact`로 **연결됨**(`DS-2026-006`). 이 카드는 그대로 둔다 |
| `kosdaq` | `kosdaq`, `^kq11` | 없음 | missing | HIP-3 대용값이 없다. 공식 종가는 `kosdaq_exact`로 **연결됨**. 영구 공석이라 섹션에서 카드 제거(METRICS 정의는 유지) |
| `samsung` | `samsung`, `005930.ks` | `xyz:SMSN` | USD/USDC 환산 합성 무기한선물 | alias `005930` **제거됨**. 그 코드는 이제 `samsung_exact`(원화 공식 종가)를 식별하므로 두 카드가 한 레코드를 집으면 안 된다 |
| `usdkrw` | `usdkrw`, `krw=x` | `xyz:KRW` **상장폐지** | missing | 공식 환율은 아래 `fx_usdkrw`로 연결됨 |
| `ewz` | `ewz`, `brazil` | `xyz:EWZ` | ETF-linked 합성값 | 권리 승인 전 gate |
| `inda` | `inda`, `india` | `xyz:NIFTY` 가능 시 | INDA가 아닌 NIFTY 50 대용값 | 카드 라벨이 현재 `인도 INDA`이므로 NIFTY 대용값을 붙이면 라벨부터 고친다 |
| `vnm` | `vnm`, `vietnam` | 없음 | missing | 승인 소스 전 비워 둠 |
| `ewj` | `ewj`, `japan` | `xyz:EWJ` | ETF-linked 합성값 | 권리 승인 전 gate |
| `dxy` | `dxy`, `dollar_index` | 상품 활성 여부에 따라 missing | 공식 ICE DXY 아님 | exact DXY는 ICE 권리 필요. 표시 가능한 대안으로 `dollar_index_broad`(Fed Board)를 **연결함** — 대체가 아니라 다른 지수다 |
| `usdjpy` | `usdjpy`, `jpy=x` | `xyz:JPY` | 합성 FX reference | 방향·통화 단위 검증 유지 |
| `vix` | `vix`, `vixcls` | `xyz:VIX` — **상장폐지** (`isDelisted: true`, 마크 20.0 동결·OI 0·거래대금 0, 2026-08-21 라이브 확인. `xyz:VOL`·`xyz:DXY`·`xyz:KRW`도 같은 상태) | missing — 코드가 delisted 컨텍스트를 자동 제외하고 카드는 `license_required` 플레이스홀더로 남는다 | proxy 경로 **종결**. 공식값은 Cboe CGI(월 $1,000~) 밖이라 계속 `license_required` |
| `wti` | `wti`, `dcoilwtico`, `cl=f` | `xyz:CL` | 공식 현물/결제값 아님 | EIA 공식값이 붙으면 `wti_exact` 신규 key로 분리 |
| `copper` | `copper`, `pcoppusdm`, `hg=f` | `xyz:COPPER` | 합성 proxy | IMF 공식값은 `copper_exact` 신규 key로 분리 |
| `sentiment` | `sentiment`, `fear_greed` | 없음 | missing | 권리 확인된 입력만으로 `Mulmit Market Sentiment` 자체 산식 |

`vix`, `wti`, `copper`의 alias에 `vixcls`, `dcoilwtico`, `pcoppusdm`이 들어 있어
FRED 계열이 들어오면 HIP-3 proxy 카드와 같은 자리를 다툰다. 공식 lane을 열 때는
alias를 정리해 proxy와 exact가 서로 다른 카드에 붙도록 먼저 분리한다.

### 5.2 거시·유동성 카드

`UI key`는 `METRICS` 키, `기존 ID`는 현재 FRED 카탈로그의 series id다. 둘이 다른
행이 많으므로 그대로 옮겨 적는다.

| UI key | 기존 ID | 원 발행기관 후보 | 상태 | 메모 |
|---|---|---|---|---|
| `yield_curve` | `RIFLGFCY10_N.B - RIFLGFCY02_N.B` | **Fed Board (계산됨)** | `approved` | 양쪽이 모두 게시한 날짜로만 계산 |
| `financial_stress` | `STLFSI4` | **St. Louis Fed 서면 허가 (2026-08-18)** | `approved` | FRED API 경유 수집, 지정 인용문+접근일 표기, 접근 유료화 금지, 로고·보증 암시 금지 (§3.3) |
| `dollar_index_broad` | `JRXWTFB_N.B` | **Fed Board H.10 (연결됨)** | `approved` | 교역가중 광의 달러지수, 2006=100. ICE `dxy`와 별도 카드이며 값 비교 불가 |
| `dollar_index_afe` | `JRXWTFN_N.B` | **Fed Board H.10 (연결됨)** | `approved` | 선진 교역상대국 |
| `dollar_index_eme` | `JRXWTFO_N.B` | **Fed Board H.10 (연결됨)** | `approved` | 신흥 교역상대국 |
| `treasury_10y` | `RIFLGFCY10_N.B` | **Fed Board H.15 (연결됨)** | `approved` | 2001~ 일별. `DS-2026-004` |
| `treasury_2y`(신규) | `RIFLGFCY02_N.B` | **Fed Board H.15 (연결됨)** | `approved` | 10Y−2Y 계산의 입력이자 자체 카드 |
| `m2` | `M2.M` | **Fed Board H.6 (연결됨)** | `approved` | 계절조정 월간, **십억 달러** 단위 |
| `unemployment` | `LNS14000000` | **BLS (연결됨)** | `approved` | 계절조정 월간. `DS-2026-005` |
| `initial_claims` | `ICSA` | DOL ETA | `pending_review` | 주간, revised 값 처리 |
| `fed_assets` | `RESPPA_N.WW` | **Fed Board H.4.1 (연결됨)** | `approved` | 백만 달러 단위. 6.76T |
| `reserve_balances` | `RESH4R_N.WW` | **Fed Board H.4.1 (연결됨)** | `approved` | 2.95T |
| `reverse_repo` | `RRP` | **New York Fed (연결됨)** | `approved` | 익일물 낙찰 총액. **단위가 달러**이며 FRED의 십억 달러와 다름 |
| `treasury_general_account` | `RESPPLLDT_N.WW` | **Fed Board H.4.1 (연결됨)** | `approved` | 지구별 합계(TOT). 0.96T |
| `retail_money_market_funds` | `MMFGB.M` | **Fed Board H.6 (연결됨)** | `approved` | 리테일 전용. 기관형(`MMFIN`)은 2021년 중단 |
| `sofr` | `SOFR` | **New York Fed (연결됨)** | `approved` | 2018-04-02~ 일별. `DS-2026-003` |
| `effective_fed_funds` | `EFFR` | **New York Fed (연결됨)** | `approved` | 2016~ 일별. percentile/volume과 target rate 혼동 금지 |
| `reserve_interest` | `IORB` | Federal Reserve Board | `pending_review` | 정책 시행일 기준 step series |
| `high_yield_spread` | `BAMLH0A0HYM2` | ICE Data Indices | `license_required` | 2026-08-21부터 공개 페이지에서 **숨김**. 신용 스트레스 역할은 `ofr_fsi_credit`(§3.17)이 맡는다 |
| `ofr_fsi` / `ofr_fsi_volatility` / `ofr_fsi_credit` (+funding·safe_assets·equity_valuation) | `OFR_FSI*` | **미 재무부 OFR (연방 저작물)** | `approved` | §3.17. 일별, 2영업일 지연. 변동성 범주가 VIX 계열, 신용 범주가 스프레드 계열의 권리 깨끗한 대체 — "VIX 자체 아님" 명시 |
| `wti_exact`(신규) | `DCOILWTICO` | EIA `PET.RWTC.D` 후보 | `pending_review` | exact endpoint·units 재검증. `wti` proxy 카드와 별도 key |
| `vix_exact`(신규) | `VIXCLS` | Cboe | `license_required` | FRED를 통해 공개하지 않음. `vix` 카드는 2026-08-21부터 숨김; 변동성 역할은 `ofr_fsi_volatility`(§3.17) |
| `copper_exact`(신규) | `PCOPPUSDM` | IMF | `pending_review` | 직접 이용조건 확인 후 결정. `copper` proxy 카드와 별도 key |
| `kospi_exact` | 없음 | **금융위원회 공공데이터 (연결됨)** | `approved` | KOSPI 공식 종가. T+1 공개. `kospi`(HIP-3 KR200)와 별도 key. `DS-2026-006` |
| `kosdaq_exact` | 없음 | **금융위원회 공공데이터 (연결됨)** | `approved` | KOSDAQ 공식 종가. HIP-3 대용값이 없어 유일한 소스 |
| `samsung_exact` | 없음 | **금융위원회 공공데이터 (연결됨)** | `approved` | 삼성전자 **원화** 종가. `samsung`(USD 합성)과 단위부터 다르다 |
| `sk_hynix_exact` | 없음 | **금융위원회 공공데이터 (연결됨)** | `approved` | SK하이닉스 원화 종가 |

`*_exact` 키는 아직 `METRICS`에 없다. 공식 lane을 여는 PR에서 `METRICS`,
`SECTIONS`, `OVERVIEW`에 함께 추가하고 proxy 카드는 그대로 둔다. 공식값이
생겼다고 proxy 카드를 덮어쓰지 않는다.

### 5.3 환율 카드 (Fed Board H.10, 연결됨)

| UI key | 계열 | 방향 | 최근값 예시 |
|---|---|---|---|
| `fx_usdkrw` | `RXI_N.B.KO` | 달러당 원 | 1,409.94 |
| `fx_usdjpy` | `RXI_N.B.JA` | 달러당 엔 | 157.54 |
| `fx_usdcny` | `RXI_N.B.CH` | 달러당 위안 | 6.7474 |
| `fx_eurusd` | `RXI$US_N.B.EU` | **유로당 달러** | 1.1559 |
| `fx_gbpusd` | `RXI$US_N.B.UK` | **파운드당 달러** | 1.3498 |

앞의 셋과 뒤의 둘은 방향이 반대다. 화면과 API 모두 `units`에 방향을 문장으로 적는다.

### 5.4 Mulmit 유동성·스트레스 지수 (자체 산출)

`GET /api/market/stress` · 코드 `app/stress_index.py`

CNN Fear & Greed는 명칭도 점수도 복제하지 않는다. 그 지수의 7개 입력 중 5개가
우리가 표시 권리를 갖지 못한 것(변동성, 풋/콜, 하이일드, 안전자산 수요, 가격
모멘텀·폭)이라, 남은 것으로 만들면 **심리 지수가 아니라 유동성·거시 스트레스
지수**가 된다. 그래서 측정하는 것의 이름을 붙였다.

| 입력 | 방향 | 근거 |
|---|---|---|
| 장단기 금리차 | 낮을수록 스트레스 | 평탄·역전은 경기 위험 반영 |
| 역레포 잔액 | 낮을수록 스트레스 | 시장으로 되돌릴 완충이 얇아짐 |
| 지급준비금 | 낮을수록 스트레스 | 결제 여력 축소 |
| 재무부 TGA | 높을수록 스트레스 | 그만큼 현금이 정부 계정에 묶임 |
| 실업률 | 높을수록 스트레스 | 경기 스트레스 |
| 원·달러 | 높을수록 스트레스 | 달러 조달 여건 |

산식 (응답의 `method`에도 동일하게 실린다):

1. 각 입력을 **최근 5년 자기 이력 안의 백분위**로 점수화한다. 고정 범위가 아니라
   자기 이력과 비교하며, 백분위라 정규성을 가정하지 않는다. 역레포처럼 강하게
   치우친 계열에 z-score를 쓰면 왜곡된다.
2. **스트레스가 큰 쪽이 항상 높아지도록** 방향을 맞춘다.
3. **동일 가중**. 가중치를 적합시킬 근거가 없으므로 적합하지 않았다는 사실을
   동일 가중으로 드러낸다.
4. 결측 입력은 **채우지 않고 제외**하며 응답에 명시한다. 입력이 3개 미만이면
   지수를 아예 산출하지 않고 구조화된 503을 반환한다.
5. 0~100으로 표시하고 100이 최대 긴축이다.

경계 조건:

- 공개할 권리가 없는 계열은 입력에서 제외된다. 합성 지수를 통해 withheld 계열을
  세탁해 내보내지 않는다(`series_values_servable` 검사).
- lane이 닫히면 그 lane의 입력도 함께 빠진다.
- **수익률 대비 백테스트는 하지 않았다.** 이 지수는 현재 여건을 자기 이력과 비교해
  요약할 뿐이며 예측이 아니다. 화면과 API의 면책에 그대로 적는다.
- 값은 다른 심리 지수와 비교할 수 없다. 화면에 그렇게 적는다.

#### 5.4.1 실현 변동성 카드 (자체 산출, 2026-08-21)

`sp500_realized_vol`·`kr200_realized_vol` — `/api/market/assets`에 파생 레코드로 동봉
(`source.derived: true`, `instrument_kind: derived_realized_volatility`). 코드
`app/market_assets.py::realized_volatility_series`.

- **입력**: 같은 응답에 이미 표시 중인 HIP-3 자산(`xyz:SP500`·`xyz:KR200`)의 일봉
  종가(§3.1 이력 lane). 외부 호출 없음.
- **산식** (응답 `derived.method`에 동일 기재): 최근 20개 일봉 종가의 로그수익률
  표본표준편차 × √252, %. 마지막 종가는 진행 중인 UTC 당일. 양수 종가 20+1개가
  안 되면 카드를 만들지 않는다(결측 보간 없음).
- **표기 규칙**: "실현 변동성"으로만 부른다. VIX·VKOSPI(내재변동성)와 **수준 비교
  금지**, 카드 설명·힌트에 "VIX가 아님" 명시. 변화는 %가 아니라 **변동성 포인트**
  (`changeMode: points`)로 표시 — 0 중심 지수(OFR FSI·STLFSI)도 같은 규칙.
- **권리**: 표시값의 산술 파생 — DS-2026-001 `derived_metrics: unconfirmed`의 범위
  안이며(변화율·세션 기준 변화와 같은 부류), 거절 회신 시 이력 lane과 함께 꺼진다.

#### 5.4.2 Mulmit 시장 심리 게이지 (자체 산출 · 실험, 2026-08-21)

`GET /api/market/sentiment` · 코드 `app/sentiment_index.py` · 카드 키 `sentiment`
(요약 띠·RISK & CREDIT) + `/us` 전용 패널(이력 차트·구성 입력 표).

§5.4가 "심리 지수가 아니라 유동성·스트레스 지수"였던 이유(변동성·신용·안전자산
입력의 권리 부재)가 2026-08-21 OFR lane(§3.17)과 HIP-3 일봉 이력(§3.1)으로 일부
해소되어, 같은 방법론 골격으로 **위험선호 게이지**를 만들었다. CNN Fear & Greed의
명칭·점수·밴드명은 복제하지 않는다 — 밴드는 위험회피/중립/위험선호로 부른다.

| 입력 | 방향 | 출처·파생 |
|---|---|---|
| S&P 500 퍼프 모멘텀 | 높을수록 위험선호 | xyz:SP500 종가 ÷ 50일 SMA − 1 (HIP-3 일봉) |
| S&P 500 퍼프 실현 변동성(20일) | 높을수록 위험회피 | §5.4.1과 동일 산식 |
| 주식 대 금 상대수익(20일) | 높을수록 위험선호 | xyz:SP500 20일 수익률 − xyz:GOLD 20일 수익률 |
| 변동성 스트레스 (OFR) | 높을수록 위험회피 | OFR FSI 변동성 범주 공표값 |
| 신용 스트레스 (OFR) | 높을수록 위험회피 | OFR FSI 신용 범주 공표값 |

산식(응답 `method`에 동일 기재): 자기 이력 백분위(OFR 5년, 퍼프 파생은 가용 이력
전체·**최소 60점**) → 위험선호가 클수록 높게 방향 정렬 → 동일 가중 평균 → 0–100.
결측·이력 부족 입력은 제외(보간 없음), 3개 미만이면 비공개(503). 최근 180일에 같은
계산을 반복해 이력을 만든다(각 입력은 해당일 이전 최신값, 7일 초과면 결측).

한계(면책문에 기재): 풋/콜·시장 폭·52주 신고가 없음, 주가 입력은 현물지수가 아닌
HIP-3 합성 퍼프, 퍼프 파생 입력은 이력이 짧아(상장 2026-03~) 백분위 기준이 얕음.
권리: 표시 중인 값의 산술 파생(§5.4.1과 같은 부류). `experimental: true`로 표기하고
`INDEX_VERSION 0.1-experimental`. 검증·가중 적합 없음.

### 5.5 옵션·심리·분석

| 기능 | 현재 상태 | 활성화 조건 |
|---|---|---|
| SKEW, VVIX, OVX, PCR | `license_required` placeholder | Cboe 등 원 권리자의 공개 표시 계약 |
| Fear & Greed | **복제하지 않음** | 대신 `Mulmit 유동성·스트레스 지수`를 자체 산출한다. 아래 참조 |
| 섹터 ETF 1D/1W/1M/1Y | legacy disabled | 승인된 EOD 역사 가격 저장소 확보 |
| 자산군 상관관계 | legacy disabled | 동일 기준의 승인 가격·환율·거래일 데이터 확보 |
| `/analytics` CAPM/MDD | legacy disabled | 조정가격, 벤치마크, 무위험수익률의 공개 사용 권리 확보 |
| `/analytics` 내부자거래 | SEC EDGAR 연결됨 (`SEC_EDGAR_ENABLED`) | 가격 lane과 무관하게 동작. 미수집 티커는 `queued` 후 다음 배치 |
| S&P 500 종목 히트맵 | TradingView widget | 공식 위젯 범위와 attribution 유지 |

## 6. 유료 공급자 예산 조사

가격은 2026-08-16 확인 스냅샷이며 언제든 바뀔 수 있다. 결제 전 공식 페이지와 서면 답변을 다시 확인한다.

| 후보 | 공개 가격/문구 | 월 30,000원 판단 | 재표시 판단 | 공식 근거 |
|---|---|---|---|---|
| Cboe Global Indices (CGI) | 라이선스 **월 USD 1,000부터**(DataShop 안내, 2026-08-17 확인). VIX 값은 CGI 보유자에게 보조 파일로 제공. CGI 없이 받는 Index Quotes는 T+1이며 재배포권 아님 | **예산의 약 28배** — 불가 | 공개 재표시가 정확히 이 라이선스 클래스 | [Global Indices Feed](https://www.cboe.com/data/global-indices-feed/), [DataShop](https://datashop.cboe.com/) |
| ICE Data Indices | 공개 가격표 없음, 기관 대상 개별 견적 | 예산 내 근거 없음 | 재배포 계약 필요(§3.12) | [ICE Data Indices](https://www.ice.com/market-data/indices) |
| **Tiingo** | **견적 회신 2026-08-18 (CEO Rishi Singh)**: 재배포 라이선스 최저 티어는 비공개 "Bootstrap Pilot" **월 $150** (5인 미만 인디 프로젝트, 사용자당·거래소 수수료 $0, 광고 유무 무관 정액). Individual Power $30/월은 약관상 개인·내부 연구 전용 — 공개 사이트의 가격 차트·역사 테이블·종가 표시 **불가** | **월 예산(50,000원 ≈ $36)의 4배 초과 — 불가** | 재배포 최저가 확인으로 조사 종결. 예산 상향 시 재문의 환영 문구 있음. 기록: [`INQUIRY_US_EOD_VENDORS.md`](INQUIRY_US_EOD_VENDORS.md) | [Pricing](https://www.tiingo.com/about/pricing), [ToS](https://app.tiingo.com/tos/) |
| EODHD | All-World $19.99/월. 비전문 이용자는 "selling, reselling, retransmitting, redistributing, **displaying**" 금지. Professional은 **사전 서면 승인** 요청 가능 | 표준 티어 부적합 | display가 금지 열거에 직접 들어 있음 — 승인 경로는 있으나 문의형 | [Terms](https://eodhd.com/financial-apis/terms-conditions) |
| Alpha Vantage | 약관(PDF, 2026-08-18 확인): "personal, non-commercial use, **unless you and Alpha Vantage have agreed otherwise in writing**". 타인에게 정보를 제공하는 활동은 상업 이용으로 분류 | 불확실 | 서면 합의 없이는 공개 표시 불가 | [Terms](https://www.alphavantage.co/terms_of_service/) |
| Twelve Data Business | 외부 표시용 business/venture가 월 USD 149 이상으로 안내됨 | 예산 초과 | business 계약 범위 확인 필요 | [Business pricing](https://twelvedata.com/pricing-business), [Commercial vs personal use](https://support.twelvedata.com/en/articles/5332349-commercial-and-personal-usage) |
| Marketstack | Basic USD 9.99. 2026-08-18 재확인: 자체 약관 페이지가 Idera 범용 SaaS 계약으로 리다이렉트되며 데이터 재배포 조항이 명시돼 있지 않음 | 가격만 보면 가능 | 데이터 전용 허락 문구가 없어 서면 확인 전 구매 금지 유지 | [Idera legal](https://www.ideracorp.com/legal/APILayer) |
| Alpha Vantage | 개인/표준 API와 commercial 문의 분리 | 불확실 | commercial/public display는 문의 필요 | [Terms](https://www.alphavantage.co/terms_of_service/) |
| Finnhub | 재배포/enterprise는 문의형 | 예산 내 근거 없음 | enterprise 계약 전 사용 금지 | [Pricing](https://finnhub.io/pricing-startups-and-enterprise) |
| roic.ai (2026-08-22) | Free $0 · $29 · $89 · **Enterprise custom = "Commercial-use API"**. ToS §7 "may not be redistributed or resold without explicit authorization" | Enterprise 견적형 — 예산 내 근거 없음 | 공개 표시 = 재배포 → Enterprise 승인 필요(§6.4) | [Pricing](https://www.roic.ai/pricing), [ToS](https://www.roic.ai/tos) |
| 넥스트레이드(NXT) 시장정보 (2026-08-22) | 정보포털 계약 상품(실시간·마감·히스토리컬). 웹사이트용(CASE 3) **고정비**, 무상 2025-03~2027-02, 최초 계약에 유상 1년(~2028-02) 포함, 금액 비공개 | 금액 미확인 — Contact Sales 문의 후 판단 | 계약 없이는 표시 불가(§6.3) | [정보포털](https://portal.nextrade.co.kr/mdclient/) |

### 6.1 뉴스·피드 소스 후보 (2026-08-19 운영자 아이디어 접수 — ROADMAP #10 조사 대기)

아직 약관 검토 전인 **후보 목록**이다. 어느 것도 승인 아님. 조사 시 공개 표시(재배포) 허용 여부와
헤드라인+링크 vs 본문의 구분, 무료 티어의 상업 이용 조건을 먼저 본다.

**2026-08-19 1차 약관 조사 결과** (아래 표에 반영):

| 후보 | 성격 | 판정 (2026-08-19) |
|---|---|---|
| Finnhub (뉴스 API) | 종목별 뉴스 | **❌ 확정** — ToS 원문: "not redistribute or share access to data or derived results … without written approval", "All plan[s] … strictly for personal use". 광고 사이트 공개 표시는 서면 승인·엔터프라이즈 필요 |
| 네이버 검색 API | 뉴스 검색 (제목+링크) | **경로 변경** — 개발자센터 Search API는 2026-07-30부로 **신규 신청 중단**(기존 이용자만 2027-06-30까지), 신규는 NCP 'NAVER API HUB' 별도 약관·절차. 추가 주의: 특약 2.1 "검색결과를 독립적으로 노출, 앞·뒤·중간에 다른 내용 삽입 금지" — **등락률 칩 병치 설계와 충돌 소지**. NCP HUB 약관 조사 후 재판정 |
| Marketaux | 뉴스 API (헤드라인+링크) | **보류** — /terms 404 (2026-08-19 실측), 약관 원문 미확보. 가입 화면 약관 확인 또는 지원 문의 필요. 무료 티어(100req/일·건당 3기사)는 피드 용도로 얇음 |
| Financial Juice | 실시간 뉴스 스쿼크 | 미조사 — 무료 플레이어는 위젯 임베드 전용일 가능성, 데이터 재배포 별도 계약 예상 |
| 한국은행 ECOS API | 뉴스 아님 — 거시 통계 | ✅ **lane 활성화(§3.16, 2026-08-20)** — 영리 카테고리 승인 키로 3시리즈 서빙 중 |
| KOSIS (통계청) | 뉴스 아님 — 통계 | ECOS와 같은 트랙. 공공누리 유형 확인 필요 |
| DART Open API | 공시 | ✅ 운영 중 — 공시 속보 피드(`/api/kr/events`)가 이 축 |

**2026-08-19 심층 조사 (2차) — GDELT 발견으로 결론 변경**

| 후보 | 판정 | 근거 (원문 확보) |
|---|---|---|
| **GDELT** | **✅ lane 구축·배포 (2026-08-20)** — `/api/news`, 게이트 GDELT_ENABLED | 공식 Terms of Use: "unlimited and unrestricted use for any academic, **commercial**, or governmental use of any kind **without fee**" + "You may **redistribute, rehost, republish**, and mirror … in any form". 조건 = GDELT 인용 + gdeltproject.org 링크. DOC 2.0 API가 주는 것 = 기사 **제목·URL·도메인·시각·언어**(본문 없음 — 언론 저작권 표면 최소, 우리 안전선과 정확히 일치). 운영 실측: 무키, **5초당 1요청**(위반 시 분 단위 쿨다운 — 2026-08-19 실측), 15분 단위 갱신. 한계: 한국어 매체 커버리지 미검증(1차 프로브 0건 — 쿼리 문법/커버리지 구분 필요), **영문 축 우선** |
| NCP NAVER API HUB (뉴스 검색) | **❌ 최종 기각 (2026-08-20)** — 삽입 금지 승계 확인 + 개정 특약이 설계 4요소 전부 금지 | 운영자가 구독 완료(앱 mulmit, 일 25,000회 무료) 후 검증. 결정 증거 = **약관 개정 공지**(ncloud.com/support/notice/all/2243, 2026-08-20 게시·2026-09-20 시행): ① 개정 전 특약 2.1 "검색결과를 **독립적으로 노출**하여야 하며, 검색결과의 **앞, 뒤, 중간 등에 다른 내용을 삽입**하거나 왜곡할 수 없고" — 구 개발자센터 특약 **승계 확정**. ② 개정 후는 더 강화: 2.2 "독립적으로, **가공 없이** 노출 … 순위 및 내용을 수정 … 할 수 없고"(통합 피드·등락 칩 병치 불가), 2.3 "데이터…를 **복사, 저장 또는 캐싱하는 행위**" 금지(배치 blob 불가; 2.4 예외는 이력조회 서버 21일뿐), "데이터를 **제3자에게 제공**" 금지, **"검색결과가 표시되는 페이지에 광고를 표시하거나, 기타 검색 API 서비스를 활용하여 수익을 얻는 행위"** 금지(광고 기반 출시와 정면 충돌), AI 입력·학습 금지. 물밑 설계 4요소(저장·피드 합류·칩 병치·광고) 전부 명시 금지 — 재론 불요. 한국어 언론 축은 보도자료+GDELT 유지 |
| 정부 보도자료 RSS (금융위·기재부) | **✅ lane 구축·배포 (2026-08-20)** — `/api/kr/press` | 실주소 확보(금융위 fsc_bbs_rss fid=0111 · 기재부 detailRssTagService bbsId=028, 안내 페이지에서 추출·검증). 근거: 기관이 구독·연동 목적으로 공표하는 RSS에서 **제목·기관명·링크만** 사용(본문 무전달 — GDELT와 같은 안전선). KOGL 유형은 본문 활용 시 재검토(기재부 푸터 "All rights reserved" 병기 기록). 금융위 피드는 게시일 부재 → first_seen 표기 |

**2026-08-20 텔레그램 스쿽 채널 — ❌ 유형 기각 (개별 채널 재론 불요)**

운영자가 "Market News Feed"(구독 38K)류 텔레그램 채널의 API 수집 가능성을 문의.
기술적으로는 가능(MTProto 유저 API·`t.me/s/` 웹 프리뷰)하나 **전송 수단이 문제가
아니다** — 권리 사슬이 두 겹으로 끊겨 있어 채널을 바꿔도 결론이 같다:

1. **채널이 콘텐츠의 권리자가 아니다.** "JUST IN:" 포맷의 익명 스쿽 채널은 유료
   뉴스와이어(블룸버그 터미널·로이터·다우존스) 헤드라인의 무단 중계가 통례.
   운영자 동의를 받아도 자기 것이 아닌 권리는 허락 불능 — 수집 시 무단 중계의
   3차 유통이 되며, 실시간 와이어 헤드라인은 hot-news misappropriation 판례가
   축적된 최고 위험 콘텐츠.
2. **등록부에 적을 권리 근거가 존재하지 않는다.** 법인·약관·출처 표기 체계
   전무. 가능한 근거 문장이 "익명 채널이 금지하지 않았음"뿐 — silence is not
   permission 원칙 위반. (법인·약관이 있던 Finnhub도 기각한 기준선 아래.)
3. **신뢰 오염.** 익명 스쿽 채널은 가짜 속보의 반복 경로 — 검증 불가 텍스트의
   verbatim relay는 확정치·1차 소스로 쌓은 신뢰에 채널 신뢰도를 이식한다.

대체 경로(동일 사실의 합법 버전): GDELT 15분 벌크가 실제 언론 보도를 실명
도메인 출처로 잡는다. 이 판정과 함께 `TITLE_KEYWORDS`에 제재·지정학·거시
키워드를 확장해 해당 유형 헤드라인의 커버리지를 넓혔다(권리 리스크 0).

**뉴스 트랙 결론(갱신)**: **GDELT로 글로벌/영문 축은 지금 구축 가능** — 계약·키·비용
전부 0, 조건은 인용+링크뿐. 한국어 축은 NCP HUB 가입(운영자) 또는 공공누리 RSS
확정 후. 등락률 칩은 소스 무관하게 우리 데이터 계산이라 어느 축이든 즉시 결합.

결론:

- 가격이 예산 안이라는 이유만으로 구매하지 않는다.
- 계약서에 `public display`, `redistribution`, `derived data`, `caching`, `API to end users`가 명시되지 않으면 Mulmit 요구를 충족한 것으로 보지 않는다.
- 첫 유료 결제 후보는 카드 수를 채우는 공급자가 아니라, 가장 필요한 소수 자산의 공개 표시 권리를 명확히 주는 공급자여야 한다.
- **2026-08-18 조사 결론**: 자가결제 티어로 공개 재표시를 서면 허용하는 벤더는 없다. 전 벤더가 "내부 이용 + 재배포는 별도 문의" 구조다. 유일하게 열려 있는 다음 수는 **Tiingo 재배포 정액 라이선스 견적 문의**(무료)이며, EODHD 서면 승인 경로가 차선이다.
- **2026-08-18 견적 회신로 확정**: 미국 EOD 재표시의 실측 최저가는 Tiingo **월 $150**이다. 현 예산으로 열리는 재표시 클래스는 없다는 결론이 견적으로 확인됐다. ADR 괴리율 등 미국 EOD 의존 기능은 예산이 월 $150 이상으로 상향되기 전까지 보류하며, 개인 열람용 티어($30)를 공개 재표시에 쓰는 클래스 착오는 하지 않는다.
- 현재 데이터 구독비 지출은 0원으로 유지한다. 예산이 50,000원으로 상향된 뒤에도 이 표에서 그 금액으로 열리는 재표시 클래스는 없다 — 개인 열람용 싼 티어를 공개 재표시에 쓰는 것은 클래스 착오이며 구매하지 않는다.

### 6.2 KRX 투자자별 순매수 (기관/외국인/개인/연기금) — ❌ 현시점 기각 (2026-08-20 권리 검증)

국내 리테일이 실제로 원하는 지표라는 판단은 유지하나, **합법 경로가 유료
라이선스뿐**이라 월 5만원 예산에서 진입 불가. 세 경로 전수 검증(원문 인용,
접근일 2026-08-20):

| 경로 | 판정 | 근거 (원문) |
|---|---|---|
| KRX Open API (openapi.krx.co.kr) | ❌ 이중 차단 | ① 서비스 목록에 투자자별 데이터셋 자체가 **없음**(지수·주식·증권상품·채권·파생·일반상품·ESG의 일별시세류뿐). ② 약관 제6조② "API 서비스를 **비상업적인 목적으로만** 이용할 수 있으며", 제11조② "제공받은 정보를 **제3자에게 제공할 수 없다**", 제6조③ "결과의 앞, 뒤, 중간 등에 다른 내용을 삽입하거나 왜곡할 수 없고"(네이버 특약과 같은 삽입 금지 — 등락 칩 병치 설계와 충돌) |
| KRX 정보데이터시스템 (data.krx.co.kr) | ❌ 무단 이용 불가 + 크롤링 금지 | 홈페이지 이용약관 제12조② "거래소의 **사전 허락 없이 복사·복제·배포·전송·공중송신하여서는 아니 됩니다**", 제10조② 금지행위 "**자동화 수단을 이용하여 정보를 무단 수집**·복제·배포하는 행위"(수집 자체가 금지 = 봇차단 우회 금지 원칙과도 충돌), 제12조의2 마켓데이터는 별도 「마켓데이터 이용약관」. 데이터 라이선스는 외부제공 권한별(일반이용·소매·**웹사이트**·정산가·방송) **판매 상품** — 합법 경로는 이 유료 계약뿐 |
| 공공데이터포털 금융공공데이터 (data.go.kr) | 대체재 부재 | 개방 110개 API·349개 테이블 목록에 투자자별 거래·순매수 데이터 없음. KRX 제공분은 상장종목정보뿐 (2026-08-20 개방 현황 확인) |

**결론**: 유일한 합법 경로 = KRX 시장데이터 유료 이용계약(웹사이트 외부제공
권한) — 예산 밖. kr_pension/kr_holdings 모듈이 이미 전제한 "KRX 투자자별
매매 데이터는 재배포 권리가 없다"가 공식 검증으로 확정됐다.

**권리 안 대체물**: 대량보유 5% lane(`/api/kr/holdings`, 2026-08-20 구축)이
"누가 쌓고 있나"의 권리 청정 근사이며, ECOS의 월간 집계(외국인 증권투자 등)는
거시 보완재다. **재검토 조건**: KRX Open API에 투자자별 데이터셋이 추가되고
약관의 비상업·제3자 제공 금지가 완화되거나, 금융공공데이터 개방 확대에
포함되는 경우.

### 6.3 넥스트레이드(NXT) 시장정보 — 조사 결과 `license_required` (2026-08-22, ROADMAP #9)

ROADMAP #9의 "NXT 시세 재배포 약관 조사" 종결. 넥스트레이드는 시장정보를 **정보포털(portal.nextrade.co.kr, "NEXTRADE Market
Data Services")의 계약 상품**으로만 제공한다 — 공개 API·무료 재배포 경로는 없다. 아래는 비로그인 상태의 정보포털 공개 페이지
실측(접근 2026-08-22, 브라우저; `www.nextrade.co.kr` 본 사이트의 "시장정보" 메뉴는 체결 현황 조회용이며 데이터 제공 조건은
정보포털에 있다).

| 항목 | 확인 내용(원문·요지) |
|---|---|
| 상품 | **Real-Time Data** — "Real-time market data delivered with low latency during market hours", "Primarily available via global data vendors, with optional direct connectivity", ASCII/Binary × 호가 10/5/3단계(NXTA-10 기본), **Usage Type: "External Use (Redistribution Allowed)" / "Internal Use Only (End User)"**. **End-of-Day Data** — 장 마감 후 FTP 파일(OHLCV 등). **Historical** — "available upon request, subject to review and approval" |
| 계약 절차 | Sign Up → Select Product(체크리스트 제출·심사) → Complete Contract(주문서·계약) → 데이터 수신. 가격은 포털 로그인 후 상품 선택/Contact Sales 단계 — **공개 페이지에 고정비 금액 없음(미확인)** |
| 라이선스 구분 (FAQ "정보 라이선스는 어떻게 구분되나요?", 2026-04-28, 인포그래픽) | CASE 1 일반용(거래참가자용) 고정비+거래 기반 변동 요율 · CASE 2 일반용(비참가자용: 웹/앱 고객 서비스) 고정비+이용 기반 변동 요율, 매월 리포트 제출, "웹/앱 내 로그인 사용자 대상 실시간 체결가 표출 희망 시 별도 웹 노출 계약 필요" · **CASE 3 웹사이트용** — 목적 "웹사이트/앱 내 실시간 체결가 공개", 이용 대상 "비로그인 불특정 다수 고객", 데이터 유형 실시간, 이용 권한 "비로그인 사용자 대상 실시간 체결가에 한해 표출 가능 · 제한적 내부 이용 가능(개발/운영/테스트 목적)", 과금 **고정비**, 유의 "별도 리포트 제출 의무 없음 · 로그인 사용자 대상 서비스 필요 시 별도 계약 필요 · 방송 및 언론 채널 노출 필요 시 별도 계약 필요" · CASE 4 소매사업용 고정비+이용 기반 · CASE 5 방송매체용 고정비 · CASE 6 최종이용자용 고정비+이용 기반, "외부 제공 및 공개 불가". 단서: "상기 내용은 NEXTRADE 정보 이용 가이드 기준이며, 세부 내용은 계약 조건에 따라 달라질 수 있습니다." |
| 무상 프로모션 (FAQ "무상 프로모션에 따른 계약기간 및 종료일 적용 방식", 2026-04-28) | "무상 제공 기간: 2025년 3월 ~ 2027년 2월(2년) — 이 기간에는 정보이용료가 부과되지 않습니다", "최초 계약 체결 시: 무상 기간 종료 후 유상 기간 1년을 포함하여 체결(2027년 3월~2028년 2월)", "계약 종료일: 2028년 2월(무상 기간 종료 전 체결 계약은 모두 고정)", "이후 1년 단위 자동 갱신" |
| 이용약관 | 정보포털 Terms and Conditions는 포털 이용약관이며 데이터 라이선스 본문은 계약서(정보이용계약)에 있음 — 공개 페이지에서 미열람 |

**판정 `license_required`.** Mulmit(비로그인 공개 대시보드)의 NXT 체결가 표시는 정확히 **CASE 3 웹사이트용 고정비 계약**에
해당하며, 계약 없는 표시·크롤링·증권사 HTS/MTS 화면 재사용은 불가. 합법 경로는 있고 지금은 정보이용료 무상(2027-02까지)이지만
**최초 계약에 2027-03~2028-02 유상 1년이 묶여 고정비 금액(비공개)을 모르면 예산 판단을 할 수 없다.** KRX 통합시세(KRX+NXT
합산)는 KRX 마켓데이터 약관(§6.2)의 별도 문제다.

- **현재 표시**: 변경 없음 — 프리장/애프터마켓(NXT 08:00–20:00) 한국 현물·지수 시세는 비표시, KR200 퍼프(§3.1)가 대체물.
- **운영자 선택지(비용 0)**: 정보포털 Contact Sales에 "웹사이트용(CASE 3) 고정비 금액·무상 기간 적용·유상 1년 약정 해지 조건"을
  문의. 회신 금액이 월 예산(5만원) 안이면 `pending_rights` → 계약 → `approved` 블록으로 진행, 아니면 기각 기록.
- **재검토**: 고정비 회신 시 / 2027-01(무상 종료 직전, 약정 구조 변화 확인).

### 6.4 roic.ai — 조사 결과 **현시점 기각** (`license_required`, Enterprise 전용) (2026-08-22, ROADMAP #11)

| 항목 | 확인 내용(접근 2026-08-22) |
|---|---|
| 약관 | [Terms of Service](https://www.roic.ai/tos) (Last updated 2026-04-07) §7 "Data obtained through the API may only be used in accordance with your subscription plan and **may not be redistributed or resold without explicit authorization**." §8 금지 행위 "To redistribute, resell, or sublicense data obtained from the platform without authorization", "To scrape, crawl, or harvest data beyond the access granted by your plan". 준거법 영국, 문의 support@roic.ai |
| 가격 | [Pricing](https://www.roic.ai/pricing): Free $0(5 req/분·2년·EOD) · Individual $29/월(300 req/분·5년) · Professional $89/월(무제한·40년+·벌크) · **Enterprise "Custom pricing" — "Commercial-use API"**(invoicing·multi-user). 상업 이용은 Enterprise에만 표기 |
| 출처 | [FAQ](https://www.roic.ai/faq): "We refresh our data every day using data from SEC for financial statements and Nasdaq for stock prices." 어닝콜 트랜스크립트는 별도 API(벤더 저작물, 발화 내용의 전문 재게시는 Enterprise 승인과 별개로 저작권 확인 필요) |

**판정**: 공개 사이트 표시 = 재배포 → Enterprise 개별 견적(명시 승인) 필요, self-serve 상업 티어 없음 → **월 예산 밖, 현시점
기각**. 재무비율은 #4 XBRL 자체 산출(`/api/us/fundamentals`)로 이미 대체. 어닝콜 원문은 벤더·발행사 저작권 문제라 요약·링크
이상의 표시는 애초에 부적합. **재검토 조건**: roic.ai가 self-serve 상업/표시 티어를 신설하거나 예산이 상향될 때.

## 7. 공급자 문의 템플릿

아래 문구를 공급자별 상품명·캐시 시간에 맞게 수정해 보낸다.

```text
Subject: Public display and derived-data permission for Mulmit

Hello,

I operate Mulmit (https://mulmit.com), a publicly accessible bilingual market
dashboard. It is currently a non-commercial personal project, but advertising
or sponsorship may be added later.

I would like written confirmation whether your terms permit all of the following:

1. Displaying the specified market data to unauthenticated website visitors.
2. Relaying selected fields through my server-side JSON API to my own frontend.
3. Caching responses for [TTL] and serving the last known value for up to [STALE].
4. Storing historical observations in a private database.
5. Computing and displaying returns, drawdowns, correlations, and clearly
   labelled composite/derived indicators.
6. Showing your required attribution and links.
7. Continuing the same use if the site later includes advertising or sponsorship.

Please also confirm whether separate exchange, index-provider, or underlying-data
permissions are required, and provide the applicable plan, fee, attribution text,
geographic/user limits, and termination requirements.

Thank you.
```

KRX 문의에는 한국어로 다음을 추가한다.

- 로그인 없는 공개 대시보드임
- 삼성전자·SK하이닉스·KOSPI·KOSDAQ의 일별 종가와 역사 차트를 표시함
- 전용 다운로드 UI(CSV 내보내기 등)는 제공하지 않지만, 화면이 쓰는 값은 인증 없는 공개 JSON 엔드포인트로 나가며 누구나 그 응답을 받아 저장할 수 있음. 이것이 이용약관상 제3자 제공에 해당하는지 명시적으로 확인 요청
- 배치 저장 기간과 갱신 빈도
- 향후 광고 가능성
- 필수 출처 표기의 정확한 문구와 표시 위치
- 별도 데이터 분배 계약 필요 여부

## 8. 승인 기록 템플릿

상태를 바꿀 때 아래 블록을 공급자 섹션에 추가한다.

```yaml
decision_id: DS-YYYY-NNN
provider_id: example
status: approved
reviewed_at: YYYY-MM-DD
reviewer: repository owner
evidence_type: official_terms | written_email | signed_contract
evidence_reference: private-vault-document-id-or-public-url
approved_scope:
  public_display: true
  server_json_relay: true
  cache_ttl_seconds: 30
  stale_seconds: 300
  historical_storage: false
  derived_metrics: true
  advertising: false
attribution: "Exact required text"
expires_at: YYYY-MM-DD | null
recheck_at: YYYY-MM-DD
notes: "No confidential contract language here"
```

상태 변경과 코드 플래그 변경은 같은 PR에 넣는다. 증거가 `pending`인데 배포 플래그만 true로 바꾸지 않는다.

## 9. 구현 완료 체크리스트

### 권리와 설정

- source register에 승인 범위, 검토일, 재검토일이 있음
- `deploy/env.example`과 compose 기본값이 fail-closed임
- serving에 영향을 주는 게이트 변수가 compose의 `ingest`뿐 아니라 `web` 서비스에도 전달됨
- 비활성 공급자는 앱 시작 시 네트워크 호출 0회
- 비활성 공급자의 기존 DB 행도 공개 reader에서 노출되지 않음
- 게이트가 공급자 lane 단위이며 승인된 lane 추가가 다른 lane의 차단을 풀지 않음
- API 응답에 `rights.status`, `provider`, `publisher`, `source.url`이 있음
- UI가 `missing`, `stale`, `pending_rights`, `license_required`, `disabled`를 구분함

### 데이터 진실성

- 합성 proxy와 공식 현물/지수 series key가 다름
- 통화, 단위, frequency, observation date, fetched time이 명시됨
- 휴일·결측·상장폐지·0 유동성을 0% 신호로 만들지 않음
- 공식 값이 없을 때 검색 결과나 다른 ticker로 채우지 않음
- history가 없으면 drawdown을 계산하지 않음

### 기술

- 공급자 호출은 background ingest에 있고 request path는 저장소만 읽음
- timeout, retry, 429, 5xx, schema 오류 fixture가 있음
- SQLite/Postgres store 테스트가 있음
- 같은 관측치 재수집이 idempotent함
- 실패 시 이전 good snapshot을 원자적으로 보존함
- rate limit과 공급자별 호출량 상한이 문서화됨
- API key와 응답 원문에 포함된 비밀값이 로그·예외·테스트 snapshot에 없음

### 릴리스

- 전체 pytest, Ruff, Node syntax, `git diff --check`, compose config 통과
- KO/EN과 1440px/390px 브라우저 QA 통과
- restricted 카드 DOM에 숫자·관측 SVG가 없음
- production smoke에서 disabled/rights 상태가 로컬 fixture와 같음
- 계약 만료·키 제거·약관 변경을 가정한 fail-closed 테스트가 있음

## 10. 변경 이력

| 날짜 | 변경 | 작성자 |
|---|---|---|
| 2026-08-16 | 최초 공급자·권리·예산·카드 매핑 등록 | Codex assisted |
| 2026-08-16 | 교차검토 반영: 실제 UI key 정정, 공개 JSON 표현 수정, KRX 출처·제3자 제공 조건 명시, ICE/IMF 경로 정정, proxy와 공식값 key 분리, HIP-3 결정 기록 추가 | Claude assisted |
| 2026-08-17 | SEC EDGAR lane 추가(`DS-2026-002`)와 Form 3/4/5 표시 규칙 기록 | Claude assisted |
| 2026-08-17 | New York Fed lane 추가(`DS-2026-003`), HIP-3와 Hyperliquid 자체 DEX 상장 주체 구분 | Claude assisted |
| 2026-08-17 | Federal Reserve Board lane 추가(`DS-2026-004`). DDP 폐지를 피해 릴리스 페이지 XML 사용 | Claude assisted |
| 2026-08-17 | H.10 환율, H.4.1 유동성, H.6 통화량 연결 | Claude assisted |
| 2026-08-17 | BLS lane 추가(`DS-2026-005`), DOL ETA는 보류 사유 기록 | Claude assisted |
| 2026-08-17 | 예산 30,000→50,000원 상향 기록. Cboe CGI 월 $1,000 시작가 확인 — 상향 후에도 재표시 클래스는 예산 밖 | Claude assisted |
| 2026-08-17 | St. Louis Fed STLFSI4 문의 초안 작성 — "Copyrighted: Citation Required" 태그 확인, 표시 권리와 수집 경로를 함께 묻는 구성 | Claude assisted |
| 2026-08-18 | 한국 24시간 참고가 섹션(`/api/kr/overnight`) 추가 — 기존 세 lane의 결합(HIP-3 마크 × H.10 공식환율 × FSC 기준가), 신규 소스·권리 없음. HIP-3 게이트를 그대로 타고 환율·기준가 날짜를 값과 함께 표기, 김프 조정 없음 명시. 모니터를 한국/미국·글로벌 존으로 재배치, 합성 참고값 카드 2장은 이 섹션이 대체. 계획서 `docs/PLAN_KR_SECTIONS.md` | Claude assisted |
| 2026-08-19 | 경제 캘린더 추가(`/api/calendar`) — 미국 데이터 발표일은 FRED 릴리스 메타데이터(승인 lane, 실측 검증), FOMC·금통위는 공식 페이지에서 확인한 큐레이션(확인일 2026-08-19 동봉, "직전 회의 전 잠정" 고지). 일정은 공표된 사실이되 변경 가능함을 basis로 전달 | Claude assisted |
| 2026-08-19 | DART 연간 재무제표 추가(`/api/kr/fundamentals/{code}`, §3.10 확장) — 주요계정 원문 전달, 연간 한정(분기 손익 누적 구분 부재), 연결 우선, 금융사 매출 부재는 사실로 표시. 미국 패널과 대칭 | Claude assisted |
| 2026-08-19 | EDGAR 재무제표 추가(`/api/us/fundamentals/{ticker}`, §3.5 확장) — XBRL companyconcept, 내부자 lane과 같은 티커 큐·게이트. 태그 사다리는 최신 보고 기간 기준(NVIDIA 태그 전환 실측), YTD 배제·정정 우선, 파생은 마진 2종뿐 | Claude assisted |
| 2026-08-20 | 환율 4종(원달러·엔달러·유로달러·파운드달러) **연준 H.10 주간 → ECOS 일별 매매기준율·재정환율 이관**(§3.16) — H.10은 월요일 주간 발행이라 최대 6영업일 지연이 본질(운영자 실사용 지적). ECOS 731Y001/0000001·731Y002 라이브 검증(당일 T+0 고시 확인). 위안/달러는 ECOS 카탈로그에만 있고 실데이터 없음(731Y002/0000027 실측) → H.10 잔류. KRO 환산 환율도 동반 신선화, 시리즈 정의 혼합 방지 위해 기존 H.10 이력 삭제 후 재수집. FEDBOARD_MAX_AGE 12h→4h(H.15 10년물 T+1 반영) | Claude assisted |
| 2026-08-20 | NCP API HUB 뉴스 검색 **최종 기각**(§6.1) — 개정 공지(2026-09-20 시행)로 확정: 삽입 금지 승계 + 저장·캐싱 금지 + 제3자 제공 금지 + **검색결과 페이지 광고 금지**. 설계 4요소 전부 충돌, 재론 불요 | Claude assisted |
| 2026-08-20 | NCP API HUB 조사 갱신(§6.1) — AI·NAVER API 약관 전문 확보(제5조⑧ 저장·배포 제한, 특약 구조), 뉴스 검색 응답 필드·쿼터 실측. 잔여 관문 = 콘솔 신판 약관의 검색 특약(운영자 캡처) | Claude assisted |
| 2026-08-20 | KRX 투자자별 순매수 권리 검증(§6.2 신설) — 3경로 전수 ❌: Open API(데이터셋 부재+비상업+제3자 금지), 정보데이터시스템(무단 복제·자동수집 금지, 유료 라이선스만), 금융공공데이터(대체재 부재). 재검토 조건 명시 | Claude assisted |
| 2026-08-20 | 대량보유(5%) 전체 보고자 lane(`/api/kr/holdings`) — 기존 국민연금 크롤의 필터 일반화(같은 걷기, 두 blob), 신규 소스·권리·요청 예산 증가 없음(상세 합집합만 확대). 피드는 신규 진입·보유목적 변경·±2%p 이상 변동만 큐레이션, 국민연금 행은 중복 탑재 안 함 | Claude assisted |
| 2026-08-20 | EDGAR 재무 함정 4호 실측·수리(§3.5) — CRWD는 IncludingAssessedTax 변형만 신고(사다리 추가), KO는 companyconcept 200+빈 배열 vs companyfacts 존재(경로 폴백 추가, 출처 접미 표기) | Claude assisted |
| 2026-08-20 | 텔레그램 스쿽 채널 유형 ❌ 기각(§6.1 — 채널은 권리자 아님·근거 부재·가짜 속보 경로) + GDELT TITLE_KEYWORDS 지정학·제재·거시 17종 확장 | Claude assisted |
| 2026-08-20 | ECOS 활성화(§3.16 — 키 도착·영리 승인 증빙·3시리즈 서빙) + 정부 보도자료 lane(`/api/kr/press`, 금융위·기재부 RSS 제목·링크만, first_seen 정직 표기) + GDELT 제목 중복 접기(+N곳) | Claude assisted |
| 2026-08-20 | GDELT 뉴스 lane 구축·배포(§6.1, `/api/news` + 통합 피드 합류) — 제목·출처·링크만(본문 무전달), 종목 태그는 닫힌 사전 단어경계 매칭, 등락 칩은 금융위 전일 확정값, 인용+링크 조건은 payload attribution으로 상시 동반, 6초 간격·배치 전용 | Claude assisted |
| 2026-08-19 | 뉴스 소스 심층 조사 2차(§6.1) — **GDELT ✅ 완전 청정 확정**(상업·재배포 명시 허용, 인용+링크 조건, 5초/1요청 실측), NCP HUB 조건부(한시 무료·약관 캡처 필요), 공공누리 축 유망(엔드포인트 미확정), Finnhub ❌ 유지 | Claude assisted |
| 2026-08-19 | 재무 파생 범위 확장(§3.5·§3.10) — 마진에 더해 연간 행의 ROE·ROA·부채비율((자산−자본)÷자본 항등식)·매출 성장률(연속 연도 한정). 국내는 후행 PER·PBR 추가: FSC 최신 시총 ÷ 최근 연간 공시값(서빙 시 계산, 적자 PER 표시 안 함). 전부 공시값 산술 — 추정·연율화 없음. 캐시 키 v2 범프 | Claude assisted |
| 2026-08-19 | ECOS 한국 거시 lane 구축(§3.16, `kr_base_rate`·`kr_cpi`) — 게이트 꺼짐 배포, sample 키로 코드·응답 형식 실측. 활성화는 운영자 인증키 발급 + 약관 전문 기록 후 | Claude assisted |
| 2026-08-19 | EDGAR 광고 병행 판정 advertising: true (§3.5) — 정책 원문 재확인(무료 접근·fair access·UA만 부과, 상업 제한 없음) + 17 U.S.C. §105 퍼블릭 도메인. webmaster@sec.gov 예우성 통지 발송(허락 게이트 아님, 상세 INQUIRY_SEC_EDGAR_ADS.md) | Claude assisted |
| 2026-08-19 | NY연은 침체 확률 lane 추가(§3.15, `recession_prob`) — 약관 전문 검토로 일반 허용 라이선스 확인(Use Restrictions 비해당), 기존 nyfed lane·인용문 기계 재사용. Polymarket 대안 검토의 산출물(Polymarket ❌ 유지, FedWatch는 CME 라이선스 대상이라 배제) | Claude assisted |
| 2026-08-18 | 미 하원 PTR lane 추가(`DS` §3.14, `/api/us/ptr`) — STOCK Act 공시 원문 전달, EIGA §105(c) 분석·고지 동봉, 엄격 파서(불일치는 원문 링크로 강등), 상원 eFD는 봇 차단으로 **보류(우회 안 함)** | Claude assisted |
| 2026-08-18 | ETF 보드(`/api/kr/etf`) 추가 — 금융위원회_증권상품시세정보 활용신청 승인(자동승인, 만료 2028-08-18) 후 기존 FSC lane·키로 하루 스냅샷 수집. 괴리율 = 종가÷NAV−1, 같은 기준일 공표값 두 개에서만 계산·NAV 0은 결측. 채권·일반상품시세정보도 함께 승인(미사용 보관) | Claude assisted |
| 2026-08-18 | 모니터를 랜딩·`/kr`·`/us` 세 페이지로 분리(P1) — 데이터·권리 변경 없음, 페이지 구성 레이어. React 전환 보류 판정은 `docs/ROADMAP.md` | Claude assisted |
| 2026-08-18 | **St. Louis Fed STLFSI4 서면 승인 수신** — FRED API 경유, 지정 인용문+접근일, 접근 유료화 금지, 로고·보증 금지(§3.3). `rights.citation` 구현, FRED lane 운영 활성화 결정. 동승 계열은 ICSA·DCOILWTICO(미 연방정부 저작물)뿐, 제3자 계열은 `license_required` 유지 | Claude assisted |
| 2026-08-18 | **Hyperliquid 지원팀 회신** — 플랫폼 permissionless·공개 API 안내, HIP-3 피드는 xyz에 문의 안내. 명시적 허락 아님, xyz 회신 대기·재검토일 유지(§4.1) | Claude assisted |
| 2026-08-18 | **Tiingo 견적 회신** — 재배포 최저 월 $150(Bootstrap Pilot), $30 티어는 공개 표시 불가. 예산 초과로 미국 EOD 재표시 보류 확정(§6) | Claude assisted |
| 2026-08-18 | 국민연금 대량보유(5%) 공시 섹션(`/api/kr/pension`) 추가 — 기존 DART lane(`DS-2026-008`) 재사용, 신규 소스·권리 없음. 공시검색(D001)에 제출인 필터가 없어 ingest 배치 전용으로 걷고 web은 저장분만 서빙, 보고서 단위 값을 원문 전달("-"는 null). 계획서 Phase B-1 | Claude assisted |
| 2026-08-18 | Tiingo 재배포 라이선스 **견적 문의 발송** (sales@tiingo.com) | Claude assisted |
| 2026-08-18 | 미국 EOD 벤더 조사 갱신 — Tiingo·EODHD·Alpha Vantage 약관 원문 확인. 자가결제 재표시 티어 부재 확인, Tiingo 견적 문의 초안 작성 | Claude assisted |
| 2026-08-17 | Open DART lane 추가(`DS-2026-008`) — 임원·주요주주 소유상황 보고를 국내 종목 분석 옆에 원문 전달. EDGAR 원문 링크를 사람용 뷰로 수정 | Claude assisted |
| 2026-08-17 | STLFSI4 문의 **발송** — FRED 공식 폼, 확인 배너·POST 200 검증. 회신 대기 | Claude assisted |
| 2026-08-17 | 코스피 지수군 섹션 추가 — 지수 하루 스냅샷(1요청/일, 168지수)으로 대표 지수 10종·코스피 200 섹터 11종의 종가·전일·연초·52주·거래대금 표. 지수명이 시리즈 간 비유일함을 확인해 (이름,분류) 복합키와 KOSPI시리즈 고정 적용. 미확정 52주 최저 0값은 결측 처리 | Claude assisted |
| 2026-08-17 | 국내 종목 검색·분석 추가 — FSC 전 종목 스냅샷 로스터 + 요청 기반 5년 종가, 낙폭·MDD·변동성 파생 통계. 야후 시절 단일종목 분석의 한국판을 승인 lane 위에 재구축 | Claude assisted |
| 2026-08-17 | 공개 준비 정리: 레거시 lane 섹션(섹터 모니터·상관관계·종목 위험 분석)을 오류 표시 대신 숨김, analytics는 내부자 공시 조회 모드로 전환, 레코드 없는 라이선스·예약 카드 숨김. 데이터·권리 변경 없음 — lane이 열리면 화면이 저절로 복원된다 | Claude assisted |
| 2026-08-17 | 영구 공석 proxy 카드(코스닥·원달러 합성)를 한국 섹션에서 제거, 개요 타일을 공식 카드로 교체. 데이터·권리 변경 없음 | Claude assisted |
| 2026-08-17 | HIP-3 문의 **발송** — XYZ Ltd와 Hyperliquid Corp. 양쪽. P0의 마지막 미발송 항목 해소 | Claude assisted |
| 2026-08-17 | HIP-3 문의 초안 개정: XYZ Ltd·Hyperliquid Corp. 약관 정독 결과 반영, 연락처 확정, 기초 자산 원 권리자 질문을 최우선으로 이동. §4.1 문의 대기 목록 신설 | Claude assisted |
| 2026-08-17 | Fed Board 교역가중 달러지수 3종 연결(H.10, 기존 lane). Cboe 지수값 서면허가 조항 원문 인용 | Claude assisted |
| 2026-08-17 | 금융위원회 공공데이터 lane 추가(`DS-2026-006`). 코스피·코스닥·삼성전자·SK하이닉스 공식 종가를 KRX 승인과 별개 근거로 연결. `samsung` alias에서 `005930` 제거 | Claude assisted |
| 2026-08-17 | `Mulmit 유동성·스트레스 지수` 도입. CNN Fear & Greed 복제 대신 자체 산식 | Claude assisted |
| 2026-08-21 | 운영자 실사용 피드백 "안 나오는 데이터" 3종 판정 — ① HIP-3 자산 카드 이력 차트: `historical_storage: false`(xyz 회신 대기)에 따른 의도된 미제공, ② 나스닥 주말 신호: 내부 세션(금 17:00 ET) 시작 전, ③ VIX·하이일드: Cboe·ICE 원 권리자 라이선스. 권리 결정 변경 없음. UI만 고장이 아닌 상태로 정직화 — "표시할 시계열이 없습니다"→"이력 차트 미제공 · 표시 권리 확인 중", "데이터 미연결"→"세션 대기 · 다음 내부 세션 {시각}"(`/api/market/weekend` session에 `next_start_at` 추가). `xyz:VIX` 상장폐지 확인으로 VIX proxy 경로 종결(§5 매핑표) | Claude assisted |
| 2026-08-21 | **DS-2026-001 개정** — 무응답→OFF 규칙 폐기(명시적 거절만 OFF), HIP-3 자산 카드 **일봉 이력 개방**(`historical_storage: true`, 운영자 위험 수용). 새 lane `app/hip3_history.py`: `candleSnapshot` 1d·1년·6h, report blob 1개, 별도 게이트 `HIP3_HISTORY_ENABLED`(기본 false), 요청 경로는 저장 블롭만 읽음, `/api/market/assets`에 `observations`·`history_status`(`withheld_pending_rights`/`collecting`/`stored_daily_candles`)·`history_lane`·`history_basis` 추가. `/api/status` 권리 요약에 `history` 게이트 표기 | Claude assisted |
| 2026-08-21 | 운영자 결정 — 영구 `license_required` 플레이스홀더 카드(VIX·하이일드 스프레드)는 공개 페이지에서 **숨김**(빈 카드 대신). API는 여전히 `license_required`로 보고하고 권리 상태 구분(§9)은 유지. 옵션 지표 4종은 정의 수준에서 이미 숨겨져 있었음. VIX 대체 후보로 OFR 금융스트레스지수(미 재무부 OFR, 연방정부 저작물, 일별, 변동성·신용 하위지수) 조사 착수 | Claude assisted |
| 2026-08-21 | **OFR 금융스트레스지수 lane 추가** (`DS-2026-009`, §3.17) — 미 재무부 OFR 연방 저작물(저작권 미주장·credit 요청·인장 금지 원문 인용), 일별 CSV 1개로 종합+5범주 수집, 게이트 `OFR_ENABLED`(기본 false), 인용문+접근일 `rights.citation` 동봉. 카드 `ofr_fsi`·`ofr_fsi_volatility`·`ofr_fsi_credit`가 숨긴 VIX·하이일드의 역할을 대신(“VIX 자체 아님” 표기). 요약 띠·RISK & CREDIT 섹션 키 재배치 | Claude assisted |
| 2026-08-21 | **실현 변동성 카드** 자체 산출(§5.4.1) — HIP-3 일봉 종가 20개 로그수익률 표준편차 × √252, `sp500_realized_vol`(RISK & CREDIT 배치)·`kr200_realized_vol`(API). "VIX 아님" 표기, 내재변동성과 수준 비교 금지. 0 중심 지수(OFR FSI·STLFSI)와 변동성 계열의 변화 표시를 %에서 **포인트**로 교정(음수 기준값의 % 변화가 방향을 뒤집던 문제) | Claude assisted |
| 2026-08-21 | **Mulmit 시장 심리 게이지(실험)** 자체 산출(§5.4.2, `/api/market/sentiment`) — OFR 변동성·신용 + HIP-3 퍼프 모멘텀·실현 변동성·주식 대 금, 자기 이력 백분위·방향 정렬·동일 가중·최소 3입력·180일 이력. CNN 명칭·밴드 불복제, 실험 표기. 예약돼 있던 `sentiment` 카드 슬롯 연결, `/us` 패널·랜딩 미니 추가 | Claude assisted |

| 2026-08-21 | 크립토 섹션 Phase 1(ROADMAP #16) — §3.1 네이티브 퍼프 단락, §3.18 alternative.me 신설(`DS-2026-010`, official_terms, 출처 값 옆 조건), §4.1 Deribit·두나무·Coinalyze 문의 대기 3행. 소스 17종 판정·실측은 `PLAN_CRYPTO_SECTION.md` §3·§8 | Claude assisted |
| 2026-08-21 | 크립토 Phase 2 — §3.19 업비트 시세(`pending_rights`, 위험수용 템플릿), §3.20 CoinMarketCap 글로벌 메트릭(`pending_review`→키 발급 시 approved), §3.21 가스 스트립 조사 결과 보류(퍼블릭 RPC·mempool 약관). 코드는 게이트 기본 OFF로 배포 | Claude assisted |
| 2026-08-21 | CoinMarketCap lane 승인·활성화(`DS-2026-011`, §3.20) — Basic 키 발급·서버 게이트 ON, 첫 blob 라이브 확인. lane report의 CMC 상태를 서빙 기준으로 정정(키는 ingest 전용) | Claude assisted |
| 2026-08-21 | 가스 스트립 lane 추가(§3.21 후속, `/api/crypto/gas`, 운영자 RPC 계정 URL 주입형·게이트 OFF), 총시총 T 단위 포맷, Deribit·Coinalyze 문의 초안을 운영자 Gmail에 생성(발송 대기) | Claude assisted |
| 2026-08-22 | **Coinalyze 서면 승인**(§3.27 신설, `DS-2026-019`) — 문의 5항 그대로 허용, 조건은 **dofollow 링크**. 코드는 무료 키 발급 후 실측하고 착수. 외부 링크 dofollow 회귀 테스트 추가 | Claude assisted |
| 2026-08-22 | 업비트 시세 lane 운영자 위험수용 개방(`DS-2026-012`, §3.19) — `UPBIT_ENABLED=true`; Deribit·Coinalyze 문의 발송(§4.1), 두나무 1:1 문의는 기록용 발송 예정 | Claude assisted |
| 2026-08-22 | 가스 스트립 lane 활성화(`DS-2026-013`, §3.21 — 운영자 Alchemy 계정, 이더리움 라이브·Base/Arbitrum은 앱 네트워크 활성화 대기), 업비트 lane 라이브 확인(§3.19) | Claude assisted |
| 2026-08-22 | CoinMarketCap lane 사용 범위 확장(§3.20) — `v2/cryptocurrency/quotes/latest` USDT·USDC 유통 공급(1크레딧/시간, 월 ≈ 720 추가, 같은 키·같은 Commercial Terms), 7d/30d 변화는 자체 일별 누적 | Claude assisted |
| 2026-08-22 | ROADMAP #9·#11 조사 종결 — 넥스트레이드 시장정보 `license_required`(§6.3: 정보포털 계약형, 웹사이트용 CASE 3 고정비, 무상 2027-02까지·유상 1년 약정, 금액 비공개 → 운영자 문의 선택), roic.ai 현시점 기각(§6.4: ToS 재배포 금지, 상업 API는 Enterprise 견적만) | Claude assisted |
| 2026-08-22 | 바이오 섹션(ROADMAP #8) Phase 1 — ClinicalTrials.gov(§3.22, `DS-2026-014`, 약관 4조건 동봉)·openFDA(§3.23, `DS-2026-015`, CC0) lane 추가, 게이트 OFF(`BIO_SECTION_ENABLED`·`CLINICALTRIALS_ENABLED`·`OPENFDA_ENABLED`), 계획 `PLAN_BIO_SECTION.md` | Claude assisted |
| 2026-08-22 | 바이오 lane 2종 활성화(§3.22·§3.23) — 운영자가 게이트 3종 ON, 첫 ingest 패스 저장·`/bio` 라이브 확인 | Claude assisted |
| 2026-08-22 | 바이오 Phase 2 — Federal Register 자문위 공고(§3.24, `DS-2026-016`)·PubMed 서지(§3.25, `DS-2026-017`, 초록 비표시) lane 추가(게이트 OFF), 식약처 품목허가는 운영자 활용신청 대기로 기록(§3.26); fda.gov 달력은 봇 감지로 보류 | Claude assisted |
| 2026-08-22 | 바이오 Phase 2 lane 2종 활성화(§3.24·§3.25) — 운영자가 게이트 ON, 첫 ingest 패스 저장·`/bio` 라이브 확인 | Claude assisted |
| 2026-08-22 | 식약처 의약품 품목허가 lane 구현(§3.26, `DS-2026-018`) — 운영자 활용신청 승인 후 서버에서 실측(상세 엔드포인트 `item_permit_date` 필터), 게이트 OFF(`MFDS_ENABLED`), 키는 FSC 키 재사용 | Claude assisted |
| 2026-08-22 | 가스 스트립 Base·Arbitrum 복구(§3.21) — 운영자 Alchemy 앱에서 두 Mainnet 네트워크 활성화, 3개 체인 라이브 확인 | Claude assisted |
| 2026-08-22 | 식약처 품목허가 lane 활성화(§3.26) — 운영자가 `MFDS_ENABLED` ON(FSC 키 재사용), 첫 패스 30일 112품목 저장·`/bio` 라이브 확인; PubMed `NCBI_EMAIL` 설정(§3.25 정책상 연락처) | Claude assisted |
