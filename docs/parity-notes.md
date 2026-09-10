# Parity Notları — V1 pipeline ↔ Freqtrade (Aşama 2)

Amaç: Freqtrade stratejisinin V1 ile **aynı feature'ları** ve **aynı sinyal
mantığını** ürettiğini kanıtlamak; farkları tek tek açıklamak.

Kontrol scriptleri:
- `.venv-rt/bin/python scripts/parity_check.py` — indikatör / OHLCV numerik parity
- `.venv-rt/bin/python scripts/parity_backtest.py` — işlem zamanlaması parity

Veri: Binance BTC/USDT 4h, Freqtrade feather (`user_data/data/binance/BTC_USDT-4h.feather`).
V1 referansı: `data/processed/features_rules_BTC_USDT.csv`.

---

## 1. Feature kodu parity — TAM

`AiCryptoFeatureStrategy.populate_indicators()` V1'in
`src/features/indicators.add_indicators()` fonksiyonunu **doğrudan çağırır**
(yeniden implementasyon yok). Bunu mümkün kılmak için:

- `src/features/indicators.py` import-güvenli hale getirildi: artık yalnızca
  `numpy` / `pandas` / `ta`'ya bağlı (`src.config` / `src.logging_config`
  bağımlılığı kaldırıldı; `logger` doğrudan `logging.getLogger(...)`).
- `.venv-rt`'ye `ta==0.11` ve `python-dotenv` kuruldu; strateji `sys.path`'e
  repo kökünü ekleyip `from src.features.indicators import add_indicators` yapar.

**Determinizm kanıtı** (`parity_check.py` bölüm A):
aynı OHLCV girdisi + aynı fonksiyon → 25 feature'ın tümü V1'in kayıtlı CSV'si
ile `max_rel ≤ 1e-12` (kayan nokta gürültüsü). Yani strateji V1 feature'larını
**birebir** üretiyor.

---

## 2. İndikatör warmup / path-dependence — bilinen, sınırlı

`ta` kütüphanesinin EMA/RSI/MACD/ATR değerleri serinin **nereden başladığına**
bağlıdır (EMA seed etkisi). V1 CSV'si 2021'den, Freqtrade feather'ı 2023'ten
başlıyor. Aynı timestamp'lerde karşılaştırınca (`parity_check.py` bölüm B):

| Feather başından itibaren | EMA20/50, RSI, ATR, MACD | EMA200 |
|---|---|---|
| ilk ~250 mum | %1–%100 sapma (seed bölgesi) | ~%0.3 |
| 250–750 mum | `1e-7` – `1e-14` (≈ özdeş) | ~%0.16 |
| 750+ mum | `1e-16` (bit-özdeş) | ~`8e-6` (%0.0008) |

