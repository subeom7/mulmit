"use strict";

/*
Planned asset API contract (the adapter below also accepts records/maps):
GET /api/market/assets?history=3y
{
  generated_at, history, provider, groups,
  assets: [{
    id, key, symbol, group, label:{ko,en}, description:{ko,en},
    source:{provider,publisher,url}, units:{long,short},
    latest:{date,value}, previous:{date,value}, change:{value,percent},
    drawdown:{value,ath,date}, freshness:{status,age_seconds,max_age_seconds},
    observations:[{date,value}]
  }], missing:[id]
}
Only finite API values are rendered. There are no demo or fallback market numbers.
*/

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const safeNumber = (value) => {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
};
const localValue = (value, lang) => value && typeof value === "object" ? (value[lang] || value.en || value.ko || "") : (value || "");

// Which page this script is driving. Each HTML sets window.MULMIT_PAGE before
// this file loads; the legacy combined monitor sets nothing and gets everything.
// Renderers already no-op when their section is absent from the page's markup —
// this constant only decides which endpoints are fetched and which deep
// sections are built.
const PAGE = window.MULMIT_PAGE || "all";
const onPage = (...pages) => PAGE === "all" || pages.includes(PAGE);

const TEXT = {
  ko: {
    "brand.tagline": "MARKET SIGNAL CONSOLE", "nav.analytics": "종목 분석", "nav.monitor": "시장 모니터",
    "nav.home": "홈", "nav.kr": "한국", "nav.us": "미국·글로벌",
    "landing.kicker": "KOREA × US MARKET CONSOLE", "landing.title": "장이 닫혀도, 시장은 움직입니다.",
    "landing.copy": "삼성전자·SK하이닉스의 24시간 참고가부터 미국 매크로까지, 연결된 데이터만 보여줍니다. 연결되지 않은 값은 추정하지 않습니다.",
    "landing.krLink": "한국 시장 페이지", "landing.krDesc": "24시간 참고가 · 공식 종가 · 코스피 지수군 · ETF 보드 · 국민연금 5% 공시",
    "landing.usLink": "미국·글로벌 페이지", "landing.usDesc": "S&P 500 히트맵 · 하원 의원 거래 · 스트레스 지수 · 매크로 · 유동성",
    "session.open": "정규장 진행 중", "session.closed": "국내장 마감", "session.until": "개장까지 약 {time}",
    "session.hm": "{h}시간 {m}분", "session.note": "시계 기준 · 휴장일 미반영 · 평일 09:00–15:30 KST",
    "ticker.note": "미 연준 H.10 공식 고시 환율 · 실시간 아님",
    "landing.krMini.kospi": "코스피 종가", "landing.usMini.sp500": "S&P 500 퍼프", "landing.usMini.stress": "스트레스",
    "krpage.kicker": "KOREA MARKETS", "krpage.title": "한국 주식, 장 밖에서도 한눈에.",
    "krpage.copy": "24시간 참고가, 공식 종가, 코스피 지수군, 국민연금 대량보유 공시를 한 페이지에서 봅니다.",
    "uspage.kicker": "US & GLOBAL MARKETS", "uspage.title": "미국·글로벌 시장.",
    "uspage.copy": "S&P 500 히트맵, 스트레스 지수, 매크로, 유동성, 공식 환율을 한 페이지에서 봅니다.",
    "status.connecting": "연결 중", "status.live": "데이터 연결", "status.partial": "일부 데이터", "status.offline": "연결 오류",
    "status.loading": "불러오는 중", "status.viewport": "화면에 표시되면 불러옵니다", "status.unavailable": "데이터 미연결",
    "status.noSeries": "표시할 시계열이 없습니다", "status.retry": "새로고침 후 다시 시도해 주세요.", "status.staleData": "지연 데이터", "status.legacyDisabled": "라이선스 데이터 전환 중 · 공개 데이터 비활성",
    "stress.eyebrow": "MULMIT 자체 산출 · 산식 공개", "stress.title": "유동성·스트레스 지수", "stress.own": "자체 산출",
    "stress.scale": "0에 가까울수록 완화, 100에 가까울수록 긴축", "stress.caption": "지수를 구성하는 입력",
    "stress.colInput": "입력", "stress.colValue": "값", "stress.colPct": "5년 내 백분위", "stress.colScore": "스트레스 점수", "stress.colDir": "방향",
    "stress.inverted": "낮을수록 스트레스", "stress.direct": "높을수록 스트레스",
    "stress.unavailable": "공개 가능한 입력이 부족해 지수를 산출하지 않습니다",
    "status.disabled": "표시 비활성", "status.macroDisabled": "승인된 거시 데이터 공급자가 없어 표시하지 않습니다", "status.rightsPending": "표시 권리 확인 중 · 값을 공개하지 않습니다",
    "theme.toggle": "테마 전환", "hero.kicker": "GLOBAL MARKET INTELLIGENCE", "hero.title": "한눈에 읽는 시장의 온도.",
    "hero.copy": "가격, 위험, 유동성, 거시경제를 같은 시간축에서 확인합니다. 연결되지 않은 데이터는 추정하지 않습니다.",
    "hero.updated": "마지막 갱신", "action.refresh": "새로고침", "overview.eyebrow": "MARKET TAPE", "overview.title": "시장 요약",
    "weekend.title": "Weekend Pulse · 주말 참고 신호", "weekend.notSpot": "현물가격 아님", "weekend.leverage": "레버리지 파생",
    "weekend.liquidity": "저유동성 가능", "weekend.noPromise": "월요일 방향 보장 안 됨", "weekend.syntheticPerp": "USD 환산 합성 무기한선물",
    "weekend.defaultDisclaimer": "주말 파생시장 가격은 얕은 유동성과 레버리지의 영향을 크게 받을 수 있습니다. 월요일 현물시장 예측값으로 사용하지 마세요.",
    "weekend.proxy": "대체 신호", "weekend.direct": "직접 계약", "weekend.auxiliary": "24시간 보조", "weekend.consensus": "합성 신호", "weekend.referenceSignal": "주말 기준 신호", "weekend.funding": "시간당 펀딩", "weekend.volume": "24시간 거래대금", "weekend.openInterest": "미결제약정", "weekend.status": "상태", "weekend.confidence": "근거 품질", "weekend.session": "활성 세션", "weekend.sessionChange": "세션 기준", "weekend.change24h": "24시간 기준", "weekend.stale": "지연", "weekend.reference": "참고 품질",
    "weekend.samsungPerp": "삼성전자 USD 환산 합성 무기한선물 · 한국 현물 종가와 동일한 상품이 아닙니다.",
    "kridx.title": "코스피 지수군", "kridx.copy": "대표 지수와 코스피 200 섹터의 장 마감 확정값입니다. 연초 대비와 52주 범위까지 한 표에서 봅니다.",
    "kridx.colName": "지수", "kridx.colClose": "종가", "kridx.colDay": "전일", "kridx.colYtd": "연초 대비", "kridx.colRange": "52주 범위", "kridx.colValue": "거래대금",
    "kridx.asof": "기준 {date} · 다음 영업일 13시 이후 갱신",
    "zone.kr": "한국 시장", "zone.us": "미국·글로벌 시장",
    "kro.title": "한국 주식, 장 밖에서는", "kro.copy": "장이 닫혀 있어도 합성 무기한선물은 24시간 움직입니다. 마크가격을 공식환율로 환산해 마지막 공식 종가와 비교합니다. 현물 호가나 시초가 예측이 아닙니다.",
    "kro.fxOfficial": "공식환율 환산 · 실시간 환율 아님", "kro.vsClose": "{date} 종가 대비", "kro.mark": "마크", "kro.official": "공식 종가", "kro.fx": "환산 환율",
    "kro.adrRatio": "ADR 비율", "kro.noFx": "환율 미확보 · 환산 보류", "kro.noClose": "공식 종가 미확보", "kro.noMarket": "표시할 시장 없음", "kro.session": "주말 내부 가격발견 중",
    "krp.title": "국민연금 5% 공시", "krp.copy": "주식등의 대량보유 상황보고(5% 룰) 중 국민연금공단 제출분입니다. 보고서 단위의 보유비율 변동이며, 통상 한 달치가 월초에 일괄 공시됩니다. 일별 매매가 아닙니다.",
    "krp.colDate": "보고일", "krp.colCompany": "회사", "krp.colRatio": "보유비율", "krp.colChange": "증감", "krp.colShares": "보유주식수", "krp.colReason": "보고사유",
    "krp.detailPending": "상세 미확보", "krp.window": "최근 {days}일 공시 {total}건 중 {count}건",
    "kre.title": "ETF 보드", "kre.copy": "거래대금 상위 ETF의 종가·NAV·괴리율입니다. 장 마감 확정값이며 실시간이 아닙니다.",
    "kre.colName": "종목", "kre.colClose": "종가", "kre.colDay": "등락", "kre.colNav": "NAV", "kre.colPremium": "괴리율", "kre.colIndex": "기초지수", "kre.colValue": "거래대금",
    "kre.window": "상장 {total}종목 중 거래대금 상위 {count}", "kre.asof": "기준 {date}",
    "ptr.title": "미 하원 의원 주식 거래", "ptr.copy": "STOCK Act에 따른 주기거래보고(PTR)를 그대로 옮깁니다. 금액은 구간으로만 공시되며, 수기 제출분은 원문 링크로 안내합니다. 상원은 수집 경로가 막혀 있어 포함되지 않습니다.",
    "ptr.colDate": "거래일", "ptr.colMember": "의원", "ptr.colAsset": "자산", "ptr.colType": "유형", "ptr.colAmount": "금액 구간", "ptr.colFiled": "신고일",
    "ptr.typeP": "매수", "ptr.typeS": "매도", "ptr.typeSP": "일부 매도", "ptr.typeE": "교환",
    "ptr.ownerSP": "배우자", "ptr.ownerJT": "공동", "ptr.ownerDC": "자녀",
    "ptr.scanned": "거래 미추출 신고(수기·스캔) {count}건 — 원문에서 확인:", "ptr.pending": "상세 수집 대기 {count}건",
    "ptr.partial": "일부 거래만 추출된 신고 {count}건 — 나머지는 원문 참조",
    "ptr.window": "최근 {days}일 신고 {total}건 · 거래 {tx}건 표시",
    "cal.title": "경제 캘린더", "cal.copy": "다가오는 미국 데이터 발표와 FOMC·금통위 일정입니다. 기관이 공표한 예정일이며 변경될 수 있습니다.",
    "cal.colDate": "날짜", "cal.colEvent": "이벤트", "cal.colRegion": "지역", "cal.colKind": "유형",
    "cal.kindRelease": "지표 발표", "cal.kindPolicy": "정책회의", "cal.regionUs": "미국", "cal.regionKr": "한국",
    "cal.dday": "D-{n}", "cal.today": "오늘",
    "sector.title": "섹터 자금 흐름", "sector.caption": "S&P 500 섹터 ETF 기간 수익률", "sector.name": "섹터", "sector.return": "수익률", "sector.interpretation": "플러스 섹터가 넓게 퍼질수록 상승 참여 폭이 넓다는 뜻입니다. ETF 수익률은 자금 유입액과 같지 않습니다.",
    "tv.title": "S&P 500 종목 히트맵", "tv.embed": "외부 위젯", "tv.notice": "이 영역은 TradingView가 직접 제공하며 Mulmit API 데이터가 아닙니다.",
    "tv.terms": "데이터·표시 조건은 제공자 정책을 따릅니다.", "corr.title": "자산군 상관관계", "corr.note": "서로 다른 시장 시간대는 동시 일간 수익률 상관을 왜곡할 수 있습니다.", "corr.scale": "+1은 같은 방향, 0은 약한 선형 관계, −1은 반대 방향입니다. 상관은 인과관계가 아닙니다.",
    "period.label": "기간", "method.title": "숫자를 다루는 원칙", "method.one.title": "출처를 함께 표시", "method.one.copy": "각 수치는 공급자, 기준일, 신선도를 함께 보여줍니다.",
    "method.two.title": "단위를 추측하지 않음", "method.two.copy": "API가 제공한 단위와 배율만 사용합니다.", "method.three.title": "미연결은 미연결로",
    "method.three.copy": "라이선스나 API가 없는 지표는 숫자 대신 상태를 표시합니다.", "badge.fresh": "최신", "badge.stale": "지연", "badge.missing": "미연결",
    "badge.licensed": "라이선스 필요", "badge.pendingRights": "권리 확인 중", "badge.disabled": "비활성", "badge.rights": "표시권리 확인", "badge.sourceTerms": "출처 조건", "badge.synthetic": "합성 무기한선물", "badge.perpetual": "무기한선물", "badge.proxyAlternative": "제한 지표의 대체 참고값", "notice.market": "자산 데이터 표시 조건", "date.asof": "기준", "change.previous": "직전 관측치 대비", "chart.normalized": "각 시계열 시작값 = 100으로 정규화",
    "legal.privacy": "개인정보처리방침", "legal.terms": "이용약관", "legal.disclaimer": "면책 고지",
    "legal.notAdvice": "Mulmit은 정보 제공 서비스이며 투자 자문이나 매매 권유가 아닙니다.",
    "options.copy": "정확한 지수 표시는 원 제공자의 외부 표시 권한이 필요합니다. 계약 전에는 값을 제공하지 않습니다.", "license.copy": "원 데이터 소유자의 외부 표시 권한이 필요한 지표입니다. 허가 전에는 값과 시계열을 공개하지 않습니다.",
    "pendingRights.copy": "공급자의 공개 표시 권리를 서면으로 확인하는 중입니다. 확인 전까지 값과 시계열을 공개하지 않습니다.", "notice.disabledLanes": "현재 비활성인 데이터 공급 경로",
  },
  en: {
    "brand.tagline": "MARKET SIGNAL CONSOLE", "nav.analytics": "Stock analytics", "nav.monitor": "Market monitor",
    "nav.home": "Home", "nav.kr": "Korea", "nav.us": "US & Global",
    "landing.kicker": "KOREA × US MARKET CONSOLE", "landing.title": "Markets move after the close.",
    "landing.copy": "From around-the-clock references for Samsung Electronics and SK Hynix to US macro — only connected data, nothing estimated.",
    "landing.krLink": "Korea markets page", "landing.krDesc": "24h references · official closes · KOSPI index family · ETF board · NPS 5% filings",
    "landing.usLink": "US & global page", "landing.usDesc": "S&P 500 heatmap · House trades · stress index · macro · liquidity",
    "session.open": "KRX session open", "session.closed": "KRX closed", "session.until": "opens in ~{time}",
    "session.hm": "{h}h {m}m", "session.note": "Clock-based; holidays not reflected. Weekdays 09:00–15:30 KST.",
    "ticker.note": "Federal Reserve H.10 official rate · not live",
    "landing.krMini.kospi": "KOSPI close", "landing.usMini.sp500": "S&P 500 perp", "landing.usMini.stress": "Stress",
    "krpage.kicker": "KOREA MARKETS", "krpage.title": "Korean stocks, beyond market hours.",
    "krpage.copy": "Around-the-clock references, official closes, the KOSPI index family and NPS large-holding filings on one page.",
    "uspage.kicker": "US & GLOBAL MARKETS", "uspage.title": "US & global markets.",
    "uspage.copy": "The S&P 500 heatmap, stress index, macro, liquidity and official FX on one page.",
    "status.connecting": "Connecting", "status.live": "Data live", "status.partial": "Partial data", "status.offline": "Connection error",
    "status.loading": "Loading", "status.viewport": "Loads when scrolled into view", "status.unavailable": "Data not connected",
    "status.noSeries": "No series available", "status.retry": "Refresh and try again.", "status.staleData": "Stale data", "status.legacyDisabled": "Public data disabled during licensed-provider migration",
    "stress.eyebrow": "MULMIT COMPOSITE · PUBLISHED METHOD", "stress.title": "Liquidity & Stress Index", "stress.own": "Own composite",
    "stress.scale": "Lower is looser, higher is tighter", "stress.caption": "Inputs that make up the index",
    "stress.colInput": "Input", "stress.colValue": "Value", "stress.colPct": "5-year percentile", "stress.colScore": "Stress score", "stress.colDir": "Direction",
    "stress.inverted": "Lower means more stress", "stress.direct": "Higher means more stress",
    "stress.unavailable": "Too few publishable inputs to compose the index",
    "status.disabled": "Display disabled", "status.macroDisabled": "No approved macro data provider is enabled", "status.rightsPending": "Display rights unconfirmed · values withheld",
    "theme.toggle": "Toggle theme", "hero.kicker": "GLOBAL MARKET INTELLIGENCE", "hero.title": "Read the market in one view.",
    "hero.copy": "Track prices, risk, liquidity and macro conditions on a shared timeline. Missing data is never estimated.",
    "hero.updated": "Last updated", "action.refresh": "Refresh", "overview.eyebrow": "MARKET TAPE", "overview.title": "Market overview",
    "weekend.title": "Weekend Pulse · Reference signals", "weekend.notSpot": "Not spot prices", "weekend.leverage": "Leveraged derivatives",
    "weekend.liquidity": "May be illiquid", "weekend.noPromise": "No Monday direction guarantee", "weekend.syntheticPerp": "USD-converted synthetic perpetuals",
    "weekend.defaultDisclaimer": "Weekend derivative prices can be heavily affected by shallow liquidity and leverage. Do not treat them as Monday spot-market forecasts.",
    "weekend.proxy": "Proxy", "weekend.direct": "Direct contract", "weekend.auxiliary": "24h auxiliary", "weekend.consensus": "Composite", "weekend.referenceSignal": "Weekend reference", "weekend.funding": "Hourly funding", "weekend.volume": "24h notional", "weekend.openInterest": "Open interest", "weekend.status": "Status", "weekend.confidence": "Evidence quality", "weekend.session": "Active session", "weekend.sessionChange": "Session change", "weekend.change24h": "24-hour change", "weekend.stale": "Stale", "weekend.reference": "Reference quality",
    "weekend.samsungPerp": "Samsung Electronics USD-converted synthetic perpetual · not the Korean spot close.",
    "kridx.title": "KOSPI index family", "kridx.copy": "Confirmed closes for the headline indices and KOSPI 200 sectors, with YTD and the 52-week range in one table.",
    "kridx.colName": "Index", "kridx.colClose": "Close", "kridx.colDay": "Day", "kridx.colYtd": "YTD", "kridx.colRange": "52w range", "kridx.colValue": "Value traded",
    "kridx.asof": "As of {date} · updates after 13:00 KST the next business day",
    "zone.kr": "Korea markets", "zone.us": "US & global markets",
    "kro.title": "Korean stocks, after hours", "kro.copy": "Synthetic perpetuals keep trading around the clock. Marks are converted at the official exchange rate and compared with the last official close. Not spot quotes, not an open forecast.",
    "kro.fxOfficial": "Official-rate conversion · not a live FX rate", "kro.vsClose": "vs {date} close", "kro.mark": "Mark", "kro.official": "Official close", "kro.fx": "FX applied",
    "kro.adrRatio": "ADR ratio", "kro.noFx": "No official FX yet · conversion withheld", "kro.noClose": "Official close unavailable", "kro.noMarket": "No live market", "kro.session": "Weekend internal price discovery",
    "krp.title": "NPS 5% filings", "krp.copy": "Large-holding (5% rule) reports filed by the National Pension Service. Report-level stake changes, usually filed as one early-month batch covering the prior month — not daily trades.",
    "krp.colDate": "Filed", "krp.colCompany": "Company", "krp.colRatio": "Stake", "krp.colChange": "Change", "krp.colShares": "Shares held", "krp.colReason": "Reason",
    "krp.detailPending": "Detail pending", "krp.window": "{count} of {total} filings in the last {days} days",
    "kre.title": "ETF board", "kre.copy": "Top ETFs by traded value with close, NAV and the premium/discount. Confirmed end-of-day values, not live quotes.",
    "kre.colName": "Fund", "kre.colClose": "Close", "kre.colDay": "Day", "kre.colNav": "NAV", "kre.colPremium": "Premium", "kre.colIndex": "Underlying index", "kre.colValue": "Value traded",
    "kre.window": "Top {count} of {total} listed, by traded value", "kre.asof": "As of {date}",
    "ptr.title": "US House stock trades", "ptr.copy": "Periodic transaction reports under the STOCK Act, relayed verbatim. Amounts are disclosed only as ranges; scanned paper filings link to the original. The Senate is not included because its portal blocks server collection.",
    "ptr.colDate": "Traded", "ptr.colMember": "Member", "ptr.colAsset": "Asset", "ptr.colType": "Type", "ptr.colAmount": "Amount range", "ptr.colFiled": "Filed",
    "ptr.typeP": "Purchase", "ptr.typeS": "Sale", "ptr.typeSP": "Partial sale", "ptr.typeE": "Exchange",
    "ptr.ownerSP": "Spouse", "ptr.ownerJT": "Joint", "ptr.ownerDC": "Dep. child",
    "ptr.scanned": "{count} paper filings without extracted trades — see the originals:", "ptr.pending": "{count} awaiting detail collection",
    "ptr.partial": "{count} filings partially extracted — see the originals for the rest",
    "ptr.window": "{total} filings in the last {days} days · {tx} transactions shown",
    "cal.title": "Economic calendar", "cal.copy": "Upcoming US data releases and FOMC/BOK meetings. Dates are as announced by the institutions and can change.",
    "cal.colDate": "Date", "cal.colEvent": "Event", "cal.colRegion": "Region", "cal.colKind": "Type",
    "cal.kindRelease": "Data release", "cal.kindPolicy": "Policy meeting", "cal.regionUs": "US", "cal.regionKr": "Korea",
    "cal.dday": "D-{n}", "cal.today": "Today",
    "sector.title": "Sector flow", "sector.caption": "S&P 500 sector ETF period returns", "sector.name": "Sector", "sector.return": "Return", "sector.interpretation": "Broader positive participation can confirm a wider advance. ETF returns are not the same thing as fund-flow dollars.",
    "tv.title": "S&P 500 constituent heatmap", "tv.embed": "Third-party widget", "tv.notice": "TradingView serves this embed directly; it is not Mulmit API data.",
    "tv.terms": "Provider data and display terms apply.", "corr.title": "Cross-asset correlation", "corr.note": "Different market hours can distort same-day return correlations.", "corr.scale": "+1 moves together, 0 indicates a weak linear link, and −1 moves oppositely. Correlation is not causation.",
    "period.label": "Period", "method.title": "How we handle numbers", "method.one.title": "Show the source", "method.one.copy": "Every value carries its provider, observation date and freshness.",
    "method.two.title": "Never guess units", "method.two.copy": "Only API-supplied units and scales are used.", "method.three.title": "Missing stays missing",
    "method.three.copy": "Unlicensed or disconnected indicators show a state instead of an invented number.", "badge.fresh": "Fresh", "badge.stale": "Stale", "badge.missing": "Not connected",
    "badge.licensed": "License required", "badge.pendingRights": "Rights pending", "badge.disabled": "Disabled", "badge.rights": "Display rights", "badge.sourceTerms": "Source terms", "badge.synthetic": "Synthetic perpetual", "badge.perpetual": "Perpetual", "badge.proxyAlternative": "Alternative to restricted series", "notice.market": "Asset-data display terms", "date.asof": "As of", "change.previous": "vs previous observation", "chart.normalized": "Each series rebased to 100 at start",
    "legal.privacy": "Privacy policy", "legal.terms": "Terms of use", "legal.disclaimer": "Disclaimer",
    "legal.notAdvice": "Mulmit is an information service, not investment advice or a solicitation to trade.",
    "options.copy": "Official index display requires the owner's external-display rights. No values are shown before licensing.", "license.copy": "This indicator requires external-display rights from the data owner. Values and history remain hidden until licensed.",
    "pendingRights.copy": "Written confirmation of the provider's public-display rights is pending. Values and history stay hidden until it arrives.", "notice.disabledLanes": "Currently disabled data lanes",
  },
};

