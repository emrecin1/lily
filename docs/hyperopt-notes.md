# Hyperopt Notları — AiCryptoFeatureStrategy (Aşama 2 sonu)

## Kurulum

`.venv-rt`'ye hyperopt bağımlılıkları eklendi:
- `optuna>4.0.0`, `cmaes`, `filelock`, `scikit-learn`
- **`joblib` 1.6.0 → 1.4.2'ye düşürüldü.** Freqtrade 2026.8 kodu
  `from joblib.externals import cloudpickle` yapıyor; joblib 1.6 bunu
  kaldırdı. 1.4.2 hâlâ vendor'lıyor. (freqai/data_drawer.py de aynı importu
  kullanıyor — Aşama 3 için de gerekli.)

## Çalıştırma

```bash
.venv-rt/bin/freqtrade hyperopt --config config/config.dry.json \
  --strategy AiCryptoFeatureStrategy --hyperopt-loss SharpeHyperOptLoss \
  --spaces buy sell roi stoploss trailing --epochs 300 \
  --timerange 20230101-20250101 --random-state 42
```

300 epoch ≈ 88 sn (16 paralel worker, Optuna NSGAIII sampler).
Sonuç `user_data/hyperopt_results/*.fthypt` (gitignore).

## Sonuç: OVERFIT — kullanılmıyor

En iyi epoch (296/300): in-sample **+19.94%**, 268 işlem.
Otomatik export edilen `AiCryptoFeatureStrategy.json` **repodan çıkarıldı** —
strateji kod varsayılanlarında bırakıldı.

### In-sample vs Out-of-sample

| Params | 2023-01 → 2025-01 (in-sample) | 2025-01 → 2026-09 (out-of-sample) |
|---|---|---|
| Kod varsayılanları (rsi_buy 45 / rsi_sell 70 / SL -8% / TP +15% / trail %20) | +0.03% (179 işlem) | **-4.99%** (147 işlem) |
| Hyperopt "en iyi" (rsi_buy 59 / rsi_sell 89 / SL -31.5% / ROI kademeli / trail %11) | +19.94% (268 işlem) | **-11.84%** (226 işlem), Sharpe -0.65 |

**Hyperopt out-of-sample'ı daha KÖTÜ yaptı** (-5% → -12%). Klasik aşırı-uyum:
2023-2024 gürültüsüne curve-fit eden parametreler görülmemiş veride negatif
genelliyor. Özellikle `stoploss = -31.5%` gerçek bir risk kuralı değil,
"stop'a hiç takılma" hilesidir.

En iyi params (referans, KULLANMA):
```json
{"buy_rsi_max": 59, "sell_rsi_max": 89, "stoploss": -0.315,
 "minimal_roi": {"0": 0.334, "1744": 0.16, "3468": 0.109, "8683": 0},
 "trailing_stop_positive": 0.11, "trailing_stop_positive_offset": 0.18,
 "trailing_only_offset_is_reached": false}
```

### Çıkarım

Ham EMA20/EMA50 + RSI kuralının BTC/ETH/SOL/BNB 4h üzerinde **kalıcı bir edge'i
yok** — parametre ayarıyla düzelmiyor, hyperopt sadece geçmişe uyduruyor.
Bu, **Aşama 3'e (FreqAI / ML sinyali) geçiş için net gerekçe**.

### Hyperopt'u ileride doğru kullanmak için

- **Walk-forward**: tek in-sample/out-of-sample yerine kayan pencere
  (Freqtrade `--timerange` döngüsü veya FreqAI'nin `backtest_period_days`).
- Daha az serbestlik: `roi`/`trailing` space'lerini optimize etme, yalnızca
  1-2 anlamlı parametre.
- `stoploss` alt sınırını daralt (ör. -0.15) — "stop yok" çözümlerini engelle.
- Loss fonksiyonu: `SharpeHyperOptLossDaily` veya `CalmarHyperOptLoss` +
  minimum işlem sayısı kısıtı.
