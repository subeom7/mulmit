"use strict";

/* 물밑 콘솔 — 테이프 · 보드 · 모드 · 용어 (2026-08-22)
 *
 * monitor.js는 그대로 엔진으로 둔다. 이 파일은 monitor.js가 데이터를 다 받은
 * 뒤 쏘는 `mulmit:render` 이벤트만 듣고, 첫 화면에 해당하는 부분(고정 테이프와
 * 대표 숫자 보드)을 직접 그린다. 상태를 따로 들고 있지 않아서 두 파일이
 * 어긋날 일이 없다.
 *
 * 값이 없으면 그 타일은 나오지 않는다. 없는 숫자를 만들지 않는 규칙은
 * 화면 어디서나 같다.
 */

(function () {
  const $ = (sel, root = document) => root.querySelector(sel);
  const num = (value) => {
    if (value === null || value === undefined || value === "") return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  };
  const lang = () => (document.documentElement.lang === "en" ? "en" : "ko");
  const pick = (pair) => (pair && typeof pair === "object" ? pair[lang()] || pair.ko || pair.en || "" : pair || "");

  const TEXT = {
    ko: {
      sessionOpen: "한국장 진행 중", sessionClosed: "한국장 마감", sessionWeekend: "주말 · 한국장 휴장",
      sessionUs: "미국장 시간대", until: "개장까지 {t}", day: "{d}일 ", hm: "{h}시간 {m}분",
      vsClose: "{d} 종가 {p} 대비", vs24h: "24시간 전 대비", official: "고시 {d}",
      easy: "쉬움", pro: "전문가", modeLabel: "표시 수준",
      detailMark: "마크가격", detailFx: "환산 환율", detailFunding: "펀딩 APR",
      detailOi: "미결제약정", detail24h: "24시간 변화", detailClose: "공식 종가",
      detailSession: "15:30 퍼프 대비", detailVolume: "24시간 거래대금",
      detailTrend: "배경 추이선", trend90d: "최근 30일 일봉 종가", sparkPeriod: "30일",
      boardTitle: "지금 시장", boardNote: "장이 닫힌 시간의 값은 24시간 거래되는 참고가입니다.",
      won: "원", noValue: "값 없음",
    },
    en: {
      sessionOpen: "Korean market open", sessionClosed: "Korean market closed", sessionWeekend: "Weekend · Korea closed",
      sessionUs: "US market hours", until: "opens in {t}", day: "{d}d ", hm: "{h}h {m}m",
      vsClose: "vs {d} close {p}", vs24h: "vs 24h ago", official: "official {d}",
      easy: "Simple", pro: "Pro", modeLabel: "Detail level",
      detailMark: "Mark price", detailFx: "FX applied", detailFunding: "Funding APR",
      detailOi: "Open interest", detail24h: "24h change", detailClose: "Official close",
      detailSession: "vs 15:30 perp", detailVolume: "24h volume",
      detailTrend: "Background line", trend90d: "last 30 daily closes", sparkPeriod: "30D",
      boardTitle: "Markets now", boardNote: "Out-of-hours values are 24-hour reference prices.",
      won: "KRW", noValue: "no value",
    },
  };
  const t = (key, vars = {}) =>
    Object.entries(vars).reduce((out, [k, v]) => out.replace(`{${k}}`, v), TEXT[lang()][key] || key);

  /* --- 숫자 표기 -------------------------------------------------------
   * 지수와 가격은 절대 축약하지 않는다. ko-KR compact은 7,660을 "7.66천"으로,
   * 29,231을 "2.92만"으로 쓰는데 한국어 화면에서 지수 레벨을 그렇게 읽는
   * 사람은 없다. */
  const group = (value, digits) =>
    value.toLocaleString(lang() === "ko" ? "ko-KR" : "en-US", {
      minimumFractionDigits: digits, maximumFractionDigits: digits,
    });
  const decimalsFor = (value) => {
    const size = Math.abs(value);
    if (size >= 10000) return 0;
    if (size >= 100) return 2;
    if (size >= 1) return 3;
    return 5;
  };
  const money = (value, currency) => {
    if (value === null) return null;
    if (currency === "KRW") return group(Math.round(value), 0);
    return `$${group(value, decimalsFor(value))}`;
  };
  const points = (value) => (value === null ? null : group(value, Math.abs(value) >= 1000 ? 1 : 2));
  const percent = (value, digits = 2) =>
    value === null ? "—" : `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(digits)}%`;
  const direction = (value) => (value === null ? "flat" : value > 0 ? "up" : value < 0 ? "down" : "flat");
  const arrow = (value) => (value === null ? "" : value > 0 ? "▲" : value < 0 ? "▼" : "—");
  const compactUsd = (value) => {
    if (value === null) return null;
    const size = Math.abs(value);
    if (size >= 1e9) return `$${(value / 1e9).toFixed(2)}B`;
    if (size >= 1e6) return `$${(value / 1e6).toFixed(1)}M`;
    return `$${group(Math.round(value), 0)}`;
  };
  const shortDate = (iso) => {
    if (!iso) return "";
    const date = new Date(iso.length <= 10 ? `${iso}T00:00:00` : iso);
    if (Number.isNaN(date.valueOf())) return String(iso);
    return lang() === "ko"
      ? `${date.getMonth() + 1}/${date.getDate()}`
      : date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  };

  /* --- 세션 ------------------------------------------------------------
   * 시계 계산일 뿐이라 권리 문제가 없다. 휴장일은 반영하지 않으므로 그렇게
   * 말한다(주말만 구분). */
  function sessionState() {
    const now = new Date();
    const kst = new Date(now.getTime() + (now.getTimezoneOffset() + 540) * 60000);
    const day = kst.getDay();
    const minutes = kst.getHours() * 60 + kst.getMinutes();
    const weekend = day === 0 || day === 6;
    if (!weekend && minutes >= 540 && minutes <= 930) return { key: "open", label: t("sessionOpen"), tone: "is-open" };
    // 미국 정규장을 KST로 옮기면 저녁 22시 이후(월~금)와 새벽 6시 이전(화~토)이다.
    // 시간만 보고 판단하면 토요일 밤이 미국장으로 잡힌다 — 요일을 함께 본다.
    const hour = kst.getHours();
    const usOpen = (hour >= 22 && day >= 1 && day <= 5) || (hour < 6 && day >= 2 && day <= 6);
    if (usOpen) return { key: "us", label: t("sessionUs"), tone: "is-open" };
    const openAt = new Date(kst);
    openAt.setHours(9, 0, 0, 0);
    if (minutes >= 540) openAt.setDate(openAt.getDate() + 1);
    while (openAt.getDay() === 0 || openAt.getDay() === 6) openAt.setDate(openAt.getDate() + 1);
    const gap = Math.max(0, openAt - kst);
    const days = Math.floor(gap / 86400000);
    const hours = Math.floor((gap % 86400000) / 3600000);
    const mins = Math.floor((gap % 3600000) / 60000);
    const left = (days ? t("day", { d: days }) : "") + t("hm", { h: hours, m: mins });
    return {
      key: weekend ? "weekend" : "closed",
      label: `${weekend ? t("sessionWeekend") : t("sessionClosed")} · ${t("until", { t: left })}`,
      tone: "is-closed",
    };
  }

  /* --- 스파크라인 ------------------------------------------------------ */
  const SPARK_DAYS = 30;

  function sparkline(observations) {
    const values = (observations || []).map((point) => num(point.value)).filter((value) => value !== null);
    const series = values.slice(-SPARK_DAYS);
    if (series.length < 8) return null;
    let min = Math.min(...series);
    let max = Math.max(...series);
    if (min === max) return null;
    const width = 240;
    const height = 46;
    const x = (index) => (index / (series.length - 1)) * width;
    const y = (value) => height - ((value - min) / (max - min)) * (height - 4) - 2;
    const line = series.map((value, index) => `${x(index).toFixed(1)},${y(value).toFixed(1)}`).join(" L");
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("aria-hidden", "true");
    svg.innerHTML =
      `<path class="fill" d="M0,${height} L${line} L${width},${height} Z"></path>` +
      `<path class="line" d="M${line}"></path>`;
    // 선의 색은 그 선 자신이 그린 방향을 따른다 — 옆의 등락률(24시간·종가 대비)과
    // 기간이 다르므로, 선은 선의 이야기를 하고 등락률은 등락률의 이야기를 한다.
    const move = series.at(-1) - series[0];
    return { node: svg, tone: move > 0 ? "up" : move < 0 ? "down" : "flat" };
  }

  /* --- 타일 ------------------------------------------------------------ */
  // 배경 추이선이 무엇인지 말하지 않으면 헤드라인 등락과 같은 기간으로 읽힌다.
  // 기간이 다르다는 사실을 전문가 모드에서 밝힌다.
  const detailRows = (spec, hasSpark) => [
    ...(spec.detail || []),
    hasSpark ? [t("detailTrend"), t("trend90d")] : null,
  ].filter((row) => row && row[1]);

  const changeText = (value) => `${arrow(value)} ${percent(value)}`.trim();

  // 5초마다 타일을 새로 만들면 hover가 끊기고 스파크라인이 매번 다시 그려진다.
  // 구성이 같으면 글자만 갈아 끼운다.
  function updateTile(node, spec) {
    if (!node) return;
    const value = node.querySelector(".tile-value > span");
    if (value) value.textContent = spec.value;
    const unit = node.querySelector(".tile-unit");
    if (unit) unit.textContent = spec.unit || "";
    const change = node.querySelector(".tile-change");
    if (change) {
      change.className = `tile-change ${direction(spec.change)}`;
      change.textContent = changeText(spec.change);
    }
    const basis = node.querySelector(".tile-basis");
    if (basis) basis.textContent = spec.basis || "";
    const values = node.querySelectorAll(".tile-detail dd");
    detailRows(spec, Boolean(node.querySelector(".tile-spark")))
      .forEach((row, index) => { if (values[index]) values[index].textContent = row[1]; });
  }

  function tile(spec) {
    const node = document.createElement(spec.href ? "a" : "article");
    node.className = "tile";
    if (spec.href) node.href = spec.href;

    const head = document.createElement("div");
    head.className = "tile-head";
    head.innerHTML = `<span class="tile-name"></span><span class="tile-tag"></span>`;
    $(".tile-name", head).textContent = spec.name;
    $(".tile-tag", head).textContent = spec.tag || "";

    const value = document.createElement("div");
    value.className = "tile-value";
    value.innerHTML = `<span></span>${spec.unit ? '<span class="tile-unit"></span>' : ""}`;
    value.firstChild.textContent = spec.value;
    if (spec.unit) $(".tile-unit", value).textContent = spec.unit;

    const delta = document.createElement("div");
    delta.className = "tile-delta";
    const change = document.createElement("span");
    change.className = `tile-change ${direction(spec.change)}`;
    change.textContent = changeText(spec.change);
    delta.append(change);
    const basis = document.createElement("span");
    basis.className = "tile-basis";
    basis.textContent = spec.basis || "";
    delta.append(basis);

    node.append(head, value, delta);

    // 추이선과 상세는 한 발판(.tile-foot) 위에 얹는다. 따로 두면 전문가 모드에서
    // 상세 글자가 추이선 위에 겹쳐 읽히지 않았다.
    const foot = document.createElement("div");
    foot.className = "tile-foot";
    const spark = spec.observations ? sparkline(spec.observations) : null;
    const rows = detailRows(spec, Boolean(spark));
    if (rows.length) {
      const detail = document.createElement("div");
      detail.className = "tile-detail pro-only";
      const list = document.createElement("dl");
      for (const [label, text] of rows) {
        const dt = document.createElement("dt");
        dt.textContent = label;
        const dd = document.createElement("dd");
        dd.textContent = text;
        list.append(dt, dd);
      }
      detail.append(list);
      foot.append(detail);
    }

    if (spark) {
      const wrap = document.createElement("div");
      wrap.className = `tile-spark ${spark.tone}`;
      // 기간을 선 옆에 적어 둔다. 이게 없으면 "하루 −0.5%인데 선은 왜 초록이냐"가
      // 된다 — 선은 30일 이야기를 하고 등락률은 오늘 이야기를 하기 때문이다.
      const period = document.createElement("span");
      period.className = "spark-period";
      period.textContent = t("sparkPeriod");
      wrap.append(period, spark.node);
      foot.prepend(wrap);
    }
    if (foot.childElementCount) node.append(foot);
    return node;
  }

  /* --- 데이터 → 타일 명세 --------------------------------------------- */
  const observationsFor = (state, id) =>
    (state.assets?.assets || []).find((asset) => asset.id === id)?.observations || null;

  function krSpec(state, id, sparkId) {
    const card = (state.krOvernight?.cards || []).find((row) => row.id === id);
    if (!card || card.status !== "ok") return null;
    const implied = card.implied || {};
    const official = card.official || {};
    const perp = card.perp || {};
    const value = num(implied.value);
    if (value === null) return null;
    const closeValue = num(official.close);
    // 지수는 원화가 아니라 포인트다. 같은 lane에 두 단위가 섞여 있으므로
    // 카드가 스스로 말한 단위를 따른다.
    const isKrw = (implied.unit || "").toUpperCase() === "KRW";
    const asText = (input) => (isKrw ? group(Math.round(input), 0) : group(input, 2));
    return {
      key: `kr:${id}`,
      name: pick(card.label),
      tag: card.code || "",
      value: asText(value),
      unit: isKrw ? t("won") : "",
      change: num(implied.vs_official_percent),
      basis: closeValue === null ? "" : t("vsClose", { d: shortDate(official.date), p: asText(closeValue) }),
      href: card.code ? `/stock/${card.code}` : "/kr#kr-indices",
      observations: sparkId ? observationsFor(state, sparkId) : null,
      detail: [
        [t("detailMark"), money(num(perp.mark), "USD")],
        [t("detail24h"), perp.change_24h_percent === undefined ? null : percent(num(perp.change_24h_percent))],
        [t("detailClose"), closeValue === null ? null : `${asText(closeValue)} (${shortDate(official.date)})`],
        [t("detailSession"), percent(num(card.session_reference?.vs_percent))],
        [t("detailFx"), num(state.krOvernight?.fx?.rate) === null ? null
          : `${group(num(state.krOvernight.fx.rate), 1)} · ${t("official", { d: shortDate(state.krOvernight.fx.date) })}`],
      ],
    };
  }

  function coinSpec(state, symbol, sparkId) {
    const coin = (state.cryptoOverview?.coins || []).find((row) => row.symbol === symbol);
    if (!coin) return null;
    const value = num(coin.price?.value);
    if (value === null) return null;
    return {
      key: `coin:${symbol}`,
      name: pick(coin.label) || symbol,
      tag: symbol,
      value: money(value, "USD"),
      change: num(coin.change_24h?.percent),
      basis: t("vs24h"),
      href: `/crypto/${symbol}`,
      observations: sparkId ? observationsFor(state, sparkId) : null,
      detail: [
        [t("detailFunding"), coin.funding?.apr_percent === undefined ? null : percent(num(coin.funding.apr_percent))],
        [t("detailOi"), compactUsd(num(coin.open_interest?.usd))],
        [t("detailVolume"), compactUsd(num(coin.volume_24h_usd))],
      ],
    };
  }

  function assetSpec(state, id, href) {
    const asset = (state.assets?.assets || []).find((row) => row.id === id);
    if (!asset) return null;
    const value = num(asset.latest?.value);
    if (value === null) return null;
    const unit = asset.units?.short || "";
    return {
      key: `asset:${id}`,
      name: pick(asset.label).replace(/\s*(합성 무기한선물|synthetic perpetual)$/i, ""),
      tag: asset.display_symbol || "",
      value: unit === "USD" ? money(value, "USD") : points(value),
      unit: unit === "USD" || unit === "pt" ? "" : unit,
      change: num(asset.change?.percent),
      basis: t("vs24h"),
      href: href || null,
      observations: asset.observations || null,
      detail: [[t("detail24h"), percent(num(asset.change?.percent))]],
    };
  }

  /* 세션에 따라 앞에 오는 것이 달라진다 — 미국장 시간에는 미국이 먼저다. */
  function boardSpecs(state, session) {
    const kr = [
      () => krSpec(state, "samsung_electronics", "samsung"),
      () => krSpec(state, "sk_hynix", "sk_hynix"),
      () => krSpec(state, "kospi_200", "kospi") || assetSpec(state, "kospi", "/kr"),
    ];
    const global = [
      () => assetSpec(state, "sp500", "/us#global-assets"),
      () => coinSpec(state, "BTC", "bitcoin"),
      () => coinSpec(state, "ETH", "ethereum"),
    ];
    const order = session.key === "us" ? [...global, ...kr] : [...kr, ...global];
    return order.map((build) => build()).filter(Boolean);
  }

  // 구성(어떤 타일이 어떤 순서로)이 그대로면 다시 만들지 않는다.
  const layout = { board: null, tape: null };

  function renderBoard(state, session) {
    const host = $("#board");
    if (!host) return;
    const specs = boardSpecs(state, session);
    const signature = [lang(), ...specs.map((spec) => spec.key)].join("|");
    if (signature && signature === layout.board && host.children.length === specs.length) {
      specs.forEach((spec, index) => updateTile(host.children[index], spec));
    } else {
      host.replaceChildren(...specs.map(tile));
      layout.board = signature;
    }
    host.hidden = specs.length === 0;
  }

  /* --- 테이프 ---------------------------------------------------------- */
  function tapeItems(state) {
    const items = [];
    const push = (name, value, change, href) => {
      if (value === null || value === undefined) return;
      items.push({ name, value, change, href });
    };
    for (const id of ["samsung_electronics", "sk_hynix", "kospi_200"]) {
      const card = (state.krOvernight?.cards || []).find((row) => row.id === id);
      const value = num(card?.implied?.value);
      if (card?.status === "ok" && value !== null) {
        const isKrw = (card.implied.unit || "").toUpperCase() === "KRW";
        push(pick(card.label), isKrw ? group(Math.round(value), 0) : group(value, 2),
          num(card.implied.vs_official_percent), card.code ? `/stock/${card.code}` : "/kr#kr-indices");
      }
    }
    for (const id of ["sp500", "nasdaq", "gold"]) {
      const asset = (state.assets?.assets || []).find((row) => row.id === id);
      const value = num(asset?.latest?.value);
      if (value === null) continue;
      const unit = asset.units?.short || "";
      push(pick(asset.label).replace(/\s*(합성 무기한선물|synthetic perpetual)$/i, ""),
        unit === "USD" ? money(value, "USD") : points(value), num(asset.change?.percent), "/us#global-assets");
    }
    for (const symbol of ["BTC", "ETH"]) {
      const coin = (state.cryptoOverview?.coins || []).find((row) => row.symbol === symbol);
      const value = num(coin?.price?.value);
      if (value === null) continue;
      push(pick(coin.label) || symbol, money(value, "USD"), num(coin.change_24h?.percent), `/crypto/${symbol}`);
    }
    const fx = num(state.krOvernight?.fx?.rate);
    if (fx !== null) push("USD/KRW", group(fx, 1), null, "/us#exchange-rates");
    return items;
  }

  function tapeItemNode(item) {
    const node = document.createElement(item.href ? "a" : "span");
    node.className = "tape-item";
    if (item.href) node.href = item.href;
    node.innerHTML = '<span class="tape-name"></span><span class="tape-value"></span><span class="tape-delta"></span>';
    updateTapeItem(node, item);
    return node;
  }

  function updateTapeItem(node, item) {
    $(".tape-name", node).textContent = item.name;
    $(".tape-value", node).textContent = item.value;
    const delta = $(".tape-delta", node);
    const has = item.change !== null && item.change !== undefined;
    delta.className = `tape-delta ${has ? direction(item.change) : "none"}`;
    delta.textContent = has ? percent(item.change, 2) : "";
  }

  /* 테이프는 한 방향으로 계속 흐른다.
   *
   * 같은 항목 묶음을 두 벌 깔고 둘 다 자기 너비만큼(-100%) 왼쪽으로 밀면, 첫
   * 벌이 빠져나간 자리에 둘째 벌이 정확히 들어와 이음매가 보이지 않는다. 한
   * 벌이 화면보다 좁으면 빈 구간이 생기므로 트랙을 채울 때까지 반복해서 붙인다.
   * 속도는 폭에 비례해 정하므로 항목이 늘어도 흐르는 속도는 같다. */
  const TAPE_SPEED = 42; // px/s

  function buildTape(host, items) {
    const track = document.createElement("div");
    track.className = "tape-track";
    const run = document.createElement("div");
    run.className = "tape-run";
    items.forEach((item) => run.append(tapeItemNode(item)));
    track.append(run);
    host.append(track);

    const trackWidth = track.clientWidth || host.clientWidth || 0;
    let guard = 0;
    while (run.offsetWidth < trackWidth && guard++ < 12) {
      items.forEach((item) => run.append(tapeItemNode(item)));
    }
    const copy = run.cloneNode(true);
    copy.setAttribute("aria-hidden", "true");
    track.append(copy);
    const seconds = Math.max(18, Math.round(run.offsetWidth / TAPE_SPEED));
    track.style.setProperty("--tape-duration", `${seconds}s`);
  }

  /* 흐르는 띠는 움직이는 과녁이다. 누르는 순간 항목이 커서 밑에서 빠져나가면
   * 클릭이 링크가 아니라 부모 div에 떨어져 아무 일도 일어나지 않는다. 터치
   * 기기에는 hover가 아예 없어 멈추지도 않는다. 그래서 포인터가 닿는 즉시
   * 세우고, 떠날 때 다시 흐르게 한다. */
  let tapeHeld = false;
  let tapePending = null;

  function setupTapePointer() {
    const host = $("#tape");
    if (!host) return;
    const hold = () => { tapeHeld = true; host.classList.add("is-paused"); };
    const release = () => {
      tapeHeld = false;
      host.classList.remove("is-paused");
      if (tapePending) { const payload = tapePending; tapePending = null; renderTape(payload); }
    };
    host.addEventListener("pointerenter", hold);
    host.addEventListener("pointerdown", hold);
    host.addEventListener("pointerleave", release);
    host.addEventListener("pointercancel", release);
    // 터치는 손을 떼면 hover가 남지 않는다 — 탭 뒤 잠깐만 세워 두고 다시 흐른다.
    host.addEventListener("pointerup", (event) => {
      if (event.pointerType === "mouse") return;
      setTimeout(release, 2500);
    });
  }

  function renderTape(state) {
    const host = $("#tape");
    if (!host) return;
    const items = tapeItems(state);
    host.hidden = items.length === 0;
    if (!items.length) return;

    const signature = [lang(), ...items.map((item) => item.name)].join("|");
    const track = $(".tape-track", host);
    if (track && signature === layout.tape) {
      // 5초마다 다시 만들면 흐르던 띠가 매번 처음으로 튄다. 구성이 같으면
      // 글자만 갈아 끼워 애니메이션을 이어 간다.
      const nodes = track.querySelectorAll(".tape-item");
      nodes.forEach((node, index) => updateTapeItem(node, items[index % items.length]));
      return;
    }
    if (tapeHeld && track) { tapePending = state; return; }
    // 세션 배지와 접속자 수는 monitor.js가 채운다(휴장일 달력 반영). 흐르는
    // 칸 밖 왼쪽에 고정해 두고 그 노드는 건드리지 않는다.
    const keep = [$("#session-badge", host), $("#presence-badge", host)].filter(Boolean);
    host.replaceChildren(...keep);
    buildTape(host, items);
    layout.tape = signature;
  }

  /* --- 쉬움 / 전문가 --------------------------------------------------- */
  const MODE_KEY = "mulmit.mode";
  function applyMode(mode) {
    document.documentElement.dataset.mode = mode;
    document.querySelectorAll("#mode-switch button").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.mode === mode));
    });
    // 전문가 모드에서는 접혀 있던 근거를 기본으로 펼친다.
    document.querySelectorAll("details.disclose[data-mode-open]").forEach((node) => {
      node.open = mode === "pro";
    });
  }
  function setupMode() {
    const stored = localStorage.getItem(MODE_KEY);
    applyMode(stored === "pro" ? "pro" : "easy");
    $("#mode-switch")?.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-mode]");
      if (!button) return;
      localStorage.setItem(MODE_KEY, button.dataset.mode);
      applyMode(button.dataset.mode);
    });
  }

  /* --- 용어 팝오버 ------------------------------------------------------
   * 지표 이름을 클릭하면 뜻·읽는 법·흔한 오해 셋만 보여준다. 사전은
   * terms.json 한 곳에 있고, 처음 클릭할 때 한 번만 받아온다. */
  let glossary = null;
  let popover = null;

  async function loadGlossary() {
    if (glossary) return glossary;
    const response = await fetch("/static/terms.json", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`terms ${response.status}`);
    glossary = (await response.json()).terms || {};
    return glossary;
  }

  function closePopover() {
    if (!popover) return;
    document.querySelector('[data-term][aria-expanded="true"]')?.setAttribute("aria-expanded", "false");
    popover.remove();
    popover = null;
  }

  function openPopover(trigger, entry) {
    closePopover();
    popover = document.createElement("div");
    popover.className = "term-pop";
    popover.setAttribute("role", "dialog");
    popover.innerHTML =
      '<button class="term-close" type="button" aria-label="close">×</button>' +
      "<h3></h3><p class=\"term-def\"></p><dl></dl>";
    $("h3", popover).textContent = entry.title;
    $(".term-def", popover).textContent = entry.def;
    const list = $("dl", popover);
    const rows = lang() === "ko"
      ? [["어떻게 읽나", entry.read], ["흔한 오해", entry.caution]]
      : [["How to read it", entry.read], ["Common mistake", entry.caution]];
    for (const [label, text] of rows) {
      if (!text) continue;
      const dt = document.createElement("dt");
      dt.textContent = label;
      const dd = document.createElement("dd");
      dd.textContent = text;
      list.append(dt, dd);
    }
    document.body.append(popover);

    if (window.matchMedia("(min-width: 561px)").matches) {
      const box = trigger.getBoundingClientRect();
      const width = popover.offsetWidth;
      const left = Math.min(Math.max(12, box.left + window.scrollX), window.innerWidth - width - 12);
      const below = box.bottom + window.scrollY + 8;
      const above = box.top + window.scrollY - popover.offsetHeight - 8;
      const fitsBelow = box.bottom + popover.offsetHeight + 20 < window.innerHeight;
      popover.style.left = `${left}px`;
      popover.style.top = `${fitsBelow || above < window.scrollY ? below : above}px`;
    }
    trigger.setAttribute("aria-expanded", "true");
    $(".term-close", popover).focus();
  }

  function setupTerms() {
    document.addEventListener("click", async (event) => {
      if (popover && event.target.closest(".term-close")) return closePopover();
      if (popover && !event.target.closest(".term-pop") && !event.target.closest("[data-term]")) closePopover();
      const trigger = event.target.closest("[data-term]");
      if (!trigger) return;
      event.preventDefault();
      if (trigger.getAttribute("aria-expanded") === "true") return closePopover();
      try {
        const terms = await loadGlossary();
        const entry = terms[trigger.dataset.term]?.[lang()];
        if (entry) openPopover(trigger, entry);
      } catch {
        /* 사전을 못 받아도 화면은 그대로 둔다 — 설명이 없을 뿐이다. */
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closePopover();
    });
    window.addEventListener("resize", closePopover);
  }

  /* --- 시작 ------------------------------------------------------------ */
  document.addEventListener("mulmit:render", (event) => {
    const state = event.detail;
    if (!state) return;
    // legal.css와 같은 규칙(.lang-ko/.lang-en)을 쓰기 위한 축. monitor.js는
    // <html lang>만 바꾸는데, lang 속성으로 직접 셀렉트하면 문서 전체가 걸린다.
    document.documentElement.dataset.lang = lang();
    const session = sessionState();
    renderTape(state);
    renderBoard(state, session);
  });

  setupMode();
  setupTerms();
  setupTapePointer();
})();