const t = (key, params) => {
  let text = TEXT[state.lang]?.[key] || TEXT.ko[key] || key;
  if (params) for (const [name, value] of Object.entries(params)) text = text.replaceAll(`{${name}}`, String(value));
  return text;
};
const LABEL = (ko, en) => ({ ko, en });

const METRICS = {
  sp500: { aliases: ["sp500", "sp_500", "^gspc", "gspc", "spy"], label: LABEL("S&P 500", "S&P 500"), group: "global", format: "number", preferDrawdown: true, accent: "#f5b942", description: LABEL("미국 대형주 시장의 가격과 전고점 대비 위치", "US large-cap price and distance from its prior high") },
  nasdaq: { aliases: ["nasdaq", "nasdaq_composite", "^ixic", "ixic", "qqq"], label: LABEL("나스닥", "Nasdaq"), group: "global", format: "number", preferDrawdown: true, accent: "#f5b942", description: LABEL("미국 성장주 중심 시장의 흐름", "US growth-heavy market trend") },
  gold: { aliases: ["gold", "gc=f", "xauusd", "gld"], label: LABEL("금", "Gold"), group: "global", format: "currency", currency: "USD", accent: "#f5b942", description: LABEL("실질금리와 위험회피 수요에 민감한 안전자산", "A haven asset sensitive to real yields and risk demand") },
  bitcoin: { aliases: ["bitcoin", "btc", "btc-usd", "btcusd"], label: LABEL("비트코인", "Bitcoin"), group: "global", format: "currency", currency: "USD", accent: "#f5b942", description: LABEL("유동성과 위험선호에 민감한 디지털 자산", "A digital asset sensitive to liquidity and risk appetite") },
  kospi: { aliases: ["kospi", "^ks11", "ks11"], label: LABEL("코스피", "KOSPI"), group: "korea", format: "number", preferDrawdown: true, accent: "#2dd4a3", description: LABEL("한국 대형주 시장", "Korean large-cap equity market") },
  kosdaq: { aliases: ["kosdaq", "^kq11", "kq11"], label: LABEL("코스닥", "KOSDAQ"), group: "korea", format: "number", preferDrawdown: true, accent: "#2dd4a3", description: LABEL("한국 성장주 중심 시장", "Korean growth-equity market") },
  // `005930` deliberately absent: that is the Korean issue code, and it now
  // identifies the official won close on `samsung_exact`. This card is the
  // USD synthetic perpetual, so letting both match one record would merge two
  // different measurements into one series.
  samsung: { aliases: ["samsung", "005930.ks"], label: LABEL("삼성전자", "Samsung Electronics"), group: "korea", format: "currency", currency: "KRW", accent: "#2dd4a3", description: LABEL("한국 증시 비중이 큰 반도체 대표 종목", "A major semiconductor constituent of Korea's equity market") },
  dollar_index_broad: { aliases: ["dollar_index_broad", "jrxwtfb_n.b"], label: LABEL("광의 달러지수", "Broad dollar index"), group: "macro", format: "number", accent: "#a78bfa", description: LABEL("연준이 교역량으로 가중한 달러 강세 지표. ICE 달러지수(DXY)와 값을 비교할 수 없습니다", "The Fed's trade-weighted dollar index — its level is not comparable with ICE's DXY") },
  dollar_index_afe: { aliases: ["dollar_index_afe", "jrxwtfn_n.b"], label: LABEL("선진국 달러지수", "AFE dollar index"), group: "macro", format: "number", accent: "#a78bfa", description: LABEL("선진 교역상대국 통화 대비 달러", "The dollar against advanced foreign economies") },
  dollar_index_eme: { aliases: ["dollar_index_eme", "jrxwtfo_n.b"], label: LABEL("신흥국 달러지수", "EME dollar index"), group: "macro", format: "number", accent: "#a78bfa", description: LABEL("신흥 교역상대국 통화 대비 달러", "The dollar against emerging market economies") },
  kospi_exact: { aliases: ["kospi_exact", "fsc_kospi", "코스피"], label: LABEL("코스피 공식 종가", "KOSPI official close"), group: "korea", format: "number", accent: "#2dd4a3", description: LABEL("한국거래소 코스피 지수의 장 마감 확정값", "The confirmed Korea Exchange KOSPI close") },
  kosdaq_exact: { aliases: ["kosdaq_exact", "fsc_kosdaq", "코스닥"], label: LABEL("코스닥 공식 종가", "KOSDAQ official close"), group: "korea", format: "number", accent: "#2dd4a3", description: LABEL("한국거래소 코스닥 지수의 장 마감 확정값", "The confirmed Korea Exchange KOSDAQ close") },
  samsung_exact: { aliases: ["samsung_exact", "fsc_005930", "005930"], label: LABEL("삼성전자 공식 종가", "Samsung official close"), group: "korea", format: "currency", currency: "KRW", accent: "#2dd4a3", description: LABEL("삼성전자 보통주의 원화 종가", "The Korean won close for Samsung Electronics common stock") },
  sk_hynix_exact: { aliases: ["sk_hynix_exact", "fsc_000660", "000660"], label: LABEL("SK하이닉스 공식 종가", "SK Hynix official close"), group: "korea", format: "currency", currency: "KRW", accent: "#2dd4a3", description: LABEL("SK하이닉스 보통주의 원화 종가", "The Korean won close for SK Hynix common stock") },
  usdkrw: { aliases: ["usdkrw", "krw=x", "krwusd", "usd/krw"], label: LABEL("원·달러", "USD/KRW"), group: "korea", format: "currency", currency: "KRW", accent: "#2dd4a3", description: LABEL("달러 한 단위당 원화 환율", "Korean won per US dollar") },
  ewz: { aliases: ["ewz", "brazil"], label: LABEL("브라질 EWZ", "Brazil EWZ"), group: "emerging", format: "currency", currency: "USD", accent: "#38bdf8", description: LABEL("브라질 주식시장 ETF", "Brazil equity ETF") },
  inda: { aliases: ["inda", "india"], label: LABEL("인도 INDA", "India INDA"), group: "emerging", format: "currency", currency: "USD", accent: "#38bdf8", description: LABEL("인도 주식시장 ETF", "India equity ETF") },
  vnm: { aliases: ["vnm", "vietnam"], label: LABEL("베트남 VNM", "Vietnam VNM"), group: "emerging", format: "currency", currency: "USD", accent: "#38bdf8", description: LABEL("베트남 주식시장 ETF", "Vietnam equity ETF") },
  ewj: { aliases: ["ewj", "japan"], label: LABEL("일본 EWJ", "Japan EWJ"), group: "emerging", format: "currency", currency: "USD", accent: "#38bdf8", description: LABEL("일본 주식시장 ETF", "Japan equity ETF") },
  vix: { aliases: ["vix", "vixcls"], label: LABEL("VIX 변동성", "VIX volatility"), group: "risk", format: "number", accent: "#fb7185" },
  // reserved: no source can fill this yet by design (own index, not built).
  sentiment: { aliases: ["sentiment", "fear_greed", "mulmit_sentiment"], label: LABEL("시장 심리", "Market sentiment"), group: "risk", format: "number", reserved: true, accent: "#fb7185", description: LABEL("공식 입력과 공개된 방법론으로 산출하는 자체 지수 연결 대기", "Awaiting a proprietary index built from licensed inputs and a published methodology") },
  yield_curve: { aliases: ["yield_curve", "t10y2y", "yield_spread"], label: LABEL("장단기 금리차", "10Y–2Y curve"), group: "risk", format: "percentPoints", accent: "#fb7185" },
  high_yield_spread: { aliases: ["high_yield_spread", "bamlh0a0hym2"], label: LABEL("하이일드 스프레드", "High-yield spread"), group: "risk", format: "percentPoints", accent: "#fb7185" },
  financial_stress: { aliases: ["financial_stress", "stlfsi4"], label: LABEL("금융스트레스", "Financial stress"), group: "risk", format: "number", accent: "#fb7185" },
  dxy: { aliases: ["dxy", "dollar_index"], label: LABEL("달러인덱스", "Dollar index"), group: "macro", format: "number", accent: "#a78bfa" },
  usdjpy: { aliases: ["usdjpy", "jpy=x", "usd/jpy"], label: LABEL("달러·엔", "USD/JPY"), group: "macro", format: "currency", currency: "JPY", accent: "#a78bfa" },
  treasury_10y: { aliases: ["treasury_10y", "dgs10", "us10y"], label: LABEL("미국 10년물", "US 10-year yield"), group: "macro", format: "percentPoints", accent: "#a78bfa" },
  wti: { aliases: ["wti", "dcoilwtico", "cl=f"], label: LABEL("WTI 원유", "WTI crude"), group: "macro", format: "currency", currency: "USD", accent: "#a78bfa" },
  copper: { aliases: ["copper", "pcoppusdm", "hg=f"], label: LABEL("구리", "Copper"), group: "macro", format: "number", accent: "#a78bfa" },
  unemployment: { aliases: ["unemployment", "unrate"], label: LABEL("미국 실업률", "US unemployment"), group: "macro", format: "percentPoints", accent: "#a78bfa" },
  initial_claims: { aliases: ["initial_claims", "icsa"], label: LABEL("신규 실업수당", "Initial claims"), group: "macro", format: "compact", accent: "#a78bfa" },
  fed_assets: { aliases: ["fed_assets", "walcl"], label: LABEL("연준 총자산", "Fed total assets"), group: "liquidity", format: "compact", accent: "#38bdf8" },
  reserve_balances: { aliases: ["reserve_balances", "wresbal", "reserves"], label: LABEL("지급준비금", "Reserve balances"), group: "liquidity", format: "compact", accent: "#38bdf8" },
  reverse_repo: { aliases: ["reverse_repo", "rrp", "rrpontsyd"], label: LABEL("역레포 RRP", "Reverse repo (RRP)"), group: "liquidity", format: "compact", accent: "#38bdf8" },
  treasury_general_account: { aliases: ["treasury_general_account", "tga", "wtregen"], label: LABEL("재무부 TGA", "Treasury General Account"), group: "liquidity", format: "compact", accent: "#38bdf8" },
  m2: { aliases: ["m2", "m2sl"], label: LABEL("미국 M2", "US M2"), group: "liquidity", format: "compact", accent: "#38bdf8" },
  retail_money_market_funds: { aliases: ["retail_money_market_funds", "wrmfns", "mmf"], label: LABEL("리테일 MMF", "Retail money market funds"), group: "liquidity", format: "compact", accent: "#38bdf8" },
  fx_usdkrw: { aliases: ["fx_usdkrw", "rxi_n.b.ko"], label: LABEL("원·달러", "USD/KRW"), group: "fx", format: "rate", accent: "#2dd4a3", description: LABEL("달러 한 단위당 원화. 미 연준 H.10 공식 고시값입니다.", "Korean won per US dollar, from the Federal Reserve's official H.10 release.") },
  fx_usdjpy: { aliases: ["fx_usdjpy", "rxi_n.b.ja"], label: LABEL("엔·달러", "USD/JPY"), group: "fx", format: "rate", accent: "#a78bfa", description: LABEL("달러 한 단위당 엔화", "Japanese yen per US dollar") },
  fx_usdcny: { aliases: ["fx_usdcny", "rxi_n.b.ch"], label: LABEL("위안·달러", "USD/CNY"), group: "fx", format: "rate", accent: "#f5b942", description: LABEL("달러 한 단위당 위안화", "Chinese yuan per US dollar") },
  fx_eurusd: { aliases: ["fx_eurusd", "rxi$us_n.b.eu"], label: LABEL("유로·달러", "EUR/USD"), group: "fx", format: "rate", accent: "#38bdf8", description: LABEL("유로 한 단위당 달러. 위 세 개와 방향이 반대입니다.", "US dollars per euro — quoted the opposite way round to the three above.") },
  fx_gbpusd: { aliases: ["fx_gbpusd", "rxi$us_n.b.uk"], label: LABEL("파운드·달러", "GBP/USD"), group: "fx", format: "rate", accent: "#fb7185", description: LABEL("파운드 한 단위당 달러. 위 세 개와 방향이 반대입니다.", "US dollars per British pound — quoted the opposite way round to the three above.") },
  sofr: { aliases: ["sofr"], label: LABEL("SOFR", "SOFR"), group: "funding", format: "percentPoints", accent: "#2dd4a3" },
  effective_fed_funds: { aliases: ["effective_fed_funds", "effr"], label: LABEL("실효 연방기금금리", "Effective fed funds"), group: "funding", format: "percentPoints", accent: "#2dd4a3" },
  reserve_interest: { aliases: ["reserve_interest", "iorb"], label: LABEL("지급준비금 이자율", "IORB"), group: "funding", format: "percentPoints", accent: "#2dd4a3" },
  skew: { aliases: ["skew", "^skew"], label: LABEL("CBOE SKEW", "CBOE SKEW"), group: "options", format: "number", licensed: true, accent: "#a78bfa" },
  vvix: { aliases: ["vvix", "^vvix"], label: LABEL("VVIX", "VVIX"), group: "options", format: "number", licensed: true, accent: "#a78bfa" },
  ovx: { aliases: ["ovx", "^ovx"], label: LABEL("OVX", "OVX"), group: "options", format: "number", licensed: true, accent: "#a78bfa" },
  pcr: { aliases: ["pcr", "put_call_ratio"], label: LABEL("Put/Call Ratio", "Put/Call ratio"), group: "options", format: "number", licensed: true, accent: "#a78bfa" },
};

