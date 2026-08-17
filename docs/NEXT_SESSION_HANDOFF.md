# Mulmit 다음 세션 인수인계

작성 기준일: 2026-08-16 (Asia/Seoul)  
기능 병합 기준: `092c3eed876e0d2f3ace49f97d83c2ee78f3a53f`  
운영 주소: <https://mulmit.com/>  
저장소: <https://github.com/subeom7/mulmit>

이 문서는 다음 Codex 세션이 현재 상태를 다시 조사하지 않고 바로 이어서 작업하기 위한 실행 문서다. 데이터 라이선스에 관한 내용은 개발상 보수적인 판단이며 법률 자문이 아니다. 공개 표시 권한은 공급자 또는 원 권리자의 서면 답변으로 확정한다.

## 1. 다음에 해야 할 일

핵심은 단순히 API 키를 추가하는 것이 아니다. 다음 순서로 진행한다.

1. ~~`FRED_ENABLED=false`인데도 과거 DB 행이 macro API에서 노출될 수 있는 serving gate를 먼저 막는다.~~ **완료 (2026-08-16).** `app/data_rights.py`에서 공급자 lane 단위로 판정한다. 운영 DB의 FRED 행은 0건으로 확인되어 purge 대상이 없다.
2. 현재 공개 중인 HIP-3 합성 시세의 외부 표시 권한을 서면으로 확인하거나, 확인 전까지 공개 API를 기능 플래그 뒤로 옮긴다.
3. ~~FRED 중심 저장 구조를 공급자 중립적인 거시 시계열 구조로 바꾼다.~~ **완료 (2026-08-17).** `economic_series`/`economic_observations`와 행 단위 `rights_status`. 마이그레이션은 `python -m app.ingest --migrate-macro`.
4. FRED를 우회 수집하지 말고 각 원 발행기관의 공식 피드를 직접 연결한다.
5. KRX는 Mulmit 공개 화면 사용 목적을 정확히 적어 승인을 받은 뒤 연결한다.
6. VIX·SKEW·VVIX·OVX·Put/Call Ratio·ICE BofA 스프레드는 계약 전까지 `license_required`를 유지한다.
7. 가격 이력이 확보된 뒤에만 섹터 수익률, 상관관계, MDD와 개별 종목 분석을 다시 연다.

월 데이터 예산은 약 30,000원이다. 이 예산에서는 광범위한 글로벌 실시간 시세의 공개 재표시 라이선스를 구매하기 어렵다. 우선 원 발행기관의 공식 데이터와 제공자가 직접 렌더링하는 위젯을 사용하고, 커스텀 가격 카드가 꼭 필요한 영역만 별도 견적을 받는 것이 현실적이다.

## 2. 다음 세션 시작 명령

작업 경로는 이전 이름이 아니라 아래 경로다.

```powershell
Set-Location C:\Users\subeo\mulmit
git -c safe.directory=C:/Users/subeo/mulmit status --short --branch
git -c safe.directory=C:/Users/subeo/mulmit pull --ff-only origin main
```

`.claude/`는 사용자의 로컬 개인 설정이므로 스테이징하거나 수정하지 않는다.

문서를 먼저 읽는다.

```powershell
Get-Content docs\NEXT_SESSION_HANDOFF.md -Encoding UTF8
Get-Content docs\DATA_SOURCE_REGISTER.md -Encoding UTF8
```

새 작업 브랜치 예시:

```powershell
git -c safe.directory=C:/Users/subeo/mulmit switch -c agent/licensed-data-sources
```

모든 Codex 작성 커밋에는 다음 트레일러를 넣는다.

```text
Co-authored-by: Codex <codex@openai.com>
```

## 3. 현재 운영 상태

### 3.1 배포와 검증

- PR #5가 `main`에 병합됐다: <https://github.com/subeom7/mulmit/pull/5>
- 병합 배포 워크플로가 성공했다: <https://github.com/subeom7/mulmit/actions/runs/31946528955>
- CI는 Python 3.11, Ruff, 전체 테스트를 실행한다.
- 병합 시점 전체 테스트는 151개다.
- `/`는 시장 모니터, `/monitor`는 별칭, `/analytics`는 기존 개별 티커 분석 화면이다.
- KO/EN 전환, 다크/라이트 테마, 모바일 레이아웃, 키보드 접근성 구조가 들어가 있다.
- TradingView S&P 500 히트맵은 1D·1W·1M·1Y 전환이 가능하다.

### 3.2 운영 API 스냅샷

2026-08-16 배포 직후 확인한 상태다. 실시간 시장 수와 값은 이후 달라질 수 있다.

