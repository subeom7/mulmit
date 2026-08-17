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
| 현재 사용 | `xyz`/`mkts` meta/context, mark, oracle, funding, OI, 24h notional, 일부 5분 기준 캔들 |
| 기술 비용 | API 키·구독료 없음 |
| 캐시 | 자산 30초/300초 stale, 주말 5분/30분 stale, 프로세스 로컬 |
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
  historical_storage: false
  derived_metrics: unconfirmed
  advertising: unconfirmed
attribution: "Hyperliquid HIP-3 / trade.xyz"
expires_at: null
recheck_at: 2026-09-16
notes: >
  코드 기본값은 HIP3_PUBLIC_DISPLAY_ENABLED=false. 서면 답변 도착 전까지 현행
  공개 화면을 유지하기로 저장소 소유자가 결정하여 서버 .env에서만 true로 둔다.
  이는 승인 근거가 아니라 명시적으로 기록된 운영자 위험 수용이다. recheck_at까지
  답변이 없으면 배포 값을 false로 되돌린다.
```

### 3.2 TradingView 공식 위젯

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
| 현재 상태 | `disabled` |
| 코드 위치 | `app/providers/fred.py`, `app/macro_dashboard.py`, `app/store.py`, `app/ingest.py` |
| 배포 기본값 | `FRED_ENABLED=false` |
| 현재 위험 | 수집 플래그가 false여도 DB에 과거 행이 있으면 macro route가 읽어 공개할 수 있음 |
| 공개 결정 | 서면 허가 전 FRED 경유 수집·저장·캐시·제3자 제공을 하지 않음 |
| 공식 근거 | [FRED API Terms](https://fred.stlouisfed.org/docs/api/terms_of_use.html), [FRED Terms](https://fred.stlouisfed.org/legal/terms/) |

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
| 코드 위치 | `app/providers/sec_edgar.py`, `app/insider_filings.py`, `app/store.py`, `app/ingest.py` |
| 배포 기본값 | `SEC_EDGAR_ENABLED=false`, `SEC_EDGAR_USER_AGENT=` (미설정이면 lane이 닫힘) |
| 현재 사용 | 티커→CIK 매핑, 회사 submissions, Form 3/4/5 원본 XML의 보고 항목 |
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
  advertising: unconfirmed    # 광고 도입 전 fair access 정책 재확인
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
| 현재 사용 | 코스피·코스닥 지수 종가, 삼성전자 `005930`·SK하이닉스 `000660` 종가 |
| 기술 비용 | 무료. data.go.kr 활용신청으로 키 발급 |
| 갱신 | 일 1회. 기준일 **다음 영업일 13시(KST) 이후** 공개. 실시간 아님 |
| attribution | `출처: 금융위원회 (공공데이터포털 data.go.kr)`. `rights.notice`로 전달 |
| 공식 근거 | [주식시세정보](https://www.data.go.kr/data/15094808/openapi.do), [지수시세정보](https://www.data.go.kr/data/15094807/openapi.do), [KRX상장종목정보](https://www.data.go.kr/data/15094775/openapi.do) |

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
  둘 이상 오면 하나를 고르지 않고 그 계열을 실패시킨다.
```

### 3.10 DOL ETA 신규 실업수당 — **보류**

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

### 3.11 Yahoo Finance / yfinance

