# Mimari Referans — AI Crypto Bot (Real-time / Otomatik Alım-Satım)

> Durum: **V2 hedef mimarisi.** V1 (elle yazılmış CLI pipeline) `src/` altında
> duruyor ve _araştırma / referans_ olarak korunuyor. Çalışan runtime, aşama
> aşama Freqtrade + FreqAI omurgasına taşınıyor. Bkz. `docs/MIGRATION.md`.

---

## 1. Hedef ve prensipler

Amaç: Binance spot üzerinde, ML destekli sinyallerle **7/24 çalışan**, önce
kâğıt (dry-run) sonra testnet sonra gerçek parayla otomatik işlem yapan,
**güvenliği öncelikli** bir sistem.

Pazarlıksız prensipler:

1. **Gerçek emir yetkisi tek yerde.** Yalnızca execution katmanı borsanın
   authenticated key'ini görür. Strateji / feature / dashboard borsaya emir
   göndermez.
2. **Risk katmanı stratejiden bağımsız bir sert geçit.** Strateji ne derse
   desin; max pozisyon, max günlük kayıp, max açık işlem, drawdown kill-switch
   burada uygulanır.
3. **Dry-run → replay → testnet → mainnet(minik) → ölçekle.** Her strateji/model
   değişikliği bu merdivenden geçer. Atlama yok.
4. **Borsa gerçektir.** Açılışta pozisyon/emir/bakiye borsadan çekilir,
   yereldeki durumla mutabakat yapılır; uyuşmazlık loglanır, mutabakat bitmeden
   işlem yapılmaz.
5. **Her şey UTC.** Sunucu NTP senkron. Zaman damgaları tz-aware.
6. **Gözlemlenebilirlik zorunlu.** Yapısal log + metrik + alert olmadan canlı
   para yönetilmez.
7. **API key: sadece trade yetkisi. Withdrawal KAPALI. Borsada IP allow-list.**

---

## 2. Neden Freqtrade + FreqAI (omurga kararı)

Ayrıntılı karar kaydı: `docs/adr/0001-backbone.md`.

Özet:

| İhtiyaç | Freqtrade'in karşılığı |
|---|---|
| Kazara gerçek işlem yapmama | `dry_run: true` varsayılan; mainnet için explicit config + flag zinciri |
| Binance + testnet | Native destek (`exchange.name: binance`, sandbox modu) |
| Kontrol + acil durdurma | Telegram bot (`/stop`, `/forceexit`, `/reload_config`) + FreqUI |
| Reconnect / kısmi dolum / rate-limit / borsa tuhaflıkları | Binlerce kullanıcının canlı koşturduğu, çözülmüş kod |
| Parametre araması | Dahili `backtesting` + `hyperopt` |
| ML pipeline | **FreqAI**: rolling retrain, feature pipeline, XGBoost/LightGBM/CatBoost, tahmin → sinyal |
| State / DB / trade kaydı | SQLite (kişisel ölçekte yeterli) + `trades` tablosu + mutabakat |

Alternatifler ve neden seçilmedi:

- **Kendi event-driven çekirdeğimiz:** execution/OMS'i güvenli yazmak aylar
  alır ve hatası gerçek para kaybettirir. Uzmanlık + zaman gerektirir.
- **NautilusTrader:** production-grade, tick seviyesi, backtest=live parity —
  ama dik öğrenme eğrisi. Mum-bazlı ML sinyali için fazla ağır (YAGNI).
  İleride tick seviyesine / egzotik emirlere ihtiyaç olursa yeniden değerlendir.

---

## 3. Bileşen mimarisi

Freqtrade tek süreç olarak bu akışı yönetir; kavramsal katmanlar şöyle:

```
                    Binance WS/REST (public: fiyat/mum/orderbook)
                                   │
                    ┌──────────────▼───────────────┐
                    │  Data Layer (Freqtrade)       │  mum indirme, cache,
                    │  - exchange abstraction (ccxt)│  gap-fill, timeframe
                    │  - dataprovider               │  agregasyonu
                    └──────────────┬───────────────┘
                                   │ OHLCV dataframe
                    ┌──────────────▼───────────────┐
                    │  Feature / Model Layer         │  strategy.populate_indicators
                    │  - FreqAI feature_engineering_*│  + FreqAI rolling retrain
                    │  - model registry (user_data/models) │  + tahmin sütunu
                    └──────────────┬───────────────┘
                                   │ enter/exit sinyalleri
                    ┌──────────────▼───────────────┐
                    │  Strategy Layer               │  populate_entry_trend /
                    │  - deterministik kural VEYA   │  populate_exit_trend
                    │    FreqAI tahmini eşiği       │  custom_stoploss, roi
                    └──────────────┬───────────────┘
                                   │ aday işlem
                    ┌──────────────▼───────────────┐
                    │  Risk / Protection Layer      │  config: max_open_trades,
                    │  - Freqtrade "protections"    │  stake_amount, tradable_ratio
                    │  - custom: günlük kayıp,      │  + protections plugin'leri
                    │    drawdown kill-switch       │  (StoplossGuard, MaxDrawdown,
                    │                               │   CooldownPeriod, LowProfitPairs)
                    └──────────────┬───────────────┘
                                   │ onaylı emir
                    ┌──────────────▼───────────────┐
                    │  Execution Layer (Freqtrade)  │  ⚠ TEK authenticated key
                    │  - order placement / cancel   │  clientOrderId, kısmi dolum,
                    │  - dry_run | testnet | live   │  retry, reconciliation
                    └──────────────┬───────────────┘
                                   │ fill / trade
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
     ┌────────────────┐  ┌──────────────────┐  ┌────────────────┐
     │ Persistence     │  │ Control Plane     │  │ Observability   │
     │ SQLite: trades, │  │ Telegram bot      │  │ - JSON loglar   │
     │ orders, pairlock│  │ FreqUI (web)      │  │ - /api_server   │
     │ user_data/      │  │ REST API          │  │ - Prometheus*   │
     └────────────────┘  └──────────────────┘  │ - Sentry*       │
                                                └────────────────┘
                          * opsiyonel eklenti (bkz. §7)
```

### Ayrı tutulan: Araştırma / ML eğitim track'i (offline)

Canlı sürecin dışında, elle çalıştırılan:

```
src/  (V1 pipeline — korunuyor)
 ├─ data/         → tarihsel OHLCV indirme (araştırma veri seti)
 ├─ features/     → feature TANIMLARI (Freqtrade stratejisine kopyalanacak kaynak)
 ├─ ml/           → hedef tasarımı, walk-forward deney fikirleri
 └─ backtest/     → V1 motor (Freqtrade backtest'i ile sonuç çapraz-kontrol için referans)

notebooks/        → keşif, feature importance, hedef analizi
```

FreqAI'nin ürettiği modeller `user_data/models/<identifier>/` altında
versiyonlanır; runtime bunları otomatik yükler ve `train_period_days` +
`backtest_period_days` ayarına göre periyodik yeniden eğitir.

---

## 4. Repo yapısı (V2)

```
ai-crypto-bot/
├─ pyproject.toml            # gerçek proje tanımı + tooling (ruff, mypy)
├─ .python-version           # 3.12
├─ docs/
│  ├─ ARCHITECTURE.md        # bu dosya
│  ├─ MIGRATION.md           # aşama aşama geçiş checklist'i
│  └─ adr/                   # mimari karar kayıtları
│     └─ 0001-backbone.md
├─ config/
│  ├─ config.dry.json        # dry-run (varsayılan çalışma modu)
│  ├─ config.testnet.example.json
│  └─ config.live.example.json
├─ user_data/                # Freqtrade çalışma alanı
│  ├─ strategies/
│  │  ├─ AiCryptoRuleStrategy.py   # deterministik EMA/RSI (plumbing doğrulama)
│  │  └─ AiCryptoFreqAIStrategy.py # ML sinyali (FreqAI) — sonraki aşama
│  ├─ freqaimodels/          # özel FreqAI model sınıfları (gerekirse)
│  ├─ models/                # eğitilmiş model artefaktları (gitignore)
│  ├─ data/                  # indirilen mum verisi (gitignore)
│  ├─ backtest_results/      # (gitignore)
│  ├─ logs/                  # (gitignore)
│  └─ notebooks/
├─ src/                      # V1 pipeline — araştırma/referans (korunuyor)
├─ tests/                    # V1 testleri + yeni strateji testleri
└─ scripts/
   ├─ reconcile.py           # borsa ↔ yerel durum mutabakat kontrolü
   └─ kill.sh                # acil: tüm emirleri iptal + pozisyonları düzleştir
```

