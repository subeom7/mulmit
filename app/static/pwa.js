/* PWA 부트스트랩 — 지금은 서비스 워커 등록만 한다.
 *
 * 설치 유도 UI(beforeinstallprompt)와 푸시 구독은 후속 단계에서 이 파일에
 * 얹는다 — 페이지마다 인라인으로 흩어 두면 한쪽만 고치는 사고가 난다.
 *
 * register("/sw.js")의 URL에는 ?v= 를 붙이지 않는다. 워커 URL은 브라우저가
 * 워커의 정체성으로 쓰는 키라서, URL이 바뀌면 갱신이 아니라 딴 워커가 된다.
 * 갱신은 브라우저가 /sw.js 바이트를 비교해서 알아서 한다(서버는 no-cache).
 */
(function () {
  if (!("serviceWorker" in navigator)) return;
  window.addEventListener("load", function () {
    navigator.serviceWorker.register("/sw.js").catch(function () {
      // 등록이 실패해도 사이트는 그대로 동작한다. 조용히 넘어간다.
    });
  });
})();
