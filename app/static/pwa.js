/* PWA 부트스트랩 — 서비스 워커 등록과 푸시 구독 토글.
 *
 * 설치 유도 UI(beforeinstallprompt)는 후속 단계에서 이 파일에 얹는다 —
 * 페이지마다 인라인으로 흩어 두면 한쪽만 고치는 사고가 난다.
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
        button.textContent = "🔔 알림 켜짐 · 누르면 해제";
        button.setAttribute("aria-pressed", "true");
      } else if (state === "blocked") {
        button.textContent = "🔕 브라우저에서 알림이 차단됨";
        button.setAttribute("aria-pressed", "false");
      } else {
        var threshold =
          serverConfig && serverConfig.topics && serverConfig.topics[TOPIC]
            ? serverConfig.topics[TOPIC].threshold_percent
            : 3;
        button.textContent = "🔔 ±" + threshold + "% 넘으면 알림 받기";
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

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", setupKimchiToggle);
  } else {
    setupKimchiToggle();
  }
})();
