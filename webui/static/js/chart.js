/* /pairs/{pair} — lightweight-charts ile mum + EMA20/EMA50 + trade
   isaretleri + FreqAI P(up) alt paneli. Sol parite listesinden tiklama TAM
   SAYFA YENILEMESI yapmaz — /pairs/<pair>/data.json'i fetch ile cekip ayni
   chart nesnesini setData() ile tazeler (JS/kutuphane yeniden yuklenmez,
   parite degistirmek aninda olur). Faz 3 SSE canli-guncelleme de ayni
   loadPair() fonksiyonunu kullanir. */
(function () {
  const dataEl = document.getElementById("chart-data");
  const container = document.getElementById("chart");
  if (!dataEl || !container || !window.LightweightCharts) return;

  const initial = JSON.parse(dataEl.textContent || "{}");
  let currentPair = container.dataset.pair;

  const chart = LightweightCharts.createChart(container, {
    layout: {
      background: { color: "#12151a" },
      textColor: "#9aa3ae",
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    },
    grid: {
      vertLines: { color: "#1e232b" },
      horzLines: { color: "#1e232b" },
    },
    rightPriceScale: { borderColor: "#1e232b" },
    timeScale: { borderColor: "#1e232b", timeVisible: true, secondsVisible: false },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    localization: { locale: "tr-TR" },
    autoSize: true,
  });

  const candleSeries = chart.addCandlestickSeries({
    upColor: "#2ecc71", downColor: "#e5484d",
    borderUpColor: "#2ecc71", borderDownColor: "#e5484d",
    wickUpColor: "#2ecc71", wickDownColor: "#e5484d",
    priceScaleId: "right",
  });
  candleSeries.priceScale().applyOptions({ scaleMargins: { top: 0.05, bottom: 0.3 } });

  const ema20Series = chart.addLineSeries({
    color: "#f5a623", lineWidth: 1, priceScaleId: "right", priceLineVisible: false, lastValueVisible: false,
  });
  const ema50Series = chart.addLineSeries({
    color: "#9aa3ae", lineWidth: 1, priceScaleId: "right", priceLineVisible: false, lastValueVisible: false,
  });
  const probSeries = chart.addAreaSeries({
    priceScaleId: "prob",
    topColor: "rgba(46, 204, 113, 0.35)",
    bottomColor: "rgba(46, 204, 113, 0.02)",
    lineColor: "#2ecc71",
    lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: true,
  });
  chart.priceScale("prob").applyOptions({
    scaleMargins: { top: 0.75, bottom: 0 },
    borderVisible: false,
  });

  function applySeries(d) {
    candleSeries.setData(d.candles || []);
    candleSeries.setMarkers(d.markers || []);
    ema20Series.setData(d.ema20 || []);
    ema50Series.setData(d.ema50 || []);
    probSeries.setData(d.prob || []);
  }

  function updateStatCards(latest) {
    const doPredictEl = document.getElementById("stat-do-predict");
    const upProbaEl = document.getElementById("stat-up-proba");
    const trendEl = document.getElementById("stat-trend");
    const lastCandleEl = document.getElementById("stat-last-candle");
    if (!doPredictEl) return; // hata sayfasindaysa (error) kartlar yok

    const accepted = latest && latest.do_predict === 1;
    doPredictEl.textContent = latest ? (accepted ? "EVET" : "HAYIR") : "—";
    doPredictEl.classList.toggle("pos", !!accepted);
    doPredictEl.classList.toggle("neg", !!latest && !accepted);

    upProbaEl.textContent = latest && latest.up != null ? (latest.up * 100).toFixed(1) + "%" : "—";

    const trendUp = !!(latest && latest.trend_up);
    trendEl.textContent = latest ? (trendUp ? "YUKARI" : "AŞAĞI") : "—";
    trendEl.classList.toggle("pos", !!latest && trendUp);
    trendEl.classList.toggle("neg", !!latest && !trendUp);

    lastCandleEl.textContent = (latest && latest.period_start && latest.period_end)
      ? latest.period_start + "–" + latest.period_end
      : "—";
  }

  function setActiveInList(pair) {
    document.querySelectorAll(".pair-list a").forEach(function (a) {
      a.classList.toggle("active", a.dataset.pair === pair);
    });
  }

  function loadPair(pair, opts) {
    opts = opts || {};
    return fetch("/pairs/" + encodeURIComponent(pair) + "/data.json")
      .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status)); })
      .then(function (fresh) {
        if (fresh.error) return Promise.reject(new Error(fresh.error));
        applySeries(fresh);
        chart.timeScale().fitContent();
        updateStatCards(fresh.latest);
        currentPair = pair;
        container.dataset.pair = pair;
        container.dataset.url = "/pairs/" + encodeURIComponent(pair) + "/data.json";
        const titleEl = document.getElementById("page-pair-name");
        if (titleEl) titleEl.textContent = pair;
        document.title = pair + " — Lily";
        setActiveInList(pair);
        if (!opts.skipHistory) {
          history.pushState({ pair: pair }, "", "/pairs/" + pair);
        }
      })
      .catch(function (err) {
        console.warn("Parite yüklenemedi:", pair, err);
      });
  }

  applySeries(initial);
  chart.timeScale().fitContent();
  updateStatCards(initial.latest);

  // ---- sol listeden tiklama: tam sayfa yenilemesi YOK ------------------
  document.querySelectorAll(".pair-list a").forEach(function (a) {
    a.addEventListener("click", function (e) {
      const p = a.dataset.pair;
      if (!p) return;
      e.preventDefault();
      if (p === currentPair) return;
      loadPair(p);
    });
  });

  // ---- geri/ileri tusu (pushState ile eklenen gecmis) -------------------
  window.addEventListener("popstate", function (e) {
    const p = (e.state && e.state.pair) || decodeURIComponent(
      location.pathname.replace(/^\/pairs\//, "")
    );
    if (p && p !== currentPair) loadPair(p, { skipHistory: true });
  });

  // ---- arama kutusu: sadece istemci tarafinda filtre --------------------
  const search = document.getElementById("pair-search");
  if (search) {
    search.addEventListener("input", function () {
      const q = search.value.trim().toUpperCase();
      document.querySelectorAll(".pair-list li").forEach(function (li) {
        const p = li.dataset.pair || "";
        li.hidden = q.length > 0 && p.toUpperCase().indexOf(q) === -1;
      });
    });
  }

  // ---- Faz 3: canli guncelleme (SSE) -------------------------------
  // Ayni pariteyle ilgili bir olay gelince mevcut pariteyi yeniden cek.
  document.addEventListener("webui:event", function (e) {
    const ev = e.detail || {};
    const relevant = ["new_candle", "entry", "entry_fill", "entry_cancel", "exit", "exit_fill", "exit_cancel"];
    if (relevant.indexOf(ev.type) === -1) return;
    if (ev.pair && ev.pair !== currentPair) return; // baska pariteyle ilgiliyse atla
    loadPair(currentPair, { skipHistory: true });
  });
})();
