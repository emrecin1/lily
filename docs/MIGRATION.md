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

Amaç: Freqtrade stratejisi V1 ile aynı feature'ları + aynı sinyal mantığını
üretiyor; feature tanımı tek kaynaktan.

- [x] `src/features/indicators.py` import-güvenli yapıldı (yalnız numpy/pandas/ta).
- [x] `AiCryptoFeatureStrategy`: `add_indicators()`'ı **doğrudan çağırır** —
      25 feature V1 ile birebir (yeniden implementasyon yok).
- [x] `.venv-rt`'ye `ta` + `python-dotenv` kuruldu.
- [x] Parity kontrolü yapıldı ve dokümante edildi: **`docs/parity-notes.md`**.
      - feature değerleri: `max_rel ≤ 1e-12` (özdeş)
      - giriş mantığı: V1 +1 mum kayma ile 23/23 eşleşiyor
      - 1 mum fark = Freqtrade doğru; V1 kural motorunda 1-bar lookahead tespit
        edildi (V1 referans olduğu için düzeltilmedi)
      - `startup_candle_count` 240→400 (EMA200 warmup)
      - parity-doğru strateji: `AiCryptoFeatureStrategy` (talib değil `ta`)
- [x] Regresyon testi: `tests/test_phase2b_feature_parity.py` (determinizm,
      no-lookahead, 25 feature, input mutasyonu yok).
- [x] `! .venv-rt/bin/freqtrade hyperopt ... --epochs 300 --timerange 20230101-20250101`
      (hyperopt bağımlılıkları + `joblib` 1.4.2 pin — bkz. `docs/hyperopt-notes.md`)
- [x] **Out-of-sample doğrulama yapıldı → params OVERFIT.**
      in-sample +19.94% ama 2025-01→ out-of-sample **-11.84%** (default'tan
      daha kötü: -4.99%). Params repoya alınmadı; strateji kod varsayılanlarında.
      Tam analiz: `docs/hyperopt-notes.md`.

**Çıkış kriteri:** parity dokümante edildi ✅ (`docs/parity-notes.md`).
Hyperopt sonucu: ham EMA/RSI kuralının kalıcı edge'i yok, ayarla düzelmiyor →
**Aşama 3'e (FreqAI) geçiş için gerekçe.** ✅ (`docs/hyperopt-notes.md`)

---

## Aşama 3 — FreqAI (ML sinyali)   ← DEVAM EDİYOR

Amaç: `AiCryptoFreqAIStrategy` — XGBoost tahmini, walk-forward retrain, tahmin
eşiği → giriş sinyali. dry-run'da forward-test.

- [x] `config/config.freqai.json` (overlay): `train_period_days=180`,
      `backtest_period_days=7` (haftalık walk-forward), `feature_parameters`,
      `model_training_parameters` (V1 `MLConfig` değerleri).
- [x] `AiCryptoFreqAIStrategy`: `feature_engineering_expand_basic` V1'in
      `add_indicators()`'ini doğrudan çağırır (25 feature, Aşama 2 parity);
      + expand_all + standard = 35 feature. `set_freqai_targets` = V1 hedefi
      (`future_return(4) >= 0.008` → "up"/"down").
- [x] `src/features/indicators.py`: kısa-frame guard (`len<30 → NaN feature'lar`)
      — FreqAI probe'u `ta` ATR/RSI'ı çökertiyordu. 104 test geçer.
- [x] `--freqaimodel XGBoostClassifier` ile backtest çalıştırıldı (4 coin,
      2024-01→2026-09, walk-forward). Hata yok, no-lookahead FreqAI garantisi.
- [x] Tuning yapıldı (8 iterasyon, `docs/freqai-notes.md`): wide stop →
      buy_proba 0.65 → time_stop `custom_exit` → **giriş trend filtresi
      (model "up" VE EMA20>EMA50)**.
- [x] **Backtest: −21.8% → +9.23%** (full 2024-2026), **in-sample +6.5% VE
      OOS +2.8% ikisi de pozitif**, max DD %3.3. Trend filtresi 0 tuned
      parametre → overfit değil.
- [x] Hyperopt denendi → yine overfit (in-sample +15.5% / OOS −5.95%),
      params atıldı. Ders: **yapısal değişiklik > parametre ayarı.**
- [ ] Feature importance incele.
- [ ] **dry-run'da 1-2 hafta forward-test** (bir sonraki iş); tahmin dağılımı +
      gerçekleşen hit-rate logla.
- [ ] Kâr artışı: daha iyi target (regresyon/3-sınıf), çoklu `include_timeframes`,
      pozisyon boyutlandırma, daha çok coin.

**Çıkış kriteri:** pipeline ✅, edge ✅ (OOS'ta da), backtest net pozitif +
OOS-dayanıklı ✅. Kalan: dry-run forward-test'te doğrula, sonra Aşama 4.
Getiri düşük (OOS ~yıllık %2.8) — kâr için feature/target işi sürecek ama
Aşama 4-5 (risk katmanı, testnet) paralel ilerleyebilir.

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