// Interpretation is intentionally separate from the data. These are reading
// guides, never replacement values or forecasts.
const INSIGHTS = {
  vix: {
    description: LABEL("미국 주식 옵션에 반영된 단기 변동성 기대를 보는 지표입니다.", "A measure of near-term volatility priced into US equity options."),
    hints: [LABEL("20 미만: 비교적 차분한 옵션 가격", "Below 20: comparatively calm option pricing"), LABEL("20~30: 불확실성 확대 구간", "20–30: uncertainty is elevated"), LABEL("30 초과: 큰 변동을 가격에 반영", "Above 30: large moves are being priced")],
  },
  yield_curve: {
    description: LABEL("미국 10년물 금리에서 2년물 금리를 뺀 경기순환 참고 지표입니다.", "The US 10-year yield minus the 2-year yield, used as a cycle reference."),
    hints: [LABEL("0 미만은 장단기 금리 역전", "Below zero is an inverted curve"), LABEL("역전 뒤 재가팔라지는 속도도 함께 확인", "Also watch the pace of re-steepening after inversion")],
  },
  high_yield_spread: {
    description: LABEL("저신용 회사채가 국채보다 요구하는 추가 보상으로 신용 스트레스를 살핍니다.", "The extra yield demanded over Treasuries for lower-rated corporate debt."),
    hints: [LABEL("3~4%: 비교적 차분한 신용시장 참고 구간", "3–4%: a comparatively calm credit reference range"), LABEL("4~6%: 신용 경계가 높아지는 구간", "4–6%: credit caution is rising"), LABEL("8% 이상: 심한 신용 스트레스 참고 구간", "8% or more: severe-credit-stress reference range")],
  },
  financial_stress: {
    description: LABEL("STLFSI4는 금리 7개·스프레드 6개·기타 5개, 총 18개 주간 시계열을 묶은 금융여건 지표입니다.", "STLFSI4 combines 18 weekly series: seven rates, six spreads and five other indicators."),
    hints: [LABEL("0 미만: 장기 평균보다 낮은 스트레스", "Below zero: stress below its long-run average"), LABEL("0 초과: 장기 평균보다 높은 스트레스", "Above zero: stress above its long-run average")],
  },
  dxy: {
    description: LABEL("주요 통화 대비 달러의 상대적 강약을 보여주는 지수입니다.", "A gauge of the dollar's relative strength against major currencies."),
    hints: [LABEL("상승: 글로벌 달러 조달 여건이 빡빡해질 수 있음", "Rising: global dollar funding can tighten"), LABEL("하락: 비달러 자산의 부담이 완화될 수 있음", "Falling: pressure on non-dollar assets can ease")],
  },
  usdjpy: {
    description: LABEL("달러 한 단위당 엔화 가격으로 미·일 금리차와 위험선호에 민감합니다.", "Yen per dollar, sensitive to US–Japan rate differentials and risk appetite."),
    hints: [LABEL("상승은 엔화 약세, 하락은 엔화 강세", "A rise means a weaker yen; a fall means a stronger yen"), LABEL("금리차와 위험회피 움직임을 함께 확인", "Read it alongside rate differentials and risk-off moves")],
  },
  treasury_10y: {
    description: LABEL("미국 장기 자금의 기준금리로 성장주와 채권 가치평가에 영향을 줍니다.", "A benchmark long-term US rate that influences bond and growth-stock valuations."),
    hints: [LABEL("급등: 장기 듀레이션 자산의 할인율 부담", "Sharp rise: higher discount-rate pressure on long-duration assets"), LABEL("하락 원인이 물가 완화인지 성장 우려인지 구분", "Distinguish disinflation from growth fear when yields fall")],
  },
  wti: {
    description: LABEL("미국 원유 가격의 대표 기준으로 에너지 비용과 물가 기대를 반영합니다.", "A US crude benchmark reflecting energy costs and inflation expectations."),
    hints: [LABEL("상승: 비용·물가 압력을 높일 수 있음", "Rising: can add cost and inflation pressure"), LABEL("급락: 공급 증가와 수요 둔화를 구분", "Sharp fall: separate extra supply from weaker demand")],
  },
  copper: {
    description: LABEL("제조·건설 수요에 폭넓게 쓰여 세계 산업활동의 보조 지표로 봅니다.", "Widely used in manufacturing and construction, making it an industrial-activity cross-check."),
    hints: [LABEL("지속 상승은 산업 수요 개선과 나란히 나타날 수 있음", "A sustained rise can align with improving industrial demand"), LABEL("단일 원자재만으로 경기를 단정하지 않음", "Do not infer the cycle from one commodity alone")],
  },
  unemployment: {
    description: LABEL("미국 노동력 중 실업 상태의 비율입니다.", "The share of the US labor force that is unemployed."),
    hints: [LABEL("고정 수치보다 상승 속도와 추세를 확인", "The pace and trend matter more than one fixed cutoff"), LABEL("빠른 상승은 노동시장 냉각 신호", "A rapid rise can signal labor-market cooling")],
  },
  initial_claims: {
    description: LABEL("새로 실업급여를 신청한 사람 수를 주간으로 집계한 고빈도 고용 지표입니다.", "A high-frequency weekly count of new unemployment-insurance claims."),
    hints: [LABEL("한 주의 잡음보다 여러 주의 지속 상승을 중시", "Prioritize a sustained multiweek rise over one noisy print")],
  },
  fed_assets: {
    description: LABEL("연준 대차대조표의 총자산으로 QE·QT의 큰 방향을 확인합니다.", "Total Federal Reserve assets, used to track the broad direction of QE or QT."),
    hints: [LABEL("확대는 통상 중앙은행 유동성 증가", "Expansion usually adds central-bank liquidity"), LABEL("구성 변화도 총액만큼 중요", "Composition can matter as much as the total")],
  },
  reserve_balances: {
    description: LABEL("은행이 연준 계정에 보유한 준비금으로 금융시스템의 결제 여력을 보여줍니다.", "Balances banks hold at the Fed, indicating settlement liquidity in the banking system."),
    hints: [LABEL("빠른 감소는 단기자금시장과 함께 점검", "Check rapid declines against money-market conditions")],
  },
  reverse_repo: {
    description: LABEL("머니마켓 참여자가 연준에 하룻밤 맡긴 자금으로 단기 유동성 완충 역할을 합니다.", "Overnight cash placed at the Fed by money-market participants, acting as a liquidity buffer."),
    hints: [LABEL("감소는 다른 시장으로 현금이 이동할 여지를 뜻함", "A decline can free cash to move elsewhere"), LABEL("0 근처에서는 이 완충 여력이 대부분 소진", "Near zero, most of this buffer is already depleted")],
  },
  treasury_general_account: {
    description: LABEL("미 재무부가 연준에 보유한 현금 계정입니다.", "The US Treasury's cash account at the Federal Reserve."),
    hints: [LABEL("증가는 대체로 은행 유동성 흡수", "An increase generally absorbs banking-system liquidity"), LABEL("감소는 대체로 유동성 환류", "A decrease generally returns liquidity")],
  },
  m2: {
    description: LABEL("현금·예금 등 비교적 유동적인 통화의 넓은 집계입니다.", "A broad measure of relatively liquid money including cash and deposits."),
    hints: [LABEL("지속 증가가 유동성 환경을 받칠 수 있음", "Sustained growth can support liquidity conditions"), LABEL("절대 수준만으로 자산 가격을 예측하지 않음", "The level alone is not an asset-price forecast")],
  },
  retail_money_market_funds: {
    description: LABEL("개인 투자자용 머니마켓펀드 잔액으로 단기 대기자금의 한 부분입니다.", "Retail money-market-fund balances, one component of short-term parked cash."),
    hints: [LABEL("증가는 현금성 자산 선호와 나란히 볼 수 있음", "A rise can align with preference for cash-like assets"), LABEL("감소분이 반드시 주식으로 이동하는 것은 아님", "A decline does not imply the money went to equities")],
  },
  fx_usdkrw: { aliases: ["fx_usdkrw", "rxi_n.b.ko"], label: LABEL("원·달러", "USD/KRW"), group: "fx", format: "rate", accent: "#2dd4a3", description: LABEL("달러 한 단위당 원화. 미 연준 H.10 공식 고시값입니다.", "Korean won per US dollar, from the Federal Reserve's official H.10 release.") },
  fx_usdjpy: { aliases: ["fx_usdjpy", "rxi_n.b.ja"], label: LABEL("엔·달러", "USD/JPY"), group: "fx", format: "rate", accent: "#a78bfa", description: LABEL("달러 한 단위당 엔화", "Japanese yen per US dollar") },
  fx_usdcny: { aliases: ["fx_usdcny", "rxi_n.b.ch"], label: LABEL("위안·달러", "USD/CNY"), group: "fx", format: "rate", accent: "#f5b942", description: LABEL("달러 한 단위당 위안화", "Chinese yuan per US dollar") },
  fx_eurusd: { aliases: ["fx_eurusd", "rxi$us_n.b.eu"], label: LABEL("유로·달러", "EUR/USD"), group: "fx", format: "rate", accent: "#38bdf8", description: LABEL("유로 한 단위당 달러. 위 세 개와 방향이 반대입니다.", "US dollars per euro — quoted the opposite way round to the three above.") },
  fx_gbpusd: { aliases: ["fx_gbpusd", "rxi$us_n.b.uk"], label: LABEL("파운드·달러", "GBP/USD"), group: "fx", format: "rate", accent: "#fb7185", description: LABEL("파운드 한 단위당 달러. 위 세 개와 방향이 반대입니다.", "US dollars per British pound — quoted the opposite way round to the three above.") },
  sofr: {
    description: LABEL("미 국채 담보 익일물 조달금리로 담보부 달러 자금시장의 기준입니다.", "The secured overnight financing benchmark backed by US Treasuries."),
    hints: [LABEL("EFFR·IORB와의 간격이 확대되면 조달 압력 점검", "A widening gap to EFFR or IORB warrants a funding-pressure check")],
  },
  effective_fed_funds: {
    description: LABEL("은행 간 무담보 익일물 거래의 실효 금리로 통화정책 전달의 기준점입니다.", "The effective unsecured overnight interbank rate and a policy-transmission anchor."),
    hints: [LABEL("목표 범위와 다른 단기금리와의 간격을 확인", "Compare it with the target range and other overnight rates")],
  },
  reserve_interest: {
    description: LABEL("연준이 적격 예금기관의 준비금에 지급하는 이자율입니다.", "The rate the Fed pays eligible depository institutions on reserve balances."),
    hints: [LABEL("SOFR가 IORB를 웃돌면 담보부 현금 수요를 점검", "When SOFR exceeds IORB, check demand for secured cash")],
  },
  skew: { hints: [LABEL("140 이상: 꼬리위험 보험료가 높은 참고 구간", "140 or more: high tail-risk-premium reference range")] },
  vvix: { hints: [LABEL("130 이상: 변동성의 변동성이 높은 참고 구간", "130 or more: high volatility-of-volatility reference range")] },
  ovx: { hints: [LABEL("60 이상: 원유 옵션 변동성이 높은 참고 구간", "60 or more: high oil-option-volatility reference range")] },
  pcr: { hints: [LABEL("1 초과: 풋 수요 우세 참고 구간", "Above 1: put-demand-heavy reference range"), LABEL("0.7 미만: 콜 쏠림 참고 구간", "Below 0.7: call-heavy reference range"), LABEL("계약 범위와 산식이 다르면 직접 비교하지 않음", "Do not compare ratios built from different contract universes")] },
};

const OVERVIEW = [
  { id: "global", label: LABEL("글로벌 자산", "Global assets"), keys: ["sp500", "nasdaq", "gold", "bitcoin"] },
  { id: "korea", label: LABEL("한국 자산", "Korean assets"), keys: ["kospi_exact", "kosdaq_exact", "samsung_exact", "fx_usdkrw"] },
  { id: "emerging", label: LABEL("글로벌 ETF", "Global ETFs"), keys: ["ewz", "inda", "vnm", "ewj"] },
  { id: "risk", label: LABEL("시장 위험", "Market risk"), keys: ["sentiment", "vix", "yield_curve", "high_yield_spread"] },
  { id: "fx", label: LABEL("환율", "Exchange rates"), keys: ["fx_usdkrw", "fx_usdjpy", "fx_eurusd", "fx_usdcny"] },
  { id: "macro", label: LABEL("매크로", "Macro"), keys: ["dollar_index_broad", "usdjpy", "treasury_10y", "wti"] },
  { id: "liquidity", label: LABEL("유동성", "Liquidity"), keys: ["fed_assets", "reserve_balances", "reverse_repo", "treasury_general_account"] },
  { id: "options", label: LABEL("옵션 위험", "Options risk"), keys: ["skew", "vvix", "ovx", "pcr"] },
];

const SECTIONS = [
  // korea-official leads: it renders into the deep flow with the others, then
  // the whole section is moved up into the Korea zone beside #kr-overnight.
  { id: "korea-official", zone: "kr", eyebrow: "KOREA · OFFICIAL CLOSE", title: LABEL("한국 공식 종가", "Korean official closes"), copy: LABEL("한국거래소 장 마감 확정값입니다. 금융위원회가 공공데이터로 개방한 자료로, 기준일 다음 영업일에 공개됩니다. 위의 24시간 참고가와 같은 값이 아닙니다.", "Confirmed Korea Exchange closes, opened as public data by the Financial Services Commission and published the next business day. These are not the around-the-clock references above."), keys: ["kospi_exact", "kosdaq_exact", "samsung_exact", "sk_hynix_exact"] },
  { id: "global-assets", zone: "us", eyebrow: "GLOBAL PRICES", title: LABEL("글로벌 자산", "Global assets"), copy: LABEL("전고점 대비 위치와 최근 가격 흐름을 함께 봅니다.", "View recent prices alongside distance from prior highs."), keys: ["sp500", "nasdaq", "gold", "bitcoin"] },
  { id: "global-etfs", zone: "us", eyebrow: "CROSS-BORDER ETFs", title: LABEL("글로벌 지역 ETF", "Regional ETFs"), copy: LABEL("미국 상장 ETF를 통해 지역별 위험선호를 확인합니다.", "Use US-listed ETFs to compare regional risk appetite."), keys: ["ewz", "inda", "vnm", "ewj"] },
  { id: "market-risk", zone: "us", eyebrow: "RISK & CREDIT", title: LABEL("시장 위험과 신용", "Risk and credit"), copy: LABEL("시장심리·변동성·금리곡선·신용스프레드·금융스트레스를 나란히 봅니다.", "Compare sentiment, volatility, the yield curve, credit spread and financial stress."), keys: ["sentiment", "vix", "yield_curve", "high_yield_spread", "financial_stress"] },
  { id: "macro-regime", zone: "us", eyebrow: "MACRO REGIME", title: LABEL("매크로 환경", "Macro regime"), copy: LABEL("달러·금리·원자재·고용의 방향을 확인합니다.", "Track the dollar, rates, commodities and labor conditions."), keys: ["dollar_index_broad", "dxy", "usdjpy", "treasury_10y", "wti", "copper", "unemployment", "initial_claims"] },
  { id: "liquidity", zone: "us", eyebrow: "FED & LIQUIDITY", title: LABEL("유동성 대차대조표", "Liquidity balance sheet"), copy: LABEL("연준·재무부·단기자금시장 유동성의 크기와 흐름입니다.", "Monitor Federal Reserve, Treasury and money-market liquidity."), keys: ["fed_assets", "reserve_balances", "reverse_repo", "treasury_general_account", "m2", "retail_money_market_funds"] },
  { id: "exchange-rates", zone: "us", eyebrow: "OFFICIAL FX · FEDERAL RESERVE H.10", title: LABEL("환율", "Exchange rates"), copy: LABEL("미 연준이 매 영업일 고시하는 공식 환율입니다. 앞의 세 개는 달러당 외화, 뒤의 두 개는 외화당 달러로 방향이 반대입니다.", "Official rates published each business day by the Federal Reserve. The first three are foreign currency per dollar; the last two are quoted the other way round."), keys: ["fx_usdkrw", "fx_usdjpy", "fx_usdcny", "fx_eurusd", "fx_gbpusd", "dollar_index_afe", "dollar_index_eme"] },
  { id: "funding", zone: "us", eyebrow: "OVERNIGHT FUNDING", title: LABEL("단기자금 조달금리", "Overnight funding"), copy: LABEL("담보·무담보 금리와 지급준비금 이자율의 간격을 봅니다.", "Compare secured, unsecured and reserve remuneration rates."), keys: ["sofr", "effective_fed_funds", "reserve_interest"] },
  { id: "options-risk", zone: "us", eyebrow: "DERIVATIVES", title: LABEL("옵션과 변동성", "Options and volatility"), copy: LABEL("공식 라이선스가 필요한 값은 계약 전까지 빈 상태로 표시합니다.", "Values requiring official display licenses remain blank until licensed."), keys: ["skew", "vvix", "ovx", "pcr"] },
];

