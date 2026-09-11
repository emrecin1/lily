/* /pairs/{pair} — lightweight-charts (CDN) ile mum + EMA20/EMA50 + trade
   isaretleri + FreqAI P(up) alt paneli. Henuz canli degil (Faz 3'te SSE
   eklenecek); JSON tek seferde #chart-data script etiketinden okunur. */
(function () {
  const dataEl = document.getElementById("chart-data");
  const container = document.getElementById("chart");
  if (!dataEl || !container || !window.LightweightCharts) return;

  const data = JSON.parse(dataEl.textContent || "{}");

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
    autoSize: true,
  });

  const candleSeries = chart.addCandlestickSeries({
    upColor: "#2ecc71", downColor: "#e5484d",
    borderUpColor: "#2ecc71", borderDownColor: "#e5484d",
    wickUpColor: "#2ecc71", wickDownColor: "#e5484d",
    priceScaleId: "right",
  });
  candleSeries.priceScale().applyOptions({ scaleMargins: { top: 0.05, bottom: 0.3 } });
  candleSeries.setData(data.candles || []);

  if (data.markers && data.markers.length) {
    candleSeries.setMarkers(data.markers);
  }

  const ema20Series = chart.addLineSeries({
    color: "#f5a623", lineWidth: 1, priceScaleId: "right", priceLineVisible: false, lastValueVisible: false,
  });
  ema20Series.setData(data.ema20 || []);

  const ema50Series = chart.addLineSeries({
    color: "#9aa3ae", lineWidth: 1, priceScaleId: "right", priceLineVisible: false, lastValueVisible: false,
  });
  ema50Series.setData(data.ema50 || []);

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
  probSeries.setData(data.prob || []);

  chart.timeScale().fitContent();

  // ---- Faz 3: canli guncelleme --------------------------------------
  // Ayni pariteyle ilgili bir SSE olayi gelince /pairs/<pair>/data.json'i
  // yeniden cek ve tum serileri tazele. Artimsal .update() yerine tam
  // setData(): 4h mumda gozle fark edilmez, cok daha az hata payi.
  const pair = container.dataset.pair;
  const dataUrl = container.dataset.url;
  if (pair && dataUrl) {
    document.addEventListener("webui:event", function (e) {
      const ev = e.detail || {};
      const relevant = ["new_candle", "entry", "entry_fill", "entry_cancel", "exit", "exit_fill", "exit_cancel"];
      if (relevant.indexOf(ev.type) === -1) return;
      if (ev.pair && ev.pair !== pair) return; // baska pariteyle ilgiliyse atla
      fetch(dataUrl)
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (fresh) {
          if (!fresh || fresh.error) return;
          candleSeries.setData(fresh.candles || []);
          candleSeries.setMarkers(fresh.markers || []);
          ema20Series.setData(fresh.ema20 || []);
          ema50Series.setData(fresh.ema50 || []);
          probSeries.setData(fresh.prob || []);
        })
        .catch(function () {});
    });
  }
})();
