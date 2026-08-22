# 바이오 섹션 계획 — 임상 파이프라인 동향 · FDA 승인 (ROADMAP #8)

작성 2026-08-22. ROADMAP #8("바이오 — ClinicalTrials.gov·PubMed, 가능·니치")의 실행 계획. 크립토 섹션(`PLAN_CRYPTO_SECTION.md`)과
같은 순서 — **권리 원문 확인 → 인벤토리 → 게이트 OFF로 구현 → 운영자가 켠다**. 단일 진실은 `docs/ROADMAP.md`, 권리 기록은
`docs/DATA_SOURCE_REGISTER.md` §3.22·§3.23.

## 0. 결론

1. **Phase 1은 외부 승인·키·비용 없이 바로 구현 가능**: 두 소스 모두 미 연방 공공 데이터이며 공개 표시·상업 이용을 막지 않는다.
   - ClinicalTrials.gov(NIH/NLM) — 약관(2023-01-31)이 요구하는 것은 4가지 **표시 의무**(출처 표기·최신 유지·처리일 표시·수정 내용 명시)뿐.
   - openFDA(FDA) — **CC0 1.0 공개 도메인**, "even for commercial purposes, all without asking permission", 출처 표기는 권장.
2. 바이오가 "니치"인 이유는 권리가 아니라 **티커 매핑과 해석**이다. 공식 스폰서↔종목 매핑이 없으므로 Mulmit이 **워치리스트(국내·미국 주요
   제약바이오 33곳)를 큐레이션**하고 스폰서명 그대로 표시한다. 상장 라벨은 Mulmit이 붙인 참고 라벨임을 밝힌다(약관의 "수정 내용 명시").