const COMPARISONS = [
  { title: LABEL("지급준비금 vs TGA", "Reserves vs TGA"), copy: LABEL("은행 유동성과 재무부 현금잔고의 상대 흐름", "Relative movement of bank liquidity and Treasury cash"), keys: ["reserve_balances", "treasury_general_account"] },
  { title: LABEL("MMF vs 역레포", "MMF vs reverse repo"), copy: LABEL("머니마켓펀드 자금과 연준 역레포의 상대 흐름", "Relative movement of money funds and the Fed reverse repo"), keys: ["retail_money_market_funds", "reverse_repo"] },
  { title: LABEL("SOFR vs EFFR", "SOFR vs EFFR"), copy: LABEL("담보부와 무담보 익일물 금리", "Secured and unsecured overnight rates"), keys: ["sofr", "effective_fed_funds"] },
  { title: LABEL("SOFR vs IORB", "SOFR vs IORB"), copy: LABEL("시장 조달금리와 지급준비금 보상금리", "Market funding versus reserve remuneration"), keys: ["sofr", "reserve_interest"] },
];

const state = {
  lang: localStorage.getItem("monitor.locale") === "en" ? "en" : "ko",
  assets: null, macro: null, sectors: null, weekend: null,
  stress: null, krOvernight: null, krPension: null, krEtf: null, usPtr: null, calendar: null,
  records: new Map(), restricted: new Map(), errors: {}, sectorPeriod: localStorage.getItem("monitor.sectorPeriod") || "1d",
  tvPeriod: localStorage.getItem("monitor.tvPeriod") || "1d", tvLoaded: false, correlationLoaded: false,
};

function trNode(root = document) {
  $$('[data-i18n]', root).forEach((node) => { node.textContent = t(node.dataset.i18n); });
  $$('[data-i18n-aria]', root).forEach((node) => node.setAttribute("aria-label", t(node.dataset.i18nAria)));
}

function identityValues(record) {
  return [record?.id, record?.key, record?.series_id, record?.symbol, record?.ticker, record?.fred_id]
    .filter(Boolean).map((value) => String(value).toLowerCase());
}

function ingestPayload(payload, kind) {
  if (!payload || typeof payload !== "object") return;
  let records = payload[kind === "macro" ? "series" : "assets"] || payload.records || payload.items || [];
  if (!Array.isArray(records) && records && typeof records === "object") {
    records = Object.entries(records).map(([key, value]) => ({ key, ...(value || {}) }));
  }
  for (const record of records || []) {
    const ids = identityValues(record);
    for (const [key, definition] of Object.entries(METRICS)) {
      if (definition.aliases.some((alias) => ids.includes(alias.toLowerCase()))) {
        const incoming = { ...record, _kind: kind };
        if (record?.status === "license_required" || record?.rights?.status === "license_required") {
          state.restricted.set(key, incoming);
        }
        const existing = state.records.get(key);
        if (!existing || kind === "assets") {
          if (kind === "assets" && state.restricted.has(key)) incoming._restrictedSeries = state.restricted.get(key);
          state.records.set(key, incoming);
        }
      }
    }
  }
}

function latest(record) {
  if (!record) return { value: null, date: null };
  if (record.latest && typeof record.latest === "object") return { value: safeNumber(record.latest.value ?? record.latest.close ?? record.latest.mark), date: record.latest.date || record.latest.as_of || null };
  return { value: safeNumber(record.value ?? record.close ?? record.mark), date: record.date || record.as_of || null };
}

function change(record) {
  if (!record) return { value: null, percent: null };
  const raw = record.change && typeof record.change === "object" ? record.change : {};
  return { value: safeNumber(raw.value ?? record.change_value), percent: safeNumber(raw.percent ?? raw.percentage ?? record.change_percent ?? record.percent_change) };
}

function observations(record) {
  const raw = record?.observations || record?.history || record?.series || record?.prices || [];
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => Array.isArray(item)
    ? { date: item[0], value: safeNumber(item[1]) }
    : { date: item?.date || item?.timestamp || item?.time, value: safeNumber(item?.value ?? item?.close ?? item?.mark) })
    .filter((item) => item.date && item.value !== null);
}

function drawdownValue(record) {
  const dd = record?.drawdown;
  if (dd && typeof dd === "object") return safeNumber(dd.value ?? dd.current ?? dd.percent);
  return safeNumber(record?.ath_drawdown ?? record?.drawdown_percent);
}

function licenseRequired(record, definition) {
  return Boolean(definition?.licensed || record?.status === "license_required" || record?.rights?.status === "license_required");
}

// Rights are still being confirmed with the provider. That is not the same as
// "no contract exists" (license_required) or "no provider is wired up"
// (missing), so it gets its own badge and copy.
function pendingRights(record) {
  return record?.status === "pending_rights" || record?.rights?.status === "pending_rights";
}

// Endpoint-level states the server reports on purpose. None of them are worth
// a "refresh and try again" prompt.
const DISABLED_CODES = {
  legacy_price_data_disabled: "status.legacyDisabled",
  macro_data_disabled: "status.macroDisabled",
  hip3_public_display_pending_rights: "status.rightsPending",
  stress_index_unavailable: "stress.unavailable",
};

// Which endpoint would have filled a card. Only consulted when the card is
// empty: a record that did arrive already carries its own `_kind`. Without this
// an entire gated-off lane would read as "not connected", which is a different
// and misleading statement.
const CARD_LANES = new Map([
  ...["sp500", "nasdaq", "gold", "bitcoin", "kospi", "kosdaq", "samsung", "usdkrw", "ewz", "inda",
    "vnm", "ewj", "dxy", "usdjpy", "vix", "wti", "copper"].map((key) => [key, "assets"]),
  ...["fx_usdkrw", "fx_usdjpy", "fx_usdcny", "fx_eurusd", "fx_gbpusd",
    "treasury_2y", "yield_curve", "high_yield_spread", "financial_stress", "treasury_10y", "unemployment",
    "initial_claims", "fed_assets", "reserve_balances", "reverse_repo", "treasury_general_account",
    "m2", "retail_money_market_funds", "sofr", "effective_fed_funds", "reserve_interest",
    "dollar_index_broad", "dollar_index_afe", "dollar_index_eme",
    "kospi_exact", "kosdaq_exact", "samsung_exact", "sk_hynix_exact"].map((key) => [key, "macro"]),
]);

// One place decides why a card shows no number, so the summary tile and the
// detail card can never disagree about it.
function cardState(key, record, definition) {
  if (licenseRequired(record, definition)) return { kind: "licensed", badge: t("badge.licensed"), copy: t("license.copy") };
  if (pendingRights(record)) return { kind: "pending", badge: t("badge.pendingRights"), copy: t("pendingRights.copy") };
  if (record) return { kind: "ok", badge: null, copy: null };
  const lane = CARD_LANES.get(key);
  const code = lane ? disabledCode(lane) : null;
  if (!code) return { kind: "missing", badge: null, copy: null };
  const pending = code === "hip3_public_display_pending_rights";
  return {
    kind: pending ? "pending" : "disabled",
    badge: t(pending ? "badge.pendingRights" : "badge.disabled"),
    copy: t(DISABLED_CODES[code]),
  };
}

function sourceDollarScale(record) {
  const units = [record?.units?.long, record?.units?.short, record?.unit_long, record?.unit_short, record?.unit]
    .filter(Boolean).join(" ").toLowerCase();
  const isDollarUnit = /dollars?|\busd\b/.test(units);
  if (!isDollarUnit) return null;
  if (/\bbillions?\b/.test(units)) return "billions";
  if (/\bmillions?\b/.test(units)) return "millions";
  return null;
}

function scaleUsdValue(value, sourceScale) {
  if (!Number.isFinite(value) || !sourceScale) return null;
  const absolute = Math.abs(value);
  if (sourceScale === "billions") {
    return absolute >= 1000 ? { value: value / 1000, suffix: "T" } : { value, suffix: "B" };
  }
  if (sourceScale === "millions") {
    if (absolute >= 1e6) return { value: value / 1e6, suffix: "T" };
    if (absolute >= 1000) return { value: value / 1000, suffix: "B" };
    return { value, suffix: "M" };
  }
  return null;
}

function unitFor(record, definition) {
  if (sourceDollarScale(record)) return "";
  const hasRecordCurrency = Boolean(record && Object.prototype.hasOwnProperty.call(record, "currency"));
  return record?.units?.short || record?.unit_short || record?.unit || (hasRecordCurrency ? (record.currency || "") : (definition.currency || ""));
}

function formatNumber(value, definition, record, compact = false) {
  if (value === null) return "—";
  const format = definition.format;
  const locale = state.lang === "ko" ? "ko-KR" : "en-US";
  const scaledUsd = scaleUsdValue(value, sourceDollarScale(record));
  if (scaledUsd) {
    const shown = new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(scaledUsd.value);
    return `$${shown}${scaledUsd.suffix}`;
  }
  if (format === "currency") {
    const hasRecordCurrency = Boolean(record && Object.prototype.hasOwnProperty.call(record, "currency"));
    const currency = hasRecordCurrency ? record.currency : definition.currency;
    if (currency && ["USD", "KRW", "JPY", "EUR", "GBP"].includes(currency)) {
      return new Intl.NumberFormat(locale, { style: "currency", currency, currencyDisplay: "narrowSymbol", maximumFractionDigits: currency === "KRW" ? 0 : value < 10 ? 2 : 1 }).format(value);
    }
  }
  if (format === "percentPoints") return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 3 }).format(value)}%`;
  // Exchange rates are read at their conventional precision and never
  // abbreviated: 1,409.94 not "1.41천", and 1.1559 not "1.16".
  if (format === "rate") {
    const digits = Math.abs(value) >= 100 ? 2 : 4;
    return new Intl.NumberFormat(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
  }
  if (format === "compact" || (compact && Math.abs(value) >= 1000) || Math.abs(value) >= 1e6) return new Intl.NumberFormat(locale, { notation: "compact", maximumFractionDigits: 2 }).format(value);
  return new Intl.NumberFormat(locale, { maximumFractionDigits: Math.abs(value) < 10 ? 2 : 1 }).format(value);
}

function formatSigned(value, suffix = "%") {
  if (value === null) return "—";
  const shown = new Intl.NumberFormat(state.lang === "ko" ? "ko-KR" : "en-US", { maximumFractionDigits: 2 }).format(Math.abs(value));
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${shown}${suffix}`;
}

function changeClass(value) { return value > 0 ? "up" : value < 0 ? "down" : ""; }
function dateText(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? String(value) : new Intl.DateTimeFormat(state.lang === "ko" ? "ko-KR" : "en-US", { year: "numeric", month: "short", day: "numeric", hour: String(value).includes("T") ? "2-digit" : undefined, minute: String(value).includes("T") ? "2-digit" : undefined }).format(date);
}

function sourceInfo(record) {
  // Macro records carry a machine id in `provider` (`fred`, `nyfed`) plus a
  // display name in `provider_name`. Asset records predate that split and put
  // the readable name in `provider` itself ("Hyperliquid HIP-3") with the
  // instrument's publisher in `publisher`, so `provider` must stay ahead of
  // `publisher` here.
  const source = record?.source || {};
  return { name: source.provider_name || source.provider || source.publisher || record?.provider || "API", url: source.url || null };
}

function recordLabel(record, definition) {
  return localValue(record?.label, state.lang) || localValue(definition?.label, state.lang) || record?.symbol || record?.id || "—";
}

function isAssetDerivative(record) {
  const kind = String(record?.instrument_kind || "").toLowerCase();
  return record?._kind === "assets" && (kind.includes("perpetual") || kind.includes("synthetic") || kind.includes("proxy"));
}

// A HIP-3 deployment lists synthetics that reference an outside market; the
// main venue lists Hyperliquid's own contracts. Calling a real BTC perpetual
// "synthetic" would be as wrong as calling a synthetic one spot.
function derivativeBadgeKey(record) {
  return record?.source?.venue === "main" ? "badge.perpetual" : "badge.synthetic";
}

function localizedRightsNotice(record) {
  return String(localValue(record?.rights?.notice_localized, state.lang)
    || (state.lang === "ko" ? record?.rights?.notice_ko : record?.rights?.notice_en)
    || record?.rights?.notice || "").trim();
}

const pageSections = () => SECTIONS.filter((section) => onPage(section.zone));

function renderSkeleton() {
  const groups = $("#overview-groups");
  if (groups) groups.replaceChildren(...OVERVIEW.map((group) => {
    const section = document.createElement("section"); section.className = "overview-group";
    const heading = document.createElement("h3"); heading.textContent = localValue(group.label, state.lang); section.append(heading);
    const grid = document.createElement("div"); grid.className = "summary-grid";
    for (const key of group.keys) {
      const definition = METRICS[key];
      const card = document.createElement("article"); card.className = "summary-card"; card.dataset.metric = key; card.style.setProperty("--card-accent", definition.accent);
      card.innerHTML = `<div class="summary-label"></div><div class="summary-value">—</div><div class="summary-change"></div><div class="summary-meta"></div>`;
      $(".summary-label", card).textContent = localValue(definition.label, state.lang); grid.append(card);
    }
    section.append(grid); return section;
  }));

  const deep = $("#deep-sections");
  if (deep) {
    deep.replaceChildren();
    // A previous skeleton pass may have moved #korea-official out of the deep
    // container, where replaceChildren cannot reach it; a fresh copy is about to
    // be built, so the stray one must go first or the id would duplicate.
    document.getElementById("korea-official")?.remove();
    pageSections().forEach((section, index) => {
      const block = document.createElement("section"); block.className = "dashboard-section"; block.id = section.id;
      block.innerHTML = `<div class="section-heading"><span class="section-index">${String(index + 1).padStart(2, "0")}</span><div><p class="eyebrow">${section.eyebrow}</p><h2></h2></div></div><p class="section-copy"></p><div class="metric-grid"></div>`;
      $("h2", block).textContent = localValue(section.title, state.lang); $(".section-copy", block).textContent = localValue(section.copy, state.lang);
      const grid = $(".metric-grid", block);
      section.keys.forEach((key) => grid.append(makeMetricCard(key)));
      deep.append(block);
    });
    if (onPage("us")) {
      const compare = document.createElement("section"); compare.className = "dashboard-section"; compare.id = "liquidity-comparisons";
      compare.innerHTML = `<div class="section-heading"><span class="section-index">${String(pageSections().length + 1).padStart(2, "0")}</span><div><p class="eyebrow">DERIVED · REBASED SERIES</p><h2>${state.lang === "ko" ? "유동성 비교" : "Liquidity comparisons"}</h2></div></div><p class="section-copy">${t("chart.normalized")}</p><div class="comparison-grid"></div>`;
      COMPARISONS.forEach((item, index) => {
        const card = document.createElement("article"); card.className = "comparison-card lazy-comparison"; card.dataset.comparison = String(index);
        card.innerHTML = `<h3></h3><p></p><div class="comparison-chart state-block">${t("status.viewport")}</div><div class="comparison-legend"></div>`;
        $("h3", card).textContent = localValue(item.title, state.lang); $("p", card).textContent = localValue(item.copy, state.lang); $(".comparison-grid", compare).append(card);
      });
      deep.append(compare);
    }
    // The official-close cards belong in the Korea zone, between the 24-hour
    // references and the index-family table, not in the middle of the deep flow.
    const koreaOfficial = $("#korea-official"), krIndicesSection = $("#kr-indices");
    if (koreaOfficial && krIndicesSection) krIndicesSection.insertAdjacentElement("beforebegin", koreaOfficial);
  }
  renderJumpNav(); setupLazyCharts();
}

function makeMetricCard(key) {
  const card = $("#metric-card-template").content.firstElementChild.cloneNode(true); const definition = METRICS[key];
  card.dataset.metric = key; card.style.setProperty("--chart", definition.accent); card.style.setProperty("--chart-fill", `color-mix(in srgb, ${definition.accent} 12%, transparent)`);
  $(".metric-kicker", card).textContent = definition.aliases[0].toUpperCase(); $("h3", card).textContent = localValue(definition.label, state.lang);
  $(".chart-slot", card).innerHTML = `<div class="chart-empty">${t("status.viewport")}</div>`;
  return card;
}

// A card with no record is hidden only when its lane answered successfully:
// then the emptiness is a fact about the data (licence pending, product gone,
// series on hold), not an outage. During an endpoint failure nothing is hidden,
// so a broken fetch still looks broken instead of quietly shrinking the page.
function laneLoaded(key) {
  const lane = CARD_LANES.get(key);
  if (lane === "macro") return Boolean(state.macro);
  if (lane === "assets") return Boolean(state.assets);
  return false;
}

