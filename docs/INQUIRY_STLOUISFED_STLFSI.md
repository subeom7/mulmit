# St. Louis Fed 금융스트레스지수(STLFSI4) 표시 허락 문의 초안

작성일: 2026-08-17
관련 항목: `docs/DATA_SOURCE_REGISTER.md` §5.2 `financial_stress`, §4.1 문의 대기 목록
상태: **발송 전.** 발송 후 회신을 새 `decision_id`로 기록한다.

## 왜 이 문의가 성립하는가

STLFSI4는 St. Louis Fed **자신이 만드는** 지수다. 시리즈 페이지(2026-08-17 확인)의
태그가 **"Copyrighted: Citation Required"**이고 권장 인용문(Suggested Citation)을
직접 제공한다. 즉 저작권을 주장하되 조건을 "인용"이라고 스스로 적어 둔 상태다.

뉴욕 연준 선례와 구조가 같을 수 있다 — 연방기관이 아닌 준비은행이라 저작권을
주장하지만, 약관을 실제로 읽어 보니 필요한 범위를 명시적으로 허락하고 있었다
(`DS-2026-003`). 확인 전까지는 양쪽 다 추측이므로 서면으로 묻는다.

두 가지를 함께 물어야 한다. **표시 권리**(공개 웹 + 자체 JSON API 전달)와
**수집 경로**(FRED API 약관은 제3자 제공을 제한하므로, 데이터 소유자인 St. Louis
Fed가 자기 지수에 대해 이를 허락하는지). 둘 중 하나만 확인되면 여전히 못 쓴다.

## 연락 경로

전용 이메일이 공개돼 있지 않다. 확인된 경로:

- FRED "Questions or Comments" 폼: <https://fred.stlouisfed.org/contactus/>
- 시리즈 페이지 하단 "NEED HELP? → Questions or Comments"

폼 제출 시 아래 본문을 그대로 붙여넣는다.

## 본문 (영문)

```text
Subject: Permission to display the STLFSI4 on a public dashboard (mulmit.com)

Hello,

I operate Mulmit (https://mulmit.com), a publicly accessible bilingual market
dashboard. It is a non-commercial personal project today, with no accounts, no
paid tier and no advertising, though advertising or sponsorship may be added
later.

I would like to display the St. Louis Fed Financial Stress Index (STLFSI4) and
I am writing to ask what that requires, rather than assuming. The series page
tags it "Copyrighted: Citation Required" and provides a Suggested Citation, so
my question is whether citation is the complete condition for the following
use, or whether separate permission or a licence is required:

1. DISPLAY
   Showing the weekly index value and a historical chart to unauthenticated
   visitors of a public website, with the Suggested Citation shown alongside.

2. SERVER RELAY
   Storing the series in my own database and serving it through my own
   server-side JSON API to my frontend. The endpoint is open without
   authentication, so any visitor could read the same JSON directly. I am not
   describing a private internal API.

3. RETRIEVAL ROUTE
   If the use above is permitted, what is the sanctioned way to obtain the
   data? I would normally use the FRED API, but its Terms of Use restrict
   storing and providing API content to third parties, so I do not want to
   rely on the API for a use its terms may not cover. If the Bank, as the
   owner of this particular series, grants the use described here, please let
   me know whether the FRED API is the right channel for it or whether another
   route is preferred.

4. ATTRIBUTION
   Whether the Suggested Citation on the series page is the wording you want,
   and where it should appear.

5. COMMERCIAL STATUS
   Whether any of the above changes if the site later carries advertising or
   sponsorship.

If any of this requires more than citation, I would appreciate the applicable
terms. If the answer is no, I will keep the card for this series empty, as it
is today.

Thank you for your time.

Kind regards,
Subeom Kwon
subeomkwon@gmail.com
https://mulmit.com
```

## 한국어 참고본

1. **표시** — 주간 지수값·역사 차트를 공개 웹에, 권장 인용문과 함께
2. **서버 중계** — 자체 DB 저장 + 자체 JSON API 전달. 누구나 직접 받을 수 있음을 숨기지 않음
3. **수집 경로** — FRED API 약관이 제3자 제공을 제한하므로, 소유자로서 허락한다면 어떤 경로가 맞는지
4. **출처 표기** — 권장 인용문이 원하는 문구인지, 위치는 어디인지
5. **상업 범위** — 광고·후원 도입 시 조건 변화

3번이 이 문의의 핵심 차별점이다. 표시 허락만 받고 수집 경로를 확인하지 않으면
"FRED 우회 복제 금지"라는 등록부 원칙과 충돌한 채로 남는다.

## 회신 후 할 일

1. 새 `decision_id`(DS-2026-007 예정)로 등록부에 기록한다.
2. 허락 시: `financial_stress`를 `license_required` → `approved`로 바꾸고, 허락된
   수집 경로로 lane을 연결한다. FRED API가 허락되면 FRED lane이 아니라 **별도
   provider id**(예: `stlouisfed`)로 저장해 FRED 전체 lane과 분리한다 — 이 허락은
   STLFSI에만 적용되기 때문이다.
3. 거부 또는 무응답 시: 카드를 빈 상태로 유지한다. 자체 스트레스 지수가 이미
   유동성·거시 축을 대체하고 있으므로 기능 공백은 제한적이다.
