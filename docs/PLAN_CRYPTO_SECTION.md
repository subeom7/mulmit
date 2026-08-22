# 크립토 섹션 확장 계획 — 판단·데이터 조사·추천안 검증

작성일: 2026-08-21 (Asia/Seoul)
관련: `docs/ROADMAP.md` #16, `docs/DATA_SOURCE_REGISTER.md` §1–§2(원칙)·§3.1(Hyperliquid),
`docs/INQUIRY_CRYPTO_SOURCES.md`(문의 초안), `docs/PLAN_KR_SECTIONS.md`(hlkr 매핑 선례).

운영자가 제안한 크립토 섹션("BTC·ETH 실시간, 공포·탐욕, 펀딩비, 도미넌스, 가스, 청산
스트림, DVOL")과 외부에서 받은 추천안을, 이 저장소의 원칙(도달 가능 ≠ 재배포 가능,
fail-closed, 수치 발명 금지)으로 하나씩 판정한 문서다. 소스별 약관 원문과 한국망 실측을
근거로 붙였다. 법률 자문이 아니며, 외부 표시 권리는 공급자의 서면 답변과 최신 약관으로
확정한다.

## 0. 결론 먼저

1. **확장은 타당하다.** 수요(시장 재주목), 기존 인프라(Hyperliquid 레인·게이트·캔들 저장이
   이미 있음), 차별화(한국·미국 합성자산 + 크립토 교차 비교)가 맞물린다. 경쟁 레퍼런스
   hyperkr.com(한국·미국 주식·코인·HL을 한 화면, 공포·탐욕·USDT 기준가 표시)이 이미 있으므로
   "권리 깨끗한 데이터 + 교차시장"이 우리 포지션이다.
2. **"크립토는 데이터 규제가 훨씬 적다"는 전제는 반만 맞다.** 거래소 데이터에 *라이선스
   요금*은 없지만, 공개 웹 재표시를 **약관으로 명시 금지**한 거래소가 주식 쪽보다 오히려
   많다 — Binance(광고 수익 사이트의 시장데이터 이용 금지), OKX(§9.4 제3자 표시 금지),
   Coinbase(Market Data Terms 표시 금지), Deribit(개인 용도 한정·승인 필요), Bybit(상업적
   이용·재패키지 금지). 반대로 **자유로운 쪽**은 Hyperliquid(퍼미션리스, 기존 위험수용
   범위), alternative.me(출처표기 조건 상업 허용), CoinMarketCap Basic(무료·상업 허용 명시),
   퍼블릭 RPC·mempool 같은 체인 데이터다. 그리고 **한국 규제 축**(미신고 해외거래소 앱·사이트
   차단 심의 진행, 레퍼럴 = 미신고 영업 조력으로 형사처벌 가능)이 "브라우저 직결" 아키텍처를
   직접 위협한다.
3. **추천안 7항목 중 그대로 채택 가능한 것은 2개**(공포·탐욕, 펀딩비), **소스만 바꾸면 되는 것
   3개**(가격, 도미넌스, 가스), **현 형태로는 불가 2개**(Binance 청산 스트림 직결, DVOL 무승인
   직결). 상세는 §2.
4. **아키텍처**: 브라우저 직결은 Hyperliquid 웹소켓 하나로 한정하고 나머지는 서버 relay +
   짧은 캐시(기존 lane 패턴). 이유는 약관(직결도 "우리 서비스가 이용"하는 것), 한국 차단
   리스크, Upbit의 Origin 요청 제한(10초 1회), 출처·상태 메타를 응답에 동봉하는 우리 계약.
5. **Phase 1은 외부 승인 없이 바로 구현 가능**: HL 네이티브 퍼프(BTC·ETH·SOL…) 가격·24h·
   펀딩·OI·교차거래소 예상펀딩 + alternative.me 공포·탐욕 + ETH/BTC·실현변동성(HL 캔들
   자체 계산) + 교차시장 상관(HL SP500 퍼프 vs BTC). 도미넌스(CMC)·김치프리미엄(Upbit)·
   가스(RPC)·청산 집계(Coinalyze)·DVOL(Deribit)은 운영자 액션(키 발급·문의) 뒤 Phase 2.

## 1. 전제 검증 — 주식 대비 크립토 데이터 규제

| 축 | 주식(현 상태) | 크립토(조사 결과) |
|---|---|---|
| 거래소 데이터 요금 | KRX·CME·Cboe 등 재배포 계약 필수, 월 $1,000~ | 요금은 0. 그러나 약관이 상업 재표시를 직접 금지하는 곳 다수(§3) |
| 무료 공식 API | 공공기관(FSC·DART·FRED·OFR)은 출처표기로 허용 | HL(퍼미션리스), alternative.me, CMC Basic, 체인 RPC는 허용 범위 명시. CoinGecko·CoinPaprika·DefiLlama·Etherscan 무료 티어는 **비상업 한정**(광고 사이트 불가) |
| 한국 규제 | 자본시장법·KRX 약관 | 특금법: 미신고 해외거래소 **영업·조력(레퍼럴) 처벌**, 2026-01-28 구글플레이 앱 차단, 2026-06 FIU 12곳 수사의뢰, 2026-07-30 방미심위 사이트 차단 심의 방안. 가상자산이용자보호법은 정보사이트 직접 의무 없음 |
| 광고(AdSense) | 무관 | 암호화폐 정보 콘텐츠 허용. 도박성 UI·미신고 거래소 홍보성 구성은 회피 |
| 운영 리스크 | 약관 변경 | 약관 변경 + **엔드포인트 변경이 잦음**(Binance 선물 WS 2026-04-23 라우팅 전면 변경 — 추천 URL은 이미 죽은 경로였다) |

## 2. 추천안 검증표

실측은 전부 2026-08-21 21:21–21:46 KST, 서울 KT 가정망, 브라우저 직결을 흉내내려 웹소켓
핸드셰이크에 `Origin: https://mulmit.com`을 붙였다. 원문은 §8.