Ne tracked, ne gitignore:

- **Tracked:** `config/*.example.json`, `config/config.dry.json`,
  `user_data/strategies/`, `user_data/freqaimodels/`, `docs/`, `src/`, `tests/`.
- **Gitignore:** gerçek `config.testnet.json` / `config.live.json` (key içerir),
  `.env`, `user_data/{models,data,logs,backtest_results}`, `*.sqlite`.

---

## 5. Çalışma modları

| Mod | Config | Borsa | Para | Ne zaman |
|---|---|---|---|---|
| **dry-run** | `config.dry.json` (`dry_run: true`) | Binance public (canlı fiyat) | Sanal cüzdan | Varsayılan. Her strateji/model değişikliğinin ilk durağı. Günlerce koştur. |
| **replay/backtest** | `--timerange` ile `backtesting` | Yok (indirilen veri) | — | Parametre / hyperopt. V1 motoruyla çapraz-kontrol. |
| **testnet** | `config.testnet.json` (`dry_run: false`, testnet key) | `testnet.binance.vision` | Sahte testnet bakiyesi | dry-run stabil olduktan sonra. Gerçek OMS yolu (emir/iptal/kısmi dolum/mutabakat) testi. |
| **live (minik)** | `config.live.json` (`dry_run: false`, `stake_amount` çok küçük) | Binance mainnet | Gerçek — minimum | testnet'te 1-2 hafta sorunsuzdan sonra. Tek sembol. |
| **live (ölçekli)** | aynı, artırılmış `stake_amount` / `max_open_trades` | mainnet | Gerçek | Minik canlıda net pozitif davranış + tüm alarmlar çalışıyorsa. |

Mod geçişi = config dosyası değişimi + explicit CLI. Kod değişmez → strateji
davranışı modlar arası özdeş.

---

## 6. Risk / koruma katmanı

Freqtrade "protections" (config `protections` bloğu) + strateji-içi custom:

| Kural | Mekanizma | Varsayılan |
|---|---|---|
| İşlem başına risk | `stake_amount` (sabit USDT) veya `tradable_balance_ratio` | küçük başla |
| Eşzamanlı pozisyon | `max_open_trades` | 3 |
| Stop-loss | strateji `stoploss` + opsiyonel `custom_stoploss` (ATR bazlı) | -0.08 |
| Take-profit | `minimal_roi` | `{"0": 0.15}` |
| Trailing | `trailing_stop` + `trailing_stop_positive(_offset)` | 0.20 / 0.02 |
| Arka arkaya stop | `StoplossGuard` protection | 3 stop / 24h → durakla |
| Toplam drawdown | `MaxDrawdown` protection | %10 → tüm işlemleri durdur |
| Zayıf çift | `LowProfitPairs` protection | X saatte negatifse o çifti kilitle |
| Giriş sonrası bekleme | `CooldownPeriod` protection | çıkıştan sonra N mum |
| Günlük kayıp limiti | **custom** (strateji `bot_loop_start` / `confirm_trade_entry`) | %1.5 → o gün yeni giriş yok |
| Kill-switch | `scripts/kill.sh` + Telegram `/stop` + borsa `cancelAllAfter` (dead-man) | — |