3. PubMed는 Phase 2로 미룬다 — E-utilities 정책(3 req/s, tool·email 등록)과 **초록 저작권**(NCBI: "abstracts in PubMed may incorporate
   material that may be protected by U.S. and foreign copyright laws") 때문에 **메타데이터·링크만** 가능하고, 투자 판단 가치가 낮다.
4. 한국 축(KR/US 동형화 원칙): 식약처 의약품 허가(공공데이터포털, 공공누리·키 필요)·CRIS(질병관리청 임상연구정보서비스)는 약관 확인 후 Phase 2.
5. 하지 않는 것: PDUFA 목표일 달력(공개 원천 없음 — 기업 IR 산재, 유료 벤더 영역), 주가·재료 연결 해석("승인 → 호재" 같은 문구), 초록 전문.

## 1. 권리 확인 (원문, 접근 2026-08-22)

| 소스 | 원문 | 판정 |
|---|---|---|
| **ClinicalTrials.gov** [Terms and Conditions](https://clinicaltrials.gov/about-site/terms-conditions) (Last updated 2023-01-31) | "ClinicalTrials.gov data are available to all requesters, both within and outside the United States, at no charge." · "In any publication or distribution of these data, you should: **Attribute the source of the data as ClinicalTrials.gov** · **Update the data such that they are current at all times** · **Clearly display the date the data were processed by ClinicalTrials.gov** · **State any modifications made to the content of the data**, along with a complete description of the modifications" · "You shall not assert any proprietary rights to any portion of the database, or represent the database … as other than a United States Government database." · "The ClinicalTrials.gov data carry an international copyright outside the United States … Some ClinicalTrials.gov data may be subject to the copyright of third parties" | `approved`(조건부 표시 의무) — 4조건을 응답·화면에 구현. 연구 요약문(briefSummary 등 서술 텍스트)은 제3자 저작물 가능성 → **표시하지 않음**(제목·상태·단계·일자·조건명·중재명만) |
| **openFDA** [Terms](https://open.fda.gov/terms/) · [License](https://open.fda.gov/license/) (2014-05-27) · [Authentication](https://open.fda.gov/apis/authentication/) | License: "the content, data, documentation, code, and related materials on openFDA is public domain and made available with a Creative Commons CC0 1.0 Universal dedication." Terms: "You can copy, modify, distribute, and perform the work, even for commercial purposes, all without asking permission." · "While not required … we ask that proper credit be given." · 응답 meta.disclaimer: "Do not rely on openFDA to make decisions regarding medical care. … you should assume all results are unvalidated." · 한도: 키 없음 240 req/분·1,000/일(IP당), 키(무료) 240/분·120,000/일. 단 GMDN(의료기기 용어)은 별도 라이선스 — 의약품 데이터만 쓰므로 무관 | `approved` — 출처 표기 + 면책 문구 동봉, 일 3회 호출 |
| NCBI E-utilities(PubMed) [Usage Guidelines](https://www.ncbi.nlm.nih.gov/books/NBK25497/) | "post no more than three URL requests per second"(키 있으면 10) · "limit large jobs to either weekends or between 9:00 PM and 5:00 AM Eastern time" · tool·email 파라미터 등록 · "abstracts in PubMed may incorporate material that may be protected by U.S. and foreign copyright laws. All persons reproducing, redistributing, or making commercial use of this information are expected to adhere to the terms and conditions asserted by the copyright holder." | Phase 2 — 메타데이터(제목·저널·일자·PMID 링크)만, 초록 비표시 |
| 식약처 의약품 허가(공공데이터포털) / CRIS | 미확인(공공누리 유형·키 발급·갱신 주기) | Phase 2 조사 |
| 증권사·뉴스·유료 벤더(PDUFA 달력 등) | 해당 없음 — 쓰지 않는다 | — |

## 2. 인벤토리·우선순위

| 우선 | 항목 | 소스 | 갱신 | 비고 |
|---|---|---|---|---|
| **Phase 1** | **임상 파이프라인 동향** — 워치리스트 스폰서(주 스폰서 기준)의 최근 갱신 임상: 상태(모집 중·모집 종료·완료·중단·결과 게시)·단계·적응증·중재·1차 완료 예정일, 스폰서별 등록 임상 수 | ClinicalTrials.gov API v2 `studies?query.lead=…&sort=LastUpdatePostDate:desc` | 6시간 | 약관 4조건 동봉. 중단 사유(`whyStopped`)·결과 게시일 강조 |
| **Phase 1** | **FDA 최근 승인** — 최근 60일 ORIG 승인(NDA·BLA 신약·바이오의약품, ANDA 제네릭은 건수만), 스폰서·브랜드·성분·우선심사 여부·Drugs@FDA 링크 | openFDA `drug/drugsfda` | 1일 | CC0·면책 동봉 |
| Phase 2 | 최근 문헌(스폰서/약물명) 메타데이터 | NCBI E-utilities esearch/esummary | 1일, 야간 | 초록 비표시 |
| Phase 2 | 식약처 품목허가 최근 목록 | 공공데이터포털(키) | 1일 | 공공누리 확인 후 |
| Phase 2 | FDA 자문위원회(AdComm) 일정 | FDA 웹(구조 확인 후) | 1일 | 스크래핑 정책 확인 전 보류 |
| 보류 | PDUFA 목표일 달력, 스폰서↔티커 자동 매핑, 초록 전문 | — | — | 공개 원천 없음 / 저작권 |

## 3. 설계

- **워치리스트(34)**: 미국·유럽·일본 대형 제약 20 + 한국 상장 제약바이오 14(`app/bio.py::WATCHLIST`). 각 항목은 CT.gov 주 스폰서 검색어·표시명(ko/en)·
  국가·상장 라벨(거래소·종목코드, **Mulmit이 붙인 참고 라벨**, 2026-08-22 기준). 상장 라벨은 스폰서 법인 자체가 상장된 경우만; 자회사(예: 삼성바이오에피스,
  SK Life Science=SK바이오팜 미국 자회사, Elevar Therapeutics=HLB 미국 자회사)는 메모로 표시. 실측으로 검색어 교정: "SK Biopharmaceuticals" 0건 → "SK Life Science"
  42건, "LegoChem" 0건 → "LigaChem" 14건(사명 변경), "HLB" 6건 + "Elevar" 9건.
- **최근 동향 목록**: 스폰서당 최신 갱신 25건 중 **중재(interventional) 2·3상**만, 최근 14일 내 갱신 건을 갱신일 내림차순으로(스폰서당 최대 8건, 전체 150건 —
  실측 14일 창에 277건이 잡혀 대형 제약이 표를 독점하지 않도록). UI에 전체/한국/글로벌 필터. 배지: 결과 게시(`resultsFirstPostDate`
  30일 내), 중단/철회/보류(+사유), 완료, 신규 시작(시작일 30일 내). 각 행은 `https://clinicaltrials.gov/study/NCT…` 링크.
- **약관 4조건 구현**: ① 출처 "ClinicalTrials.gov" 문구를 값 옆·푸터에 ② 6시간 갱신 + `freshness` ③ `/api/v2/version`의 `dataTimestamp`를 "ClinicalTrials.gov 처리일"로
  표시 ④ `modifications` 필드에 "워치리스트 주 스폰서로 한정·중재 2/3상 필터·필드 부분집합·한국어 라벨/상장 라벨 추가"를 명시.
- **FDA 승인**: 60일 창, `submissions[].submission_type=ORIG & submission_status=AP` 날짜가 창 안인 신청건. 신청번호 접두(NDA/BLA/ANDA)로 분류, 브랜드명은
  `openfda.brand_name` → `products[].brand_name` 순, 우선심사(`review_priority`)·제출 분류(`submission_class_code_description`, 예: "TYPE 1 - NEW MOLECULAR ENTITY").
  링크는 Drugs@FDA(`accessdata.fda.gov/scripts/cder/daf/…ApplNo=`).
- **표시 금지**: 연구 요약문·초록, 주가 연결 해석, "호재/악재" 표현, 특정 종목 추천.
- **UI**: 새 페이지 `/bio`(`window.MULMIT_PAGE="bio"`, 헤더 탭 "바이오" 전 페이지 추가, 랜딩 존 카드 4번째). 섹션: ① 임상 파이프라인 동향(스폰서 칩 + 최근 갱신 표)
  ② FDA 최근 승인(신약·바이오 표 + 제네릭 건수) ③ 고지 스트립.

## 4. 아키텍처

- 게이트(기본 false, web·ingest `&app-env`): `BIO_SECTION_ENABLED`(페이지·라우트), `CLINICALTRIALS_ENABLED`, `OPENFDA_ENABLED`; 선택 `OPENFDA_API_KEY`(ingest 전용, 없어도 동작).
  `CLINICALTRIALS_MAX_AGE`(기본 21600초), `CLINICALTRIALS_PACE_SECONDS`(요청 간격 0.6초), `OPENFDA_MAX_AGE`(86400초), `OPENFDA_WINDOW_DAYS`(60).
- 수집은 `app/ingest.py`의 `refresh_bio_trials`·`refresh_bio_fda`(블롭 `bio_trials_v1`·`bio_fda_approvals_v1`), 요청 경로는 블롭만 읽는다(CT.gov 호출 ≈ 34회/6시간,
  openFDA ≈ 1~3회/일 — 두 소스의 한도와 무관한 수준).
- 엔드포인트 `/api/bio/trials`, `/api/bio/fda` — 503 계약 `bio_section_disabled` / `bio_trials_disabled|collecting` / `bio_fda_disabled|collecting`, `lane_report`에 `bio`·
  `clinicaltrials`·`openfda`.
- 등록부 §3.22(ClinicalTrials.gov, `DS-2026-014`)·§3.23(openFDA, `DS-2026-015`).

## 5. 실측 로그 (2026-08-22, 서울 KT 가정망)

| 호출 | 결과 |
|---|---|
| CT.gov `GET /api/v2/version` | 200 — `apiVersion 2.0.5`, `dataTimestamp 2026-08-21T09:00:05` |
| CT.gov `studies?query.lead=Celltrion&sort=LastUpdatePostDate:desc&pageSize=3&fields=…&countTotal=true` | 200, `totalCount 84` — 예: NCT06939595 PHASE3 ACTIVE_NOT_RECRUITING(CT-P51 vs Keytruda, 1차 완료 2027-02), NCT07533539 PHASE1 COMPLETED. 속도 제한 헤더 없음(공식 수치 미게시 → 요청 간격 0.6초로 보수 운용) |
| CT.gov `query.spons=Celltrion` | 협력기관 포함 매칭(UNC 주 스폰서 관찰연구가 상위) → **주 스폰서는 `query.lead`** 사용 |
| 로컬 E2E(실제 API, 2026-08-22 13:3x KST) | 34 스폰서 29초(0.6초 간격)·오류 0, 14일 창 갱신 277건(캡 전) — GSK 3상 3건 NOT_YET_RECRUITING, 암젠 Tarlatamab 3상 등. openFDA 60일 창: 게시자 total 697(절별 매칭) → ORIG 승인 140건 파싱(NDA 16·BLA 7·ANDA 117, 우선심사 8·NME 11) → 전 페이지(7회) 순회 필요 확인 |
| openFDA `drug/drugsfda.json?search=submissions.submission_status_date:[20260801 TO 20260822]+AND+submissions.submission_status:AP&limit=2` | 200 — meta.last_updated 2026-08-21, 결과에 ANDA 라벨링 보충(SUPPL) 다수 → **ORIG로 한정**해야 신규 승인만 남음. curl은 `-g`(대괄호) 필요 |

### 5.1 Phase 2 실측 (2026-08-22)

| 호출 | 결과 |
|---|---|
| NCBI `esearch.fcgi?db=pubmed&term=NCT04368728[si]&retmode=json` | 200, `X-Ratelimit-Limit: 3`, count 15 — `[si]`(secondary source id)로 등록번호 검색 가능. `esummary` JSON: title·fulljournalname·pubdate·epubdate·pubtype·articleids(doi) — 초록 없음 |
| PubMed 적중률(로컬 블롭 최근 중재 2·3상 20건) | 완료/중단/결과 게시 12건 중 4건 적중(1~17편), 진행 중 8건 중 2건 → 등록번호 검색은 누락이 있어 "참고" 표기 |
| Federal Register `documents.json?conditions[agencies][]=food-and-drug-administration&conditions[type][]=NOTICE&conditions[term]="advisory committee" "notice of meeting"&conditions[publication_date][gte]=2026-02-22` | 200, 11건 — 제목 "… Advisory Committee; Notice of Meeting; Establishment of a Public Docket …", DATES "The meeting will be held on September 23, 2026, from 9 a.m. to 6 p.m. Eastern Time."(정정 공고는 DATES 공란) → 제목 필터 + DATES 정규식 |
| fda.gov 자문위 달력·robots.txt (curl, 임의 UA) | **봇 감지 리다이렉트**(`/apology_objects/abuse-detection-apology.html`, `excessive-requests-apology`) → 서버 수집 보류, RSS 없음. 브라우저로 본 달력은 194건 DataTable(Export Excel) |
| 공공데이터포털 15095677 (식약처 의약품 제품 허가정보) | 무료·"이용허락범위 제한 없음"·개발계정 자동승인 10,000/일, Base URL `apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService07`, `/getDrugPrdtPrmsnInq07`. 미리보기·명세는 로그인/팝업 → **활용신청 후 실측** |

### 7. Phase 2 구현 메모 (2026-08-22)

- **PubMed 서지**(`app/providers/pubmed.py`, `bio.refresh_bio_pubmed`): 임상 표와 같은 행(중재 2·3상·14일·스폰서당 8건·최대 150) 각각 `NCT[si]` esearch(retmax 3, pub_date 정렬) → PMID를 50개 묶음 esummary → 블롭 `bio_pubmed_v1`
  (60일 내 이전 결과 이월). **NCBI 정책 구현**: `tool=mulmit`(+`NCBI_EMAIL`), 0.4초 간격, **ET 21~05시·주말 창에서만**(`pubmed_window_open`, `PUBMED_OFFPEAK_ONLY`), 초록 미요청. 표시: 임상 표 제목 아래
  "PubMed · 논문 n건 — 첫 논문 제목(저널, 일자)" + PubMed 검색 링크, 푸터 출처·고지.
- **FDA 자문위 공고**(`app/providers/federal_register.py`, `bio.refresh_bio_adcomm`/`build_bio_adcomm`, `/api/bio/adcomm`): FR API 240일 창, 제목 필터(위원회명 + Notice of Meeting/Amendment), DATES 정규식으로 회의일,
  예정/최근 30일 종료/날짜 미기재 분류, 6시간 주기. 새 섹션 "FDA 자문위원회 회의 공고"(임상 표와 FDA 승인 사이). 로고·인장 미사용.
- **식약처 품목허가**: 검증 없는 파서를 넣지 않는다 — 운영자 활용신청(자동승인) → 실측 → 구현(등록부 §3.26).

## 6. 운영자 액션

서버 `.env`에 `BIO_SECTION_ENABLED=true`, `CLINICALTRIALS_ENABLED=true`, `OPENFDA_ENABLED=true` → `compose up -d web ingest`. 첫 블롭은 다음 ingest 주기에 저장된다. (완료 2026-08-22)

Phase 2: `PUBMED_ENABLED=true`(+ 권장 `NCBI_EMAIL=<연락 이메일>`, 선택 `NCBI_API_KEY`), `FEDERAL_REGISTER_ENABLED=true` → `compose up -d web ingest`. PubMed 첫 패스는 **ET 야간 창(KST 10~18시)**에 돈다.
식약처: data.go.kr에서 데이터셋 15095677 활용신청(개발계정 자동승인) 후 알려주면 실측·구현.
선택: openFDA 키(무료) 발급 후 `OPENFDA_API_KEY`(ingest 전용) — 일 1,000회 IP 한도는 현재 호출량(≈3/일)에 충분해 필수 아님.

## 변경 이력

| 날짜 | 내용 |
|---|---|
| 2026-08-22 | 최초 작성 — 권리 원문 4종 확인, 인벤토리·Phase 확정, API 실측, Phase 1 구현(`/bio`, `/api/bio/{trials,fda}`, 게이트 OFF) |
| 2026-08-22 | Phase 1 라이브 — 운영자 게이트 ON(13:5x KST), 첫 패스 임상 34/34·FDA 140건, `/bio` 확인 |
| 2026-08-22 | Phase 2 — PubMed 서지·FDA 자문위 공고(Federal Register) 구현(§5.1·§7), 식약처는 활용신청 대기, fda.gov 달력은 봇 감지로 보류 |
| 2026-08-22 | Phase 2 라이브 — 운영자 게이트 ON(14:2x KST), 첫 패스 PubMed 150/150·적중 34(ET 주말 창), 자문위 공고 11건 |
