/* One search box for the whole site: coins, Korean listings, US tickers.
 *
 * Standalone on purpose. Six pages load monitor.js and two hub pages
 * (/stock/…, /crypto/…) do not, but all of them share the masthead and
 * monitor.css — so this mounts itself into `.mast-actions` and depends on
 * nothing else. Every roster is stored server-side; a keystroke never
 * reaches an upstream API.
 */
(() => {
  "use strict";

  const actions = document.querySelector(".mast-actions");
  if (!actions || document.getElementById("site-search")) return;

  const COPY = {
    ko: { placeholder: "종목·코인 검색", label: "검색", empty: "일치하는 종목이 없습니다.", error: "검색을 불러오지 못했습니다." },
    en: { placeholder: "Search markets", label: "Search", empty: "No matching market.", error: "Search is unavailable." },
  };
  const lang = () => (localStorage.getItem("monitor.locale") === "en" ? "en" : "ko");
  const t = (key) => COPY[lang()][key];

  const form = document.createElement("form");
  form.className = "site-search";
  form.id = "site-search";
  form.setAttribute("role", "search");
  form.autocomplete = "off";

  const input = document.createElement("input");
  input.type = "search";
  input.className = "site-search-input";
  input.id = "site-search-input";
  input.setAttribute("aria-label", t("label"));
  input.setAttribute("aria-expanded", "false");
  input.setAttribute("aria-controls", "site-search-results");
  input.setAttribute("role", "combobox");
  input.placeholder = t("placeholder");

  const panel = document.createElement("div");
  panel.className = "site-search-panel";
  panel.id = "site-search-results";
  panel.setAttribute("role", "listbox");
  panel.hidden = true;

  form.append(input, panel);
  actions.prepend(form);

  let items = [];        // flat list of anchors, for keyboard travel
  let active = -1;
  let controller = null;
  let timer = 0;

  const close = () => {
    panel.hidden = true;
    input.setAttribute("aria-expanded", "false");
    items = [];
    active = -1;
  };

  const highlight = (next) => {
    if (!items.length) return;
    if (active >= 0) items[active].classList.remove("is-active");
    active = (next + items.length) % items.length;
    items[active].classList.add("is-active");
    items[active].scrollIntoView({ block: "nearest" });
  };

  const note = (text) => {
    const p = document.createElement("p");
    p.className = "site-search-note";
    p.textContent = text;
    panel.replaceChildren(p);
    panel.hidden = false;
    input.setAttribute("aria-expanded", "true");
    items = [];
    active = -1;
  };

  const percentText = (value) => {
    if (typeof value !== "number" || !Number.isFinite(value)) return "";
    return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
  };

  const row = (hit) => {
    const link = document.createElement("a");
    link.className = "site-search-hit";
    link.href = hit.hub;
    link.setAttribute("role", "option");

    const symbol = document.createElement("span");
    symbol.className = "hit-symbol";
    symbol.textContent = hit.symbol;

    const name = document.createElement("span");
    name.className = "hit-name";
    name.textContent = lang() === "en" ? (hit.name_en || hit.name) : hit.name;

    const meta = document.createElement("span");
    meta.className = "hit-meta";
    if (hit.kind === "kr_stock" && typeof hit.change_percent === "number") {
      meta.textContent = percentText(hit.change_percent);
      meta.classList.add(hit.change_percent > 0 ? "up" : hit.change_percent < 0 ? "down" : "flat");
    } else {
      meta.textContent = hit.market || "";
    }

    link.append(symbol, name, meta);
    return link;
  };

  const render = (payload) => {
    const groups = Array.isArray(payload.groups) ? payload.groups : [];
    if (!groups.length) {
      note(t("empty"));
      return;
    }
    const frag = document.createDocumentFragment();
    const found = [];
    for (const group of groups) {
      const heading = document.createElement("p");
      heading.className = "site-search-group";
      heading.textContent = (group.label && group.label[lang()]) || group.kind;
      frag.append(heading);
      for (const hit of group.results || []) {
        const link = row(hit);
        found.push(link);
        frag.append(link);
      }
    }
    panel.replaceChildren(frag);
    panel.hidden = false;
    input.setAttribute("aria-expanded", "true");
    items = found;
    active = -1;
  };

  const run = async (query) => {
    if (controller) controller.abort();
    controller = new AbortController();
    try {
      const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`, {
        signal: controller.signal,
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error(String(response.status));
      render(await response.json());
    } catch (error) {
      if (error && error.name === "AbortError") return;  // superseded by a newer keystroke
      note(t("error"));
    }
  };

  input.addEventListener("input", () => {
    const query = input.value.trim();
    window.clearTimeout(timer);
    if (query.length < 1) {
      if (controller) controller.abort();
      close();
      return;
    }
    timer = window.setTimeout(() => run(query), 180);
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") { event.preventDefault(); highlight(active + 1); }
    else if (event.key === "ArrowUp") { event.preventDefault(); highlight(active - 1); }
    else if (event.key === "Escape") { close(); input.blur(); }
    else if (event.key === "Enter" && active >= 0) { event.preventDefault(); items[active].click(); }
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (items.length) items[Math.max(active, 0)].click();
  });

  input.addEventListener("focus", () => {
    if (input.value.trim() && panel.childElementCount) {
      panel.hidden = false;
      input.setAttribute("aria-expanded", "true");
    }
  });

  document.addEventListener("click", (event) => {
    if (!form.contains(event.target)) close();
  });

  // "/" jumps to the box, the way every other market terminal does — but never
  // while the visitor is already typing somewhere.
  document.addEventListener("keydown", (event) => {
    if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
    const tag = (event.target && event.target.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (event.target && event.target.isContentEditable)) return;
    event.preventDefault();
    input.focus();
  });

  // The locale button lives in monitor.js; mirror it without importing anything.
  const localeButton = document.getElementById("locale-toggle");
  if (localeButton) {
    localeButton.addEventListener("click", () => {
      window.setTimeout(() => {
        input.placeholder = t("placeholder");
        input.setAttribute("aria-label", t("label"));
        if (input.value.trim()) run(input.value.trim());
      }, 0);
    });
  }
})();