| 경로 | 상태 | 의미 |
|---|---:|---|
| `GET /api/health` | 200 | 앱 헬스 정상 |
| `GET /api/status` | 200 | `provider=disabled`, `legacy_price_data_enabled=false` |
| `GET /api/market/assets?history=3y` | 200 | HIP-3 17개 정의 중 당시 10개 사용 가능, 7개 미연결 |
| `GET /api/market/weekend` | 200 | 직접·보조 신호 8개, 합성 신호 2개 |
| `GET /api/market/macro?history=3y` | 200 | 15개 미수집, 3개 `license_required` |
| `GET /api/market/sectors` | 503 | 레거시 가격 공급자 비활성 상태가 정상 |
| `GET /api/correlation` | 503 | 레거시 가격 공급자 비활성 상태가 정상 |
| `GET /api/metrics` | 503 | 레거시 가격 공급자 비활성 상태가 정상 |

> **해소됨 (2026-08-16, `agent/rights-serving-gate`):** 위 표는 serving gate 이전
> 스냅샷이다. 현재는 `FRED_ENABLED=false`에서 `/api/market/macro`와 상세 route가
> `macro_data_disabled` 503과 `Cache-Control: no-store`를 반환하고, seeded DB에서도
> 값·관측치가 0건이다. 판정은 `app/data_rights.py`의 **공급자 lane 단위**라서
> 이후 승인되는 NY Fed·BLS·EIA lane은 FRED lane이 닫힌 채로도 독립적으로 열린다.
> `HIP3_PUBLIC_DISPLAY_ENABLED`가 꺼지면 `/api/market/assets`와
> `/api/market/weekend`도 같은 방식으로 `pending_rights` 503을 반환한다.
> 운영 DB의 FRED 행은 0건으로 확인되어 purge 대상이 없다(`/api/status`의
> `fred_series`·`fred_observations`).

### 3.3 현재 값이 표시되는 영역

아래 값은 현물·공식 종가가 아니라 trade.xyz가 Hyperliquid HIP-3에 상장한 합성 무기한선물 참고값이다.

- S&P 500 합성 무기한선물: `xyz:SP500`
- XYZ100 나스닥 대용 지표: `xyz:XYZ100`
- 금 합성 무기한선물: `xyz:GOLD`
- KR200: `xyz:KR200`
- 삼성전자 USD 환산 합성 무기한선물: `xyz:SMSN`
- 브라질 EWZ 무기한선물: `xyz:EWZ`
- 일본 EWJ 무기한선물: `xyz:EWJ`
- 달러/엔 합성 무기한선물: `xyz:JPY`
- WTI/CL 연계 합성 무기한선물: `xyz:CL`
- 구리 연계 합성 무기한선물: `xyz:COPPER`

주말 영역에는 다음 8개 직접 또는 보조 신호와 2개 합성 신호가 있다.

- 직접 계약: `xyz:SKHX`, `xyz:SMSN`, `xyz:KR200`, `xyz:HYUNDAI`, `xyz:XYZ100`
- 24시간 보조: `xyz:EWY`, `xyz:KORU`, `mkts:USTECH`
- 합성: `korea_weekend`, `nasdaq_weekend`

`EWY`, `KORU`, `USTECH`는 세션 합성값에 섞지 않는 24시간 보조값이다. 한국 합성 신호는 KR200·삼성전자·SK하이닉스·현대차 직접 계약만 사용한다.

### 3.4 현재 미연결 또는 제한된 영역

자산 카드에서 당시 미연결:

- 비트코인
- KOSDAQ
- 원/달러
- 인도 NIFTY/INDA 대용 카드
- 베트남 VNM
- DXY
- VIX 연계 합성값

거시·유동성에서 미수집:

- `T10Y2Y`, `STLFSI4`, `DGS10`, `M2SL`
- `UNRATE`, `ICSA`
- `WALCL`, `WRESBAL`, `RRPONTSYD`, `WTREGEN`, `WRMFNS`
- `SOFR`, `EFFR`, `IORB`
- `DCOILWTICO`

계약 전 비공개:

- `VIXCLS`
- `BAMLH0A0HYM2`
- `PCOPPUSDM`
- CBOE SKEW, VVIX, OVX, Put/Call Ratio

별도 입력이 없는 영역:

- Mulmit 자체 시장 심리 지수
- S&P 500 11개 섹터 ETF 수익률
- 자산군 상관관계
- 개별 티커 CAPM·MDD 분석용 공개 가격 이력

## 4. 절대 유지해야 하는 경계

### 4.1 공개 API 접근과 재표시 권리는 다르다

API가 인증 없이 열려 있거나 무료라고 해서 Mulmit이 그 값을 자체 API로 다시 공개할 권리가 자동으로 생기지 않는다. 공급자 이용약관, 원 기초 데이터 권리, 거래소 표시 계약을 각각 확인한다.

### 4.2 정확한 지표와 대용 지표를 섞지 않는다

- `xyz:XYZ100`을 Nasdaq Composite 또는 공식 Nasdaq-100이라고 표시하지 않는다.
- `xyz:KR200`을 KOSPI Composite라고 표시하지 않는다.
- `xyz:SMSN`을 삼성전자 원화 현물 종가라고 표시하지 않는다.
- `xyz:CL`을 WTI 현물 또는 CME/NYMEX 공식 결제값이라고 표시하지 않는다.
- `xyz:COPPER`를 IMF 구리 시계열 또는 공식 거래소 결제값이라고 표시하지 않는다.
- 주말 합성 신호를 월요일 시가 예측이라고 표현하지 않는다.