**Dead-man's switch:** bot heartbeat kesilirse borsadaki açık emirler otomatik
iptal olmalı. Binance spot `cancelAllAfter` destekliyor — execution başlangıcında
kur, her loop'ta yenile.

---

## 7. Gözlemlenebilirlik ve alarm

Zorunlu (canlıdan önce):

- **Yapısal log:** Freqtrade `--logfile` + JSON formatter. `user_data/logs/`.
- **Telegram bildirimleri:** her giriş/çıkış, her stop, her hata, reconnect,
  günlük kâr/zarar özeti, protection tetiklenmesi.
- **Heartbeat:** `internals.heartbeat_interval` — log + (opsiyonel) harici
  uptime izleyici (healthchecks.io ping).
- **Reconciliation raporu:** `scripts/reconcile.py` cron ile saatlik → borsa
  pozisyon/bakiye vs. yerel `trades` tablosu; fark varsa Telegram alarm.

Opsiyonel (ölçeklenince):

- **Prometheus + Grafana:** Freqtrade REST API'den `/api/v1/profit`, `/status`
  vb. scrape eden küçük exporter. Latency, açık pozisyon, günlük PnL panosu.
- **Sentry:** exception yakalama.

---

## 8. Deployment

- **Nerede:** Binance'e yakın bölgede küçük VPS (ör. AWS `ap-northeast-1` Tokyo).
  Latency ve API stabilitesi için.
- **Nasıl:** Docker (`freqtradeorg/freqtrade:stable` imajı) + `docker compose`,
  `restart: unless-stopped`. Config + `user_data` volume mount.
- **Süreç sağlığı:** compose restart policy + heartbeat izleme. systemd de olur.
- **Güncelleme:** imaj pinli (`freqtrade:2024.x`), elle bump + dry-run'da
  doğrula, sonra prod.
- **Yedek:** `user_data/tradesv3.sqlite` + config'ler günlük yedek (borsa dışı).
- **Secrets:** `.env` chmod 600, veya `config.live.json` chmod 600 ve repo dışı.
  Docker secret / SOPS+age kişisel ölçekte fazlası.

---

## 9. Test stratejisi

| Katman | Ne |
|---|---|
| Birim | Strateji indikatör/sinyal fonksiyonları (pandas fixture ile). `tests/` |
| Backtest parity | Aynı dönem + parametre için Freqtrade backtest ↔ V1 `src/backtest` sonucu; büyük sapma = bug |
| FreqAI | `--freqaimodel` ile küçük `train_period_days`, no-lookahead kontrolü, feature importance sanity |
| Dry-run smoke | CI'de değil ama: her release öncesi 24-48h dry-run, sıfır exception |
| Testnet | Manuel: emir aç/kapat, kısmi dolum senaryosu, bot restart → reconciliation temiz |

---

## 10. Yol haritası (yüksek seviye)

1. **Aşama 0** — repo hijyeni: git, pyproject, tooling, bu dokümanlar. ✅
2. **Aşama 1** — Freqtrade dry-run: `AiCryptoRuleStrategy` (EMA/RSI) çalışıyor,
   FreqUI + Telegram bağlı. Plumbing doğrulandı.
3. **Aşama 2** — Backtest parity: feature tanımları V1'den taşındı, Freqtrade
   backtest sonucu V1 ile tutarlı. Hyperopt ile parametre araması.
4. **Aşama 3** — FreqAI: `AiCryptoFreqAIStrategy`, XGBoost, rolling retrain,
   tahmin → giriş eşiği. dry-run'da forward-test.
5. **Aşama 4** — Protections + observability + `reconcile.py` + `kill.sh` +
   günlük kayıp custom kuralı.
6. **Aşama 5** — testnet: gerçek OMS yolu, restart/mutabakat testleri.
7. **Aşama 6** — mainnet minik size, tek sembol, tüm alarmlar açık.
8. **Aşama 7** — ölçekle: sembol ekle, `stake_amount` artır, Grafana panosu.

Ayrıntılı, işaretlenebilir liste: `docs/MIGRATION.md`.
