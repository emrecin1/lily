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

## İlk backtest sonuçları — 4 coin, 2024-01 → 2026-09

| # | Ayar | Toplam | İşlem | Win% | Max DD |
|---|---|---|---|---|---|
| 1 | buy_proba 0.55, stop **−8%**, trailing %20 | **−21.8%** | 1107 | 56.0 | 25.5% |
| 2 | buy_proba 0.55, stop **−20%**, trailing kapalı | −10.7% | 983 | 58.4 | 18.8% |
| 3 | buy_proba **0.62**, stop −20% | **−6.34%** | 713 | 59.5 | 13.9% |
| 4 | + `DI_threshold=1.0` | −6.34% (**etkisiz** — hiçbir mum DI>1.0) | 713 | 59.5 | 13.9% |

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
- ✅ Model ölçülebilir bir edge'e sahip (`freqai_down` +%27, %60 win).
- ⚠️ Strateji henüz net negatif (−%6.3); kayıp trade-yönetiminden, model
  sinyalinden değil. Yukarıdaki 8 kalemle pozitife çekilmeli.
- Gerçek paraya **çok var** — önce bu strateji dry-run'da net pozitif +
  out-of-sample dayanıklı olmalı (Aşama 4-5).
