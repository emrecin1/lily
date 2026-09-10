# Geçiş Planı — V1 CLI pipeline → V2 Freqtrade + FreqAI (real-time)

Her aşama bir öncekine dayanır. **Bir aşama "bitti" sayılmaz** çıkış kriterleri
sağlanmadan. Gerçek paraya geçiş yalnızca Aşama 5 tamamlanınca.

Komutlar: `!` ile başlayanları bu oturumda sen çalıştır (çıktı sohbete düşer).

---

## Aşama 0 — Repo hijyeni  ✅ (bu oturumda yapıldı)

- [x] `git init` + baseline commit
- [x] `docs/ARCHITECTURE.md`, `docs/adr/0001-backbone.md`, bu dosya
- [x] Gerçek `pyproject.toml` (deps + ruff + mypy), `.python-version`
- [x] `config/` iskeleti + `.gitignore` güncellemesi
- [x] `user_data/strategies/AiCryptoRuleStrategy.py` (ilk strateji)
- [x] `config/config.dry.json`

**Çıkış kriteri:** repo temiz, `git status` beklendik, dokümanlar yerinde.

---

## Aşama 1 — Freqtrade dry-run çalışıyor

Amaç: borsadan canlı fiyat akıyor, deterministik EMA/RSI stratejisi sanal
cüzdanla işlem açıp kapatıyor, FreqUI + Telegram bağlı. **Model yok** — sadece
plumbing.