### 4.3 누락값을 임의의 숫자로 채우지 않는다

공급자 실패, 휴장, 상장폐지, 권리 미확인, 기준선 실패는 모두 null 또는 명시적 상태로 반환한다. 이전 값, 다른 티커, 검색 결과, 페이지 스크래핑 값을 조용히 대체하지 않는다.

### 4.4 기본 비활성 플래그를 성급히 켜지 않는다

현재 배포 기본값:

```dotenv
LEGACY_PRICE_DATA_ENABLED=false
FRED_ENABLED=false
KRX_ENABLED=false
HIP3_PUBLIC_DISPLAY_ENABLED=false
```

- `LEGACY_PRICE_DATA_ENABLED=true`는 Yahoo/yfinance 기반 경로를 다시 열기 때문에 공개 배포에서 사용하지 않는다.
- `FRED_ENABLED=true`는 현행 FRED 약관상 저장·캐시·제3자 제공 문제를 해결하지 못한다.
- `FRED_ENABLED=false`는 수집과 서빙을 모두 막는다. DB에 행이 남아 있어도 값이 나가지 않는다.
- `KRX_ENABLED=true`는 API 키 보유가 아니라 정확한 공개 사용 승인을 받은 뒤에만 고려한다.
- `HIP3_PUBLIC_DISPLAY_ENABLED`는 코드 기본값 false다. 서면 확인 전 현행 화면을 유지하기로 결정한 경우에만 서버 `.env`에서 true로 두고, 그 결정과 유효기간을 source register에 남긴다.

권리 게이트 변수는 `docker-compose.yml`의 공용 `x-app` env에 있어 `web`과 `ingest`
양쪽에 전달된다. 서빙에 영향을 주는 플래그를 `ingest` 블록에만 두면 web이 이미지
기본값으로 판정해 운영 값과 어긋나므로, 새 게이트를 추가할 때도 `x-app`에 올린다.

## 5. 우선순위별 실행 계획

### P0. Serving gate, 권리 안전장치와 의사결정 기록

목표: 권리가 확인되지 않은 공급자가 설정 실수로 공개되지 않게 한다.

> 상태(2026-08-17): 1·2·3·4·6·8·9·10은 `agent/rights-serving-gate`에서 구현·검증했다.
> 5는 운영 DB에 FRED 행이 0건으로 확인되어 옮기거나 지울 대상이 없다.
> **남은 항목은 7(HIP-3/trade.xyz 서면 문의 발송 및 회신 기록) 하나뿐이다.**

1. `FRED_ENABLED=false`이면 DB에 FRED 행이 있어도 `/api/market/macro`와 상세 route가 그 행의 값·변화·관측치를 절대 반환하지 않게 한다. 판정 단위는 series의 공급자 lane이며, 등록되지 않은 lane은 fail-closed로 본다.
2. 서빙 가능한 lane이 하나도 없으면 macro 응답은 구조화된 503(`macro_data_disabled`)을 쓰고 `public` Cache-Control을 `no-store`로 바꾼다. lane이 하나라도 열려 있으면 200을 유지하되 막힌 lane의 series는 응답에서 제외하거나 `disabled` 상태로만 표시한다.
3. `app/macro_dashboard.py`에도 방어 검사를 두어 route 우회나 재사용 코드에서도 fail-closed가 되게 한다.
4. 프런트도 같은 계약을 이해해야 한다. `monitor.js`는 `macro_data_disabled`와 `pending_rights`를 재시도 오류가 아니라 `disabled` 상태로 표시하고, 연결 배지·카드 배지·주말 패널을 각각 disabled 문구로 바꾼다. 기존 `legacyDisabled()`는 `legacy_price_data_disabled` 하나만 보므로 코드 집합을 확장한다.
5. 운영 DB의 기존 `fred_series`/`fred_observations`를 purge할지 quarantine할지 결정하고 배포 runbook에 기록한다.
6. `docs/DATA_SOURCE_REGISTER.md`의 각 공급자 상태를 갱신한다.
7. HIP-3/trade.xyz에 다음 사용 목적을 포함해 서면 문의한다.
   - 공개 웹사이트
   - 로그인 없는 불특정 다수 열람
   - mark/oracle, funding, open interest, day notional 표시
   - 30초 캐시와 5분 stale fallback
   - Mulmit 자체 JSON API를 통한 브라우저 전달
   - 비상업 개인 프로젝트인지, 향후 광고·유료화 가능성이 있는지
8. 허가를 받기 전의 안전한 구현은 `HIP3_PUBLIC_DISPLAY_ENABLED=false` 기본 플래그다. 코드 기본값은 false로 두고, 서면 답변 전 현행 화면을 유지할지 여부는 서버 `.env`에서 결정한다. 결정과 근거는 source register에 기록한다.
9. 비활성일 때 `/api/market/assets`와 `/api/market/weekend`는 가짜 200 숫자가 아니라 구조화된 503 또는 `disabled` 상태를 반환한다.
10. TradingView 위젯은 공급자가 직접 렌더링하므로 자체 API 데이터와 분리한 현재 구조를 유지한다.

