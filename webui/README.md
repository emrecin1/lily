# webui/ — özel panel (FreqUI'nin yerine geçen BFF)

FreqUI jenerik/tema desteği olmayan sabit bir SPA olduğu için, günlük
kullanılan arayüz olarak yerine bunu koyduk (FreqUI'nin kendisi de artık
sunucuda kurulu değil — `freqtrade install-ui --erase` ile kaldırıldı;
`:8081` sadece REST API olarak kullanılıyor). Freqtrade'in REST/WS API'sine
çoğunlukla **salt-okunur** bağlanır; emir gönderme/iptal/force-exit gibi
trading-kontrol aksiyonları bilinçli olarak **yok** — onlar için Telegram
veya `scripts/kill.sh` kullan.

Tek istisna: `/settings` ve `/profile` (demo bakiyesi) sayfaları, Freqtrade'in
**kendi resmi** `POST /reload_config` ucunu çağırır — config/strateji
dosyalarını diskte güncelledikten sonra botu AYNI SÜREÇTE (PID değişmez,
açık pozisyonlara dokunmaz) yeniden yükletir. Özel/gayrı-resmi bir kontrol
ucu değil; freqtrade'in kendi "Bot-control" API'sinin dokümante edilmiş bir
parçası. Açık pozisyon varsa reload otomatik ERTELENİR (dosyalar yine de
güncellenir), sayfada "Şimdi uygula" ile elle tetiklenebilir. Detaylar için
`webui/reload.py` ve `webui/settings_store.py`.

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
- ✅ Faz 4 — `/trades` (sayfalanmış geçmiş, giriş/çıkış tag chip'leri) +
  `/system` (bot durumu, FreqAI identifier + son eğitim zamanı — `config/
  config.freqai.json` + `user_data/models/<id>/` dizin mtime'larından,
  CPU/RAM, renkli log görüntüleyici).
- ✅ Faz 5 — `/settings` (giriş eşiği, çıkış/zaman-stop/ROI/stop-loss,
  pozisyon büyüklüğü modu, günlük-kayıp limiti) + `/profile` (panel şifresi
  değiştirme, demo/dry-run başlangıç bakiyesi). Kaydet -> dosyalar güncellenir
  -> açık pozisyon yoksa `reload_config` ile bota anında uygulanır.
- ⏳ Faz 6 (opsiyonel) — docker-compose'a ikinci servis.

**Tüm ana fazlar (1-5) tamam.** Panel FreqUI'nin yerini alacak durumda.

## Bilinen kısıtlar

- Günlük-kayıp pili artık `config/config.dry.json > aicrypto.max_daily_loss_pct`'i
  okur — `/settings` sayfası ve `AiCryptoFreqAIStrategy.max_daily_loss_pct`
  AYNI dosyayı okuduğu için elle senkron tutma ihtiyacı kalmadı (eski
  `WEBUI_DAILY_LOSS_PCT` env değişkeni artık kullanılmıyor).
- `/settings` ve `/profile` dışında hâlâ salt-okunur: emir gönderme/iptal/
  force-exit/start-stop yok.
- Demo bakiyesini değiştirmek sadece YENİ başlangıç noktasını değiştirir,
  geçmiş simüle işlemlerin kâr/zararını silmez. Tam sıfırlama (işlem
  geçmişini de silme) panelden bilinçli olarak sunulmuyor — bot çalışırken
  aynı SQLite dosyasına aktif bağlantı varken güvenle yapılamaz; gerekirse
  botu durdurup elle yapılmalı.
- **Telegram** (`/profile` sayfası): token/chat_id, git'te takip edilmeyen
  `config/config.telegram.local.json` dosyasına yazılır (`config/*.local.json`
  kalıbıyla `.gitignore`'da zaten kapsanır — `config.dry.json` git'te takip
  edildiği için secret oraya YAZILMAZ). Bu dosyanın Freqtrade tarafından
  okunması için `freqtrade trade` komutuna ayrı bir `-c` katmanı olarak
  eklenmiş olması gerekir:
  `-c config/config.dry.json -c config/config.freqai.json -c config/config.telegram.local.json`.
  Bu katman bir kez eklendikten sonra `/profile`'dan yapılan değişiklikler
  normal `reload_config` akışıyla (PID değişmeden) uygulanır — AMA botu bu
  `-c` bayrağı OLMADAN yeniden başlatırsan (ör. eski bir komutu/scripti
  kullanarak) Telegram config'i sessizce devre dışı kalır. Kalıcı bir
  başlatma scripti yok; botu yeniden başlatırken bu üçüncü `-c` argümanını
  unutma.
