# HIP-3 / Hyperliquid 공개 표시 권리 문의 초안

작성일: 2026-08-17  
관련 결정: `docs/DATA_SOURCE_REGISTER.md`의 `DS-2026-001`  
상태: **발송 전.** 저장소 소유자가 발송하고, 회신을 받으면 등록부에 기록한다.

## 보내기 전에 확인할 것

**수신처가 둘이다.** 지금까지 등록부는 trade.xyz만 다뤘지만, 자산 카드에는 두 상장
주체의 상품이 섞여 있다.

| 상품 | 상장 주체 | 예시 |
|---|---|---|
| `xyz:` 접두사 | trade.xyz가 HIP-3로 배포 | `xyz:SP500`, `xyz:KR200`, `xyz:SMSN` |
| 접두사 없음 | Hyperliquid 자체 DEX | `BTC` |

두 곳 모두 `api.hyperliquid.xyz/info`로 서빙되지만 계약 상대는 다르다. 아래 본문을
**양쪽에 각각** 보내고, 회신을 별도 `decision_id`로 기록한다.

연락 경로 후보:

- trade.xyz — <https://docs.trade.xyz/>의 지원 채널, <https://trade.xyz/terms>에 적힌 연락처
- Hyperliquid — <https://hyperliquid.gitbook.io/hyperliquid-docs/>의 지원 채널

## 회신 전까지의 현재 상태

`HIP3_PUBLIC_DISPLAY_ENABLED=true`가 서버 `.env`에 들어 있다. 이는 승인이 아니라
**기록된 운영자 위험 수용**이며, `DS-2026-001`의 `recheck_at`은 **2026-09-16**이다.
그때까지 회신이 없으면 배포 값을 `false`로 되돌리는 것이 등록부에 적힌 방침이다.

---

## 본문 (영문)

```text
Subject: Public display and derived-data permission for Mulmit (mulmit.com)

Hello,

I operate Mulmit (https://mulmit.com), a publicly accessible bilingual market
dashboard. It is a non-commercial personal project today, with no accounts, no
paid tier and no advertising, though advertising or sponsorship may be added
later.

Mulmit currently displays reference values from perpetual contracts read
through the public Hyperliquid info endpoint. I would like written
confirmation of whether your terms permit each of the following. I have listed
them separately because I do not want to assume that permission for one
implies permission for another.

1. DISPLAY
   Showing mark price, oracle price, funding rate, open interest and 24-hour
   notional volume to unauthenticated visitors of a public website.

2. SERVER RELAY
   Relaying those selected fields through my own server-side JSON API to my
   frontend. The endpoints are open without authentication, so any visitor can
   read the same JSON directly. I am not describing a private internal API.

3. SHORT-TERM CACHING
   Caching responses for 30 seconds and serving the last known value for up to
   5 minutes when your API is unreachable.

4. HISTORICAL STORAGE
   Storing historical candles (candleSnapshot) in a private database in order
   to draw price charts on the cards. Mulmit does not do this today precisely
   because I have not confirmed whether it is permitted.

5. DERIVED VALUES
   Computing and displaying period changes, session-referenced changes, and
   clearly labelled composite indicators built from several of your contracts.

6. ATTRIBUTION
   The exact wording and placement you require, and whether a logo or link is
   mandatory.

7. COMMERCIAL STATUS
   Whether any of the above changes if the site later carries advertising or
   sponsorship.

8. UNDERLYING DATA
   Whether separate permission is required from the exchanges, index providers
   or data vendors behind the referenced instruments — in particular for the
   Korean equity and index products.

Two further questions about how I describe your data, since I would rather be
accurate than flattering:

9. Mulmit labels these values as synthetic perpetual references and states
   explicitly that they are not spot prices, official index closes, or
   forecasts of the next session's open. Is that characterisation acceptable
   to you, and is there wording you would prefer?

10. When a contract is delisted, your API continues to return a frozen mark
    with zero open interest and zero volume. Mulmit treats those as
    unavailable rather than displaying them. Is that the behaviour you would
    expect from a downstream display?

If any of this requires a licence or agreement rather than a permission, I
would appreciate the applicable terms, fees, geographic or user limits, and
termination requirements. If the answer to any item is no, I will disable that
specific use rather than continue it.

Thank you for your time.
```

## 한국어 참고본

발송은 영문으로 하되, 내용 확인용 요약이다.

1. **표시** — 로그인 없는 공개 웹사이트에 mark/oracle/funding/미결제약정/24시간 거래대금 표시
2. **서버 중계** — 자체 JSON API로 전달. 인증이 없어 누구나 같은 JSON을 직접 받을 수 있다는 사실을 숨기지 않음
3. **단기 캐시** — 30초 캐시, 장애 시 5분까지 마지막 값
4. **히스토리 저장** — 차트용 캔들을 사설 DB에 저장. **지금은 허가 여부가 확인되지 않아 하지 않고 있음**
5. **파생값** — 기간 변화율, 세션 기준 변화, 명시적으로 라벨링한 합성 지표
6. **출처 표기** — 정확한 문구·위치, 로고·링크 필수 여부
7. **상업 범위** — 광고·후원 도입 시 조건 변화
8. **기초 데이터** — 거래소·지수 제공자의 별도 허가 필요 여부 (특히 한국 주식·지수)
9. **표현 검증** — "합성 무기한선물 참고값이며 현물·공식 지수 종가·월요일 예측이 아님"이라는 현재 표현이 적절한지
10. **상장폐지 처리** — 얼어붙은 mark를 표시하지 않고 미연결로 두는 현재 동작이 적절한지

9·10번은 허가를 구하는 질문이 아니라 **표현이 정확한지 확인하는** 질문이다. 이쪽이
틀리면 허가를 받아도 잘못 표시하게 된다.

## 회신 후 할 일

1. 등록부에 `decision_id`를 새로 추가한다. trade.xyz와 Hyperliquid를 각각 기록한다.
2. 항목별로 `approved_scope`를 채운다. 부분 허가면 허가된 항목만 켠다.
3. 4번(히스토리 저장)이 허가되면 자산 카드 차트 작업을 시작한다. 이때 기간 선택지를
   실제 커버리지에 맞춰야 한다 — 현재 HIP-3 상품은 상장 5~8개월이라 1Y·2Y·3Y·5Y를
   제시하면 없는 데이터를 약속하는 셈이다.
4. 거부되거나 무응답이면 `HIP3_PUBLIC_DISPLAY_ENABLED=false`로 되돌리고, 자산 카드와
   Weekend Pulse는 `pending_rights` 상태로 전환된다. 코드는 이미 그렇게 동작한다.