권장 코드 위치:

- `app/config.py`: 공개 표시 플래그와 권리 상태
- `app/data_rights.py`(신규): 공급자 lane별 serving 판정 한 곳에 모음
- `app/main.py`: 라우트 fail-closed 게이트
- `app/macro_dashboard.py`: 저장값 reader의 이중 방어
- `app/market_assets.py`, `app/weekend_signals.py`: 권리 메타데이터
- `app/static/monitor.js`: `macro_data_disabled`·`pending_rights`의 disabled 렌더링
- `deploy/env.example`, `docker-compose.yml`: 기본값 false. compose는 `web` 서비스에도 게이트 변수를 넘겨야 한다(현재 FRED/KRX 변수는 `ingest`에만 있어서 web은 이미지 기본값을 쓴다)
- `tests/test_macro_api.py`, `tests/test_legacy_gate.py`, `tests/test_fred_store.py`와 새 권리 게이트 테스트

기존 테스트 fixture 보완:

`tests/conftest.py`의 `db` fixture는 `FRED_ENABLED=False`를 고정한다. serving gate가
들어가면 `tests/test_macro_api.py`의 기존 200 기대값이 전부 깨진다. `legacy_price_data`
fixture와 같은 방식으로 FRED lane을 의도적으로 여는 opt-in fixture를 추가하고,
기존 조립 테스트는 그 fixture를 쓰도록 바꾼다. 기본 `db` fixture만 쓰는 테스트는
차단된 상태를 검증하는 쪽으로 남긴다.

완료 기준:

- 서면 승인 문서의 날짜·범위·URL 또는 파일 위치가 source register에 기록됨
- `FRED_ENABLED=false` + seeded DB에서 overview/detail 값·관측치가 0건이고 공개 캐시 헤더가 없음
- 승인 범위가 없으면 운영 기본값에서 값이 노출되지 않음
- 게이트가 FRED lane에만 걸리고, 승인된 lane을 추가해도 코드 구조 변경 없이 열림
- UI가 `데이터 미연결`(`missing`)과 `권리 확인 중`(`pending_rights`), `비활성`(`disabled`)을 구분함

### P1. 거시 저장소를 공급자 중립 구조로 전환

> **완료 (2026-08-17, `agent/economic-series-store`).** `economic_series` /
> `economic_observations`를 추가했고 조립기는 새 테이블을 우선 읽는다. 아직
> 마이그레이션되지 않은 계열만 레거시 `fred_*`로 폴백한다. ingest는 새 테이블에만
> 쓴다. 마이그레이션은 부팅이 아니라 명시적 실행이다.
>
> ```powershell
> python -m app.ingest --migrate-macro
> ```
>
> 운영 DB에는 FRED 행이 0건이라 실행이 필수는 아니지만, 레거시 행이 있는 환경에서는
> 이 명령으로 옮긴다. 기존 테이블은 삭제하지 않는다.
>
> 추가된 것: 행 단위 `rights_status`. lane 게이트가 "이 공급자를 서빙해도 되는가"를
> 답하고, 행이 "이 계열을 서빙해도 되는가"를 답한다. 둘 다 통과해야 값이 나간다.
> 그래서 FRED lane이 열려도 `VIXCLS`(Cboe 권리)는 계속 비어 있다.

현재 `fred_series`, `fred_observations`, `save_fred_series()`처럼 이름과 메타데이터가 FRED에 묶여 있다. 원 발행기관을 직접 연결하려면 이 구조부터 일반화한다.

권장 새 모델:

```text
economic_series
  series_key             내부 안정 키
  provider_id            nyfed | bls | eia | federal_reserve | treasury | licensed_vendor
  provider_series_id     공급자 원본 ID
  title, units, frequency, seasonal_adjustment
  publisher, publisher_url, series_url
  rights_status          approved | pending | license_required | disabled
  rights_evidence        약관/서면 승인 근거
  fetched_at, last_attempted_at, status, error

economic_observations
  series_key, date, value
```

마이그레이션 원칙:

1. 새 테이블을 먼저 만든다.
2. 기존 FRED 테이블은 즉시 삭제하지 않는다.
3. API 조립기는 새 테이블을 우선 읽고, 전환 기간에는 필요한 경우에만 기존 테이블을 읽는다.
4. 모든 응답에 `provider`, `publisher`, `source.url`, `rights.status`, `as_of`, `fetched_at`을 유지한다.
5. 공급자별 원 단위를 저장하고 UI에서 단위를 추정하지 않는다.
6. Postgres와 SQLite 양쪽을 테스트한다.

관련 파일:

- `app/store.py`
- `app/macro_dashboard.py`
- `app/providers/fred.py`
- `app/ingest.py`
- `tests/test_fred_store.py`
- `tests/test_macro_api.py`

