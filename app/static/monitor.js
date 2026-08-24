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
    "brand.tagline": "물밑 · 주식·암호화폐 시장 신호", "nav.analytics": "종목 분석", "nav.monitor": "시장 모니터",
    "nav.home": "홈", "nav.kr": "한국", "nav.us": "미국·글로벌", "nav.crypto": "암호화폐", "crypto.regime.title": "시장 국면", "crypto.regime.copy": "지금 시장이 얼마나 쏠려 있고 어느 쪽으로 기울어 있는지를 요약한 상태 지표입니다. 매수·매도 신호가 아니며, 과열이 곧 하락을 뜻하지도 않습니다.", "crypto.liq.title": "청산 집계", "crypto.liq.copy": "최근 24시간 강제청산 규모를 롱·숏으로 나눠 봅니다. 응답한 거래소들의 합이며 전체 시장 합계가 아닙니다. 1시간 단위 집계이고 실시간 체결 피드가 아닙니다.", "crypto.liq.window": "24시간 청산", "crypto.liq.long": "롱 청산", "crypto.liq.short": "숏 청산", "crypto.liq.hour": "최근 1시간", "crypto.liq.oi": "미결제약정", "crypto.liq.venues": "포함 거래소", "crypto.liq.silent": "응답 없음", "crypto.liq.none": "아직 수집된 청산 집계가 없습니다.", "crypto.news.title": "암호화폐 뉴스", "crypto.news.copy": "GDELT가 수집한 글로벌 기사에서 코인 이름이 제목에 잡힌 헤드라인입니다. 제목·출처·링크까지만 전달하며 본문은 원문에서 확인하세요. 실시간 속보가 아니라 수집 주기 갱신입니다.", "crypto.news.none": "코인 태그가 붙은 헤드라인이 아직 없습니다.", "crypto.news.also": "외 {n}곳", "videos.title": "뉴스 영상", "videos.shortCopy": "재생을 누르기 전에는 플레이어가 로드되지 않습니다", "videos.copy": "읽고 계신 언어의 뉴스 채널에서 가져온 최근 영상입니다. 썸네일은 구글 이미지 서버에서 직접 불러오며 쿠키는 심지 않습니다. 재생을 누르면 그때 유튜브 플레이어가 로드되고 유튜브의 쿠키·정책이 적용됩니다. 영상 내용은 각 채널의 것이며 이 사이트의 수치와는 무관합니다.", "videos.play": "재생", "videos.playAria": "{title} 재생", "videos.none": "아직 수집된 영상이 없습니다.", "videos.openOn": "유튜브에서 열기", "crypto.regime.change24h": "24h 변화", "crypto.regime.collecting": "추이 수집 중", "crypto.regime.heat": "과열도", "crypto.regime.trend": "추세", "crypto.regime.sample": "표본", "crypto.regime.sampleValue": "유동 시장 {n}개", "crypto.heatBadge": "과열도 {n}", "nav.bio": "바이오", "landing.bioLink": "바이오", "landing.bioDesc": "임상 파이프라인 동향 · FDA 최근 승인 · 식약처 품목허가", "biopage.kicker": "BIOPHARMA", "biopage.title": "바이오, 임상과 승인을 기록으로 봅니다.", "biopage.copy": "국내·글로벌 제약바이오 워치리스트의 임상 파이프라인 갱신(ClinicalTrials.gov)과 FDA의 최근 신약·바이오의약품 승인(openFDA)을 공공 기록 그대로 봅니다. 결과의 성패나 주가 해석, 투자 권유가 아닙니다.", "biopage.h1": "바이오", "biopage.scope": "다가올 결정 · 한국 · 미국·글로벌",
    "biopage.sub": "바이오 종목은 결정 하나에 움직입니다. 그래서 날짜가 잡힌 것을 맨 앞에 두고, 이미 난 결정은 시장별로 나눠 봅니다. 전부 공공 기록 그대로이며 결과의 성패나 주가 해석이 아닙니다.",
    "bio.cat.title": "다가오는 결정", "bio.cat.note": "날짜가 잡힌 것만 · 가까운 순서",
    "bio.cat.copy": "FDA 자문위원회 회의처럼 날짜가 확정된 것과, 임상의 1차 완료 예정일을 한 줄에 놓고 가까운 순서로 봅니다. 1차 완료 예정일은 스폰서가 등록부에 적어 둔 계획값이라 자주 바뀌고, 완료가 곧 결과 발표도 아닙니다.",
    "bio.cat.badgePlan": "계획일 포함 · 확정 아님", "bio.cat.kindMeeting": "자문위 회의", "bio.cat.kindReadout": "1차 완료 예정",
    "bio.cat.meetings": "예정 자문위", "bio.cat.readouts90": "90일 내 1차 완료", "bio.cat.window": "보는 창",
    "bio.cat.windowValue": "{n}일", "bio.cat.monthOnly": "중", "bio.cat.none": "창 안에 날짜가 잡힌 항목이 없습니다.",
    "bio.cat.basis": "자문위 회의일은 Federal Register 공고에서, 1차 완료 예정일은 ClinicalTrials.gov 등록값에서 왔습니다. 예정일은 스폰서가 수시로 고치는 계획값이며, 1차 완료는 결과 발표일이 아닙니다. 날짜가 없는 공고는 여기 오지 않습니다.",
    "bio.zone.kr": "한국", "bio.zone.krNote": "식약처 허가 · 국내 스폰서 임상",
    "bio.zone.global": "미국 · 글로벌", "bio.zone.globalNote": "FDA 승인 · 글로벌 스폰서 임상 · 자문위",
    "bio.trials.krTitle": "국내 스폰서 임상", "bio.trials.globalTitle": "글로벌 스폰서 임상",
    "bio.trials.note": "최근 14일 갱신 · 중재 2·3상",
    "bio.trials.title": "임상 파이프라인 동향", "bio.filter.all": "전체", "bio.filter.kr": "한국", "bio.filter.global": "글로벌", "bio.pub.link": "논문 {n}건", "bio.pub.linkOne": "논문 1건", "bio.pub.source": "PubMed", "bio.pub.notice": "PubMed 서지(제목·저널·일자·PMID)만, 초록 비표시 · 등록번호(NCT) 기준 검색", "bio.adcomm.title": "FDA 자문위원회 회의 공고", "bio.adcomm.copy": "Federal Register에 게재된 FDA 자문위원회 회의 공고입니다(예정 회의와 최근 30일 종료 회의). 회의일은 공고의 DATES 단락에서 추출한 값이며 최종 일정은 링크된 공고를 따릅니다. 자문위 결론이나 승인 여부가 아닙니다.", "bio.adcomm.caption": "자문위원회 회의 공고 (예정 · 최근 종료)", "bio.adcomm.upcoming": "예정 회의", "bio.adcomm.next": "다음 회의", "bio.adcomm.recentPast": "최근 30일 종료", "bio.adcomm.undated": "날짜 미기재 공고", "bio.adcomm.none": "예정된 회의 공고가 없습니다.", "bio.col.meeting": "회의일", "bio.col.committee": "위원회", "bio.col.notice": "공고", "bio.col.published": "공고일", "bio.col.state": "상태", "bio.adcomm.state.upcoming": "예정", "bio.adcomm.state.past": "종료", "bio.adcomm.state.undated": "날짜 미기재", "bio.adcomm.amendment": "정정 공고", "bio.adcomm.daysUntil": "D-{n}", "bio.adcomm.today": "오늘", "bio.mfds.title": "식약처 최근 품목허가", "bio.mfds.copy": "식품의약품안전처 의약품 제품 허가정보(공공데이터포털)를 허가일자별로 최근 30일 모은 목록입니다. 기본 보기는 '주목'(허가된 전문의약품·신약·희귀의약품)이며 신고·일반의약품까지 전체를 볼 수 있습니다. 규제 기록일 뿐 매출·주가 해석이 아닙니다.", "bio.mfds.caption": "식약처 품목허가 (최근 30일)", "bio.mfds.filter.notable": "주목", "bio.mfds.filter.permit": "허가만", "bio.mfds.filter.all": "전체", "bio.mfds.total": "30일 품목", "bio.mfds.permit": "허가", "bio.mfds.report": "신고", "bio.mfds.rx": "전문의약품", "bio.mfds.newDrug": "신약", "bio.mfds.rare": "희귀의약품", "bio.mfds.none": "창 안에 해당하는 품목이 없습니다.", "bio.mfds.failedDays": "일부 날짜 조회 실패 {n}일", "bio.col.permitDate": "허가일", "bio.col.item": "품목명", "bio.col.company": "업체", "bio.col.rxOtc": "구분", "bio.col.kind": "허가/신고", "bio.col.ingredients": "주성분", "bio.mfds.flag.newDrug": "신약", "bio.mfds.flag.rare": "희귀", "bio.mfds.flag.cancelled": "취하·취소", "bio.trials.copy": "워치리스트 34개 스폰서(주 스폰서 기준)의 임상 중 최근 14일 내 갱신된 중재 2·3상입니다(스폰서당 최대 8건). 상태·단계·일자는 ClinicalTrials.gov 등록값 그대로이며, 한국어 이름과 상장 라벨은 Mulmit이 붙인 참고 라벨입니다.", "bio.trials.caption": "최근 갱신 임상 (중재 2·3상, 14일)", "bio.badge.registry": "등록 정보 · 결과 아님", "bio.badge.sponsorEntered": "스폰서 직접 등록", "bio.badge.notAdvice": "투자 권유 아님", "bio.trials.sponsors": "워치리스트 스폰서", "bio.trials.recent": "최근 갱신(14일)", "bio.trials.registered": "등록 임상", "bio.trials.processed": "ClinicalTrials.gov 처리일", "bio.trials.none": "최근 14일 내 갱신된 중재 2·3상이 없습니다.", "bio.col.sponsor": "스폰서", "bio.col.study": "임상", "bio.col.phase": "단계", "bio.col.status": "상태", "bio.col.updated": "갱신일", "bio.col.primary": "1차 완료(예정)", "bio.col.conditions": "적응증", "bio.col.intervention": "중재", "bio.status.RECRUITING": "모집 중", "bio.status.NOT_YET_RECRUITING": "모집 예정", "bio.status.ENROLLING_BY_INVITATION": "초청 등록", "bio.status.ACTIVE_NOT_RECRUITING": "진행 중(모집 종료)", "bio.status.COMPLETED": "완료", "bio.status.TERMINATED": "조기 종료", "bio.status.WITHDRAWN": "철회", "bio.status.SUSPENDED": "보류", "bio.status.UNKNOWN": "미확인", "bio.status.AVAILABLE": "이용 가능", "bio.status.NO_LONGER_AVAILABLE": "이용 종료", "bio.flag.results": "결과 게시", "bio.flag.stopped": "중단", "bio.flag.completed": "완료", "bio.flag.new": "신규", "bio.flag.why": "사유", "bio.phaseSuffix": "상", "bio.enrollment": "등록 {n}명", "bio.fda.title": "FDA 최근 승인", "bio.fda.copy": "최근 60일 안에 원 신청(ORIG)이 승인된 NDA(신약)·BLA(바이오의약품) 목록입니다. 제네릭(ANDA)은 건수만 표시합니다. openFDA 공개 도메인 데이터이며 규제 기록일 뿐 매출·주가 해석이 아닙니다.", "bio.fda.caption": "최근 원 신청 승인 (NDA·BLA)", "bio.fda.window": "창 {s} ~ {e}", "bio.fda.nda": "NDA 신약", "bio.fda.bla": "BLA 바이오", "bio.fda.anda": "ANDA 제네릭(건수)", "bio.fda.priority": "우선심사", "bio.fda.nme": "신규 분자(NME)", "bio.fda.none": "창 안에 승인된 NDA·BLA가 없습니다.", "bio.fda.publisherUpdated": "openFDA 데이터 갱신", "bio.col.approved": "승인일", "bio.col.application": "신청", "bio.col.product": "제품(성분)", "bio.col.class": "분류", "bio.col.review": "심사", "bio.review.PRIORITY": "우선", "bio.review.STANDARD": "표준", "bio.listingNote": "상장 라벨은 Mulmit 참고 표기", "bio.modifications": "수정 내용", "bio.processedLabel": "ClinicalTrials.gov 처리일",
    "console.title": "지금 시장", "console.scope": "한국 · 미국 · 암호화폐", "console.hip3": "HIP-3 합성 무기한선물 · trade.xyz",
    "console.sub": "한국장이 닫혀 있어도 삼성전자·SK하이닉스·코스피200은 해외 시장에서 24시간 거래됩니다. 마지막 종가 이후 지금까지 얼마나 움직였는지를 원화로 환산해 보여줍니다.",
    "console.disclose": "이 가격은 어떻게 계산한 값인가요?",
    "console.zones": "더 깊이 보기", "console.zonesNote": "시장별 전용 화면",
    "mode.easy": "쉬움", "mode.pro": "전문가", "mode.label": "표시 수준", "tape.label": "시세 요약",
    "landing.kicker": "KOREA × US MARKET CONSOLE", "landing.title": "장이 닫혀도, 시장은 움직입니다.",
    "landing.title.krOpen": "장중입니다. 마감 후에도, 여기서 이어집니다.",
    "landing.title.usOpen": "서울은 밤, 뉴욕은 장중입니다.",
    "landing.title.weekend": "주말에도, 시장은 움직입니다.",
    "landing.title.holiday": "휴장일에도, 시장은 움직입니다.",
    "session.holiday": "휴장일",
    "presence.now": "{n}명 보는 중", "presence.note": "최근 90초 하트비트 기준 열린 브라우저 수 — 사람 수가 아닙니다.",
    "ev.title": "미국 기업 공시 속보 (8-K)", "ev.copy": "커버 중인 티커의 8-K(주요 이벤트 보고)입니다. 수집 주기(약 1시간)로 갱신되며 실시간 속보가 아닙니다. 제목은 공식 Item 번호의 표준 제목이고, 내용은 원문에서 확인하세요.",
    "krev.title": "한국 기업 공시 속보 (주요사항보고)", "krev.copy": "유가증권·코스닥 상장사의 주요사항보고서 접수 목록입니다. 제목은 공시 원문 제목이며, 수집 주기(약 1시간)로 갱신되어 실시간 속보가 아닙니다.",
    "feed.title": "지금 일어나는 일", "feed.shortCopy": "공시와 일정을 시간순으로 모았습니다 · 실시간 속보는 아닙니다", "feed.copy": "공시와 일정 lane을 시간순 한 줄기로 모았습니다. 뉴스·공시 속보류는 약 15분, 나머지는 시간 단위 주기이며 실시간 속보가 아닙니다.",
    "kro.officialStrip": "확정 종가", "kro.stripKospi": "코스피", "kro.stripKosdaq": "코스닥",
    "krev.colDate": "접수일", "krev.colCompany": "회사", "krev.colName": "보고서명", "krev.colLink": "원문", "krev.view": "보기",
    "ev.colDate": "제출일", "ev.colCompany": "회사", "ev.colItems": "내용 (Item)", "ev.colLink": "원문", "ev.view": "보기",
    "landing.copy": "삼성전자·SK하이닉스의 24시간 참고가부터 미국 매크로까지, 연결된 데이터만 보여줍니다. 연결되지 않은 값은 추정하지 않습니다.",
    "landing.krLink": "한국 시장", "landing.krDesc": "24시간 참고가 · 공식 종가 · 코스피 지수군 · ETF 보드 · 국민연금 5% 공시",
    "landing.usLink": "미국·글로벌", "landing.usDesc": "S&P 500 히트맵 · 하원 의원 거래 · 스트레스 지수 · 매크로 · 유동성",
    "session.open": "정규장 진행 중", "session.closed": "국내장 마감", "session.until": "개장까지 약 {time}",
    "session.hm": "{h}시간 {m}분", "session.note": "시계 기준 · 휴장일 미반영 · 평일 09:00–15:30 KST",
    "ticker.note": "한국은행 ECOS 매매기준율 · 실시간 아님",
    "landing.krMini.kospi": "코스피 200 퍼프", "landing.usMini.sp500": "S&P 500 퍼프", "landing.usMini.stress": "스트레스",
    "krpage.kicker": "KOREA MARKETS", "krpage.title": "한국 주식, 장 밖에서도 한눈에.",
    "krpage.h1": "한국 시장", "krpage.scope": "장 밖의 값 · 공시 · 지수",
    "krpage.sub": "한국장이 닫혀 있어도 주요 종목은 해외 시장에서 24시간 거래됩니다. 마지막 종가 이후 지금까지 얼마나 움직였는지를 원화로 환산해 보여주고, 그 사이 쌓인 공시를 함께 봅니다.",
    "krpage.overnightNote": "마지막 종가 이후 24시간 시장에서 얼마나 움직였나",
    "krpage.weekendNote": "주말에만 의미가 있는 보조 신호",
    "krpage.copy": "24시간 참고가, 공식 종가, 코스피 지수군, 국민연금 대량보유 공시를 한 페이지에서 봅니다.",
    "uspage.kicker": "US & GLOBAL MARKETS", "uspage.title": "미국·글로벌 시장.",
    "uspage.h1": "미국·글로벌", "uspage.scope": "지수 · 금리 · 유동성",
    "uspage.sub": "서울이 잠든 사이 미국 시장이 움직입니다. 지수·금리·환율은 여기서, 종목별 등락은 아래 히트맵에서 봅니다.",
    "uspage.disclose": "이 값들은 어디서 오나요?",
    "uspage.deep": "지표 자세히 보기 — 시장 위험 · 매크로 · 유동성 · 환율 · 자금시장",
    "uspage.heatmapNote": "종목 단위로 오늘 무엇이 움직였는지 봅니다",
    "uspage.stressNote": "미 재무부 OFR 공표값과 자체 합성 지수",
    "uspage.copy": "S&P 500 히트맵, 스트레스 지수, 매크로, 유동성, 공식 환율을 한 페이지에서 봅니다.",
    "cryptopage.kicker": "CRYPTO MARKETS", "cryptopage.title": "암호화폐, 가격·심리·파생을 한눈에.",
    "cryptopage.h1": "암호화폐", "cryptopage.scope": "가격 · 김프 · 심리 · 파생",
    "cryptopage.sub": "암호화폐 시장은 쉬지 않습니다. Hyperliquid 무기한선물 참고가와 업비트 원화 시세를 나란히 놓고, 지금 시장이 어느 쪽으로 얼마나 쏠려 있는지까지 봅니다.",
    "cryptopage.disclose": "이 가격은 어디서 온 값인가요?",
    "cryptopage.deep": "파생·구조 자세히 보기 — 펀딩·미결제약정 · 청산 · 변동성 · 도미넌스 · 가스",
    "cryptopage.tapeNote": "Hyperliquid 무기한선물 · 현물 거래소 시세 아님",
    "cryptopage.kimchiNote": "국내가 해외보다 얼마나 비싼가",
    "cryptopage.copy": "Hyperliquid 무기한선물 참고가, 공포·탐욕 지수, 펀딩비·미결제약정, 실현 변동성과 합성자산 상관을 한 페이지에서 봅니다. 현물 거래소 호가나 투자 권유가 아닙니다.",
    "landing.cryptoLink": "암호화폐", "landing.cryptoDesc": "BTC·ETH 퍼프 참고가 · 공포·탐욕 · 펀딩비·OI · 김치프리미엄 · 실현 변동성",
    "landing.cryptoMini.btc": "BTC 퍼프", "landing.cryptoMini.fng": "공포·탐욕",
    "crypto.tape.title": "암호화폐 24시간 참고가", "crypto.tape.copy": "Hyperliquid 자체 DEX 무기한선물의 마크가격과 24시간 변화입니다. 현물 거래소 가격·원화 시세가 아니며 유동성이 낮은 시장은 왜곡될 수 있습니다.",
    "crypto.usdOnly": "USD 기준 · 원화 아님", "crypto.noMarket": "표시할 시장 없음",
    "crypto.funding": "펀딩 (1h)", "crypto.apr": "연율", "crypto.oi": "미결제약정", "crypto.volume": "24h 거래대금", "crypto.predicted": "예상 펀딩 (연율)",
    "crypto.relayed": "Binance·Bybit 값은 Hyperliquid가 공표하는 전달값 · Mulmit은 해당 거래소를 조회하지 않음", "crypto.predictedUnavailable": "예상 펀딩 일시 미수신",
    "crypto.longsPay": "롱이 지불", "crypto.shortsPay": "숏이 지불", "crypto.balanced": "균형", "crypto.heatHigh": "과열", "crypto.heatElevated": "높음",
    "crypto.ethbtc": "ETH/BTC", "crypto.coverage": "{n}/{total} 시장",
    "crypto.fng.title": "암호화폐 공포·탐욕 지수", "crypto.fng.copy": "alternative.me가 매일 00:00 UTC에 발표하는 지수를 그대로 전달합니다. 비트코인 중심 지표이며 Mulmit 시장 심리 게이지와 정의가 달라 수치를 직접 비교할 수 없습니다.",
    "crypto.fng.scale": "0 극단적 공포 · 100 극단적 탐욕", "crypto.fng.sourceLabel": "출처", "crypto.fng.prev": "전일", "crypto.fng.week": "1주 전", "crypto.fng.month": "1개월 전", "crypto.fng.next": "다음 갱신 {time}",
    "crypto.fng.caption": "지수 구성 (발행자 공개 가중치)", "crypto.fng.colInput": "입력", "crypto.fng.colWeight": "가중치",
    "crypto.fng.vsMulmit": "참고 — Mulmit 시장 심리 게이지 {score} · {band}. 정의가 달라 두 수치는 비교 대상이 아닙니다.",
    "crypto.fng.collecting": "공포·탐욕 지수 수집 중 · 첫 수집 뒤 표시됩니다",
    "crypto.deriv.title": "펀딩비·미결제약정", "crypto.deriv.copy": "Hyperliquid 시간당 펀딩(연율 환산), 미결제약정, 거래대금과 거래소별 예상 펀딩입니다. 양수는 롱이 숏에 지불 — 롱 쏠림, 음수는 그 반대입니다.",
    "crypto.deriv.caption": "코인별 파생 지표", "crypto.colCoin": "코인", "crypto.colPrice": "가격", "crypto.col24h": "24h", "crypto.colFunding": "펀딩 1h", "crypto.colApr": "연율", "crypto.colPredicted": "예상 연율 HL · Binance · Bybit", "crypto.colOi": "OI", "crypto.colVolume": "거래대금", "crypto.colState": "상태",
    "crypto.vol.title": "실현 변동성 · 합성자산 상관", "crypto.vol.copy": "저장된 일봉 종가만으로 계산한 값입니다. 실현 변동성은 이미 일어난 변동의 크기(연율 √365)이며 옵션 내재변동성(DVOL)이 아닙니다. 상관은 같은 날짜 일간 로그수익률의 피어슨 상관이며 인과관계가 아닙니다.",
    "crypto.vol.rv": "실현 변동성 {d}일", "crypto.vol.caption": "BTC 일간 수익률과의 상관", "crypto.vol.colPeer": "대상", "crypto.vol.col30": "30일", "crypto.vol.col90": "90일", "crypto.vol.points": "{n}일",
    "crypto.kimchi.title": "김치프리미엄 · 원화 시세", "crypto.kimchi.copy": "업비트 원화 최근 체결가를 Hyperliquid 오라클 참고가와 비교합니다. 헤드라인 프리미엄은 업비트 KRW-USDT로 나눠 환율을 소거한 'USDT 기준'이고, 공식환율 기준은 한국은행 일별 고시값(날짜 표시)입니다. 호가·수수료·출금 조건은 반영하지 않습니다.",
    "crypto.kimchi.lastTrade": "업비트 최근 체결가", "crypto.kimchi.usdtBasis": "USDT 기준 · 환율 소거",
    "crypto.kimchi.usdtKrw": "USDT/KRW (업비트)", "crypto.kimchi.tether": "테더 프리미엄", "crypto.kimchi.premiumUsdt": "USDT 기준 프리미엄", "crypto.kimchi.premiumOfficial": "공식환율 기준", "crypto.kimchi.upbit24h": "업비트 24h", "crypto.kimchi.oracle": "Hyperliquid 오라클", "crypto.kimchi.volume": "업비트 24h 거래대금", "crypto.kimchi.noReference": "참고가 없음", "crypto.kimchi.official": "고시",
    "crypto.structure.title": "도미넌스 · 시장 구조", "crypto.structure.copy": "비트코인·이더리움이 전체 암호화폐 시가총액에서 차지하는 비중과 총시총·스테이블코인 시총, USDT·USDC 유통 공급입니다. CoinMarketCap 집계 유니버스 기준이며 산출 기관마다 값이 다릅니다.",
    "crypto.structure.btcDom": "BTC 도미넌스", "crypto.structure.ethDom": "ETH 도미넌스", "crypto.structure.othersDom": "기타 (100 − BTC − ETH)", "crypto.structure.totalCap": "총 시가총액", "crypto.structure.stableCap": "스테이블코인 시총", "crypto.structure.volume": "24h 거래대금", "crypto.structure.pts": "{v}p · 24h", "crypto.structure.sourceLabel": "출처", "crypto.structure.stable.title": "스테이블코인 공급 · 유동성", "crypto.structure.stable.supply": "{s} 유통 공급", "crypto.structure.stable.share": "스테이블코인 비중", "crypto.structure.stable.shareSub": "총시총 대비", "crypto.structure.stable.volume": "스테이블코인 24h 거래대금", "crypto.structure.stable.peg": "페그 {v}bp", "crypto.structure.stable.collecting": "7d 변화 수집 중", "crypto.structure.stable.history": "7d·30d 변화는 Mulmit이 {since}부터 매일 저장한 CoinMarketCap 유통 공급값으로 계산합니다({n}일 누적). 공급 증가는 발행, 감소는 상환이며 투자 권유가 아닙니다.",
    "crypto.gas.title": "가스·전송 수수료", "crypto.gas.copy": "이더리움 메인넷과 주요 L2의 다음 블록 기본 수수료·우선 수수료(50분위)와 단순 전송(21,000 gas) 비용입니다. 운영자 RPC 계정으로 읽는 공개 체인 상태이며, L2 행은 L1 데이터 수수료를 포함하지 않습니다.",
    "crypto.gas.base": "기본 수수료", "crypto.gas.priority": "우선 수수료 p50", "crypto.gas.gasPrice": "가스 가격", "crypto.gas.transfer": "단순 전송 ≈", "crypto.gas.l2note": "L1 데이터 수수료 제외", "crypto.gas.unavailable": "RPC 응답 없음",
    "crypto.board.title": "HL 전체 시장 보드", "crypto.board.copy": "Hyperliquid에 상장된 모든 무기한선물 한 스냅샷을 정렬한 보드입니다. 24h 상위·하위와 펀딩 극단값은 24h 거래대금 $1M 이상 시장만, OI·거래대금 상위는 전체가 대상입니다. 현물 가격·투자 권유가 아닙니다.",
    "crypto.board.markets": "상장 퍼프", "crypto.board.totalOi": "전체 OI", "crypto.board.totalVolume": "전체 24h 거래대금",
    "crypto.board.gainers": "24h 상위", "crypto.board.losers": "24h 하위", "crypto.board.oiLeaders": "OI 상위", "crypto.board.volumeLeaders": "거래대금 상위", "crypto.board.fundingHigh": "펀딩 최고 (롱 과열)", "crypto.board.fundingLow": "펀딩 최저 (숏 과열)",
    "crypto.board.colSymbol": "심볼", "crypto.board.colPrice": "가격", "crypto.board.colChange": "24h", "crypto.board.colOi": "OI", "crypto.board.colVolume": "거래대금", "crypto.board.colApr": "연율",
    "status.collecting": "수집 중 · 첫 수집 뒤 표시됩니다",
    "status.connecting": "연결 중", "status.live": "데이터 연결", "status.partial": "일부 데이터", "status.offline": "연결 오류",
    "status.loading": "불러오는 중", "status.viewport": "화면에 보이면 불러옵니다", "status.unavailable": "데이터 미연결",
    "status.noSeries": "표시할 시계열이 없습니다", "status.historyPending": "이력 차트 미제공 · 표시 권리 확인 중 (최신값만 표시)", "status.historyCollecting": "이력 수집 중 · 첫 수집 뒤 차트가 표시됩니다", "status.retry": "새로고침 후 다시 시도해 주세요.", "status.staleData": "지연 데이터", "status.legacyDisabled": "라이선스 데이터 전환 중 · 공개 데이터 비활성",
    "stress.eyebrow": "MULMIT 자체 산출 · 산식 공개", "stress.title": "유동성·스트레스 지수", "stress.own": "자체 산출",
    "stress.scale": "0에 가까울수록 완화, 100에 가까울수록 긴축", "stress.caption": "지수를 구성하는 입력",
    "stress.colInput": "입력", "stress.colValue": "값", "stress.colPct": "5년 내 백분위", "stress.colScore": "스트레스 점수", "stress.colDir": "방향",
    "stress.inverted": "낮을수록 스트레스", "stress.direct": "높을수록 스트레스",
    "stress.unavailable": "공개 가능한 입력이 부족해 지수를 산출하지 않습니다",
    "sentiment.eyebrow": "MULMIT 자체 산출 · 실험 · 산식 공개", "sentiment.title": "시장 심리 게이지", "sentiment.own": "자체 산출 · 실험",
    "sentiment.scale": "0에 가까울수록 위험회피, 100에 가까울수록 위험선호", "sentiment.caption": "게이지를 구성하는 입력",
    "sentiment.colInput": "입력", "sentiment.colValue": "값", "sentiment.colPct": "자기 이력 백분위", "sentiment.colScore": "위험선호 점수", "sentiment.colDir": "방향",
    "sentiment.inverted": "높을수록 위험회피", "sentiment.direct": "높을수록 위험선호",
    "sentiment.unavailable": "공개 가능한 입력이 부족해 게이지를 산출하지 않습니다", "landing.usMini.sentiment": "심리",
    "status.disabled": "표시 비활성", "status.macroDisabled": "승인된 거시 데이터 공급자가 없어 표시하지 않습니다", "status.rightsPending": "표시 권리 확인 중 · 값을 공개하지 않습니다",
    "theme.toggle": "테마 전환", "hero.kicker": "GLOBAL MARKET INTELLIGENCE", "hero.title": "한눈에 읽는 시장의 온도.",
    "hero.copy": "가격, 위험, 유동성, 거시경제를 같은 시간축에서 확인합니다. 연결되지 않은 데이터는 추정하지 않습니다.",
    "hero.updated": "마지막 갱신", "action.refresh": "새로고침", "overview.eyebrow": "MARKET TAPE", "overview.title": "시장 요약",
    "weekend.title": "Weekend Pulse · 주말 참고 신호", "weekend.notSpot": "실제 체결가 아님", "weekend.leverage": "레버리지 파생",
    "weekend.liquidity": "거래 한산 · 가격 튈 수 있음", "weekend.noPromise": "월요일 방향 보장 안 됨", "weekend.syntheticPerp": "USD 환산 합성 무기한선물",
    "weekend.defaultDisclaimer": "주말 파생시장 가격은 얕은 유동성과 레버리지의 영향을 크게 받을 수 있습니다. 월요일 현물시장 예측값으로 사용하지 마세요.",
    "weekend.nextSession": "다음 내부 세션", "weekend.awaitingSession": "세션 대기", "weekend.proxy": "대체 신호", "weekend.direct": "직접 계약", "weekend.auxiliary": "24시간 보조", "weekend.consensus": "합성 신호", "weekend.referenceSignal": "주말 기준 신호", "weekend.funding": "시간당 펀딩", "weekend.volume": "24시간 거래대금", "weekend.openInterest": "미결제약정", "weekend.status": "상태", "weekend.confidence": "근거 품질", "weekend.session": "활성 세션", "weekend.sessionChange": "세션 기준", "weekend.change24h": "24시간 기준", "weekend.stale": "지연", "weekend.reference": "참고 품질",
    "weekend.samsungPerp": "삼성전자 USD 환산 합성 무기한선물 · 한국 현물 종가와 동일한 상품이 아닙니다.",
    "uso.title": "미국 대형주, 장 밖에서는", "uso.note": "마지막 정규장 마감 이후 얼마나 움직였나",
    "uso.copy": "미국장이 닫혀 있어도 대형주를 추종하는 합성 무기한선물은 24시간 거래됩니다. 마지막 정규장 마감(16:00 ET) 시점의 퍼프 가격과 지금을 견줍니다. 현물 호가가 아니고 다음 시초가를 예측하지도 않습니다.",
    "uso.badgePerp": "USD 합성 무기한선물", "uso.sinceClose": "{date} 마감 이후",
    "uso.close": "마감 시점 퍼프", "uso.noClose": "마감 시점 값 없음",
    "uso.more": "종목 더 보기 →",
    "kridx.title": "코스피 지수군", "kridx.copy": "대표 지수와 코스피 200 섹터의 장 마감 확정값입니다. 연초 대비와 연중 최고에서 얼마나 내려와 있는지까지 한 표에서 봅니다.",
    "kridx.peakTip": "연중 최고 {value} · {date}", "kridx.peakNone": "연중 최고가 아직 공표되지 않았습니다",
    "kridx.lowNote": "연중 최저는 금융위가 확정 전 0으로 공표해 표시하지 않습니다",
    "kridx.colName": "지수", "kridx.colClose": "종가", "kridx.colDay": "전일", "kridx.colYtd": "연초 대비", "kridx.colRange": "연중 최고 대비", "kridx.colValue": "거래대금",
    "kridx.asof": "기준 {date} · 다음 영업일 13시 이후 갱신",
    "zone.kr": "한국 시장", "zone.us": "미국·글로벌 시장",
    "kro.title": "한국 주식, 장 밖에서는", "kro.copy": "장이 닫혀 있어도 합성 무기한선물은 24시간 움직입니다. 마크가격을 공식환율로 환산해 마지막 공식 종가와 비교합니다. 현물 호가나 시초가 예측이 아닙니다.",
    "kro.fxOfficial": "환율은 하루 한 번 고시값", "kro.vsClose": "{date} 마감 이후", "kro.mark": "마크", "kro.official": "공식 종가", "kro.fx": "환산 환율",
    "kro.adrRatio": "ADR 비율", "kro.noFx": "환율 미확보 · 환산 보류", "kro.noClose": "공식 종가 미확보", "kro.noMarket": "표시할 시장 없음", "kro.session": "한국장 휴장 중",
    "kro.vsSession": "{date} 15:30 이후", "kro.vsSessionNote": "퍼프 5분봉 기준 · 공식 종가 아님",
    "kro.usEtf": "미국 상장 ETF · 종가 비교 없음", "kro.leverage": "레버리지",
    "kro.vsPremium": "원주 {date} 종가 대비 프리미엄", "kro.adrImpliedNote": "마크 × {ratio}(공시 비율) × 환율 = 원주 1주 환산가 — ADR 가격 상승률이 아니라 원주 대비 괴리입니다",
    "dots.title": "연준 점도표", "dots.copy": "FOMC 위원들이 분기 SEP에서 스스로 전망한 연말 기준금리입니다. 시장 내재 확률이 아니라 위원 전망의 중앙값과 중앙경향입니다.",
    "dots.target": "전망 대상", "dots.median": "중앙값", "dots.band": "중앙경향", "dots.year": "{year}년 말", "dots.longerRun": "장기 (중립)",
    "dots.asof": "SEP {date} 기준 · 분기 FOMC(3·6·9·12월)마다 갱신 · 중앙경향은 상·하위 3명 제외 범위",
    "krpf.title": "국민연금 국내주식 포트폴리오", "krpf.copy": "국민연금공단이 공시한 국내주식 종목별 평가액과 자산군 내 비중입니다. 연 1회 갱신되는 연말 스냅샷이라 현재 보유와 다를 수 있습니다. 아래 5% 공시가 그 뒤의 변동입니다.", "krpf.asOf": "{date} 기준", "krpf.next": "다음 파일 {date} 예정", "krpf.rest": "기타", "krpf.restCount": "기타 {n}종목", "krpf.total": "평가액 합계", "krpf.count": "보유 종목", "krpf.topShare": "상위 {n}개 비중", "krpf.countValue": "{n}종목", "krpf.centerLabel": "국내주식 평가액", "krpf.colRank": "순위", "krpf.colName": "종목명", "krpf.colValue": "평가액(억원)", "krpf.colWeight": "자산군 내 비중", "krpf.colStake": "지분율", "krpf.caption": "평가액 상위 {n}종목", "krpf.weightNote": "화면의 백분율은 원자료의 값을 그대로 옮긴 것입니다. 공단의 반올림 때문에 1,200종목의 비중을 다 더하면 {sum}%가 되며, 원형 차트의 각도는 평가액으로 그렸습니다.", "krpf.tailNote": "{n}종목은 비중이 0.00%로 반올림되어 표시됩니다 — 평가액을 다 더해도 {value}으로 전체의 {pct}%입니다.", "krpf.none": "포트폴리오 파일을 읽지 못했습니다.", "krp.title": "국민연금 5% 공시", "krp.copy": "주식등의 대량보유 상황보고(5% 룰) 중 국민연금공단 제출분입니다. 보고서 단위의 보유비율 변동이며, 통상 한 달치가 월초에 일괄 공시됩니다. 일별 매매가 아닙니다.",
    "krev.colCode": "종목코드", "krp.colMarket": "시장",
    "krp.colDate": "보고일", "krp.colCompany": "회사", "krp.colRatio": "보유비율", "krp.colChange": "증감", "krp.colShares": "보유주식수", "krp.colReason": "보고사유",
    "krp.detailPending": "상세 미확보", "krp.window": "최근 {days}일 공시 {total}건 중 {count}건",
    "krh.title": "대량보유 5% 공시 — 전체 보고자", "krh.copy": "자본시장법 5% 룰에 따른 주식등의 대량보유 상황보고 전체입니다 — 운용사·펀드·대주주 모두. 보고 기한이 5영업일이라 보고일은 변동일과 다를 수 있습니다. 일별 매매가 아닙니다.",
    "krh.colReporter": "보고자", "krh.colType": "보고구분",
    "krh.window": "최근 {days}일 공시 {total}건 중 {count}건",
    "kre.title": "ETF 보드", "kre.copy": "거래대금 상위 ETF의 종가·NAV·괴리율입니다. 장 마감 확정값이며 실시간이 아닙니다.",
    "ksi.title": "종목 검색 관심도", "ksi.note": "네이버에서 평소보다 많이 찾아본 종목",
    "ksi.copy": "네이버 통합검색의 90일 검색 추이입니다. 주식 검색은 주말에 평일의 10~20%로 떨어지므로 같은 요일끼리 견줍니다. 검색량 순위가 아니라 각 종목이 자기 평소와 얼마나 다른지입니다.",
    "ksi.badgeRelative": "상대값 · 절댓값 아님", "ksi.badgeWeekday": "같은 요일끼리 비교", "ksi.badgeNotRank": "검색량 순위 아님",
    "ksi.colVs": "평소 대비", "ksi.colPercentile": "90일 위치", "ksi.colTrend": "추이", "ksi.thinSample": "표본 부족",
    "ksi.colRank": "순위", "ksi.colLevel": "관심도 수준", "ksi.anchorTag": "기준",
    "ksi.help": "×1보다 크면 평소보다 많이 찾아봤다는 뜻입니다. 요일마다 검색량이 크게 달라서 같은 요일끼리만 견줍니다.",
    "ksi.sortSpike": "평소 대비", "ksi.sortLevel": "관심도 수준",
    "ksi.anchorNote": "수준은 {name}를 100으로 둔 상대 위치입니다. 검색량의 절댓값이 아니며, 순위 변동은 전날 대비입니다.",
    "kre.colName": "종목", "kre.colClose": "종가", "kre.colDay": "등락", "kre.colNav": "NAV", "kre.colPremium": "괴리율", "kre.colIndex": "기초지수", "kre.colValue": "거래대금",
    "kre.window": "상장 {total}종목 중 거래대금 상위 {count}", "kre.asof": "기준 {date}",
    "usm.title": "13F 기관 포트폴리오", "usm.copy": "미국 증권거래위원회에 제출된 13F-HR(분기 기관 보유 신고)을 그대로 옮깁니다. 분기 말 기준이고 45일 안에 내면 되므로 현재 보유와 다를 수 있습니다. 이 서식에는 공매도·채권·현금·해외 상장 주식·사모 지분이 들어오지 않으므로, 여기 보이는 것은 자산 전부가 아니라 미국 상장주식 롱 포지션의 구성입니다. 투자 권유가 아닙니다.", "usm.centerLabel": "미국 상장주식", "usm.rest": "기타", "usm.restCount": "{n}종목", "usm.andMore": "이하 {n}종목", "usm.period": "{date} 기준", "usm.lagged": "신고 지연 {n}일", "usm.options": "옵션 {n}%", "usm.indexed": "지수 상품 {n}%", "usm.manyNames": "보유 {n}종목", "usm.noMajority": "상위 조각이 과반에 못 미침", "usm.filing": "{form} 원문", "usm.failed": "읽지 못한 신고자 {n}곳", "ptr.title": "미 하원 의원 주식 거래", "ptr.copy": "STOCK Act에 따른 주기거래보고(PTR)를 그대로 옮깁니다. 금액은 구간으로만 공시되며, 수기 제출분은 원문 링크로 안내합니다. 상원은 수집 경로가 막혀 있어 포함되지 않습니다.",
    "ev.colTicker": "티커",
    "ptr.colDistrict": "지역구", "ptr.colTicker": "티커", "ptr.colOwner": "보유자",
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
    "cal.prev": "이전 달", "cal.next": "다음 달", "cal.thisMonth": "이번 달",
    "cal.shortNote": "기관이 공표한 예정일 · 변경될 수 있습니다",
    "cal.empty": "이 달에는 예정된 발표가 없습니다.", "cal.allEvents": "전체 일정 {n}건 표로 보기",
    "sector.title": "섹터 자금 흐름", "sector.caption": "S&P 500 섹터 ETF 기간 수익률", "sector.name": "섹터", "sector.return": "수익률", "sector.interpretation": "플러스 섹터가 넓게 퍼질수록 상승 참여 폭이 넓다는 뜻입니다. ETF 수익률은 자금 유입액과 같지 않습니다.",
    "tv.title": "S&P 500 종목 히트맵", "tv.embed": "외부 위젯", "tv.notice": "이 히트맵은 TradingView가 직접 그립니다. Mulmit이 계산한 값이 아닙니다.",
    "tv.terms": "데이터·표시 조건은 제공자 정책을 따릅니다.", "corr.title": "자산군 상관관계", "corr.note": "서로 다른 시장 시간대는 동시 일간 수익률 상관을 왜곡할 수 있습니다.", "corr.scale": "+1은 같은 방향, 0은 약한 선형 관계, −1은 반대 방향입니다. 상관은 인과관계가 아닙니다.",
    "period.label": "기간", "method.title": "숫자를 다루는 원칙", "method.one.title": "숫자마다 출처가 붙습니다", "method.one.copy": "어디서 받은 값인지, 언제 기준인지, 얼마나 오래된 값인지 함께 보여줍니다.",
    "method.two.title": "단위를 바꾸지 않습니다", "method.two.copy": "받은 그대로의 단위로 보여줍니다. 보기 좋으라고 배율을 손대지 않습니다.", "method.three.title": "없는 값은 만들지 않습니다",
    "method.three.copy": "가져올 수 없는 지표는 비슷한 다른 값으로 대신하지 않습니다. 값이 없으면 왜 없는지 적습니다.", "badge.fresh": "최신", "badge.stale": "지연", "badge.missing": "미연결",
    "badge.licensed": "라이선스 필요", "badge.pendingRights": "권리 확인 중", "badge.disabled": "비활성", "badge.rights": "표시권리 확인", "badge.sourceTerms": "출처 조건", "badge.synthetic": "합성 무기한선물", "badge.perpetual": "무기한선물", "badge.proxyAlternative": "제한 지표의 대체 참고값", "notice.market": "자산 데이터 표시 조건", "date.asof": "기준", "change.previous": "직전 관측치 대비", "chart.normalized": "각 시계열 시작값 = 100으로 정규화",
    "legal.privacy": "개인정보처리방침", "legal.terms": "이용약관", "legal.disclaimer": "면책 고지", "legal.news": "신호 피드", "legal.glossary": "용어 사전",
    "legal.notAdvice": "Mulmit은 정보 제공 서비스이며 투자 자문이나 매매 권유가 아닙니다.",
    "options.copy": "정확한 지수 표시는 원 제공자의 외부 표시 권한이 필요합니다. 계약 전에는 값을 제공하지 않습니다.", "license.copy": "원 데이터 소유자의 외부 표시 권한이 필요한 지표입니다. 허가 전에는 값과 시계열을 공개하지 않습니다.",
    "pendingRights.copy": "공급자의 공개 표시 권리를 서면으로 확인하는 중입니다. 확인 전까지 값과 시계열을 공개하지 않습니다.", "notice.disabledLanes": "현재 비활성인 데이터 공급 경로",
  },
  en: {
    "brand.tagline": "MARKET SIGNALS · KR · US · CRYPTO", "nav.analytics": "Stock analytics", "nav.monitor": "Market monitor",
    "nav.home": "Home", "nav.kr": "Korea", "nav.us": "US & Global", "nav.crypto": "Crypto", "crypto.regime.title": "Market regime", "crypto.regime.copy": "A summary of how crowded the market is and which way it leans. Not a buy or sell signal — overheated does not mean a fall is coming.", "crypto.liq.title": "Liquidations", "crypto.liq.copy": "Forced liquidations over the last 24 hours, split long against short. A sum across the venues that answered — not a market-wide total. Bucketed hourly, not a live trade feed.", "crypto.liq.window": "24h liquidations", "crypto.liq.long": "Longs", "crypto.liq.short": "Shorts", "crypto.liq.hour": "Last hour", "crypto.liq.oi": "Open interest", "crypto.liq.venues": "Venues included", "crypto.liq.silent": "No data", "crypto.liq.none": "No liquidation snapshot collected yet.", "crypto.news.title": "Crypto headlines", "crypto.news.copy": "Global articles collected by GDELT whose titles name a coin. Title, source and link only — read the source for substance. Refreshed on the collection cycle, not a live wire.", "crypto.news.none": "No coin-tagged headline yet.", "crypto.news.also": "+{n} more outlets", "videos.title": "News videos", "videos.shortCopy": "The player does not load until you press play", "videos.copy": "Recent videos from news channels in the language you are reading. Thumbnails load from Google's image servers, which set no cookies. Pressing play loads the YouTube player at that moment, under YouTube's own cookies and policies. The videos are their channels' content and carry none of this site's figures.", "videos.play": "Play", "videos.playAria": "Play {title}", "videos.none": "No videos collected yet.", "videos.openOn": "Open on YouTube", "crypto.regime.change24h": "24h change", "crypto.regime.collecting": "trend collecting", "crypto.regime.heat": "Heat", "crypto.regime.trend": "Trend", "crypto.regime.sample": "Sample", "crypto.regime.sampleValue": "{n} liquid markets", "crypto.heatBadge": "heat {n}", "nav.bio": "Bio", "landing.bioLink": "Bio", "landing.bioDesc": "Clinical pipeline activity · recent FDA approvals · MFDS product approvals", "biopage.kicker": "BIOPHARMA", "biopage.title": "Biopharma — trials and approvals, as recorded.", "biopage.copy": "Clinical pipeline updates for a Korean and global biopharma watchlist (ClinicalTrials.gov) and the FDA's recent new-drug and biologic approvals (openFDA), shown as the public records state them. Not trial outcomes, not price commentary, not a recommendation.", "biopage.h1": "Biopharma", "biopage.scope": "what is next · Korea · US & global",
    "biopage.sub": "Bio names move on single decisions. So what has a date sits first, and what has already been decided is split by market. All of it is the public record as written — not an outcome, not price commentary.",
    "bio.cat.title": "What is coming", "bio.cat.note": "dated items only · soonest first",
    "bio.cat.copy": "FDA advisory committee meetings, whose dates are fixed, alongside the primary-completion dates registered for trials — one timeline, soonest first. A primary-completion date is a sponsor-entered plan that changes often, and completion is not a readout.",
    "bio.cat.badgePlan": "includes planned dates", "bio.cat.kindMeeting": "AdComm", "bio.cat.kindReadout": "Primary completion (est.)",
    "bio.cat.meetings": "Upcoming AdComms", "bio.cat.readouts90": "Primary completion (90d)", "bio.cat.window": "Window",
    "bio.cat.windowValue": "{n} days", "bio.cat.monthOnly": "(month)", "bio.cat.none": "Nothing dated inside the window.",
    "bio.cat.basis": "Meeting dates come from Federal Register notices; primary-completion dates are the ClinicalTrials.gov registered values. Registered dates are sponsor-entered plans revised often, and primary completion is not a readout date. Undated notices do not appear here.",
    "bio.zone.kr": "Korea", "bio.zone.krNote": "MFDS permits · Korean-sponsored trials",
    "bio.zone.global": "US & Global", "bio.zone.globalNote": "FDA approvals · global-sponsored trials · advisory committees",
    "bio.trials.krTitle": "Korean-sponsored trials", "bio.trials.globalTitle": "Global-sponsored trials",
    "bio.trials.note": "updated in 14 days · interventional Phase 2/3",
    "bio.trials.title": "Clinical pipeline activity", "bio.filter.all": "All", "bio.filter.kr": "Korea", "bio.filter.global": "Global", "bio.pub.link": "{n} publications", "bio.pub.linkOne": "1 publication", "bio.pub.source": "PubMed", "bio.pub.notice": "PubMed citation metadata only (title, journal, date, PMID), no abstracts · matched by registration number (NCT)", "bio.adcomm.title": "FDA advisory committee meeting notices", "bio.adcomm.copy": "FDA advisory committee meeting notices as published in the Federal Register (upcoming meetings and meetings that ended in the last 30 days). Meeting dates are extracted from each notice's DATES paragraph; the linked notice governs the final schedule. Not a committee conclusion or an approval.", "bio.adcomm.caption": "Advisory committee meeting notices (upcoming · recently ended)", "bio.adcomm.upcoming": "Upcoming", "bio.adcomm.next": "Next meeting", "bio.adcomm.recentPast": "Ended (30d)", "bio.adcomm.undated": "Undated notices", "bio.adcomm.none": "No upcoming meeting notice.", "bio.col.meeting": "Meeting", "bio.col.committee": "Committee", "bio.col.notice": "Notice", "bio.col.published": "Published", "bio.col.state": "State", "bio.adcomm.state.upcoming": "upcoming", "bio.adcomm.state.past": "ended", "bio.adcomm.state.undated": "undated", "bio.adcomm.amendment": "amendment", "bio.adcomm.daysUntil": "in {n}d", "bio.adcomm.today": "today", "bio.mfds.title": "Korea MFDS — recent drug product permits", "bio.mfds.copy": "Drug product permits from the Ministry of Food and Drug Safety (data.go.kr), collected by permit date over the trailing 30 days. The default view is 'notable' (prescription products granted a permit, new drugs, orphan drugs); the full list includes notifications and OTC products. A regulatory record, not sales or price commentary.", "bio.mfds.caption": "MFDS drug product permits (30 days)", "bio.mfds.filter.notable": "Notable", "bio.mfds.filter.permit": "Permits only", "bio.mfds.filter.all": "All", "bio.mfds.total": "Items (30d)", "bio.mfds.permit": "Permits", "bio.mfds.report": "Notifications", "bio.mfds.rx": "Prescription", "bio.mfds.newDrug": "New drugs", "bio.mfds.rare": "Orphan drugs", "bio.mfds.none": "No matching item inside the window.", "bio.mfds.failedDays": "{n} day(s) failed to load", "bio.col.permitDate": "Permit date", "bio.col.item": "Product", "bio.col.company": "Company", "bio.col.rxOtc": "Rx/OTC", "bio.col.kind": "Permit/notification", "bio.col.ingredients": "Main ingredients", "bio.mfds.flag.newDrug": "new drug", "bio.mfds.flag.rare": "orphan", "bio.mfds.flag.cancelled": "withdrawn/cancelled", "bio.trials.copy": "Interventional Phase 2/3 studies of 34 watchlist sponsors (lead sponsor) updated in the last 14 days (at most 8 per sponsor). Status, phase and dates are the ClinicalTrials.gov registered values; Korean names and listing labels are Mulmit's reference labels.", "bio.trials.caption": "Recently updated studies (interventional Phase 2/3, 14 days)", "bio.badge.registry": "Registry record · not results", "bio.badge.sponsorEntered": "Sponsor-entered", "bio.badge.notAdvice": "Not a recommendation", "bio.trials.sponsors": "Watchlist sponsors", "bio.trials.recent": "Updated (14d)", "bio.trials.registered": "Registered studies", "bio.trials.processed": "ClinicalTrials.gov processed", "bio.trials.none": "No interventional Phase 2/3 study was updated in the last 14 days.", "bio.col.sponsor": "Sponsor", "bio.col.study": "Study", "bio.col.phase": "Phase", "bio.col.status": "Status", "bio.col.updated": "Updated", "bio.col.primary": "Primary completion (est.)", "bio.col.conditions": "Conditions", "bio.col.intervention": "Intervention", "bio.status.RECRUITING": "Recruiting", "bio.status.NOT_YET_RECRUITING": "Not yet recruiting", "bio.status.ENROLLING_BY_INVITATION": "Enrolling by invitation", "bio.status.ACTIVE_NOT_RECRUITING": "Active, not recruiting", "bio.status.COMPLETED": "Completed", "bio.status.TERMINATED": "Terminated", "bio.status.WITHDRAWN": "Withdrawn", "bio.status.SUSPENDED": "Suspended", "bio.status.UNKNOWN": "Unknown", "bio.status.AVAILABLE": "Available", "bio.status.NO_LONGER_AVAILABLE": "No longer available", "bio.flag.results": "results posted", "bio.flag.stopped": "stopped", "bio.flag.completed": "completed", "bio.flag.new": "new", "bio.flag.why": "reason", "bio.phaseSuffix": "", "bio.enrollment": "enrollment {n}", "bio.fda.title": "Recent FDA approvals", "bio.fda.copy": "NDA (new drug) and BLA (biologic) applications whose original submission was approved in the last 60 days; generics (ANDA) are shown as a count. openFDA public-domain data — a regulatory record, not sales or price commentary.", "bio.fda.caption": "Recent original approvals (NDA · BLA)", "bio.fda.window": "window {s} – {e}", "bio.fda.nda": "NDA new drugs", "bio.fda.bla": "BLA biologics", "bio.fda.anda": "ANDA generics (count)", "bio.fda.priority": "priority review", "bio.fda.nme": "new molecular entities", "bio.fda.none": "No NDA/BLA approval inside the window.", "bio.fda.publisherUpdated": "openFDA data updated", "bio.col.approved": "Approved", "bio.col.application": "Application", "bio.col.product": "Product (ingredient)", "bio.col.class": "Class", "bio.col.review": "Review", "bio.review.PRIORITY": "Priority", "bio.review.STANDARD": "Standard", "bio.listingNote": "Listing labels are Mulmit reference labels", "bio.modifications": "Modifications", "bio.processedLabel": "ClinicalTrials.gov processed",
    "console.title": "Markets now", "console.scope": "Korea · US · Crypto", "console.hip3": "HIP-3 synthetic perpetuals · trade.xyz",
    "console.sub": "Samsung Electronics, SK hynix and the KOSPI 200 keep trading offshore around the clock while Seoul is shut. We show how far they have moved since the last official close, converted to won.",
    "console.disclose": "How is this price calculated?",
    "console.zones": "Go deeper", "console.zonesNote": "One page per market",
    "mode.easy": "Simple", "mode.pro": "Pro", "mode.label": "Detail level", "tape.label": "Market tape",
    "landing.kicker": "KOREA × US MARKET CONSOLE", "landing.title": "Markets move after the close.",
    "landing.title.krOpen": "Seoul is trading. It carries on here after the close.",
    "landing.title.usOpen": "Night in Seoul, open in New York.",
    "landing.title.weekend": "Even on weekends, markets move.",
    "landing.title.holiday": "Even on market holidays, markets move.",
    "session.holiday": "Market holiday",
    "presence.now": "{n} viewing", "presence.note": "Open browsers heard from in the last 90 seconds — not unique people.",
    "ev.title": "US company events (8-K)", "ev.copy": "8-K current reports for covered tickers, refreshed on the collection cycle (about hourly) — not a live wire. Titles are the standard Item headings; read the filing for substance.",
    "krev.title": "Korean company events (주요사항보고)", "krev.copy": "Material-event report filings from KOSPI and KOSDAQ listings, straight from the DART index. Titles are the filings’ own titles; refreshed on the collection cycle (about hourly), not live.",
    "feed.title": "Happening now", "feed.shortCopy": "Filings and schedule in time order · not a live newswire", "feed.copy": "Filing and schedule lanes merged into one timeline. News and fast filings refresh about every 15 minutes, other lanes hourly — not a live wire.",
    "kro.officialStrip": "Official closes", "kro.stripKospi": "KOSPI", "kro.stripKosdaq": "KOSDAQ",
    "krev.colDate": "Received", "krev.colCompany": "Company", "krev.colName": "Filing title", "krev.colLink": "Filing", "krev.view": "View",
    "ev.colDate": "Filed", "ev.colCompany": "Company", "ev.colItems": "Items", "ev.colLink": "Filing", "ev.view": "View",
    "landing.copy": "From around-the-clock references for Samsung Electronics and SK Hynix to US macro — only connected data, nothing estimated.",
    "landing.krLink": "Korea", "landing.krDesc": "24h references · official closes · KOSPI index family · ETF board · NPS 5% filings",
    "landing.usLink": "US & global", "landing.usDesc": "S&P 500 heatmap · House trades · stress index · macro · liquidity",
    "session.open": "KRX session open", "session.closed": "KRX closed", "session.until": "opens in ~{time}",
    "session.hm": "{h}h {m}m", "session.note": "Clock-based; holidays not reflected. Weekdays 09:00–15:30 KST.",
    "ticker.note": "BOK ECOS official rate · not live",
    "landing.krMini.kospi": "KOSPI 200 perp", "landing.usMini.sp500": "S&P 500 perp", "landing.usMini.stress": "Stress",
    "krpage.kicker": "KOREA MARKETS", "krpage.title": "Korean stocks, beyond market hours.",
    "krpage.h1": "Korean markets", "krpage.scope": "after hours · filings · indices",
    "krpage.sub": "Major Korean names keep trading offshore around the clock while Seoul is shut. We show how far they have moved since the last official close, in won, alongside the filings that piled up meanwhile.",
    "krpage.overnightNote": "How far it has moved in the 24h market since the last close",
    "krpage.weekendNote": "A side signal that only means something on weekends",
    "krpage.copy": "Around-the-clock references, official closes, the KOSPI index family and NPS large-holding filings on one page.",
    "uspage.kicker": "US & GLOBAL MARKETS", "uspage.title": "US & global markets.",
    "uspage.h1": "US & global", "uspage.scope": "indices · rates · liquidity",
    "uspage.sub": "US markets move while Seoul sleeps. Indices, yields and FX live here; what individual names did is in the heatmap below.",
    "uspage.disclose": "Where do these numbers come from?",
    "uspage.deep": "Detailed indicators — risk · macro · liquidity · FX · funding",
    "uspage.heatmapNote": "What moved today, name by name",
    "uspage.stressNote": "U.S. Treasury OFR readings and our own composite",
    "uspage.copy": "The S&P 500 heatmap, stress index, macro, liquidity and official FX on one page.",
    "cryptopage.kicker": "CRYPTO MARKETS", "cryptopage.title": "Crypto: price, sentiment, derivatives — one view.",
    "cryptopage.h1": "Crypto", "cryptopage.scope": "price · premium · sentiment · derivatives",
    "cryptopage.sub": "Crypto never closes. We put Hyperliquid perpetual references next to Upbit won prices, and show how far the market is leaning and which way.",
    "cryptopage.disclose": "Where do these prices come from?",
    "cryptopage.deep": "Derivatives and structure — funding, open interest, liquidations, volatility, dominance, gas",
    "cryptopage.tapeNote": "Hyperliquid perpetuals · not spot-exchange prices",
    "cryptopage.kimchiNote": "How much more Korea is paying than offshore",
    "cryptopage.copy": "Hyperliquid perpetual references, the Fear & Greed index, funding and open interest, realized volatility and correlations with the synthetic assets — on one page. Not spot-exchange quotes, not a recommendation.",
    "landing.cryptoLink": "Crypto", "landing.cryptoDesc": "BTC·ETH perp references · Fear & Greed · funding & OI · kimchi premium · realized volatility",
    "landing.cryptoMini.btc": "BTC perp", "landing.cryptoMini.fng": "Fear & Greed",
    "crypto.tape.title": "Crypto 24h references", "crypto.tape.copy": "Mark prices and 24-hour changes of perpetual futures on Hyperliquid's own DEX. Not spot-exchange prices or KRW quotes; thin markets can be distorted.",
    "crypto.usdOnly": "USD terms · not KRW", "crypto.noMarket": "No live market",
    "crypto.funding": "Funding (1h)", "crypto.apr": "APR", "crypto.oi": "Open interest", "crypto.volume": "24h volume", "crypto.predicted": "Predicted APR",
    "crypto.relayed": "Binance/Bybit figures are Hyperliquid's published relay · Mulmit does not query those venues", "crypto.predictedUnavailable": "Predicted funding temporarily unavailable",
    "crypto.longsPay": "Longs pay", "crypto.shortsPay": "Shorts pay", "crypto.balanced": "Balanced", "crypto.heatHigh": "crowded", "crypto.heatElevated": "elevated",
    "crypto.ethbtc": "ETH/BTC", "crypto.coverage": "{n}/{total} markets",
    "crypto.fng.title": "Crypto Fear & Greed Index", "crypto.fng.copy": "Relayed as alternative.me publishes it, daily at 00:00 UTC. It is bitcoin-centric and defined differently from Mulmit's own sentiment gauge, so the two numbers are not comparable.",
    "crypto.fng.scale": "0 extreme fear · 100 extreme greed", "crypto.fng.sourceLabel": "Source", "crypto.fng.prev": "Yesterday", "crypto.fng.week": "1 week ago", "crypto.fng.month": "1 month ago", "crypto.fng.next": "Next update {time}",
    "crypto.fng.caption": "Index composition (publisher's stated weights)", "crypto.fng.colInput": "Input", "crypto.fng.colWeight": "Weight",
    "crypto.fng.vsMulmit": "For reference — Mulmit Market Sentiment Gauge {score} · {band}. Different definitions: the two readings are not comparable.",
    "crypto.fng.collecting": "Collecting the Fear & Greed index · shown after the first collection",
    "crypto.deriv.title": "Funding & open interest", "crypto.deriv.copy": "Hyperliquid hourly funding (annualised), open interest, notional volume and venue-by-venue predicted funding. Positive means longs pay shorts — a long-heavy book; negative is the reverse.",
    "crypto.deriv.caption": "Derivatives metrics by coin", "crypto.colCoin": "Coin", "crypto.colPrice": "Price", "crypto.col24h": "24h", "crypto.colFunding": "Funding 1h", "crypto.colApr": "APR", "crypto.colPredicted": "Predicted APR HL · Binance · Bybit", "crypto.colOi": "OI", "crypto.colVolume": "Volume", "crypto.colState": "State",
    "crypto.vol.title": "Realized volatility · cross-asset correlation", "crypto.vol.copy": "Computed only from stored daily closes. Realized volatility measures moves that already happened (annualised by √365) and is not implied volatility (DVOL). Correlations are Pearson on same-date daily log returns, not causation.",
    "crypto.vol.rv": "Realized vol {d}d", "crypto.vol.caption": "Correlation with BTC daily returns", "crypto.vol.colPeer": "Asset", "crypto.vol.col30": "30d", "crypto.vol.col90": "90d", "crypto.vol.points": "{n}d",
    "crypto.kimchi.title": "Kimchi premium · KRW quotes", "crypto.kimchi.copy": "Upbit's last KRW trade prices against Hyperliquid's oracle reference. The headline premium is the 'USDT basis' — divided by Upbit KRW-USDT so the exchange rate cancels; the official basis uses the Bank of Korea's daily quotation (date shown). Order books, fees and withdrawal conditions are not reflected.",
    "crypto.kimchi.lastTrade": "Upbit last trade", "crypto.kimchi.usdtBasis": "USDT basis · FX cancels",
    "crypto.kimchi.usdtKrw": "USDT/KRW (Upbit)", "crypto.kimchi.tether": "Tether premium", "crypto.kimchi.premiumUsdt": "Premium (USDT basis)", "crypto.kimchi.premiumOfficial": "Official-rate basis", "crypto.kimchi.upbit24h": "Upbit 24h", "crypto.kimchi.oracle": "Hyperliquid oracle", "crypto.kimchi.volume": "Upbit 24h volume", "crypto.kimchi.noReference": "No reference price", "crypto.kimchi.official": "official",
    "crypto.structure.title": "Dominance · market structure", "crypto.structure.copy": "Bitcoin's and Ethereum's share of total crypto market cap, plus total and stablecoin market cap and USDT/USDC circulating supply. As aggregated by CoinMarketCap's universe; other publishers report different numbers.",
    "crypto.structure.btcDom": "BTC dominance", "crypto.structure.ethDom": "ETH dominance", "crypto.structure.othersDom": "Others (100 − BTC − ETH)", "crypto.structure.totalCap": "Total market cap", "crypto.structure.stableCap": "Stablecoin market cap", "crypto.structure.volume": "24h volume", "crypto.structure.pts": "{v}p · 24h", "crypto.structure.sourceLabel": "Source", "crypto.structure.stable.title": "Stablecoin supply · liquidity", "crypto.structure.stable.supply": "{s} circulating supply", "crypto.structure.stable.share": "Stablecoin share", "crypto.structure.stable.shareSub": "of total market cap", "crypto.structure.stable.volume": "Stablecoin 24h volume", "crypto.structure.stable.peg": "peg {v}bp", "crypto.structure.stable.collecting": "7d change collecting", "crypto.structure.stable.history": "7d/30d changes are computed from the CoinMarketCap circulating-supply values Mulmit has stored daily since {since} ({n} days so far). Supply growth means issuance, shrinkage means redemptions; not a recommendation.",
    "crypto.gas.title": "Gas · transfer cost", "crypto.gas.copy": "Next-block base fee and p50 priority fee on Ethereum mainnet and the main L2s, with the cost of a plain 21,000-gas transfer. Public chain state read through the operator's own RPC account; L2 rows exclude the L1 data fee.",
    "crypto.gas.base": "Base fee", "crypto.gas.priority": "Priority fee p50", "crypto.gas.gasPrice": "Gas price", "crypto.gas.transfer": "Plain transfer ≈", "crypto.gas.l2note": "excl. L1 data fee", "crypto.gas.unavailable": "No RPC response",
    "crypto.board.title": "HL market board", "crypto.board.copy": "One sorted snapshot of every perpetual listed on Hyperliquid. Movers and funding extremes consider markets with ≥ $1M 24h volume; OI and volume leaders are unfiltered. Not spot prices or recommendations.",
    "crypto.board.markets": "Listed perps", "crypto.board.totalOi": "Total OI", "crypto.board.totalVolume": "Total 24h volume",
    "crypto.board.gainers": "24h top", "crypto.board.losers": "24h bottom", "crypto.board.oiLeaders": "OI leaders", "crypto.board.volumeLeaders": "Volume leaders", "crypto.board.fundingHigh": "Highest funding (long crowded)", "crypto.board.fundingLow": "Lowest funding (short crowded)",
    "crypto.board.colSymbol": "Symbol", "crypto.board.colPrice": "Price", "crypto.board.colChange": "24h", "crypto.board.colOi": "OI", "crypto.board.colVolume": "Volume", "crypto.board.colApr": "APR",
    "status.collecting": "Collecting · shown after the first collection",
    "status.connecting": "Connecting", "status.live": "Data live", "status.partial": "Partial data", "status.offline": "Connection error",
    "status.loading": "Loading", "status.viewport": "Loads when scrolled into view", "status.unavailable": "Data not connected",
    "status.noSeries": "No series available", "status.historyPending": "History chart withheld while display rights are confirmed · latest value only", "status.historyCollecting": "Collecting history · the chart appears after the first collection", "status.retry": "Refresh and try again.", "status.staleData": "Stale data", "status.legacyDisabled": "Public data disabled during licensed-provider migration",
    "stress.eyebrow": "MULMIT COMPOSITE · PUBLISHED METHOD", "stress.title": "Liquidity & Stress Index", "stress.own": "Own composite",
    "stress.scale": "Lower is looser, higher is tighter", "stress.caption": "Inputs that make up the index",
    "stress.colInput": "Input", "stress.colValue": "Value", "stress.colPct": "5-year percentile", "stress.colScore": "Stress score", "stress.colDir": "Direction",
    "stress.inverted": "Lower means more stress", "stress.direct": "Higher means more stress",
    "stress.unavailable": "Too few publishable inputs to compose the index",
    "sentiment.eyebrow": "MULMIT COMPOSITE · EXPERIMENTAL · PUBLISHED METHOD", "sentiment.title": "Market Sentiment Gauge", "sentiment.own": "Own composite · experimental",
    "sentiment.scale": "Lower is risk-off, higher is risk-on", "sentiment.caption": "Inputs that make up the gauge",
    "sentiment.colInput": "Input", "sentiment.colValue": "Value", "sentiment.colPct": "Own-history percentile", "sentiment.colScore": "Risk-appetite score", "sentiment.colDir": "Direction",
    "sentiment.inverted": "Higher means risk-off", "sentiment.direct": "Higher means risk-on",
    "sentiment.unavailable": "Too few publishable inputs to compose the gauge", "landing.usMini.sentiment": "Sentiment",
    "status.disabled": "Display disabled", "status.macroDisabled": "No approved macro data provider is enabled", "status.rightsPending": "Display rights unconfirmed · values withheld",
    "theme.toggle": "Toggle theme", "hero.kicker": "GLOBAL MARKET INTELLIGENCE", "hero.title": "Read the market in one view.",
    "hero.copy": "Track prices, risk, liquidity and macro conditions on a shared timeline. Missing data is never estimated.",
    "hero.updated": "Last updated", "action.refresh": "Refresh", "overview.eyebrow": "MARKET TAPE", "overview.title": "Market overview",
    "weekend.title": "Weekend Pulse · Reference signals", "weekend.notSpot": "Not an executable price", "weekend.leverage": "Leveraged derivatives",
    "weekend.liquidity": "Thin trading · price can jump", "weekend.noPromise": "No Monday direction guarantee", "weekend.syntheticPerp": "USD-converted synthetic perpetuals",
    "weekend.defaultDisclaimer": "Weekend derivative prices can be heavily affected by shallow liquidity and leverage. Do not treat them as Monday spot-market forecasts.",
    "weekend.nextSession": "Next internal session", "weekend.awaitingSession": "Awaiting session", "weekend.proxy": "Proxy", "weekend.direct": "Direct contract", "weekend.auxiliary": "24h auxiliary", "weekend.consensus": "Composite", "weekend.referenceSignal": "Weekend reference", "weekend.funding": "Hourly funding", "weekend.volume": "24h notional", "weekend.openInterest": "Open interest", "weekend.status": "Status", "weekend.confidence": "Evidence quality", "weekend.session": "Active session", "weekend.sessionChange": "Session change", "weekend.change24h": "24-hour change", "weekend.stale": "Stale", "weekend.reference": "Reference quality",
    "weekend.samsungPerp": "Samsung Electronics USD-converted synthetic perpetual · not the Korean spot close.",
    "uso.title": "US large caps, outside the session", "uso.note": "how far they moved since the last close",
    "uso.copy": "Even with the US market shut, synthetic perpetuals tracking these names trade around the clock. Each card compares the mark now with the mark at the last regular-session close (16:00 ET). Not a spot quote, and not a prediction of the next open.",
    "uso.badgePerp": "USD synthetic perpetual", "uso.sinceClose": "since the {date} close",
    "uso.close": "Mark at close", "uso.noClose": "No value at the close",
    "uso.more": "More names →",
    "kridx.title": "KOSPI index family", "kridx.copy": "Confirmed closes for the headline indices and KOSPI 200 sectors, with year-to-date change and how far each sits below its high for the year.",
    "kridx.peakTip": "High for the year {value} · {date}", "kridx.peakNone": "No high published yet for this index",
    "kridx.lowNote": "The year's low is published as 0 until it is finalised, so it is not shown",
    "kridx.colName": "Index", "kridx.colClose": "Close", "kridx.colDay": "Day", "kridx.colYtd": "YTD", "kridx.colRange": "vs YTD high", "kridx.colValue": "Value traded",
    "kridx.asof": "As of {date} · updates after 13:00 KST the next business day",
    "zone.kr": "Korea markets", "zone.us": "US & global markets",
    "kro.title": "Korean stocks, after hours", "kro.copy": "Synthetic perpetuals keep trading around the clock. Marks are converted at the official exchange rate and compared with the last official close. Not spot quotes, not an open forecast.",
    "kro.fxOfficial": "Converted at the daily official FX rate", "kro.vsClose": "since the {date} close", "kro.mark": "Mark", "kro.official": "Official close", "kro.fx": "FX applied",
    "kro.adrRatio": "ADR ratio", "kro.noFx": "No official FX yet · conversion withheld", "kro.noClose": "Official close unavailable", "kro.noMarket": "No live market", "kro.session": "Korea market closed",
    "kro.vsSession": "since {date} 15:30 KST", "kro.vsSessionNote": "Perp 5-minute candle basis · not an official close",
    "kro.usEtf": "US-listed ETF · no close comparison", "kro.leverage": "leveraged",
    "kro.vsPremium": "premium vs ordinary {date} close", "kro.adrImpliedNote": "Mark × {ratio} (disclosed ratio) × FX = per-ordinary-share equivalent — a cross-listing premium, not the ADR's price change",
    "dots.title": "Fed dot plot", "dots.copy": "Year-end fed funds projections FOMC participants publish themselves in the quarterly SEP — the committee's own medians and central tendency, not market-implied odds.",
    "dots.target": "Target", "dots.median": "Median", "dots.band": "Central tendency", "dots.year": "End of {year}", "dots.longerRun": "Longer run (neutral)",
    "dots.asof": "As of the {date} SEP · updates at quarterly FOMCs (Mar·Jun·Sep·Dec) · central tendency trims the three highest and lowest",
    "krpf.title": "NPS domestic equity portfolio", "krpf.copy": "Domestic equity holdings published by the National Pension Service: market value and share of the domestic-equity book. A year-end snapshot updated once a year, so it may differ from current holdings. The 5% filings below are what moved since.", "krpf.asOf": "As of {date}", "krpf.next": "Next file due {date}", "krpf.rest": "Others", "krpf.restCount": "{n} other holdings", "krpf.total": "Total market value", "krpf.count": "Holdings", "krpf.topShare": "Top {n} share", "krpf.countValue": "{n} names", "krpf.centerLabel": "Domestic equity", "krpf.colRank": "Rank", "krpf.colName": "Name", "krpf.colValue": "Market value (KRW 100M)", "krpf.colWeight": "Share of book", "krpf.colStake": "Stake in company", "krpf.caption": "Top {n} holdings by market value", "krpf.weightNote": "Percentages are relayed verbatim from the source. After the publisher rounding, all 1,200 holdings sum to {sum}%; the pie angles are drawn from market value instead.", "krpf.tailNote": "{n} holdings round to 0.00% — together they are {value}, {pct}% of the book.", "krpf.none": "Portfolio file could not be read.", "krp.title": "NPS 5% filings", "krp.copy": "Large-holding (5% rule) reports filed by the National Pension Service. Report-level stake changes, usually filed as one early-month batch covering the prior month — not daily trades.",
    "krh.title": "5% filings — all filers", "krh.copy": "Every large-holding (5% rule) report: asset managers, funds, major shareholders. The filing deadline is five business days, so the report date can trail the change — not daily trades.",
    "krh.colReporter": "Filer", "krh.colType": "Type",
    "krh.window": "{count} of {total} filings in the last {days} days",
    "krev.colCode": "Code", "krp.colMarket": "Market",
    "krp.colDate": "Filed", "krp.colCompany": "Company", "krp.colRatio": "Stake", "krp.colChange": "Change", "krp.colShares": "Shares held", "krp.colReason": "Reason",
    "krp.detailPending": "Detail pending", "krp.window": "{count} of {total} filings in the last {days} days",
    "kre.title": "ETF board", "kre.copy": "Top ETFs by traded value with close, NAV and the premium/discount. Confirmed end-of-day values, not live quotes.",
    "ksi.title": "Search interest by stock", "ksi.note": "Looked up more than usual on NAVER",
    "ksi.copy": "NAVER integrated-search interest over 90 days. Stock searches fall to 10-20% of weekday levels at weekends, so each day is compared with the same weekday. This is not a search-volume ranking — it shows how far each stock sits from its own normal.",
    "ksi.badgeRelative": "Relative, not absolute", "ksi.badgeWeekday": "Same weekday compared", "ksi.badgeNotRank": "Not a volume ranking",
    "ksi.colVs": "vs usual", "ksi.colPercentile": "90-day position", "ksi.colTrend": "Trend", "ksi.thinSample": "Too few samples",
    "ksi.colRank": "Rank", "ksi.colLevel": "Interest level", "ksi.anchorTag": "baseline",
    "ksi.help": "Above ×1 means people looked it up more than usual. Search volume swings by weekday, so each day is compared with the same weekday.",
    "ksi.sortSpike": "vs usual", "ksi.sortLevel": "Interest level",
    "ksi.anchorNote": "Level is measured against {name} at 100. It is not an absolute search count, and rank moves are against the previous day.",
    "kre.colName": "Fund", "kre.colClose": "Close", "kre.colDay": "Day", "kre.colNav": "NAV", "kre.colPremium": "Premium", "kre.colIndex": "Underlying index", "kre.colValue": "Value traded",
    "kre.window": "Top {count} of {total} listed, by traded value", "kre.asof": "As of {date}",
    "usm.title": "13F institutional portfolios", "usm.copy": "Form 13F-HR quarterly institutional holdings, relayed verbatim from the SEC. Positions are as of quarter end and may be filed up to 45 days later, so they may differ from current holdings. The form excludes short positions, bonds, cash, non-US listings and private stakes, so this is the composition of a US-listed long book, not a whole portfolio. Not investment advice.", "usm.centerLabel": "US-listed long book", "usm.rest": "Others", "usm.restCount": "{n} names", "usm.andMore": "{n} more named", "usm.period": "As of {date}", "usm.lagged": "{n} days since quarter end", "usm.options": "Options {n}%", "usm.indexed": "Index products {n}%", "usm.manyNames": "{n} holdings", "usm.noMajority": "Named slices are not a majority", "usm.filing": "{form} filing", "usm.failed": "{n} filers unread", "ptr.title": "US House stock trades", "ptr.copy": "Periodic transaction reports under the STOCK Act, relayed verbatim. Amounts are disclosed only as ranges; scanned paper filings link to the original. The Senate is not included because its portal blocks server collection.",
    "ev.colTicker": "Ticker",
    "ptr.colDistrict": "District", "ptr.colTicker": "Ticker", "ptr.colOwner": "Owner",
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
    "cal.prev": "Previous month", "cal.next": "Next month", "cal.thisMonth": "This month",
    "cal.shortNote": "As announced by the institutions · dates can change",
    "cal.empty": "No scheduled releases this month.", "cal.allEvents": "All {n} dates as a table",
    "sector.title": "Sector flow", "sector.caption": "S&P 500 sector ETF period returns", "sector.name": "Sector", "sector.return": "Return", "sector.interpretation": "Broader positive participation can confirm a wider advance. ETF returns are not the same thing as fund-flow dollars.",
    "tv.title": "S&P 500 constituent heatmap", "tv.embed": "Third-party widget", "tv.notice": "TradingView serves this embed directly; it is not Mulmit API data.",
    "tv.terms": "Provider data and display terms apply.", "corr.title": "Cross-asset correlation", "corr.note": "Different market hours can distort same-day return correlations.", "corr.scale": "+1 moves together, 0 indicates a weak linear link, and −1 moves oppositely. Correlation is not causation.",
    "period.label": "Period", "method.title": "How we handle numbers", "method.one.title": "Every number names its source", "method.one.copy": "You can see where a value came from, what date it is for, and how old it is.",
    "method.two.title": "Units stay as published", "method.two.copy": "We show the units we received. Nothing is rescaled to look neater.", "method.three.title": "No invented numbers",
    "method.three.copy": "When a figure cannot be fetched we do not substitute something similar. If it is missing, we say why.", "badge.fresh": "Fresh", "badge.stale": "Stale", "badge.missing": "Not connected",
    "badge.licensed": "License required", "badge.pendingRights": "Rights pending", "badge.disabled": "Disabled", "badge.rights": "Display rights", "badge.sourceTerms": "Source terms", "badge.synthetic": "Synthetic perpetual", "badge.perpetual": "Perpetual", "badge.proxyAlternative": "Alternative to restricted series", "notice.market": "Asset-data display terms", "date.asof": "As of", "change.previous": "vs previous observation", "chart.normalized": "Each series rebased to 100 at start",
    "legal.privacy": "Privacy policy", "legal.terms": "Terms of use", "legal.disclaimer": "Disclaimer", "legal.news": "Signal feed", "legal.glossary": "Glossary",
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
  dollar_index_broad: { aliases: ["dollar_index_broad", "jrxwtfb_n.b"], label: LABEL("광의 달러지수", "Broad dollar index"), group: "macro", format: "number", accent: "#a78bfa", description: LABEL("연준이 교역량으로 가중한 달러 강세 지표. ICE 달러지수(DXY)와 값을 비교할 수 없습니다", "The Fed's trade-weighted dollar index — its level is not comparable with ICE's DXY") , term: "dollar-index"},
  dollar_index_afe: { aliases: ["dollar_index_afe", "jrxwtfn_n.b"], label: LABEL("선진국 달러지수", "AFE dollar index"), group: "macro", format: "number", accent: "#a78bfa", description: LABEL("선진 교역상대국 통화 대비 달러", "The dollar against advanced foreign economies") , term: "dollar-index"},
  dollar_index_eme: { aliases: ["dollar_index_eme", "jrxwtfo_n.b"], label: LABEL("신흥국 달러지수", "EME dollar index"), group: "macro", format: "number", accent: "#a78bfa", description: LABEL("신흥 교역상대국 통화 대비 달러", "The dollar against emerging market economies") , term: "dollar-index"},
  kr_base_rate: { aliases: ["kr_base_rate", "ecos_722y001"], label: LABEL("한국은행 기준금리", "BOK base rate"), group: "korea", format: "number", accent: "#2dd4a3", description: LABEL("한국은행 금융통화위원회가 결정하는 정책금리", "The Bank of Korea's policy rate, set by the Monetary Policy Board") },
  kr_unemployment: { aliases: ["kr_unemployment", "ecos_901y027"], label: LABEL("실업률 (한국)", "Korea unemployment"), group: "korea", format: "number", accent: "#f5b942", description: LABEL("경제활동인구조사 실업률 — 한국은행 ECOS 제공", "Unemployment rate from the economically active population survey, via ECOS") },
  kr_cpi: { aliases: ["kr_cpi", "ecos_901y009"], label: LABEL("소비자물가지수 (한국)", "Korea CPI"), group: "korea", format: "number", accent: "#42a5ff", description: LABEL("소비자물가지수 총지수(2020=100) — 한국은행 ECOS 제공", "Korean CPI, all items (2020=100), via the Bank of Korea's ECOS") },
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
  sentiment: { aliases: ["sentiment", "market_sentiment", "mulmit_sentiment"], label: LABEL("시장 심리 게이지 (실험)", "Market sentiment gauge (experimental)"), group: "risk", format: "number", changeMode: "points", accent: "#fb7185", description: LABEL("Mulmit 자체 산출 0–100 게이지. OFR 변동성·신용 스트레스와 HIP-3 퍼프 모멘텀·실현 변동성·주식 대 금을 자기 이력 백분위로 점수화해 동일 가중 평균합니다. CNN Fear & Greed가 아닙니다.", "Mulmit's own 0–100 gauge: OFR volatility and credit stress plus HIP-3 perp momentum, realized volatility and equity-vs-gold, each scored as an own-history percentile and equally weighted. Not CNN's Fear & Greed.") },
  yield_curve: { aliases: ["yield_curve", "t10y2y", "yield_spread"], label: LABEL("장단기 금리차", "10Y–2Y curve"), group: "risk", format: "percentPoints", accent: "#fb7185", term: "yield-curve"},
  ofr_fsi: { aliases: ["ofr_fsi"], label: LABEL("OFR 금융스트레스 (종합)", "OFR financial stress"), group: "risk", format: "number", changeMode: "points", accent: "#fb7185", term: "stress-index"},
  ofr_fsi_volatility: { aliases: ["ofr_fsi_volatility"], label: LABEL("변동성 스트레스 (OFR)", "Volatility stress (OFR)"), group: "risk", format: "number", changeMode: "points", accent: "#fb7185" },
  ofr_fsi_credit: { aliases: ["ofr_fsi_credit"], label: LABEL("신용 스트레스 (OFR)", "Credit stress (OFR)"), group: "risk", format: "number", changeMode: "points", accent: "#fb7185" },
  sp500_realized_vol: { aliases: ["sp500_realized_vol"], label: LABEL("S&P 500 퍼프 실현 변동성 (20일)", "S&P 500 perp realized vol (20d)"), group: "risk", format: "percentPoints", changeMode: "points", accent: "#fb7185", term: "realized-vol"},
  kr200_realized_vol: { aliases: ["kr200_realized_vol"], label: LABEL("KR200 퍼프 실현 변동성 (20일)", "KR200 perp realized vol (20d)"), group: "risk", format: "percentPoints", changeMode: "points", accent: "#fb7185", term: "realized-vol"},
  high_yield_spread: { aliases: ["high_yield_spread", "bamlh0a0hym2"], label: LABEL("하이일드 스프레드", "High-yield spread"), group: "risk", format: "percentPoints", accent: "#fb7185", term: "high-yield-spread"},
  financial_stress: { aliases: ["financial_stress", "stlfsi4"], label: LABEL("금융스트레스", "Financial stress"), group: "risk", format: "number", changeMode: "points", accent: "#fb7185", term: "stress-index"},
  recession_prob: { aliases: ["recession_prob", "rec_prob_12m"], label: LABEL("미국 침체 확률 (12개월 선행)", "US recession odds (12M ahead)"), group: "risk", format: "number", accent: "#fb7185", description: LABEL("뉴욕 연은이 국채 10년–3개월 스프레드로 추정한 12개월 뒤 침체 확률 — 날짜는 예측 대상 월", "NY Fed treasury-spread model: probability of a U.S. recession twelve months ahead — dates mark the predicted month") , term: "recession-prob"},
  dxy: { aliases: ["dxy", "dollar_index"], label: LABEL("달러인덱스", "Dollar index"), group: "macro", format: "number", accent: "#a78bfa", term: "dollar-index"},
  usdjpy: { aliases: ["usdjpy", "jpy=x", "usd/jpy"], label: LABEL("달러·엔", "USD/JPY"), group: "macro", format: "currency", currency: "JPY", accent: "#a78bfa" },
  treasury_10y: { aliases: ["treasury_10y", "dgs10", "us10y"], label: LABEL("미국 10년물", "US 10-year yield"), group: "macro", format: "percentPoints", changeMode: "points", accent: "#a78bfa" },
  wti: { aliases: ["wti", "dcoilwtico", "cl=f"], label: LABEL("WTI 원유", "WTI crude"), group: "macro", format: "currency", currency: "USD", accent: "#a78bfa" },
  copper: { aliases: ["copper", "pcoppusdm", "hg=f"], label: LABEL("구리", "Copper"), group: "macro", format: "number", accent: "#a78bfa" },
  unemployment: { aliases: ["unemployment", "unrate"], label: LABEL("미국 실업률", "US unemployment"), group: "macro", format: "percentPoints", accent: "#a78bfa" },
  initial_claims: { aliases: ["initial_claims", "icsa"], label: LABEL("신규 실업수당", "Initial claims"), group: "macro", format: "compact", accent: "#a78bfa" },
  fed_assets: { aliases: ["fed_assets", "walcl"], label: LABEL("연준 총자산", "Fed total assets"), group: "liquidity", format: "compact", accent: "#38bdf8", term: "fed-balance-sheet"},
  reserve_balances: { aliases: ["reserve_balances", "wresbal", "reserves"], label: LABEL("지급준비금", "Reserve balances"), group: "liquidity", format: "compact", accent: "#38bdf8", term: "reserves"},
  reverse_repo: { aliases: ["reverse_repo", "rrp", "rrpontsyd"], label: LABEL("역레포 RRP", "Reverse repo (RRP)"), group: "liquidity", format: "compact", accent: "#38bdf8", term: "reverse-repo"},
  treasury_general_account: { aliases: ["treasury_general_account", "tga", "wtregen"], label: LABEL("재무부 TGA", "Treasury General Account"), group: "liquidity", format: "compact", accent: "#38bdf8", term: "tga"},
  m2: { aliases: ["m2", "m2sl"], label: LABEL("미국 M2", "US M2"), group: "liquidity", format: "compact", accent: "#38bdf8" },
  retail_money_market_funds: { aliases: ["retail_money_market_funds", "wrmfns", "mmf"], label: LABEL("리테일 MMF", "Retail money market funds"), group: "liquidity", format: "compact", accent: "#38bdf8" },
  fx_usdkrw: { aliases: ["fx_usdkrw", "rxi_n.b.ko"], label: LABEL("원·달러", "USD/KRW"), group: "fx", format: "rate", accent: "#2dd4a3", description: LABEL("달러 한 단위당 원화. 한국은행 ECOS 매매기준율입니다.", "Korean won per US dollar — the Bank of Korea's official ECOS trading-reference rate.") },
  fx_usdjpy: { aliases: ["fx_usdjpy", "rxi_n.b.ja"], label: LABEL("엔·달러", "USD/JPY"), group: "fx", format: "rate", accent: "#a78bfa", description: LABEL("달러 한 단위당 엔화", "Japanese yen per US dollar") },
  fx_usdcny: { aliases: ["fx_usdcny", "rxi_n.b.ch"], label: LABEL("위안·달러", "USD/CNY"), group: "fx", format: "rate", accent: "#f5b942", description: LABEL("달러 한 단위당 위안화", "Chinese yuan per US dollar") },
  fx_eurusd: { aliases: ["fx_eurusd", "rxi$us_n.b.eu"], label: LABEL("유로·달러", "EUR/USD"), group: "fx", format: "rate", accent: "#38bdf8", description: LABEL("유로 한 단위당 달러. 위 세 개와 방향이 반대입니다.", "US dollars per euro — quoted the opposite way round to the three above.") },
  fx_gbpusd: { aliases: ["fx_gbpusd", "rxi$us_n.b.uk"], label: LABEL("파운드·달러", "GBP/USD"), group: "fx", format: "rate", accent: "#fb7185", description: LABEL("파운드 한 단위당 달러. 위 세 개와 방향이 반대입니다.", "US dollars per British pound — quoted the opposite way round to the three above.") },
  sofr: { aliases: ["sofr"], label: LABEL("SOFR", "SOFR"), group: "funding", format: "percentPoints", changeMode: "points", accent: "#2dd4a3", term: "sofr"},
  effective_fed_funds: { aliases: ["effective_fed_funds", "effr"], label: LABEL("실효 연방기금금리", "Effective fed funds"), group: "funding", format: "percentPoints", accent: "#2dd4a3" },
  reserve_interest: { aliases: ["reserve_interest", "iorb"], label: LABEL("지급준비금 이자율", "IORB"), group: "funding", format: "percentPoints", changeMode: "points", accent: "#2dd4a3" },
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
  sentiment: {
    hints: [LABEL("0~20 위험회피 강함 · 40~60 중립 · 80~100 위험선호 강함", "0–20 strong risk-off · 40–60 neutral · 80–100 strong risk-on"), LABEL("실험 지수 — 예측이 아니며 다른 심리 지수와 값 비교 불가", "Experimental — not a forecast and not comparable with other sentiment indexes")],
  },
  ofr_fsi: {
    description: LABEL("미 재무부 금융연구국(OFR)이 33개 시장 변수로 매일 산출하는 글로벌 금융 스트레스 종합지수입니다. 2영업일 지연 공표.", "The U.S. Treasury's Office of Financial Research builds this daily composite from 33 market variables; published with a two-business-day lag."),
    hints: [LABEL("0 = 평균 스트레스, 양수 = 평균 이상, 음수 = 평균 이하", "0 = average stress; positive above average, negative below"), LABEL("다섯 범주(신용·주식 밸류에이션·자금조달·안전자산·변동성)의 합", "The sum of five categories: credit, equity valuation, funding, safe assets, volatility")],
  },
  ofr_fsi_volatility: {
    description: LABEL("OFR 금융스트레스지수의 변동성 범주 — 주식·신용·외환·원자재의 내재·실현 변동성 기여분입니다. Cboe VIX 값 자체가 아닙니다.", "The volatility category of the OFR FSI — implied and realised volatility across equity, credit, FX and commodity markets. Not the Cboe VIX value itself."),
    hints: [LABEL("양수로 올라서면 변동성 가격이 평균 이상으로 뛴 상태", "Rising above zero: volatility pricing above its average"), LABEL("급등은 위험회피 국면과 함께 나타나는 경향", "Spikes tend to accompany risk-off episodes")],
  },
  ofr_fsi_credit: {
    description: LABEL("OFR 금융스트레스지수의 신용 범주 — 신용 스프레드 기여분입니다. 개별 하이일드 스프레드 값이 아닙니다.", "The credit category of the OFR FSI — credit-spread contributions. Not an individual high-yield spread."),
    hints: [LABEL("양수 확대는 신용시장 경계 심화", "Widening above zero: credit caution deepening"), LABEL("음수 지속은 차분한 신용 여건 참고 구간", "Sustained negative: a calm-credit reference range")],
  },
  sp500_realized_vol: {
    description: LABEL("위 S&P 500 합성 무기한선물의 최근 일봉 종가 20개로 계산한 실현 변동성(연율화 √252)입니다. 옵션 내재변동성인 VIX가 아니며, 이미 일어난 가격 변동의 크기만 보여줍니다.", "Realized volatility from the last 20 daily closes of the S&P 500 synthetic perpetual above, annualized by √252. Not the VIX (implied volatility): it measures moves that already happened."),
    hints: [LABEL("상승: 최근 20일 일일 변동 폭이 커진 상태", "Rising: daily swings over the last 20 days have widened"), LABEL("VIX와 수준을 직접 비교하지 않음 — 실현치와 내재치는 다른 양", "Do not compare levels with the VIX — realized and implied are different quantities")],
  },
  kr200_realized_vol: {
    description: LABEL("xyz:KR200 합성 무기한선물의 최근 일봉 종가 20개로 계산한 실현 변동성(연율화 √252)입니다. VKOSPI 같은 내재변동성 지수가 아닙니다.", "Realized volatility from the last 20 daily closes of the xyz:KR200 synthetic perpetual, annualized by √252. Not an implied-volatility index such as VKOSPI."),
    hints: [LABEL("상승: 최근 20일 일일 변동 폭이 커진 상태", "Rising: daily swings over the last 20 days have widened")],
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
  fx_usdkrw: { aliases: ["fx_usdkrw", "rxi_n.b.ko"], label: LABEL("원·달러", "USD/KRW"), group: "fx", format: "rate", accent: "#2dd4a3", description: LABEL("달러 한 단위당 원화. 한국은행 ECOS 매매기준율입니다.", "Korean won per US dollar — the Bank of Korea's official ECOS trading-reference rate.") },
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
  { id: "emerging", label: LABEL("글로벌 ETF", "Global ETFs"), keys: ["ewz", "inda", "vnm", "ewj"] },
  { id: "risk", label: LABEL("시장 위험", "Market risk"), keys: ["sentiment", "ofr_fsi_volatility", "ofr_fsi_credit", "yield_curve", "recession_prob"] },
  { id: "fx", label: LABEL("환율", "Exchange rates"), keys: ["fx_usdkrw", "fx_usdjpy", "fx_eurusd", "fx_usdcny"] },
  { id: "macro", label: LABEL("매크로", "Macro"), keys: ["dollar_index_broad", "usdjpy", "treasury_10y", "wti"] },
  { id: "liquidity", label: LABEL("유동성", "Liquidity"), keys: ["fed_assets", "reserve_balances", "reverse_repo", "treasury_general_account"] },
  { id: "options", label: LABEL("옵션 위험", "Options risk"), keys: ["skew", "vvix", "ovx", "pcr"] },
];

const SECTIONS = [
  // 한국 공식 종가 히어로 섹션은 2026-08-19 제거: T+1 확정값이 실시간처럼 생긴
  // 큰 카드로 나가 장중마다 오독을 낳았다(8/14 기준일, −1.55% 소동). 기준선
  // 역할은 kr-overnight 카드의 메타 행이, 기록은 kr-indices 표와 분석 페이지가 맡는다.
  { id: "kr-macro", zone: "kr", eyebrow: "KOREA · MACRO · BANK OF KOREA ECOS", title: LABEL("한국 매크로", "Korea macro"), copy: LABEL("한국은행 경제통계시스템(ECOS)의 공식 통계입니다. 기준금리와 소비자물가부터 시작합니다.", "Official statistics from the Bank of Korea's ECOS — starting with the base rate and CPI."), keys: ["kr_base_rate", "kr_cpi", "kr_unemployment"] },
  { id: "global-assets", zone: "us", eyebrow: "GLOBAL PRICES", title: LABEL("글로벌 자산", "Global assets"), copy: LABEL("전고점 대비 위치와 최근 가격 흐름을 함께 봅니다.", "View recent prices alongside distance from prior highs."), keys: ["sp500", "nasdaq", "gold", "bitcoin"] },
  { id: "global-etfs", zone: "us", eyebrow: "CROSS-BORDER ETFs", title: LABEL("글로벌 지역 ETF", "Regional ETFs"), copy: LABEL("미국 상장 ETF를 통해 지역별 위험선호를 확인합니다.", "Use US-listed ETFs to compare regional risk appetite."), keys: ["ewz", "inda", "vnm", "ewj"] },
  { id: "market-risk", zone: "us", eyebrow: "RISK & CREDIT", title: LABEL("시장 위험과 신용", "Risk and credit"), copy: LABEL("변동성·신용 스트레스(미 재무부 OFR)·금리곡선·금융스트레스·침체 확률을 나란히 봅니다.", "Compare volatility and credit stress (U.S. Treasury OFR), the yield curve, financial stress and recession odds."), keys: ["sentiment", "ofr_fsi_volatility", "ofr_fsi_credit", "sp500_realized_vol", "ofr_fsi", "yield_curve", "financial_stress", "recession_prob", "vix", "high_yield_spread"] },
  { id: "macro-regime", zone: "us", eyebrow: "MACRO REGIME", title: LABEL("매크로 환경", "Macro regime"), copy: LABEL("달러·금리·원자재·고용의 방향을 확인합니다.", "Track the dollar, rates, commodities and labor conditions."), keys: ["dollar_index_broad", "dxy", "usdjpy", "treasury_10y", "wti", "copper", "unemployment", "initial_claims"] },
  { id: "liquidity", zone: "us", eyebrow: "FED & LIQUIDITY", title: LABEL("유동성 대차대조표", "Liquidity balance sheet"), copy: LABEL("연준·재무부·단기자금시장 유동성의 크기와 흐름입니다.", "Monitor Federal Reserve, Treasury and money-market liquidity."), keys: ["fed_assets", "reserve_balances", "reverse_repo", "treasury_general_account", "m2", "retail_money_market_funds"] },
  { id: "exchange-rates", zone: "us", eyebrow: "OFFICIAL FX · BOK ECOS × FED H.10", title: LABEL("환율", "Exchange rates"), copy: LABEL("원·달러, 엔·달러, 유로·달러, 파운드·달러는 한국은행 ECOS의 일별 고시(당일 반영), 위안·달러와 달러지수는 미 연준 H.10 주간 릴리스입니다. 앞의 세 개는 달러당 외화, 뒤의 두 개는 외화당 달러로 방향이 반대입니다.", "USD/KRW, USD/JPY, EUR/USD and GBP/USD are the Bank of Korea's daily ECOS quotations (same-day); USD/CNY and the dollar indexes come from the Fed's weekly H.10 release. The first three are foreign currency per dollar; the last two are quoted the other way round."), keys: ["fx_usdkrw", "fx_usdjpy", "fx_usdcny", "fx_eurusd", "fx_gbpusd", "dollar_index_afe", "dollar_index_eme"] },
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
  stress: null, sentiment: null, cryptoOverview: null, cryptoSentiment: null, cryptoVolatility: null, cryptoKimchi: null, cryptoStructure: null, cryptoGas: null, cryptoBoard: null, cryptoRegime: null, cryptoNews: null, bioTrials: null, bioFda: null, bioAdcomm: null, bioMfds: null, bioMfdsFilter: "notable", krOvernight: null, krPension: null, krHoldings: null, krEtf: null, krSearchInterest: null, ksiSort: "spike", usPtr: null, usOvernight: null, calendar: null,
  records: new Map(), restricted: new Map(), errors: {}, sectorPeriod: localStorage.getItem("monitor.sectorPeriod") || "1d",
  tvPeriod: localStorage.getItem("monitor.tvPeriod") || "1d", tvLoaded: false, correlationLoaded: false,
};

let presenceCount = null;
const cryptoPrevValues = new Map();
// 피드 지역 필터 — renderFeed보다 먼저 초기화돼야 한다(파일 하단 let 금지, TDZ).
let feedRegion = ["kr", "us"].includes(localStorage.getItem("monitor.feedRegion"))
  ? localStorage.getItem("monitor.feedRegion") : "all";

// 종목명이 보이는 모든 곳을 종목 허브의 문으로 만든다. 코드가 형식에 맞을
// 때만 링크를 건다 — 허브가 404를 돌려줄 심볼에 죽은 문을 달지 않는다.
function hubLink(text, code, { us = false } = {}) {
  const symbol = String(code || "").trim().toUpperCase();
  const valid = us ? /^[A-Z][A-Z0-9.-]{0,9}$/.test(symbol) : /^\d{6}$/.test(symbol);
  if (!valid) { const span = document.createElement("span"); span.textContent = text; return span; }
  const link = document.createElement("a");
  link.href = `/stock/${symbol}`;
  link.textContent = text;
  link.style.color = "inherit";
  return link;
}

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

// 날짜 없는 "직전 관측 대비"는 폭락장에 이틀 전 종가를 오늘 시세처럼 읽게
// 만들었다. 두 관측일이 있으면 라벨에 박아 무엇 대 무엇인지 그 자리에서 보인다.
function changeLabel(record) {
  const latestDate = record?.latest?.date, previousDate = record?.previous?.date;
  if (latestDate && previousDate) return `${kroDate(latestDate)} vs ${kroDate(previousDate)}`;
  return t("change.previous");
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
  sentiment_index_unavailable: "sentiment.unavailable",
  crypto_section_disabled: "status.disabled",
  crypto_sentiment_disabled: "status.disabled",
  crypto_sentiment_collecting: "status.collecting",
  crypto_structure_disabled: "status.disabled",
  crypto_structure_collecting: "status.collecting",
  upbit_quotation_pending_rights: "status.rightsPending",
  chain_gas_disabled: "status.disabled",
  bio_section_disabled: "status.disabled",
  bio_trials_disabled: "status.disabled",
  bio_trials_collecting: "status.collecting",
  bio_fda_disabled: "status.disabled",
  bio_fda_collecting: "status.collecting",
  bio_adcomm_disabled: "status.disabled",
  bio_adcomm_collecting: "status.collecting",
  bio_mfds_disabled: "status.disabled",
  bio_mfds_collecting: "status.collecting",
  chain_gas_not_configured: "status.disabled",
  news_videos_disabled: "status.disabled",
};

// Which endpoint would have filled a card. Only consulted when the card is
// empty: a record that did arrive already carries its own `_kind`. Without this
// an entire gated-off lane would read as "not connected", which is a different
// and misleading statement.
const CARD_LANES = new Map([
  ...["sp500", "nasdaq", "gold", "bitcoin", "kospi", "kosdaq", "samsung", "usdkrw", "ewz", "inda",
    "vnm", "ewj", "dxy", "usdjpy", "vix", "wti", "copper", "sp500_realized_vol", "kr200_realized_vol"].map((key) => [key, "assets"]),
  ...["fx_usdkrw", "fx_usdjpy", "fx_usdcny", "fx_eurusd", "fx_gbpusd",
    "treasury_2y", "yield_curve", "high_yield_spread", "financial_stress", "treasury_10y", "unemployment",
    "ofr_fsi", "ofr_fsi_volatility", "ofr_fsi_credit",
    "initial_claims", "fed_assets", "reserve_balances", "reverse_repo", "treasury_general_account",
    "m2", "retail_money_market_funds", "sofr", "effective_fed_funds", "reserve_interest",
    "dollar_index_broad", "dollar_index_afe", "dollar_index_eme",
    "kospi_exact", "kosdaq_exact", "samsung_exact", "sk_hynix_exact",
    "kr_base_rate", "kr_cpi"].map((key) => [key, "macro"]),
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
  // 지수·가격 레벨은 축약하지 않는다. ko-KR의 compact 표기는 7,660을 "7.66천",
  // 29,231을 "2.92만"으로 쓰는데, 한국어 화면에서 지수를 그렇게 읽는 사람은
  // 없다. 축약은 집계량(연준 총자산·M2처럼 조 단위로 읽는 값)에만 남긴다.
  if (format === "compact" || Math.abs(value) >= 1e8) return new Intl.NumberFormat(locale, { notation: "compact", maximumFractionDigits: 2 }).format(value);
  if (compact && Math.abs(value) >= 1e4) return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(value);
  return new Intl.NumberFormat(locale, { maximumFractionDigits: Math.abs(value) < 10 ? 2 : 1 }).format(value);
}

function formatSigned(value, suffix = "%") {
  if (value === null) return "—";
  const shown = new Intl.NumberFormat(state.lang === "ko" ? "ko-KR" : "en-US", { maximumFractionDigits: 2 }).format(Math.abs(value));
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${shown}${suffix}`;
}

function changeClass(value) { return value > 0 ? "up" : value < 0 ? "down" : ""; }

// Zero-centred indexes (OFR FSI, STLFSI) and volatility series change in points:
// a move from −0.60 to −0.48 is "+0.12", not "−19.6%", and its colour follows the
// point direction. Everything else keeps the percent move.
function changeParts(delta, definition) {
  if (definition?.changeMode === "points") {
    if (delta.value === null) return null;
    const suffix = definition.format === "percentPoints" ? "%p" : " pt";
    return { text: formatSigned(delta.value, suffix), direction: delta.value };
  }
  if (delta.percent === null) return null;
  return { text: formatSigned(delta.percent), direction: delta.percent };
}
// 금융위 날짜는 하이픈 없는 8자리다("20260622"). Date가 그대로는 못 읽어서
// dateText에 넘기기 전에 모양을 맞춘다.
function krCompactDate(value) {
  const text = String(value || "").trim();
  return /^\d{8}$/.test(text) ? `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6)}` : text;
}

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
    const record = state.records.get(key);
    // Operator decision 2026-08-21: a card that can only ever say "license
    // required" (Cboe VIX, ICE BofA HY spread) is hidden on the public pages
    // rather than shown blank. The API still reports it as license_required,
    // so the distinction survives — only the empty tile goes.
    const licensedPlaceholder = Boolean(record) && cardState(key, record, definition).kind === "licensed";
    card.hidden = licensedPlaceholder || (!record
      && (laneLoaded(key) || Boolean(definition.licensed) || Boolean(definition.reserved)));
  });
  $$(".overview-group").forEach((group) => {
    group.hidden = $$(".summary-card", group).every((card) => card.hidden);
  });
  $$("#deep-sections .dashboard-section").forEach((section) => {
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
    { id: "kr-indices", text: t("kridx.title") },
    { id: "kr-etf", text: t("kre.title") },
    { id: "kr-search-interest", text: t("ksi.title") },
    { id: "kr-events", text: t("krev.title") },
    { id: "kr-pension-portfolio", text: t("krpf.title") },
    { id: "kr-pension", text: t("krp.title") },
    { id: "constituent-heatmap", text: t("tv.title") },
    { id: "us-managers", text: t("usm.title") },
    { id: "us-ptr", text: t("ptr.title") },
    { id: "us-events", text: t("ev.title") },
    { id: "econ-calendar", text: t("cal.title") },
    { id: "fomc-dots", text: t("dots.title") },
    { id: "crypto-regime", text: t("crypto.regime.title") },
    { id: "crypto-tape", text: t("crypto.tape.title") },
    { id: "crypto-kimchi", text: t("crypto.kimchi.title") },
    { id: "crypto-sentiment", text: t("crypto.fng.title") },
    { id: "crypto-structure", text: t("crypto.structure.title") },
    { id: "crypto-derivatives", text: t("crypto.deriv.title") },
    { id: "crypto-board", text: t("crypto.board.title") },
    { id: "bio-trials", text: t("bio.trials.title") },
    { id: "bio-adcomm", text: t("bio.adcomm.title") },
    { id: "bio-fda", text: t("bio.fda.title") },
    { id: "bio-mfds", text: t("bio.mfds.title") },
    { id: "crypto-gas", text: t("crypto.gas.title") },
    { id: "crypto-liq", text: t("crypto.liq.title") },
    { id: "crypto-news", text: t("crypto.news.title") },
    { id: "crypto-volatility", text: t("crypto.vol.title") },
    ...numbered,
    { id: "liquidity-comparisons", text: `${String(sections.length + 1).padStart(2, "0")} ${state.lang === "ko" ? "유동성 비교" : "Comparisons"}` },
    { id: "sector-flow", text: t("sector.title") }, { id: "correlation", text: t("corr.title") }]
    // A split page carries only its own sections; links must not point at ids
    // that exist on a different page.
    .filter((item) => { const el = document.getElementById(item.id); return el && !el.hidden; })
    // 위 목록은 손으로 적은 순서다. 페이지에서 섹션을 옮기면 목록과 화면이
    // 갈라지고, 갈라진 쪽이 화면이라 눈에 띄지도 않는다 — 그래서 순서를
    // 여기서 정하지 않고 **문서에서 읽는다**. 옮긴 섹션이 곧 옮긴 링크다.
    .sort((a, b) => {
      const left = document.getElementById(a.id), right = document.getElementById(b.id);
      return left.compareDocumentPosition(right) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
    })
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
    const delta = change(record); const move = changeParts(delta, definition); const changeNode = $(".summary-change", card); changeNode.className = `summary-change ${withheld || !move ? "" : changeClass(move.direction)}`;
    changeNode.textContent = info.badge || (!move ? (record ? t("change.previous") : t("status.unavailable")) : `${move.text} · ${changeLabel(record)}`);
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
    // 사전에 항목이 있는 지표는 제목 자체가 설명으로 가는 문이 된다. 팝오버는
    // console.js가 [data-term] 하나만 보고 붙으므로, 여기서는 표시만 만든다.
    const heading = $("h3", card);
    if (definition.term) {
      heading.replaceChildren();
      const opener = document.createElement("button");
      opener.type = "button";
      opener.className = "term";
      opener.dataset.term = definition.term;
      opener.setAttribute("aria-expanded", "false");
      opener.textContent = recordLabel(record, definition);
      heading.append(opener);
    } else {
      heading.textContent = recordLabel(record, definition);
    }
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
    const move = changeParts(delta, definition); const changeNode = $(".metric-change", card); changeNode.className = `metric-change ${withheld || !move ? "" : changeClass(move.direction)}`;
    changeNode.textContent = withheld || !move ? "—" : `${move.text} · ${changeLabel(record)}`;
    const insight = INSIGHTS[key];
    $(".metric-description", card).textContent = info.copy || localValue(record?.description, state.lang) || localValue(definition.description, state.lang) || localValue(insight?.description, state.lang) || t("status.unavailable");
    const hints = $(".metric-hints", card); hints.replaceChildren(); hints.setAttribute("aria-label", state.lang === "ko" ? "해석 참고" : "Interpretation guide");
    (insight?.hints || []).forEach((hint) => { const chip = document.createElement("span"); chip.className = "hint-chip"; chip.textContent = localValue(hint, state.lang); hints.append(chip); });
    const footer = $("footer", card); footer.replaceChildren(); const source = sourceInfo(record);
    const provider = source.url ? document.createElement("a") : document.createElement("span"); provider.textContent = source.name; if (source.url) { provider.href = source.url; provider.target = "_blank"; provider.rel = "noopener noreferrer"; }
    footer.append(provider, document.createTextNode(` · ${record?.instrument_kind || record?._kind || "API"} · ${t("date.asof")} ${dateText(recent.date)}`));
    if (card.dataset.visible === "1") queueChart(() => renderMetricChart(card));
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

// Why a chart slot is empty, in the asset lane's own words (see app/hip3_history.py).
const HISTORY_EMPTY_TEXT = { withheld_pending_rights: "status.historyPending", not_requested_to_bound_public_api_latency: "status.historyPending", collecting: "status.historyCollecting" };

function renderMetricChart(card) {
  const key = card.dataset.metric; const slot = $(".chart-slot", card); const record = state.records.get(key); const definition = METRICS[key];
  const info = cardState(key, record, definition); slot.replaceChildren();
  if (info.badge) { const empty = document.createElement("div"); empty.className = "chart-empty"; empty.textContent = info.badge; slot.append(empty); return; }
  const chart = lineChart(observations(record));
  if (chart) slot.append(chart); else { const empty = document.createElement("div"); empty.className = "chart-empty"; empty.textContent = t(HISTORY_EMPTY_TEXT[record?.history_status] || "status.noSeries"); slot.append(empty); }
}

/* 차트는 한 프레임에 몇 개씩만 그린다.
 *
 * 스크롤로 하나씩 들어올 때는 콜백당 한두 장이라 문제가 없었다. 그런데 /us의
 * 지표 섹션이 접힌 서랍 안으로 들어가면서, 서랍을 열면 46장이 한 번에
 * 교차(intersect)로 잡힌다 — 콜백 하나에서 SVG 46개를 만들면 그 프레임이
 * 통째로 길어진다. 큐에 넣고 프레임마다 조금씩 흘려보낸다. 15분 갱신 때 이미
 * 보이는 카드를 다시 그리는 경로도 같은 큐를 쓴다. */
const chartQueue = [];
let chartDraining = false;
function queueChart(task) {
  chartQueue.push(task);
  if (chartDraining) return;
  chartDraining = true;
  const drain = () => {
    for (let budget = 4; budget > 0 && chartQueue.length; budget -= 1) chartQueue.shift()();
    if (chartQueue.length) requestAnimationFrame(drain); else chartDraining = false;
  };
  requestAnimationFrame(drain);
}

function setupLazyCharts() {
  const observer = new IntersectionObserver((entries) => entries.forEach((entry) => {
    if (!entry.isIntersecting) return; const card = entry.target; card.dataset.visible = "1";
    observer.unobserve(card);
    queueChart(() => {
      if (card.classList.contains("metric-card")) renderMetricChart(card);
      else renderComparison(Number(card.dataset.comparison));
    });
  }), { rootMargin: "220px 0px" });
  // 이미 그린 카드는 다시 관찰하지 않는다 — 서랍이 열릴 때 이 함수를 다시
  // 부르기 때문에, 걸러 두지 않으면 볼 때마다 같은 차트를 새로 그린다.
  $$(".metric-card:not([data-visible='1']), .lazy-comparison:not([data-visible='1'])")
    .forEach((card) => observer.observe(card));
}

/* 서랍이 열릴 때 아직 처리되지 않은 지연 대상만 다시 관찰한다.
 *
 * 닫힌 <details>의 내용은 렌더 트리 밖이라, 그 안에서 observe()한 대상이
 * 열린 뒤 제대로 교차로 잡히는지는 브라우저 구현에 달렸다. 확인하려던 창이
 * 백그라운드(visibilityState: hidden)라 IntersectionObserver 자체가 돌지
 * 않아 실측하지 못했다 — 그래서 어느 쪽이든 맞는 쪽으로 둔다. 이미 그린
 * 대상은 위 필터와 data-lazy-done이 걸러 내므로 다시 불러도 공짜다. */
function refreshLazyTargets() {
  setupLazyCharts();
  setupLazySections();
}
window.mulmitRefreshLazy = refreshLazyTargets;

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
    localValue(state.cryptoOverview?.rights?.notice_localized, state.lang) || state.cryptoOverview?.rights?.notice,
    state.cryptoSentiment?.rights?.notice,
    localValue(state.cryptoKimchi?.rights?.notice_localized, state.lang) || state.cryptoKimchi?.rights?.notice,
    state.cryptoStructure?.rights?.notice,
    localValue(state.cryptoGas?.rights?.notice_localized, state.lang) || state.cryptoGas?.rights?.notice,
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
  const laneReasons = [...new Set(["macro", "assets", "weekend", "sectors", "correlation", "stress", "sentiment", "cryptoOverview", "cryptoSentiment", "cryptoVolatility", "cryptoKimchi", "cryptoStructure", "cryptoGas", "cryptoBoard", "cryptoRegime", "cryptoNews", "bioTrials", "bioFda", "bioAdcomm", "bioMfds"]
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
  } else if (key === "cryptoOverview") {
    usable = (Array.isArray(payload.coins) ? payload.coins : []).filter((record) => safeNumber(record?.price?.value) !== null);
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
  sentiment: ["landing", "us", "crypto"],
  krIndices: ["kr"],
  krOvernight: ["landing", "kr"],
  feed: ["landing"],
  newsVideos: ["landing"],
  krPension: ["kr"],
  krPensionPortfolio: ["kr"],
  krHoldings: ["kr"],
  krEvents: ["kr"],
  krEtf: ["kr"],
  usPtr: ["us"],
  usManagers: ["us"],
  usOvernight: ["landing", "us"],
  usEvents: ["us"],
  calendar: ["landing", "us"],
  cryptoOverview: ["landing", "crypto"],
  cryptoSentiment: ["landing", "crypto"],
  cryptoVolatility: ["crypto"],
  cryptoKimchi: ["crypto"],
  cryptoStructure: ["crypto"],
  cryptoGas: ["crypto"],
  cryptoBoard: ["crypto"],
  cryptoRegime: ["crypto"],
  cryptoLiquidations: ["crypto"],
  cryptoNews: ["crypto"],
  bioTrials: ["bio"],
  bioFda: ["bio"],
  bioAdcomm: ["bio"],
  krSearchInterest: ["kr"],
  bioMfds: ["bio"],
};

async function loadCore() {
  $("#refresh-button")?.setAttribute("aria-busy", "true");
  state.records.clear(); state.restricted.clear();
  const request = (url, key) => onPage(...PAGE_FETCHES[key]) ? fetchJson(url, key) : Promise.resolve(null);
  const [macro, assets, sectors, weekend, stress, sentiment, krIndices, krOvernight, krPension, krPensionPortfolio, krHoldings, krEvents, krEtf, usPtr, usManagers, usOvernight, usEvents, calendar, feed, cryptoOverview, cryptoSentiment, cryptoVolatility, cryptoKimchi, cryptoStructure, cryptoGas, cryptoBoard, cryptoRegime, cryptoLiquidations, cryptoNews, bioTrials, bioFda, bioAdcomm, bioMfds, newsVideos, krSearchInterest] = await Promise.all([
    request("/api/market/macro?history=3y", "macro"), request("/api/market/assets?history=3y", "assets"),
    request("/api/market/sectors", "sectors"), request("/api/market/weekend", "weekend"),
    request("/api/market/stress", "stress"), request("/api/market/sentiment", "sentiment"), request("/api/kr/indices", "krIndices"),
    request("/api/kr/overnight", "krOvernight"), request("/api/kr/pension", "krPension"),
    request("/api/kr/pension-portfolio", "krPensionPortfolio"),
    request("/api/kr/holdings", "krHoldings"),
    request("/api/kr/events", "krEvents"),
    request("/api/kr/etf", "krEtf"), request("/api/us/ptr", "usPtr"),
    request("/api/us/managers", "usManagers"),
    request("/api/us/overnight", "usOvernight"),
    request("/api/us/events", "usEvents"),
    request("/api/calendar", "calendar"),
    request("/api/feed", "feed"),
    request("/api/crypto/overview", "cryptoOverview"),
    request("/api/crypto/sentiment", "cryptoSentiment"),
    request("/api/crypto/volatility", "cryptoVolatility"),
    request("/api/crypto/kimchi", "cryptoKimchi"),
    request("/api/crypto/structure", "cryptoStructure"),
    request("/api/crypto/gas", "cryptoGas"),
    request("/api/crypto/board", "cryptoBoard"),
    request("/api/crypto/regime", "cryptoRegime"),
    request("/api/crypto/liquidations", "cryptoLiquidations"),
    request("/api/crypto/news", "cryptoNews"),
    request("/api/bio/trials", "bioTrials"),
    request("/api/bio/fda", "bioFda"),
    request("/api/bio/adcomm", "bioAdcomm"),
    request("/api/bio/mfds", "bioMfds"),
    request("/api/news/videos", "newsVideos"),
    request("/api/kr/search-interest", "krSearchInterest"),
  ]);
  state.macro = macro; state.assets = assets; state.sectors = sectors; state.weekend = weekend;
  state.stress = stress; state.sentiment = sentiment; state.krIndices = krIndices; state.krOvernight = krOvernight; state.krPension = krPension; state.krPensionPortfolio = krPensionPortfolio; state.krHoldings = krHoldings;
  state.krEvents = krEvents; state.krEtf = krEtf; state.krSearchInterest = krSearchInterest; state.usPtr = usPtr; state.usManagers = usManagers; state.usOvernight = usOvernight; state.usEvents = usEvents; state.calendar = calendar; state.feed = feed;
  state.cryptoOverview = cryptoOverview; state.cryptoSentiment = cryptoSentiment; state.cryptoVolatility = cryptoVolatility;
  state.cryptoKimchi = cryptoKimchi; state.cryptoStructure = cryptoStructure; state.cryptoGas = cryptoGas; state.cryptoBoard = cryptoBoard; state.cryptoRegime = cryptoRegime; state.cryptoLiquidations = cryptoLiquidations; state.cryptoNews = cryptoNews; state.bioTrials = bioTrials; state.bioFda = bioFda; state.bioAdcomm = bioAdcomm; state.bioMfds = bioMfds; state.newsVideos = newsVideos;
  ingestPayload(macro, "macro"); ingestPayload(assets, "assets"); ingestPayload(sentimentRecordPayload(sentiment), "sentiment");
  renderAll(); $("#refresh-button")?.removeAttribute("aria-busy");
}

function renderAll() {
  renderSummary(); renderMetricCards(); renderAttribution(); renderSectors(); renderWeekend(); renderStressIndex(); renderSentimentIndex(); renderKrIndices(); renderKrOvernight(); renderKroOfficialStrip(); renderFeed(); renderKrPensionPortfolio(); renderKrPension(); renderKrHoldings(); renderKrEvents(); renderKrEtf(); renderKrSearchInterest(); renderUsManagers(); renderUsPtr(); renderUsEvents(); renderCalendar(); renderFomcDots();
  renderCryptoOverview(); renderCryptoSentiment(); renderCryptoDerivatives(); renderCryptoVolatility(); renderCryptoKimchi(); renderCryptoStructure(); renderCryptoGas(); renderCryptoBoard(); renderCryptoRegime(); renderCryptoLiquidations(); renderUsOvernight(); renderCryptoNews(); renderBioCatalysts(); renderBioTrials(); renderBioFda(); renderBioAdcomm(); renderBioMfds(); renderNewsVideos();
  renderMastTicker(); renderZonePreviews(); updateSessionBadge(); renderPresenceBadge();
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
  $$(".lazy-comparison[data-visible='1']").forEach((card) => queueChart(() => renderComparison(Number(card.dataset.comparison))));
  const times = [state.macro?.generated_at, state.assets?.generated_at, state.sectors?.generated_at, state.sectors?.as_of, state.weekend?.generated_at, state.cryptoOverview?.generated_at, state.bioTrials?.generated_at, state.bioFda?.generated_at].filter(Boolean);
  $("#updated-at").textContent = times.length ? dateText(times.sort().at(-1)) : "—";
  // A deliberately disabled lane is absence by decision, not degraded service.
  // It leaves the health calculation entirely: with the legacy price lane off,
  // the badge would otherwise read "partial data" forever on a healthy site.
  const health = ["macro", "assets", "sectors", "weekend", "krOvernight", "cryptoOverview"]
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
  notifyConsole();
}

// 콘솔 셸(console.js)이 같은 state로 테이프와 보드를 그린다. 상태를 복제하지
// 않고 렌더가 끝난 시점만 알린다 — 두 파일이 서로 어긋날 여지를 없앤다.
// 전체 렌더뿐 아니라 5초 부분 갱신 루프도 이걸 부른다. 부르지 않으면 첫 화면
// 숫자만 15분 주기로 멈춰 있게 된다.
function notifyConsole() {
  document.dispatchEvent(new CustomEvent("mulmit:render", { detail: state }));
}

/* 콘솔 셸이 지표를 읽는 유일한 창구.
 *
 * console.js가 자체 판정표를 들고 있으면 같은 계열이 화면마다 다른 숫자로
 * 나온다 — 10년물 변화를 %로 쓸지 %p로 쓸지, 어떤 값이 라이선스 때문에
 * 비어야 하는지 같은 판단은 METRICS 정의 한 곳에만 있어야 한다. 여기서는
 * 카드가 그릴 것과 똑같은 결과만 스냅샷으로 넘긴다. 값이 없거나 표시 권리가
 * 없으면 null이고, 그러면 타일이 만들어지지 않는다. */
function metricSnapshot(key) {
  const definition = METRICS[key];
  if (!definition) return null;
  const record = state.records.get(key);
  if (cardState(key, record, definition).badge) return null;
  const recent = latest(record);
  if (recent.value === null) return null;
  const move = changeParts(change(record), definition);
  return {
    label: recordLabel(record, definition),
    value: recent.value,
    text: formatNumber(recent.value, definition, record),
    date: recent.date,
    changeText: move ? move.text : null,
    changeDirection: move ? move.direction : null,
    basis: changeLabel(record),
    source: record ? sourceInfo(record).name : null,
    observations: observations(record),
  };
}
window.mulmitMetric = metricSnapshot;

function formatKrw(value) {
  if (value == null || !isFinite(value)) return "—";
  if (Math.abs(value) >= 1e12) return `${(value / 1e12).toFixed(1)}조`;
  if (Math.abs(value) >= 1e8) return `${Math.round(value / 1e8).toLocaleString()}억`;
  return Math.round(value).toLocaleString();
}

// Every Korean close on this page can be a session behind every other quote
// screen, because the public dataset publishes a session only after 13:00 KST
// on the next business day. Over a weekend that means Thursday's close while
// the rest of the world compares against Friday's. The overnight payload
// already works out which session is missing and when it lands; the same
// sentence belongs everywhere a close is shown, not only on the cards.
function krClosePublicationNote() {
  const card = (state.krOvernight?.cards || []).find((row) => row.official?.publication_note_ko);
  if (!card) return null;
  return state.lang === "ko"
    ? card.official.publication_note_ko
    : card.official.publication_note_en;
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

  // 연중 최고에서 얼마나 내려와 있나.
  //
  // 이 열은 "52주 범위"라는 이름으로 스물한 행 모두 "—"였다. 금융위가 연중
  // **최저**를 확정 전까지 0(그리고 미래 날짜)으로 내보내고 우리 가드가 그걸
  // 올바르게 걷어내기 때문이다. 반면 연중 **최고**는 스물한 행 모두 실제 값이
  // 온다. 그래서 열을 데이터가 실제로 뒷받침하는 것으로 바꿨다.
  //
  // 이름도 고쳤다. 원천 필드(yrWRcrdHgst)는 "지수의 연중최고치"이지 52주를
  // 되돌아본 값이 아니고, 형제 필드가 전년말 대비(lsYrEdVsFltRt)인 것도 이
  // 데이터셋이 역년 기준이라는 뜻이다. 범위도 아니다 — 한쪽 끝뿐이다.
  const peakGap = (row) => {
    const peak = row.high_52w;
    if (peak == null || !(peak > 0) || row.close == null) return "—";
    return `${((row.close / peak - 1) * 100).toFixed(1)}%`;
  };
  const peakTitle = (row) => {
    const peak = row.high_52w;
    if (peak == null || !(peak > 0)) return t("kridx.peakNone");
    return t("kridx.peakTip", {
      value: peak.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
      date: dateText(krCompactDate(row.high_52w_date)),
    });
  };
  for (const group of payload.groups) {
    if (!(group.rows || []).length) continue;
    // 제목과 표를 한 블록으로 묶는다. 그래야 그리드가 묶음 단위로 배치한다 —
    // 형제로 늘어놓으면 제목 둘이 한 줄, 표 둘이 다음 줄로 흩어진다.
    const block = document.createElement("div");
    block.className = "kridx-block";
    const heading = document.createElement("h3");
    heading.className = "kridx-group";
    heading.textContent = localValue(group.label, state.lang);
    block.append(heading);
    body.append(block);
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
        ["num range peak", peakGap(row), peakTitle(row)],
        ["num", formatKrw(row.value)],
      ];
      for (const [cls, text, title] of cells) {
        const td = document.createElement("td");
        if (cls) td.className = cls;
        td.textContent = text;
        if (title) td.title = title;
        tr.append(td);
      }
      tbody.append(tr);
    }
    table.append(tbody); scroll.append(table); block.append(scroll);
  }
  const source = payload.source || {};
  $("#kridx-footer").replaceChildren();
  const link = document.createElement("a");
  link.href = source.url || "#"; link.target = "_blank"; link.rel = "noopener noreferrer";
  link.textContent = source.provider_name || "금융위원회";
  const note = document.createElement("span");
  note.textContent = `${t("kridx.asof", { date: dateText(payload.as_of) })}`;
  // 열 하나가 최고만 말하는 이유를 밝힌다. 저가를 못 쓰는 것은 우리 사정이
  // 아니라 원천이 확정 전 0으로 내보내기 때문이다.
  const lowNote = document.createElement("span");
  lowNote.textContent = t("kridx.lowNote");
  $("#kridx-footer").append(link, note, lowNote);
  const lag = krClosePublicationNote();
  if (lag) {
    const lagNote = document.createElement("span");
    lagNote.textContent = lag;
    $("#kridx-footer").append(lagNote);
  }
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

/* 도넛 하나를 그린다. 국민연금 파이와 13F 카드가 **같은 함수를 쓴다.**
 *
 * 처음엔 13F 쪽에 기하를 한 벌 더 쓰려 했다. 두 벌로 두면 반드시 어긋난다 —
 * 한쪽에서 12시 시작을 고치고 다른 쪽을 잊는 식이다. 각도는 그림의 뜻이라
 * 그런 어긋남이 눈에 잘 띄지도 않는다.
 *
 * `shareOf`가 백분율을 준다. 조각의 합이 100이 되도록 부르는 쪽이 책임진다 —
 * 두 화면 모두 **금액에서 뽑은 비율**을 넘기므로 잔차가 없다. */
function donutSvg(slices, opts) {
  const NS = "http://www.w3.org/2000/svg";
  const size = opts.size || 260;
  const rOut = size / 2 - (opts.pad == null ? 12 : opts.pad);
  const rIn = rOut * (opts.ring == null ? 0.58 : opts.ring);
  const cx = size / 2, cy = size / 2;

  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 " + size + " " + size);
  if (opts.className) svg.setAttribute("class", opts.className);
  svg.setAttribute("role", "img");
  if (opts.ariaLabel) svg.setAttribute("aria-label", opts.ariaLabel);

  const point = (r, angle) => [
    (cx + r * Math.cos(angle)).toFixed(2),
    (cy + r * Math.sin(angle)).toFixed(2),
  ];

  let angle = -Math.PI / 2;  // 12시에서 시작해 시계 방향.
  slices.forEach((slice, index) => {
    const sweep = (Number(opts.shareOf(slice)) || 0) / 100 * Math.PI * 2;
    if (sweep <= 0) return;
    const end = angle + sweep;
    const large = sweep > Math.PI ? 1 : 0;
    const [x0, y0] = point(rOut, angle), [x1, y1] = point(rOut, end);
    const [x2, y2] = point(rIn, end), [x3, y3] = point(rIn, angle);

    const path = document.createElementNS(NS, "path");
    path.setAttribute("d", [
      "M", x0, y0, "A", rOut, rOut, 0, large, 1, x1, y1,
      "L", x2, y2, "A", rIn, rIn, 0, large, 0, x3, y3, "Z",
    ].join(" "));
    path.setAttribute("fill", opts.colorOf(slice, index));
    if (opts.sliceClass) path.setAttribute("class", opts.sliceClass);
    if (opts.titleOf) {
      const title = document.createElementNS(NS, "title");
      title.textContent = opts.titleOf(slice, index);
      path.append(title);
    }
    svg.append(path);
    angle = end;
  });

  if (opts.centerValue) {
    const top = document.createElementNS(NS, "text");
    top.setAttribute("x", String(cx)); top.setAttribute("y", String(cy - 4));
    top.setAttribute("class", opts.centerValueClass || "krpf-center-value");
    top.setAttribute("text-anchor", "middle");
    top.textContent = opts.centerValue;
    svg.append(top);
  }
  if (opts.centerLabel) {
    const sub = document.createElementNS(NS, "text");
    sub.setAttribute("x", String(cx)); sub.setAttribute("y", String(cy + 16));
    sub.setAttribute("class", opts.centerLabelClass || "krpf-center-label");
    sub.setAttribute("text-anchor", "middle");
    sub.textContent = opts.centerLabel;
    svg.append(sub);
  }
  return svg;
}

/* 인접 조각의 색이 붙지 않도록 황금각으로 색상환을 걷는다. 두 화면이 같은
 * 규칙을 써서 같은 순위의 조각이 같은 색으로 보인다. */
function sliceColor(index, isRest) {
  return isRest
    ? "var(--ink-4, #9aa0a6)"
    : "hsl(" + Math.round((index * 137.508 + 208) % 360) + " 58% 52%)";
}

/* 13F 기관 포트폴리오 — 널리 알려진 운용자들의 미국 상장주식 구성.
 *
 * 국민연금 파이와 겉모습은 닮았지만 **말해야 하는 경고가 다르다.** 13F에는
 * 공매도·채권·현금·해외 상장·사모 지분이 안 들어오므로 이 그림은 자산 전부가
 * 아니다. 그 문장을 섹션 머리에 한 번, 그리고 카드마다 사정을 배지로 붙인다:
 *
 *   - 지연이 큰 신고자(퍼싱은 실측 147일)
 *   - 옵션 비중이 큰 신고자(두케인 16.4%) - 13F는 옵션을 명목가로 적는다
 *   - 지수 상품 비중이 큰 신고자(브리지워터 30.5%)
 *   - 보유 종목이 아주 많은 신고자(피셔 1,019 - 자산관리사 성격)
 *
 * 배지는 전부 **payload의 수치에서 계산된다.** 손으로 적은 설명은 데이터가
 * 바뀌면 조용히 거짓이 되기 때문이다. 사람에 관한 사실 하나만 예외로 서버가
 * 문장으로 들고 온다(`person_note`) - 달리오가 2022년 브리지워터 지배에서
 * 물러났다는 것으로, 수치로는 유도할 수 없다. */
function renderUsManagers() {
  const section = $("#us-managers");
  if (!section) return;
  const payload = state.usManagers;
  const managers = Array.isArray(payload?.managers) ? payload.managers : [];
  if (!managers.length) { section.hidden = true; return; }
  section.hidden = false;

  const locale = state.lang === "ko" ? "ko-KR" : "en-US";
  const num = (value, digits) => Number(value ?? 0).toLocaleString(locale, {
    minimumFractionDigits: digits ?? 0, maximumFractionDigits: digits ?? 0,
  });
  // 달러도 언어마다 읽는 단위가 다르다. 국민연금에서 겪은 그 문제다.
  const usd = (value) => {
    const v = Number(value) || 0;
    if (state.lang === "ko") {
      return v >= 1e8 ? num(v / 1e8, 0) + "억 달러" : num(v / 1e4, 0) + "만 달러";
    }
    if (v >= 1e9) return "$" + num(v / 1e9, 1) + "B";
    if (v >= 1e6) return "$" + num(v / 1e6, 1) + "M";
    return "$" + num(v, 0);
  };
  const local = (pair) => pair ? (state.lang === "ko" ? pair.ko : pair.en) : "";

  const body = $("#usm-body");
  body.replaceChildren();

  const grid = document.createElement("div");
  grid.className = "usm-grid";

  managers.forEach((manager) => {
    const totals = manager.totals || {};
    const slices = Array.isArray(manager.slices) ? manager.slices : [];
    const restLabel = t("usm.rest");

    const card = document.createElement("article");
    card.className = "usm-card";

    const head = document.createElement("header");
    head.className = "usm-card-head";
    const title = document.createElement("h3");
    title.textContent = local(manager.fund);
    const person = document.createElement("p");
    person.className = "usm-person";
    person.textContent = local(manager.person);
    head.append(title, person);
    card.append(head);

    // 도넛. 조각 라벨은 발행사 이름 그대로 옮긴다.
    const donut = donutSvg(slices, {
      size: 190, pad: 6, ring: 0.6,
      className: "usm-donut", sliceClass: "usm-slice",
      centerValue: usd(totals.value),
      centerValueClass: "usm-center-value",
      centerLabel: t("usm.centerLabel"),
      centerLabelClass: "usm-center-label",
      ariaLabel: local(manager.fund) + " " + t("usm.centerLabel"),
      shareOf: (slice) => slice.share,
      colorOf: (slice, index) => sliceColor(index, slice.kind === "rest"),
      titleOf: (slice) => (slice.kind === "rest"
        ? t("usm.restCount", { n: num(slice.count) })
        : slice.issuer) + " " + num(slice.share, 1) + "% · " + usd(slice.value),
    });
    card.append(donut);

    // 범례는 상위 여덟만. 카드 여섯 개에 스무 줄씩 세우면 아무도 안 읽는다.
    const legend = document.createElement("ul");
    legend.className = "usm-legend";
    const named = slices.filter((slice) => slice.kind === "holding");
    named.slice(0, 8).forEach((slice, index) => {
      const li = document.createElement("li");
      const dot = document.createElement("span");
      dot.className = "krpf-dot";
      dot.style.background = sliceColor(index, false);
      const name = document.createElement("span");
      name.className = "krpf-legend-name";
      name.textContent = slice.issuer;
      const pct = document.createElement("span");
      pct.className = "krpf-legend-pct";
      pct.textContent = num(slice.share, 1) + "%";
      li.append(dot, name, pct);
      legend.append(li);
    });
    if (named.length > 8) {
      const li = document.createElement("li");
      li.className = "usm-legend-more";
      li.textContent = t("usm.andMore", { n: num(named.length - 8) });
      legend.append(li);
    }
    const rest = slices.find((slice) => slice.kind === "rest");
    if (rest) {
      const li = document.createElement("li");
      const dot = document.createElement("span");
      dot.className = "krpf-dot";
      dot.style.background = sliceColor(0, true);
      const name = document.createElement("span");
      name.className = "krpf-legend-name";
      name.textContent = restLabel + " " + t("usm.restCount", { n: num(rest.count) });
      const pct = document.createElement("span");
      pct.className = "krpf-legend-pct";
      pct.textContent = num(rest.share, 1) + "%";
      li.append(dot, name, pct);
      legend.append(li);
    }
    card.append(legend);

    // 배지 - 전부 수치에서 계산한다.
    const badges = document.createElement("ul");
    badges.className = "usm-badges";
    const badge = (text, tone) => {
      const li = document.createElement("li");
      li.className = "usm-badge" + (tone ? " usm-badge-" + tone : "");
      li.textContent = text;
      badges.append(li);
    };
    badge(t("usm.period", { date: manager.period || "—" }));
    if ((manager.period_lag_days || 0) > 120) {
      badge(t("usm.lagged", { n: num(manager.period_lag_days) }), "warn");
    }
    if ((totals.options_share || 0) >= 5) {
      badge(t("usm.options", { n: num(totals.options_share, 0) }), "warn");
    }
    if ((totals.index_share || 0) >= 10) {
      badge(t("usm.indexed", { n: num(totals.index_share, 0) }), "warn");
    }
    if ((totals.issuers || 0) >= 500) {
      badge(t("usm.manyNames", { n: num(totals.issuers) }), "warn");
    }
    if (totals.short_of_majority) {
      badge(t("usm.noMajority"), "warn");
    }
    card.append(badges);

    if (manager.person_note) {
      const note = document.createElement("p");
      note.className = "usm-note";
      note.textContent = local(manager.person_note);
      card.append(note);
    }

    const foot = document.createElement("p");
    foot.className = "usm-card-foot";
    const link = document.createElement("a");
    link.href = manager.filing_url || "#";
    link.target = "_blank"; link.rel = "noopener noreferrer";
    link.textContent = t("usm.filing", { form: manager.form || "13F-HR" });
    foot.append(link);
    card.append(foot);

    grid.append(card);
  });

  body.append(grid);

  const footer = $("#usm-footer");
  footer.replaceChildren();
  const source = payload.source || {};
  const link = document.createElement("a");
  link.href = source.url || "#"; link.target = "_blank"; link.rel = "noopener noreferrer";
  link.textContent = source.publisher || "SEC";
  const basis = document.createElement("span");
  basis.textContent = state.lang === "ko" ? (payload.basis_ko || "") : (payload.basis_en || "");
  footer.append(link, basis);
  if (Array.isArray(payload.failed) && payload.failed.length) {
    const failed = document.createElement("span");
    failed.className = "usm-failed";
    failed.textContent = t("usm.failed", { n: String(payload.failed.length) });
    footer.append(failed);
  }
}


/* 국민연금 국내주식 포트폴리오 — 연말 스냅샷의 원형 차트.
 *
 * 여기서 가장 조심한 것은 **각도와 라벨의 출처를 나눈 것**이다. 원자료의 비중
 * 컬럼은 소수 둘째 자리 반올림이라 1,200행을 다 더하면 100%가 아니라 99.37%가
 * 된다. 100%로 정규화하면 그림은 깔끔해지지만 그것은 공단이 내지 않은 숫자를
 * 화면에 세우는 일이다. 그래서 각도는 평가액(정수, 잔차 없음)으로 그리고 화면에
 * 찍히는 %는 원자료 값을 그대로 옮긴다. 둘이 미세하게 어긋난다는 사실 자체를
 * 푸터가 말한다.
 *
 * 조각을 20개로 끊은 것도 임의가 아니다 — 이름 붙은 조각이 과반이 되는 가장
 * 작은 수다(상위 20 = 53.48%, 상위 15 = 48.75%). 15에서 끊으면 `기타`가 최대
 * 조각이 되어 그림이 "나머지"를 말하게 된다.
 *
 * 접근성: 파이는 아래 표의 요약일 뿐이고 같은 값이 표에 전부 글자로 있다.
 * 조각마다 <title>을 넣어 마우스와 스크린리더가 같은 문장을 읽게 했다. */
function renderKrPensionPortfolio() {
  const section = $("#kr-pension-portfolio");
  if (!section) return;
  const payload = state.krPensionPortfolio;
  const slices = Array.isArray(payload?.slices) ? payload.slices : [];
  if (!slices.length) { section.hidden = true; return; }
  section.hidden = false;

  const locale = state.lang === "ko" ? "ko-KR" : "en-US";
  const totals = payload.totals || {};
  const restLabel = t("krpf.rest");
  const nameOf = (slice) => slice.kind === "rest" ? restLabel : slice.name;
  const num = (value, digits) => Number(value ?? 0).toLocaleString(locale, {
    minimumFractionDigits: digits ?? 0, maximumFractionDigits: digits ?? 0,
  });

  /* 금액은 언어마다 읽는 단위가 다르다. 원자료의 단위는 억원인데, 한국어는
   * 조/억으로 접고 영어는 원화를 T/B로 접어야 읽힌다. 처음엔 숫자 뒤에 단위
   * 문자열을 그냥 이어 붙였다가 영어에서 "230,421hundred million KRW"가
   * 나왔다 — 한국어의 무공백 관례를 그대로 옮긴 탓이다. 표에서는 이 함수를
   * 쓰지 않는다. 칸마다 단위가 붙으면 세로로 비교가 안 되므로 단위는 열
   * 제목에 한 번만 적고 칸에는 숫자만 둔다. */
  const money = (eok) => {
    const value = Number(eok) || 0;
    if (state.lang === "ko") {
      return value >= 10000 ? num(value / 10000, 1) + "조원" : num(value) + "억원";
    }
    const krw = value * 1e8;
    if (krw >= 1e12) return "KRW " + num(krw / 1e12, 1) + "T";
    if (krw >= 1e9) return "KRW " + num(krw / 1e9, 1) + "B";
    return "KRW " + num(krw / 1e6, 0) + "M";
  };

  // 색 규칙은 13F 카드와 공유한다(`sliceColor`).
  const colorOf = (index, kind) => sliceColor(index, kind === "rest");

  const body = $("#krpf-body");
  body.replaceChildren();

  const wrap = document.createElement("div");
  wrap.className = "krpf-wrap";

  /* --- 도넛 ------------------------------------------------------------- */
  // 기하는 13F 카드와 같은 함수를 쓴다 — 두 벌로 두면 반드시 어긋난다.
  const svg = donutSvg(slices, {
    size: 260, pad: 12, ring: 0.576,
    className: "krpf-donut", sliceClass: "krpf-slice",
    ariaLabel: t("krpf.caption", { n: String(slices.length - 1) }),
    centerValue: money(totals.value),
    centerLabel: t("krpf.centerLabel"),
    shareOf: (slice) => slice.share,
    colorOf: (slice, index) => colorOf(index, slice.kind),
    titleOf: (slice) => nameOf(slice) + " " + num(slice.weight, 2) + "% · " + money(slice.value),
  });

  /* --- 범례 ------------------------------------------------------------- */
  const legend = document.createElement("ul");
  legend.className = "krpf-legend";
  slices.forEach((slice, index) => {
    const li = document.createElement("li");
    const dot = document.createElement("span");
    dot.className = "krpf-dot";
    dot.style.background = colorOf(index, slice.kind);
    const name = document.createElement("span");
    name.className = "krpf-legend-name";
    name.textContent = slice.kind === "rest"
      ? t("krpf.restCount", { n: num(slice.count) })
      : nameOf(slice);
    const pct = document.createElement("span");
    pct.className = "krpf-legend-pct";
    pct.textContent = num(slice.weight, 2) + "%";
    li.append(dot, name, pct);
    legend.append(li);
  });

  wrap.append(svg, legend);
  body.append(wrap);

  /* --- 요약 숫자 --------------------------------------------------------- */
  const topShare = slices
    .filter((slice) => slice.kind !== "rest")
    .reduce((sum, slice) => sum + (Number(slice.weight) || 0), 0);
  const stats = document.createElement("dl");
  stats.className = "krpf-stats";
  [
    [t("krpf.count"), t("krpf.countValue", { n: num(totals.count) })],
    [t("krpf.total"), money(totals.value)],
    [t("krpf.topShare", { n: String(totals.slice_count ?? "") }), num(topShare, 2) + "%"],
  ].forEach((pair) => {
    const dt = document.createElement("dt"); dt.textContent = pair[0];
    const dd = document.createElement("dd"); dd.textContent = pair[1];
    stats.append(dt, dd);
  });
  body.append(stats);

  /* --- 표 ---------------------------------------------------------------- */
  const holdings = Array.isArray(payload.holdings) ? payload.holdings : [];
  if (holdings.length) {
    const caption = document.createElement("p");
    caption.className = "krpf-caption";
    caption.textContent = t("krpf.caption", { n: num(holdings.length) });
    const scroll = document.createElement("div"); scroll.className = "table-scroll";
    const table = document.createElement("table");
    table.className = "accessible-table kridx-table krpf-table";
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    [
      ["num", t("krpf.colRank")],
      ["", t("krpf.colName")],
      ["num", t("krpf.colValue")],
      ["num", t("krpf.colWeight")],
      ["num", t("krpf.colStake")],
    ].forEach((pair) => {
      const th = document.createElement("th");
      th.scope = "col";
      if (pair[0]) th.className = pair[0];
      th.textContent = pair[1];
      headRow.append(th);
    });
    head.append(headRow); table.append(head);

    const tbody = document.createElement("tbody");
    holdings.forEach((row) => {
      const tr = document.createElement("tr");
      [
        ["num krp-code", num(row.rank)],
        ["", row.name],
        ["num", num(row.value)],
        ["num", num(row.weight, 2) + "%"],
        ["num", num(row.stake, 2) + "%"],
      ].forEach((pair) => {
        const td = document.createElement("td");
        if (pair[0]) td.className = pair[0];
        td.textContent = pair[1];
        tr.append(td);
      });
      tbody.append(tr);
    });
    table.append(tbody); scroll.append(table);
    body.append(caption, scroll);
  }

  /* --- 푸터: 출처와 반올림 사정 ------------------------------------------ */
  const footer = $("#krpf-footer");
  footer.replaceChildren();
  const source = payload.source || {};
  const link = document.createElement("a");
  link.href = source.url || "#"; link.target = "_blank"; link.rel = "noopener noreferrer";
  link.textContent = (source.publisher || "") + " · " + (source.provider_name || "");
  const asOf = document.createElement("span");
  asOf.className = "krpf-asof";
  asOf.textContent = t("krpf.asOf", { date: payload.as_of || "" })
    + " · " + t("krpf.next", { date: payload.next_release || "" });
  const rounding = document.createElement("span");
  rounding.textContent = t("krpf.weightNote", { sum: num(totals.weight_sum, 2) });
  const tail = document.createElement("span");
  const tailValue = Number(totals.rounded_out_value) || 0;
  const totalValue = Number(totals.value) || 1;
  tail.textContent = t("krpf.tailNote", {
    n: num(totals.rounded_out_count),
    value: money(tailValue),
    pct: num(tailValue / totalValue * 100, 2),
  });
  const basis = document.createElement("span");
  basis.textContent = state.lang === "ko" ? (payload.basis_ko || "") : (payload.basis_en || "");
  footer.append(link, asOf, rounding, tail, basis);
}


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
    <th scope="col">${t("krp.colMarket")}</th>
    <th scope="col" class="num">${t("krp.colRatio")}</th><th scope="col" class="num">${t("krp.colChange")}</th>
    <th scope="col" class="num">${t("krp.colShares")}</th><th scope="col">${t("krp.colReason")}</th>
    <th scope="col">${t("krev.colLink")}</th>
  </tr></thead>`;
  const tbody = document.createElement("tbody");
  const signClass = (value) => value == null ? "" : value > 0 ? "up" : value < 0 ? "down" : "";
  for (const filing of filings) {
    const tr = document.createElement("tr");
    const dateTd = document.createElement("td");
    dateTd.textContent = kroDate(filing.report_date);
    // 한 칸에 회사명·원문 링크·시장이 함께 있었다. 셋 다 다른 것이고 글꼴도
    // 굵기도 달라서, 읽는 사람이 매번 경계를 다시 찾아야 했다. 열로 나눈다.
    const companyTd = document.createElement("td"); companyTd.className = "krp-company";
    companyTd.append(hubLink(filing.company || "—", filing.stock_code));
    const marketTd = document.createElement("td");
    marketTd.textContent = filing.market ? localValue(filing.market, state.lang) : "—";
    const sourceTd = document.createElement("td");
    if (filing.report_url) {
      const source = document.createElement("a");
      source.href = filing.report_url; source.target = "_blank"; source.rel = "noopener noreferrer";
      source.textContent = t("krev.view");
      sourceTd.append(source);
    } else sourceTd.textContent = "—";
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
    tr.append(dateTd, companyTd, marketTd, ratioTd, changeTd, sharesTd, reasonTd, sourceTd);
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

/* 종목 검색 관심도.
 *
 * 이 표에서 가장 조심할 것은 **원값을 나란히 놓지 않는 것**이다. 데이터랩은 요청
 * 기간의 최댓값을 100으로 두므로, 한 요청에 다섯 종목씩 들어가면 요청이 갈릴 때마다
 * 100의 뜻도 갈린다(2026-08-24 실측: 삼성전자 최대 100, LG에너지솔루션도 최대 100 —
 * 서로 다른 자다). 그래서 화면에 세우는 숫자는 자기 평소 대비 배수와 자기 창 안의
 * 백분위뿐이고, 원값은 추이선의 모양으로만 쓴다.
 *
 * 추이선은 홈 타일·야간 카드와 같은 함수를 부른다 — 창을 자르는 규칙이 화면마다
 * 갈리면 같은 그림이 다른 뜻이 된다. */
function renderKrSearchInterest() {
  const section = $("#kr-search-interest"); if (!section) return;
  const stateNode = $("#ksi-state"), panel = $("#ksi-panel");
  const payload = state.krSearchInterest;
  const stocks = Array.isArray(payload?.stocks) ? payload.stocks : [];

  if (!stocks.length) {
    // 게이트가 닫혀 있으면 섹션을 아예 숨긴다 — 빈 표보다 없는 편이 정직하다.
    if (disabledCode("krSearchInterest") || !payload) { section.hidden = true; return; }
    section.hidden = false; panel.hidden = true; stateNode.hidden = false;
    stateNode.textContent = `${t("status.unavailable")} · ${t("status.retry")}`;
    return;
  }
  section.hidden = false; stateNode.hidden = true; panel.hidden = false;

  // 두 질문은 다르다. "누가 평소보다 튀었나"(spike)와 "누가 더 많이 검색되나"(level).
  // 어느 쪽을 보고 있는지 화면이 밝혀야 하고, 정렬만 바뀌지 값은 안 바뀐다.
  const mode = state.ksiSort === "level" ? "level" : "spike";
  $$("#ksi-sort button").forEach((button) => {
    const active = button.dataset.ksiSort === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });

  const rows = stocks.slice().sort((a, b) => mode === "level"
    ? (safeNumber(b.level) ?? -1) - (safeNumber(a.level) ?? -1)
    : (safeNumber(b.vs_baseline) ?? -1) - (safeNumber(a.vs_baseline) ?? -1));

  const body = $("#ksi-body"); body.replaceChildren();
  // 쉬움 모드의 한 줄. 숫자가 무슨 뜻인지 그 자리에서 말한다 — 용어 사전으로
  // 보내는 대신, 보고 있는 화면에서 답한다.
  const help = document.createElement("p");
  help.className = "easy-only ksi-help";
  help.textContent = t("ksi.help");
  body.append(help);
  const scroll = document.createElement("div"); scroll.className = "table-scroll";
  const table = document.createElement("table"); table.className = "accessible-table kridx-table";
  table.innerHTML = `<thead><tr>
    <th scope="col" class="num">${t("ksi.colRank")}</th>
    <th scope="col">${t("krev.colCode")}</th><th scope="col">${t("kre.colName")}</th>
    <th scope="col" class="num">${t("ksi.colLevel")}</th>
    <th scope="col" class="num">${t("ksi.colVs")}</th><th scope="col" class="num pro-only">${t("ksi.colPercentile")}</th>
    <th scope="col" id="ksi-trend-head">${t("ksi.colTrend")}</th>
  </tr></thead>`;
  const tbody = document.createElement("tbody");
  // 열 이름에 붙일 기간. 첫 줄에서 정해지고, 다른 줄이 다르면 그 줄에만 적는다.
  let spanLabel = null;

  rows.forEach((stock, position) => {
    const tr = document.createElement("tr");
    // 자리를 옮긴 줄은 잠깐 밝아진다. 값이 아니라 순위가 움직인 것이라, 눈이 그
    // 줄을 다시 찾을 수 있어야 한다.
    const change = safeNumber(stock.level_rank_change);
    if (mode === "level" && change) tr.classList.add(change > 0 ? "rank-up" : "rank-down");

    const rankTd = document.createElement("td"); rankTd.className = "num ksi-rank";
    const rank = safeNumber(stock.level_rank);
    if (mode === "level" && rank !== null) {
      const number = document.createElement("b"); number.textContent = String(rank);
      rankTd.append(number);
      if (change) {
        const badge = document.createElement("span");
        badge.className = `ksi-move ${change > 0 ? "up" : "down"}`;
        badge.textContent = `${change > 0 ? "▲" : "▼"}${Math.abs(change)}`;
        rankTd.append(badge);
      }
    } else {
      rankTd.textContent = mode === "level" ? "—" : String(position + 1);
      rankTd.classList.add("muted");
    }

    const codeTd = document.createElement("td"); codeTd.className = "krp-code";
    const link = document.createElement("a"); link.href = stock.hub || `/stock/${stock.code}`;
    link.textContent = stock.code || "—"; codeTd.append(link);
    const nameTd = document.createElement("td"); nameTd.className = "krp-company";
    nameTd.textContent = stock.name || "—";
    if (stock.is_anchor) {
      // 100의 출처를 밝힌다. 안 밝히면 100이 절댓값처럼 읽힌다.
      const tag = document.createElement("span"); tag.className = "ksi-anchor-tag";
      tag.textContent = t("ksi.anchorTag"); nameTd.append(" ", tag);
    }

    // 수준: 앵커=100 기준. 요청이 갈려도 견줄 수 있는 유일한 위치다.
    const level = safeNumber(stock.level);
    const levelTd = document.createElement("td"); levelTd.className = "num";
    levelTd.textContent = level === null ? "—"
      : level >= 10 ? level.toFixed(1)
      : level >= 1 ? level.toFixed(2)
      : level.toFixed(3);

    // 배수. 1을 넘으면 평소보다 많이 찾아본 것이고, 그 방향으로만 색을 준다.
    const multiple = safeNumber(stock.vs_baseline);
    const vsTd = document.createElement("td");
    vsTd.className = `num ${multiple === null ? "" : multiple > 1 ? "up" : multiple < 1 ? "down" : ""}`;
    if (multiple === null) {
      // 요일 표본이 얇아 숫자를 못 낸 경우다. 빈칸으로 두면 0으로 읽힌다.
      vsTd.textContent = t("ksi.thinSample");
      vsTd.classList.add("muted");
    } else {
      vsTd.textContent = `×${multiple.toFixed(2)}`;
    }

    const percentile = safeNumber(stock.percentile);
    // 백분위는 배수를 이해한 다음에 읽는 값이다. 쉬움 모드에서는 접는다 —
    // 두 숫자를 나란히 놓으면 초보자는 어느 쪽을 봐야 할지부터 헤맨다.
    const pctTd = document.createElement("td"); pctTd.className = "num pro-only";
    pctTd.textContent = percentile === null ? "—" : `${percentile.toFixed(0)}%`;

    const trendTd = document.createElement("td");
    const series = Array.isArray(stock.series) ? stock.series : [];
    const spark = window.mulmitSparkline?.(series.map((point) => ({ date: point.period, value: point.ratio })));
    if (spark) {
      const wrap = document.createElement("div");
      wrap.className = `tile-spark card-spark ${spark.tone}`;
      // 기간은 열 이름에 한 번만 적는다 — 열 줄에 "30일"을 열 번 쓰면 그건 정보가
      // 아니라 소음이다. 다만 어느 줄의 창이 짧으면 그 줄에만 적는다 — 같은 열의
      // 선들이 다른 기간이면 모양을 나란히 읽을 수 없기 때문이다.
      if (spanLabel === null) spanLabel = spark.label;
      else if (spark.label !== spanLabel) {
        const period = document.createElement("span");
        period.className = "spark-period"; period.textContent = spark.label;
        wrap.append(period);
      }
      wrap.append(spark.node);
      trendTd.append(wrap);
    } else {
      trendTd.textContent = "—";
    }

    tr.append(rankTd, codeTd, nameTd, levelTd, vsTd, pctTd, trendTd);
    tbody.append(tr);
  });
  table.append(tbody); scroll.append(table); body.append(scroll);
  if (spanLabel) {
    const head = table.querySelector("#ksi-trend-head");
    if (head) head.textContent = `${t("ksi.colTrend")} · ${spanLabel}`;
  }

  const footer = $("#ksi-footer"); footer.replaceChildren();
  const basis = document.createElement("span");
  const anchorName = payload.anchor?.name;
  const written = state.lang === "ko" ? (payload.basis_ko || "") : (payload.basis_en || payload.basis_ko || "");
  basis.textContent = anchorName ? `${written} ${t("ksi.anchorNote", { name: anchorName })}` : written;
  footer.append(basis);
  const attribution = payload.attribution || {};
  if (attribution.url) {
    const link = document.createElement("a");
    link.href = attribution.url; link.target = "_blank"; link.rel = "noopener noreferrer";
    link.textContent = state.lang === "ko" ? (attribution.text_ko || attribution.text) : attribution.text;
    footer.append(link);
  }
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
    <th scope="col">${t("krev.colCode")}</th><th scope="col">${t("kre.colName")}</th><th scope="col" class="num">${t("kre.colClose")}</th>
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
    const codeTd = document.createElement("td"); codeTd.className = "krp-code";
    codeTd.textContent = fund.code || "—";
    const nameTd = document.createElement("td"); nameTd.className = "krp-company";
    nameTd.textContent = fund.name || "—";
    const cells = [
      ["num", close === null ? "—" : Math.round(close).toLocaleString("en-US")],
      [`num ${signClass(dayPercent)}`, signed(dayPercent)],
      ["num", nav === null ? "—" : nav.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })],
      [`num ${signClass(premium)}`, signed(premium)],
      ["range", fund.index_name || "—"],
      ["num", formatKrw(safeNumber(fund.value))],
    ];
    tr.append(codeTd, nameTd);
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
// 공식 환율 미니 티커(ECOS 매매기준율), 랜딩 존 카드의 라이브 미니 프리뷰.
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

// 히어로 카피를 시장 세션에 맞춘다. 방문자 시계가 아니라 서울·뉴욕 타임존
// 기준이고(해외 접속 대비), 미국 서머타임은 타임존 API가 처리한다. 시계 기준
// 평일 판정이라 휴장일은 반영하지 못한다 — 세션 배지와 같은 공통 한계다.
// 한국 정규장(09:00–15:30 KST)과 미국 정규장(NY 09:30–16:00)은 겹치지 않아
// 상태는 넷으로 닫힌다: 한국 장중 · 미국 장중 · 주말 · 그 외(원래 문구).
function zoneClock(timeZone) {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone, weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false }).formatToParts(new Date());
  const get = (type) => parts.find((part) => part.type === type)?.value || "";
  const weekday = get("weekday");
  return {
    weekend: weekday === "Sat" || weekday === "Sun",
    minutes: (parseInt(get("hour"), 10) % 24) * 60 + parseInt(get("minute"), 10),
  };
}

function heroTitleKey() {
  // 시계는 개장 시간대를, 서버의 큐레이션 달력(market_days)은 휴장일을 판정한다.
  // 페이로드가 아직 없으면 시계만으로 판단한다 — 휴장일 오탐 가능성은 연 몇 회의
  // 짧은 첫 로딩 구간뿐이다.
  const days = state.krOvernight?.market_days;
  const newYork = zoneClock("America/New_York");
  if (!newYork.weekend && !days?.nyse_closed_today
    && newYork.minutes >= 9 * 60 + 30 && newYork.minutes < 16 * 60) return "landing.title.usOpen";
  const seoul = zoneClock("Asia/Seoul");
  if (seoul.weekend) return "landing.title.weekend";
  if (days?.krx_closed_today) return "landing.title.holiday";
  if (seoul.minutes >= 9 * 60 && seoul.minutes < 15 * 60 + 30) return "landing.title.krOpen";
  return "landing.title";
}

function updateHeroTitle() {
  const node = document.querySelector('[data-i18n^="landing.title"]');
  if (!node) return;
  const key = heroTitleKey();
  // dataset까지 바꿔 두면 언어 전환(trNode)이 고른 변형을 그대로 번역한다.
  if (node.dataset.i18n !== key) { node.dataset.i18n = key; node.textContent = t(key); }
}

function updateSessionBadge() {
  updateHeroTitle();
  const badge = $("#session-badge");
  if (!badge) return;
  const info = krSessionInfo();
  badge.hidden = false;
  // 시계는 열렸다고 하지만 큐레이션 달력이 휴장일이라면, 개장 표시도 다음 개장
  // 카운트다운도 둘 다 거짓이 된다 — 휴장일 라벨만 보여준다.
  const holiday = Boolean(state.krOvernight?.market_days?.krx_closed_today);
  badge.classList.toggle("open", info.open && !holiday);
  badge.title = t("session.note");
  const label = $("span", badge);
  if (holiday) { label.textContent = t("session.holiday"); return; }
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
  date.textContent = `${state.lang === "ko" ? "고시" : "official"} ${kroDate(recent.date)}`;
  node.replaceChildren(
    document.createTextNode(`USD/KRW ${recent.value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`),
    date,
  );
}

function renderZonePreviews() {
  const krMini = $("#zone-kr-mini"), usMini = $("#zone-us-mini"), cryptoMini = $("#zone-crypto-mini");
  if (!krMini && !usMini && !cryptoMini) return;
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
    // 확정 종가(T+1)가 아니라 살아 있는 KR200 퍼프를 보여준다. 종가는 폭락장
    // 한복판에 이틀 전 숫자를 "지금"처럼 내보내 오독을 낳았다.
    const kro = (state.krOvernight?.cards || []).find((card) => card.id === "kospi_200");
    const value = safeNumber(kro?.implied?.value);
    const percent = safeNumber(kro?.implied?.vs_official_percent);
    krMini.hidden = value === null;
    if (!krMini.hidden) {
      krMini.replaceChildren(entry(
        t("landing.krMini.kospi"),
        value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
        percent,
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
    const sentimentScore = safeNumber(state.sentiment?.score);
    if (sentimentScore !== null) {
      parts.push(entry(t("landing.usMini.sentiment"),
        `${sentimentScore.toFixed(1)} · ${localValue(state.sentiment?.band, state.lang)}`, null));
    }
    usMini.hidden = !parts.length;
    if (parts.length) usMini.replaceChildren(...parts);
  }
  if (cryptoMini) {
    const parts = [];
    const btc = (state.cryptoOverview?.coins || []).find((card) => card?.symbol === "BTC");
    const btcPrice = safeNumber(btc?.price?.value);
    if (btcPrice !== null) parts.push(entry(t("landing.cryptoMini.btc"), cryptoUsd(btcPrice), safeNumber(btc?.change_24h?.percent)));
    const fng = safeNumber(state.cryptoSentiment?.value);
    if (fng !== null) parts.push(entry(t("landing.cryptoMini.fng"), `${fng} · ${localValue(state.cryptoSentiment?.classification, state.lang)}`, null));
    cryptoMini.hidden = !parts.length;
    if (parts.length) cryptoMini.replaceChildren(...parts);
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
    <th scope="col">${t("ptr.colDate")}</th><th scope="col">${t("ptr.colMember")}</th><th scope="col">${t("ptr.colDistrict")}</th>
    <th scope="col">${t("ptr.colTicker")}</th><th scope="col">${t("ptr.colAsset")}</th>
    <th scope="col">${t("ptr.colOwner")}</th><th scope="col">${t("ptr.colType")}</th>
    <th scope="col" class="num">${t("ptr.colAmount")}</th><th scope="col">${t("ptr.colFiled")}</th>
  </tr></thead>`;
  const tbody = document.createElement("tbody");
  for (const { filing, tx } of shown) {
    const tr = document.createElement("tr");
    const dateTd = document.createElement("td"); dateTd.textContent = dateText(tx.date);
    // 의원 칸에 이름과 지역구가, 종목 칸에 종목명·티커·보유자 셋이 들어 있었다.
    // 전부 다른 것이라 열로 나눈다 — 특히 보유자(본인/배우자/공동)는 같은 거래를
    // 다르게 읽게 만드는 값이라 작은 칩으로 붙어 있을 자리가 아니다.
    const memberTd = document.createElement("td"); memberTd.className = "krp-company";
    const link = document.createElement("a");
    link.href = filing.pdf_url; link.target = "_blank"; link.rel = "noopener noreferrer";
    link.textContent = filing.name || "—";
    memberTd.append(link);
    const districtTd = document.createElement("td"); districtTd.className = "krp-code";
    districtTd.textContent = filing.state_district || "—";
    const tickerTd = document.createElement("td"); tickerTd.className = "krp-code";
    tickerTd.textContent = tx.ticker || "—";
    const assetTd = document.createElement("td");
    assetTd.textContent = tx.asset || "—";
    const ownerTd = document.createElement("td");
    ownerTd.textContent = tx.owner && PTR_OWNER_KEYS[tx.owner] ? t(PTR_OWNER_KEYS[tx.owner]) : "—";
    const typeTd = document.createElement("td");
    const typeClass = tx.type === "P" ? "up" : tx.type === "E" ? "" : "down";
    if (typeClass) typeTd.className = typeClass;
    typeTd.textContent = PTR_TYPE_KEYS[tx.type] ? t(PTR_TYPE_KEYS[tx.type]) : (tx.type || "—");
    const amountTd = document.createElement("td"); amountTd.className = "num";
    amountTd.textContent = tx.amount || "—";
    const filedTd = document.createElement("td"); filedTd.textContent = dateText(tx.notification_date || filing.filed_date);
    tr.append(dateTd, memberTd, districtTd, tickerTd, assetTd, ownerTd, typeTd, amountTd, filedTd);
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

// FOMC dot plot: the committee's own year-end projections (SEP), rendered as a
// small table instead of generic metric cards — the newest observation of each
// series is the FARTHEST projection year, so a "latest value" headline would
// front the wrong number.
function renderFomcDots() {
  const section = $("#fomc-dots");
  if (!section) return;
  const median = state.records.get("fedfunds_proj_median");
  const rows = observations(median)
    .map((o) => ({ date: String(o.date || ""), value: safeNumber(o.value) }))
    .filter((o) => o.value !== null && o.date)
    .sort((a, b) => a.date.localeCompare(b.date));
  if (!rows.length) { section.hidden = true; return; }
  section.hidden = false;

  const bandMap = (key) => new Map(observations(state.records.get(key))
    .map((o) => [String(o.date || ""), safeNumber(o.value)]));
  const highs = bandMap("fedfunds_proj_ct_high"), lows = bandMap("fedfunds_proj_ct_low");
  const pct = (v) => v === null || v === undefined ? "—" : `${parseFloat(v.toFixed(2))}%`;

  const table = document.createElement("table"); table.className = "accessible-table";
  table.innerHTML = `<thead><tr><th>${t("dots.target")}</th><th>${t("dots.median")}</th><th>${t("dots.band")}</th></tr></thead>`;
  const tbody = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    const high = highs.get(row.date), low = lows.get(row.date);
    const band = low !== null && low !== undefined && high !== null && high !== undefined
      ? `${pct(low)} – ${pct(high)}` : "—";
    [t("dots.year", { year: row.date.slice(0, 4) }), pct(row.value), band].forEach((text) => {
      const td = document.createElement("td"); td.textContent = text; tr.append(td);
    });
    tbody.append(tr);
  });
  const longerRun = observations(state.records.get("fedfunds_proj_longer_run"))
    .map((o) => ({ date: String(o.date || ""), value: safeNumber(o.value) }))
    .filter((o) => o.value !== null)
    .sort((a, b) => a.date.localeCompare(b.date))
    .pop();
  if (longerRun) {
    const tr = document.createElement("tr");
    [t("dots.longerRun"), pct(longerRun.value), "—"].forEach((text) => {
      const td = document.createElement("td"); td.textContent = text; tr.append(td);
    });
    tbody.append(tr);
  }
  table.append(tbody);
  const scroll = document.createElement("div"); scroll.className = "table-scroll"; scroll.append(table);
  $("#dots-body").replaceChildren(scroll);

  const source = sourceInfo(median);
  const sepDate = String(median?.last_updated || "").slice(0, 10) || latest(median).date;
  $("#dots-footer").textContent = `${t("dots.asof", { date: dateText(sepDate) })} · ${source.name}`;
}

// 코스피·코스닥 확정 종가 스트립. 히어로 제거 후에도 두 지수의 수준 자체는
// 첫 화면에서 보여야 한다 — 표 형태 대신 한 줄, 날짜쌍 라벨로 정직하게.
const FEED_KIND = {
  us_8k: { label: LABEL("8-K", "8-K"), cls: "us" },
  kr_material: { label: LABEL("주요사항", "Material"), cls: "kr" },
  us_ptr: { label: LABEL("의원거래", "Congress"), cls: "us" },
  kr_pension: { label: LABEL("국민연금", "NPS"), cls: "kr" },
  index_move: { label: LABEL("지수 급변", "Index move"), cls: "kr" },
  news: { label: LABEL("뉴스", "News"), cls: "news" },
  kr_press: { label: LABEL("보도자료", "Press"), cls: "kr" },
  kr_holdings: { label: LABEL("대량보유", "5% filing"), cls: "kr" },
};

function renderFeed() {
  const section = $("#signal-feed");
  if (!section) return;
  const payload = state.feed;
  const items = Array.isArray(payload?.items) ? payload.items : [];
  if (!items.length) { section.hidden = true; return; }
  section.hidden = false;

  // 홈에는 경제 캘린더 격자가 따로 있어 이 칩 줄을 두지 않는다. 요소가 없는
  // 페이지에서도 돌아야 하므로 존재를 먼저 확인한다.
  const upcoming = $("#feed-upcoming");
  const soon = Array.isArray(payload.upcoming) ? payload.upcoming : [];
  if (upcoming) upcoming.hidden = !soon.length;
  if (upcoming && soon.length) {
    upcoming.replaceChildren(...soon.map((event) => {
      const chip = document.createElement("a");
      chip.className = "feed-soon";
      if (event.url) { chip.href = event.url; chip.target = "_blank"; chip.rel = "noopener noreferrer"; }
      const dday = event.d_day === 0 ? "D-DAY" : `D-${event.d_day}`;
      chip.textContent = `${dday} ${localValue(event.title, state.lang)}`;
      return chip;
    }));
  }

  // 한국/미국·해외 분리 — region은 서버가 소스별로 판정해 보낸다.
  const filter = $("#feed-filter");
  if (filter) {
    filter.hidden = false;
    filter.replaceChildren(...[
      ["all", state.lang === "ko" ? "전체" : "All"],
      ["kr", state.lang === "ko" ? "한국" : "Korea"],
      ["us", state.lang === "ko" ? "미국·해외" : "US & Global"],
    ].map(([value, label]) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = `feed-region${feedRegion === value ? " active" : ""}`;
      chip.textContent = label;
      chip.addEventListener("click", () => {
        feedRegion = value; localStorage.setItem("monitor.feedRegion", value); renderFeed();
      });
      return chip;
    }));
  }
  const shown = feedRegion === "all" ? items : items.filter((item) => item.region === feedRegion);

  const body = $("#feed-body");
  body.replaceChildren(...shown.map((item) => {
    const row = document.createElement("div"); row.className = "feed-row";
    const date = document.createElement("small"); date.className = "feed-date";
    date.textContent = kroDate(item.date);
    const kind = FEED_KIND[item.kind] || { label: LABEL(item.kind, item.kind), cls: "" };
    const tag = document.createElement("span"); tag.className = `feed-tag ${kind.cls}`;
    tag.textContent = localValue(kind.label, state.lang);
    const title = document.createElement(item.url ? "a" : "span"); title.className = "feed-text";
    if (item.url) { title.href = item.url; title.target = "_blank"; title.rel = "noopener noreferrer"; }
    title.textContent = localValue(item.title, state.lang);
    row.append(date, tag, title);
    if (item.domain) {
      const domain = document.createElement("small"); domain.className = "feed-domain";
      domain.textContent = item.domain + (item.also_on ? ` +${item.also_on}` : "");
      if (item.also_on) domain.title = state.lang === "ko" ? `같은 제목을 실은 다른 매체 ${item.also_on}곳` : `${item.also_on} more outlets carried this title`;
      row.append(domain);
    }
    // 연관 종목 등락 칩 — %는 뉴스 벤더가 아니라 우리 확정 종가 데이터다.
    for (const chip of (item.tags || []).slice(0, 3)) {
      const move = safeNumber(chip.change_percent);
      const link = document.createElement("a");
      link.className = `feed-move ${changeClass(move)}`;
      link.href = chip.hub || "#";
      link.textContent = move === null ? chip.symbol : `${chip.symbol} ${formatSigned(move)}`;
      if (move !== null) link.title = state.lang === "ko" ? "전일 확정 종가 기준" : "T+1 official close basis";
      row.append(link);
    }
    if (item.hub && !(item.tags || []).length) {
      const hub = document.createElement("a"); hub.className = "feed-hub"; hub.href = item.hub;
      hub.textContent = state.lang === "ko" ? "종목 →" : "stock →";
      row.append(hub);
    }
    return row;
  }));
  if (!shown.length) {
    const empty = document.createElement("small"); empty.className = "feed-empty";
    empty.textContent = state.lang === "ko" ? "이 지역의 최근 신호가 없습니다." : "No recent signals for this region.";
    body.replaceChildren(empty);
  }
  const footer = $("#feed-footer");
  footer.replaceChildren(document.createTextNode(localValue({ ko: payload.basis_ko, en: payload.basis_en }, state.lang)));
  if (payload.attribution) {
    // GDELT 약관 조건: 인용 + 링크가 사용처에 함께 보여야 한다.
    footer.append(document.createTextNode(" · "));
    const cite = document.createElement("a");
    cite.href = payload.attribution.url; cite.target = "_blank"; cite.rel = "noopener noreferrer";
    cite.textContent = state.lang === "ko" ? payload.attribution.text_ko : payload.attribution.text;
    footer.append(cite);
  }
}

function renderKroOfficialStrip() {
  const strip = $("#kro-official-strip");
  if (!strip) return;
  const parts = [];
  for (const [key, labelKey] of [["kospi_exact", "kro.stripKospi"], ["kosdaq_exact", "kro.stripKosdaq"]]) {
    const record = state.records.get(key);
    const recent = latest(record);
    if (!record || recent.value === null) continue;
    const delta = change(record);
    const wrap = document.createElement("span"); wrap.className = "kro-strip-item";
    const name = document.createElement("small"); name.textContent = t(labelKey);
    const value = document.createElement("strong");
    value.textContent = recent.value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    wrap.append(name, value);
    if (delta.percent !== null) {
      const move = document.createElement("em"); move.className = changeClass(delta.percent);
      move.textContent = `${formatSigned(delta.percent)} · ${changeLabel(record)}`;
      wrap.append(move);
    }
    parts.push(wrap);
  }
  strip.hidden = !parts.length;
  if (parts.length) {
    const label = document.createElement("small"); label.className = "kro-strip-label";
    label.textContent = t("kro.officialStrip");
    const lag = krClosePublicationNote();
    if (lag) {
      const lagNote = document.createElement("small"); lagNote.className = "kro-strip-lag";
      lagNote.textContent = lag;
      strip.replaceChildren(label, ...parts, lagNote);
    } else {
      strip.replaceChildren(label, ...parts);
    }
  }
}

function renderKrHoldings() {
  const section = $("#kr-holdings");
  if (!section) return;
  const payload = state.krHoldings;
  const filings = Array.isArray(payload?.filings) ? payload.filings : [];
  if (!filings.length) { section.hidden = true; return; }
  section.hidden = false;

  const body = $("#krh-body");
  body.replaceChildren();
  const scroll = document.createElement("div"); scroll.className = "table-scroll";
  const table = document.createElement("table"); table.className = "accessible-table kridx-table";
  table.innerHTML = `<thead><tr>
    <th scope="col">${t("krp.colDate")}</th><th scope="col">${t("krp.colCompany")}</th>
    <th scope="col">${t("krh.colReporter")}</th><th scope="col">${t("krh.colType")}</th>
    <th scope="col" class="num">${t("krp.colRatio")}</th><th scope="col" class="num">${t("krp.colChange")}</th>
    <th scope="col">${t("krp.colReason")}</th><th scope="col">${t("krev.colLink")}</th>
  </tr></thead>`;
  const tbody = document.createElement("tbody");
  const signClass = (value) => value == null ? "" : value > 0 ? "up" : value < 0 ? "down" : "";
  for (const filing of filings) {
    const tr = document.createElement("tr");
    const dateTd = document.createElement("td");
    dateTd.textContent = kroDate(filing.report_date);
    const companyTd = document.createElement("td"); companyTd.className = "krp-company";
    companyTd.append(hubLink(filing.company || "—", filing.stock_code));
    const sourceTd = document.createElement("td");
    if (filing.report_url) {
      const source = document.createElement("a");
      source.href = filing.report_url; source.target = "_blank"; source.rel = "noopener noreferrer";
      source.textContent = t("krev.view");
      sourceTd.append(source);
    } else sourceTd.textContent = "—";
    const reporterTd = document.createElement("td");
    reporterTd.textContent = filing.reporter || "—";
    const typeTd = document.createElement("td");
    typeTd.textContent = filing.report_type || (filing.detail_status === "unavailable" ? t("krp.detailPending") : "—");
    const ratio = safeNumber(filing.ratio); const ratioChange = safeNumber(filing.ratio_change);
    const ratioTd = document.createElement("td"); ratioTd.className = "num";
    ratioTd.textContent = ratio === null ? "—" : `${ratio.toFixed(2)}%`;
    const changeTd = document.createElement("td"); changeTd.className = `num ${signClass(ratioChange)}`;
    changeTd.textContent = ratioChange === null ? "—" : `${ratioChange > 0 ? "+" : ""}${ratioChange.toFixed(2)}%p`;
    const reasonTd = document.createElement("td");
    const reason = filing.reason || "";
    reasonTd.textContent = reason
      ? (state.lang === "en" ? (KRP_REASON_EN[reason] || reason) : reason)
      : "—";
    tr.append(dateTd, companyTd, reporterTd, typeTd, ratioTd, changeTd, reasonTd, sourceTd);
    tbody.append(tr);
  }
  table.append(tbody); scroll.append(table); body.append(scroll);

  const footer = $("#krh-footer");
  footer.replaceChildren();
  const source = payload.source || {};
  const link = document.createElement("a");
  link.href = source.url || "#"; link.target = "_blank"; link.rel = "noopener noreferrer";
  link.textContent = source.provider_name || "금융감독원";
  const window_ = payload.window || {};
  footer.append(document.createTextNode(
    t("krh.window", { days: window_.days ?? "—", total: payload.total_in_window ?? "—", count: payload.count ?? "—" }) + " · "
  ), link);
}

function renderKrEvents() {
  const section = $("#kr-events");
  if (!section) return;
  const payload = state.krEvents;
  const events = Array.isArray(payload?.events) ? payload.events : [];
  if (!events.length) { section.hidden = true; return; }
  section.hidden = false;

  const table = document.createElement("table"); table.className = "accessible-table";
  // 한 칸에 두 가지를 넣지 않는다. 종목코드와 회사명은 서로 다른 글꼴로
  // 붙어 있어서 눈이 어디까지가 코드인지 매번 다시 재고 있었다.
  table.innerHTML = `<thead><tr><th>${t("krev.colDate")}</th><th>${t("krev.colCode")}</th><th>${t("krev.colCompany")}</th><th>${t("krev.colName")}</th><th>${t("krev.colLink")}</th></tr></thead>`;
  const tbody = document.createElement("tbody");
  for (const event of events) {
    const tr = document.createElement("tr");
    const date = document.createElement("td"); date.textContent = dateText(event.filed_at);
    const codeTd = document.createElement("td"); codeTd.className = "krp-code";
    codeTd.textContent = event.stock_code || "—";
    const company = document.createElement("td");
    company.append(hubLink(event.company || "", event.stock_code));
    const name = document.createElement("td"); name.textContent = event.report_name || "—";
    const linkTd = document.createElement("td");
    const link = document.createElement("a"); link.href = event.url; link.target = "_blank"; link.rel = "noopener noreferrer";
    link.textContent = t("krev.view");
    linkTd.append(link);
    tr.append(date, codeTd, company, name, linkTd); tbody.append(tr);
  }
  table.append(tbody);
  const scroll = document.createElement("div"); scroll.className = "table-scroll"; scroll.append(table);
  $("#krev-body").replaceChildren(scroll);
  const notice = state.lang === "ko" ? payload.source?.notice : (payload.source?.notice_en || payload.source?.notice);
  $("#krev-footer").textContent = `${state.lang === "ko" ? payload.basis_ko : payload.basis_en} · ${notice || ""}`;
}

function renderUsEvents() {
  const section = $("#us-events");
  if (!section) return;
  const payload = state.usEvents;
  const events = Array.isArray(payload?.events) ? payload.events : [];
  if (!events.length) { section.hidden = true; return; }
  section.hidden = false;

  const table = document.createElement("table"); table.className = "accessible-table";
  table.innerHTML = `<thead><tr><th>${t("ev.colDate")}</th><th>${t("ev.colTicker")}</th><th>${t("ev.colCompany")}</th><th>${t("ev.colItems")}</th><th>${t("ev.colLink")}</th></tr></thead>`;
  const tbody = document.createElement("tbody");
  for (const event of events) {
    const tr = document.createElement("tr");
    const date = document.createElement("td"); date.textContent = dateText(event.filed_at);
    const tickerTd = document.createElement("td"); tickerTd.className = "krp-code";
    tickerTd.textContent = event.ticker || "—";
    const company = document.createElement("td");
    company.append(hubLink(event.company || "", event.ticker, { us: true }));
    const items = document.createElement("td");
    items.textContent = (event.items || []).map((item) => localValue(item.label, state.lang) || item.code).join(" · ") || "—";
    const linkTd = document.createElement("td");
    const link = document.createElement("a"); link.href = event.url; link.target = "_blank"; link.rel = "noopener noreferrer";
    link.textContent = t("ev.view");
    linkTd.append(link);
    tr.append(date, tickerTd, company, items, linkTd); tbody.append(tr);
  }
  table.append(tbody);
  const scroll = document.createElement("div"); scroll.className = "table-scroll"; scroll.append(table);
  $("#ev-body").replaceChildren(scroll);
  $("#ev-footer").textContent = `${localValue(payload.basis, state.lang)} · ${payload.source?.publisher || "SEC"}`;
}

// 경제 캘린더 — 표가 아니라 달력으로 본다.
// 스무 줄짜리 표는 "다음 발표가 며칠인가"는 알려 주지만 "그때까지 얼마나
// 비어 있나"를 보여 주지 못한다. 달 격자는 빈 날이 빈칸으로 남아 그 간격이
// 그대로 읽힌다. 한 번에 한 달만 그리고, 전체 목록은 아래 서랍에 표로 남긴다
// — 선형으로 훑고 싶은 사람과, JS를 실행하지 않는 크롤러를 위해서다.
let calendarMonth = null; // 사용자가 넘겨 둔 달. 5초 갱신에도 유지한다.
let calendarSignature = ""; // 다시 그릴 이유가 없으면 DOM을 건드리지 않는다.

// 서울 기준 오늘(YYYY-MM-DD). en-CA가 ISO 차례로 찍어 준다.
// toISOString()에 getTimezoneOffset()을 더하던 옛 계산은 보는 사람의 시간대만큼
// 한 번 더 밀려서, 한국에서 오전 9시 전에 열면 D-day가 하루 어긋났다.
function seoulToday() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul" }).format(new Date());
}

function calMonthLabel(ym) {
  const [year, month] = ym.split("-").map(Number);
  return new Intl.DateTimeFormat(state.lang === "ko" ? "ko-KR" : "en-US", {
    year: "numeric", month: "long", timeZone: "UTC",
  }).format(new Date(Date.UTC(year, month - 1, 1)));
}

function calDaysAway(iso, todayIso) {
  return Math.round((Date.parse(iso + "T00:00:00Z") - Date.parse(todayIso + "T00:00:00Z")) / 86400000);
}

function calKind(event) { return event.kind === "policy" ? "policy" : "release"; }
function calRegion(event) { return event.region === "kr" ? "kr" : "us"; }
function calKindLabel(event) { return t(calKind(event) === "policy" ? "cal.kindPolicy" : "cal.kindRelease"); }
function calRegionLabel(event) { return t(calRegion(event) === "kr" ? "cal.regionKr" : "cal.regionUs"); }

function calGoTo(month) {
  calendarMonth = month;
  calendarSignature = ""; // 달을 바꿨으니 다시 그린다
  renderCalendar();
}

function calNav(months, todayIso) {
  const nav = document.createElement("div");
  nav.className = "cal-nav";
  const index = months.indexOf(calendarMonth);

  const step = (target, label, aria, className) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = className;
    button.textContent = label;
    button.setAttribute("aria-label", aria);
    if (target) button.addEventListener("click", () => calGoTo(target));
    else button.disabled = true;
    return button;
  };

  const title = document.createElement("h3");
  title.className = "cal-month";
  title.textContent = calMonthLabel(calendarMonth);

  nav.append(
    step(months[index - 1], "‹", t("cal.prev"), "cal-step"),
    title,
    step(months[index + 1], "›", t("cal.next"), "cal-step"),
  );

  const thisMonth = todayIso.slice(0, 7);
  if (calendarMonth !== thisMonth && months.includes(thisMonth)) {
    nav.append(step(thisMonth, t("cal.thisMonth"), t("cal.thisMonth"), "cal-jump"));
  }

  const legend = document.createElement("div");
  legend.className = "cal-legend";
  for (const [kind, key] of [["release", "cal.kindRelease"], ["policy", "cal.kindPolicy"]]) {
    const item = document.createElement("span");
    item.className = "cal-key is-" + kind;
    item.textContent = t(key);
    legend.append(item);
  }
  nav.append(legend);
  return nav;
}

function calChip(event) {
  const chip = document.createElement("a");
  chip.className = `cal-chip is-${calKind(event)} is-${calRegion(event)}`;
  chip.href = event.source_url || "#";
  chip.target = "_blank";
  chip.rel = "noopener noreferrer";
  const name = localValue(event.name, state.lang);
  chip.textContent = name;
  chip.title = `${name} · ${calRegionLabel(event)} · ${calKindLabel(event)}`;
  return chip;
}

function calCell(iso, day, byDay, todayIso) {
  const cell = document.createElement("div");
  cell.className = "cal-cell";
  cell.setAttribute("role", "gridcell");
  const weekday = new Date(iso + "T00:00:00Z").getUTCDay();
  if (weekday === 0) cell.classList.add("is-sun");
  if (weekday === 6) cell.classList.add("is-sat");
  if (iso < todayIso) cell.classList.add("is-past");
  if (iso === todayIso) cell.classList.add("is-today");

  const head = document.createElement("div");
  head.className = "cal-daynum";
  const number = document.createElement("span");
  number.className = "cal-n";
  number.textContent = String(day);
  head.append(number);

  const list = byDay.get(iso) || [];
  if (list.length) {
    cell.classList.add("has-event");
    const away = calDaysAway(iso, todayIso);
    if (away === 0 || (away > 0 && away <= 14)) {
      const badge = document.createElement("span");
      badge.className = away === 0 ? "cal-dday is-now" : "cal-dday";
      badge.textContent = away === 0 ? t("cal.today") : t("cal.dday", { n: String(away) });
      head.append(badge);
    }
  }
  cell.append(head);
  for (const event of list) cell.append(calChip(event));

  // 좁은 화면에서는 칸에 글자가 들어가지 않는다. 점으로 자리만 찍고
  // 이름은 격자 아래 목록에서 읽는다.
  if (list.length) {
    const dots = document.createElement("span");
    dots.className = "cal-dots";
    dots.setAttribute("aria-hidden", "true");
    for (const event of list) {
      const dot = document.createElement("i");
      dot.className = "is-" + calKind(event);
      dots.append(dot);
    }
    cell.append(dots);
  }
  return cell;
}

function calGrid(byDay, todayIso) {
  const grid = document.createElement("div");
  grid.className = "cal-grid";
  grid.setAttribute("role", "grid");
  grid.setAttribute("aria-label", calMonthLabel(calendarMonth));

  const weekdayName = new Intl.DateTimeFormat(state.lang === "ko" ? "ko-KR" : "en-US", {
    weekday: "short", timeZone: "UTC",
  });
  for (let i = 0; i < 7; i += 1) {
    const head = document.createElement("div");
    head.className = "cal-weekday";
    if (i === 0) head.classList.add("is-sun");
    if (i === 6) head.classList.add("is-sat");
    head.setAttribute("role", "columnheader");
    // 2024-01-07은 일요일 — 요일 이름을 언어별로 뽑기 위한 기준일일 뿐이다.
    head.textContent = weekdayName.format(new Date(Date.UTC(2024, 0, 7 + i)));
    grid.append(head);
  }

  const [year, month] = calendarMonth.split("-").map(Number);
  const lead = new Date(Date.UTC(year, month - 1, 1)).getUTCDay();
  const days = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const blank = () => {
    const cell = document.createElement("div");
    cell.className = "cal-cell is-blank";
    cell.setAttribute("role", "gridcell");
    return cell;
  };
  for (let i = 0; i < lead; i += 1) grid.append(blank());
  for (let day = 1; day <= days; day += 1) {
    grid.append(calCell(`${calendarMonth}-${String(day).padStart(2, "0")}`, day, byDay, todayIso));
  }
  const tail = (7 - ((lead + days) % 7)) % 7;
  for (let i = 0; i < tail; i += 1) grid.append(blank());
  return grid;
}

// 격자 아래 그 달의 일정 목록. 좁은 화면에서는 이게 본문이고, 넓은 화면에서는
// 칸 안의 칩이 같은 내용을 보여 주므로 CSS가 숨긴다.
function calAgenda(monthEvents, todayIso) {
  const agenda = document.createElement("ul");
  agenda.className = "cal-agenda";
  if (!monthEvents.length) {
    const empty = document.createElement("li");
    empty.className = "cal-agenda-empty";
    empty.textContent = t("cal.empty");
    agenda.append(empty);
    return agenda;
  }
  for (const event of monthEvents) {
    const item = document.createElement("li");
    const away = calDaysAway(String(event.date), todayIso);
    const when = document.createElement("span");
    when.className = "cal-agenda-date";
    when.textContent = dateText(event.date);
    if (away === 0) when.classList.add("up");
    const link = calChip(event);
    link.classList.add("cal-agenda-name");
    const kind = document.createElement("span");
    kind.className = "cal-agenda-kind";
    kind.textContent = `${calRegionLabel(event)} · ${calKindLabel(event)}`;
    item.append(when, link, kind);
    agenda.append(item);
  }
  return agenda;
}

// 전체 일정 표. 접혀 있어도 DOM에 있으므로 크롤러는 그대로 읽는다.
function calFullTable(events, todayIso) {
  const drawer = document.createElement("details");
  drawer.className = "disclose cal-all";
  const summary = document.createElement("summary");
  summary.textContent = t("cal.allEvents", { n: String(events.length) });
  drawer.append(summary);

  const scroll = document.createElement("div");
  scroll.className = "table-scroll";
  const table = document.createElement("table");
  table.className = "accessible-table kridx-table";
  table.innerHTML = `<thead><tr>
    <th scope="col">${t("cal.colDate")}</th><th scope="col">${t("cal.colEvent")}</th>
    <th scope="col">${t("cal.colRegion")}</th><th scope="col">${t("cal.colKind")}</th>
  </tr></thead>`;
  const tbody = document.createElement("tbody");
  for (const event of events) {
    const row = document.createElement("tr");
    const dateTd = document.createElement("td");
    const away = calDaysAway(String(event.date), todayIso);
    const dday = away === 0 ? t("cal.today") : away > 0 && away <= 14 ? t("cal.dday", { n: String(away) }) : "";
    dateTd.textContent = dday ? `${dateText(event.date)} · ${dday}` : dateText(event.date);
    if (away === 0) dateTd.className = "up";
    const nameTd = document.createElement("td");
    nameTd.className = "krp-company";
    const link = document.createElement("a");
    link.href = event.source_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = localValue(event.name, state.lang);
    nameTd.append(link);
    const regionTd = document.createElement("td");
    regionTd.textContent = calRegionLabel(event);
    const kindTd = document.createElement("td");
    kindTd.className = "range";
    kindTd.textContent = calKindLabel(event);
    row.append(dateTd, nameTd, regionTd, kindTd);
    tbody.append(row);
  }
  table.append(tbody);
  scroll.append(table);
  drawer.append(scroll);
  return drawer;
}

function renderCalendar() {
  const section = $("#econ-calendar");
  if (!section) return;
  const payload = state.calendar;
  const events = Array.isArray(payload?.events) ? payload.events : [];
  if (!events.length) { section.hidden = true; return; }
  section.hidden = false;

  const todayIso = seoulToday();
  const months = [...new Set(events.map((event) => String(event.date).slice(0, 7)))].sort();
  const thisMonth = todayIso.slice(0, 7);
  if (!months.includes(calendarMonth)) {
    // 처음 열면 이번 달. 이번 달에 일정이 하나도 없으면 가장 가까운 다음 달.
    calendarMonth = months.includes(thisMonth)
      ? thisMonth
      : months.find((month) => month > thisMonth) || months[months.length - 1];
  }

  // 5초마다 통째로 다시 그리면 열어 둔 서랍이 닫히고 포커스가 튄다.
  const signature = [state.lang, calendarMonth, todayIso, events.length,
    events[events.length - 1]?.date].join("|");
  if (signature === calendarSignature) return;
  calendarSignature = signature;

  const byDay = new Map();
  const monthEvents = [];
  for (const event of events) {
    const iso = String(event.date);
    if (iso.slice(0, 7) !== calendarMonth) continue;
    if (!byDay.has(iso)) byDay.set(iso, []);
    byDay.get(iso).push(event);
    monthEvents.push(event);
  }

  const body = $("#cal-body");
  body.replaceChildren(
    calNav(months, todayIso),
    calGrid(byDay, todayIso),
    calAgenda(monthEvents, todayIso),
    calFullTable(events, todayIso),
  );

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

// 직전 렌더의 환산가 — 값이 움직인 카드에 틱 플래시를 준다.
const kroPrevValues = new Map();
const usoPrevValues = new Map();

// 미국 대형주, 장 밖에서는.
//
// 카드는 /kr의 야간 카드와 같은 부품(.kro-card)을 쓴다. 같은 성격의 값이라
// 화면마다 다르게 생길 이유가 없다. 다른 것은 두 가지뿐이다 — 통화가 USD라
// 환산이 없고, 정규장이 열려 있으면 섹션 자체가 서지 않는다.
// 미국 정규장 마감일은 뉴욕 날짜로 적는다. 보는 사람의 시간대로 찍으면
// 금요일 16:00 ET가 한국에서는 토요일이 되고, 미국장이 열리지도 않는 날짜를
// "마감"이라 부르게 된다(실측: 8/21 금 마감이 "8. 22. 마감 이후"로 나왔다).
function usoCloseDate(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.valueOf())) return String(iso);
  return new Intl.DateTimeFormat(state.lang === "ko" ? "ko-KR" : "en-US", {
    month: "numeric", day: "numeric", timeZone: "America/New_York",
  }).format(date);
}

// 주식 가격은 소수 두 자리다. 암호화폐 포맷터는 $0.09100처럼 잔돈까지 보여
// 주려고 자릿수를 늘리는데, 그 규칙을 주식에 쓰면 $218.040이 된다.
function usoPrice(value, card) {
  if (value === null) return "—";
  if (card && card.kind === "index") {
    // 지수는 USDC로 호가되는 참조 포인트다. 달러 기호를 붙이면 없는 통화를
    // 만들고, 종목 카드와 나란히 서면 "29,321달러"로 읽힌다.
    return `${value.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} pt`;
  }
  return `$${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/* 어느 카드를 세울지는 페이지가 정한다.
 *
 * 홈은 훑는 자리라 한 줄(3칸)이면 충분하다 — 시장 전체가 어느 쪽인지(지수)와
 * 가장 두꺼운 종목 둘. /us는 종목을 다 보여 주되 지수는 뺀다. 바로 아래에
 * XYZ100 전용 서랍이 이미 있어서, 같은 값이 한 화면에 두 번 서게 된다. */
const USO_HOME_IDS = ["nasdaq", "nvda", "tsla"];

function usoVisibleCards(cards) {
  if (PAGE === "landing") {
    return USO_HOME_IDS.map((id) => cards.find((card) => card.id === id)).filter(Boolean);
  }
  return cards.filter((card) => card.kind !== "index");
}

function renderUsOvernight() {
  const section = $("#us-overnight"); if (!section) return;
  const stateNode = $("#uso-state"), grid = $("#uso-grid"), footer = $("#uso-footer");
  const payload = state.usOvernight;

  if (!payload) {
    // 게이트가 닫혀 있으면 섹션을 아예 숨긴다 — 빈 카드보다 없는 편이 정직하다.
    if (disabledCode("usOvernight")) { section.hidden = true; return; }
    section.hidden = false; grid.hidden = true; footer.hidden = true;
    stateNode.hidden = false;
    stateNode.textContent = `${t("status.unavailable")} · ${t("status.retry")}`;
    return;
  }
  // 정규장 중에는 이 섹션이 할 말이 없다. 서버도 카드를 만들지 않는다.
  if (payload.session?.market_open || payload.status === "market_open") {
    section.hidden = true; return;
  }

  const cards = Array.isArray(payload.cards) ? payload.cards : [];
  const usable = usoVisibleCards(cards.filter((card) => safeNumber(card.price?.value) !== null));
  if (!usable.length) {
    section.hidden = false; grid.hidden = true; footer.hidden = true;
    stateNode.hidden = false;
    stateNode.textContent = `${t("status.unavailable")} · ${t("status.retry")}`;
    return;
  }
  section.hidden = false; stateNode.hidden = true; grid.hidden = false; footer.hidden = false;

  grid.replaceChildren(...usable.map((card) => {
    const price = safeNumber(card.price?.value);
    const sinceClose = safeNumber(card.session_reference?.vs_percent);
    const change24h = safeNumber(card.change_24h?.percent);
    const article = document.createElement("article");
    article.className = `kro-card ${changeClass(sinceClose)}`;

    const header = document.createElement("header");
    const title = document.createElement("h3");
    title.textContent = localValue(card.label, state.lang);
    const symbol = document.createElement("span");
    symbol.className = "kro-sym";
    symbol.textContent = card.ticker || card.symbol;
    header.append(title, symbol);

    const priceNode = document.createElement("div");
    priceNode.className = "kro-price";
    priceNode.textContent = usoPrice(price, card);
    const previous = usoPrevValues.get(card.id);
    if (previous !== undefined && price !== previous) {
      priceNode.classList.add(price > previous ? "tick-up" : "tick-down");
    }
    usoPrevValues.set(card.id, price);

    // 헤드라인은 "마감 이후"다. 이 섹션의 존재 이유이고, 24시간 변화는 그 아래
    // 근거표로 내린다 — 주말에는 24시간 창이 마감 이후 구간과 어긋난다.
    const vs = document.createElement("div");
    vs.className = `kro-vs ${changeClass(sinceClose)}`;
    vs.textContent = sinceClose === null
      ? t("uso.noClose")
      : `${formatSigned(sinceClose)} · ${t("uso.sinceClose", { date: usoCloseDate(card.session_reference?.boundary_et) })}`;

    // 30일 추이선. 홈 타일·암호화폐 카드와 같은 함수(console.js)를 부른다.
    const spark = window.mulmitSparkline?.(card.observations);
    let sparkNode = null;
    if (spark) {
      sparkNode = document.createElement("div");
      sparkNode.className = `tile-spark card-spark ${spark.tone}`;
      const period = document.createElement("span");
      period.className = "spark-period";
      period.textContent = spark.label;
      sparkNode.append(period, spark.node);
    }

    const meta = document.createElement("dl");
    meta.className = "kro-meta";
    const row = (labelText, valueText) => {
      const wrap = document.createElement("div");
      const dt = document.createElement("dt"); dt.textContent = labelText;
      const dd = document.createElement("dd"); dd.textContent = valueText;
      wrap.append(dt, dd); return wrap;
    };
    const refClose = safeNumber(card.session_reference?.close);
    meta.append(row(t("uso.close"), usoPrice(refClose, card)));
    meta.append(row(t("kro.mark"), change24h === null ? usoPrice(price, card) : `${usoPrice(price, card)} · 24h ${formatSigned(change24h)}`));
    meta.append(row(t("crypto.volume"), cryptoUsd(safeNumber(card.volume_24h_usd), { compact: true })));

    const badges = document.createElement("div");
    badges.className = "kro-badges";
    if (card.liquidity_status === "low") {
      const chip = document.createElement("span");
      chip.className = "status-badge warn";
      chip.textContent = t("weekend.liquidity");
      badges.append(chip);
    }

    article.append(header, priceNode, vs);
    if (sparkNode) article.append(sparkNode);
    article.append(meta);
    if (badges.childElementCount) article.append(badges);
    return article;
  }));

  footer.replaceChildren();
  const method = document.createElement("p");
  method.className = "kro-method";
  method.textContent = localValue(payload.methodology, state.lang);
  const disclaimer = document.createElement("p");
  disclaimer.className = "kro-disclaimer";
  disclaimer.textContent = localValue(payload.disclaimer, state.lang);
  footer.append(method, disclaimer);
}


/* 장 마감 이후의 움직임을 정직하게 말하는 기준은 둘 중 하나다.
 *
 * 공식 종가는 T+1로 확정되므로 아침·연휴에는 직전 세션보다 하루 늦다. 그때
 * "종가 대비"는 이미 끝난 정규장 하루를 통째로 포함해 버린다 — 실측 2026-08-23:
 * 삼성전자 종가 대비 −0.49% vs 15:30 퍼프 대비 −4.96%. 주말에 이 값을 보는
 * 사람이 알고 싶은 것은 뒤쪽이다. 공식 종가가 따라잡으면 둘이 같은 구간을
 * 가리키므로 공식 종가를 쓴다(공표된 값이 항상 낫다).
 *
 * 카드와 홈 보드가 서로 다른 기준을 고르면 같은 종목이 화면마다 다른 퍼센트로
 * 나온다. 그래서 규칙은 여기 하나만 있다. */
function overnightReference(card) {
  const official = card?.official || {};
  const ref = card?.session_reference || {};
  const officialPercent = safeNumber(card?.implied?.vs_official_percent);
  const refPercent = safeNumber(ref.vs_percent);
  const refDate = String(ref.boundary_kst || "").slice(0, 10);
  const officialDate = String(official.date || "");
  if (ref.status === "ok" && refPercent !== null && refDate && (!officialDate || officialDate < refDate)) {
    return { kind: "session", percent: refPercent, date: refDate };
  }
  if (officialPercent === null) return null;
  return { kind: "official", percent: officialPercent, date: officialDate };
}
window.mulmitOvernightReference = overnightReference;

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
    const reference = overnightReference(card);
    const article = document.createElement("article");
    article.className = `kro-card ${changeClass(percent)}`;
    // 규칙이 15:30 퍼프가를 고르면 두 줄의 주·보조가 뒤바뀐다. 순서와 크기는
    // CSS가 이 클래스를 보고 정한다(마크업 순서는 그대로 둔다).
    if (reference?.kind === "session") article.classList.add("kro-ref-primary");

    const header = document.createElement("header");
    const title = document.createElement("h3");
    if (card.code) {
      // 종목 허브로 가는 문 — 카드가 곧 그 종목의 랜딩이 된다.
      const nameLink = document.createElement("a");
      nameLink.href = `/stock/${card.code}`;
      nameLink.textContent = localValue(card.label, state.lang);
      nameLink.style.color = "inherit";
      title.append(nameLink);
    } else {
      title.textContent = localValue(card.label, state.lang);
    }
    const symbol = document.createElement("a");
    symbol.className = "kro-sym"; symbol.textContent = String(card.symbol || "").toUpperCase();
    if (card.perp?.source_url) { symbol.href = card.perp.source_url; symbol.target = "_blank"; symbol.rel = "noopener noreferrer"; }
    header.append(title, symbol);

    const price = document.createElement("div"); price.className = "kro-price";
    const markUsd = mark === null ? "—" : `$${mark.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    price.textContent = implied !== null ? kroMoney(implied, card.kind) : markUsd;
    const tickValue = implied !== null ? implied : mark;
    const previous = kroPrevValues.get(card.id);
    if (tickValue !== null && previous !== undefined && tickValue !== previous) {
      price.classList.add(tickValue > previous ? "tick-up" : "tick-down");
    }
    if (tickValue !== null) kroPrevValues.set(card.id, tickValue);

    const vs = document.createElement("div"); vs.className = `kro-vs ${changeClass(percent)}`;
    // ADR 카드의 %는 가격 상승률이 아니라 원주 대비 괴리라, "종가 대비"로 두면
    // 30% 오른 것처럼 읽힌다. 프리미엄임을 문구로 박는다.
    const vsKey = card.kind === "adr" ? "kro.vsPremium" : "kro.vsClose";
    if (percent !== null) vs.textContent = `${formatSigned(percent)} · ${t(vsKey, { date: kroDate(card.official?.date) })}`;
    else if (card.status === "reference_only") {
      // 미국 상장 ETF — 이 섹션의 종가 체계 밖. 24시간 변화가 주 표기다.
      vs.className = `kro-vs ${changeClass(change24h)}`;
      vs.textContent = change24h === null ? t("kro.usEtf") : `24h ${formatSigned(change24h)} · ${t("kro.usEtf")}`;
    }
    else if (card.status === "no_fx") vs.textContent = t("kro.noFx");
    else vs.textContent = t("kro.noClose");
    if (card.kind === "adr" && card.adr?.per_ordinary) {
      const note = t("kro.adrImpliedNote", { ratio: card.adr.per_ordinary });
      vs.title = note; price.title = note;
    }

    // 공식 종가가 직전 세션보다 늦을 때(아침·연휴)만 직전 15:30 퍼프가 대비를
    // 참고선으로 덧붙인다. 공식 종가가 따라잡으면 두 수치가 겹치므로 숨긴다.
    const ref = card.session_reference;
    const refPercent = safeNumber(ref?.vs_percent);
    const refDate = String(ref?.boundary_kst || "").slice(0, 10);
    const officialDate = String(card.official?.date || "");
    let vsRef = null;
    if (ref?.status === "ok" && refPercent !== null && refDate && (!officialDate || officialDate < refDate)) {
      vsRef = document.createElement("div");
      vsRef.className = `kro-vs-ref ${changeClass(refPercent)}`;
      vsRef.textContent = `${formatSigned(refPercent)} · ${t("kro.vsSession", { date: kroDate(refDate) })}`;
      vsRef.title = t("kro.vsSessionNote");
    }

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
      meta.append(row(t("kro.fx"), `${payload.fx.rate.toLocaleString("en-US", { maximumFractionDigits: 2 })} · ${kroDate(payload.fx.date)} ${state.lang === "ko" ? "고시" : "official"}`));
    }

    const badges = document.createElement("div"); badges.className = "kro-badges";
    const badge = (text, cls = "warn") => { const span = document.createElement("span"); span.className = `status-badge ${cls}`; span.textContent = text; badges.append(span); };
    if (card.perp?.stale) badge(t("badge.stale"));
    if (card.perp?.liquidity_status === "low") badge(t("weekend.liquidity"));
    if (card.leverage && card.leverage !== 1) badge(`${card.leverage}× ${t("kro.leverage")}`);
    if (payload.session?.active) badge(t("kro.session"), "info");

    // The close on this card can be a session behind every other quote screen,
    // because the public dataset publishes a session only after 13:00 KST on the
    // next business day. The dates are already shown; this says why they differ.
    const lagNote = state.lang === "ko"
      ? card.official?.publication_note_ko
      : card.official?.publication_note_en;

    // 기준선은 하나만 보여 준다.
    //
    // 공식 종가가 늦으면 vsRef("8/21 15:30 이후")가 지금 이야기이고, vs는 이미
    // 끝난 정규장 하루를 포함한 전전날 마감 대비다. 같은 카드에 크기가 비슷한
    // 퍼센트가 둘 서면 어느 쪽이 오늘 이야기인지 읽는 사람이 판단해야 한다.
    // 값이 사라지는 것은 아니다 — 공식 종가는 근거표에 날짜와 함께 남는다.
    //
    // ADR만 예외다. 그 %는 가격 변화가 아니라 원주 대비 프리미엄이라 둘이 서로
    // 다른 것을 재고 있어서 하나로 합칠 수 없다.
    const dropCloseCompare = vsRef && card.kind !== "adr" && percent !== null;
    article.append(header, price);
    if (vsRef) article.append(vsRef);
    if (!dropCloseCompare) article.append(vs);
    article.append(meta);
    if (lagNote) {
      const note = document.createElement("p"); note.className = "kro-lag";
      note.textContent = lagNote;
      article.append(note);
    }
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

// --- 크립토 섹션 (Phase 1, docs/PLAN_CRYPTO_SECTION.md) ------------------------------
// Hyperliquid 자체 무기한선물 카드·파생 표, alternative.me 공포·탐욕 relay, 저장 일봉
// 파생 변동성·상관. 게이트가 닫힌 lane은 kr-overnight와 같은 규칙으로 섹션을 숨긴다
// (재시도 안내 대신 결정에 의한 부재). 공포·탐욕 출처 문구는 발행자 약관대로 값 바로 옆.
function cryptoUsd(value, { compact = false } = {}) {
  if (value === null || value === undefined) return "—";
  const abs = Math.abs(value);
  if (compact) {
    if (abs >= 1e12) return `$${(value / 1e12).toFixed(2)}T`;
    if (abs >= 1e9) return `$${(value / 1e9).toFixed(2)}B`;
    if (abs >= 1e6) return `$${(value / 1e6).toFixed(1)}M`;
    if (abs >= 1e3) return `$${(value / 1e3).toFixed(0)}K`;
    return `$${value.toFixed(0)}`;
  }
  const digits = abs >= 1000 ? 2 : abs >= 1 ? 3 : 5;
  return `$${value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

function cryptoCompactNumber(value) {
  if (value === null || value === undefined) return "—";
  const abs = Math.abs(value);
  if (abs >= 1e12) return `${(value / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${(value / 1e3).toFixed(0)}K`;
  return value.toFixed(0);
}

function cryptoFundingText(funding) {
  const hourly = safeNumber(funding?.hourly_percent);
  if (hourly === null) return "—";
  const apr = safeNumber(funding?.apr_percent);
  const hourlyText = `${hourly >= 0 ? "+" : ""}${hourly.toFixed(4)}%`;
  return apr === null ? hourlyText : `${hourlyText} · ${t("crypto.apr")} ${formatSigned(apr)}`;
}

function cryptoSideText(funding) {
  const side = funding?.side;
  const sideText = side === "longs_pay" ? t("crypto.longsPay") : side === "shorts_pay" ? t("crypto.shortsPay") : side === "balanced" ? t("crypto.balanced") : "—";
  if (funding?.heat === "high") return `${sideText} · ${t("crypto.heatHigh")}`;
  if (funding?.heat === "elevated") return `${sideText} · ${t("crypto.heatElevated")}`;
  return sideText;
}

// Venue order is fixed so a column never silently swaps meaning between rows.
const CRYPTO_VENUE_ORDER = ["HlPerp", "BinPerp", "BybitPerp"];
const CRYPTO_VENUE_SHORT = { HlPerp: "HL", BinPerp: "Binance", BybitPerp: "Bybit" };
function cryptoPredictedText(rows) {
  if (!Array.isArray(rows) || !rows.length) return null;
  const parts = CRYPTO_VENUE_ORDER.map((venue) => rows.find((row) => row?.venue === venue)).filter(Boolean)
    .map((row) => `${CRYPTO_VENUE_SHORT[row.venue] || row.venue} ${safeNumber(row.apr_percent) === null ? "—" : formatSigned(row.apr_percent)}`);
  return parts.length ? parts.join(" · ") : null;
}

// A lane that is switched off by a rights/rollout decision hides its section;
// a lane that merely has no data yet keeps the section with a state message.
function bioGateHidden(key) {
  const code = disabledCode(key);
  return code === "bio_section_disabled" || code === "bio_trials_disabled" || code === "bio_fda_disabled" || code === "bio_adcomm_disabled" || code === "bio_mfds_disabled";
}

function bioStatusText(status) {
  if (!status) return "—";
  const key = `bio.status.${status}`; const text = t(key);
  return text === key ? status.replaceAll("_", " ").toLowerCase() : text;
}

function bioPhaseText(phases) {
  if (!Array.isArray(phases) || !phases.length) return "—";
  const nums = phases.map((p) => String(p).replace("EARLY_PHASE1", "1a").replace("PHASE", ""));
  return state.lang === "ko" ? `${nums.join("·")}${t("bio.phaseSuffix")}` : `Phase ${nums.join("/")}`;
}

function bioSponsorLabel(sponsor) {
  const name = localValue(sponsor?.name, state.lang) || "—";
  const listing = sponsor?.listing;
  return listing ? `${name} · ${listing.exchange} ${listing.ticker}` : name;
}

function bioCell(content, className = null) {
  const td = document.createElement("td");
  if (content instanceof Node) td.append(content); else td.textContent = content ?? "—";
  if (className) td.className = className;
  return td;
}

function bioHead(table, labels) {
  const thead = table.querySelector("thead"), tbody = table.querySelector("tbody");
  thead.replaceChildren(); tbody.replaceChildren();
  const row = document.createElement("tr");
  labels.forEach((label) => { const th = document.createElement("th"); th.scope = "col"; th.textContent = label; row.append(th); });
  thead.append(row);
  return tbody;
}

function bioEmptyRow(tbody, span, text) {
  const tr = document.createElement("tr"); const td = document.createElement("td"); td.colSpan = span; td.textContent = text; tr.append(td); tbody.append(tr);
}

// 다가오는 결정.
//
// 이 화면의 나머지는 전부 "이미 일어난 일"이다 — 승인됐다, 허가됐다, 갱신됐다.
// 그런데 바이오 종목을 움직이는 것은 **아직 나지 않은 결정**이다. 흩어져 있던
// 앞을 보는 값 둘을 한 시간축에 놓는다.
//
//   FDA 자문위 예정 회의   Federal Register 공고의 확정 일자
//   임상 1차 완료 예정일   스폰서가 등록부에 적어 둔 **계획값**
//
// 둘은 확실성이 다르다. 그래서 같은 줄에 두되 배지로 구분하고, 계획값이라는
// 것과 "1차 완료 ≠ 결과 발표"라는 것을 근거 줄에 적는다. 날짜가 없는 공고는
// 여기 오지 않는다 — 시간축에 놓을 수 없는 값을 시간축에 두면 거짓이 된다.
const BIO_CATALYST_DAYS = 180;
const BIO_CATALYST_LIMIT = 24;

function bioCatalystRows(todayIso) {
  const rows = [];
  const adcomm = state.bioAdcomm;
  for (const meeting of (adcomm && Array.isArray(adcomm.upcoming) ? adcomm.upcoming : [])) {
    const date = String(meeting.meeting_start || "").slice(0, 10);
    if (!date) continue;
    rows.push({
      date,
      kind: "adcomm",
      title: meeting.committee || meeting.title,
      note: meeting.title,
      url: meeting.url,
      region: "us",
    });
  }
  const trials = state.bioTrials;
  for (const trial of (trials && Array.isArray(trials.recent) ? trials.recent : [])) {
    // 등록부는 "2026-10"처럼 월까지만 적힌 값도 준다. 그런 값은 그 달의 1일로
    // 줄 세우되 화면에는 등록된 그대로 보여 준다 — 없는 정밀도를 만들지 않는다.
    const raw = String(trial.primary_completion || "");
    if (!raw) continue;
    const sortable = raw.length === 7 ? `${raw}-01` : raw;
    if (sortable <= todayIso) continue;
    rows.push({
      date: sortable,
      shown: raw,
      kind: "trial",
      title: trial.title || trial.nct_id,
      note: `${bioPhaseText(trial.phases)} · ${bioStatusText(trial.status)}`,
      url: trial.url,
      sponsor: trial.sponsor,
      region: trial.sponsor?.country === "KR" ? "kr" : "global",
    });
  }
  const cutoff = new Date(Date.parse(`${todayIso}T00:00:00Z`) + BIO_CATALYST_DAYS * 86400000)
    .toISOString().slice(0, 10);
  return rows
    .filter((row) => row.date <= cutoff)
    .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0))
    .slice(0, BIO_CATALYST_LIMIT);
}

function renderBioCatalysts() {
  const section = $("#bio-catalysts"); if (!section) return;
  const stateNode = $("#cat-state"), strip = $("#cat-strip"), panel = $("#cat-panel"), list = $("#cat-list"), footer = $("#cat-footer");

  // 두 레인 다 닫혀 있으면 이 섹션은 존재할 이유가 없다. 하나라도 열려 있으면
  // 그쪽 값만으로 선다 — 반쪽이라도 앞을 보는 값이 있는 편이 낫다.
  const haveAdcomm = !!state.bioAdcomm;
  const haveTrials = !!state.bioTrials;
  if (!haveAdcomm && !haveTrials) {
    if (bioGateHidden("bioAdcomm") && bioGateHidden("bioTrials")) { section.hidden = true; return; }
    section.hidden = false; strip.hidden = true; panel.hidden = true;
    stateNode.hidden = false; stateNode.textContent = `${t("status.unavailable")} · ${t("status.retry")}`;
    return;
  }

  const todayIso = seoulToday();
  const rows = bioCatalystRows(todayIso);
  section.hidden = false; stateNode.hidden = true; strip.hidden = false; panel.hidden = false; footer.hidden = false;

  const meetings = rows.filter((row) => row.kind === "adcomm").length;
  const within90 = rows.filter((row) => row.kind === "trial"
    && calDaysAway(row.date, todayIso) <= 90).length;
  strip.replaceChildren(
    cryptoStripItem(t("bio.cat.meetings"), String(meetings)),
    cryptoStripItem(t("bio.cat.readouts90"), String(within90)),
    cryptoStripItem(t("bio.cat.window"), t("bio.cat.windowValue", { n: String(BIO_CATALYST_DAYS) })),
  );

  list.replaceChildren();
  if (!rows.length) {
    const empty = document.createElement("li");
    empty.className = "bio-cat-empty";
    empty.textContent = t("bio.cat.none");
    list.append(empty);
  }
  for (const row of rows) {
    const item = document.createElement("li");
    const away = calDaysAway(row.date, todayIso);
    item.className = `bio-cat-row is-${row.kind}${away <= 14 ? " is-near" : ""}`;

    const when = document.createElement("div");
    when.className = "bio-cat-when";
    const date = document.createElement("strong");
    date.textContent = dateText(row.shown && row.shown.length === 7 ? `${row.shown}-01` : row.date);
    // 등록부가 월까지만 준 값은 "예정월"임을 밝힌다.
    if (row.shown && row.shown.length === 7) date.textContent = `${row.shown} ${t("bio.cat.monthOnly")}`;
    const dday = document.createElement("span");
    dday.className = "bio-cat-dday";
    dday.textContent = away === 0 ? t("cal.today") : t("cal.dday", { n: String(away) });
    when.append(date, dday);

    const what = document.createElement("div");
    what.className = "bio-cat-what";
    const link = document.createElement("a");
    link.href = row.url || "#"; link.target = "_blank"; link.rel = "noopener noreferrer";
    link.textContent = row.title;
    const note = document.createElement("small");
    note.textContent = row.kind === "adcomm" ? row.note : `${bioSponsorLabel(row.sponsor)} · ${row.note}`;
    what.append(link, note);

    const tags = document.createElement("div");
    tags.className = "bio-cat-tags";
    const kind = document.createElement("span");
    kind.className = `status-badge ${row.kind === "adcomm" ? "info" : ""}`.trim();
    kind.textContent = t(row.kind === "adcomm" ? "bio.cat.kindMeeting" : "bio.cat.kindReadout");
    tags.append(kind);
    if (row.region === "kr") {
      const region = document.createElement("span");
      region.className = "status-badge";
      region.textContent = t("cal.regionKr");
      tags.append(region);
    }

    item.append(when, what, tags);
    list.append(item);
  }

  footer.replaceChildren();
  const basis = document.createElement("p");
  basis.className = "kro-method";
  basis.textContent = t("bio.cat.basis");
  footer.append(basis);
}

// 지역을 필터 버튼이 아니라 **섹션**으로 나눈다.
//
// 한 표 안에 한국과 글로벌이 섞여 있으면, 국내 종목을 보는 사람은 매번 자기
// 것을 눈으로 골라내야 한다. 필터 버튼이 있어도 "지금 무엇을 보고 있는지"를
// 기억해야 하는 부담은 남는다. 화면이 대신 나눠 준다.
const BIO_TRIAL_VIEWS = [
  { section: "#bio-trials-kr", prefix: "biotkr", keep: (country) => country === "KR" },
  { section: "#bio-trials-global", prefix: "biotgl", keep: (country) => country !== "KR" },
];

function renderBioTrials() {
  for (const view of BIO_TRIAL_VIEWS) renderBioTrialsView(view);
}

function renderBioTrialsView({ section: sectionId, prefix, keep }) {
  const section = $(sectionId); if (!section) return;
  const stateNode = $(`#${prefix}-state`), strip = $(`#${prefix}-strip`), sponsors = $(`#${prefix}-sponsors`), panel = $(`#${prefix}-panel`), table = $(`#${prefix}-table`), footer = $(`#${prefix}-footer`);
  const data = state.bioTrials;
  if (!data || !Array.isArray(data.watchlist)) {
    if (bioGateHidden("bioTrials")) { section.hidden = true; return; }
    const collecting = disabledCode("bioTrials") === "bio_trials_collecting";
    section.hidden = false; strip.hidden = true; sponsors.hidden = true; panel.hidden = true; stateNode.hidden = false;
    stateNode.classList.toggle("disabled", collecting);
    stateNode.textContent = collecting ? t("status.collecting") : `${t("status.unavailable")} · ${t("status.retry")}`;
    return;
  }
  section.hidden = false; stateNode.hidden = true; strip.hidden = false; sponsors.hidden = false; panel.hidden = false; footer.hidden = false;
  // 요약 숫자도 이 지역의 것이어야 한다. 전체 합계를 그대로 쓰면 한국 섹션이
  // 여섯 줄을 보여 주면서 "스폰서 34"라고 적게 된다.
  const watched = data.watchlist.filter((s) => keep(s.country));
  const recentHere = (Array.isArray(data.recent) ? data.recent : []).filter((row) => keep(row.sponsor?.country));
  strip.replaceChildren(
    cryptoStripItem(t("bio.trials.sponsors"), String(watched.length)),
    cryptoStripItem(t("bio.trials.recent"), String(recentHere.length)),
    cryptoStripItem(t("bio.trials.processed"), data.processed_date || "—"),
  );
  sponsors.replaceChildren(...watched.map((s) => {
    const chip = document.createElement("span"); chip.className = `bio-chip${s.error ? " muted" : ""}`;
    const name = document.createElement("strong"); name.textContent = bioSponsorLabel(s);
    const small = document.createElement("small");
    small.textContent = s.error ? t("status.unavailable") : `${t("bio.trials.registered")} ${s.counts?.registered_total ?? "—"} · ${t("bio.trials.recent")} ${s.counts?.recent_watched ?? 0}`;
    if (s.note) small.textContent += ` · ${localValue(s.note, state.lang)}`;
    chip.append(name, small); return chip;
  }));
  const tbody = bioHead(table, [t("bio.col.updated"), t("bio.col.sponsor"), t("bio.col.study"), t("bio.col.phase"), t("bio.col.status"), t("bio.col.primary"), t("bio.col.conditions"), t("bio.col.intervention")]);
  const rows = recentHere;
  if (!rows.length) bioEmptyRow(tbody, 8, t("bio.trials.none"));
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    const study = document.createElement("span"); study.className = "bio-title";
    const link = document.createElement("a"); link.href = row.url; link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = row.title || row.nct_id;
    const id = document.createElement("small"); id.textContent = ` ${row.nct_id}${safeNumber(row.enrollment) !== null ? ` · ${t("bio.enrollment", { n: row.enrollment })}` : ""}`;
    study.append(link, id);
    if (row.publications && safeNumber(row.publications.count) !== null && row.publications.count > 0) {
      const pub = document.createElement("small"); pub.className = "bio-pub";
      const plink = document.createElement("a"); plink.href = row.publications.search_url; plink.target = "_blank"; plink.rel = "noopener noreferrer"; plink.textContent = `${t("bio.pub.source")} · ${row.publications.count === 1 ? t("bio.pub.linkOne") : t("bio.pub.link", { n: row.publications.count })}`;
      pub.append(plink);
      const first = Array.isArray(row.publications.articles) ? row.publications.articles[0] : null;
      if (first && first.title) pub.append(document.createTextNode(` — ${first.title}${first.journal ? ` (${first.journal}${first.pubdate ? `, ${first.pubdate}` : ""})` : ""}`));
      study.append(pub);
    }
    const status = document.createElement("span"); status.textContent = bioStatusText(row.status);
    const flags = document.createElement("span"); flags.className = "bio-flags";
    const f = row.flags || {};
    [["results_posted", "bio.flag.results", ""], ["stopped", "bio.flag.stopped", "warn"], ["completed", "bio.flag.completed", ""], ["new_start", "bio.flag.new", ""]].forEach(([key, label, cls]) => {
      if (!f[key]) return; const b = document.createElement("span"); b.className = `status-badge ${cls}`.trim(); b.textContent = t(label); flags.append(b);
    });
    const statusCell = document.createElement("span"); statusCell.append(status); if (flags.childNodes.length) statusCell.append(flags);
    if (row.why_stopped) { const why = document.createElement("small"); why.className = "bio-why"; why.textContent = `${t("bio.flag.why")}: ${row.why_stopped}`; statusCell.append(why); }
    tr.append(
      bioCell(row.last_update_post || "—"),
      bioCell(bioSponsorLabel(row.sponsor)),
      bioCell(study),
      bioCell(bioPhaseText(row.phases)),
      bioCell(statusCell),
      bioCell(row.primary_completion || "—"),
      bioCell((row.conditions || []).slice(0, 3).join(", ") || "—"),
      bioCell((row.interventions || []).slice(0, 3).join(", ") || "—"),
    );
    tbody.append(tr);
  });
  footer.replaceChildren();
  const attribution = document.createElement("p"); attribution.className = "kro-method";
  const link = document.createElement("a"); link.href = data.attribution?.url || "https://clinicaltrials.gov/"; link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = data.attribution?.text || "Source: ClinicalTrials.gov";
  attribution.append(link, document.createTextNode(` · ${t("bio.processedLabel")} ${data.processed_date || "—"}`));
  if (data.as_of) attribution.append(document.createTextNode(` · ${t("date.asof")} ${dateText(data.as_of)}${data.freshness?.status === "stale" ? ` · ${t("badge.stale")}` : ""}`));
  const mods = document.createElement("p"); mods.className = "kro-method"; mods.textContent = `${t("bio.modifications")}: ${localValue(data.modifications, state.lang)}`;
  // The table is ClinicalTrials.gov data, so its attribution leads; PubMed is the secondary source for one column.
  let pubLine = null;
  if (data.pubmed?.status === "ok") {
    pubLine = document.createElement("p"); pubLine.className = "kro-method";
    const plink = document.createElement("a"); plink.href = data.pubmed.attribution?.url || "https://pubmed.ncbi.nlm.nih.gov/"; plink.target = "_blank"; plink.rel = "noopener noreferrer"; plink.textContent = data.pubmed.attribution?.text || "Source: PubMed";
    pubLine.append(plink, document.createTextNode(` · ${t("bio.pub.notice")}${data.pubmed.as_of ? ` · ${t("date.asof")} ${dateText(data.pubmed.as_of)}` : ""}`));
  }
  const method = document.createElement("p"); method.className = "kro-method"; method.textContent = localValue(data.methodology, state.lang);
  const disclaimer = document.createElement("p"); disclaimer.className = "kro-disclaimer"; disclaimer.textContent = localValue(data.disclaimer, state.lang);
  footer.append(attribution, mods, ...(pubLine ? [pubLine] : []), method, disclaimer);
}

function renderBioAdcomm() {
  const section = $("#bio-adcomm"); if (!section) return;
  const stateNode = $("#bioa-state"), strip = $("#bioa-strip"), panel = $("#bioa-panel"), table = $("#bioa-table"), footer = $("#bioa-footer");
  const data = state.bioAdcomm;
  if (!data || !Array.isArray(data.upcoming)) {
    if (bioGateHidden("bioAdcomm")) { section.hidden = true; return; }
    const collecting = disabledCode("bioAdcomm") === "bio_adcomm_collecting";
    section.hidden = false; strip.hidden = true; panel.hidden = true; stateNode.hidden = false;
    stateNode.classList.toggle("disabled", collecting);
    stateNode.textContent = collecting ? t("status.collecting") : `${t("status.unavailable")} · ${t("status.retry")}`;
    return;
  }
  section.hidden = false; stateNode.hidden = true; strip.hidden = false; panel.hidden = false; footer.hidden = false;
  const totals = data.totals || {};
  const next = data.next_meeting;
  strip.replaceChildren(
    cryptoStripItem(t("bio.adcomm.upcoming"), String(totals.upcoming ?? "—")),
    cryptoStripItem(t("bio.adcomm.next"), next ? `${next.meeting_start}${next.committee ? ` · ${next.committee}` : ""}` : "—"),
    cryptoStripItem(t("bio.adcomm.recentPast"), String(totals.recent_past ?? "—")),
  );
  const tbody = bioHead(table, [t("bio.col.meeting"), t("bio.col.committee"), t("bio.col.notice"), t("bio.col.published"), t("bio.col.state")]);
  const rows = [...data.upcoming, ...(Array.isArray(data.recent_past) ? data.recent_past : []), ...(Array.isArray(data.undated) ? data.undated : [])];
  if (!rows.length) bioEmptyRow(tbody, 5, t("bio.adcomm.none"));
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    const link = document.createElement("a"); link.href = row.url; link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = row.title || "—"; link.className = "bio-title";
    let when = row.meeting_start || "—";
    if (row.meeting_end && row.meeting_end !== row.meeting_start) when += ` → ${row.meeting_end}`;
    const stateText = row.status === "upcoming"
      ? `${t("bio.adcomm.state.upcoming")}${typeof row.days_until === "number" ? ` · ${row.days_until === 0 ? t("bio.adcomm.today") : t("bio.adcomm.daysUntil", { n: row.days_until })}` : ""}`
      : row.status === "past" ? t("bio.adcomm.state.past") : t("bio.adcomm.state.undated");
    const stateCell = document.createElement("span"); stateCell.textContent = stateText;
    if (row.amendment) { const b = document.createElement("span"); b.className = "status-badge warn"; b.style.marginLeft = "4px"; b.textContent = t("bio.adcomm.amendment"); stateCell.append(b); }
    tr.append(bioCell(when), bioCell(row.committee || "—"), bioCell(link), bioCell(row.publication_date || "—"), bioCell(stateCell));
    tbody.append(tr);
  });
  footer.replaceChildren();
  const attribution = document.createElement("p"); attribution.className = "kro-method";
  const link = document.createElement("a"); link.href = data.attribution?.url || "https://www.federalregister.gov/"; link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = data.attribution?.text || "Source: Federal Register";
  attribution.append(link);
  if (data.as_of) attribution.append(document.createTextNode(` · ${t("date.asof")} ${dateText(data.as_of)}${data.freshness?.status === "stale" ? ` · ${t("badge.stale")}` : ""}`));
  const method = document.createElement("p"); method.className = "kro-method"; method.textContent = localValue(data.methodology, state.lang);
  const disclaimer = document.createElement("p"); disclaimer.className = "kro-disclaimer"; disclaimer.textContent = localValue(data.disclaimer, state.lang);
  footer.append(attribution, method, disclaimer);
}

function renderBioMfds() {
  const section = $("#bio-mfds"); if (!section) return;
  const stateNode = $("#biom-state"), strip = $("#biom-strip"), panel = $("#biom-panel"), table = $("#biom-table"), footer = $("#biom-footer"), filterBar = $("#biom-filter");
  const data = state.bioMfds;
  if (!data || !Array.isArray(data.permits)) {
    if (bioGateHidden("bioMfds")) { section.hidden = true; return; }
    const collecting = disabledCode("bioMfds") === "bio_mfds_collecting";
    section.hidden = false; strip.hidden = true; panel.hidden = true; stateNode.hidden = false; if (filterBar) filterBar.hidden = true;
    stateNode.classList.toggle("disabled", collecting);
    stateNode.textContent = collecting ? t("status.collecting") : `${t("status.unavailable")} · ${t("status.retry")}`;
    return;
  }
  section.hidden = false; stateNode.hidden = true; strip.hidden = false; panel.hidden = false; footer.hidden = false; if (filterBar) filterBar.hidden = false;
  const counts = data.counts || {};
  strip.replaceChildren(
    cryptoStripItem(t("bio.mfds.total"), String(counts.total ?? "—")),
    cryptoStripItem(t("bio.mfds.permit"), String(counts.permit ?? "—")),
    cryptoStripItem(t("bio.mfds.report"), String(counts.report ?? "—")),
    cryptoStripItem(t("bio.mfds.rx"), String(counts.rx ?? "—")),
    cryptoStripItem(t("bio.mfds.newDrug"), String(counts.new_drug ?? "—")),
    cryptoStripItem(t("bio.mfds.rare"), String(counts.rare ?? "—")),
  );
  const filter = state.bioMfdsFilter || "notable";
  const rows = filter === "notable" ? (Array.isArray(data.notable) ? data.notable : [])
    : filter === "permit" ? data.permits.filter((r) => r.permit_kind === "허가")
    : data.permits;
  const tbody = bioHead(table, [t("bio.col.permitDate"), t("bio.col.item"), t("bio.col.company"), t("bio.col.rxOtc"), t("bio.col.kind"), t("bio.col.ingredients")]);
  if (!rows.length) bioEmptyRow(tbody, 6, t("bio.mfds.none"));
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    const item = document.createElement("span"); item.className = "bio-title";
    const link = document.createElement("a"); link.href = row.url; link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = row.item_name || row.item_seq || "—";
    item.append(link);
    if (row.item_eng_name && state.lang === "en") { const en = document.createElement("small"); en.className = "bio-why"; en.textContent = row.item_eng_name; item.append(en); }
    const flags = document.createElement("span"); flags.className = "bio-flags";
    if (row.newdrug_class) { const b = document.createElement("span"); b.className = "status-badge"; b.textContent = `${t("bio.mfds.flag.newDrug")} · ${row.newdrug_class}`; flags.append(b); }
    if (row.rare) { const b = document.createElement("span"); b.className = "status-badge"; b.textContent = t("bio.mfds.flag.rare"); flags.append(b); }
    if (row.cancel_name && row.cancel_name !== "정상") { const b = document.createElement("span"); b.className = "status-badge warn"; b.textContent = `${t("bio.mfds.flag.cancelled")} · ${row.cancel_name}`; flags.append(b); }
    if (flags.childNodes.length) item.append(flags);
    const company = state.lang === "en" && row.entp_eng_name ? `${row.entp_name || ""} (${row.entp_eng_name})` : (row.entp_name || "—");
    tr.append(
      bioCell(row.permit_date || "—"),
      bioCell(item),
      bioCell(company),
      bioCell(row.etc_otc || "—"),
      bioCell(row.permit_kind || "—"),
      bioCell((row.main_ingredients || []).slice(0, 4).join(", ") || "—"),
    );
    tbody.append(tr);
  });
  footer.replaceChildren();
  const attribution = document.createElement("p"); attribution.className = "kro-method";
  const link = document.createElement("a"); link.href = data.attribution?.url || "https://www.data.go.kr/data/15095677/openapi.do"; link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = state.lang === "en" ? (data.attribution?.text_en || "Source: MFDS (data.go.kr)") : (data.attribution?.text || "출처: 식품의약품안전처 (공공데이터포털)");
  attribution.append(link);
  if (data.window) attribution.append(document.createTextNode(` · ${data.window.start} ~ ${data.window.end}`));
  if (data.as_of) attribution.append(document.createTextNode(` · ${t("date.asof")} ${dateText(data.as_of)}${data.freshness?.status === "stale" ? ` · ${t("badge.stale")}` : ""}`));
  if (safeNumber(data.totals?.failed_days) !== null && data.totals.failed_days > 0) attribution.append(document.createTextNode(` · ${t("bio.mfds.failedDays", { n: data.totals.failed_days })}`));
  const method = document.createElement("p"); method.className = "kro-method"; method.textContent = localValue(data.methodology, state.lang);
  const disclaimer = document.createElement("p"); disclaimer.className = "kro-disclaimer"; disclaimer.textContent = localValue(data.disclaimer, state.lang);
  footer.append(attribution, method, disclaimer);
}

function renderBioFda() {
  const section = $("#bio-fda"); if (!section) return;
  const stateNode = $("#biof-state"), strip = $("#biof-strip"), panel = $("#biof-panel"), table = $("#biof-table"), footer = $("#biof-footer");
  const data = state.bioFda;
  if (!data || !Array.isArray(data.approvals)) {
    if (bioGateHidden("bioFda")) { section.hidden = true; return; }
    const collecting = disabledCode("bioFda") === "bio_fda_collecting";
    section.hidden = false; strip.hidden = true; panel.hidden = true; stateNode.hidden = false;
    stateNode.classList.toggle("disabled", collecting);
    stateNode.textContent = collecting ? t("status.collecting") : `${t("status.unavailable")} · ${t("status.retry")}`;
    return;
  }
  section.hidden = false; stateNode.hidden = true; strip.hidden = false; panel.hidden = false; footer.hidden = false;
  const counts = data.counts || {};
  strip.replaceChildren(
    cryptoStripItem(t("bio.fda.nda"), String(counts.nda ?? "—")),
    cryptoStripItem(t("bio.fda.bla"), String(counts.bla ?? "—")),
    cryptoStripItem(t("bio.fda.anda"), String(counts.anda ?? "—")),
    cryptoStripItem(t("bio.fda.priority"), String(counts.priority_review ?? "—")),
    cryptoStripItem(t("bio.fda.nme"), String(counts.new_molecular_entity ?? "—")),
  );
  const tbody = bioHead(table, [t("bio.col.approved"), t("bio.col.application"), t("bio.col.product"), t("bio.col.sponsor"), t("bio.col.class"), t("bio.col.review")]);
  if (!data.approvals.length) bioEmptyRow(tbody, 6, t("bio.fda.none"));
  data.approvals.forEach((row) => {
    const tr = document.createElement("tr");
    const app = document.createElement("a"); app.href = row.url; app.target = "_blank"; app.rel = "noopener noreferrer"; app.textContent = row.application_number || "—";
    const product = document.createElement("span"); product.className = "bio-title";
    product.textContent = `${row.brand_name || row.generic_name || "—"}${row.brand_name && row.generic_name && row.generic_name.toLowerCase() !== String(row.brand_name).toLowerCase() ? ` (${row.generic_name})` : ""}`;
    if (Array.isArray(row.dosage_forms) && row.dosage_forms.length) { const small = document.createElement("small"); small.className = "bio-why"; small.textContent = row.dosage_forms.join(", "); product.append(small); }
    const review = row.review_priority ? (() => { const key = `bio.review.${String(row.review_priority).toUpperCase()}`; const text = t(key); return text === key ? row.review_priority : text; })() : "—";
    tr.append(
      bioCell(row.approved_on || "—"),
      bioCell(app),
      bioCell(product),
      bioCell(row.sponsor_name || "—"),
      bioCell(row.class_description || "—"),
      bioCell(review),
    );
    tbody.append(tr);
  });
  footer.replaceChildren();
  const attribution = document.createElement("p"); attribution.className = "kro-method";
  const link = document.createElement("a"); link.href = data.attribution?.url || "https://open.fda.gov/"; link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = data.attribution?.text || "Source: openFDA";
  attribution.append(link);
  if (data.window) attribution.append(document.createTextNode(` · ${t("bio.fda.window", { s: data.window.start, e: data.window.end })}`));
  if (data.publisher_last_updated) attribution.append(document.createTextNode(` · ${t("bio.fda.publisherUpdated")} ${data.publisher_last_updated}`));
  if (data.freshness?.status === "stale") attribution.append(document.createTextNode(` · ${t("badge.stale")}`));
  const method = document.createElement("p"); method.className = "kro-method"; method.textContent = localValue(data.methodology, state.lang);
  const disclaimer = document.createElement("p"); disclaimer.className = "kro-disclaimer"; disclaimer.textContent = localValue(data.disclaimer, state.lang);
  footer.append(attribution, method, disclaimer);
}

function coinPath(symbol) { return `/crypto/${encodeURIComponent(String(symbol || "").trim())}`; }

function coinLink(symbol) {
  const link = document.createElement("a"); link.className = "cboard-sym";
  link.href = coinPath(symbol); link.textContent = symbol;
  return link;
}

function cryptoGateHidden(key) {
  const code = disabledCode(key);
  return code === "crypto_section_disabled" || code === "hip3_public_display_pending_rights" || code === "crypto_sentiment_disabled"
    || code === "crypto_structure_disabled" || code === "upbit_quotation_pending_rights"
    || code === "chain_gas_disabled" || code === "chain_gas_not_configured";
}

function renderCryptoOverview() {
  const section = $("#crypto-tape"); if (!section) return;
  const stateNode = $("#ctape-state"), grid = $("#ctape-grid"), strip = $("#ctape-strip"), footer = $("#ctape-footer");
  const payload = state.cryptoOverview;
  if (!payload || !Array.isArray(payload.coins)) {
    if (cryptoGateHidden("cryptoOverview")) { section.hidden = true; return; }
    section.hidden = false; grid.hidden = true; strip.hidden = true; footer.hidden = true;
    stateNode.hidden = false; stateNode.textContent = `${t("status.unavailable")} · ${t("status.retry")}`;
    return;
  }
  const coins = payload.coins.filter((card) => card && safeNumber(card.price?.value) !== null);
  if (!coins.length) {
    section.hidden = false; grid.hidden = true; strip.hidden = true; footer.hidden = true;
    stateNode.hidden = false; stateNode.textContent = payload.provider?.error ? `${t("status.unavailable")} · ${t("status.retry")}` : t("crypto.noMarket");
    return;
  }
  section.hidden = false; stateNode.hidden = true; grid.hidden = false; strip.hidden = false; footer.hidden = false;
  grid.replaceChildren(...coins.map((card) => {
    const price = safeNumber(card.price?.value);
    const pct = safeNumber(card.change_24h?.percent);
    const article = document.createElement("article");
    article.className = `kro-card crypto-card ${changeClass(pct)}`;
    const header = document.createElement("header");
    const title = document.createElement("h3");
    const detail = document.createElement("a"); detail.className = "kro-detail"; detail.href = coinPath(card.symbol); detail.textContent = localValue(card.label, state.lang);
    title.append(detail);
    const symbol = document.createElement("a"); symbol.className = "kro-sym"; symbol.textContent = `${card.symbol}-PERP`;
    if (card.source?.url) { symbol.href = card.source.url; symbol.target = "_blank"; symbol.rel = "noopener noreferrer"; }
    header.append(title, symbol);
    const priceNode = document.createElement("div"); priceNode.className = "kro-price"; priceNode.textContent = cryptoUsd(price);
    const previous = cryptoPrevValues.get(card.symbol);
    if (previous !== undefined && price !== previous) priceNode.classList.add(price > previous ? "tick-up" : "tick-down");
    cryptoPrevValues.set(card.symbol, price);
    const vs = document.createElement("div"); vs.className = `kro-vs ${changeClass(pct)}`;
    vs.textContent = pct === null ? "—" : `${formatSigned(pct)} · 24h`;

    // 30일 추이선. 홈 보드 타일과 **같은 함수**를 부른다(console.js) — 창을
    // 자르는 규칙과 색 규칙이 화면마다 갈리면 같은 그림이 다른 뜻이 된다.
    // 아직 안 모인 코인은 선 없이 카드만 선다.
    const spark = window.mulmitSparkline?.(card.observations);
    let sparkNode = null;
    if (spark) {
      sparkNode = document.createElement("div");
      sparkNode.className = `tile-spark card-spark ${spark.tone}`;
      const period = document.createElement("span");
      period.className = "spark-period";
      period.textContent = spark.label;
      sparkNode.append(period, spark.node);
    }

    const meta = document.createElement("dl"); meta.className = "kro-meta";
    const row = (labelText, valueText) => {
      const wrap = document.createElement("div");
      const dt = document.createElement("dt"); dt.textContent = labelText;
      const dd = document.createElement("dd"); dd.textContent = valueText;
      wrap.append(dt, dd); return wrap;
    };
    meta.append(row(t("crypto.funding"), cryptoFundingText(card.funding)));
    meta.append(row(t("crypto.oi"), cryptoUsd(safeNumber(card.open_interest?.usd), { compact: true })));
    meta.append(row(t("crypto.volume"), cryptoUsd(safeNumber(card.volume_24h_usd), { compact: true })));
    const predicted = cryptoPredictedText(card.predicted_funding);
    if (predicted) meta.append(row(t("crypto.predicted"), predicted));
    const badges = document.createElement("div"); badges.className = "kro-badges";
    if (card.signal && safeNumber(card.signal.heat) !== null) {
      const chip = document.createElement("span");
      chip.className = `status-badge ${card.signal.band === "overheated" || card.signal.band === "elevated" ? "warn" : ""}`.trim();
      const move = safeNumber(card.signal.heat_24h_points);
      const trail = move === null || Math.abs(move) < 0.5 ? "" : ` ${move > 0 ? "▲" : "▼"}${Math.abs(move).toFixed(0)}`;
      chip.textContent = `${t("crypto.heatBadge", { n: Math.round(card.signal.heat) })} · ${localValue(card.signal.label, state.lang)}${trail}`;
      badges.append(chip);
    }
    const badge = (text, cls = "warn") => { const span = document.createElement("span"); span.className = `status-badge ${cls}`; span.textContent = text; badges.append(span); };
    if (card.status === "stale") badge(t("badge.stale"));
    if (card.liquidity_status === "low") badge(t("weekend.liquidity"));
    if (card.funding?.heat === "high" || card.funding?.heat === "elevated") badge(cryptoSideText(card.funding), card.funding.heat === "high" ? "error" : "warn");
    article.append(header, priceNode, vs);
    if (sparkNode) article.append(sparkNode);
    article.append(meta);
    // The whole card opens the coin page; the symbol link (venue) and any other link keep their own target.
    article.addEventListener("click", (event) => { if (!event.target.closest("a")) window.location.href = coinPath(card.symbol); });
    if (badges.childElementCount) article.append(badges);
    return article;
  }));

  strip.replaceChildren();
  const ratio = payload.eth_btc;
  if (ratio && safeNumber(ratio.value) !== null) {
    const item = document.createElement("span"); item.className = "kro-strip-item";
    const label = document.createElement("small"); label.textContent = t("crypto.ethbtc");
    const value = document.createElement("strong"); value.textContent = ratio.value.toFixed(5);
    item.append(label, value);
    const change = safeNumber(ratio.change_24h_percent);
    if (change !== null) { const em = document.createElement("em"); em.className = changeClass(change); em.textContent = `${formatSigned(change)} 24h`; item.append(em); }
    strip.append(item);
  }
  const coverage = document.createElement("span"); coverage.className = "kro-strip-item";
  const coverageLabel = document.createElement("small");
  coverageLabel.textContent = t("crypto.coverage", { n: payload.coverage?.available ?? coins.length, total: payload.coverage?.total ?? coins.length });
  coverage.append(coverageLabel);
  if (payload.as_of) { const asOf = document.createElement("small"); asOf.textContent = `${t("date.asof")} ${dateText(payload.as_of)}`; coverage.append(asOf); }
  strip.append(coverage);

  footer.replaceChildren();
  const method = document.createElement("p"); method.className = "kro-method"; method.textContent = localValue(payload.methodology, state.lang);
  const disclaimer = document.createElement("p"); disclaimer.className = "kro-disclaimer"; disclaimer.textContent = localValue(payload.disclaimer, state.lang);
  footer.append(method, disclaimer);
}

function renderCryptoSentiment() {
  const section = $("#crypto-sentiment"), stateNode = $("#cfng-state"), body = $("#cfng-body");
  if (!section || !stateNode || !body) return;
  const data = state.cryptoSentiment;
  if (!data || safeNumber(data.value) === null) {
    if (cryptoGateHidden("cryptoSentiment")) { section.hidden = true; return; }
    const collecting = disabledCode("cryptoSentiment") === "crypto_sentiment_collecting";
    section.hidden = false; body.hidden = true; stateNode.hidden = false;
    stateNode.classList.toggle("disabled", collecting);
    stateNode.textContent = collecting ? t("crypto.fng.collecting") : `${t("status.unavailable")} · ${t("status.retry")}`;
    return;
  }
  section.hidden = false; stateNode.hidden = true; stateNode.classList.remove("disabled"); body.hidden = false;
  $("#cfng-score").textContent = String(data.value);
  const staleText = data.freshness?.status === "stale" ? ` · ${t("badge.stale")}` : "";
  $("#cfng-band").textContent = `${localValue(data.classification, state.lang)} · ${t("date.asof")} ${data.as_of}${staleText}`;
  $("#cfng-marker").style.left = `calc(${Math.max(0, Math.min(100, data.value))}% - 1.5px)`;

  // Publisher's condition: attribution right next to the displayed value.
  const attribution = $("#cfng-attribution"); attribution.replaceChildren();
  if (data.attribution?.text) {
    attribution.append(document.createTextNode(`${t("crypto.fng.sourceLabel")}: `));
    const link = document.createElement("a"); link.href = data.attribution.url || "#"; link.target = "_blank"; link.rel = "noopener noreferrer";
    link.textContent = data.attribution.text; attribution.append(link);
  }

  const deltas = $("#cfng-deltas"); deltas.replaceChildren();
  const chip = (labelText, item) => {
    if (!item || safeNumber(item.change_points) === null) return;
    const span = document.createElement("span"); span.className = changeClass(item.change_points);
    span.textContent = `${labelText} ${item.value} (${item.change_points > 0 ? "+" : ""}${item.change_points})`;
    deltas.append(span);
  };
  chip(t("crypto.fng.prev"), data.previous); chip(t("crypto.fng.week"), data.week_ago); chip(t("crypto.fng.month"), data.month_ago);
  if (data.next_update_at) { const span = document.createElement("span"); span.textContent = t("crypto.fng.next", { time: dateText(data.next_update_at) }); deltas.append(span); }

  const chartHost = $("#cfng-chart");
  if (chartHost) {
    chartHost.replaceChildren();
    const chart = lineChart((data.observations || []).map((item) => ({ date: item.date, value: safeNumber(item.value) })).filter((item) => item.date && item.value !== null));
    if (chart) chartHost.append(chart); else { const empty = document.createElement("div"); empty.className = "chart-empty"; empty.textContent = t("status.noSeries"); chartHost.append(empty); }
  }

  const table = $("#cfng-table");
  $("thead", table).innerHTML = `<tr><th scope="col">${t("crypto.fng.colInput")}</th><th scope="col" class="num">${t("crypto.fng.colWeight")}</th></tr>`;
  const tbody = $("tbody", table); tbody.replaceChildren();
  for (const item of data.components || []) {
    const row = document.createElement("tr");
    const name = document.createElement("td"); name.textContent = localValue(item.label, state.lang);
    const weight = document.createElement("td"); weight.className = "num"; weight.textContent = `${item.weight_percent}%`;
    row.append(name, weight); tbody.append(row);
  }
  const mulmitScore = safeNumber(state.sentiment?.score);
  $("#cfng-compare").textContent = mulmitScore === null ? "" : t("crypto.fng.vsMulmit", { score: mulmitScore.toFixed(1), band: localValue(state.sentiment?.band, state.lang) });
  $("#cfng-disclaimer").textContent = localValue(data.disclaimer, state.lang);
}

function renderCryptoDerivatives() {
  const section = $("#crypto-derivatives"); if (!section) return;
  const stateNode = $("#cderiv-state"), wrap = $("#cderiv-wrap"), footer = $("#cderiv-footer");
  const payload = state.cryptoOverview;
  const coins = Array.isArray(payload?.coins) ? payload.coins.filter((card) => card && safeNumber(card.price?.value) !== null) : [];
  if (!coins.length) {
    if (cryptoGateHidden("cryptoOverview")) { section.hidden = true; return; }
    section.hidden = false; wrap.hidden = true; footer.hidden = true; stateNode.hidden = false;
    stateNode.textContent = `${t("status.unavailable")} · ${t("status.retry")}`;
    return;
  }
  section.hidden = false; stateNode.hidden = true; wrap.hidden = false; footer.hidden = false;
  const table = $("#cderiv-table");
  const heads = [["crypto.colCoin", ""], ["crypto.colPrice", "num"], ["crypto.col24h", "num"], ["crypto.colFunding", "num"], ["crypto.colApr", "num"], ["crypto.colPredicted", ""], ["crypto.colOi", "num"], ["crypto.colVolume", "num"], ["crypto.colState", ""]];
  $("thead", table).innerHTML = `<tr>${heads.map(([key, cls]) => `<th scope="col"${cls ? ` class="${cls}"` : ""}>${t(key)}</th>`).join("")}</tr>`;
  const tbody = $("tbody", table); tbody.replaceChildren();
  for (const card of coins) {
    const row = document.createElement("tr");
    const pct = safeNumber(card.change_24h?.percent);
    const hourly = safeNumber(card.funding?.hourly_percent);
    const apr = safeNumber(card.funding?.apr_percent);
    const cells = [
      [`${localValue(card.label, state.lang)} · ${card.symbol}`, ""],
      [cryptoUsd(safeNumber(card.price?.value)), "num"],
      [pct === null ? "—" : formatSigned(pct), `num ${changeClass(pct)}`],
      [hourly === null ? "—" : `${hourly >= 0 ? "+" : ""}${hourly.toFixed(4)}%`, "num"],
      [apr === null ? "—" : formatSigned(apr), `num ${changeClass(apr)}`],
      [cryptoPredictedText(card.predicted_funding) || "—", ""],
      [cryptoUsd(safeNumber(card.open_interest?.usd), { compact: true }), "num"],
      [cryptoUsd(safeNumber(card.volume_24h_usd), { compact: true }), "num"],
      [cryptoSideText(card.funding), ""],
    ];
    cells.forEach(([text, cls]) => { const cell = document.createElement("td"); if (cls.trim()) cell.className = cls.trim(); cell.textContent = text; row.append(cell); });
    tbody.append(row);
  }
  footer.replaceChildren();
  const note = document.createElement("span"); note.textContent = t("crypto.relayed"); footer.append(note);
  if (payload.predicted_funding?.status === "unavailable") { const warn = document.createElement("span"); warn.textContent = t("crypto.predictedUnavailable"); footer.append(warn); }
  if (payload.as_of) { const asOf = document.createElement("span"); asOf.textContent = `${t("date.asof")} ${dateText(payload.as_of)}`; footer.append(asOf); }
}

function renderCryptoVolatility() {
  const section = $("#crypto-volatility"); if (!section) return;
  const stateNode = $("#cvol-state"), body = $("#cvol-body");
  const data = state.cryptoVolatility;
  if (!data) {
    if (cryptoGateHidden("cryptoVolatility")) { section.hidden = true; return; }
    section.hidden = false; body.hidden = true; stateNode.hidden = false;
    stateNode.textContent = `${t("status.unavailable")} · ${t("status.retry")}`;
    return;
  }
  const realized = Array.isArray(data.realized) ? data.realized : [];
  const correlations = Array.isArray(data.correlations) ? data.correlations : [];
  if (data.status !== "ok" || (!realized.length && !correlations.length)) {
    section.hidden = false; body.hidden = true; stateNode.hidden = false;
    stateNode.textContent = data.status === "withheld_pending_rights" ? t("status.historyPending") : t("status.historyCollecting");
    return;
  }
  section.hidden = false; stateNode.hidden = true; body.hidden = false;
  const grid = $("#cvol-realized"); grid.replaceChildren();
  for (const block of realized) {
    for (const window of block.windows || []) {
      if (safeNumber(window.value) === null) continue;
      const card = document.createElement("article"); card.className = "cvol-card";
      const title = document.createElement("h3"); title.textContent = `${block.symbol} · ${t("crypto.vol.rv", { d: window.window_days })}`;
      const value = document.createElement("strong"); value.textContent = `${window.value.toFixed(1)}%`;
      const meta = document.createElement("small"); meta.textContent = `${t("date.asof")} ${window.as_of}`;
      card.append(title, value, meta); grid.append(card);
    }
  }
  const table = $("#cvol-corr");
  $("thead", table).innerHTML = `<tr><th scope="col">${t("crypto.vol.colPeer")}</th><th scope="col" class="num">${t("crypto.vol.col30")}</th><th scope="col" class="num">${t("crypto.vol.col90")}</th></tr>`;
  const tbody = $("tbody", table); tbody.replaceChildren();
  for (const item of correlations) {
    const row = document.createElement("tr");
    const name = document.createElement("td"); name.textContent = localValue(item.label, state.lang); row.append(name);
    for (const days of [30, 90]) {
      const window = (item.windows || []).find((entry) => entry.window_days === days);
      const cell = document.createElement("td"); cell.className = "num";
      cell.textContent = window && safeNumber(window.value) !== null
        ? `${window.value >= 0 ? "+" : ""}${window.value.toFixed(2)} (${t("crypto.vol.points", { n: window.points })})` : "—";
      row.append(cell);
    }
    tbody.append(row);
  }
  const corrWrap = table.closest(".table-scroll"); if (corrWrap) corrWrap.hidden = !correlations.length;
  const footer = $("#cvol-footer"); footer.replaceChildren();
  const basis = document.createElement("span"); basis.textContent = localValue(data.basis, state.lang); footer.append(basis);
}

function cryptoKrw(value) {
  if (value === null || value === undefined) return "—";
  const digits = Math.abs(value) >= 1000 ? 0 : 2;
  return `₩${value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

function cryptoStripItem(labelText, valueText, percent = null, noteText = null) {
  const item = document.createElement("span"); item.className = "kro-strip-item";
  const label = document.createElement("small"); label.textContent = labelText;
  const value = document.createElement("strong"); value.textContent = valueText;
  item.append(label, value);
  if (percent !== null && percent !== undefined) { const em = document.createElement("em"); em.className = changeClass(percent); em.textContent = formatSigned(percent); item.append(em); }
  if (noteText) { const note = document.createElement("small"); note.textContent = noteText; item.append(note); }
  return item;
}

function cryptoStatCard(title, valueText, subText = null, subClass = "") {
  const card = document.createElement("article"); card.className = "cvol-card";
  const heading = document.createElement("h3"); heading.textContent = title;
  const value = document.createElement("strong"); value.textContent = valueText;
  card.append(heading, value);
  if (subText) { const sub = document.createElement("small"); sub.className = subClass; sub.textContent = subText; card.append(sub); }
  return card;
}

function renderCryptoKimchi() {
  const section = $("#crypto-kimchi"); if (!section) return;
  const stateNode = $("#ckim-state"), strip = $("#ckim-strip"), grid = $("#ckim-grid"), footer = $("#ckim-footer");
  const payload = state.cryptoKimchi;
  const coins = Array.isArray(payload?.coins) ? payload.coins.filter((coin) => coin && safeNumber(coin.krw) !== null) : [];
  if (!payload || !coins.length) {
    if (cryptoGateHidden("cryptoKimchi")) { section.hidden = true; return; }
    section.hidden = false; strip.hidden = true; grid.hidden = true; footer.hidden = true;
    stateNode.hidden = false; stateNode.textContent = `${t("status.unavailable")} · ${t("status.retry")}`;
    return;
  }
  section.hidden = false; stateNode.hidden = true; strip.hidden = false; grid.hidden = false; footer.hidden = false;

  strip.replaceChildren();
  const usdt = payload.usdt;
  if (usdt && safeNumber(usdt.krw) !== null) {
    strip.append(cryptoStripItem(t("crypto.kimchi.usdtKrw"), cryptoKrw(usdt.krw), safeNumber(usdt.change_24h_percent)));
    const tether = safeNumber(usdt.tether_premium_percent);
    if (tether !== null && safeNumber(usdt.official_rate) !== null) {
      const note = `${t("kro.fx")} ${usdt.official_rate.toLocaleString("en-US", { maximumFractionDigits: 2 })} · ${kroDate(usdt.official_rate_date)} ${t("crypto.kimchi.official")}`;
      strip.append(cryptoStripItem(t("crypto.kimchi.tether"), formatSigned(tether), null, note));
    } else {
      strip.append(cryptoStripItem(t("crypto.kimchi.tether"), t("kro.noFx")));
    }
  }
  if (payload.as_of) strip.append(cryptoStripItem(t("date.asof"), dateText(payload.as_of)));

  grid.replaceChildren(...coins.map((coin) => {
    const premium = safeNumber(coin.premium_usdt_basis_percent);
    const article = document.createElement("article");
    article.className = `kro-card crypto-card ${changeClass(premium)}`;
    const header = document.createElement("header");
    const title = document.createElement("h3"); title.textContent = localValue(coin.label, state.lang);
    const symbol = document.createElement("span"); symbol.className = "kro-sym"; symbol.textContent = coin.market;
    header.append(title, symbol);
    const price = document.createElement("div"); price.className = "kro-price"; price.textContent = cryptoKrw(coin.krw);
    const vs = document.createElement("div"); vs.className = `kro-vs ${changeClass(premium)}`;
    vs.textContent = premium === null ? t("crypto.kimchi.noReference") : `${formatSigned(premium)} · ${t("crypto.kimchi.premiumUsdt")}`;
    const meta = document.createElement("dl"); meta.className = "kro-meta";
    const row = (labelText, valueText) => { const wrap = document.createElement("div"); const dt = document.createElement("dt"); dt.textContent = labelText; const dd = document.createElement("dd"); dd.textContent = valueText; wrap.append(dt, dd); return wrap; };
    const change = safeNumber(coin.change_24h_percent);
    meta.append(row(t("crypto.kimchi.upbit24h"), change === null ? "—" : formatSigned(change)));
    meta.append(row(t("crypto.kimchi.oracle"), cryptoUsd(safeNumber(coin.oracle_usd))));
    const official = safeNumber(coin.premium_official_basis_percent);
    meta.append(row(t("crypto.kimchi.premiumOfficial"), official === null ? t("kro.noFx") : `${formatSigned(official)} · ${kroDate(payload.fx?.date)}`));
    meta.append(row(t("crypto.kimchi.volume"), cryptoKrw(safeNumber(coin.volume_24h_krw))));
    article.append(header, price, vs, meta);
    const badges = document.createElement("div"); badges.className = "kro-badges";
    if (payload.source?.upbit?.stale) { const span = document.createElement("span"); span.className = "status-badge warn"; span.textContent = t("badge.stale"); badges.append(span); }
    if (badges.childElementCount) article.append(badges);
    return article;
  }));

  footer.replaceChildren();
  const attribution = document.createElement("p"); attribution.className = "kro-method";
  attribution.textContent = `${localValue(payload.source?.upbit?.attribution, state.lang)} · ${t("crypto.kimchi.oracle")}: Hyperliquid`;
  const method = document.createElement("p"); method.className = "kro-method"; method.textContent = localValue(payload.methodology, state.lang);
  const disclaimer = document.createElement("p"); disclaimer.className = "kro-disclaimer"; disclaimer.textContent = localValue(payload.disclaimer, state.lang);
  footer.append(attribution, method, disclaimer);
}

function renderCryptoStructure() {
  const section = $("#crypto-structure"); if (!section) return;
  const stateNode = $("#cstr-state"), grid = $("#cstr-grid"), bar = $("#cstr-bar"), footer = $("#cstr-footer");
  const data = state.cryptoStructure;
  if (!data || !data.dominance || safeNumber(data.dominance.btc_percent) === null) {
    if (cryptoGateHidden("cryptoStructure")) { section.hidden = true; return; }
    const collecting = disabledCode("cryptoStructure") === "crypto_structure_collecting";
    section.hidden = false; grid.hidden = true; bar.hidden = true; footer.hidden = true; stateNode.hidden = false;
    const stableWrapOff = $("#cstr-stable"); if (stableWrapOff) stableWrapOff.hidden = true;
    stateNode.classList.toggle("disabled", collecting);
    stateNode.textContent = collecting ? t("status.collecting") : `${t("status.unavailable")} · ${t("status.retry")}`;
    return;
  }
  section.hidden = false; stateNode.hidden = true; grid.hidden = false; footer.hidden = false;
  const dom = data.dominance, cap = data.market_cap || {}, vol = data.volume_24h || {};
  const pct = (value, digits = 1) => safeNumber(value) === null ? "—" : `${value.toFixed(digits)}%`;
  const pts = (value) => safeNumber(value) === null ? null : t("crypto.structure.pts", { v: `${value >= 0 ? "+" : ""}${value.toFixed(2)}` });
  const signed = (value) => safeNumber(value) === null ? null : `${formatSigned(value)} · 24h`;
  const cards = [
    [t("crypto.structure.btcDom"), pct(dom.btc_percent), pts(dom.btc_24h_change_points), changeClass(dom.btc_24h_change_points)],
    [t("crypto.structure.ethDom"), pct(dom.eth_percent), pts(dom.eth_24h_change_points), changeClass(dom.eth_24h_change_points)],
    [t("crypto.structure.othersDom"), pct(dom.others_percent), null, ""],
    [t("crypto.structure.totalCap"), cryptoUsd(safeNumber(cap.total_usd), { compact: true }), signed(cap.total_24h_change_percent), changeClass(cap.total_24h_change_percent)],
    [t("crypto.structure.stableCap"), cryptoUsd(safeNumber(cap.stablecoin_usd), { compact: true }), null, ""],
    [t("crypto.structure.volume"), cryptoUsd(safeNumber(vol.total_usd), { compact: true }), signed(vol.change_percent), changeClass(vol.change_percent)],
  ].filter(([, value]) => value !== "—");
  grid.replaceChildren(...cards.map(([title, value, sub, cls]) => cryptoStatCard(title, value, sub, cls)));

  const btc = safeNumber(dom.btc_percent), eth = safeNumber(dom.eth_percent), others = safeNumber(dom.others_percent);
  bar.replaceChildren();
  if (btc !== null && eth !== null && others !== null) {
    bar.hidden = false;
    [["btc", btc, "BTC"], ["eth", eth, "ETH"], ["others", others, localValue({ ko: "기타", en: "Others" }, state.lang)]].forEach(([cls, width, label]) => {
      const seg = document.createElement("span"); seg.className = `seg ${cls}`; seg.style.width = `${Math.max(0, Math.min(100, width))}%`; seg.title = `${label} ${width.toFixed(1)}%`; seg.textContent = width >= 8 ? `${label} ${width.toFixed(1)}%` : ""; bar.append(seg);
    });
  } else bar.hidden = true;

  const stable = data.stablecoins, stableWrap = $("#cstr-stable"), stableGrid = $("#cstr-stable-grid"), stableNote = $("#cstr-stable-note");
  if (stableWrap) {
    const coins = Array.isArray(stable?.coins) ? stable.coins : [];
    const agg = stable?.aggregate || {};
    if (!coins.length) stableWrap.hidden = true;
    else {
      stableWrap.hidden = false;
      const historyOk = stable.history?.status === "ok";
      const stableCards = coins.map((coin) => {
        const parts = [];
        if (safeNumber(coin.change_7d_percent) !== null) parts.push(`${formatSigned(coin.change_7d_percent)} · 7d`);
        else if (!historyOk) parts.push(t("crypto.structure.stable.collecting"));
        if (safeNumber(coin.peg_deviation_bp) !== null) parts.push(t("crypto.structure.stable.peg", { v: `${coin.peg_deviation_bp >= 0 ? "+" : ""}${coin.peg_deviation_bp.toFixed(1)}` }));
        return [t("crypto.structure.stable.supply", { s: coin.symbol || "?" }), cryptoCompactNumber(safeNumber(coin.circulating_supply)), parts.join(" · ") || null, changeClass(coin.change_7d_percent)];
      });
      if (safeNumber(agg.share_of_total_percent) !== null) stableCards.push([t("crypto.structure.stable.share"), `${agg.share_of_total_percent.toFixed(2)}%`, t("crypto.structure.stable.shareSub"), ""]);
      if (safeNumber(agg.volume_24h_usd) !== null) stableCards.push([t("crypto.structure.stable.volume"), cryptoUsd(agg.volume_24h_usd, { compact: true }), signed(agg.volume_24h_change_percent), changeClass(agg.volume_24h_change_percent)]);
      stableGrid.replaceChildren(...stableCards.filter(([, value]) => value !== "—").map(([title, value, sub, cls]) => cryptoStatCard(title, value, sub, cls)));
      const since = stable.history?.since || null;
      stableNote.hidden = !since;
      stableNote.textContent = since ? `${t("crypto.structure.stable.history", { since, n: stable.history?.points ?? 0 })}${stable.stale ? ` · ${t("badge.stale")}` : ""}` : "";
    }
  }

  footer.replaceChildren();
  // Attribution right under the values, as the commercial terms expect.
  const attribution = document.createElement("p"); attribution.className = "kro-method";
  attribution.append(document.createTextNode(`${t("crypto.structure.sourceLabel")}: `));
  const link = document.createElement("a"); link.href = data.attribution?.url || "https://coinmarketcap.com/"; link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = data.attribution?.text || "Data provided by CoinMarketCap"; attribution.append(link);
  if (data.as_of) attribution.append(document.createTextNode(` · ${t("date.asof")} ${dateText(data.as_of)}${data.freshness?.status === "stale" ? ` · ${t("badge.stale")}` : ""}`));
  const method = document.createElement("p"); method.className = "kro-method"; method.textContent = localValue(data.methodology, state.lang);
  const disclaimer = document.createElement("p"); disclaimer.className = "kro-disclaimer"; disclaimer.textContent = localValue(data.disclaimer, state.lang);
  footer.append(attribution, method, disclaimer);
}

function renderCryptoGas() {
  const section = $("#crypto-gas"); if (!section) return;
  const stateNode = $("#cgas-state"), grid = $("#cgas-grid"), footer = $("#cgas-footer");
  const data = state.cryptoGas;
  const chains = Array.isArray(data?.chains) ? data.chains : [];
  if (!data || !chains.length) {
    if (cryptoGateHidden("cryptoGas")) { section.hidden = true; return; }
    section.hidden = false; grid.hidden = true; footer.hidden = true; stateNode.hidden = false;
    stateNode.textContent = `${t("status.unavailable")} · ${t("status.retry")}`;
    return;
  }
  section.hidden = false; stateNode.hidden = true; grid.hidden = false; footer.hidden = false;
  const gwei = (value) => safeNumber(value) === null ? "—" : `${value >= 100 ? value.toFixed(0) : value >= 1 ? value.toFixed(2) : value.toFixed(4)} gwei`;
  grid.replaceChildren(...chains.map((chain) => {
    const card = document.createElement("article"); card.className = "cvol-card";
    const heading = document.createElement("h3"); heading.textContent = localValue(chain.label, state.lang);
    const value = document.createElement("strong");
    value.textContent = chain.status === "ok" ? gwei(safeNumber(chain.effective_gwei)) : t("crypto.gas.unavailable");
    card.append(heading, value);
    if (chain.status === "ok") {
      const lines = [];
      if (safeNumber(chain.base_fee_gwei) !== null) lines.push(`${t("crypto.gas.base")} ${gwei(chain.base_fee_gwei)}`);
      if (safeNumber(chain.priority_fee_gwei) !== null) lines.push(`${t("crypto.gas.priority")} ${gwei(chain.priority_fee_gwei)}`);
      if (safeNumber(chain.base_fee_gwei) === null && safeNumber(chain.gas_price_gwei) !== null) lines.push(`${t("crypto.gas.gasPrice")} ${gwei(chain.gas_price_gwei)}`);
      const usd = safeNumber(chain.transfer?.usd);
      if (usd !== null) lines.push(`${t("crypto.gas.transfer")} $${usd < 0.01 ? usd.toFixed(4) : usd.toFixed(2)}${chain.layer === "L2" ? ` (${t("crypto.gas.l2note")})` : ""}`);
      lines.forEach((text) => { const small = document.createElement("small"); small.textContent = text; small.style.display = "block"; card.append(small); });
    }
    if (chain.stale) { const small = document.createElement("small"); small.textContent = t("badge.stale"); small.className = "down"; card.append(small); }
    return card;
  }));
  footer.replaceChildren();
  const method = document.createElement("p"); method.className = "kro-method";
  const ethUsd = safeNumber(data.eth_usd?.value);
  method.textContent = `${localValue(data.methodology, state.lang)}${ethUsd !== null ? ` ETH ${cryptoUsd(ethUsd)}.` : ""}${data.rpc?.provider_name ? ` RPC: ${data.rpc.provider_name}.` : ""}`;
  const disclaimer = document.createElement("p"); disclaimer.className = "kro-disclaimer"; disclaimer.textContent = localValue(data.disclaimer, state.lang);
  footer.append(method, disclaimer);
}

const REGIME_TONE = { cool: "var(--accent)", steady: "var(--accent)", warm: "var(--amber, var(--accent))", elevated: "var(--amber, var(--red))", overheated: "var(--red)" };

function renderCryptoLiquidations() {
  const section = $("#crypto-liq"); if (!section) return;
  const stateNode = $("#cliq-state"), panel = $("#cliq-panel"), grid = $("#cliq-grid"), footer = $("#cliq-footer");
  const data = state.cryptoLiquidations;
  if (!data || !Array.isArray(data.coins)) {
    const code = disabledCode("cryptoLiquidations");
    if (code === "crypto_section_disabled" || code === "crypto_liquidations_disabled") { section.hidden = true; return; }
    section.hidden = false; panel.hidden = true; stateNode.hidden = false;
    stateNode.classList.toggle("disabled", code === "crypto_liquidations_collecting");
    stateNode.textContent = code === "crypto_liquidations_collecting" ? t("status.collecting") : `${t("status.unavailable")} · ${t("status.retry")}`;
    return;
  }
  section.hidden = false; stateNode.hidden = true; panel.hidden = false; footer.hidden = false;
  grid.replaceChildren();
  if (!data.coins.length) {
    const empty = document.createElement("p"); empty.className = "kro-disclaimer"; empty.textContent = t("crypto.liq.none");
    grid.append(empty);
  }
  data.coins.forEach((coin) => {
    const liq = coin.liquidations || {}, oi = coin.open_interest || {};
    const card = document.createElement("div"); card.className = "cliq-card";

    const head = document.createElement("div"); head.className = "cliq-head";
    const link = document.createElement("a"); link.href = coin.hub || `/crypto/${coin.symbol}`;
    link.textContent = (state.lang === "ko" ? coin.name?.ko : coin.name?.en) || coin.symbol;
    const oiNode = document.createElement("span"); oiNode.className = "oi";
    oiNode.textContent = `${t("crypto.liq.oi")} ${cryptoUsd(safeNumber(oi.total_usd), { compact: true })}`;
    head.append(link, oiNode);

    const total = document.createElement("p"); total.className = "cliq-total";
    total.textContent = cryptoUsd(safeNumber(liq.total_usd), { compact: true });
    const label = document.createElement("p"); label.className = "cliq-legend";
    const window_ = document.createElement("span"); window_.textContent = t("crypto.liq.window");
    const hour = document.createElement("span");
    hour.textContent = `${t("crypto.liq.hour")} ${cryptoUsd(safeNumber((liq.latest_hour || {}).long_usd) + safeNumber((liq.latest_hour || {}).short_usd), { compact: true })}`;
    label.append(window_, hour);

    const split = document.createElement("div"); split.className = "cliq-split";
    const share = safeNumber(liq.long_share_percent);
    const longBar = document.createElement("i"); longBar.className = "long"; longBar.style.width = `${share || 0}%`;
    const shortBar = document.createElement("i"); shortBar.className = "short"; shortBar.style.width = `${100 - (share || 0)}%`;
    split.append(longBar, shortBar);

    const legend = document.createElement("p"); legend.className = "cliq-legend";
    const longSide = document.createElement("span"); longSide.className = "long";
    longSide.textContent = `${t("crypto.liq.long")} ${cryptoUsd(safeNumber(liq.long_usd), { compact: true })}`;
    const shortSide = document.createElement("span"); shortSide.className = "short";
    shortSide.textContent = `${t("crypto.liq.short")} ${cryptoUsd(safeNumber(liq.short_usd), { compact: true })}`;
    legend.append(longSide, shortSide);

    // Which venues are in the number, and which said nothing — a partial total
    // that does not say so is just a wrong total.
    const venues = document.createElement("p"); venues.className = "cliq-venues";
    const included = document.createElement("b");
    included.textContent = `${t("crypto.liq.venues")}: ${(liq.venues || []).map((row) => row.venue).join(" · ") || "—"}`;
    venues.append(included);
    if ((liq.venues_silent || []).length) {
      const silent = document.createElement("span"); silent.className = "cliq-silent";
      silent.textContent = ` / ${t("crypto.liq.silent")}: ${liq.venues_silent.join(" · ")}`;
      venues.append(silent);
    }

    card.append(head, total, label, split, legend, venues);
    grid.append(card);
  });

  footer.replaceChildren();
  const attribution = document.createElement("p"); attribution.className = "kro-method";
  const source = document.createElement("a");
  source.href = data.attribution?.url || "https://coinalyze.net/";
  source.target = "_blank";
  // The written permission requires a dofollow link, so this rel must never
  // gain nofollow, ugc or sponsored (tests/test_outbound_links.py guards it).
  source.rel = "noopener noreferrer";
  source.textContent = (state.lang === "ko" ? data.attribution?.text_ko : data.attribution?.text) || "Data: Coinalyze";
  attribution.append(source);
  const basis = document.createElement("p"); basis.className = "kro-disclaimer";
  basis.textContent = state.lang === "ko" ? (data.basis_ko || "") : (data.basis_en || "");
  footer.append(attribution, basis);
}

function renderCryptoNews() {
  const section = $("#crypto-news"); if (!section) return;
  const stateNode = $("#cnews-state"), panel = $("#cnews-panel"), list = $("#cnews-list"), footer = $("#cnews-footer");
  const data = state.cryptoNews;
  if (!data || !Array.isArray(data.articles)) {
    const code = disabledCode("cryptoNews");
    if (code === "crypto_section_disabled" || code === "crypto_news_disabled") { section.hidden = true; return; }
    section.hidden = false; panel.hidden = true; stateNode.hidden = false;
    stateNode.classList.toggle("disabled", code === "crypto_news_collecting");
    stateNode.textContent = code === "crypto_news_collecting" ? t("status.collecting") : `${t("status.unavailable")} · ${t("status.retry")}`;
    return;
  }
  section.hidden = false; stateNode.hidden = true; panel.hidden = false; footer.hidden = false;
  list.replaceChildren();
  if (!data.articles.length) {
    const empty = document.createElement("li"); empty.textContent = t("crypto.news.none"); list.append(empty);
  }
  data.articles.forEach((article) => {
    const item = document.createElement("li");
    const link = document.createElement("a"); link.className = "headline";
    link.href = article.url; link.target = "_blank"; link.rel = "noopener noreferrer";
    link.textContent = article.title;
    const meta = document.createElement("div"); meta.className = "meta";
    if (article.domain) { const span = document.createElement("span"); span.textContent = article.domain; meta.append(span); }
    if (article.seendate) { const span = document.createElement("span"); span.textContent = dateText(article.seendate); meta.append(span); }
    if (safeNumber(article.also_on) > 0) { const span = document.createElement("span"); span.textContent = t("crypto.news.also", { n: article.also_on }); meta.append(span); }
    (article.coins || []).forEach((coin) => {
      const tag = document.createElement("a"); tag.className = "coin-tag"; tag.href = coin.hub;
      tag.textContent = `${coin.name || coin.symbol}`;
      meta.append(tag);
    });
    item.append(link, meta);
    list.append(item);
  });
  footer.replaceChildren();
  const attribution = document.createElement("p"); attribution.className = "kro-method";
  const source = document.createElement("a");
  source.href = data.attribution?.url || "https://www.gdeltproject.org/";
  source.target = "_blank"; source.rel = "noopener noreferrer";
  source.textContent = (state.lang === "ko" ? data.attribution?.text_ko : data.attribution?.text) || "GDELT Project";
  attribution.append(source);
  const basis = document.createElement("p"); basis.className = "kro-disclaimer";
  basis.textContent = state.lang === "ko" ? (data.basis_ko || "") : (data.basis_en || "");
  footer.append(attribution, basis);
}

function renderNewsVideos() {
  const section = $("#news-videos"); if (!section) return;
  const stateNode = $("#nvid-state"), panel = $("#nvid-panel"), list = $("#nvid-list"), footer = $("#nvid-footer");
  const data = state.newsVideos;
  if (!data || !Array.isArray(data.videos)) {
    // 레인이 꺼져 있으면 실패가 아니라 결정이다 — 재시도 안내 대신 숨긴다.
    if (disabledCode("newsVideos") === "news_videos_disabled") { section.hidden = true; return; }
    section.hidden = false; panel.hidden = true; stateNode.hidden = false;
    stateNode.textContent = `${t("status.unavailable")} · ${t("status.retry")}`;
    return;
  }
  section.hidden = false; stateNode.hidden = true; panel.hidden = false; footer.hidden = false;
  // 읽는 언어의 영상만 남긴다. 한국어로 보는 사람에게 영어 방송을, 그 반대를
  // 들이밀 이유가 없다. 한쪽이 비면 거르지 않는다 — 빈 섹션보다는 낫다.
  const matching = data.videos.filter((video) => video.lang === state.lang);
  const videos = matching.length ? matching : data.videos;
  list.replaceChildren();
  if (!videos.length) {
    const empty = document.createElement("li"); empty.textContent = t("videos.none"); list.append(empty);
  }
  videos.forEach((video) => {
    const item = document.createElement("li");
    const play = () => {
      // 유튜브 플레이어가 로드되는 첫 순간이다. 썸네일은 구글 CDN에서 오지만
      // 쿠키를 심지 않고, 쿠키는 여기서부터 붙는다.
      const frame = document.createElement("iframe"); frame.className = "nvid-frame";
      frame.src = `https://www.youtube-nocookie.com/embed/${encodeURIComponent(video.video_id)}?autoplay=1&rel=0`;
      frame.title = video.title || t("videos.title");
      frame.allow = "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture";
      frame.allowFullscreen = true;
      frame.referrerPolicy = "strict-origin-when-cross-origin";
      item.classList.add("playing");
      item.replaceChildren(frame);
    };

    const thumbs = Array.isArray(video.thumbnails) ? video.thumbnails : [];
    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.setAttribute("aria-label", t("videos.playAria", { title: video.title || "" }));
    trigger.addEventListener("click", play);
    if (thumbs.length) {
      trigger.className = "nvid-shot";
      const img = document.createElement("img");
      img.className = "nvid-thumb";
      img.loading = "lazy"; img.decoding = "async";
      // 구글에 IP는 가되 어느 페이지를 보고 있는지는 가지 않는다.
      img.referrerPolicy = "no-referrer";
      img.alt = "";                       // 제목이 바로 아래 있으므로 장식 이미지다
      img.width = 320; img.height = 180;  // 로드 전에도 자리를 잡아 밀림을 막는다
      img.src = thumbs[0].url;
      if (thumbs.length > 1) img.srcset = thumbs.map((size) => `${size.url} ${size.width}w`).join(", ");
      img.sizes = "(max-width: 760px) 100vw, 320px";
      // maxres는 없는 영상이 흔하다. 깨진 이미지 아이콘 대신 글자 카드로 물러난다.
      img.addEventListener("error", () => { trigger.classList.add("no-shot"); img.remove(); }, { once: true });
      const badge = document.createElement("span"); badge.className = "nvid-badge"; badge.textContent = "▶";
      trigger.append(img, badge);
    } else {
      trigger.className = "nvid-play";
      trigger.textContent = `▶ ${t("videos.play")}`;
    }

    const meta = document.createElement("div"); meta.className = "nvid-meta";
    const channel = document.createElement("span"); channel.className = "nvid-channel";
    channel.textContent = video.channel || ""; meta.append(channel);
    if (video.published_at) {
      const when = document.createElement("span"); when.textContent = dateText(video.published_at); meta.append(when);
    }
    // 제목은 유튜브로 나가는 평범한 링크다. 새 탭에서 보고 싶은 사람도 있다.
    const title = document.createElement("a"); title.className = "nvid-title";
    title.href = video.watch_url; title.target = "_blank"; title.rel = "noopener noreferrer";
    title.textContent = video.title || "";

    item.append(trigger, meta, title);
    list.append(item);
  });
  footer.replaceChildren();
  const attribution = document.createElement("p"); attribution.className = "kro-method";
  const source = document.createElement("a");
  source.href = data.attribution?.url || "https://www.youtube.com/";
  source.target = "_blank"; source.rel = "noopener noreferrer";
  source.textContent = (state.lang === "ko" ? data.attribution?.text_ko : data.attribution?.text) || "YouTube";
  attribution.append(source);
  const basis = document.createElement("p"); basis.className = "kro-disclaimer";
  basis.textContent = state.lang === "ko" ? (data.basis_ko || "") : (data.basis_en || "");
  footer.append(attribution, basis);
}

function renderCryptoRegime() {
  const section = $("#crypto-regime"); if (!section) return;
  const stateNode = $("#creg-state"), top = $("#creg-top"), strip = $("#creg-components"), footer = $("#creg-footer");
  const data = state.cryptoRegime;
  if (!data || !data.heat) {
    if (cryptoGateHidden("cryptoRegime")) { section.hidden = true; return; }
    section.hidden = false; top.hidden = true; strip.hidden = true; footer.hidden = true; stateNode.hidden = false;
    stateNode.textContent = `${t("status.unavailable")} · ${t("status.retry")}`;
    return;
  }
  section.hidden = false; stateNode.hidden = true; top.hidden = false; strip.hidden = false; footer.hidden = false;
  const heat = data.heat, dir = data.direction || {};
  $("#creg-heat").textContent = `${Math.round(heat.score)} / 100`;
  const heatBar = $("#creg-heat-bar");
  heatBar.style.width = `${Math.max(0, Math.min(100, heat.score))}%`;
  heatBar.style.background = REGIME_TONE[heat.band] || "var(--accent)";
  $("#creg-heat-band").textContent = localValue(heat.label, state.lang);
  const score = Math.max(-100, Math.min(100, dir.score || 0));
  $("#creg-dir").textContent = `${score > 0 ? "+" : score < 0 ? "−" : ""}${Math.round(Math.abs(score))}`;
  const dirBar = $("#creg-dir-bar");
  dirBar.style.left = `${score >= 0 ? 50 : 50 + score / 2}%`;
  dirBar.style.width = `${Math.abs(score) / 2}%`;
  dirBar.style.background = score > 0 ? "var(--green)" : score < 0 ? "var(--red)" : "var(--muted)";
  $("#creg-dir-band").textContent = localValue(dir.label, state.lang);
  $("#creg-reading").textContent = localValue(data.reading, state.lang);
  const history = data.history || null;
  const collecting = (history?.changes || {}).status === "collecting";
  const anchorMove = collecting ? null : safeNumber((history?.changes || {}).crowded_share_24h_points);
  const shares = (history?.recent || []).map((row) => row.crowded_share).filter((v) => typeof v === "number");
  const spark = $("#creg-spark");
  if (spark) {
    spark.replaceChildren();
    if (shares.length > 1) {
      const lo = Math.min(...shares), hi = Math.max(...shares), span = (hi - lo) || 1;
      const d = shares.map((value, index) => {
        const x = (index / (shares.length - 1)) * 120;
        const y = 26 - ((value - lo) / span) * 24;
        return `${index ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(" ");
      const path = createSvg("path", { d, fill: "none", "stroke-width": 1.6, stroke: anchorMove > 0 ? "var(--red)" : anchorMove < 0 ? "var(--accent)" : "var(--muted)" });
      spark.append(path);
      spark.removeAttribute("hidden");
    } else {
      spark.setAttribute("hidden", "");
    }
  }
  const deltaNode = $("#creg-delta");
  if (deltaNode) {
    deltaNode.textContent = anchorMove === null
      ? t("crypto.regime.collecting")
      : `${t("crypto.regime.change24h")} ${anchorMove > 0 ? "+" : anchorMove < 0 ? "−" : "±"}${Math.abs(anchorMove).toFixed(1)}%p`;
    deltaNode.className = `creg-delta ${changeClass(anchorMove)}`.trim();
  }

  strip.replaceChildren(...(data.components || []).map((component) => cryptoStripItem(
    localValue(component.label, state.lang),
    component.heat_score == null ? "—" : `${Math.round(component.heat_score)}`,
    null,
    localValue(component.note, state.lang),
  )));
  const sample = data.sample || {};
  if (safeNumber(sample.liquid) !== null) strip.append(cryptoStripItem(t("crypto.regime.sample"), t("crypto.regime.sampleValue", { n: sample.liquid })));

  footer.replaceChildren();
  const method = document.createElement("p"); method.className = "kro-method"; method.textContent = localValue(data.methodology, state.lang);
  const disclaimer = document.createElement("p"); disclaimer.className = "kro-disclaimer"; disclaimer.textContent = localValue(data.disclaimer, state.lang);
  footer.append(method, disclaimer);
}

function renderCryptoBoard() {
  const section = $("#crypto-board"); if (!section) return;
  const stateNode = $("#cboard-state"), strip = $("#cboard-strip"), grid = $("#cboard-grid"), footer = $("#cboard-footer");
  const data = state.cryptoBoard;
  const hasRows = data && ["movers", "leaders", "funding"].some((group) => Object.values(data[group] || {}).some((rows) => Array.isArray(rows) && rows.length));
  if (!data || !hasRows) {
    if (cryptoGateHidden("cryptoBoard")) { section.hidden = true; return; }
    section.hidden = false; strip.hidden = true; grid.hidden = true; footer.hidden = true; stateNode.hidden = false;
    stateNode.textContent = `${t("status.unavailable")} · ${t("status.retry")}`;
    return;
  }
  section.hidden = false; stateNode.hidden = true; strip.hidden = false; grid.hidden = false; footer.hidden = false;
  strip.replaceChildren();
  const totals = data.totals || {};
  if (safeNumber(totals.markets) !== null) strip.append(cryptoStripItem(t("crypto.board.markets"), String(totals.markets)));
  if (safeNumber(totals.open_interest_usd) !== null) strip.append(cryptoStripItem(t("crypto.board.totalOi"), cryptoUsd(totals.open_interest_usd, { compact: true })));
  if (safeNumber(totals.volume_24h_usd) !== null) strip.append(cryptoStripItem(t("crypto.board.totalVolume"), cryptoUsd(totals.volume_24h_usd, { compact: true })));
  if (data.as_of) strip.append(cryptoStripItem(t("date.asof"), dateText(data.as_of)));

  const table = (titleKey, rows, columns) => {
    const wrap = document.createElement("article"); wrap.className = "cboard-card";
    const heading = document.createElement("h3"); heading.textContent = t(titleKey); wrap.append(heading);
    const scroll = document.createElement("div"); scroll.className = "table-scroll";
    const tbl = document.createElement("table"); tbl.className = "accessible-table crypto-table cboard-table";
    const thead = document.createElement("thead"); thead.innerHTML = `<tr>${columns.map(([key, cls]) => `<th scope="col"${cls ? ` class="${cls}"` : ""}>${t(key)}</th>`).join("")}</tr>`;
    const tbody = document.createElement("tbody");
    for (const row of rows) {
      const tr = document.createElement("tr");
      columns.forEach(([key, cls, render]) => { const td = document.createElement("td"); const [text, extra] = render(row); td.className = `${cls || ""} ${extra || ""}`.trim(); if (text instanceof Node) td.append(text); else td.textContent = text; tr.append(td); });
      tbody.append(tr);
    }
    tbl.append(thead, tbody); scroll.append(tbl); wrap.append(scroll); return wrap;
  };
  const sym = (row) => [coinLink(row.symbol), ""];
  const price = (row) => [cryptoUsd(safeNumber(row.price)), ""];
  const change = (row) => { const v = safeNumber(row.change_24h_percent); return [v === null ? "—" : formatSigned(v), changeClass(v)]; };
  const oi = (row) => [cryptoUsd(safeNumber(row.open_interest_usd), { compact: true }), ""];
  const vol = (row) => [cryptoUsd(safeNumber(row.volume_24h_usd), { compact: true }), ""];
  const apr = (row) => { const v = safeNumber(row.funding_apr_percent); return [v === null ? "—" : formatSigned(v), changeClass(v)]; };
  const moverCols = [["crypto.board.colSymbol", "", sym], ["crypto.board.colPrice", "num", price], ["crypto.board.colChange", "num", change], ["crypto.board.colVolume", "num", vol]];
  const leaderCols = [["crypto.board.colSymbol", "", sym], ["crypto.board.colPrice", "num", price], ["crypto.board.colOi", "num", oi], ["crypto.board.colVolume", "num", vol]];
  const fundingCols = [["crypto.board.colSymbol", "", sym], ["crypto.board.colApr", "num", apr], ["crypto.board.colChange", "num", change], ["crypto.board.colOi", "num", oi]];
  grid.replaceChildren(
    table("crypto.board.gainers", data.movers?.gainers || [], moverCols),
    table("crypto.board.losers", data.movers?.losers || [], moverCols),
    table("crypto.board.oiLeaders", data.leaders?.open_interest || [], leaderCols),
    table("crypto.board.volumeLeaders", data.leaders?.volume || [], leaderCols),
    table("crypto.board.fundingHigh", data.funding?.highest || [], fundingCols),
    table("crypto.board.fundingLow", data.funding?.lowest || [], fundingCols),
  );
  footer.replaceChildren();
  const method = document.createElement("p"); method.className = "kro-method"; method.textContent = localValue(data.methodology, state.lang);
  const disclaimer = document.createElement("p"); disclaimer.className = "kro-disclaimer"; disclaimer.textContent = localValue(data.disclaimer, state.lang);
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
  { id: "skhx", market: "kr", symbols: ["xyz:skhx"], label: LABEL("SK하이닉스", "SK Hynix"), kind: "direct" },
  { id: "smsn", market: "kr", symbols: ["xyz:smsn"], label: LABEL("삼성전자 합성선물", "Samsung synthetic perpetual"), kind: "direct", note: LABEL("USD 환산 무기한 합성선물", "USD-converted synthetic perpetual") },
  { id: "kr200", market: "kr", symbols: ["xyz:kr200"], label: LABEL("Korea 200", "Korea 200"), kind: "direct" },
  { id: "hyundai", market: "kr", symbols: ["xyz:hyundai"], label: LABEL("현대차", "Hyundai"), kind: "direct" },
  { id: "ewy", market: "kr", symbols: ["xyz:ewy"], label: LABEL("EWY 24시간 보조", "EWY 24h auxiliary"), kind: "auxiliary" },
  { id: "koru", market: "kr", symbols: ["xyz:koru"], label: LABEL("KORU 24시간 보조", "KORU 24h auxiliary"), kind: "auxiliary" },
  { id: "xyz100", market: "us", symbols: ["xyz:xyz100"], label: LABEL("XYZ100", "XYZ100"), kind: "direct" },
  { id: "ustech", market: "us", symbols: ["mkts:ustech"], label: LABEL("USTECH 24시간 보조", "USTECH 24h auxiliary"), kind: "auxiliary" },
  { id: "korea_weekend", market: "kr", symbols: ["xyz:kr200", "xyz:smsn", "xyz:skhx", "xyz:hyundai"], symbolText: LABEL("KR200 · 삼성 · SK하이닉스 · 현대차", "KR200 · Samsung · SK Hynix · Hyundai"), label: LABEL("한국 주말 기준 신호", "Korea weekend reference"), kind: "referenceSignal", composite: "korea_weekend" },
  { id: "nasdaq_weekend", market: "us", symbols: ["xyz:xyz100", "mkts:ustech"], symbolText: LABEL("xyz:XYZ100 · USTECH 24시간 보조", "xyz:XYZ100 · USTECH 24h auxiliary"), label: LABEL("나스닥 주말 기준 신호", "Nasdaq weekend reference"), kind: "referenceSignal", composite: "nasdaq_weekend" },
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
  // The Korea page and the US page read the same payload; each shows its own
  // market. The reference implementation at /monitor still shows everything.
  const wanted = PAGE === "us" ? "us" : PAGE === "kr" ? "kr" : null;
  WEEKEND_CARDS.filter((definition) => !wanted || definition.market === wanted).forEach((definition) => {
    const composite = definition.composite ? payload.composites?.[definition.composite] : null; const signal = definition.composite ? null : definition.symbols.map((symbol) => bySymbol.get(symbol)).find(Boolean); const record = composite || signal;
    const mark = safeNumber(signal?.mark ?? signal?.oracle ?? record?.value); const usable = definition.composite ? Boolean(record && record.status !== "unavailable") : mark !== null;
    const role = signal?.session_role === "auxiliary_24h_only" ? "auxiliary" : signal ? "direct" : definition.kind;
    // A composite outside its documented internal window is waiting, not broken:
    // show the next opening time instead of "data not connected".
    const awaiting = Boolean(definition.composite && record?.status === "outside_internal_session");
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
    if (awaiting) { const waitBadge = document.createElement("span"); waitBadge.className = "status-badge"; waitBadge.textContent = t("weekend.awaitingSession"); $(".weekend-badges", card).append(waitBadge); }
    const quality = awaiting ? null : (signal?.reference_quality || record?.evidence_quality); if (quality) { const qualityBadge = document.createElement("span"); qualityBadge.className = "status-badge"; qualityBadge.textContent = enumText(quality); qualityBadge.title = `${t("weekend.reference")}: ${quality}`; $(".weekend-badges", card).append(qualityBadge); }
    if (signal?.stale || record?.stale) { const staleBadge = document.createElement("span"); staleBadge.className = "status-badge stale"; staleBadge.textContent = t("weekend.stale"); const age = safeNumber(signal?.age_seconds ?? record?.age_seconds); if (age !== null) staleBadge.title = `${Math.round(age)}s`; $(".weekend-badges", card).append(staleBadge); }
    $(".weekend-value", card).textContent = definition.composite ? enumText(record?.status) : formatWeekendValue(mark, signal); const ch = $(".weekend-change", card); ch.className = `weekend-change ${changeClass(delta)}`; ch.textContent = delta !== null ? `${formatSigned(delta)} · ${deltaLabel}` : awaiting && record?.session?.next_start_at ? `${t("weekend.nextSession")} · ${dateText(record.session.next_start_at)}` : t("status.unavailable");
    const baseline = safeNumber(signal?.session_baseline?.price ?? signal?.session_baseline); const previous24h = safeNumber(signal?.previous_24h); const baselines = [];
    if (baseline !== null) baselines.push(`${t("weekend.session")} baseline: ${formatWeekendValue(baseline, signal)}`);
    if (previous24h !== null) baselines.push(`24h baseline: ${formatWeekendValue(previous24h, signal)}`);
    if (baselines.length) ch.title = baselines.join(" · ");
    const strong = $$(".weekend-meta strong", card);
    if (definition.composite) { strong[0].textContent = enumText(record?.status); strong[1].textContent = awaiting ? t("weekend.awaitingSession") : enumText(record?.evidence_quality || record?.reference_quality); strong[2].textContent = enumText(record?.session?.state || record?.session?.window); }
    else { strong[0].textContent = formatContractValue(safeNumber(signal?.funding_hourly_percent), "%/h"); strong[1].textContent = formatContractValue(safeNumber(signal?.open_interest_base_units), weekendUnit(signal, "open_interest_base_units"), true); strong[2].textContent = formatContractValue(safeNumber(signal?.day_volume_usd_notional ?? signal?.day_volume), weekendUnit(signal, "day_volume_usd_notional") || "USD", true); }
    const age = safeNumber(signal?.age_seconds ?? record?.age_seconds); card.title = `${signal?.kind || (definition.composite ? "composite_reference" : role)} · ${t("date.asof")} ${dateText(signal?.as_of || signal?.fetched_at || record?.as_of || payload.generated_at)}${age === null ? "" : ` · ${Math.round(age)}s`}`;
    host.append(card);
  });
  const baseDisclaimer = localValue(payload.disclaimer, state.lang) || t("weekend.defaultDisclaimer"); $("#weekend-disclaimer").textContent = `${baseDisclaimer} ${t("weekend.samsungPerp")}`;
  // Open while the internal session is actually running, collapsed otherwise.
  // Asking the payload beats asking the clock: the window is Friday 17:00 to
  // Sunday 18:00 ET, not "is it Saturday".
  const wrapper = $("#weekend-details");
  if (wrapper) {
    const composite = payload.composites?.[wanted === "us" ? "nasdaq_weekend" : "korea_weekend"];
    wrapper.open = Boolean(composite?.session?.active) || payload.calendar_day_type === "weekend";
  }
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

// The gauge also fills the "sentiment" card in the risk tape/section, so it
// is adapted into the record shape the card renderer already understands.
function sentimentRecordPayload(data) {
  if (!data || typeof data !== "object" || safeNumber(data.score) === null) return null;
  const history = Array.isArray(data.observations) ? data.observations : [];
  const previous = history.length > 1 ? history[history.length - 2] : null;
  const delta = previous && safeNumber(previous.value) !== null ? data.score - previous.value : null;
  return { records: [{
    id: "market_sentiment", key: "sentiment", status: "ok", experimental: true,
    label: data.label, description: data.disclaimer,
    source: { provider: "mulmit", provider_name: state.lang === "ko" ? "Mulmit 자체 산출 (실험)" : "Mulmit composite (experimental)" },
    units: { long: "0-100 risk appetite", short: "" },
    latest: { date: data.as_of, value: data.score },
    previous: previous ? { date: previous.date, value: previous.value } : null,
    change: { value: delta, percent: delta !== null && previous.value ? delta / previous.value * 100 : null },
    observations: history.map((item) => ({ date: item.date, value: item.value })),
    freshness: { status: "fresh" },
    rights: { public_display: true, provider: "mulmit" },
  }] };
}

function renderSentimentIndex() {
  const stateNode = $("#sentiment-state"), body = $("#sentiment-body"), data = state.sentiment;
  if (!stateNode || !body) return;
  if (!data) {
    const disabled = disabledText("sentiment");
    stateNode.hidden = false; stateNode.classList.toggle("disabled", Boolean(disabled)); body.hidden = true;
    stateNode.textContent = disabled || `${t("status.unavailable")} · ${t("status.retry")}`;
    return;
  }
  stateNode.hidden = true; stateNode.classList.remove("disabled"); body.hidden = false;
  const locale = state.lang === "ko" ? "ko-KR" : "en-US";
  const num = (value, digits = 1) => value === null || value === undefined ? "—" : new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(value);

  $("#sentiment-score").textContent = num(data.score);
  $("#sentiment-band").textContent = `${localValue(data.band, state.lang)} · ${t("date.asof")} ${dateText(data.as_of)}`;
  $("#sentiment-marker").style.left = `calc(${Math.max(0, Math.min(100, data.score))}% - 1.5px)`;

  const chartHost = $("#sentiment-chart");
  if (chartHost) {
    chartHost.replaceChildren();
    const chart = lineChart((data.observations || []).map((item) => ({ date: item.date, value: safeNumber(item.value) })).filter((item) => item.date && item.value !== null));
    if (chart) chartHost.append(chart); else { const empty = document.createElement("div"); empty.className = "chart-empty"; empty.textContent = t("status.noSeries"); chartHost.append(empty); }
  }

  const table = $("#sentiment-table");
  const heads = ["sentiment.colInput", "sentiment.colValue", "sentiment.colPct", "sentiment.colScore", "sentiment.colDir"];
  $("thead", table).innerHTML = `<tr>${heads.map((key) => `<th scope="col">${t(key)}</th>`).join("")}</tr>`;
  const tbody = $("tbody", table); tbody.replaceChildren();
  for (const item of data.components || []) {
    const row = document.createElement("tr");
    const cells = [
      localValue(item.label, state.lang),
      `${num(item.value, 2)}${item.unit ? ` ${item.unit}` : ""}`,
      num(item.percentile),
      num(item.score),
      t(item.inverted ? "sentiment.inverted" : "sentiment.direct"),
    ];
    cells.forEach((text, index) => {
      const cell = document.createElement("td");
      if (index >= 1 && index <= 3) cell.className = "num";
      cell.textContent = text;
      if (index === 0) cell.title = `${localValue(item.rationale, state.lang)} — ${localValue(item.derivation, state.lang)}`;
      row.append(cell);
    });
    tbody.append(row);
  }
  $("#sentiment-method").textContent = localValue(
    { ko: data.method?.summary_ko, en: data.method?.summary_en }, state.lang);
  $("#sentiment-disclaimer").textContent = localValue(data.disclaimer, state.lang);
}

function renderTradingView() {
  state.tvLoaded = true; const host = $("#tradingview-host"); host.replaceChildren(); const container = document.createElement("div"); container.className = "tradingview-widget-container"; const widget = document.createElement("div"); widget.className = "tradingview-widget-container__widget";
  const script = document.createElement("script"); script.type = "text/javascript"; script.src = "https://s3.tradingview.com/external-embedding/embed-widget-stock-heatmap.js"; script.async = true;
  const blockColors = { "1d": "change", "1w": "Perf.W", "1m": "Perf.1M", "1y": "Perf.Y" };
  script.textContent = JSON.stringify({ exchanges: [], dataSource: "SPX500", grouping: "sector", blockSize: "market_cap_basic", blockColor: blockColors[state.tvPeriod], locale: state.lang, symbolUrl: "", colorTheme: "dark", hasTopBar: true, isDataSetEnabled: true, isZoomEnabled: true, hasSymbolTooltip: true, isMonoSize: false, width: "100%", height: "100%" });
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
    if (!entry.isIntersecting) return; const kind = entry.target.dataset.lazy; entry.target.dataset.lazyDone = "1";
    if (kind === "tradingview") renderTradingView(); if (kind === "correlation") loadCorrelation(); observer.unobserve(entry.target);
    // 한 번 불러온 것은 표시해 둔다. 다시 관찰하면 TradingView iframe이
    // 통째로 재로딩된다.
  }), { rootMargin: "300px 0px" }); $$("[data-lazy]:not([data-lazy-done])").forEach((node) => observer.observe(node));
}

function applyLocale() {
  document.documentElement.lang = state.lang; trNode(); renderSkeleton(); renderAll(); $("#locale-toggle").textContent = state.lang === "ko" ? "EN" : "KO";
  // 탭 제목도 따라간다. 각 페이지가 <meta name="doc-title-{lang}">로 자기 제목을
  // 들고 있고, 없으면 문서에 박힌 제목을 그대로 둔다 — 크롤러가 보는 것은
  // 언제나 HTML에 적힌 한국어 제목이라 색인에는 영향이 없다.
  const titleMeta = document.querySelector(`meta[name="doc-title-${state.lang}"]`);
  if (titleMeta?.content) document.title = titleMeta.content;
  if (state.tvLoaded) renderTradingView();
}

function setupControls() {
  $("#locale-toggle").addEventListener("click", () => { state.lang = state.lang === "ko" ? "en" : "ko"; localStorage.setItem("monitor.locale", state.lang); applyLocale(); });
  // 다크 고정(2026-08-19 운영자 결정): 라이트 팔레트가 데이터 밀도 높은 화면과
  // 어울리지 않아 토글을 제거했다. 과거에 저장된 라이트 선택도 무시한다.
  $("#refresh-button")?.addEventListener("click", loadCore);
  $("#sector-period")?.addEventListener("click", (event) => { const button = event.target.closest("button[data-period]"); if (!button) return; state.sectorPeriod = button.dataset.period; localStorage.setItem("monitor.sectorPeriod", state.sectorPeriod); renderSectors(); });
  $("#tv-period")?.addEventListener("click", (event) => { const button = event.target.closest("button[data-period]"); if (!button) return; state.tvPeriod = button.dataset.period; localStorage.setItem("monitor.tvPeriod", state.tvPeriod); $$("#tv-period button").forEach((node) => { const active = node === button; node.classList.toggle("active", active); node.setAttribute("aria-pressed", String(active)); }); if (state.tvLoaded) renderTradingView(); });
  $("#corr-period")?.addEventListener("change", () => { if (state.correlationLoaded) loadCorrelation(); });
  $$("#tv-period button").forEach((node) => { const active = node.dataset.period === state.tvPeriod; node.classList.toggle("active", active); node.setAttribute("aria-pressed", String(active)); });
}

// 검색 관심도 표의 정렬 토글. 값은 그대로고 순서만 바뀐다 — 두 질문이 다르기
// 때문이다: "누가 평소보다 튀었나"와 "누가 더 많이 검색되나".
document.getElementById("ksi-sort")?.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-ksi-sort]");
  if (!button) return;
  state.ksiSort = button.dataset.ksiSort;
  renderKrSearchInterest();
});

setupControls(); applyLocale(); setupLazySections(); loadCore();
setInterval(() => { if (!document.hidden) loadCore(); }, 15 * 60 * 1000);
// 세션 배지는 데이터가 아니라 시계라 1분마다 자체 갱신한다.
setInterval(updateSessionBadge, 60 * 1000);
// 24시간 참고가 카드의 마크가격은 실시간 소스라, 페이지 전체 주기(15분)와
// 별개로 5초마다 가볍게 갱신한다. 레이트리밋(60/분) 안이고, 상류 호출은
// 서버 캐시 TTL이 캡을 씌우므로 방문자 수와 무관하다.
if (onPage(...PAGE_FETCHES.krOvernight)) {
  setInterval(async () => {
    if (document.hidden) return;
    if (!document.getElementById("kr-overnight") && !document.getElementById("board")) return;
    const payload = await fetchJson("/api/kr/overnight", "krOvernight");
    if (payload) { state.krOvernight = payload; renderKrOvernight(); renderZonePreviews(); notifyConsole(); }
  }, 5 * 1000);
}
// 미국 야간 카드도 같은 이유로 5초 갱신. 이게 없으면 15분 주기(loadCore)에만
// 값이 바뀌어서, 계기판도 깜빡임도 돌 일이 없고 화면이 정지 화면처럼 보인다
// (실측: 라이브 /us에서 계기판 0개·추이선 0개였다).
// 정규장 중에는 서버가 카드를 만들지 않으므로 이 폴링도 곧 빈 응답을 받는다.
if (onPage(...PAGE_FETCHES.usOvernight)) {
  setInterval(async () => {
    if (document.hidden) return;
    if (!document.getElementById("us-overnight")) return;
    const payload = await fetchJson("/api/us/overnight", "usOvernight");
    if (payload) { state.usOvernight = payload; renderUsOvernight(); notifyConsole(); }
  }, 5 * 1000);
}
// 크립토 카드도 같은 이유로 5초 갱신 — 서버 TTL(15초)이 상류 호출에 캡을 씌운다.
if (onPage(...PAGE_FETCHES.cryptoOverview)) {
  setInterval(async () => {
    if (document.hidden) return;
    if (!document.getElementById("crypto-tape") && !document.getElementById("zone-crypto-mini")
      && !document.getElementById("board")) return;
    if (disabledCode("cryptoOverview")) return; // a closed gate is not a reason to keep knocking
    const payload = await fetchJson("/api/crypto/overview", "cryptoOverview");
    if (payload) { state.cryptoOverview = payload; renderCryptoOverview(); renderCryptoDerivatives(); renderZonePreviews(); notifyConsole(); }
    if (document.getElementById("crypto-kimchi") && !disabledCode("cryptoKimchi")) {
      const kimchi = await fetchJson("/api/crypto/kimchi", "cryptoKimchi");
      if (kimchi) { state.cryptoKimchi = kimchi; renderCryptoKimchi(); }
    }
  }, 5 * 1000);
  // 가스는 블록 단위(수 초~수십 초)라 30초면 충분하다 — 서버 캐시도 30초.
  setInterval(async () => {
    if (document.hidden || !document.getElementById("crypto-gas") || disabledCode("cryptoGas")) return;
    const gas = await fetchJson("/api/crypto/gas", "cryptoGas");
    if (gas) { state.cryptoGas = gas; renderCryptoGas(); }
  }, 30 * 1000);
  setInterval(async () => {
    if (document.hidden || !document.getElementById("crypto-board") || disabledCode("cryptoBoard")) return;
    const board = await fetchJson("/api/crypto/board", "cryptoBoard");
    if (board) { state.cryptoBoard = board; renderCryptoBoard(); }
  }, 30 * 1000);
}

// --- 접속자 수 ---------------------------------------------------------------
// 익명 무작위 id의 30초 하트비트. 서버가 세는 것은 최근 90초 창의 열린 브라우저
// 수라 사람 수가 아니고, 자기 자신을 포함한다. id는 다른 무엇과도 연결되지 않는다.
function presenceId() {
  let id = localStorage.getItem("mulmit.presence");
  if (!id) {
    id = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${String(Math.random()).slice(2, 12)}`;
    localStorage.setItem("mulmit.presence", id);
  }
  return id;
}

// 마지막 수신 값은 캐시에 두고 그리기만 다시 한다 — 언어 전환(renderAll)이
// 다음 박동을 기다리지 않고 즉시 새 언어로 배지를 다시 그리게 하기 위해서다.
// 주의: 캐시 변수 선언은 파일 상단(state 옆)에 있다 — renderAll이 이 블록보다
// 먼저 실행되므로 여기 let으로 두면 TDZ ReferenceError로 전체 렌더가 죽는다
// (2026-08-19 프로덕션 장애 실측).
function renderPresenceBadge() {
  if (presenceCount === null) return;
  let badge = document.getElementById("presence-badge");
  if (!badge) {
    const host = document.querySelector(".mast-actions");
    if (!host) return;
    badge = document.createElement("span");
    badge.id = "presence-badge";
    badge.className = "presence-badge";
    host.prepend(badge);
  }
  badge.title = t("presence.note");
  badge.textContent = t("presence.now", { n: presenceCount });
}

async function presenceBeat() {
  if (document.hidden) return;
  try {
    const res = await fetch("/api/presence", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: presenceId() }),
    });
    if (!res.ok) return;
    const data = await res.json();
    if (!Number.isFinite(data.count)) return;
    presenceCount = data.count;
    renderPresenceBadge();
  } catch (error) { /* 하트비트 실패는 조용히 넘어간다 — 배지는 다음 박동에 */ }
}
presenceBeat();
setInterval(presenceBeat, 30 * 1000);
// 백그라운드로 열린 탭은 숨김 상태의 박동을 건너뛰므로(집계 정직성),
// 화면에 나타나는 순간 즉시 한 번 박동해 배지가 바로 뜨게 한다.
document.addEventListener("visibilitychange", () => { if (!document.hidden) presenceBeat(); });

// --- 방문 통계 비콘 -----------------------------------------------------------
// 페이지 로드당 한 번, 익명으로: 경로·유입 호스트·presence의 무작위 id만 보낸다.
// 쿠키 없음. 실패는 조용히 무시한다 — 통계가 서비스를 방해하면 안 된다.
try {
  fetch("/api/pageview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: location.pathname, ref: document.referrer || "", id: presenceId() }),
    keepalive: true,
  }).catch(() => {});
} catch (error) { /* 통계는 최선노력 */ }

document.querySelectorAll("[data-mfds-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    state.bioMfdsFilter = button.dataset.mfdsFilter || "notable";
    document.querySelectorAll("[data-mfds-filter]").forEach((other) => other.classList.toggle("active", other === button));
    renderBioMfds();
  });
});

// a change