function pruneEmpty() {
  $$(".summary-card, .metric-card").forEach((card) => {
    const key = card.dataset.metric;
    // Definition-level licensed cards (Cboe's option gauges) cannot fill
    // without a contract no matter what any endpoint says, so they hide on the
    // same rule without needing a lane to have answered.
    const definition = METRICS[key] || {};
    card.hidden = !state.records.get(key)
      && (laneLoaded(key) || Boolean(definition.licensed) || Boolean(definition.reserved));
  });
  $$(".overview-group").forEach((group) => {
    group.hidden = $$(".summary-card", group).every((card) => card.hidden);
  });
  // #korea-official is relocated out of #deep-sections into the Korea zone,
  // so the selector must name it or an all-empty section would keep its header.
  $$("#deep-sections .dashboard-section, #korea-official").forEach((section) => {
    const cards = $$(".metric-card", section);
    if (cards.length) section.hidden = cards.every((card) => card.hidden);
  });
}

function renderJumpNav() {
  const nav = $("#jump-nav"); if (!nav) return; nav.replaceChildren();
  // Mirrors the page: Korea zone first, then the US & global flow. Numbering
  // must come from the same filtered list renderSkeleton used, or the nav and
  // the section headings would disagree on a split page.
  const sections = pageSections();
  const numbered = sections.map((section, index) => ({ id: section.id, text: `${String(index + 1).padStart(2, "0")} ${localValue(section.title, state.lang)}` }));
  [{ id: "kr-overnight", text: t("kro.title") },
    ...numbered.filter((item) => item.id === "korea-official"),
    { id: "kr-indices", text: t("kridx.title") },
    { id: "kr-etf", text: t("kre.title") },
    { id: "kr-pension", text: t("krp.title") },
    { id: "constituent-heatmap", text: t("tv.title") },
    { id: "us-ptr", text: t("ptr.title") },
    { id: "econ-calendar", text: t("cal.title") },
    ...numbered.filter((item) => item.id !== "korea-official"),
    { id: "liquidity-comparisons", text: `${String(sections.length + 1).padStart(2, "0")} ${state.lang === "ko" ? "유동성 비교" : "Comparisons"}` },
    { id: "sector-flow", text: t("sector.title") }, { id: "correlation", text: t("corr.title") }]
    // A split page carries only its own sections; links must not point at ids
    // that exist on a different page.
    .filter((item) => { const el = document.getElementById(item.id); return el && !el.hidden; })
    .forEach((item) => { const link = document.createElement("a"); link.href = `#${item.id}`; link.textContent = item.text; nav.append(link); });
}

function renderSummary() {
  $$(".summary-card").forEach((card) => {
    const key = card.dataset.metric; const definition = METRICS[key]; const record = state.records.get(key); const recent = latest(record); const dd = drawdownValue(record);
    const info = cardState(key, record, definition); const withheld = Boolean(info.badge);
    const useDd = !withheld && definition.preferDrawdown && dd !== null; const value = withheld ? null : useDd ? (Math.abs(dd) <= 1 ? dd * 100 : dd) : recent.value;
    $(".summary-label", card).textContent = recordLabel(record, definition);
    card.title = info.copy || localValue(record?.description, state.lang) || localValue(definition.description, state.lang) || "";
    card.classList.toggle("unavailable", !record || value === null);
    card.classList.toggle("stale", record?.freshness?.status === "stale");
    $(".summary-value", card).textContent = useDd ? formatSigned(value) : formatNumber(value, definition, record, true);
    const delta = change(record); const changeNode = $(".summary-change", card); changeNode.className = `summary-change ${withheld ? "" : changeClass(delta.percent)}`;
    changeNode.textContent = info.badge || (delta.percent === null ? (record ? t("change.previous") : t("status.unavailable")) : `${formatSigned(delta.percent)} · ${t("change.previous")}`);
    const meta = $(".summary-meta", card); const metaParts = [];
    if (record?.freshness?.status === "stale") metaParts.push(t("badge.stale"));
    if (record?._restrictedSeries) metaParts.push(t("badge.proxyAlternative"));
    if (isAssetDerivative(record)) metaParts.push(t(derivativeBadgeKey(record)));
    if (record) metaParts.push(sourceInfo(record).name, `${t("date.asof")} ${dateText(recent.date)}`);
    meta.textContent = info.badge || (metaParts.length ? metaParts.join(" · ") : t("badge.missing"));
  });
}

function renderMetricCards() {
  $$(".metric-card").forEach((card) => {
    const key = card.dataset.metric; const definition = METRICS[key]; const record = state.records.get(key); const recent = latest(record); const delta = change(record);
    card.classList.toggle("unavailable", !record || recent.value === null);
    $("h3", card).textContent = recordLabel(record, definition);
    $(".metric-kicker", card).textContent = String(record?.display_symbol || record?.symbol || record?.id || definition.aliases[0]).toUpperCase();
    const badges = $(".badge-row", card); badges.replaceChildren();
    const badge = document.createElement("span");
    const freshness = record?.freshness?.status;
    const info = cardState(key, record, definition); const withheld = Boolean(info.badge);
    badge.className = `status-badge ${withheld ? "warn" : freshness === "stale" ? "stale" : record ? "fresh" : "error"}`;
    badge.textContent = info.badge || (record ? t(freshness === "stale" ? "badge.stale" : "badge.fresh") : t("badge.missing")); badges.append(badge);
    if (isAssetDerivative(record)) { const instrument = document.createElement("span"); instrument.className = "status-badge info"; instrument.textContent = t(derivativeBadgeKey(record)); instrument.title = String(record.instrument_kind || ""); badges.append(instrument); }
    if (record?._restrictedSeries) { const alternative = document.createElement("span"); alternative.className = "status-badge warn"; alternative.textContent = t("badge.proxyAlternative"); alternative.title = `${recordLabel(record._restrictedSeries, definition)} · ${t("badge.licensed")}`; badges.append(alternative); }
    const rightsNotice = localizedRightsNotice(record);
    if (record?.rights?.copyrighted || rightsNotice) { const rights = document.createElement("span"); rights.className = "status-badge warn"; rights.textContent = t(record?.rights?.copyrighted ? "badge.rights" : "badge.sourceTerms"); rights.title = rightsNotice; badges.append(rights); }
    $(".metric-primary strong", card).textContent = formatNumber(withheld ? null : recent.value, definition, record);
    $(".metric-unit", card).textContent = withheld ? "" : unitFor(record, definition);
    const changeNode = $(".metric-change", card); changeNode.className = `metric-change ${withheld ? "" : changeClass(delta.percent)}`;
    changeNode.textContent = withheld || delta.percent === null ? "—" : `${formatSigned(delta.percent)} · ${t("change.previous")}`;
    const insight = INSIGHTS[key];
    $(".metric-description", card).textContent = info.copy || localValue(record?.description, state.lang) || localValue(definition.description, state.lang) || localValue(insight?.description, state.lang) || t("status.unavailable");
    const hints = $(".metric-hints", card); hints.replaceChildren(); hints.setAttribute("aria-label", state.lang === "ko" ? "해석 참고" : "Interpretation guide");
    (insight?.hints || []).forEach((hint) => { const chip = document.createElement("span"); chip.className = "hint-chip"; chip.textContent = localValue(hint, state.lang); hints.append(chip); });
    const footer = $("footer", card); footer.replaceChildren(); const source = sourceInfo(record);
    const provider = source.url ? document.createElement("a") : document.createElement("span"); provider.textContent = source.name; if (source.url) { provider.href = source.url; provider.target = "_blank"; provider.rel = "noopener noreferrer"; }
    footer.append(provider, document.createTextNode(` · ${record?.instrument_kind || record?._kind || "API"} · ${t("date.asof")} ${dateText(recent.date)}`));
    if (card.dataset.visible === "1") renderMetricChart(card);
  });
}

function createSvg(tag, attrs = {}) { const node = document.createElementNS("http://www.w3.org/2000/svg", tag); Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value)); return node; }
function lineChart(series, color = null, normalize = false) {
  const points = series.filter((point) => point.value !== null); if (points.length < 2) return null;
  const values = normalize ? points.map((point) => ({ ...point, value: point.value / points[0].value * 100 })) : points;
  if (!values.every((point) => Number.isFinite(point.value))) return null;
  const width = 600, height = 160, pad = 10; let min = Math.min(...values.map((p) => p.value)); let max = Math.max(...values.map((p) => p.value));
  if (min === max) { min -= Math.abs(min || 1) * .01; max += Math.abs(max || 1) * .01; }
  const x = (index) => pad + index / Math.max(1, values.length - 1) * (width - pad * 2); const y = (value) => pad + (max - value) / (max - min) * (height - pad * 2);
  const svg = createSvg("svg", { viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: "none" });
  [0.25, .5, .75].forEach((ratio) => svg.append(createSvg("line", { x1: 0, x2: width, y1: height * ratio, y2: height * ratio, class: "grid" })));
  if (min < 0 && max > 0) svg.append(createSvg("line", { x1: 0, x2: width, y1: y(0), y2: y(0), class: "zero" }));
  const coords = values.map((point, index) => `${x(index)},${y(point.value)}`).join(" ");
  const area = createSvg("polygon", { points: `${pad},${height - pad} ${coords} ${width - pad},${height - pad}`, class: "area" });
  const line = createSvg("polyline", { points: coords, class: "line" }); if (color) line.style.stroke = color;
  const dot = createSvg("circle", { cx: x(values.length - 1), cy: y(values.at(-1).value), r: 3.5, class: "dot" }); if (color) dot.style.fill = color;
  svg.append(area, line, dot); return svg;
}

function renderMetricChart(card) {
  const key = card.dataset.metric; const slot = $(".chart-slot", card); const record = state.records.get(key); const definition = METRICS[key];
  const info = cardState(key, record, definition); slot.replaceChildren();
  if (info.badge) { const empty = document.createElement("div"); empty.className = "chart-empty"; empty.textContent = info.badge; slot.append(empty); return; }
  const chart = lineChart(observations(record));
  if (chart) slot.append(chart); else { const empty = document.createElement("div"); empty.className = "chart-empty"; empty.textContent = t("status.noSeries"); slot.append(empty); }
}

function setupLazyCharts() {
  const observer = new IntersectionObserver((entries) => entries.forEach((entry) => {
    if (!entry.isIntersecting) return; const card = entry.target; card.dataset.visible = "1";
    if (card.classList.contains("metric-card")) renderMetricChart(card); else renderComparison(Number(card.dataset.comparison)); observer.unobserve(card);
  }), { rootMargin: "220px 0px" });
  $$(".metric-card, .lazy-comparison").forEach((card) => observer.observe(card));
}

function renderComparison(index) {
  const card = $$(`.lazy-comparison`)[index]; if (!card) return; const definition = COMPARISONS[index]; const chartHost = $(".comparison-chart", card); const legend = $(".comparison-legend", card);
  const records = definition.keys.map((key) => state.records.get(key)); const series = records.map(observations);
  if (series.some((items) => items.length < 2)) { chartHost.className = "comparison-chart state-block"; chartHost.textContent = t("status.unavailable"); legend.replaceChildren(); return; }
  chartHost.className = "comparison-chart chart-slot"; chartHost.replaceChildren(); const colors = ["var(--accent)", "var(--violet)"];
  series.forEach((items, idx) => { const svg = lineChart(items, colors[idx], true); if (svg) { svg.style.position = idx ? "absolute" : "relative"; svg.style.inset = "0"; chartHost.style.position = "relative"; chartHost.append(svg); } });
  legend.replaceChildren(...definition.keys.map((key) => { const span = document.createElement("span"); span.innerHTML = "<i></i>"; span.append(document.createTextNode(localValue(METRICS[key].label, state.lang))); return span; }));
}

function renderAttribution() {
  const host = $("#attribution"); if (!host) return; host.replaceChildren(); const attr = state.macro?.attribution;
  // Each serving lane states its own required notice and term links. Hardcoding
  // one provider's name here would credit it for another's data.
  const providers = Array.isArray(attr?.providers) && attr.providers.length
    ? attr.providers
    : (attr?.notice ? [{ name: attr.name || "", ...attr }] : []);
  for (const entry of providers) {
    if (entry.notice) { const notice = document.createElement("p"); notice.textContent = entry.notice; host.append(notice); }
    [[entry.terms_url, "Terms"], [entry.api_terms_url, "API Terms"]].forEach(([url, suffix]) => {
      if (!url) return;
      const link = document.createElement("a"); link.href = url; link.target = "_blank"; link.rel = "noopener noreferrer";
      link.textContent = entry.name ? `${entry.name} ${suffix}` : suffix;
      host.append(link, document.createTextNode(" "));
    });
    if (entry.user_terms) { const termsNotice = document.createElement("p"); termsNotice.textContent = entry.user_terms; host.append(termsNotice); }
  }
  const notices = new Set([
    localValue(state.assets?.rights?.notice_localized, state.lang) || state.assets?.rights?.notice,
    localValue(state.assets?.attribution?.notice_localized, state.lang) || state.assets?.attribution?.notice,
    ...[...state.records.values()].map(localizedRightsNotice),
    ...[...state.restricted.values()].map(localizedRightsNotice),
    // Publisher-prescribed citations (e.g. STLFSI4) ship with the series and
    // must appear wherever the values do, retrieval date included.
    ...[...state.records.values()].map((record) => record?.rights?.citation),
  ].map((value) => String(value || "").trim()).filter(Boolean));
  if (notices.size) {
    const title = document.createElement("p"); title.textContent = t("notice.market"); host.append(title);
    const list = document.createElement("ul"); notices.forEach((value) => { const item = document.createElement("li"); item.textContent = value; list.append(item); }); host.append(list);
  }
  // Say out loud which lanes are switched off. Otherwise a page full of blank
  // cards looks like a broken site rather than a deliberate rights decision.
  const laneReasons = [...new Set(["macro", "assets", "weekend", "sectors", "correlation", "stress"]
    .map(disabledText).filter(Boolean))];
  if (laneReasons.length) {
    const title = document.createElement("p"); title.textContent = t("notice.disabledLanes"); host.append(title);
    const list = document.createElement("ul"); laneReasons.forEach((value) => { const item = document.createElement("li"); item.textContent = value; list.append(item); }); host.append(list);
  }
  host.hidden = !host.childNodes.length;
}

async function fetchJson(url, key) {
  try {
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    let payload = null;
    try { payload = await response.json(); } catch (_) { payload = null; }
    if (!response.ok) {
      const detail = payload?.detail;
      state.errors[key] = {
        status: response.status,
        code: detail?.code || payload?.code || null,
        message: detail?.message || (typeof detail === "string" ? detail : null) || `HTTP ${response.status}`,
      };
      return null;
    }
    state.errors[key] = null;
    return payload;
  } catch (error) {
    state.errors[key] = { status: null, code: null, message: error?.message || String(error) };
    return null;
  }
}

function errorCode(key) { return state.errors[key]?.code || state.errors[key]?.detail?.code || null; }
function disabledCode(key) { const code = errorCode(key); return code && DISABLED_CODES[code] ? code : null; }
function disabledText(key) { const code = disabledCode(key); return code ? t(DISABLED_CODES[code]) : null; }

function endpointHealth(key) {
  if (disabledCode(key)) return "disabled";
  const payload = state[key];
  if (!payload) return "missing";
  let usable = [];
  if (key === "macro") {
    usable = (Array.isArray(payload.series) ? payload.series : []).filter((record) => !licenseRequired(record) && !pendingRights(record) && latest(record).value !== null);
  } else if (key === "assets") {
    usable = (Array.isArray(payload.assets) ? payload.assets : []).filter((record) => latest(record).value !== null);
  } else if (key === "weekend") {
    usable = (Array.isArray(payload.signals) ? payload.signals : []).filter((record) => safeNumber(record?.mark ?? record?.oracle) !== null);
  } else if (key === "krOvernight") {
    usable = (Array.isArray(payload.cards) ? payload.cards : []).filter((record) => safeNumber(record?.perp?.mark) !== null);
  } else if (key === "sectors") {
    usable = (Array.isArray(payload.sectors) ? payload.sectors : []).filter((record) => Object.values(record?.returns || {}).some((value) => safeNumber(value) !== null));
  }
  if (!usable.length) return "missing";
  const staleCount = usable.filter((record) => record?.stale === true || record?.freshness?.status === "stale" || record?.status === "stale").length;
  return staleCount === usable.length ? "stale" : "usable";
}

// Which pages need which endpoint. A lane a page never shows is never fetched
// there; its state stays null and its renderers no-op on the missing markup.
const PAGE_FETCHES = {
  macro: ["landing", "kr", "us"],
  assets: ["landing", "us"],
  sectors: ["us"],
  weekend: ["kr"],
  stress: ["landing", "us"],
  krIndices: ["kr"],
  krOvernight: ["landing", "kr"],
  krPension: ["kr"],
  krEtf: ["kr"],
  usPtr: ["us"],
  calendar: ["us"],
};

async function loadCore() {
  $("#refresh-button")?.setAttribute("aria-busy", "true");
  state.records.clear(); state.restricted.clear();
  const request = (url, key) => onPage(...PAGE_FETCHES[key]) ? fetchJson(url, key) : Promise.resolve(null);
  const [macro, assets, sectors, weekend, stress, krIndices, krOvernight, krPension, krEtf, usPtr, calendar] = await Promise.all([
    request("/api/market/macro?history=3y", "macro"), request("/api/market/assets?history=3y", "assets"),
    request("/api/market/sectors", "sectors"), request("/api/market/weekend", "weekend"),
    request("/api/market/stress", "stress"), request("/api/kr/indices", "krIndices"),
    request("/api/kr/overnight", "krOvernight"), request("/api/kr/pension", "krPension"),
    request("/api/kr/etf", "krEtf"), request("/api/us/ptr", "usPtr"),
    request("/api/calendar", "calendar"),
  ]);
  state.macro = macro; state.assets = assets; state.sectors = sectors; state.weekend = weekend;
  state.stress = stress; state.krIndices = krIndices; state.krOvernight = krOvernight; state.krPension = krPension;
  state.krEtf = krEtf; state.usPtr = usPtr; state.calendar = calendar;
  ingestPayload(macro, "macro"); ingestPayload(assets, "assets");
  renderAll(); $("#refresh-button")?.removeAttribute("aria-busy");
}

