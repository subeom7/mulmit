# 크립토 소스 서면 문의 초안 — Deribit · 두나무(Upbit) · Coinalyze · (CoinMarketCap 확인)

작성일: 2026-08-21 (Asia/Seoul)
관련: `docs/PLAN_CRYPTO_SECTION.md` §3·§9, `docs/DATA_SOURCE_REGISTER.md` §7(문의 템플릿)·§8(승인 기록).

발송 주체는 저장소 소유자(운영자)다. 비밀키·개인정보·비공개 견적은 이 파일에 적지 않는다.
회신은 `decision_id`와 함께 등록부 해당 공급자 섹션에 기록하고, 상태 변경과 게이트 플래그
변경은 같은 PR에 넣는다. 회신이 없을 때의 처리 규칙은 §5.

발송 전 공통 체크:

- 보내는 주소는 mulmit.com 도메인 메일(운영자 확인). 본문에 사이트 URL, 로그인 없는 공개
  대시보드, 공개 JSON API로 값이 나간다는 사실, 향후 광고 가능성을 **빠짐없이** 적는다 —
  전용 다운로드 UI가 없다는 말로 흐리지 않는다(등록부 §1).
- 문의 대상 엔드포인트·채널명을 정확히 쓴다(실측 2026-08-21 기준).

## 1. Deribit — DVOL (BTC·ETH 내재변동성 지수)

