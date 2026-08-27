/* PWA 부트스트랩 — 서비스 워커 등록, 푸시 구독 토글, 설치 유도.
 *
 * 전부 이 파일에 산다 — 페이지마다 인라인으로 흩어 두면 한쪽만 고치는
 * 사고가 난다. 어느 페이지에나 실리므로 특정 페이지의 마크업·스타일시트에
 * 기대지 않는다(배너는 인라인 스타일로 자기 완결).
 *
 * register("/sw.js")의 URL에는 ?v= 를 붙이지 않는다. 워커 URL은 브라우저가
 * 워커의 정체성으로 쓰는 키라서, URL이 바뀌면 갱신이 아니라 딴 워커가 된다.
 * 갱신은 브라우저가 /sw.js 바이트를 비교해서 알아서 한다(서버는 no-cache).
 *
 * 푸시 토글(#kimchi-alert-toggle, /crypto의 김프 카드)은 보여 주기 전에 세
 * 문을 차례로 통과해야 한다: 브라우저 지원(iOS는 홈 화면 설치본에서만
 * PushManager가 있다) → 서버 게이트(/api/push/config) → 권한. 어느 문에서
 * 막히든 버튼은 숨김/비활성으로 남고 콘솔 오류를 만들지 않는다 — 알림은
 * 부가 기능이라, 실패가 시세 화면을 건드리면 안 된다.
 */