function renderAll() {
  renderSummary(); renderMetricCards(); renderAttribution(); renderSectors(); renderWeekend(); renderStressIndex(); renderKrIndices(); renderKrOvernight(); renderKrPension(); renderKrEtf(); renderUsPtr(); renderCalendar();
  renderMastTicker(); renderZonePreviews(); updateSessionBadge();
  // The sector monitor and the correlation matrix live on the quarantined
  // legacy price lane. When the deployment has that lane switched off they are
  // not failing — they are absent by decision, so they are hidden rather than
  // left showing a retry prompt for something a retry cannot fix.
  const legacyOff = errorCode("sectors") === "legacy_price_data_disabled";
  const sectorSection = $("#sector-flow"), corrSection = $("#correlation");
  if (sectorSection) sectorSection.hidden = legacyOff;
  if (corrSection) corrSection.hidden = legacyOff;
  if (legacyOff) state.correlationLoaded = true; // the lazy loader must not fetch it
  pruneEmpty(); renderJumpNav();
  $$(".lazy-comparison[data-visible='1']").forEach((card) => renderComparison(Number(card.dataset.comparison)));
  const times = [state.macro?.generated_at, state.assets?.generated_at, state.sectors?.generated_at, state.sectors?.as_of, state.weekend?.generated_at].filter(Boolean);
  $("#updated-at").textContent = times.length ? dateText(times.sort().at(-1)) : "—";
  // A deliberately disabled lane is absence by decision, not degraded service.
  // It leaves the health calculation entirely: with the legacy price lane off,
  // the badge would otherwise read "partial data" forever on a healthy site.
  const health = ["macro", "assets", "sectors", "weekend", "krOvernight"]
    // A lane this page never fetches must not read as an outage here.
    .filter((key) => onPage(...PAGE_FETCHES[key]))
    .map(endpointHealth).filter((item) => item !== "disabled");
  const badge = $("#connection-badge");
  const count = (value) => health.filter((item) => item === value).length;
  const usable = count("usable"); const stale = count("stale");
  const key = !health.length ? "status.disabled"
    : usable === health.length ? "status.live"
    : usable || stale ? (usable ? "status.partial" : "status.staleData")
    : "status.offline";
  badge.className = `connection-badge ${key === "status.live" ? "ok" : key === "status.staleData" ? "stale" : key === "status.offline" ? "error" : ""}`;
  $("span", badge).textContent = t(key);
  const overviewSource = $("#overview-source");
  if (overviewSource) overviewSource.textContent = [state.assets?.provider?.name || state.assets?.provider?.id, state.macro?.provider?.name || state.macro?.provider?.id].filter(Boolean).join(" + ") || "API";
}

function formatKrw(value) {
  if (value == null || !isFinite(value)) return "—";
  if (Math.abs(value) >= 1e12) return `${(value / 1e12).toFixed(1)}조`;
  if (Math.abs(value) >= 1e8) return `${Math.round(value / 1e8).toLocaleString()}억`;
  return Math.round(value).toLocaleString();
}

function renderKrIndices() {
  const section = $("#kr-indices");
  if (!section) return;
  const payload = state.krIndices;
  if (!payload || !Array.isArray(payload.groups)) { section.hidden = true; return; }
  const rows = payload.groups.flatMap((group) => group.rows || []);
  if (!rows.length) { section.hidden = true; return; }
  section.hidden = false;

  const body = $("#kridx-body");
  body.replaceChildren();
  const signed = (value, digits = 2) => value == null ? "—" : `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
  const signClass = (value) => value == null ? "" : value > 0 ? "up" : value < 0 ? "down" : "";
  for (const group of payload.groups) {
    if (!(group.rows || []).length) continue;
    const heading = document.createElement("h3");
    heading.className = "kridx-group";
    heading.textContent = localValue(group.label, state.lang);
    body.append(heading);
    const scroll = document.createElement("div"); scroll.className = "table-scroll";
    const table = document.createElement("table"); table.className = "accessible-table kridx-table";
    table.innerHTML = `<thead><tr>
      <th scope="col">${t("kridx.colName")}</th><th scope="col" class="num">${t("kridx.colClose")}</th>
      <th scope="col" class="num">${t("kridx.colDay")}</th><th scope="col" class="num">${t("kridx.colYtd")}</th>
      <th scope="col" class="num">${t("kridx.colRange")}</th><th scope="col" class="num">${t("kridx.colValue")}</th>
    </tr></thead>`;
    const tbody = document.createElement("tbody");
    for (const row of group.rows) {
      const tr = document.createElement("tr");
      const cells = [
        ["", row.name],
        ["num", row.close == null ? "—" : row.close.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })],
        [`num ${signClass(row.change_percent)}`, signed(row.change_percent)],
        [`num ${signClass(row.ytd_percent)}`, signed(row.ytd_percent, 1)],
        ["num range", row.low_52w == null ? "—" : `${row.low_52w.toLocaleString()} ~ ${row.high_52w?.toLocaleString?.() ?? "—"}`],
        ["num", formatKrw(row.value)],
      ];
      for (const [cls, text] of cells) {
        const td = document.createElement("td");
        if (cls) td.className = cls;
        td.textContent = text;
        tr.append(td);
      }
      tbody.append(tr);
    }
    table.append(tbody); scroll.append(table); body.append(scroll);
  }
  const source = payload.source || {};
  $("#kridx-footer").replaceChildren();
  const link = document.createElement("a");
  link.href = source.url || "#"; link.target = "_blank"; link.rel = "noopener noreferrer";
  link.textContent = source.provider_name || "금융위원회";
  const note = document.createElement("span");
  note.textContent = `${t("kridx.asof", { date: dateText(payload.as_of) })}`;
  $("#kridx-footer").append(link, note);
}

// DART fields carry a closed Korean vocabulary; EN gets a fixed mapping with a
// verbatim fallback, same as the insider panel on /analytics.
const KRP_REASON_EN = {
  "단순추가취득/처분": "Simple acquisition/disposal",
  "단순추가취득": "Simple additional acquisition",
  "단순처분": "Simple disposal",
  "단순취득": "Simple acquisition",
  "신규보고": "New report",
  "1%이상변동": "Change of 1% or more",
  "1% 이상 변동": "Change of 1% or more",
  "단순투자목적에서 일반투자목적으로 보유목적 변경":
    "Purpose changed from simple to general investment",
};

function renderKrPension() {
  const section = $("#kr-pension");
  if (!section) return;
  const payload = state.krPension;
  const filings = Array.isArray(payload?.filings) ? payload.filings : [];
  // Batch-fed lane: no payload means the lane is off or not collected yet.
  // Either way the section stays hidden, like the index-family table.
  if (!filings.length) { section.hidden = true; return; }
  section.hidden = false;

  const body = $("#krp-body");
  body.replaceChildren();
  const scroll = document.createElement("div"); scroll.className = "table-scroll";
  const table = document.createElement("table"); table.className = "accessible-table kridx-table";
  table.innerHTML = `<thead><tr>
    <th scope="col">${t("krp.colDate")}</th><th scope="col">${t("krp.colCompany")}</th>
    <th scope="col" class="num">${t("krp.colRatio")}</th><th scope="col" class="num">${t("krp.colChange")}</th>
    <th scope="col" class="num">${t("krp.colShares")}</th><th scope="col">${t("krp.colReason")}</th>
  </tr></thead>`;
  const tbody = document.createElement("tbody");
  const signClass = (value) => value == null ? "" : value > 0 ? "up" : value < 0 ? "down" : "";
  for (const filing of filings) {
    const tr = document.createElement("tr");
    const dateTd = document.createElement("td");
    dateTd.textContent = kroDate(filing.report_date);
    const companyTd = document.createElement("td"); companyTd.className = "krp-company";
    const link = document.createElement("a");
    link.href = filing.report_url; link.target = "_blank"; link.rel = "noopener noreferrer";
    link.textContent = filing.company || "—";
    companyTd.append(link);
    if (filing.market) {
      const chip = document.createElement("small"); chip.className = "krp-market";
      chip.textContent = localValue(filing.market, state.lang);
      companyTd.append(chip);
    }
    const ratio = safeNumber(filing.ratio); const ratioChange = safeNumber(filing.ratio_change);
    const shares = safeNumber(filing.shares);
    const ratioTd = document.createElement("td"); ratioTd.className = "num";
    ratioTd.textContent = ratio === null ? "—" : `${ratio.toFixed(2)}%`;
    const changeTd = document.createElement("td"); changeTd.className = `num ${signClass(ratioChange)}`;
    changeTd.textContent = ratioChange === null ? "—" : `${ratioChange > 0 ? "+" : ""}${ratioChange.toFixed(2)}%p`;
    const sharesTd = document.createElement("td"); sharesTd.className = "num";
    sharesTd.textContent = shares === null ? "—" : shares.toLocaleString("en-US");
    const reasonTd = document.createElement("td");
    const reason = filing.reason || "";
    reasonTd.textContent = reason
      ? (state.lang === "en" ? (KRP_REASON_EN[reason] || reason) : reason)
      : (filing.detail_status === "unavailable" ? t("krp.detailPending") : "—");
    tr.append(dateTd, companyTd, ratioTd, changeTd, sharesTd, reasonTd);
    tbody.append(tr);
  }
  table.append(tbody); scroll.append(table); body.append(scroll);

  const footer = $("#krp-footer");
  footer.replaceChildren();
  const source = payload.source || {};
  const link = document.createElement("a");
  link.href = source.url || "#"; link.target = "_blank"; link.rel = "noopener noreferrer";
  link.textContent = source.provider_name || "금융감독원";
  const note = document.createElement("span");
  note.textContent = t("krp.window", {
    days: String(payload.window?.days ?? "—"),
    total: String(payload.total_in_window ?? filings.length),
    count: String(filings.length),
  });
  const basis = document.createElement("span");
  basis.textContent = state.lang === "ko" ? (payload.basis_ko || "") : (payload.basis_en || "");
  footer.append(link, note, basis);
}

function renderKrEtf() {
  const section = $("#kr-etf");
  if (!section) return;
  const payload = state.krEtf;
  const rows = Array.isArray(payload?.rows) ? payload.rows : [];
  if (!rows.length) { section.hidden = true; return; }
  section.hidden = false;

  const body = $("#kre-body");
  body.replaceChildren();
  const scroll = document.createElement("div"); scroll.className = "table-scroll";
  const table = document.createElement("table"); table.className = "accessible-table kridx-table";
  table.innerHTML = `<thead><tr>
    <th scope="col">${t("kre.colName")}</th><th scope="col" class="num">${t("kre.colClose")}</th>
    <th scope="col" class="num">${t("kre.colDay")}</th><th scope="col" class="num">${t("kre.colNav")}</th>
    <th scope="col" class="num">${t("kre.colPremium")}</th><th scope="col">${t("kre.colIndex")}</th>
    <th scope="col" class="num">${t("kre.colValue")}</th>
  </tr></thead>`;
  const tbody = document.createElement("tbody");
  const signClass = (value) => value == null ? "" : value > 0 ? "up" : value < 0 ? "down" : "";
  const signed = (value, suffix = "%") => value == null ? "—" : `${value > 0 ? "+" : ""}${value.toFixed(2)}${suffix}`;
  for (const fund of rows) {
    const tr = document.createElement("tr");
    const close = safeNumber(fund.close), nav = safeNumber(fund.nav);
    const dayPercent = safeNumber(fund.change_percent), premium = safeNumber(fund.premium_percent);
    const nameTd = document.createElement("td"); nameTd.className = "krp-company";
    const name = document.createElement("span"); name.textContent = fund.name || "—";
    const code = document.createElement("small"); code.className = "krp-market"; code.textContent = fund.code || "";
    nameTd.append(name, code);
    const cells = [
      ["num", close === null ? "—" : Math.round(close).toLocaleString("en-US")],
      [`num ${signClass(dayPercent)}`, signed(dayPercent)],
      ["num", nav === null ? "—" : nav.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })],
      [`num ${signClass(premium)}`, signed(premium)],
      ["range", fund.index_name || "—"],
      ["num", formatKrw(safeNumber(fund.value))],
    ];
    tr.append(nameTd);
    for (const [cls, text] of cells) {
      const td = document.createElement("td");
      if (cls) td.className = cls;
      td.textContent = text;
      tr.append(td);
    }
    tbody.append(tr);
  }
  table.append(tbody); scroll.append(table); body.append(scroll);

  const footer = $("#kre-footer");
  footer.replaceChildren();
  const source = payload.source || {};
  const link = document.createElement("a");
  link.href = source.url || "#"; link.target = "_blank"; link.rel = "noopener noreferrer";
  link.textContent = source.provider_name || "금융위원회";
  const window_ = document.createElement("span");
  window_.textContent = t("kre.window", {
    total: String(payload.total_listed ?? rows.length), count: String(rows.length),
  });
  const asof = document.createElement("span");
  asof.textContent = t("kre.asof", { date: dateText(payload.as_of) });
  const note = document.createElement("span");
  note.textContent = localValue(payload.premium_note, state.lang);
  footer.append(link, window_, asof, note);
}

// P2: 헤더 상태줄 — 세션 배지(시계 기준, 휴장일 미반영을 툴팁에 명시)와
// H.10 공식 환율 미니 티커, 랜딩 존 카드의 라이브 미니 프리뷰.
function krSessionInfo(now = new Date()) {
  const kst = new Date(now.getTime() + (now.getTimezoneOffset() + 540) * 60000);
  const day = kst.getDay(), minutes = kst.getHours() * 60 + kst.getMinutes();
  const OPEN = 9 * 60, CLOSE = 15 * 60 + 30;
  if (day >= 1 && day <= 5 && minutes >= OPEN && minutes < CLOSE) return { open: true, minutesToOpen: 0 };
  let wait = 0, probeDay = day, probeMinutes = minutes;
  if (!(day >= 1 && day <= 5 && minutes < OPEN)) {
    wait += 24 * 60 - probeMinutes; probeDay = (probeDay + 1) % 7; probeMinutes = 0;
    while (probeDay === 0 || probeDay === 6) { wait += 24 * 60; probeDay = (probeDay + 1) % 7; }
  }
  wait += OPEN - probeMinutes;
  return { open: false, minutesToOpen: wait };
}

function updateSessionBadge() {
  const badge = $("#session-badge");
  if (!badge) return;
  const info = krSessionInfo();
  badge.hidden = false;
  badge.classList.toggle("open", info.open);
  badge.title = t("session.note");
  const label = $("span", badge);
  if (info.open) { label.textContent = t("session.open"); return; }
  const h = Math.floor(info.minutesToOpen / 60), m = info.minutesToOpen % 60;
  label.textContent = `${t("session.closed")} · ${t("session.until", { time: t("session.hm", { h: String(h), m: String(m) }) })}`;
}

function renderMastTicker() {
  const node = $("#mast-ticker");
  if (!node) return;
  const record = state.records.get("fx_usdkrw");
  const recent = latest(record);
  if (!record || recent.value === null) { node.hidden = true; return; }
  node.hidden = false;
  node.title = t("ticker.note");
  const date = document.createElement("small");
  date.textContent = `H.10 ${kroDate(recent.date)}`;
  node.replaceChildren(
    document.createTextNode(`USD/KRW ${recent.value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`),
    date,
  );
}

function renderZonePreviews() {
  const krMini = $("#zone-kr-mini"), usMini = $("#zone-us-mini");
  if (!krMini && !usMini) return;
  const entry = (labelText, valueText, percent) => {
    const wrap = document.createElement("span");
    const label = document.createElement("small"); label.textContent = labelText;
    wrap.append(label, document.createTextNode(` ${valueText}`));
    if (percent !== null) {
      const delta = document.createElement("em");
      delta.className = changeClass(percent);
      delta.textContent = ` ${formatSigned(percent)}`;
      wrap.append(delta);
    }
    return wrap;
  };
  if (krMini) {
    const kospi = state.records.get("kospi_exact");
    const recent = latest(kospi), delta = change(kospi);
    krMini.hidden = !kospi || recent.value === null;
    if (!krMini.hidden) {
      krMini.replaceChildren(entry(
        t("landing.krMini.kospi"),
        recent.value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
        delta.percent,
      ));
    }
  }
  if (usMini) {
    const parts = [];
    const sp = state.records.get("sp500");
    const spRecent = latest(sp), spDelta = change(sp);
    if (sp && spRecent.value !== null) {
      parts.push(entry(t("landing.usMini.sp500"),
        spRecent.value.toLocaleString("en-US", { maximumFractionDigits: 1 }), spDelta.percent));
    }
    const stressScore = safeNumber(state.stress?.score);
    if (stressScore !== null) {
      parts.push(entry(t("landing.usMini.stress"),
        `${stressScore.toFixed(1)} · ${localValue(state.stress?.band, state.lang)}`, null));
    }
    usMini.hidden = !parts.length;
    if (parts.length) usMini.replaceChildren(...parts);
  }
}

const PTR_TYPE_KEYS = { "P": "ptr.typeP", "S": "ptr.typeS", "S (partial)": "ptr.typeSP", "E": "ptr.typeE" };
const PTR_OWNER_KEYS = { SP: "ptr.ownerSP", JT: "ptr.ownerJT", DC: "ptr.ownerDC" };
const PTR_MAX_ROWS = 30;

function renderUsPtr() {
  const section = $("#us-ptr");
  if (!section) return;
  const payload = state.usPtr;
  const filings = Array.isArray(payload?.filings) ? payload.filings : [];
  if (!filings.length) { section.hidden = true; return; }
  section.hidden = false;

  const transactions = [];
  const scanned = [], pending = [], partial = [];
  for (const filing of filings) {
    if (filing.detail_status === "unavailable") scanned.push(filing);
    if (filing.detail_status === "pending") pending.push(filing);
    if (filing.detail_status === "partial") partial.push(filing);
    for (const tx of filing.transactions || []) transactions.push({ filing, tx });
  }
  transactions.sort((a, b) => String(b.tx.date || b.filing.filed_date).localeCompare(String(a.tx.date || a.filing.filed_date)));
  const shown = transactions.slice(0, PTR_MAX_ROWS);

  const body = $("#ptr-body");
  body.replaceChildren();
  const scroll = document.createElement("div"); scroll.className = "table-scroll";
  const table = document.createElement("table"); table.className = "accessible-table kridx-table";
  table.innerHTML = `<thead><tr>
    <th scope="col">${t("ptr.colDate")}</th><th scope="col">${t("ptr.colMember")}</th>
    <th scope="col">${t("ptr.colAsset")}</th><th scope="col">${t("ptr.colType")}</th>
    <th scope="col" class="num">${t("ptr.colAmount")}</th><th scope="col">${t("ptr.colFiled")}</th>
  </tr></thead>`;
  const tbody = document.createElement("tbody");
  for (const { filing, tx } of shown) {
    const tr = document.createElement("tr");
    const dateTd = document.createElement("td"); dateTd.textContent = dateText(tx.date);
    const memberTd = document.createElement("td"); memberTd.className = "krp-company";
    const link = document.createElement("a");
    link.href = filing.pdf_url; link.target = "_blank"; link.rel = "noopener noreferrer";
    link.textContent = filing.name || "—";
    const district = document.createElement("small"); district.className = "krp-market";
    district.textContent = filing.state_district || "";
    memberTd.append(link, district);
    const assetTd = document.createElement("td");
    const assetName = document.createElement("span"); assetName.textContent = tx.asset || "—";
    assetTd.append(assetName);
    if (tx.ticker) { const chip = document.createElement("small"); chip.className = "krp-market"; chip.textContent = tx.ticker; assetTd.append(chip); }
    if (tx.owner && PTR_OWNER_KEYS[tx.owner]) { const owner = document.createElement("small"); owner.className = "krp-market"; owner.textContent = t(PTR_OWNER_KEYS[tx.owner]); assetTd.append(owner); }
    const typeTd = document.createElement("td");
    const typeClass = tx.type === "P" ? "up" : tx.type === "E" ? "" : "down";
    if (typeClass) typeTd.className = typeClass;
    typeTd.textContent = PTR_TYPE_KEYS[tx.type] ? t(PTR_TYPE_KEYS[tx.type]) : (tx.type || "—");
    const amountTd = document.createElement("td"); amountTd.className = "num";
    amountTd.textContent = tx.amount || "—";
    const filedTd = document.createElement("td"); filedTd.textContent = dateText(tx.notification_date || filing.filed_date);
    tr.append(dateTd, memberTd, assetTd, typeTd, amountTd, filedTd);
    tbody.append(tr);
  }
  table.append(tbody); scroll.append(table); body.append(scroll);

  // 수기·스캔 제출분은 거래 표에 실을 수 없다 — 그 사실과 원문 링크를 그대로 보여준다.
  if (scanned.length) {
    const note = document.createElement("p"); note.className = "interpretation-note";
    note.append(document.createTextNode(`${t("ptr.scanned", { count: String(scanned.length) })} `));
    scanned.slice(0, 5).forEach((filing, index) => {
      if (index) note.append(document.createTextNode(" · "));
      const a = document.createElement("a");
      a.href = filing.pdf_url; a.target = "_blank"; a.rel = "noopener noreferrer";
      a.textContent = `${filing.name} (${dateText(filing.filed_date)})`;
      note.append(a);
    });
    body.append(note);
  }

  const footer = $("#ptr-footer");
  footer.replaceChildren();
  const source = payload.source || {};
  const sourceLink = document.createElement("a");
  sourceLink.href = source.url || "#"; sourceLink.target = "_blank"; sourceLink.rel = "noopener noreferrer";
  sourceLink.textContent = source.provider_name || "House Clerk";
  const windowNote = document.createElement("span");
  windowNote.textContent = t("ptr.window", {
    days: String(payload.window?.days ?? "—"),
    total: String(payload.total_in_window ?? filings.length),
    tx: String(shown.length),
  });
  const parts = [sourceLink, windowNote];
  if (partial.length) {
    const partialNote = document.createElement("span");
    partialNote.textContent = t("ptr.partial", { count: String(partial.length) });
    parts.push(partialNote);
  }
  if (pending.length) {
    const pendingNote = document.createElement("span");
    pendingNote.textContent = t("ptr.pending", { count: String(pending.length) });
    parts.push(pendingNote);
  }
  const basis = document.createElement("span");
  basis.textContent = state.lang === "ko" ? (payload.basis_ko || "") : (payload.basis_en || "");
  const legal = document.createElement("span");
  legal.textContent = state.lang === "ko"
    ? (payload.legal?.notice_ko || "") : (payload.legal?.notice || "");
  footer.append(...parts, basis, legal);
}

function renderCalendar() {
  const section = $("#econ-calendar");
  if (!section) return;
  const payload = state.calendar;
  const events = Array.isArray(payload?.events) ? payload.events : [];
  if (!events.length) { section.hidden = true; return; }
  section.hidden = false;

  const body = $("#cal-body");
  body.replaceChildren();
  const scroll = document.createElement("div"); scroll.className = "table-scroll";
  const table = document.createElement("table"); table.className = "accessible-table kridx-table";
  table.innerHTML = `<thead><tr>
    <th scope="col">${t("cal.colDate")}</th><th scope="col">${t("cal.colEvent")}</th>
    <th scope="col">${t("cal.colRegion")}</th><th scope="col">${t("cal.colKind")}</th>
  </tr></thead>`;
  const tbody = document.createElement("tbody");
  const todayIso = new Date(Date.now() + (new Date().getTimezoneOffset() + 540) * 60000).toISOString().slice(0, 10);
  for (const event of events) {
    const tr = document.createElement("tr");
    const dateTd = document.createElement("td");
    const days = Math.round((new Date(event.date) - new Date(todayIso)) / 86400000);
    const dday = days === 0 ? t("cal.today") : days > 0 && days <= 14 ? t("cal.dday", { n: String(days) }) : "";
    dateTd.textContent = dday ? `${dateText(event.date)} · ${dday}` : dateText(event.date);
    if (days === 0) dateTd.className = "up";
    const eventTd = document.createElement("td"); eventTd.className = "krp-company";
    const link = document.createElement("a");
    link.href = event.source_url; link.target = "_blank"; link.rel = "noopener noreferrer";
    link.textContent = localValue(event.name, state.lang);
    eventTd.append(link);
    const regionTd = document.createElement("td");
    regionTd.textContent = event.region === "kr" ? t("cal.regionKr") : t("cal.regionUs");
    const kindTd = document.createElement("td"); kindTd.className = "range";
    kindTd.textContent = event.kind === "policy" ? t("cal.kindPolicy") : t("cal.kindRelease");
    tr.append(dateTd, eventTd, regionTd, kindTd);
    tbody.append(tr);
  }
  table.append(tbody); scroll.append(table); body.append(scroll);

  const footer = $("#cal-footer");
  footer.replaceChildren();
  const basis = document.createElement("span");
  basis.textContent = state.lang === "ko" ? (payload.basis_ko || "") : (payload.basis_en || "");
  const fred = document.createElement("span");
  fred.textContent = payload.source?.fred_notice || "";
  footer.append(basis, fred);
}

// Compact month/day for the overnight cards, where the full year is noise.
function kroDate(iso) {
  if (!iso) return "—";
  const date = new Date(String(iso).length === 10 ? `${iso}T00:00:00` : iso);
  if (Number.isNaN(date.valueOf())) return String(iso);
  return new Intl.DateTimeFormat(state.lang === "ko" ? "ko-KR" : "en-US", { month: "numeric", day: "numeric" }).format(date);
}

function kroMoney(value, kind) {
  if (value === null || !isFinite(value)) return "—";
  if (kind === "index") return `${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} pt`;
  return `₩${Math.round(value).toLocaleString("en-US")}`;
}

function renderKrOvernight() {
  const section = $("#kr-overnight");
  if (!section) return;
  const stateNode = $("#kro-state"), grid = $("#kro-grid"), footer = $("#kro-footer");
  const payload = state.krOvernight;
  if (!payload || !Array.isArray(payload.cards)) {
    // The HIP-3 gate being off is absence by decision, same as the other
    // gated lanes: the section disappears instead of asking for a retry.
    if (disabledCode("krOvernight")) { section.hidden = true; return; }
    section.hidden = false; grid.hidden = true; footer.hidden = true;
    stateNode.hidden = false; stateNode.textContent = `${t("status.unavailable")} · ${t("status.retry")}`;
    return;
  }
  const cards = payload.cards.filter((card) => card && card.perp);
  if (!cards.length) {
    section.hidden = false; grid.hidden = true; footer.hidden = true;
    stateNode.hidden = false; stateNode.textContent = t("kro.noMarket");
    return;
  }
  section.hidden = false; stateNode.hidden = true; grid.hidden = false; footer.hidden = false;

  grid.replaceChildren(...cards.map((card) => {
    const percent = safeNumber(card.implied?.vs_official_percent);
    const mark = safeNumber(card.perp?.mark);
    const change24h = safeNumber(card.perp?.change_24h_percent);
    const implied = safeNumber(card.implied?.value);
    const officialClose = safeNumber(card.official?.close);
    const article = document.createElement("article");
    article.className = `kro-card ${changeClass(percent)}`;

    const header = document.createElement("header");
    const title = document.createElement("h3"); title.textContent = localValue(card.label, state.lang);
    const symbol = document.createElement("a");
    symbol.className = "kro-sym"; symbol.textContent = String(card.symbol || "").toUpperCase();
    if (card.perp?.source_url) { symbol.href = card.perp.source_url; symbol.target = "_blank"; symbol.rel = "noopener noreferrer"; }
    header.append(title, symbol);

    const price = document.createElement("div"); price.className = "kro-price";
    const markUsd = mark === null ? "—" : `$${mark.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    price.textContent = implied !== null ? kroMoney(implied, card.kind) : markUsd;

    const vs = document.createElement("div"); vs.className = `kro-vs ${changeClass(percent)}`;
    if (percent !== null) vs.textContent = `${formatSigned(percent)} · ${t("kro.vsClose", { date: kroDate(card.official?.date) })}`;
    else if (card.status === "no_fx") vs.textContent = t("kro.noFx");
    else vs.textContent = t("kro.noClose");

    const meta = document.createElement("dl"); meta.className = "kro-meta";
    const row = (labelText, valueText) => {
      const wrap = document.createElement("div");
      const dt = document.createElement("dt"); dt.textContent = labelText;
      const dd = document.createElement("dd"); dd.textContent = valueText;
      wrap.append(dt, dd); return wrap;
    };
    const markText = card.kind === "index" ? kroMoney(mark, "index") : markUsd;
    meta.append(row(t("kro.mark"), `${markText}${change24h === null ? "" : ` · 24h ${formatSigned(change24h)}`}`));
    meta.append(row(t("kro.official"), officialClose === null ? "—" : `${kroMoney(officialClose, card.kind)} · ${kroDate(card.official?.date)}`));
    if (card.adr?.per_ordinary) {
      meta.append(row(t("kro.adrRatio"), `${card.adr.per_ordinary} ADR = 1`));
    }
    if (card.kind !== "index" && payload.fx?.status === "ok") {
      meta.append(row(t("kro.fx"), `${payload.fx.rate.toLocaleString("en-US", { maximumFractionDigits: 2 })} · ${kroDate(payload.fx.date)} H.10`));
    }

    const badges = document.createElement("div"); badges.className = "kro-badges";
    const badge = (text, cls = "warn") => { const span = document.createElement("span"); span.className = `status-badge ${cls}`; span.textContent = text; badges.append(span); };
    if (card.perp?.stale) badge(t("badge.stale"));
    if (card.perp?.liquidity_status === "low") badge(t("weekend.liquidity"));
    if (payload.session?.active) badge(t("kro.session"), "info");

    article.append(header, price, vs, meta);
    if (badges.childElementCount) article.append(badges);
    return article;
  }));

  footer.replaceChildren();
  const method = document.createElement("p"); method.className = "kro-method";
  method.textContent = localValue(payload.methodology, state.lang);
  const disclaimer = document.createElement("p"); disclaimer.className = "kro-disclaimer";
  disclaimer.textContent = localValue(payload.disclaimer, state.lang);
  footer.append(method, disclaimer);
}

