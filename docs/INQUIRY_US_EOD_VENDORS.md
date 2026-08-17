# 미국 EOD 재배포 라이선스 견적 문의 초안 (Tiingo · EODHD)

작성일: 2026-08-18
관련 항목: `docs/DATA_SOURCE_REGISTER.md` §6 조사표, [[kr-us-data-parity]] 원칙의 미국 쪽 날개
상태: **발송 전.** 견적 요청이지 구매가 아니다 — 등록부 원칙상 서면 확인·예산 판단 전에는 결제하지 않는다.

## 배경

미국 종목별 가격 분석(낙폭·MDD·변동성)을 되살리려면 "공개 웹 재표시"가 서면으로
허용된 미국 EOD 소스가 필요하다. 2026-08-18 조사 결과 자가결제 티어로 이를
허용하는 벤더는 없었고, 전부 문의형이다. 자세가 가장 열린 곳부터 견적을 받는다.

| 우선순위 | 수신처 | 근거 |
|---|---|---|
| 1 | Tiingo — `sales@tiingo.com` | 재배포 라이선스를 "flat rate, predictable"로 안내하며 웹사이트·앱 사례를 명시적으로 환영 |
| 2 | EODHD — `support@eodhistoricaldata.com` | Professional 이용자의 재배포에 "prior written approval" 경로 존재 |

## 본문 (영문 — Tiingo용, EODHD는 수신처만 바꿔 동일 사용)

```text
Subject: Redistribution license quote for a small public dashboard (mulmit.com)

Hello,

I operate Mulmit (https://mulmit.com), a publicly accessible bilingual market
dashboard. It is a personal project today with no accounts and no advertising,
though advertising may be added later. I am writing for a quote, not to
negotiate: my budget is small and fixed, and if the number does not fit I will
simply not build this feature.

What I want to license:

1. DATA - US-listed equities and ETFs, end-of-day adjusted closes only.
   No real-time, no intraday, no fundamentals, no news.

2. USE - Per-ticker display on the public site: the latest close, historical
   price and drawdown charts, and statistics derived from the closes
   (returns, maximum drawdown, volatility). Users look up one ticker at a
   time; I would store the history server-side and serve it through my own
   JSON API, which is open without authentication.

3. SCALE - A hobby-sized deployment: one server, low thousands of page views
   a month today.

Questions:

1. What flat-rate license covers this use, and at what monthly price?
2. Does the price change if the site later carries advertising?
3. What attribution do you require, and is a link mandatory?
4. Are there per-user or per-pageview reporting obligations I should know
   about before committing?

For transparency: my total data budget is roughly USD 36 a month. If your
redistribution licensing starts above that, a one-line reply saying so would
save us both time, and I appreciate it either way.

Thank you,
Subeom Kwon
subeomkwon@gmail.com
https://mulmit.com
```

## 회신 후 할 일

1. 견적을 등록부 §6 표에 기록한다 (금액, 조건, 날짜).
2. 예산(월 5만원) 안이고 조건이 명확하면 사용자 승인 후 결제 → 새 lane
   (`tiingo` 등) + `DS-2026-009`로 등록 → 미국 종목 분석을 한국판과 같은
   화면으로 복원.
3. 예산 밖이면 금액만 기록하고 종료 — 미국 가격 분석은 수익화 이후로.