(function () {
  "use strict";

  if (!("serviceWorker" in navigator)) return;
  var registration = navigator.serviceWorker.register("/sw.js").catch(function () {
    // 등록이 실패해도 사이트는 그대로 동작한다. 조용히 넘어간다.
    return null;
  });

  // 언어. 이 파일은 모든 페이지에 실리므로 스스로 판단해야 한다 —
  // <html lang>은 페이지마다 세우는 주체가 다르고(대시보드는 monitor.js,
  // 상세 페이지는 자기 <head> 부트) 이 스크립트가 그보다 먼저 돌 수도 있다.
  // 그래서 저장된 값을 직접 읽는다. 열쇠는 사이트 전체가 같다.
  var EN = false;
  try { EN = localStorage.getItem("monitor.locale") === "en"; } catch (e) { /* 저장소 차단 */ }
  function t(ko, en) { return EN ? en : ko; }

  var TOPIC = "kimchi";

  // applicationServerKey는 base64url 문자열이 아니라 바이트를 요구한다.
  function base64UrlToBytes(value) {
    var padded = value + "=".repeat((4 - (value.length % 4)) % 4);
    var raw = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
    var bytes = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
    return bytes;
  }

  function postJson(path, body) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  function setupKimchiToggle() {
    var button = document.getElementById("kimchi-alert-toggle");
    if (!button) return;
    if (!("PushManager" in window) || !("Notification" in window)) return;

    var serverConfig = null;

    function render(state) {
      button.hidden = false;
      button.disabled = state === "blocked";
      if (state === "on") {
        button.textContent = t("🔔 알림 켜짐 · 누르면 해제", "🔔 Alerts on · tap to turn off");
        button.setAttribute("aria-pressed", "true");
      } else if (state === "blocked") {
        button.textContent = t("🔕 브라우저에서 알림이 차단됨", "🔕 Notifications blocked by the browser");
        button.setAttribute("aria-pressed", "false");
      } else {
        var threshold =
          serverConfig && serverConfig.topics && serverConfig.topics[TOPIC]
            ? serverConfig.topics[TOPIC].threshold_percent
            : 3;
        button.textContent = t("🔔 ±" + threshold + "% 넘으면 알림 받기", "🔔 Alert me past ±" + threshold + "%");
        button.setAttribute("aria-pressed", "false");
      }
    }

    function refresh(reg) {
      if (Notification.permission === "denied") {
        render("blocked");
        return;
      }
      reg.pushManager.getSubscription().then(function (subscription) {
        render(subscription ? "on" : "off");
      });
    }

    function enable(reg) {
      return Notification.requestPermission().then(function (permission) {
        if (permission !== "granted") return refresh(reg);
        return reg.pushManager
          .subscribe({
            userVisibleOnly: true,
            applicationServerKey: base64UrlToBytes(serverConfig.vapid_public_key),
          })
          .then(function (subscription) {
            var raw = subscription.toJSON();
            return postJson("/api/push/subscribe", {
              endpoint: raw.endpoint,
              keys: raw.keys,
              topics: [TOPIC],
            }).then(function (response) {
              if (!response.ok) return subscription.unsubscribe();
            });
          })
          .then(function () {
            refresh(reg);
          });
      });
    }

    function disable(reg) {
      return reg.pushManager.getSubscription().then(function (subscription) {
        if (!subscription) return refresh(reg);
        var endpoint = subscription.endpoint;
        return subscription
          .unsubscribe()
          .then(function () {
            return postJson("/api/push/unsubscribe", { endpoint: endpoint });
          })
          .then(function () {
            refresh(reg);
          });
      });
    }

    Promise.all([
      fetch("/api/push/config").then(function (response) {
        return response.ok ? response.json() : { enabled: false };
      }),
      registration.then(function () {
        return navigator.serviceWorker.ready;
      }),
    ])
      .then(function (results) {
        serverConfig = results[0];
        var reg = results[1];
        if (!serverConfig || !serverConfig.enabled || !serverConfig.vapid_public_key) return;
        refresh(reg);
        button.addEventListener("click", function () {
          button.disabled = true;
          reg.pushManager
            .getSubscription()
            .then(function (subscription) {
              return subscription ? disable(reg) : enable(reg);
            })
            .catch(function () {})
            .then(function () {
              button.disabled = Notification.permission === "denied";
            });
        });
      })
      .catch(function () {
        // 게이트가 닫혀 있거나 워커가 없으면 버튼은 숨겨진 채 남는다.
      });
  }

  // --- 설치 유도 --------------------------------------------------------------
  //
  // 크롬의 beforeinstallprompt는 기본 인포바의 타이밍이 우리 손 밖이라 잡아
  // 둔다(preventDefault). iOS에는 그 이벤트 자체가 없어서, 설치 안 된 iOS
  // 브라우저에는 "공유 → 홈 화면에 추가" 안내를 보여 준다 — iOS 푸시는 홈
  // 화면 설치본만 받을 수 있으니 이 배너가 알림의 관문이기도 하다.
  //
  // 조용함의 규칙: standalone으로 열렸거나 설치된 적이 있으면 영영 안 보이고,
  // 방문 첫 페이지에서는 안 보이며(둘째 페이지뷰부터), 닫으면 30일 쉰다.
  // localStorage는 실패할 수 있으니(시크릿 창 등) 전부 try로 감싼다 — 그때
  // 배너는 다시 후보가 될 뿐이고 닫기 자체는 그 자리에서 여전히 동작한다.

  var SNOOZE_KEY = "mulmit-install-snooze";
  var VISITED_KEY = "mulmit-visited";
  var INSTALLED_KEY = "mulmit-installed";
  var SNOOZE_MS = 30 * 24 * 60 * 60 * 1000;

  function storageGet(key) {
    try {
      return localStorage.getItem(key);
    } catch (error) {
      return null;
    }
  }
  function storageSet(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch (error) {
      // 저장 못 하면 규칙이 조금 후해질 뿐, 동작은 그대로다.
    }
  }

  var firstVisit = !storageGet(VISITED_KEY);
  storageSet(VISITED_KEY, "1");

  function isStandalone() {
    return (
      (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) ||
      window.navigator.standalone === true
    );
  }
  function isIos() {
    return (
      /iPad|iPhone|iPod/.test(navigator.userAgent) ||
      // iPadOS 사파리는 데스크톱 UA를 쓴다 — 터치 지원으로 가른다.
      (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)
    );
  }
  function isTouchDevice() {
    // 설치 배너는 폰·태블릿 전용(운영자 결정 2026-08-27). PC 크롬에서도
    // beforeinstallprompt는 발화하지만 거기서 배너는 소음이다 — 데스크톱
    // 설치를 원하는 사람에게는 주소창의 브라우저 자체 설치 아이콘이 남는다.
    // UA 대신 기기 성질로 가른다: 주 입력이 hover 없는 거친 포인터(손가락)면
    // 폰·태블릿이고, 터치스크린 노트북은 주 입력이 마우스라 걸리지 않는다.
    return window.matchMedia && window.matchMedia("(hover: none) and (pointer: coarse)").matches;
  }
  function bannerAllowed() {
    if (!isTouchDevice()) return false;
    if (isStandalone() || firstVisit) return false;
    if (storageGet(INSTALLED_KEY)) return false;
    return Date.now() >= Number(storageGet(SNOOZE_KEY) || 0);
  }

  var banner = null;
  function hideBanner() {
    if (banner && banner.parentNode) banner.parentNode.removeChild(banner);
    banner = null;
  }
  function snoozeBanner() {
    storageSet(SNOOZE_KEY, String(Date.now() + SNOOZE_MS));
    hideBanner();
  }

  function showBanner(bodyText, actionLabel, onAction) {
    if (banner) return;
    banner = document.createElement("div");
    banner.setAttribute("role", "dialog");
    banner.setAttribute("aria-label", t("앱 설치 안내", "Install this app"));
    banner.style.cssText =
      "position:fixed;left:50%;transform:translateX(-50%);bottom:16px;z-index:9999;" +
      "box-sizing:border-box;width:calc(100% - 24px);max-width:420px;" +
      "display:flex;align-items:center;gap:12px;padding:12px 14px;" +
      "background:#10151b;color:#f3f6f8;border:1px solid #2a3138;border-radius:12px;" +
      "box-shadow:0 8px 28px rgba(0,0,0,.45);font-size:14px;line-height:1.5;";

    var mark = document.createElement("img");
    mark.src = "/static/brand/mulmit-favicon.svg";
    mark.alt = "";
    mark.width = 34;
    mark.height = 34;
    mark.style.cssText = "flex:none;border-radius:8px;";

    var text = document.createElement("div");
    text.style.cssText = "flex:1;min-width:0;";
    var title = document.createElement("strong");
    title.textContent = t("물밑을 앱처럼", "Mulmit as an app");
    var body = document.createElement("span");
    body.textContent = bodyText;
    text.append(title, document.createElement("br"), body);

    banner.append(mark, text);

    if (actionLabel) {
      var action = document.createElement("button");
      action.type = "button";
      action.textContent = actionLabel;
      action.style.cssText =
        "flex:none;font:inherit;font-weight:600;color:#0a0c0f;background:#42a5ff;" +
        "border:0;border-radius:8px;padding:8px 14px;cursor:pointer;";
      action.addEventListener("click", onAction);
      banner.append(action);
    }

    var close = document.createElement("button");
    close.type = "button";
    close.setAttribute("aria-label", t("닫기", "Close"));
    close.textContent = "✕";
    close.style.cssText =
      "flex:none;font:inherit;color:#9aa7b2;background:none;border:0;padding:4px;cursor:pointer;";
    close.addEventListener("click", snoozeBanner);
    banner.append(close);

    document.body.append(banner);
  }

  var deferredInstall = null;

  window.addEventListener("beforeinstallprompt", function (event) {
    event.preventDefault();
    deferredInstall = event;
    if (!bannerAllowed()) return;
    whenReady(function () {
      window.setTimeout(function () {
        // 2.5초 사이에 상황이 바뀌었을 수 있다 — 설치가 끝났거나 닫았거나.
        if (!deferredInstall || !bannerAllowed()) return;
        showBanner(t("설치하면 전체화면 앱으로 바로 열립니다.", "Install it and it opens straight into a full-screen app."), t("설치", "Install"), function () {
          var prompt = deferredInstall;
          deferredInstall = null;
          if (!prompt) {
            hideBanner();
            return;
          }
          prompt.prompt();
          prompt.userChoice.then(function (choice) {
            if (choice && choice.outcome === "accepted") storageSet(INSTALLED_KEY, "1");
            else storageSet(SNOOZE_KEY, String(Date.now() + SNOOZE_MS));
            hideBanner();
          });
        });
      }, 2500);
    });
  });

  window.addEventListener("appinstalled", function () {
    storageSet(INSTALLED_KEY, "1");
    hideBanner();
  });

  function isInAppBrowser() {
    // 인앱 브라우저(카카오톡·네이버앱·인스타·페북·라인, 일반 WebView)는 홈
    // 화면 설치 경로 자체가 없다 — 안내해 봐야 찾을 수 없는 메뉴를 찾게 한다.
    return /\bwv\b|KAKAOTALK|NAVER\(inapp|Instagram|FBAV|FBAN|Line\//i.test(navigator.userAgent);
  }

  function setupManualInstallHint() {
    // beforeinstallprompt를 아는 브라우저(크롬·삼성인터넷·웨일)는 위의 이벤트
    // 경로가 담당한다. 이벤트가 아예 없는 브라우저 — iOS 전부, 안드로이드
    // 파이어폭스(운영자 실측 2026-08-27: 배너가 영영 안 떴다) — 에는 코드로
    // 프롬프트를 띄울 방법이 없으므로 수동 경로를 안내한다.
    if ("onbeforeinstallprompt" in window) return;
    if (isInAppBrowser() || !bannerAllowed()) return;
    window.setTimeout(function () {
      if (!bannerAllowed()) return;
      showBanner(
        isIos()
          ? t("공유 버튼(↑)을 누르고 '홈 화면에 추가'를 선택하면 앱처럼 열리고 알림도 받을 수 있습니다.",
              "Tap Share (↑) and choose 'Add to Home Screen' — it opens like an app and can receive alerts.")
          : t("브라우저 메뉴(⋮)에서 '홈 화면에 추가' 또는 '설치'를 누르면 앱처럼 쓸 수 있습니다.",
              "Open the browser menu (⋮) and choose 'Add to Home screen' or 'Install' to use it like an app."),
        null,
        null
      );
    }, 2500);
  }

  function whenReady(callback) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", callback);
    } else {
      callback();
    }
  }

  whenReady(setupKimchiToggle);
  whenReady(setupManualInstallHint);
})();
