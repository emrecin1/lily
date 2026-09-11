# webui/ — özel panel (FreqUI'nin yerine geçen BFF)

FreqUI jenerik/tema desteği olmayan sabit bir SPA olduğu için, günlük
kullanılan arayüz olarak yerine bunu koyduk. Freqtrade'in REST/WS API'sine
(`:8081`) salt-okunur bağlanır; kontrol aksiyonları (start/stop/forceexit)
bilinçli olarak **yok** — onlar için FreqUI, Telegram veya `scripts/kill.sh`
kullan. Detaylı tasarım kararları için proje geçmişindeki plan dosyasına ya
da `docs/ARCHITECTURE.md`'ye bak.

## Kurulum

```bash
# .venv (V1 ortamı) zaten fastapi/uvicorn/httpx icerir; eksikleri ekle:
.venv/bin/pip install -e ".[webui]"
```

`.env`'e ekle (`.env.example`'a bak):

```
DASHBOARD_PASSWORD=<rastgele-guclu-sifre>
DASHBOARD_SESSION_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
FREQTRADE_CONFIG_PATH=config/config.dry.json
```

Freqtrade Basic Auth bilgisi + `ws_token` **buradan değil**, doğrudan
`FREQTRADE_CONFIG_PATH`'teki `api_server` bloğundan okunur — tek doğruluk
kaynağı, testnet/live'a geçince sadece bu env değişir.

## Çalıştırma

Freqtrade zaten çalışıyor olmalı (`:8081`, `api_server.enabled: true`):

```bash
.venv/bin/uvicorn webui.app:app --host 127.0.0.1 --port 8082
```

`http://127.0.0.1:8082` → `DASHBOARD_PASSWORD` ile giriş.

## Durum (fazlar)

- ✅ Faz 1 — BFF iskeleti, login, `/overview` (bakiye, bugün/hafta/ay PnL,
  açık işlem kartları, günlük-kayıp pili, bot-unreachable banner).
- ✅ Faz 2 — `/pairs/{pair}` grafik sayfası: mum + EMA20/EMA50 + trade
  işaretleri (`/pair_candles` + `/trades` + `/status`) + FreqAI P(up)
  alt-paneli (lightweight-charts, CDN) + "model — neden bu durum" kartları
  (do_predict, P(up), trend, son mum). Henüz canlı değil, sayfa yenileme ile.
- ✅ Faz 3 — canlı güncelleme: `webui/ws_bridge.py` Freqtrade'in
  `/api/v1/message/ws`'ine bağlanır (reconnect + exponential backoff),
  olayları `/events` (SSE) ile tarayıcıya dağıtır. `/overview` açık-işlem
  ve PnL kartlarını, `/pairs/{pair}` grafiği ilgili olaylarda (trade
  giriş/çıkış, yeni mum) sayfa yenilemeden tazeler (tam veri REST'ten
  yeniden çekilir — artımsal update değil, 4h mumda gereksiz). Topbar'da
  yeşil nokta = canlı akış bağlı.
- ⏳ Faz 4 — `/trades`, `/system` sayfaları.
- ⏳ Faz 5 (opsiyonel) — docker-compose'a ikinci servis.

## Bilinen kısıtlar

- Günlük-kayıp pili, `AiCryptoFreqAIStrategy.max_daily_loss_pct`'i
  `WEBUI_DAILY_LOSS_PCT` env değişkeninde **elle senkron** tutar (Freqtrade'in
  bunu veren bir endpoint'i yok). Strateji sabiti değişirse burayı da güncelle.
- Salt-okunur: emir gönderme/iptal/başlatma-durdurma yok.