**Sonuç:** yeterli warmup verilirse fark ihmal edilebilir.
`startup_candle_count` her iki stratejide **240 → 400**'e çıkarıldı (EMA200 için;
EMA20/50/RSI zaten ~250 mumda yakınsıyor). Freqtrade backtest/canlıda bu kadar
öncesini otomatik yükler (veri 2023'ten mevcut).

> FreqAI (Aşama 3) feature setinde EMA200 var — orada `startup_candle_count`'u
> 600'e çıkarmayı değerlendir, ya da EMA200'ü feature setinden çıkar.

---

## 3. talib ≠ ta — stratejide `ta` kullan

`AiCryptoRuleStrategy` `talib.abstract` kullanıyor (Freqtrade konvansiyonu).
`parity_check.py` bölüm 3: talib ve `ta` EMA/RSI **farklı seed yöntemi** kullanır
→ EMA50 `max_rel ~1.7e-3`, RSI `~0.18` sapar (özellikle ilk yüz mumda).

- **Parity için doğru strateji: `AiCryptoFeatureStrategy`** (`ta`, V1 ile özdeş).
- `AiCryptoRuleStrategy` yalnızca Aşama 1 plumbing testi içindi; Aşama 2+ için
  `AiCryptoFeatureStrategy` esas alınır. (İleride `AiCryptoRuleStrategy`
  emekliye ayrılabilir ya da o da `ta`'ya çevrilebilir.)

---

## 4. OHLCV kaynağı — bit-özdeş

Freqtrade `download-data` (ccxt) ile V1 downloader (ccxt) çıktısı:
8052 mumdan **8051'i tam aynı** (open/high/low/close/volume kuruşuna kadar).
Tek fark: V1 CSV'sinin **son satırı** (`2026-09-03 20:00`) — CSV üretilirken
**henüz kapanmamış mum**. Gerçek fark değil.

---

## 5. İşlem zamanlaması parity — TAM (1 mum kaydırma ile)

`scripts/parity_backtest.py`: V1 `src/rules/engine.run_coin()` ↔ Freqtrade
`AiCryptoFeatureStrategy` backtest, BTC/USDT, 2024 tam yıl.

| | İşlem sayısı |
|---|---|
| V1 kural motoru | 25 |
| Freqtrade | 23 |

Ham eşleşen giriş mumu: **0**. Ama V1 girişleri **+1 mum (4h) kaydırılınca:
23/23 Freqtrade girişi birebir eşleşiyor.** Çıkış mumu da 20/23'te eşleşiyor.

### Neden 1 mum fark? → Freqtrade DOĞRU, V1'de 1-bar lookahead

- **V1 `run_coin`**: mum N'in kapanışıyla hesaplanan sinyalle **aynı mum N'in
  açılışında** pozisyona giriyor (`price = row["open"]`). Yani N'in close'unu
  kullanıp N'in open'ında işlem yapıyor → **hafif lookahead**.
- **Freqtrade**: mum N'in kapanışındaki sinyalle **N+1'in açılışında** giriyor.
  Lookahead yok. Doğru davranış.

→ V1'in kural demo motorunda (`src/rules/engine.py`) 1-bar lookahead var.
V1 artık yalnızca referans olduğu için düzeltilmiyor, ama **V1 kural demo
sonuçları bu yüzden iyimser** — kayda geçti.

### Açıklanan küçük farklar

| Fark | Sebep |
|---|---|
| V1'de 2 fazla giriş (`2024-01-13 00:00`, `2024-12-20 00:00`) | Freqtrade `CooldownPeriod` protection (çıkıştan sonra 2 mum yeni giriş yok); V1'de böyle bir kısıt yok |
| Çıkış nedeni: V1 `stop_loss`×4, Freqtrade `roi`×1 + `stoploss`×0 | 1 mum giriş kayması → giriş fiyatı farklı → -%8 stop seviyesi farklı mumda tetikleniyor; ayrıca +%15 ROI bir işlemde önce doluyor |
| Absolut PnL karşılaştırılmadı | Pozisyon boyutu (V1 `alloc %25` vs FT `stake_amount=1000`), fill fiyatı, fee muhasebesi iki motorda farklı — parity kapsamı dışı |

---

## Sonuç

| Kontrol | Durum |
|---|---|
| Feature değerleri V1 ile özdeş | ✅ `max_rel ≤ 1e-12` |
| No-lookahead (feature'lar geçmişe bağlı) | ✅ (bkz. `tests/test_phase2b_feature_parity.py`) |
| Sinyal / giriş mantığı V1 ile özdeş | ✅ +1 mum kayma ile 23/23 |
| OHLCV kaynağı tutarlı | ✅ 8051/8052 bit-özdeş |
| V1 kural motorunda lookahead | ⚠️ tespit edildi, V1 referans olduğu için düzeltilmedi |
| Parity-doğru strateji | `AiCryptoFeatureStrategy` (talib değil `ta`) |

Aşama 2 sonraki iş: hyperopt (`docs/MIGRATION.md` Aşama 2 son madde).