이 단계에서 이름만 바꾸고 FRED 수집을 켜면 안 된다.

### P2. 원 발행기관의 공식 거시 피드 연결

첫 구현 묶음은 권리·형식이 비교적 명확하고 화면 효과가 큰 다음 세 종류를 권장한다.

1. New York Fed: SOFR, EFFR
2. BLS: 미국 실업률 (`LNS14000000`을 후보로 검증)
3. EIA: WTI 일간 현물 계열 (`PET.RWTC.D` 후보를 API v2에서 검증)

그 다음 묶음:

1. Federal Reserve Board H.15: 10년물·2년물 금리
2. 10Y-2Y: 두 공식 계열을 같은 날짜로 정렬해 Mulmit에서 계산
3. Federal Reserve Board H.4.1: 총자산·지급준비금·TGA 후보
4. New York Fed: 역레포 잔액
5. Federal Reserve Board H.6: M2·리테일 MMF 후보
6. DOL ETA: 주간 신규 실업수당
7. IORB: Federal Reserve Board 공식 정책금리 자료

각 공급자 구현 규칙:

- 새 provider 파일은 `app/providers/<provider>.py`에 둔다.
- HTTP 전송을 주입 가능하게 만들어 네트워크 없는 fixture 테스트를 작성한다.
- timeout, 429/5xx 재시도, 스키마 검증, 비밀키 비노출을 테스트한다.
- 수집은 `ingest` 컨테이너에서만 실행하고 요청 경로에서는 공급자를 호출하지 않는다.
- 전체 현재 빈티지를 받는 공급자는 원자적 교체, 증분 공급자는 날짜 upsert를 사용한다.
- 휴일의 빈 응답을 오류나 0으로 바꾸지 않는다.
- `last_updated`, `observation date`, `fetched_at`을 서로 구분한다.
- 원 발행기관 출처와 약관 링크를 카드 및 API에 포함한다.

환경변수 예시:

```dotenv
NYFED_ENABLED=false
BLS_ENABLED=false
BLS_API_KEY=
EIA_ENABLED=false
EIA_API_KEY=
FED_BOARD_ENABLED=false
TREASURY_ENABLED=false
```

키가 없어도 앱이 부팅되고 해당 series만 `not_configured`가 되어야 한다.

### P3. 한국 자산 연결

KRX 어댑터는 이미 있다.

- 파일: `app/providers/krx.py`
- 테스트: `tests/test_krx_provider.py`
- 준비된 항목: KOSPI 종목 일별매매정보, KOSPI 지수, KOSDAQ 지수
- 삼성전자 `005930`, SK하이닉스 `000660` 선택 로직이 있다.

다음 세션에서 바로 `KRX_ENABLED=true`로 바꾸지 않는다. 먼저 KRX 신청서에 Mulmit의 정확한 공개 화면, 캐시, 사용자 범위, 수익화 여부를 적어 승인 또는 별도 데이터 분배 계약 필요 여부를 확인한다.

승인 후 구현 순서:

1. KRX API별 관리자 승인과 키를 확인한다.
2. 하루에 종목 전체 1회, KOSPI 지수 1회, KOSDAQ 지수 1회만 수집한다.
3. 주말·휴일은 제한된 일수만 이전 영업일로 backtrack한다.
4. `한국거래소 통계정보` 출처를 화면에 표시한다.
5. 원화, 지수 포인트, 조정주가 여부를 명시한다.
6. 삼성전자·SK하이닉스·KOSPI·KOSDAQ 카드와 역사 차트를 연결한다.
7. HIP-3 주말 신호와 KRX 현물 종가를 같은 상품처럼 합치지 않는다.

원/달러 환율은 한국은행 ECOS 또는 다른 공식 피드를 후보로 조사하되, ECOS의 공개 재표시·저장 조건을 먼저 source register에 기록한다.

### P4. 라이선스가 필요한 지표

다음 값은 우회 스크래핑하거나 검색 결과 숫자로 채우지 않는다.

| 지표 | 필요한 권리/공급자 | 예산 내 기본 결정 |
|---|---|---|
| VIX | Cboe 공식 외부 표시 권리 | `license_required` 유지 |
| SKEW | Cboe | `license_required` 유지 |
| VVIX | Cboe | `license_required` 유지 |
| OVX | Cboe | `license_required` 유지 |
| Put/Call Ratio | Cboe, 계약 범위와 산식 명시 | `license_required` 유지 |
| ICE BofA HY OAS | ICE Data Indices | `license_required` 유지 |
| IMF 구리 정확 계열 | IMF/원 권리 조건 | 현재 HIP-3 proxy와 명확히 분리 |
| STLFSI4 | St. Louis Fed 권리 확인 | permission 또는 공식 embed 검토 |

CNN Fear & Greed는 공식 공개 API를 가정하지 않는다. 대신 `Mulmit Market Sentiment`를 만들 수 있다.

자체 지수 조건:

- 모든 입력이 공개 표시 가능한 소스여야 한다.
- 산식, 가중치, 정상화 구간, 결측 처리, 리밸런싱 주기를 공개한다.
- `CNN Fear & Greed`라는 이름이나 점수를 복제하지 않는다.
- 최소 5년 백테스트와 입력 누락 테스트를 추가한다.
- 화면에는 자체 지수임을 명시한다.

### P5. 섹터·상관관계·개별 분석 복구

현재 TradingView 종목 히트맵은 정상이며 유지한다. Mulmit 자체 섹터 ETF 수익률, 상관관계, 개별 티커 분석은 합법적인 역사 가격 공급자가 생긴 뒤에 연다.

필요한 데이터:

- 섹터 ETF: XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY
- 상관관계: 대표 주식·채권·금·달러·원유·비트코인 일간 종가
- 개별 분석: 조정주가, 기업 메타데이터, S&P 500 벤치마크, 무위험수익률

기술 조건:

- 요청 중 공급자 호출 금지
- 배치 수집 및 DB 읽기 전용 요청 경로
- 공급자·통화·거래일·조정 방식 기록
- 상관관계는 최대 12개 제한 유지
- 섹터 API는 1d·1w·1m·1y 기준일을 거래일 기준으로 계산
- 주말·휴일은 가장 가까운 이전 종가를 사용하되 기준일을 응답에 표시
- 가격 이력 사용 권한이 없으면 503을 유지

## 6. 추천 첫 번째 구현 PR 범위

한 PR에 모든 대시보드 연결을 넣지 않는다. 다음 범위가 가장 안전하다.

### PR A: 권리 게이트와 공급자 중립 저장소

- HIP-3 공개 표시 플래그 추가
- source rights 상태 enum과 응답 메타데이터 추가
- `economic_series` / `economic_observations` 추가
- 기존 FRED 테이블 유지한 채 새 reader/writer 추가
- `/api/status`에 각 데이터 lane 상태 노출
- UI에 `pending_rights`, `not_configured`, `disabled`, `stale`, `license_required` 구분
- 테스트와 README/env 갱신

### PR B: NY Fed + BLS

- SOFR, EFFR, 실업률 provider
- 배치 수집과 DB 정규화
- 기존 카드와 비교 차트 연결
- 출처·단위·신선도·약관 표시
- fixture 기반 테스트

### PR C: EIA + Federal Reserve Board

- WTI 공식 계열
- 10Y·2Y와 계산된 10Y-2Y
- H.4.1 유동성 계열
- 기존 HIP-3 WTI proxy와 공식 WTI 카드를 충돌 없이 구분

### PR D: KRX 승인 후 한국 현물

- KOSPI, KOSDAQ, 삼성전자, SK하이닉스
- KRX 일일 bulk 수집
- 원화·거래일·출처 표기
- 주말 HIP-3 참고 신호와 현물 카드 분리

## 7. API 계약 유지사항

거시 overview:

```text
GET /api/market/macro?history=1y|2y|3y|5y|10y|max
```

P0 완료 전에는 기존 route가 DB의 과거 FRED 행을 읽을 수 있다. P0 이후의 비활성
계약은 다음 중 하나를 명시적으로 택하고 overview/detail에 동일하게 적용한다.

```json
{
  "detail": {
    "code": "macro_data_disabled",
    "message": "No approved macro data source is enabled."
  }
}
```

구조화된 503을 권장한다. UI는 이를 재시도 오류가 아니라 `disabled`로 표시하고,
응답 헤더는 `Cache-Control: no-store`로 한다. 이후 원 발행기관 피드가 하나라도
승인되면 전체 FRED flag가 아니라 series별 `rights.status=approved`를 기준으로
공급자 중립 응답을 만든다. 즉 503은 “FRED가 꺼졌다”가 아니라 “서빙 가능한 lane이
0개다”라는 뜻이고, lane이 하나라도 열리면 route는 200으로 돌아온다.

HIP-3 lane이 아직 서면 확인 전이면 `/api/market/assets`와 `/api/market/weekend`도
같은 형태를 쓴다.

```json
{
  "detail": {
    "code": "hip3_public_display_pending_rights",
    "status": "pending_rights",
    "message": "Public display rights for Hyperliquid HIP-3 data are not confirmed."
  }
}
```

프런트 처리 규칙:

- `legacy_price_data_disabled`, `macro_data_disabled`, `hip3_public_display_pending_rights`는 모두 `disabled` 계열로 묶어 재시도 안내를 띄우지 않는다.
- 연결 배지는 이 세 코드로 인한 실패를 `status.offline`이 아니라 별도 disabled 문구로 표시한다.
- series 단위 `rights.status`가 `pending_rights`면 값과 차트를 비우고 `권리 확인 중` 배지를 단다. `license_required`와 문구를 섞지 않는다.
- `missing`(공급자 미연결), `pending_rights`(권리 미확인), `license_required`(계약 필요), `disabled`(운영자가 끔)는 서로 다른 문구를 쓴다.

UI가 기대하는 핵심 구조:

```json
{
  "generated_at": "ISO-8601",
  "history": "3y",
  "provider": {"id": "multi-source", "name": "Official source feeds"},
  "groups": [],
  "series": [
    {
      "id": "SOFR",
      "key": "sofr",
      "label": {"ko": "SOFR", "en": "SOFR"},
      "source": {"provider": "nyfed", "publisher": "Federal Reserve Bank of New York", "url": "https://..."},
      "units": {"long": "Percent", "short": "%"},
      "latest": {"date": "YYYY-MM-DD", "value": 0.0},
      "previous": {"date": "YYYY-MM-DD", "value": 0.0},
      "change": {"value": 0.0, "percent": null},
      "freshness": {"status": "fresh", "age_seconds": 0, "max_age_seconds": 21600},
      "rights": {"status": "approved", "notice": "..."},
      "observations": [{"date": "YYYY-MM-DD", "value": 0.0}]
    }
  ],
  "missing": [],
  "restricted": []
}
```

규칙:

- 금리처럼 0이 가능한 값은 falsy 검사로 버리지 않는다.
- 변화율 분모가 0이면 percent는 null이다.
- `license_required`와 `pending_rights`는 `latest`, `previous`, `change`, `observations`를 모두 비운다.
- API가 원 단위를 주지 않으면 UI가 `$B`나 `$T`를 추정하지 않는다.
- `publisher`는 집계 API 이름이 아니라 원 발행기관을 우선한다.
- 최대 공개 관측치 수와 downsampling은 유지한다.
- 공식값과 HIP-3 proxy는 끝까지 별도 key/lane으로 둔다. `wti`(HIP-3 `xyz:CL`)와 `wti_exact`(EIA), `vix`(HIP-3)와 `vix_exact`(Cboe), `copper`(HIP-3)와 `copper_exact`(IMF), `kospi`(HIP-3 `xyz:KR200`)와 KRX 공식 종가는 서로 다른 카드·시계열이다. 공식값이 승인되어도 proxy series를 같은 key로 덮어쓰거나 두 시계열을 이어 붙이지 않는다.

## 8. 테스트 체크리스트

### 공급자 단위 테스트

- 정상 JSON/XML/CSV 응답
- 빈 관측치
- 휴일과 주말
- 401/403 키 오류
- 429 재시도와 `Retry-After`
- 5xx 재시도
- 잘못된 스키마
- NaN, `.`, 공백 값
- 날짜 정렬과 중복 제거
- API 키가 예외 메시지에 포함되지 않음

### 저장소 테스트

- SQLite와 Postgres 호환 SQL
- 원자적 교체 중 실패 시 이전 good snapshot 보존
- 같은 관측치 재수집의 idempotency
- stale 판정
- 공급자와 publisher 보존
- 권리 상태가 `approved`가 아니면 공개 reader가 값을 반환하지 않음

### API 테스트

- `history` 검증
- unknown series 404
- disabled/not configured 상태
- `FRED_ENABLED=false` + seeded DB에서도 overview/detail 값·관측치 비공개
- disabled macro 응답에 `Cache-Control: no-store` 적용
- 게이트가 lane 단위인지: 승인된 다른 lane이 있으면 macro route가 200을 유지
- `HIP3_PUBLIC_DISPLAY_ENABLED=false`에서 assets·weekend가 구조화된 503
- restricted 값 비공개
- Cache-Control과 X-Data-Source
- 1,500개 이하 downsampling과 양 끝점 보존
- 공급자 장애가 다른 데이터 lane을 막지 않음

### UI 테스트

- KO/EN 번역 키 누락 0
- null, 0, 음수, 큰 단위 포맷
- stale/missing/restricted/pending-rights/disabled 구분
- `macro_data_disabled`와 `hip3_public_display_pending_rights` 503에서 재시도 문구 대신 disabled 문구가 나오고 연결 배지가 `offline`이 아님
- 동일 카드에 공식 값과 proxy가 동시에 들어올 때 공식/대용 라벨 보존
- 모바일 390px 가로 overflow 0
- 버튼 이름, `aria-pressed`, status region
- TradingView iframe 한 개, 1D·1W·1M·1Y 전환
- 콘솔 error/warn 0

### 전체 검증 명령

```powershell
python -m pytest -q
python -m ruff check app tests scripts cli.py
node --check app/static/monitor.js
git -c safe.directory=C:/Users/subeo/mulmit diff --check
docker compose config --quiet
```

Windows에서 requirements 파일의 한글 주석 디코딩 문제가 나면 임시로 UTF-8 모드를 사용한다.

```powershell
$env:PYTHONUTF8='1'
python -m pip install -r requirements-dev.txt
```

## 9. 배포 절차

1. 기능 브랜치에서 작업한다.
2. 변경 파일만 명시적으로 스테이징한다. `.claude/`는 제외한다.
3. staged diff와 secret을 확인한다.
4. Codex 공동 작성자 트레일러를 포함해 커밋한다.
5. 브랜치를 push하고 draft PR을 연다.
6. PR CI의 설치·Ruff·테스트를 모두 확인한다.
7. Ready로 전환하고 검증한 head SHA를 고정해 merge한다.
8. main 워크플로의 test → ARM build → SSM deploy를 확인한다.
9. 운영 화면과 API를 직접 smoke test한다.

