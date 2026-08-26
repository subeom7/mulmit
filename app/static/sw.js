/* 물밑 서비스 워커 — 껍데기만 다루고, 데이터는 절대 만지지 않는다.
 *
 * 이 파일이 존재하는 이유는 둘이다: PWA 설치 가능 조건, 그리고 (후속 단계의)
 * 웹 푸시 수신처. 오프라인 "앱"을 만들려는 것이 아니다 — 이 사이트의 본질은
 * 실시간 신호라, 낡은 값을 그럴듯하게 그려 주는 캐시가 오프라인 안내문보다
 * 훨씬 나쁘다. 그래서:
 *
 *  - `/api/` 는 가로채지 않는다. respondWith를 부르지 않으면 브라우저 기본
 *    네트워크 경로 그대로다.
 *  - 정적 자산(`?v=`)도 가로채지 않는다. 캐싱은 HTTP 캐시가 이미 한다
 *    (app/main.py STATIC_VERSIONED — 하루 + ETag 자가 치유). 여기에 두 번째
 *    캐시 층을 얹으면 main.py가 기록해 둔 "옛 내용이 새 키로 박히는" 사고를
 *    서비스 워커에서 재현하게 된다.
 *  - 문서 내비게이션이 네트워크에서 실패하면(오프라인) 자기 완결적인
 *    안내 페이지를 보여 준다.
 *  - 웹 푸시를 받아 알림으로 띄우고, 알림 탭이 해당 화면을 연다. 발송은
 *    서버 배치(app/web_push.py)가 하고, 여기는 받은 JSON을 그대로 그린다.
 *
 * CACHE 이름은 캐시의 **형식**이 바뀔 때만 올린다. 배포마다 올릴 필요 없다 —
 * 이 파일의 바이트가 바뀌면 브라우저가 알아서 새 워커를 설치한다. 워커 URL
 * (/sw.js)에는 절대 ?v= 를 붙이지 않는다 — URL이 곧 워커의 정체성이다.
 */
const CACHE = "mulmit-sw-v1";
const OFFLINE_URL = "/static/offline.html";

self.addEventListener("install", (event) => {
  // cache: "reload" — HTTP 캐시를 거치지 않고 서버 판을 받아 둔다.
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.add(new Request(OFFLINE_URL, { cache: "reload" })))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return;
  event.respondWith(
    fetch(event.request).catch(() =>
      caches.match(OFFLINE_URL).then((cached) => cached || Response.error())
    )
  );
});

self.addEventListener("push", (event) => {
  if (!event.data) return;
  let payload;
  try {
    payload = event.data.json();
  } catch {
    return; // 우리 서버는 항상 JSON을 보낸다 — 아닌 것은 우리 것이 아니다
  }
  event.waitUntil(
    self.registration.showNotification(payload.title || "물밑 Mulmit", {
      body: payload.body || "",
      // 같은 tag의 알림은 쌓이지 않고 최신으로 갈린다 — 김프 알림이
      // 밤 사이 석 장 쌓여 있을 이유가 없다.
      tag: payload.tag || "mulmit",
      icon: "/static/brand/favicon-192.png",
      data: { url: payload.url || "/" },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      for (const client of windows) {
        if (new URL(client.url).pathname === new URL(url, self.location.origin).pathname) {
          return client.focus();
        }
      }
      return clients.openWindow(url);
    })
  );
});