| # | 추천 내용 | 확인 결과 | 판정 |
|---|---|---|---|
| 1 | BTC·ETH 실시간 가격·24h·스파크라인 — Binance/HL 웹소켓 브라우저 직결, 틱 플래시 | HL `activeAssetCtx`(mark·oracle·prevDayPx·funding·OI·dayNtlVlm)와 `allMids`가 Origin 포함 직결로 정상. BTC 퍼프 카드는 **이미 라이브**(`app/market_assets.py`, publisher=hyperliquid). Binance는 약관(§3.3)상 광고 사이트 이용 금지이고 스팟 WS 직결은 되지만 쓰지 않는다. HL 오라클가는 CEX 현물 가중중앙값이라 "현물 참고가" 역할을 하되 **현물 아님 고지 유지** | ✅ **HL로 채택**(Binance 제외). 틱 플래시는 `prefers-reduced-motion` 존중 |
| 2 | 크립토 공포·탐욕(alternative.me) 반원 게이지 | 약관 원문: "Commercial use is allowed as long as the attribution is given right next to the display of the data." / "You must properly acknowledge the source of the data and prominently reference it accordingly." 일 1회 갱신(응답에 `time_until_update`). 실측 값 72(Greed), 전일 62. 구성: 변동성 25·모멘텀/거래량 25·소셜 15·설문 15·도미넌스 10·트렌드 10 | ✅ **채택**. 등록부의 "CNN F&G 복제 안 함" 결정과 충돌 없음(타사 공식 공개 API의 출처표기 재표시). `Mulmit Market Sentiment Gauge`(#103)와 **나란히** 두되 비교 불가 고지 |
| 3 | 펀딩비 핫리스트(HL/Binance), 8h·APR 환산, 롱/숏 과열 배지 | HL `predictedFundings`가 코인별 **BinPerp·HlPerp·BybitPerp 예상 펀딩과 `fundingIntervalHours`**(실측: Binance 0G=4h, HL=1h)를 준다 → Binance·Bybit API 호출 없이 교차거래소 비교 가능. "8시간 펀딩비" 표현은 틀림(HL 1h, Binance 일부 4h) → interval 동봉, APR = rate × (24/interval) × 365 | ✅ **채택(HL 단독)**. 등록부에 "예상펀딩 타 거래소 값은 HL이 2차 전달" 하위권리 메모 |
| 4 | BTC 도미넌스·ETH/BTC(CoinGecko 무료) | CoinGecko Demo는 **비상업**(pricing·support 확인), 상업은 Basic $35/월(≈예산 전액). 대안 ① CMC Basic: 무료, pricing 페이지 "Commercial use rights — the free Basic tier included", 15k credits/월·50 rpm, 키·약관 동의 필요, 출처 링크 ② alternative.me `/v2/global/`: 상업 허용·출처표기이나 **유니버스 165종**이라 실측 64.9% vs CoinPaprika 57.2% — 정의 차이가 7%p | ⚠️ **소스 교체**: 도미넌스·총시총은 CMC Basic(운영자 키 발급 후), 폴백 alternative.me(유니버스 명시). ETH/BTC는 HL 오라클 ETH÷BTC로 자체 계산(권리 無) |
| 5 | 가스 트래커(Etherscan) 헤더 알약 + "온체인 활성도" | Etherscan 무료 API: 출처표기 필수·**상업 이용은 사전 동의 필요**, 5 call/s. 퍼블릭 RPC `eth_gasPrice`로 대체 가능(실측 mainnet 0.31 gwei, Base 0.006, Arbitrum 0.02). L2 "<$0.01"은 L1 데이터 수수료 포함 추정치라 정직한 표기는 "base fee(gwei)+단순 전송 21k gas 달러 환산"까지. GNB 전역 고정은 한국·미국 페이지와 무관 → 크립토 페이지 내 스트립. "활성도"는 정의 모호 | ⚠️ **소스 교체·범위 축소**: RPC(이더 mainnet·Base·Arbitrum) + mempool.space(BTC sat/vB), 제공자 이용조건 1회 확인 후 Phase 2 |
| 6 | 실시간 청산 스트림 — `wss://fstream.binance.com/ws/!forceOrder@arr` 브라우저 직결, 0.5초 피드, 10만$ 이상 화면 번쩍 | (a) Binance ToU: 광고·레퍼럴 수익 사이트의 시장데이터 이용 금지(서면 동의 경로만). (b) **추천 URL은 죽은 경로**: Binance 선물 WS 2026-03-06 공지·2026-04-23 마감으로 `/public`·`/market`·`/private` 라우팅 전환, 실측 legacy `/ws/!forceOrder@arr` **0건/285s**(대조군 `btcusdt@aggTrade`도 0건), 새 `/market/ws/!forceOrder@arr` 58건/60s·명목 $725,813·35심볼. (c) 스트림 정의가 "심볼당 1000ms 내 최신 1건 스냅샷"이라 **전체 청산 합계가 아님** — 합계·"지난 1분 청산액" 표기는 허위. (d) 한국: 미신고 해외거래소 사이트 차단 심의 진행 → 직결이 끊기거나, 사이트가 Binance 트래픽 관문처럼 보인다. Bybit `allLiquidation`(전체 푸시 500ms, 실측 5건/170s)·OKX(49건/170s)도 약관 동일 문제 | ❌ **현 형태 불가**. 대안: Coinalyze 집계 API("free if you use the API/data in public places… please cite the data source", 40 call/분, 1분 버킷 히스토리)로 **1h/24h 청산 합계 카드**(문의 후 Phase 2). 실시간 틱 피드·번쩍임 UI는 보류 — 도파민·체류시간 프레임은 사이트 톤과도 맞지 않는다 |
| 7 | DVOL — `wss://test.deribit.com` 연결, `ticker` 채널 `BTC-DVOL` 구독, 브라우저 직결 | 기술은 쉽다: REST `public/get_volatility_index_data`(실측 BTC 1h 봉 44.56→42.84), `get_index_price?index_name=btcdvol_usdc` 42.84 / `ethdvol_usdc` 53.66, WS 채널 **`deribit_volatility_index.btc_usd`**(추천안의 채널명·테스트넷 URL은 오류). 그러나 Deribit ToS §4.6: "The use of Market Data and/or Derived Data is for personal use only. You are not allowed to aggregate, resell, publish, forward or in any other way process Market Data and/or Derived Data (except for personal use) without explicit approval from us." 연락처 info@deribit.com. 한국은 Deribit 제한국 아님 | ⚠️ **서면 승인 전 `pending_rights`**. 문의 초안 `INQUIRY_CRYPTO_SOURCES.md` §1. 승인 전에는 "권리 확인 중" 카드 |
| 8 | 교차시장: CNN F&G 1일 1회 스크래핑 vs 크립토 F&G, CBOE VIX vs DVOL | 등록부 결정 유지: CNN F&G 복제 안 함(§5.5), Cboe VIX `license_required`(§3.13). 대체 쌍은 이미 권리 깨끗한 우리 값: `Mulmit Market Sentiment Gauge`(#103) vs 크립토 F&G, `OFR FSI 변동성 범주`(#101)·HIP-3 실현변동성(#102) vs BTC 실현변동성(HL 캔들)·DVOL(승인 후) | ❌ 추천 소스 거부, ✅ 대체 쌍 채택 |
| 9 | 히어로 4단(가격·심리·펀딩·사이클) | 구성은 타당. 한국 사용자 관점에서 **김치프리미엄**이 빠진 것이 가장 큰 공백(§4.2) | ✅ 수정안 §6 |
| 10 | "규제·라이선스 0, 직결이라 서버 비용 0" | 위 (1)·(6)·(7)로 반박. 직결도 "우리 서비스가 데이터를 이용"하는 것이며 약관은 그걸 본다. 서버 relay 비용은 미미(REST 폴링, t4g.small 여유) | ⚠️ 전제 수정 |

## 3. 소스별 권리 판정 (등록부 형식 요약)

등록부 §3에 정식 섹션을 추가할 때 이 표를 옮긴다. 인용은 접근일 2026-08-21 원문이다.

| 공급자 / 내부 ID 후보 | 대상 | 상태 제안 | 근거 (원문 인용) | 실측·조건 |
|---|---|---|---|---|
| Hyperliquid 네이티브 퍼프 / `hyperliquid_native` (기존 3.1 게이트 공유) | BTC·ETH·SOL 등 mark·oracle·24h·funding·OI·`predictedFundings`·캔들 | `pending_rights` + **운영자 위험수용(2026-08-21 개정과 동일 근거)** | 등록부 §3.1: 양사 약관 재배포 금지 없음, Hyperliquid Corp. "permissionless" 회신. 추가 메모: `predictedFundings`의 BinPerp·BybitPerp 값은 HL이 산출·전달하는 2차 데이터 | REST 65ms, WS Origin 직결 정상. 기존 `HIP3_PUBLIC_DISPLAY_ENABLED` 아래에서 `publisher=hyperliquid` 구분 |
| alternative.me / `alternative_me` | Crypto Fear & Greed(`/fng/`), 보조 `/v2/global/`(유니버스 165종) | **`approved` 후보 (official_terms)** | "Commercial use is allowed as long as the attribution is given right next to the display of the data." / "You must properly acknowledge the source of the data and prominently reference it accordingly." / "You may not use our data to impersonate us or to create a service that could be confused with our offering." | 200·0.6s. 일 1회(00:00 UTC) 갱신. 출처 문구·링크를 값 **바로 옆**에 고정. 캐시 1h·stale 48h |
| CoinMarketCap Basic / `coinmarketcap` | 글로벌 메트릭(도미넌스·총시총), CMC F&G 보조 | `pending_review` → 키 발급·Commercial ToU 동의 후 `approved` | pricing: "Commercial use rights — the free Basic tier included", 15,000 credits/월, 50 req/분. 출처 문구 "Data provided by CoinMarketCap"+링크(Commercial ToU에서 정확 문구 확인). 독립 서비스로 재배포·재판매 금지 | 키 없이는 401(실측). 운영자 액션: 키 발급 + Commercial ToU 원문 확인·기록 |
| CoinGecko / `coingecko` | 대안 도미넌스 | `license_required` | Demo 플랜 비상업(pricing·support). 약관 §4.4 "Powered by CoinGecko" 표기, §4.1.6 재배포 금지, §6.1 캐시 24h 내 갱신, §6.2 저장 금지. 상업은 Basic $35/월 | 예산(월 5만원) 거의 전액 → 채택 안 함 |
| CoinPaprika / `coinpaprika` | 대안 도미넌스(57.19% 실측) | `license_required` | "You are eligible to use API for Commercial use only in Plans other than 'Free'." | 채택 안 함 |
| Upbit(두나무) 시세 API / `upbit_quotation` | KRW-BTC·ETH·USDT 현재가(김치프리미엄·원화 표시) | `pending_rights` → 문의 또는 위험수용 기록 | Open API 이용약관(2023-12-15) §2 정의에 "시세 조회" 포함, **§5 "Open API 서비스상에서 제공되는 모든 데이터 및 내용에 대한 저작권은 두나무에 있으므로 사용자는 이를 무단으로 사용하거나 변경하여서는 안 됩니다."** 공개 표시 허가·금지 조항은 없음(침묵 ≠ 허가). 개발자센터: 시세 API 인증 불필요, IP당 10회/초, **Origin 헤더 요청은 REST·WS 모두 10초당 1회** | 200·47ms. 직결 부적합(Origin 제한) → 서버 relay. 문의 초안 §2 |
| Binance / `binance` | 스팟·선물 시세, 청산, OI | **`license_required`** | Terms of Use "commercial uses of Binance data" 금지 열거: "Trading services that make use of Binance quotes…", "Data feeding or streaming services that make use of any market data of Binance", "Any other websites/apps/services that charge for or otherwise profit from (**including through advertising or referral fees**) market data obtained from Binance" — 서면 동의 없이는 불가. *원문 페이지(binance.com/en/terms)는 JS 렌더·봇 차단(curl 202/0 byte, 브라우저 본문 미로딩)이라 제3자 인용(GitHub Superalgos #1019 등)으로 확인 — 운영자 브라우저로 현행 조항 번호·문구 1회 확인해 기록* | 한국망 REST·WS 모두 도달(스팟 WS 직결 정상, 선물 legacy 경로 사망). 사용 안 함 |
| Bybit / `bybit` | 청산 `allLiquidation`, 시세 | **`license_required`** | API Terms & Conditions: "shall not commercially exploit the APIs", "shall not, under any circumstances, repackage or resell the services or any part thereof, API or Service Data"(2024-11-14 판, 페이지 last updated 2026-03-18, 본문 JS 렌더라 제3자 인용 확인) | 사용 안 함 |
| OKX / `okx` | 청산 `liquidation-orders`, 시세 | **`license_required`** | API Agreement §9.4(Last updated 2026-07-28): "The fact that Market Data is publicly accessible does not grant any right to redistribute, resell, or commercially exploit that data." / "solely for your own personal, non-commercial trading and account management purposes" / "resell, redistribute, publish, display, or otherwise make Market Data available to any third party … without OKX's prior written consent" 금지, "competing data product, market data service, financial data aggregator, price feed, or analytics platform" 금지 | 사용 안 함. 국내 구글플레이 검색·설치 차단 보도(2026) |
| Coinbase Exchange / `coinbase` | 현물 참고가 | **`license_required`** | Market Data Terms of Use: "Without prior express written consent from Coinbase, you may not redistribute, display, or disseminate the Market Data … to any third party outside of your organization" | 사용 안 함 |
| Deribit / `deribit_dvol` | BTC·ETH DVOL | `pending_rights` → 문의 | ToS §4.6 (DRB Panama Inc.): "The use of Market Data and/or Derived Data is for personal use only. You are not allowed to aggregate, resell, publish, forward or in any other way process Market Data and/or Derived Data (except for personal use) without explicit approval from us. In case you wish to make use of this Market Data and/or Derived Data for any non-personal use, please contact info@deribit.com." Derived Data 정의에 "indices" 포함 | REST·WS 정상. 문의 초안 §1. 승인 전 값 비공개 |
| Coinalyze / `coinalyze` | 거래소 집계 청산·OI·펀딩·롱숏 히스토리 | `pending_review` → 문의(공개 사이트·광고 범위 확인 + 하위권리) | API 문서: "The API is free, if you use the API/data in public places: news articles, blog posts, charts etc. please be kind and cite the data source, add link to Coinalyze website if possible." 40 call/분/키, 인트라데이 1,500–2,000 포인트 보존 | 키 발급(무료). 문의 초안 §3 |
| Etherscan / `etherscan` | 가스 오라클 | `license_required` | 무료 API: "Powered by Etherscan.io APIs" 출처표기 필수(개인 용도 제외), 상업 이용은 사전 동의 필요, 5 call/s | 키 없이 1회/5초 응답 실측. 대체: 퍼블릭 RPC |
| 퍼블릭 RPC(publicnode·Base 공식·Arbitrum 공식) / `chain_rpc` | `eth_gasPrice`·`eth_feeHistory`(이더·Base·Arb) | `pending_review` → 각 제공자 이용조건 1회 확인 | 실측 200, 0.3–0.6s. 체인 데이터 자체는 공개 원장이고 RPC 제공자 약관만 문제(fair use·무보증) | Phase 2. 자체 노드는 예산 밖 |
| mempool.space / `mempool_space` | BTC 추천 수수료(sat/vB) | `pending_review` | 공개 API, 이용조건 확인 1회 | 실측 fastest 2 sat/vB |
| DefiLlama / `defillama` | 스테이블코인 공급 | `license_required`(문의 가능) | Terms of Use: "personal, non-commercial purposes", "copy, scrape… or otherwise exploit the Content & Data for commercial purposes without prior written consent" 금지. Pro $300/월 | 대체: CMC의 USDT·USDC 시총 |
| Dunamu forex·CoinCap | 환율·시세 | `disabled` | `quotation-api-cdn.dunamu.com`·`api.coincap.io` 모두 DNS 미해결(실측) | 제외 |

## 4. 데이터 인벤토리 — 무엇을 보여줄 것인가

### 4.1 우선순위표

| 등급 | 지표 | 소스(권리) | 갱신 | 비고 |
|---|---|---|---|---|
| **Phase 1** | BTC·ETH·SOL·(HL 상위 N) USD 가격, 24h 변동, 24h 명목거래대금, 미니 스파크라인 | HL `metaAndAssetCtxs`/`activeAssetCtx`, `candleSnapshot`(기존 `hip3_history` 확장) | WS 직결 + 서버 15s | "합성 무기한선물·현물 아님" 고지 동일 |
| Phase 1 | 펀딩비(1h, APR 환산)·예상펀딩 3거래소(Bin/Bybit/HL, interval 동봉)·OI(USD) | HL `predictedFundings`·`metaAndAssetCtxs` | 60s | 양수=롱 과열/음수=숏 과열 배지 |
| Phase 1 | 크립토 공포·탐욕(값·분류·전일·7일·다음 갱신까지) | alternative.me | 1h 폴링(일 1회 갱신) | 출처 문구 값 옆 고정 |
| Phase 1 | ETH/BTC 비율·7d 변화 | HL 오라클 계산 | 15s | 권리 無 |
| Phase 1 | BTC·ETH 실현변동성 7d/30d(연율) | HL 1d 캔들 자체 계산(#102 방식 재사용) | 6h | DVOL 대체 참고값, 내재변동성 아님 고지 |
| Phase 1 | 교차시장: HL SP500·XYZ100·GOLD 퍼프 vs BTC 30d 롤링 상관 | 전부 HL 캔들 | 6h | 권리 無. "합성 퍼프 기준" 고지 |
| Phase 1 | `Mulmit Market Sentiment Gauge` vs 크립토 F&G 병치 | 기존 #103 + alternative.me | — | "정의 다름·비교 불가" 고지 |
| Phase 2 | BTC 도미넌스·총시총·24h 변화 | CMC Basic(키) / 폴백 alternative.me global(유니버스 명시) | 10분 | 출처·유니버스 동봉 |
| Phase 2 | **김치프리미엄**(한국 특화): ① 테더 프리미엄 = Upbit KRW-USDT ÷ ECOS 일별 고시 − 1(환율 날짜 명시) ② BTC 김프(USDT 기준) = (KRW-BTC ÷ KRW-USDT) ÷ HL BTC 오라클 − 1(환율 불필요·실시간) | Upbit(문의/위험수용) + 기존 ECOS lane + HL | 15s | hlkr 계획 §1.2 "무허가 실시간 환율 안 씀" 원칙과 정합 — USDT 분모로 환율을 소거 |
| Phase 2 | 원화 표시(BTC·ETH KRW 현재가) | Upbit | 15s | 같은 lane |
| Phase 2 | 가스 스트립: 이더 base fee·Base·Arbitrum(gwei, 21k 전송 $ 환산), BTC 멤풀 sat/vB | 퍼블릭 RPC·mempool.space(이용조건 확인) | 30s | 크립토 페이지 내부 스트립 |
| Phase 2 | 청산 집계 1h/24h(롱·숏 분리, 거래소 집계) | Coinalyze(문의 회신 후) | 5분 | 틱 피드 아님·집계 지연 고지 |
| Phase 2 | DVOL BTC·ETH + 30일 히스토리 | Deribit(서면 승인 후) | 60s | 승인 전 "권리 확인 중" 카드 |
| Phase 3 | 스테이블코인 공급(USDT·USDC) | CMC 시총 대체 또는 DefiLlama 문의 | 1h | 유동성 게이지 |
| 보류 | 실시간 청산 틱 스트림, 롱/숏 계정 비율, Binance OI | 거래소 약관 | — | 약관·정합성 모두 미충족 |
| 보류 | 현물 ETF 일별 순유입, 거래소 순유입·활성주소 등 온체인 심화 | 무료 라이선스 소스 없음 / Glassnode·CryptoQuant 유료 | — | 예산 재검토 조건부 |

### 4.2 왜 김치프리미엄인가

한국 사용자가 크립토 대시보드에서 가장 먼저 찾는 수치이고 hlkr·HyperKR 모두 "USDT 기준
가격"을 둔다. 우리 원칙상 문제는 실시간 USD/KRW 환율의 권리였는데(`PLAN_KR_SECTIONS.md`
§1.2), **USDT를 분모로 두면 환율이 소거된다** — BTC 김프(USDT 기준)는 Upbit 두 시세와 HL
오라클만으로 성립한다. 공식 환율은 "테더 프리미엄" 한 칸에만, 고시 날짜와 함께 쓴다.

## 5. 한국 규제·운영 경계 (법률 자문 아님)

- **레퍼럴·가입 유도 0**: FIU(2026-06)·BKL 해설 모두 "해외 거래소로부터 레퍼럴 수익을 대가로
  홍보·알선하는 행위는 미신고 영업 조력으로 형사처벌 가능". 거래소 링크는 **데이터 출처
  페이지(문서·API)**만, 거래소 가입·이용 권유 문구 금지, 제휴 코드 금지. 거래소명
  (HL `predictedFundings`의 BinPerp·BybitPerp 등)은 **보조 행의 데이터 라벨로만** 노출하고
  헤드라인·카드 제목에 올리지 않으며 로고는 쓰지 않는다.
- **차단 동향 대비**: 2026-01-28 구글플레이 미신고 거래소 앱 차단 → 2026-06-25 FIU 12곳
  수사의뢰(업비트 고지 목록 40곳엔 Binance·Bybit·OKX·Deribit·Hyperliquid 없음) → 2026-07-30
  방미심위 "피해 확인 사이트 우선 차단 심의" 방안(Binance는 FIU가 제외, 위원회는 이견).
  사용자 브라우저가 해외 거래소 도메인에 직접 붙는 구조는 어느 날 끊길 수 있고, 우리
  사이트가 관문처럼 보일 수 있다 → **직결은 HL만, 나머지는 AWS 서울 서버 relay**.
- **면책·고지**: 모든 크립토 카드에 "정보 제공 목적·투자 권유 아님·합성/참고값" 배지(기존
  HIP-3 문구 재사용), 거래소 로고 미사용(텍스트 출처), 출처 문구는 공급자 요구 그대로.
- **개인정보**: HL 직결은 사용자 IP가 HL 노드에 노출 → `/privacy`에 "브라우저가
  api.hyperliquid.xyz에 직접 연결" 1줄 추가(Phase 1).
- **AdSense**: 정보 콘텐츠 범위. 청산 피드의 "번쩍임·도파민" 프레임은 채택하지 않는다
  (Polymarket 판정 #15의 감수성 유지).

## 6. 화면 설계 (제안)

새 페이지 `/crypto`(`kr.html` 패턴, `window.MULMIT_PAGE="crypto"`, 헤더 탭 추가, 랜딩 미니 카드).

- **히어로 4단**: ① BTC·ETH (USD=HL 오라클·KRW=Upbit[P2]·24h·스파크라인) ② 심리 —
  크립토 F&G 게이지 + Mulmit Sentiment Gauge 소형 ③ 파생 과열 — 펀딩 APR·OI·예상펀딩
  3거래소 ④ 시장 구조 — 도미넌스[P2]·ETH/BTC·김프[P2].
- **본문**: HL 상위 코인 표(가격·24h·펀딩·OI·거래대금) → 펀딩 히트맵 → 변동성(실현 7d/30d,
  DVOL 자리 `권리 확인 중`) → 온체인 스트립[P2] → 청산 집계[P2] → 교차시장(합성자산 vs BTC
  상관, 크립토 F&G vs Mulmit 게이지).
- **고지 스트립**: 현물 아님 · 합성 무기한선물 · 출처/시각 · 투자 권유 아님.
- 모션: 가격 틱 플래시만, `prefers-reduced-motion`이면 끔. 탭 비활성 시 구독 해제.

## 7. 아키텍처·구현 항목

- **게이트(모두 web·ingest 양쪽, 기본 false)**: `CRYPTO_SECTION_ENABLED`(페이지·라우트 노출),
  `ALTERNATIVE_ME_ENABLED`, `CMC_ENABLED`+`CMC_API_KEY`, `UPBIT_ENABLED`, `CHAIN_RPC_ENABLED`,
  `COINALYZE_ENABLED`+`COINALYZE_API_KEY`, `DERIBIT_ENABLED`. HL 부분은 기존
  `HIP3_PUBLIC_DISPLAY_ENABLED`(+`HIP3_HISTORY_ENABLED`)를 그대로 쓴다. `app/data_rights.py`
  lane 등록·`lane_report` 노출·등록부 승인 블록을 **같은 PR**에 넣는다.
- **엔드포인트**: `/api/crypto/overview`(HL 코인 컨텍스트·예상펀딩·ETH/BTC, 15s),
  `/api/crypto/sentiment`(F&G, 1h 캐시), `/api/crypto/volatility`(실현변동성·상관, 6h 블롭),
  `/api/crypto/dominance`[P2], `/api/crypto/kimchi`[P2], `/api/crypto/gas`[P2],
  `/api/crypto/liquidations`[P2], `/api/crypto/dvol`[P2]. 응답에 `rights.status`·`provider`·
  `publisher`·`source.url`·`attribution`·`fetched_at`·`observation_at` 동봉(등록부 §9).
- **수집**: 공급자 호출은 `app/ingest.py` `refresh_*`(report blob)에서만, 요청 경로는 저장값만
  읽는다(HL 15s 스냅샷은 기존 `market_assets` 캐시 패턴). Binance·Bybit·OKX·Coinbase·
  Etherscan 호출 코드는 **두지 않는다**(비활성 공급자 네트워크 호출 0 원칙).
- **프론트**: HL WS `allMids`(+선택 `activeAssetCtx`) 직결은 가격·24h 숫자 갱신에만, 구조·
  권리·출처는 서버 응답을 신뢰. 서버값이 `pending_rights`/`disabled`면 WS도 붙지 않는다.
- **테스트**: APR 환산(interval 1/4/8h), 김프 분해식, F&G 파싱·stale, 도미넌스 유니버스
  표기, 게이트 503 계약, 비활성 lane 네트워크 0회, 실현변동성·상관(기존 테스트 재사용).
- **비용**: REST 폴링 수십 req/분 수준, t4g.small 영향 미미. WS relay 없음.

### 7.1 Phase 1 구현 메모 (2026-08-21)

- 구현 범위: `/crypto` 페이지(`crypto.html`, `MULMIT_PAGE="crypto"`, 전 페이지 헤더 탭·랜딩 존 카드),
  `/api/crypto/overview`(HL 네이티브 퍼프 10종: BTC·ETH·SOL·XRP·BNB·DOGE·HYPE·SUI·LINK·AVAX —
  가격·24h·펀딩 APR·OI·거래대금·`predictedFundings` 3거래소·ETH/BTC), `/api/crypto/sentiment`
  (alternative.me, ingest blob relay, 1d/7d/30d 변화·90일 차트·구성 가중치·값 옆 출처),
  `/api/crypto/volatility`(BTC·ETH·SOL 실현 변동성 7/30일 √365, BTC 대 SP500·XYZ100·GOLD·KR200
  퍼프 30/90일 상관 — HIP-3 이력 blob만 사용).
- 계획과 다른 점: 브라우저 HL 웹소켓 직결은 **Phase 1에서 쓰지 않는다** — kr-overnight와 같은
  5초 서버 폴링(서버 TTL 15초)으로 충분하고, 개인정보처리방침 변경이 필요 없다. 직결은 필요성이
  확인되면 후속.
- 게이트: `CRYPTO_SECTION_ENABLED`(페이지·API 노출), `ALTERNATIVE_ME_ENABLED`(F&G lane) — 둘 다
  기본 false, compose `&app-env`에 web·ingest 공통. HL 부분은 기존 `HIP3_PUBLIC_DISPLAY_ENABLED`,
  이력은 `HIP3_HISTORY_ENABLED`(섹션이 켜지면 BTC·ETH·SOL 일봉 추가 저장).
- 펀딩 "과열" 배지 기준(편집 기준, 응답 `basis`에 명시): |APR| ≥ 15% 높음, ≥ 30% 과열.
- 등록부: §3.1 단락·§3.18(`DS-2026-010`)·§4.1 문의 3행. 운영자 액션은 §9 그대로.

### 7.2 Phase 2 구현 메모 (2026-08-21)

- **도미넌스·시장 구조** — `/api/crypto/structure`, `app/crypto_structure.py` + `app/providers/coinmarketcap.py`.
  CoinMarketCap `/v1/global-metrics/quotes/latest`를 ingest가 15분 주기로 blob 저장(월 ≈ 2,900크레딧),
  web은 blob만. 게이트 `CMC_ENABLED`(web·ingest) + `CMC_API_KEY`(ingest 전용). 출처 문구
  `CMC_ATTRIBUTION_TEXT`(기본 "Data provided by CoinMarketCap")를 값 바로 아래 링크로 고정. 등록부 §3.20.
  **운영자 액션**: CMC 계정·Basic 키 발급 → Commercial Terms 원문 확인(출처 문구·한도) → .env에
  `CMC_ENABLED=true`(web·ingest), `CMC_API_KEY=…`(ingest) → 등록부 DS 블록 기록.
- **김치프리미엄·원화 시세** — `/api/crypto/kimchi`, `app/crypto_kimchi.py` + `app/providers/upbit.py`.
  업비트 KRW-BTC·ETH·SOL·XRP·DOGE·USDT 서버 relay(15초 캐시), 테더 프리미엄(ECOS 일별 고시 대비,
  날짜 표시), 코인 프리미엄 USDT 기준(환율 소거)·공식환율 기준, HL 오라클 참고가. 게이트 `UPBIT_ENABLED`
  기본 OFF — `pending_rights`(등록부 §3.19): 두나무 문의 발송 후 회신 또는 운영자 위험수용 블록 기록 뒤 켠다.
- **가스·온체인 수수료 스트립 — 보류**(등록부 §3.21): 퍼블릭 RPC(publicnode ToS 배포 제한, Base/Arbitrum
  "프로덕션 부적합" 명시)·Etherscan(상업 동의)·mempool.space(상업 유료) 모두 깨끗하지 않음. 재개 조건은
  운영자의 키 발급형 RPC(Alchemy/Infura 무료 티어) 가입.
- **청산 집계(Coinalyze)·DVOL(Deribit)** — 코드 없음, 문의 회신 대기(§9).
- 프런트: `/crypto`에 김치프리미엄(참고가 바로 아래)·도미넌스(공포·탐욕 아래) 섹션 추가, 게이트 닫힘 =
  섹션 숨김, 5초 폴링에 김치 합류.

### 7.3 Phase 2b 메모 (2026-08-21)

- **가스·전송 수수료 스트립** — `/api/crypto/gas`(`app/crypto_gas.py`, `providers/evm_rpc.py`). 퍼블릭 RPC 대신
  운영자 RPC 계정 URL(`CHAIN_RPC_*_URL`, web 전용, 키 비노출)을 쓰는 주입형 lane. 게이트 `CHAIN_GAS_ENABLED`.
  **운영자 액션**: Alchemy(권장, 무료 티어) 가입 → 앱 생성(Ethereum·Base·Arbitrum) → HTTPS URL 3개를 서버 .env에
  (`CHAIN_GAS_ENABLED=true`, `CHAIN_RPC_PROVIDER_NAME=Alchemy`) → compose up web.
- **문의**: Deribit(info@deribit.com)·Coinalyze(contact@coinalyze.net) 초안을 운영자 Gmail 임시보관함에 생성 —
  발송은 운영자. 두나무는 지원센터 1:1 문의(INQUIRY §2 본문).
- **업비트 김치프리미엄 개방 판단**: 회신 가능성 낮음(고객센터 보일러플레이트 예상) → 문의는 기록용으로 발송하되
  HL 선례(DS-2026-001 개정: 명시 거절만 OFF)대로 운영자 위험수용으로 개방 가능. 결정 시 등록부 §3.19 YAML 확정.
- UI: `cryptoUsd` compact에 T(조) 단위 추가(총시총 "$2.59T").

### 7.4 Phase 3a — HL 전체 시장 보드 (2026-08-22)

- `/api/crypto/board`(`app/crypto_board.py`): 코인 카드와 같은 `metaAndAssetCtxs` 스냅샷(추가 호출 없음)을 정렬·합계 —
  24h 급등·급락 TOP 8, OI·거래대금 상위 TOP 8, 펀딩 APR 최고·최저 TOP 8, 전체 상장 퍼프 수·OI 합계·24h 거래대금 합계.
  급등·급락·펀딩 극단값은 24h 거래대금 $1M 이상 시장만(응답 `filters`에 명시), 상위 표는 전체. 같은 HIP-3 게이트·고지.
  새 권리 없음(등록부 변경 없음). `/crypto`에 "HL 전체 시장 보드" 섹션(파생 표 아래), 30초 폴링.

### 7.5 Phase 3b — 스테이블코인 공급·유동성 (2026-08-22)

- 같은 CoinMarketCap 키로 `GET /v2/cryptocurrency/quotes/latest?id=825,3408&convert=USD`(USDT·USDC, 1크레딧/회, 심볼 대신 id —
  티커는 중복 가능)를 `CMC_STABLECOIN_MAX_AGE`(기본 3600초) 주기로 ingest가 저장(블롭 `crypto_stablecoins_v1`, 월 ≈ 720크레딧 추가).
  실측(서버 ingest 컨테이너, 2026-08-22 11:2x KST): `data`는 id 키 객체, USDT 유통 183.23B·시총 $183.24B·도미넌스 6.93%, USDC 73.62B·
  2.78%, `credit_count` 1.
- `/api/crypto/structure`에 `stablecoins` 블록: 집계(CMC 스테이블코인 시총, **비중 = 스테이블 시총 ÷ 총시총(산술)**, 24h 변화, 24h
  거래대금), 코인별(유통 공급·시총·가격·페그 편차 bp·스테이블 내 비중), **7d·30d 공급 변화는 Mulmit 자체 일별 누적**(블롭 안 `history`,
  UTC 하루 1점, 같은 날은 최신값으로 교체, 최대 400점; 누적 전에는 `collecting` + 시작일 표시 — 과거치 발명 없음). 스테이블 블롭이
  없어도 도미넌스는 그대로 서빙하고 `stablecoins.status=collecting`.
- UI: 구조 섹션 안 "스테이블코인 공급 · 유동성" 카드(USDT·USDC 유통 공급 + 7d/페그, 스테이블 비중 + 24h, 스테이블 24h 거래대금)와
  누적 시작일 각주. 출처 문구는 같은 섹션 푸터(값 바로 아래). 새 권리 없음 — 같은 키·같은 Commercial Terms·같은 1-product 표시
  (등록부 §3.20 사용 범위만 갱신).
- 한계: ingest가 48시간 이상 멈추면 `purge_reports`가 블롭(히스토리 포함)을 지워 누적이 다시 시작된다 — 시작일이 그대로 드러난다.
- **실측 함정(2026-08-22, 정정 PR)**: CMC 글로벌 메트릭의 `stablecoin_24h_percentage_change`(및 defi·derivatives 동명 필드)는 **24h
  거래대금 변화**다 — 라이브 +22.56%가 스테이블 시총 $282B 옆에 붙어 있었고 총 거래대금 변화(+23.48%)와 같은 급(시총이 하루 22%
  움직일 수 없음). Phase 2부터 "스테이블코인 시총 +x% · 24h"로 붙이던 라벨을 떼고 `volume_24h.stablecoin_change_percent`·
  `stablecoins.aggregate.volume_24h_change_percent`로 옮겼다. CMC는 스테이블 시총의 24h 변화를 주지 않는다 → 자체 누적(7d/30d)이 그 자리.

### 7.6 Phase 4a — 코인 상세 페이지·캔들 차트 (2026-08-22)

- 문제: 대시보드의 코인 카드를 눌러도 아무 일도 일어나지 않았다(카드가 `<article>`). **`/crypto/{symbol}`** 상세 페이지를 신설하고 카드·보드 심볼을
  링크로 바꿨다.
- **차트 소스 판단 — TradingView 위젯을 쓰지 않는다**: 등록부 §3.2에 TradingView 공식 위젯이 `provider_widget`으로 이미 승인돼 있어 *권리상으로는* 붙일 수
  있다. 그러나 ① 위젯이 그리는 값은 Binance·Coinbase 등 **다른 거래소의 현물**이라 페이지 전체가 "Hyperliquid 무기한선물 참고가"라고 말하는 것과 표시
  거래소가 어긋난다(§3.2 금지: "TradingView 데이터처럼 보이는 자체 API" 반대 방향의 혼동), ② iframe이 사용자 IP·페이지 URL을 제3자에 넘긴다(개인정보
  §4에 이미 고지된 사항이지만 코인 페이지마다 반복된다), ③ 무게(수백 KB)와 테마 불일치. **결론: 같은 HL `candleSnapshot`을 서버가 릴레이하고 페이지가
  자체 SVG로 그린다.** 드로잉 툴·지표가 필요하면 §3.2 경로로 나중에 "TradingView로 보기" 토글을 얹을 수 있다(새 권리 없음).
- `GET /api/crypto/coin/{symbol}?interval=15m|1h|4h|1d&candles=true|false`(`app/crypto_coin.py`): 시장 컨텍스트는 **카드와 같은 `_coin_card` 빌더**를 재사용해
  대시보드와 상세 페이지의 숫자가 어긋나지 않게 했고, 캔들은 `candleSnapshot` 한 창(15m 2일·1h 14일·4h 60일·1d 365일)을 요청 경로 캐시(30~300초)로 돌린다.
  `candles=false`는 15초 폴링용 경량 응답(캔들 생략, 상단 지표만 갱신).
- 페이지는 `/stock/{symbol}`과 같은 **서버 렌더 메타** 방식(크롤러용 제목·설명·canonical)이며, 상장돼 있지 않은 심볼은 404(거래소 미응답 시에는 큐레이션
  10종만 렌더). 차트는 캔들·거래량·십자선·툴팁을 자체 SVG로 그리고, 인터벌 선택은 `localStorage`에 남는다.
- 표시 경계: 상단 고지 배지(현물 아님·무기한선물·USD 기준·투자 권유 아님)와 방법론·면책을 응답에서 그대로 받아 쓴다. 새 권리 없음 — 같은 HIP-3 게이트
  (`DS-2026-001`)와 같은 `metaAndAssetCtxs`·`candleSnapshot`.

## 8. 실측 로그 (2026-08-21, 서울 KT 가정망)

REST(curl, `Mozilla/5.0 mulmit-probe`):

| 엔드포인트 | 결과 |
|---|---|
| HL `info` predictedFundings / allMids | 200, 0.06s — `[["0G",[["BinPerp",{"fundingRate":"0.00005","fundingIntervalHours":4}],["HlPerp",{…,"fundingIntervalHours":1}],["BybitPerp",…]]]…` |
| Binance spot 24hr BTCUSDT / fapi premiumIndex / openInterest | 200 (lastPrice 76,846, +6.95%; lastFundingRate 0.0001; OI 107,907 BTC) — 권리상 미사용 |
| Bybit linear ticker / OKX swap ticker / Coinbase / Kraken | 200 — 권리상 미사용 |
| Deribit `get_volatility_index_data` BTC 1h / `get_index_price` btcdvol_usdc·ethdvol_usdc | 200 — 44.56→42.84 / 42.84 / 53.66 |
| alternative.me `/fng/?limit=2` / `/v2/global/` | 200 — 72 Greed(전일 62), `time_until_update` 41,925s / 도미넌스 64.9%(165종) |
| CoinGecko `/global`(키 없음) / CoinPaprika `/global` | 200 / 200(도미넌스 57.19%) |
| Upbit `/v1/ticker` KRW-BTC,ETH,USDT / Bithumb | 200, 0.05s — KRW-BTC 105,551,000(+4.93%) |
| DefiLlama stablecoins / mempool.space fees | 200(USDT 183.1B) / 200(fastest 2 sat/vB) |
| 퍼블릭 RPC `eth_gasPrice` 이더·Base·Arbitrum | 0.31 / 0.006 / 0.02 gwei |
| Etherscan gasoracle(키 없음) | 200, "Missing/Invalid API Key, rate limit of 1/5sec applied" |
| CMC `/v3/fear-and-greed/*`(키 없음) | 401 |
| Dunamu forex / CoinCap | DNS 미해결 |

WebSocket(python websockets, `origin=https://mulmit.com`):

| 연결 | 결과 |
|---|---|
| HL `allMids` / `activeAssetCtx` BTC | 정상 — BTC funding 0.0000125, OI 33,325, oraclePx 76,757.2, markPx 76,799.0, prevDayPx 71,819.0, dayNtlVlm $7.49B |
| Upbit `ticker` KRW-BTC·ETH·USDT | 정상 21건/6s (Origin 요청 제한은 구독 요청 수 기준) |
| Deribit `deribit_volatility_index.btc_usd`·`eth_usd` | 정상 24건/12s |
| Binance spot `btcusdt@miniTicker` | 정상 |
| Binance futures **legacy** `/ws/!forceOrder@arr`, `/stream?streams=`, `/ws`+SUBSCRIBE, `btcusdt@forceOrder`, 대조군 `btcusdt@aggTrade` | **전부 0건**(25s+170s+90s) — 2026-04-23 라우팅 전환 이후 사망 |
| Binance futures **new** `/market/ws/!forceOrder@arr` | 58건/60s, 명목 $725,813, 35심볼(BTCUSDT 16) |
| Binance `dstream.binance.com/ws/!forceOrder@arr` | 44건/90s(UM+CM 병합, `st`=1) |
| Bybit `allLiquidation.{BTC,ETH,SOL,XRP,DOGE}USDT` | 5건/170s, $1,431 |
| OKX `liquidation-orders` SWAP | 49건/170s |

## 9. 운영자 액션과 열린 질문

1. CoinMarketCap 계정·Basic 키 발급, Commercial Terms of Use 원문에서 출처 문구·캐시·재배포
   조항 확인 후 등록부에 `DS-` 블록 기록.
2. `INQUIRY_CRYPTO_SOURCES.md`의 Deribit(§1)·두나무(§2)·Coinalyze(§3) 문의 발송. Upbit은
   회신 없을 때 HL과 같은 "명시 금지 없음 + 공개 시세 API + 출처표기" 근거로 위험수용할지
   결정(등록부 방식대로 `recheck_at` 기록).
3. Binance·Bybit 약관 원문을 운영자 브라우저에서 1회 열어 현행 조항 번호·문구를 등록부에
   남긴다(자동 수집 실패 기록 있음). 결론(사용 안 함)은 바뀌지 않는다.
4. 퍼블릭 RPC·mempool.space 이용조건 확인(가스 스트립 전제).
5. 페이지 이름·헤더 탭 순서(`홈·한국·미국·크립토·종목 분석`), 랜딩 미니 카드 포함 여부.
6. 재검토일: 한국 차단 심의 진행 상황 **2026-09-30**, Deribit·두나무 회신 **2026-09-16**(HIP-3
   재검토일과 맞춤).

## 변경 이력

| 날짜 | 내용 |
|---|---|
| 2026-08-22 | Phase 4a(§7.6) — 코인 상세 페이지 `/crypto/{symbol}`·캔들 API(`/api/crypto/coin`), 카드·보드 링크 연결. TradingView 위젯 대신 HL 캔들 자체 렌더 판단 기록 |
| 2026-08-22 | 정정 — CMC `stablecoin_24h_percentage_change`는 거래대금 변화(실측 +22.6% vs 시총 $282B): 시총 카드의 24h 라벨 제거, 거래대금 카드로 이동(§7.5) |
| 2026-08-22 | Phase 3b(§7.5) — 스테이블코인 공급·유동성(CMC quotes/latest USDT·USDC, 같은 키, 자체 일별 누적 7d/30d), 등록부 §3.20 사용 범위 갱신 |
| 2026-08-22 | Phase 3a(§7.4) — HL 전체 시장 보드(급등·급락·OI·거래대금·펀딩 극단값·합계), 새 권리 없음 |
| 2026-08-21 | Phase 2b(§7.3) — 가스 스트립 lane(운영자 RPC 계정 주입형), T 단위 포맷, Deribit·Coinalyze 문의 초안 생성 |
| 2026-08-21 | Phase 2 구현(§7.2) — 도미넌스(CMC, 키 대기)·김치프리미엄(업비트, pending_rights) 레인 + 가스 스트립 보류 판정 |
| 2026-08-21 | Phase 1 구현(§7.1) — `/crypto`·`/api/crypto/{overview,sentiment,volatility}`, 게이트 2종, 등록부 §3.18 |
| 2026-08-21 | 최초 작성 — 추천안 10항목 검증, 소스 17종 약관·한국망 실측, 인벤토리·Phase·아키텍처 확정. Binance 선물 WS legacy 경로 사망·새 `/market` 경로 실측, Deribit §4.6·OKX §9.4·Coinbase·Bybit 금지 조항 확인, CoinGecko/CoinPaprika/DefiLlama/Etherscan 무료 티어 비상업 확인, alternative.me·CMC Basic 상업 허용 확인 |