- [ ] Ortam: `python -m venv .venv-rt && source .venv-rt/bin/activate`
      (Freqtrade'i V1 ortamından ayrı tut — bağımlılık çakışması olmasın)
- [ ] `! pip install freqtrade` (veya Docker imajı — bkz. aşağıda)
- [ ] `! freqtrade create-userdir --userdir user_data` (varsa atla)
- [ ] `config/config.dry.json` içindeki `pair_whitelist`, `max_open_trades`,
      `dry_run_wallet`, `timeframe` gözden geçir
- [x] `! freqtrade download-data --config config/config.dry.json --timeframe 4h --timerange 20230101-`
      NOT: EMA200 ısınması için test aralığından ~1 yıl önce veri gerekir.
      Freqtrade artımlı indirir; daha eski veri için **`--prepend`** şart:
      `! freqtrade download-data ... --timerange 20230101- --prepend`
- [x] `! freqtrade backtesting --config config/config.dry.json --strategy AiCryptoRuleStrategy --timerange 20240101-20250101 --cache none`
      → ✅ hatasız çalışıyor. Sonuç: 103 işlem, -6.37%, win %27 (V1 ile tutarlı:
      bu basit kural stratejisi kârlı değil — Aşama 2'de hyperopt).
      `--cache none` yoksa Freqtrade önceki sonucu cache'den döndürebilir.
- [ ] `! freqtrade trade --config config/config.dry.json --strategy AiCryptoRuleStrategy`
      → birkaç saat/gün koştur. (Boot smoke-test'i ✅ geçti: dry_run enabled,
      strateji + parametreler doğru yükleniyor, hata/deprecation yok.)
      ÖNCE: `config.dry.json` `api_server` içindeki `DEGISTIR` değerlerini
      gerçek rastgele string'lerle değiştir.
- [ ] FreqUI: `config.dry.json` `api_server` bloğu açık, `http://127.0.0.1:8080`
      erişiliyor (kullanıcı/şifre config'de)
- [ ] Telegram (opsiyonel bu aşamada): bot token + chat id, `/status` çalışıyor

**Çıkış kriteri:** 24 saat dry-run, sıfır exception, en az 1 sanal işlem
açılıp kapanmış, FreqUI'de görülüyor.

### Docker alternatifi (önerilen prod yolu)

```bash
# docker-compose.yml projede; imaj pinli
docker compose run --rm freqtrade download-data --timerange 20240101- --timeframe 4h
docker compose up -d   # dry-run trade
docker compose logs -f
```

---

## Aşama 2 — Backtest parity + parametre araması

Amaç: Freqtrade backtest sonuçları V1 `src/backtest` ile tutarlı; feature
tanımları tek kaynaktan.

- [ ] `src/features/indicators.py`'deki feature listesini strateji
      `populate_indicators`'a taşı (EMA20/50/100/200, RSI, MACD, ATR, ROC,
      returns, volume z-score...). Aynı `ta`/`talib` parametreleri.
- [ ] Aynı sembol + dönem için V1 backtest (`python main.py backtest`) ve
      Freqtrade backtesting sonuçlarını karşılaştır: işlem sayısı, win rate,
      toplam getiri aynı büyüklük mertebesinde olmalı. Büyük sapma → araştır
      (fill modeli, fee, timeframe hizası).
- [ ] `! freqtrade hyperopt --config config/config.dry.json --strategy AiCryptoRuleStrategy --hyperopt-loss SharpeHyperOptLoss --spaces buy sell roi stoploss trailing --epochs 300 --timerange 20230101-20250101`
- [ ] En iyi parametreleri stratejiye sabitle; **out-of-sample** dönemde
      (hyperopt'a girmeyen tarih aralığı) doğrula.

**Çıkış kriteri:** parity dokümante edildi (`docs/parity-notes.md`), hyperopt
parametreleri out-of-sample'da çökmüyor.

---

## Aşama 3 — FreqAI (ML sinyali)

Amaç: `AiCryptoFreqAIStrategy` — XGBoost tahmini, rolling retrain, tahmin eşiği
→ giriş sinyali. dry-run'da forward-test.

- [ ] `config/config.dry.json`'a `freqai` bloğu ekle:
      `train_period_days`, `backtest_period_days`, `identifier`,
      `feature_parameters` (indicator periyotları, `include_timeframes`,
      `label_period_candles`), `data_split_parameters`,
      `model_training_parameters` (XGBoost hiperparametreleri — V1'deki
      `MLConfig` değerleri başlangıç).
- [ ] Strateji `feature_engineering_expand_all` / `feature_engineering_standard`
      / `set_freqai_targets` callback'lerini yaz. Hedef: V1'deki
      `future_return_{h} >= min_return` mantığı (`&get_data_split` yerine
      `label_period_candles`).
- [ ] `--freqaimodel XGBoostClassifier` (veya regressor + eşik).
- [ ] `! freqtrade backtesting --config config/config.dry.json --strategy AiCryptoFreqAIStrategy --freqaimodel XGBoostClassifier --timerange 20240101-20250601`
      → no-lookahead sanity: FreqAI otomatik purged split yapar; yine de
      feature'larda `.shift(-x)` sızıntısı yok mu kontrol et.
- [ ] Feature importance çıktısını incele (`user_data/models/<id>/`).
- [ ] dry-run'da 1-2 hafta forward-test; tahmin dağılımı + gerçekleşen hit-rate
      logla.

**Çıkış kriteri:** FreqAI backtest sızıntısız, dry-run forward-test'te model
mantıklı sıklıkta ve makul isabetle sinyal üretiyor (V1'deki "eşik 0.70'te hiç
sinyal yok" durumu tekrarlanmıyor — `scale_pos_weight` / eşik ayarı yapıldı).

---

## Aşama 4 — Risk katmanı + gözlemlenebilirlik + operasyon araçları

- [ ] `protections` **strateji sınıfında** (`protections` property'si — yeni
      Freqtrade sürümlerinde config'de deprecated): `StoplossGuard`,
      `MaxDrawdown`, `CooldownPeriod`, `LowProfitPairs`. Değerleri
      `ARCHITECTURE.md` §6. (İlk hali `AiCryptoRuleStrategy`'de mevcut —
      gözden geçir/sıkılaştır.)
- [ ] Custom günlük kayıp limiti: strateji `bot_loop_start` +
      `confirm_trade_entry` içinde "bugünkü realize kayıp > %1.5 ise yeni giriş
      yok".
- [ ] `custom_stoploss`: ATR bazlı stop (V1 `risk_manager` mantığı).
- [ ] `scripts/reconcile.py`: borsa pozisyon/bakiye ↔ Freqtrade `trades`
      tablosu; fark → Telegram alarm. Cron saatlik.
- [ ] `scripts/kill.sh`: `freqtrade` REST API `/forceexit all` + `/stop` +
      (canlıda) ccxt ile `cancel_all_orders`.
- [ ] Telegram: tüm giriş/çıkış/stop/hata/protection bildirimleri açık;
      günlük özet.
- [ ] Heartbeat: `internals.heartbeat_interval` + healthchecks.io ping.
- [ ] (Opsiyonel) Prometheus exporter + Grafana panosu.

**Çıkış kriteri:** kill-switch test edildi (dry-run'da tetikle, hepsi kapandı),
reconcile temiz rapor veriyor, protection'lar backtest'te tetikleniyor.

---

## Aşama 5 — Binance testnet

Amaç: gerçek OMS yolu — emir gönder/iptal/kısmi dolum/mutabakat — sahte parayla.

- [ ] Binance **spot testnet** hesabı: https://testnet.binance.vision → API key
      (trade yetkisi, withdrawal yok — testnet'te zaten yok).
- [ ] `config/config.testnet.json` (gitignore'da): `dry_run: false`, testnet
      key/secret, exchange sandbox modu (kurulu Freqtrade sürümünün dokümanına
      göre: `exchange.ccxt_config` veya sandbox flag'i — **doğrula**).
- [ ] `! freqtrade trade --config config/config.testnet.json --strategy <strateji>`
- [ ] Senaryolar:
  - [ ] Normal giriş → çıkış, `trades` tablosu + borsa uyuşuyor
  - [ ] Bot'u işlem açıkken `kill` et, yeniden başlat → reconciliation temiz,
        pozisyon "adopted"
  - [ ] Elle borsadan pozisyon kapat, bot fark ediyor mu
  - [ ] Rate-limit / geçici network hatası → retry, çökme yok
  - [ ] Kısmi dolum (küçük likidite çiftinde limit emir)
- [ ] 1-2 hafta kesintisiz testnet.

**Çıkış kriteri:** yukarıdaki senaryoların hepsi temiz; restart sonrası hiç
"hayalet pozisyon" yok; Telegram alarmları doğru.

---

## Aşama 6 — Mainnet, minik size

- [ ] Binance mainnet API key: **sadece spot trade. Withdrawal KAPALI. IP
      allow-list** (VPS IP'si).
- [ ] `config/config.live.json` (gitignore, chmod 600): `dry_run: false`,
      `stake_amount` = borsa minimumu civarı (ör. 15-20 USDT), `max_open_trades: 1`,
      tek sembol (BTC/USDT).
- [ ] VPS'te Docker compose, `restart: unless-stopped`, heartbeat izleme aktif.
- [ ] İlk hafta: her gün logları + reconcile + Telegram özetini elle kontrol et.
- [ ] `kill.sh` elinin altında, test edilmiş.

**Çıkış kriteri:** 2 hafta canlı, beklenm/dık davranış yok, tüm alarmlar
çalışıyor, sen sisteme güveniyorsun.

---

## Aşama 7 — Ölçekleme

- [ ] Sembol ekle (whitelist), `max_open_trades` artır.
- [ ] `stake_amount` kademeli artır (her artıştan sonra 1 hafta gözlem).
- [ ] Grafana panosu (PnL, drawdown, açık pozisyon, latency).
- [ ] FreqAI retrain sıklığı / model izleme otomasyonu.
- [ ] Periyodik: hyperopt yeniden, model yeniden değerlendirme, parity kontrol.

---

## Geri dönüş (rollback) planı

Her aşamada: `docker compose down` / `freqtrade` süreçini durdur + `kill.sh`.
Config dosyaları git'te (canlı olanlar hariç) → önceki stratejiye/parametreye
`git checkout` + dry-run'da doğrula + tekrar başlat. Gerçek pozisyon varsa önce
`kill.sh` ile düzleştir.
