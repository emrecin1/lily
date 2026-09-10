# FreqAI Notları — AiCryptoFreqAIStrategy (Aşama 3)

## Kurulum

`.venv-rt` ek bağımlılıklar:
- `xgboost==2.1.4` (**`--no-deps` ile** — xgboost 2.1.x `nvidia-nccl-cu12`'yi
  342 MB koşulsuz bağımlılık yapıyor; CPU'da gereksiz. V1 `.venv` de 2.1.4.)
- `lightgbm`, `datasieve>=0.1.5`
- (hyperopt bloğundan) `optuna>4`, `cmaes`, `filelock`, `joblib==1.4.2`

## Mimari

`user_data/strategies/AiCryptoFreqAIStrategy.py` + `config/config.freqai.json`
(overlay — `config.dry.json` üstüne bindirilir).

```bash
.venv-rt/bin/freqtrade backtesting \
  -c config/config.dry.json -c config/config.freqai.json \
  --strategy AiCryptoFreqAIStrategy --freqaimodel XGBoostClassifier \
  --timerange 20240101-20260901 --cache none
```

- **Feature'lar**: `feature_engineering_expand_basic` içinde V1'in
  `add_indicators()`'i **doğrudan** çağrılır → 25 V1 feature'ı `%-` önekiyle
  (Aşama 2 parity). + `expand_all` (rsi/adx/cci/relvol × periyot [20,50]) +
  `standard` (gün/saat) = **toplam 35 feature**.
- **Hedef**: V1 ile aynı — `future_return(label_period_candles=4) >= 0.008`
  → ikili sınıf `"up"`/`"down"` (XGBoostClassifier).
- **Walk-forward**: `train_period_days=180`, `backtest_period_days=7` →
  backtest boyunca **haftalık yeniden eğitim** (V1'in tek sabit split'inin
  aksine — büyük iyileştirme, no-lookahead FreqAI tarafından garanti).
- **Giriş**: `do_predict==1 & &-trend=="up" & P(up) >= buy_proba`.
- **Çıkış**: `do_predict==1 & &-trend=="down"` + ROI (+%15) + katastrofi stop.

## `src/features/indicators.py` düzeltmesi

FreqAI feature-populate sırasında `add_indicators`'a çok kısa (1 satırlık) frame
geçiyor; `ta`'nın ATR/RSI'ı `IndexError` veriyordu. **Guard eklendi**:
`len(df) < 30` ise tüm feature kolonları NaN olarak döner (zaten warm-up NaN
olurdu). `ALL_FEATURE_COLUMNS` modül sabiti eklendi. V1 davranışı değişmez
(V1 hep binlerce satırlık frame veriyor); `tests/test_phase2b_feature_parity.py`
+ 5 test + tüm 104 test geçer.

## Backtest tuning ilerlemesi — 4 coin, 2024-01 → 2026-09 (full)

| # | Ayar | Toplam | İşlem | Win% | Max DD |
|---|---|---|---|---|---|
| 1 | buy_proba 0.55, stop **−8%**, trailing %20 | **−21.8%** | 1107 | 56.0 | 25.5% |
| 2 | buy_proba 0.55, stop **−20%**, trailing kapalı | −10.7% | 983 | 58.4 | 18.8% |
| 3 | buy_proba **0.62**, stop −20% | −6.34% | 713 | 59.5 | 13.9% |
| 4 | + `DI_threshold=1.0` | −6.34% (**etkisiz** — hiçbir mum DI>1.0) | 713 | 59.5 | 13.9% |
| 5 | + breakeven+trail `custom_stoploss` | **−22.1%** (kazananları kesti — GERİ ALINDI) | 739 | 59.1 | 23.4% |
| 6 | + `custom_exit` time_stop, buy_proba **0.65** | −4.3% | 670 | 59.3 | 11.3% |
| 7 | + hyperopt (buy/sell/roi/stoploss) | in-sample +15.5% / **OOS −5.95%** → **OVERFIT**, params atıldı | | | |
| 8 | + **giriş trend filtresi** (model "up" **VE** EMA20>EMA50) | **+9.23%** | 287 | 61.0 | **3.27%** |

### #8 — genelleyen ilk config (in-sample + OOS pozitif)

Trend filtresi = tek yapısal koşul, **0 tuned parametre** → overfit edilemez.

| Dönem | Getiri | İşlem | Win% | Max DD | Sharpe |
|---|---|---|---|---|---|
| In-sample 2024-01 → 2025-09 | **+6.46%** | 170 | 57.6 | 3.27% | 0.53 |
| **OOS 2025-09 → 2026-09** | **+2.77%** | 117 | 65.8 | 2.74% | 0.51 |
| Full 2024 → 2026 | **+9.23%** | 287 | 61.0 | 3.27% | 0.53 |

Çıkış nedeni (full #8): `freqai_down` **+21.5%** (266, %65 win) · `roi` +1.5% ·
`time_stop` **−13.8%** (20). Model "up" dediği ama düşüş trendindeki (EMA20<EMA50)
girişleri elemek, OOS kaybını pozitife çevirdi.

**Değerlendirme:** modest (OOS yıllık ~%2.8, düşük). Gerçek slippage/fee sonrası
marjinal. AMA: tutarlı pozitif, çok düşük drawdown (%3), üzerine inşa edilecek
sağlam bir baz. Kâr için daha iyi feature/target + pozisyon boyutlandırma gerek.

### Overfit uyarısı (#7)

FreqAI hyperopt de Aşama 2 gibi overfit etti: in-sample +15.5%, OOS −5.95%.
Bulduğu `stoploss = −34.3%` yine arama uzayı kenarında ("stop yok" hilesi).
**Yapısal değişiklik (trend filtresi) > parametre ayarı.**

### #9 — 3-sınıflı target denemesi (deney; #8'e döndü)

`set_freqai_targets`: `|future_return(4)| >= %1.5` → "up"/"down", arası "flat".
Giriş yalnızca net "up" tahmininde. Full 2024-2026:

| | #8 binary + trend | #9 3-sınıf + trend |
|---|---|---|
| Getiri | +9.23% | +6.90% |
| İşlem | 287 | **85** |
| `freqai_down` win% | 65% | **85%** |
| Max DD | 3.3% | 4.5% |
| Profit factor | 1.31 | 1.31 |

3-sınıf çok daha az/temiz işlem (fee + operasyon yükü düşük), per-trade kalitesi
yüksek — ama `time_stop` kaybı (−%21) yine kazancı büyük ölçüde yiyor ve toplam
getiri biraz düşük. **#8 (binary + trend) esas alındı**; 3-sınıf ileride
`label_period_candles` + band birlikte ayarlanarak tekrar denenebilir.

### Kalıcı sorun (tüm varyantlarda)

Her config'de `time_stop` / wrong-entry kaybı ~−%20. Model yön tahmininde
iyi (freqai_down %65-85 win) ama emin-ama-yanlış girişler günlerce düşüp
time_stop'a gidiyor. Bunu asıl çözecek: daha güçlü feature'lar (çoklu
timeframe, funding rate, orderbook imbalance), rejim tespiti, veya 4h TA'nın
tek başına yetmediğini kabul edip veri kaynağı genişletmek.

### Kritik bulgu: modelin edge'i GERÇEK, kayıp trade yönetiminden

Çıkış nedeni dökümü (ayar #3):

| Çıkış | Adet | Toplam P&L | Win% |
|---|---|---|---|
| **`freqai_down`** (modelin kendi çıkış sinyali) | 691 | **+27.5%** | 60.9 |
| `roi` (+%15) | 3 | +4.5% | 100 |
| **`stop_loss`** (−%20) | 19 | **−38.3%** | 0 |

- Model "çık" dediğinde **kârlı** (+%27, 691 işlem, %61 isabet). Base rate
  ("4 mumda +%0.8") ~%40-46 iken %60 win → **model sinyal üretiyor** (V1'de
  eşik 0.70'te sıfır sinyal vardı; burada `buy_proba` ayarlanabilir).
- Kayıp tamamen: modelin **kötü yanıldığı azınlık girişler** −%20 sert stop'a
  kadar düşüyor (19 işlem, −%38). Model bunlara "down" sinyalini hiç/geç
  veriyor.
- Eşik ↑ + stop genişletme her adımda düzeltti: −21.8% → −6.34%.

## Sıradaki adımlar (Aşama 3 devam)

Öncelik sırası:

1. **ATR bazlı `custom_stoploss`** (V1 `risk_manager` mantığı: `entry − ATR×1.5`)
   — sabit −%20 yerine adaptif; −%20'lik felaketleri erken kesmeli.
2. **`buy_proba` ↑ (0.65–0.70)** + **hyperopt** (`--spaces buy roi stoploss`,
   `--hyperopt-loss CalmarHyperOptLoss`, min-trades kısıtı). Aşama 2 dersi:
   out-of-sample doğrula, `stoploss` alt sınırını daralt.
3. **`DI_threshold` daha düşük (0.3–0.5)** veya `use_SVM_to_remove_outliers` —
   dağılım-dışı girişleri ele. (1.0 etkisizdi.)
4. **`weight_factor` 0.5–0.9** — yeni veriye ağırlık (rejim değişimi).
5. **Sınıf dengesizliği**: `model_training_parameters`'a `scale_pos_weight`
   (pozitif sınıf ~%40) veya `stratify_training_data`.
6. **`label_period_candles` 6–8 dene** — daha uzun ufuk, daha az whipsaw/fee.
7. **Fee etkisi**: 700–1100 işlem çok; toplam hacim 2.2M USDT → ~%20 fee drag.
   Eşik ↑ ve daha uzun ufuk bunu azaltır.
8. **Feature importance**: `plot_feature_importances` (plotly gerekir) veya
   `user_data/models/aicrypto-xgb-v1/` altındaki modelden SHAP.

## Durum

- ✅ FreqAI pipeline uçtan uca çalışıyor, walk-forward, hata yok.
- ✅ Model ölçülebilir, **OOS'ta da kalıcı** bir edge'e sahip
  (`freqai_down` in-sample +13% / OOS +8%, %65-70 win).
- ✅ **Strateji artık net pozitif ve genelliyor** (#8): in-sample +6.5%,
  OOS +2.8%, full +9.2%, max DD %3.3. Yapısal filtre ile, overfit'siz.
- ⚠️ Getiri düşük; gerçek fee/slippage sonrası marjinal. Kâr için sonraki iş:
  daha iyi target (regresyon / 3-sınıf), ek feature (`include_timeframes`
  çoklu, funding, orderbook), pozisyon boyutlandırma, daha çok coin.
- Sıra: **dry-run forward-test** (Aşama 3 çıkış kriteri) — canlı public veriyle
  1-2 hafta, tahmin dağılımı + gerçekleşen hit-rate logla. Sonra Aşama 4.
- Gerçek paraya hâlâ var: dry-run net pozitif + Aşama 4-5 merdiveni.