운영 확인 경로:

```text
https://mulmit.com/
https://mulmit.com/analytics
https://mulmit.com/api/health
https://mulmit.com/api/status
https://mulmit.com/api/market/assets?history=3y
https://mulmit.com/api/market/weekend
https://mulmit.com/api/market/macro?history=3y
https://mulmit.com/api/market/sectors
```

배포는 `.github/workflows/deploy.yml`, 서버 롤백은 `deploy/release.sh`를 따른다. 서버 `.env`는 저장소에 커밋하지 않는다.

## 10. 하지 말아야 할 것

- Yahoo, CNN, Cboe, ICE, TradingView 페이지를 서버에서 스크래핑하지 않는다.
- TradingView iframe 안의 숫자를 추출해 Mulmit API로 재배포하지 않는다.
- 개인용 API 요금제를 공개 웹 표시 권한으로 해석하지 않는다.
- `commercial use` 문구만 보고 `redistribution`까지 허용됐다고 가정하지 않는다.
- FRED 시리즈 페이지에 숫자가 보인다는 이유로 FRED API 콘텐츠를 DB에 저장하지 않는다.
- KRX 키 발급만으로 공개 재배포가 허용됐다고 가정하지 않는다.
- 휴장일 값을 0으로 저장하지 않는다.
- 공식 현물과 합성 무기한선물을 한 시계열로 이어 붙이지 않는다.
- 사용자가 지정한 월 예산을 넘는 계약을 승인 없이 구매하지 않는다.
- secret, API key, 서면 계약 원문 중 비공개 내용을 git에 넣지 않는다.

## 11. 다음 세션에 붙여 넣을 프롬프트

```text
C:\Users\subeo\mulmit에서 계속 작업해줘.

먼저 docs/NEXT_SESSION_HANDOFF.md와 docs/DATA_SOURCE_REGISTER.md를 끝까지 읽고,
현재 main과 운영 상태를 확인해. .claude/는 건드리거나 커밋하지 마.

가장 먼저 FRED_ENABLED=false + seeded DB에서도 macro overview/detail 값과 관측치가
절대 노출되지 않는 serving gate를 구현하고, 공개 cache header도 제거해.

그 다음 우선순위는 HIP-3 권리 게이트와 공급자 중립 economic_series 저장소야.
FRED_ENABLED, KRX_ENABLED, LEGACY_PRICE_DATA_ENABLED는 서면 권리 근거 없이 켜지 마.
HIP-3 공개 표시 권리가 아직 확인되지 않았다면 안전한 기본 비활성 플래그와
UI의 pending_rights 상태를 구현해. 이후 NY Fed/BLS/EIA 등 원 발행기관 피드는
공식 약관을 다시 확인하고, 승인된 source만 fixture 테스트부터 구현해.

모든 값에는 source/publisher/units/as_of/fetched_at/rights를 유지하고,
누락값을 다른 값으로 대체하지 마. 전체 테스트, Ruff, Node syntax, compose config,
desktop/mobile QA를 통과한 뒤 PR을 만들고 CI를 확인해.

Codex가 만든 모든 커밋에는 정확히 아래 트레일러를 넣어:
Co-authored-by: Codex <codex@openai.com>
```

## 12. 관련 파일 빠른 색인

| 역할 | 파일 |
|---|---|
| 라우트와 게이트 | `app/main.py` |
| 공급자 lane 권리 판정 | `app/data_rights.py` |
| 환경변수 | `app/config.py` |
| 배치 조율 | `app/ingest.py` |
| DB 테이블·저장 | `app/store.py` |
| SEC EDGAR 어댑터 | `app/providers/sec_edgar.py` |
| 내부자거래 응답 조립 | `app/insider_filings.py` |
| 법적 고지 페이지 | `app/static/privacy.html`, `terms.html`, `disclaimer.html`, `legal.css`, `legal.js` |
| 거시 응답 조립 | `app/macro_dashboard.py` |
| FRED 카탈로그/어댑터 | `app/providers/fred.py` |
| KRX 어댑터 | `app/providers/krx.py` |
| HIP-3 클라이언트 | `app/providers/hyperliquid.py` |
| 자산 카드 | `app/market_assets.py` |
| 주말 신호 | `app/weekend_signals.py` |
| 시장 모니터 UI | `app/static/monitor.html`, `monitor.css`, `monitor.js` |
| 개별 분석 UI | `app/static/index.html` |
| 배포 환경 예시 | `deploy/env.example` |
| 컨테이너 구성 | `docker-compose.yml` |
| GitHub Actions | `.github/workflows/deploy.yml` |
| 배포·롤백 | `deploy/release.sh` |
| 권리·공급자 기록 | `docs/DATA_SOURCE_REGISTER.md` |