- **수신처**: `info@deribit.com` (Terms of Service §4.6 "In case you wish to make use of
  this Market Data and/or Derived Data for any non-personal use, please contact
  info@deribit.com"). 운영 주체 표기는 DRB Panama Inc.(ToS 정의). 2025년 Coinbase 인수
  이후 주체·약관이 갱신됐을 수 있으니 발송 직전 최신 ToS를 다시 연다.
- **근거 조항**: ToS §4.6 — Market Data·Derived Data(정의에 "indices" 포함)는 개인 용도
  한정, 공개·전달은 명시 승인 필요.
- **요청 범위**: `public/get_volatility_index_data`(currency BTC·ETH), `public/get_index_price`
  (`btcdvol_usdc`·`ethdvol_usdc`), WS 채널 `deribit_volatility_index.btc_usd`·`.eth_usd`.

```text
Subject: Public display permission for Deribit DVOL (BTC/ETH) on Mulmit

Hello Deribit team,

I operate Mulmit (https://mulmit.com), a publicly accessible bilingual (KO/EN)
market dashboard. It is currently a non-commercial personal project, but
advertising or sponsorship may be added later. Visitors are mostly in Korea.

Per Section 4.6 of your Terms of Service (use of Market Data for non-personal
purposes requires your explicit approval), I would like written confirmation
whether you permit all of the following for the Deribit Volatility Index (DVOL)
only — no order book, trade, or option chain data:

1. Displaying the current BTC DVOL and ETH DVOL values, their daily change, and a
   30-day history chart to unauthenticated website visitors.
2. Fetching the values on my server via public/get_volatility_index_data and
   public/get_index_price (btcdvol_usdc, ethdvol_usdc), and/or subscribing on
   the server or in the visitor's browser to the WebSocket channels
   deribit_volatility_index.btc_usd / .eth_usd.
3. Relaying the values through my own server-side JSON endpoint
   (/api/crypto/dvol) to my frontend. Note: this endpoint is unauthenticated,
   so anyone could read that JSON; I do not offer bulk download or CSV export.
4. Caching for 60 seconds and serving the last known value for up to 1 hour on
   failure; storing hourly/daily DVOL observations in a private database for up
   to 1 year to draw the history chart.
5. Showing DVOL next to clearly labelled, separately computed indicators of my
   own (e.g. realized volatility of BTC computed from other sources), with a
   note that they are not comparable.
6. Displaying the attribution you require (proposed: "Source: Deribit DVOL" with
   a link to https://www.deribit.com/ next to every value). I will not use the
   Deribit logo unless you ask me to.
7. Continuing the same use if the site later includes advertising or sponsorship.

Please also tell me whether a specific plan or fee applies, the exact attribution
text you require, any geographic or user limits, and how you would like me to
handle termination (I will remove the values immediately on request).

Thank you,
[운영자 이름] — Mulmit (https://mulmit.com)
```

- **회신 후**: 승인 → 등록부 §3.x 신설, `decision_id: DS-2026-0NN`, `evidence_type:
  written_email`, `DERIBIT_ENABLED=true`(web·ingest). 거절 → `license_required` 카드 유지,
  호출 코드 비활성. 조건부(유료) → 예산(월 5만원) 대조 후 결정.

## 2. 두나무(업비트) — 시세 조회 API 공개 표시 (국문)

- **수신처**: 업비트 고객센터 1:1 문의(Open API 카테고리, https://support.upbit.com) 또는
  두나무 제휴·사업 문의 채널. 공개된 전용 이메일은 확인하지 못했다(발송 전 고객센터
  안내 확인).
- **근거 조항**: Open API 이용약관(2023-12-15) §2(정의 — 시세 조회 포함), **§5(저작권 —
  "모든 데이터 및 내용에 대한 저작권은 두나무에 있으므로 사용자는 이를 무단으로 사용하거나
  변경하여서는 안 됩니다")**, §6 ③(프로그램 유상 양도 금지). 개발자센터: 시세 API는 인증
  불필요, IP당 10회/초, Origin 헤더 요청은 10초당 1회.
- **요청 범위**: REST `/v1/ticker`(KRW-BTC·KRW-ETH·KRW-USDT 등 소수 마켓), 필요 시
  `/v1/candles/minutes`, WebSocket `ticker`. 서버에서만 호출(브라우저 직결 없음).

```text
제목: 업비트 시세 조회 API의 공개 웹사이트 표시 허용 여부 문의 (mulmit.com)

안녕하세요. 공개 시장 대시보드 Mulmit(https://mulmit.com)을 운영하는 [이름]입니다.
로그인 없이 누구나 보는 한국어·영어 사이트이며, 현재는 비상업 개인 프로젝트이지만
향후 광고나 후원이 붙을 수 있습니다. 이용자는 대부분 국내 거주자입니다.

업비트 Open API 이용약관 제5조(저작권)를 확인했고, 아래 사용이 약관상 허용되는지
서면(메일)으로 확인받고자 합니다. 주문·자산·입출금 등 인증이 필요한 API는 전혀 쓰지
않으며, 인증 없는 시세 조회 API만 해당합니다.

1. 사용 데이터: KRW-BTC, KRW-ETH, KRW-USDT 등 소수 마켓의 현재가·24시간 변동률
   (/v1/ticker, 필요 시 분봉 /v1/candles, WebSocket ticker).
2. 호출 방식: 저희 서버(AWS 서울)에서만 호출하고 15초 캐시합니다. 이용자 브라우저가
   업비트 API에 직접 연결하지 않습니다. 호출량은 IP당 허용 한도(초당 10회)보다 훨씬 적습니다.
3. 표시 방식: 사이트 화면의 카드와, 화면이 쓰는 값을 그대로 내보내는 저희 공개 JSON
   엔드포인트(/api/crypto/…, 인증 없음). 전용 다운로드·CSV 기능은 없지만, 공개 JSON이므로
   누구나 그 응답을 받아 저장할 수는 있습니다. 이것이 약관상 제3자 제공·재배포에
   해당하는지 명시적으로 확인 부탁드립니다.
4. 가공: 원화 표시가, "테더 프리미엄"(KRW-USDT ÷ 한국은행 일별 고시환율 − 1),
   "비트코인 프리미엄(USDT 기준)"(KRW-BTC ÷ KRW-USDT ÷ 해외 달러 참고가 − 1) 같은
   명확히 표기된 파생 지표. 김치프리미엄 계산에 업비트 시세가 쓰인다는 점을 화면에 밝힙니다.
5. 저장: 현재가는 15초 캐시만, 일별 종가 수준의 관측치는 내부 DB에 보관(차트용).
6. 출처 표기: 값 옆에 "시세: 업비트(두나무)" 문구와 업비트 링크를 고정 표시합니다.
   업비트 로고·상표는 사용하지 않습니다. 요구하시는 정확한 문구가 있으면 알려 주세요.
7. 광고·후원이 붙는 경우에도 같은 조건이 유지되는지, 별도 계약·수수료가 필요한지,
   종료 요청 시 처리 방법(요청 즉시 삭제 예정)을 알려 주시면 감사하겠습니다.

[이름] — Mulmit (https://mulmit.com)
```

- **회신 후**: 허용 → 등록부 신설·`UPBIT_ENABLED=true`. 불허 → 원화 표시·김프 카드 제외,
  호출 코드 비활성. **무응답** → §5 규칙.

## 3. Coinalyze — 집계 청산·OI 히스토리

- **수신처**: API 문서(https://api.coinalyze.net/v1/doc/) 하단 연락처(문서에서 확인해 기입).
- **근거**: 문서 문구 "The API is free, if you use the API/data in public places: news
  articles, blog posts, charts etc. please be kind and cite the data source, add link to
  Coinalyze website if possible." 40 call/분/키, 인트라데이 히스토리 1,500–2,000 포인트.
- **확인할 것**: 광고가 붙는 공개 웹사이트의 **자동 갱신 카드**가 "public places"에
  포함되는지, 출처 문구, 캐시·저장, 그리고 **하위 권리** — Coinalyze가 집계하는 거래소
  (Binance·Bybit·OKX 등) 데이터의 공개 재표시를 Coinalyze 측이 허용할 권한이 있는지.

```text
Subject: Using Coinalyze API data on a public dashboard (mulmit.com)

Hello,

I run Mulmit (https://mulmit.com), a public bilingual market dashboard (no login;
currently non-commercial, advertising may be added later). Your API docs say the
API is free when the data is used in public places with a citation. I'd like to
confirm that the following fits that description, or learn your conditions:

1. Showing aggregated perpetual-futures liquidation totals (last 1h / 24h, long vs
   short) and open-interest values for BTC, ETH and a few other coins, refreshed
   every 5 minutes from /liquidation-history and /open-interest(-history).
2. Relaying those values through my own server-side JSON endpoint to my frontend
   (unauthenticated, no bulk export), caching up to 5 minutes, storing daily
   aggregates privately for charts.
3. Attribution "Data: Coinalyze" with a link to https://coinalyze.net next to the
   values — please tell me the exact wording you prefer.
4. Whether the exchanges whose data you aggregate impose conditions on this kind
   of public display that I should be aware of, or whether your permission covers
   it.
5. Whether the same applies if the site carries advertising.

Thank you,
[운영자 이름] — Mulmit
```

## 4. CoinMarketCap Basic — 발송 없는 확인 체크리스트

- pricing 페이지(2026-08-21 확인): "Commercial use rights — the free Basic tier included",
  15,000 credits/월, 50 req/분.
- 운영자 액션: 계정·키 발급 → **Commercial Terms of Use 원문**에서 ① 출처 문구("Data
  provided by CoinMarketCap"+링크 형태인지) ② 캐시·저장 한도 ③ "standalone 재배포 금지"
  범위(우리 공개 JSON relay가 해당하지 않는지) ④ 1 product·이용자 수 한도 — 네 항목을
  등록부에 인용으로 기록. 불명확하면 support 티켓으로 "ad-supported public dashboard,
  global-metrics + fear-and-greed endpoints, server relay JSON"을 적어 확인.
- 사용 엔드포인트: `/v1/global-metrics/quotes/latest`(도미넌스·총시총), 보조
  `/v3/fear-and-greed/latest`. 키는 ingest 전용 환경변수, web은 게이트만.

## 5. 무응답·거절 규칙

| 공급자 | 회신 기한 | 무응답 시 | 거절 시 |
|---|---|---|---|
| Deribit | 2026-09-16 | `pending_rights` 유지(값 비공개). 약관이 개인 용도를 명시하므로 HL식 위험수용 **안 함** | `license_required`, 코드 비활성 |
| 두나무 | 2026-09-16 | 운영자 결정: ① 계속 대기 또는 ② 위험수용 — 근거(인증 없는 공개 시세 API, 명시적 공개 금지 없음, 출처표기, 서버 relay·저호출, 로고 미사용)를 `DS-` 블록에 적고 `recheck_at` 설정 | 카드 제외, 코드 비활성 |
| Coinalyze | 2026-09-16 | 문서의 공개 이용 문구를 근거로 출처표기 조건 활성화 가능(하위권리 메모 동봉) | 비활성 |

## 변경 이력

| 날짜 | 내용 |
|---|---|
| 2026-08-21 | 최초 작성 — Deribit(§4.6)·두나무(§5)·Coinalyze 문의 초안, CMC Basic 확인 체크리스트, 무응답·거절 규칙 |