function renderSectors() {
  const payload = state.sectors; const stateNode = $("#sector-state"), bars = $("#sector-bars");
  if (!stateNode) return;
  $$("#sector-period button").forEach((button) => { const active = button.dataset.period === state.sectorPeriod; button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active)); });
  if (!payload) { const disabled = disabledText("sectors"); stateNode.hidden = false; stateNode.classList.toggle("disabled", Boolean(disabled)); stateNode.textContent = disabled || `${t("status.unavailable")} · ${t("status.retry")}`; bars.hidden = true; return; }
  stateNode.classList.remove("disabled");
  const returnMultiplier = payload.basis?.return_unit === "decimal" ? 100 : 1;
  const sectors = Array.isArray(payload.sectors) ? payload.sectors : []; const rows = sectors.map((sector) => ({ sector, value: safeNumber(sector.returns?.[state.sectorPeriod] ?? sector[state.sectorPeriod]) }));
  const available = rows.filter((row) => row.value !== null); if (!available.length) { stateNode.hidden = false; stateNode.textContent = t("status.noSeries"); bars.hidden = true; return; }
  stateNode.hidden = true; bars.hidden = false; bars.replaceChildren(); const max = Math.max(...available.map((row) => Math.abs(row.value)), .0001);
  rows.sort((a, b) => (b.value ?? -Infinity) - (a.value ?? -Infinity)).forEach(({ sector, value }) => {
    const row = document.createElement("div"); row.className = "sector-row"; const name = document.createElement("div"); name.className = "sector-name"; name.textContent = localValue({ ko: sector.sector_ko, en: sector.sector_en }, state.lang) || sector.ticker;
    const code = document.createElement("code"); code.textContent = sector.ticker || ""; name.append(code); const track = document.createElement("div"); track.className = "bar-track"; const fill = document.createElement("i"); fill.className = `bar-fill ${changeClass(value)}`; fill.style.width = `${value === null ? 0 : Math.abs(value) / max * 50}%`; track.append(fill);
    const shown = document.createElement("div"); shown.className = `sector-value ${changeClass(value)}`; shown.textContent = value === null ? "—" : formatSigned(value * returnMultiplier); row.append(name, track, shown); bars.append(row);
  });
  const table = $("#sector-table"); $("thead", table).innerHTML = `<tr><th>${t("sector.name")}</th><th>Ticker</th><th>${t("sector.return")}</th></tr>`; const tbody = $("tbody", table); tbody.replaceChildren();
  rows.forEach(({ sector, value }) => { const tr = document.createElement("tr"); [localValue({ ko: sector.sector_ko, en: sector.sector_en }, state.lang), sector.ticker, value === null ? "—" : formatSigned(value * returnMultiplier)].forEach((text) => { const td = document.createElement("td"); td.textContent = text || "—"; tr.append(td); }); tbody.append(tr); });
  const provider = payload.source?.price_provider || payload.provider?.name || "API"; $("#sector-footer").textContent = `${provider} · ${t("date.asof")} ${dateText(payload.as_of || payload.generated_at)} · ${available.length}/${rows.length}`;
}

const WEEKEND_CARDS = [
  { id: "skhx", symbols: ["xyz:skhx"], label: LABEL("SK하이닉스", "SK Hynix"), kind: "direct" },
  { id: "smsn", symbols: ["xyz:smsn"], label: LABEL("삼성전자 합성선물", "Samsung synthetic perpetual"), kind: "direct", note: LABEL("USD 환산 무기한 합성선물", "USD-converted synthetic perpetual") },
  { id: "kr200", symbols: ["xyz:kr200"], label: LABEL("Korea 200", "Korea 200"), kind: "direct" },
  { id: "hyundai", symbols: ["xyz:hyundai"], label: LABEL("현대차", "Hyundai"), kind: "direct" },
  { id: "ewy", symbols: ["xyz:ewy"], label: LABEL("EWY 24시간 보조", "EWY 24h auxiliary"), kind: "auxiliary" },
  { id: "koru", symbols: ["xyz:koru"], label: LABEL("KORU 24시간 보조", "KORU 24h auxiliary"), kind: "auxiliary" },
  { id: "xyz100", symbols: ["xyz:xyz100"], label: LABEL("XYZ100", "XYZ100"), kind: "direct" },
  { id: "ustech", symbols: ["mkts:ustech"], label: LABEL("USTECH 24시간 보조", "USTECH 24h auxiliary"), kind: "auxiliary" },
  { id: "korea_weekend", symbols: ["xyz:kr200", "xyz:smsn", "xyz:skhx", "xyz:hyundai"], symbolText: LABEL("KR200 · 삼성 · SK하이닉스 · 현대차", "KR200 · Samsung · SK Hynix · Hyundai"), label: LABEL("한국 주말 기준 신호", "Korea weekend reference"), kind: "referenceSignal", composite: "korea_weekend" },
  { id: "nasdaq_weekend", symbols: ["xyz:xyz100", "mkts:ustech"], symbolText: LABEL("xyz:XYZ100 · USTECH 24시간 보조", "xyz:XYZ100 · USTECH 24h auxiliary"), label: LABEL("나스닥 주말 기준 신호", "Nasdaq weekend reference"), kind: "referenceSignal", composite: "nasdaq_weekend" },
];