| 항목 | 기록 |
|---|---|
| 내부 ID | `yahoo_legacy` |
| 현재 상태 | `private_only` |
| 배포 기본값 | `LEGACY_PRICE_DATA_ENABLED=false` |
| 남은 기능 | `/analytics`, `/api/metrics`, `/api/correlation`, `/api/market/sectors`의 레거시 opt-in |
| 공개 결정 | 서면 라이선스 전 공개 배포에서 계속 503 |
| 공식 근거 | [Yahoo data providers and redistribution notice](https://help.yahoo.com/kb/yahoo-finance-plus/exchanges-data-providers-yahoo-finance-sln2310.html), [Yahoo Terms](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html) |

yfinance 패키지가 공개 표시·저장·재배포 권리를 부여한다고 해석하지 않는다. 401/429를 스크래핑 엔드포인트로 우회하지 않는다.

### 3.12 Cboe, ICE, IMF

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
| `bok_ecos` | USD/KRW와 한국 거시 후보 | JSON/XML | `pending_review` | [한국은행 ECOS](https://ecos.bok.or.kr/api/) | 3 |

Fed Board DDP의 일부 데이터 전달 경로는 전환 공지가 있으므로 신규 구현 시 종료 일정과 공식 대체 경로를 다시 확인한다. 특정 FRED series ID를 그대로 복제하는 것이 아니라 원 발행기관의 원 series와 단위를 검증한다.

### 4.1 서면 문의 대기 목록

코드로 풀 수 없고 회신이 있어야 열리는 항목만 모았다. 우선순위는 회신이 열어 주는
화면의 크기 순이다.

| 수신처 | 막고 있는 것 | 상태 | 초안 |
|---|---|---|---|
| trade.xyz **및** Hyperliquid (수신처 2곳) | 자산 카드 전체의 역사 차트. `historical_storage: false`라 현재는 최신값만 보인다 | **발송 완료 2026-08-17** (양쪽 각각). 회신 대기. `DS-2026-001`, `recheck_at: 2026-09-16` | [`INQUIRY_HYPERLIQUID_TRADE_XYZ.md`](INQUIRY_HYPERLIQUID_TRADE_XYZ.md) |
| Federal Reserve Bank of St. Louis | `financial_stress`(STLFSI4). 뉴욕 연준과 같은 구조 — 연방기관이 아니라 저작권을 주장하지만, 명시적 이용허락을 주는지가 관건이다. 시리즈 태그가 "Copyrighted: Citation Required"(2026-08-17 확인)라 인용이 완결 조건인지 서면으로 묻는다. FRED 경유 복제는 하지 않는다 | **초안 있음**, 발송 전 | [`INQUIRY_STLOUISFED_STLFSI.md`](INQUIRY_STLOUISFED_STLFSI.md) |
| 한국거래소 | 실시간 시세와 KRX 통계정보 전체(§3.4). 장 마감값은 §3.9로 이미 해결됨 | 초안 없음. 우선순위 낮아짐 | — |
| Cboe | VIX·SKEW·VVIX·OVX·Put/Call | 서면 허가가 명시적으로 필요하고 월 예산 안의 근거가 없어 **문의하지 않기로** 결정 | — |

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
| `vix` | `vix`, `vixcls` | `xyz:VIX` 가능 시 | 공식 Cboe VIX 아님 | 공식값은 별도 lane에서 계속 `license_required` |
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
| `financial_stress` | `STLFSI4` | St. Louis Fed 별도 permission 또는 대체 자체 지수 | `license_required` | FRED 우회 복제 금지. 문의 대상(§4.1) |
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
| `high_yield_spread` | `BAMLH0A0HYM2` | ICE Data Indices | `license_required` | 계약 전 blank |
| `wti_exact`(신규) | `DCOILWTICO` | EIA `PET.RWTC.D` 후보 | `pending_review` | exact endpoint·units 재검증. `wti` proxy 카드와 별도 key |
| `vix_exact`(신규) | `VIXCLS` | Cboe | `license_required` | FRED를 통해 공개하지 않음. `vix` proxy 카드와 별도 key |
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
| Twelve Data Business | 외부 표시용 business/venture가 월 USD 149 이상으로 안내됨 | 예산 초과 | business 계약 범위 확인 필요 | [Business pricing](https://twelvedata.com/pricing-business), [Commercial vs personal use](https://support.twelvedata.com/en/articles/5332349-commercial-and-personal-usage) |
| Marketstack | Basic USD 9.99, Commercial Use 문구 | 가격만 보면 가능 | `commercial use`가 공개 재배포를 뜻하는지 서면 확인 전 구매 금지 | [Pricing](https://marketstack.com/pricing) |
| Alpha Vantage | 개인/표준 API와 commercial 문의 분리 | 불확실 | commercial/public display는 문의 필요 | [Terms](https://www.alphavantage.co/terms_of_service/) |
| Finnhub | 재배포/enterprise는 문의형 | 예산 내 근거 없음 | enterprise 계약 전 사용 금지 | [Pricing](https://finnhub.io/pricing-startups-and-enterprise) |

결론:

- 가격이 예산 안이라는 이유만으로 구매하지 않는다.
- 계약서에 `public display`, `redistribution`, `derived data`, `caching`, `API to end users`가 명시되지 않으면 Mulmit 요구를 충족한 것으로 보지 않는다.
- 첫 유료 결제 후보는 카드 수를 채우는 공급자가 아니라, 가장 필요한 소수 자산의 공개 표시 권리를 명확히 주는 공급자여야 한다.
- 현재 데이터 구독비 지출은 0원으로 유지한다. 예산이 50,000원으로 상향된 뒤에도 이 표에서 그 금액으로 열리는 재표시 클래스는 없다 — 개인 열람용 싼 티어를 공개 재표시에 쓰는 것은 클래스 착오이며 구매하지 않는다.

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
| 2026-08-17 | 공개 준비 정리: 레거시 lane 섹션(섹터 모니터·상관관계·종목 위험 분석)을 오류 표시 대신 숨김, analytics는 내부자 공시 조회 모드로 전환, 레코드 없는 라이선스·예약 카드 숨김. 데이터·권리 변경 없음 — lane이 열리면 화면이 저절로 복원된다 | Claude assisted |
| 2026-08-17 | 영구 공석 proxy 카드(코스닥·원달러 합성)를 한국 섹션에서 제거, 개요 타일을 공식 카드로 교체. 데이터·권리 변경 없음 | Claude assisted |
| 2026-08-17 | HIP-3 문의 **발송** — XYZ Ltd와 Hyperliquid Corp. 양쪽. P0의 마지막 미발송 항목 해소 | Claude assisted |
| 2026-08-17 | HIP-3 문의 초안 개정: XYZ Ltd·Hyperliquid Corp. 약관 정독 결과 반영, 연락처 확정, 기초 자산 원 권리자 질문을 최우선으로 이동. §4.1 문의 대기 목록 신설 | Claude assisted |
| 2026-08-17 | Fed Board 교역가중 달러지수 3종 연결(H.10, 기존 lane). Cboe 지수값 서면허가 조항 원문 인용 | Claude assisted |
| 2026-08-17 | 금융위원회 공공데이터 lane 추가(`DS-2026-006`). 코스피·코스닥·삼성전자·SK하이닉스 공식 종가를 KRX 승인과 별개 근거로 연결. `samsung` alias에서 `005930` 제거 | Claude assisted |
| 2026-08-17 | `Mulmit 유동성·스트레스 지수` 도입. CNN Fear & Greed 복제 대신 자체 산식 | Claude assisted |

