/* Genel SSE dinleyici — her sayfada yuklu. /events'ten gelen her olayi
   "webui:event" custom DOM event'i olarak yayinlar; sayfaya ozel script'ler
   (overview.html, pair_chart.html) buna abone olup kendi parcalarini
   yeniler. Baglanti durumunu topbar'daki nokta ile gosterir. */
(function () {
  if (!window.EventSource) return;

  const dot = document.querySelector(".live-dot");
  const es = new EventSource("/events");

  es.onopen = function () {
    if (dot) { dot.classList.add("on"); dot.title = "Canlı akış bağlı"; }
  };
  es.onerror = function () {
    if (dot) { dot.classList.remove("on"); dot.title = "Canlı akış kopuk — yeniden bağlanılıyor"; }
  };
  es.onmessage = function (e) {
    let ev;
    try { ev = JSON.parse(e.data); } catch (_) { return; }
    document.dispatchEvent(new CustomEvent("webui:event", { detail: ev }));
  };
})();
