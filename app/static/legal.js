"use strict";

/* 법적 고지 페이지의 언어·테마 토글.
   본문은 이미 DOM에 KO/EN 양쪽이 들어 있으므로 이 스크립트가 실패해도
   페이지는 기본 언어로 그대로 읽힌다. 대시보드와 같은 localStorage 키를
   써서 사이트 전체 선택이 이어지도록 한다. */

const root = document.documentElement;

const savedTheme = localStorage.getItem("monitor.theme") || localStorage.getItem("theme");
if (savedTheme === "light" || savedTheme === "dark") root.dataset.theme = savedTheme;

const savedLocale = localStorage.getItem("monitor.locale") || localStorage.getItem("locale");
let lang = savedLocale === "en" ? "en" : "ko";

function applyLang() {
  root.dataset.lang = lang;
  root.lang = lang;
  const button = document.getElementById("locale-toggle");
  if (button) {
    button.textContent = lang === "ko" ? "EN" : "한국어";
    button.setAttribute("aria-label", lang === "ko" ? "Switch to English" : "한국어로 전환");
  }
  const title = document.querySelector(`title[data-lang="${lang}"]`)
    || document.querySelector("meta[name='doc-title-" + lang + "']");
  if (title && title.content) document.title = title.content;
}

document.getElementById("locale-toggle")?.addEventListener("click", () => {
  lang = lang === "ko" ? "en" : "ko";
  localStorage.setItem("monitor.locale", lang);
  localStorage.setItem("locale", lang);
  applyLang();
});

document.getElementById("theme-toggle")?.addEventListener("click", () => {
  const next = root.dataset.theme === "light" ? "dark" : "light";
  root.dataset.theme = next;
  localStorage.setItem("monitor.theme", next);
  localStorage.setItem("theme", next);
});

applyLang();