const ENUM_LABELS = {
  ok: LABEL("정상", "OK"), limited: LABEL("제한적", "Limited"), unavailable: LABEL("사용 불가", "Unavailable"),
  outside_internal_session: LABEL("내부 세션 밖", "Outside internal session"),
  internal_price_discovery: LABEL("내부 가격발견", "Internal price discovery"),
  outside_weekend_internal_session: LABEL("주말 내부 세션 밖", "Outside weekend internal session"),
  external_reference: LABEL("외부 기준 세션", "External reference"), weekend_internal: LABEL("주말 내부 세션", "Weekend internal"),
  daily_internal_gap: LABEL("일간 내부 구간", "Daily internal gap"), high: LABEL("높음", "High"), medium: LABEL("중간", "Medium"), low: LABEL("낮음", "Low"),
  available: LABEL("사용 가능", "Available"), not_applicable_24h_auxiliary: LABEL("24시간 보조에는 해당 없음", "Not applicable to 24h auxiliary"),
  internal_session_eligible: LABEL("내부 세션 기준 가능", "Internal-session eligible"), auxiliary_24h_only: LABEL("24시간 보조 전용", "24h auxiliary only"),
};

function enumText(value) {
  if (!value) return "—";
  return localValue(ENUM_LABELS[value], state.lang) || (state.lang === "en" ? String(value).replaceAll("_", " ") : String(value));
}

function weekendUnit(signal, field) {
  const units = signal?.units;
  if (!units) return "";
  let raw = typeof units === "object" ? units[field] : units;
  if (!raw && field === "mark" && typeof units === "object") raw = units.price || units.quote || units.quote_currency || units.currency;
  if (raw && typeof raw === "object") raw = raw.short || raw.symbol || raw.unit || raw.currency || raw.name;
  const unit = raw ? String(raw) : "";
  const displayUnits = {
    "USDC per contract reference unit": "USDC/ref",
    "raw decimal rate per one-hour funding interval": "raw/h",
    "percent per one-hour funding interval": "%/h",
    "base contract units": "base units",
    "rolling-day USD/USDC notional reported by dayNtlVlm": "USD/USDC",
  };
  return displayUnits[unit] || unit;
}

function formatContractValue(value, unit = "", compact = false) {
  if (value === null) return "—";
  const formatted = new Intl.NumberFormat(state.lang === "ko" ? "ko-KR" : "en-US", compact
    ? { notation: "compact", maximumFractionDigits: 2 }
    : { maximumFractionDigits: Math.abs(value) < .01 ? 8 : 4 }).format(value);
  return unit ? `${formatted} ${unit}` : formatted;
}

function formatWeekendValue(value, signal) {
  const unit = weekendUnit(signal, "mark");
  if (value === null) return "—";
  if (["USD", "KRW", "JPY", "EUR", "GBP"].includes(unit)) {
    return new Intl.NumberFormat(state.lang === "ko" ? "ko-KR" : "en-US", { style: "currency", currency: unit, currencyDisplay: "narrowSymbol", maximumFractionDigits: value < 10 ? 4 : 2 }).format(value);
  }
  return formatContractValue(value, unit);
}

function renderWeekend() {
  const host = $("#weekend-grid"), status = $("#weekend-state"), payload = state.weekend;
  if (!host || !status) return;
  if (!payload) {
    const disabled = disabledText("weekend");
    host.hidden = true; status.hidden = false; status.classList.toggle("disabled", Boolean(disabled));
    status.textContent = disabled || `${t("status.unavailable")} · ${t("status.retry")}`;
    $("#weekend-disclaimer").textContent = t("weekend.defaultDisclaimer"); return;
  }
  status.classList.remove("disabled"); status.hidden = true; host.hidden = false; host.replaceChildren(); const signals = Array.isArray(payload.signals) ? payload.signals : [];
  const bySymbol = new Map(signals.map((signal) => [String(signal.symbol || signal.id).toLowerCase(), signal]));
  WEEKEND_CARDS.forEach((definition) => {
    const composite = definition.composite ? payload.composites?.[definition.composite] : null; const signal = definition.composite ? null : definition.symbols.map((symbol) => bySymbol.get(symbol)).find(Boolean); const record = composite || signal;
    const mark = safeNumber(signal?.mark ?? signal?.oracle ?? record?.value); const usable = definition.composite ? Boolean(record && record.status !== "unavailable") : mark !== null;
    const role = signal?.session_role === "auxiliary_24h_only" ? "auxiliary" : signal ? "direct" : definition.kind;
    const card = document.createElement("article"); card.className = `weekend-card ${role === "auxiliary" ? "proxy" : ""} ${usable ? "" : "unavailable"}`;
    const shownLabel = definition.composite ? localValue(definition.label, state.lang) : localValue(signal?.label, state.lang) || localValue(definition.label, state.lang);
    const sessionDelta = safeNumber(definition.composite ? record?.change_percent : record?.session_change_percent);
    const dayDelta = definition.composite ? null : safeNumber(record?.change_24h_percent); const delta = sessionDelta ?? dayDelta; const deltaLabel = sessionDelta !== null ? t("weekend.sessionChange") : t("weekend.change24h");
    const metaLabels = definition.composite ? [t("weekend.status"), t("weekend.confidence"), t("weekend.session")] : [t("weekend.funding"), t("weekend.openInterest"), t("weekend.volume")];
    card.innerHTML = `<header><div><h3></h3><span class="weekend-symbol"></span></div><div class="weekend-badges"><span class="status-badge ${record ? "info" : "error"}"></span></div></header><div class="weekend-value"></div><div class="weekend-change"></div><div class="weekend-meta"><span>${metaLabels[0]}<strong></strong></span><span>${metaLabels[1]}<strong></strong></span><span>${metaLabels[2]}<strong></strong></span></div>`;
    $("h3", card).textContent = shownLabel; const symbolNode = $(".weekend-symbol", card); symbolNode.textContent = definition.composite ? localValue(definition.symbolText, state.lang) || definition.symbols.join(" + ") : (signal?.symbol || definition.symbols[0]); $(".status-badge", card).textContent = t(`weekend.${role}`);
    if (signal?.source_url) { const link = document.createElement("a"); link.href = signal.source_url; link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = symbolNode.textContent; symbolNode.replaceChildren(link); }
    if (!usable) { const unavailableBadge = document.createElement("span"); unavailableBadge.className = "status-badge error"; unavailableBadge.textContent = t("status.unavailable"); $(".weekend-badges", card).append(unavailableBadge); }
    if (signal && safeNumber(signal.mark) === null && safeNumber(signal.oracle) !== null) { const oracleBadge = document.createElement("span"); oracleBadge.className = "status-badge warn"; oracleBadge.textContent = "ORACLE"; oracleBadge.title = "mark unavailable · oracle fallback"; $(".weekend-badges", card).append(oracleBadge); }
    const quality = signal?.reference_quality || record?.evidence_quality; if (quality) { const qualityBadge = document.createElement("span"); qualityBadge.className = "status-badge"; qualityBadge.textContent = enumText(quality); qualityBadge.title = `${t("weekend.reference")}: ${quality}`; $(".weekend-badges", card).append(qualityBadge); }
    if (signal?.stale || record?.stale) { const staleBadge = document.createElement("span"); staleBadge.className = "status-badge stale"; staleBadge.textContent = t("weekend.stale"); const age = safeNumber(signal?.age_seconds ?? record?.age_seconds); if (age !== null) staleBadge.title = `${Math.round(age)}s`; $(".weekend-badges", card).append(staleBadge); }
    $(".weekend-value", card).textContent = definition.composite ? enumText(record?.status) : formatWeekendValue(mark, signal); const ch = $(".weekend-change", card); ch.className = `weekend-change ${changeClass(delta)}`; ch.textContent = delta === null ? t("status.unavailable") : `${formatSigned(delta)} · ${deltaLabel}`;
    const baseline = safeNumber(signal?.session_baseline?.price ?? signal?.session_baseline); const previous24h = safeNumber(signal?.previous_24h); const baselines = [];
    if (baseline !== null) baselines.push(`${t("weekend.session")} baseline: ${formatWeekendValue(baseline, signal)}`);
    if (previous24h !== null) baselines.push(`24h baseline: ${formatWeekendValue(previous24h, signal)}`);
    if (baselines.length) ch.title = baselines.join(" · ");
    const strong = $$(".weekend-meta strong", card);
    if (definition.composite) { strong[0].textContent = enumText(record?.status); strong[1].textContent = enumText(record?.evidence_quality || record?.reference_quality); strong[2].textContent = enumText(record?.session?.state || record?.session?.window); }
    else { strong[0].textContent = formatContractValue(safeNumber(signal?.funding_hourly_percent), "%/h"); strong[1].textContent = formatContractValue(safeNumber(signal?.open_interest_base_units), weekendUnit(signal, "open_interest_base_units"), true); strong[2].textContent = formatContractValue(safeNumber(signal?.day_volume_usd_notional ?? signal?.day_volume), weekendUnit(signal, "day_volume_usd_notional") || "USD", true); }
    const age = safeNumber(signal?.age_seconds ?? record?.age_seconds); card.title = `${signal?.kind || (definition.composite ? "composite_reference" : role)} · ${t("date.asof")} ${dateText(signal?.as_of || signal?.fetched_at || record?.as_of || payload.generated_at)}${age === null ? "" : ` · ${Math.round(age)}s`}`;
    host.append(card);
  });
  const baseDisclaimer = localValue(payload.disclaimer, state.lang) || t("weekend.defaultDisclaimer"); $("#weekend-disclaimer").textContent = `${baseDisclaimer} ${t("weekend.samsungPerp")}`;
}

function renderStressIndex() {
  const stateNode = $("#stress-state"), body = $("#stress-body"), data = state.stress;
  if (!stateNode || !body) return;
  if (!data) {
    const disabled = disabledText("stress");
    stateNode.hidden = false; stateNode.classList.toggle("disabled", Boolean(disabled)); body.hidden = true;
    stateNode.textContent = disabled || `${t("status.unavailable")} · ${t("status.retry")}`;
    return;
  }
  stateNode.hidden = true; stateNode.classList.remove("disabled"); body.hidden = false;
  const locale = state.lang === "ko" ? "ko-KR" : "en-US";
  const num = (value, digits = 1) => new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(value);

  $("#stress-score").textContent = num(data.score);
  $("#stress-band").textContent = `${localValue(data.band, state.lang)} · ${t("date.asof")} ${dateText(data.as_of)}`;
  $("#stress-marker").style.left = `calc(${Math.max(0, Math.min(100, data.score))}% - 1.5px)`;

  const table = $("#stress-table");
  const heads = ["stress.colInput", "stress.colValue", "stress.colPct", "stress.colScore", "stress.colDir"];
  $("thead", table).innerHTML = `<tr>${heads.map((key) => `<th scope="col">${t(key)}</th>`).join("")}</tr>`;
  const tbody = $("tbody", table); tbody.replaceChildren();
  for (const item of data.components || []) {
    const row = document.createElement("tr");
    const cells = [
      localValue(item.label, state.lang),
      num(item.value, 2),
      num(item.percentile),
      num(item.score),
      t(item.inverted ? "stress.inverted" : "stress.direct"),
    ];
    cells.forEach((text, index) => {
      const cell = document.createElement("td");
      if (index >= 1 && index <= 3) cell.className = "num";
      cell.textContent = text;
      // The direction of each input is the part a reader most needs explained.
      if (index === 0) cell.title = localValue(item.rationale, state.lang);
      row.append(cell);
    });
    tbody.append(row);
  }
  $("#stress-method").textContent = localValue(
    { ko: data.method?.summary_ko, en: data.method?.summary_en }, state.lang);
  $("#stress-disclaimer").textContent = localValue(data.disclaimer, state.lang);
}

function renderTradingView() {
  state.tvLoaded = true; const host = $("#tradingview-host"); host.replaceChildren(); const container = document.createElement("div"); container.className = "tradingview-widget-container"; const widget = document.createElement("div"); widget.className = "tradingview-widget-container__widget";
  const script = document.createElement("script"); script.type = "text/javascript"; script.src = "https://s3.tradingview.com/external-embedding/embed-widget-stock-heatmap.js"; script.async = true;
  const blockColors = { "1d": "change", "1w": "Perf.W", "1m": "Perf.1M", "1y": "Perf.Y" };
  script.textContent = JSON.stringify({ exchanges: [], dataSource: "SPX500", grouping: "sector", blockSize: "market_cap_basic", blockColor: blockColors[state.tvPeriod], locale: state.lang, symbolUrl: "", colorTheme: document.documentElement.dataset.theme === "light" ? "light" : "dark", hasTopBar: true, isDataSetEnabled: true, isZoomEnabled: true, hasSymbolTooltip: true, isMonoSize: false, width: "100%", height: "100%" });
  container.append(widget, script); host.append(container);
}

function correlationColor(value) {
  const number = Math.max(-1, Math.min(1, value)); const alpha = .16 + Math.abs(number) * .68;
  return number >= 0 ? `rgba(8,127,97,${alpha})` : `rgba(201,60,85,${alpha})`;
}

async function loadCorrelation() {
  state.correlationLoaded = true; const stateNode = $("#corr-state"), wrap = $("#corr-table-wrap"); stateNode.hidden = false; stateNode.classList.remove("disabled"); stateNode.textContent = t("status.loading"); wrap.hidden = true;
  const payload = await fetchJson(`/api/correlation?tickers=${encodeURIComponent("SPY,TLT,GLD,UUP,USO,BTC-USD")}&period=${encodeURIComponent($("#corr-period").value)}`, "correlation");
  if (!payload?.matrix || !Array.isArray(payload.tickers)) { const disabled = disabledText("correlation"); stateNode.classList.toggle("disabled", Boolean(disabled)); stateNode.textContent = disabled || `${t("status.unavailable")} · ${t("status.retry")}`; return; }
  const table = document.createElement("table"); table.className = "accessible-table corr-table"; const caption = document.createElement("caption"); caption.textContent = t("corr.title"); table.append(caption); const thead = document.createElement("thead"); const hr = document.createElement("tr"); ["", ...payload.tickers].forEach((name) => { const th = document.createElement("th"); th.scope = "col"; th.textContent = name; hr.append(th); }); thead.append(hr); table.append(thead); const tbody = document.createElement("tbody");
  payload.tickers.forEach((row) => { const tr = document.createElement("tr"); const th = document.createElement("th"); th.scope = "row"; th.textContent = row; tr.append(th); payload.tickers.forEach((col) => { const td = document.createElement("td"); const value = safeNumber(payload.matrix[row]?.[col]); td.textContent = value === null ? "—" : value.toFixed(2); if (value !== null) { td.className = "corr-cell"; td.style.background = correlationColor(value); } tr.append(td); }); tbody.append(tr); }); table.append(tbody); wrap.replaceChildren(table); stateNode.hidden = true; wrap.hidden = false;
}

function setupLazySections() {
  const observer = new IntersectionObserver((entries) => entries.forEach((entry) => {
    if (!entry.isIntersecting) return; const kind = entry.target.dataset.lazy; if (kind === "tradingview") renderTradingView(); if (kind === "correlation") loadCorrelation(); observer.unobserve(entry.target);
  }), { rootMargin: "300px 0px" }); $$("[data-lazy]").forEach((node) => observer.observe(node));
}

function applyLocale() {
  document.documentElement.lang = state.lang; trNode(); renderSkeleton(); renderAll(); $("#locale-toggle").textContent = state.lang === "ko" ? "EN" : "KO";
  if (state.tvLoaded) renderTradingView();
}

function setupControls() {
  $("#locale-toggle").addEventListener("click", () => { state.lang = state.lang === "ko" ? "en" : "ko"; localStorage.setItem("monitor.locale", state.lang); applyLocale(); });
  $("#theme-toggle").addEventListener("click", () => { const next = document.documentElement.dataset.theme === "light" ? "dark" : "light"; document.documentElement.dataset.theme = next; localStorage.setItem("monitor.theme", next); if (state.tvLoaded) renderTradingView(); });
  const theme = localStorage.getItem("monitor.theme"); if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
  $("#refresh-button")?.addEventListener("click", loadCore);
  $("#sector-period")?.addEventListener("click", (event) => { const button = event.target.closest("button[data-period]"); if (!button) return; state.sectorPeriod = button.dataset.period; localStorage.setItem("monitor.sectorPeriod", state.sectorPeriod); renderSectors(); });
  $("#tv-period")?.addEventListener("click", (event) => { const button = event.target.closest("button[data-period]"); if (!button) return; state.tvPeriod = button.dataset.period; localStorage.setItem("monitor.tvPeriod", state.tvPeriod); $$("#tv-period button").forEach((node) => { const active = node === button; node.classList.toggle("active", active); node.setAttribute("aria-pressed", String(active)); }); if (state.tvLoaded) renderTradingView(); });
  $("#corr-period")?.addEventListener("change", () => { if (state.correlationLoaded) loadCorrelation(); });
  $$("#tv-period button").forEach((node) => { const active = node.dataset.period === state.tvPeriod; node.classList.toggle("active", active); node.setAttribute("aria-pressed", String(active)); });
}

setupControls(); applyLocale(); setupLazySections(); loadCore();
setInterval(() => { if (!document.hidden) loadCore(); }, 15 * 60 * 1000);
// 세션 배지는 데이터가 아니라 시계라 1분마다 자체 갱신한다.
setInterval(updateSessionBadge, 60 * 1000);
// 24시간 참고가 카드의 마크가격은 실시간 소스라, 페이지 전체 주기(15분)와
// 별개로 1분마다 가볍게 갱신한다. API 캐시가 15초라 서버 부담은 미미하다.
if (onPage(...PAGE_FETCHES.krOvernight)) {
  setInterval(async () => {
    if (document.hidden || !document.getElementById("kr-overnight")) return;
    const payload = await fetchJson("/api/kr/overnight", "krOvernight");
    if (payload) { state.krOvernight = payload; renderKrOvernight(); }
  }, 60 * 1000);
}
