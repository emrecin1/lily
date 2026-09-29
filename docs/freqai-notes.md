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

### #10 — ATR-bazlı custom_stoploss denemesi (deney; GERİ ALINDI)

`custom_stoploss()`: giriş anındaki ATR(14)'e göre SABİT stop fiyatı
(`entry − ATR×multiplier`, V1 `risk_manager.atr_stop_multiplier` mantığı),
kâr tarafına dokunmaz, `-%20` mutlak tavan olarak kalır (`max()` ile).
Amaç: "azınlık yanlış giriş" işlemlerinin `-%20`'ye kadar düşmesini daha
erken kesmek (bkz. "Kritik bulgu" bölümü).

**Not:** bu deney artık 66 coinlik güncel pairlist üzerinde koşuldu (2026-06-15
→ 2026-09-15, 3 ay), #1-#9'daki 4-coin deneylerinden farklı bir evren —
sayılar doğrudan karşılaştırılamaz, ama ATR ↔ sabit stop A/B'si aynı
koşullarda yapıldı.

| Çarpan | Toplam getiri | Not |
|---|---|---|
| **Baseline (sabit -%20)** | **+8.55%** | 219 işlem, %56 win — `time_stop` (22, tamamı zarar) en büyük kayıp kaynağı |
| ATR × 1.5 (V1 varsayılanı) | **-8.68%** | çok sıkı → whipsaw (337 işlem, `trailing_stop_loss` 140 işlem tamamı zarar −%47) |
| ATR × 2.0 | +2.45% | |
| ATR × 2.5 | +3.53% | |
| ATR × 3.0 | +6.03% | |
| ATR × 4.0 | +5.88% | |
| ATR × 5.0 | +8.05% | en iyi ATR sonucu, hâlâ baseline'ın altında |

Çarpan büyüdükçe sonuç baseline'a yakınsıyor (ATR mesafesi `-%20` tavanını
aşınca fiilen devre dışı kalıyor) ama **hiçbir çarpan sabit -%20'yi geçemedi**.
Sonuç: bu portföy/zaman diliminde `time_stop` + model sinyali kombinasyonu
"azınlık yanlış giriş" sorununu ATR-bazlı fiyat stop'undan daha iyi çözüyor.
**GERİ ALINDI** — kod `AiCryptoFreqAIStrategy.py`'den çıkarıldı, #8 (sabit
-%20 + trend filtresi + time_stop) esas alınmaya devam ediyor.

### #11 — Sabit stop'u sıkılaştırma denemesi (-%10 / -%5, deney; GERİ ALINDI)

Soru: "-%20 çok geniş, -%10/-%5'e düşürsek kâr artar mı?" Güncel 66 coinlik
pairlist + buy_proba=0.65 ile aynı 3 aylık pencerede (2026-06-15 → 2026-09-15)
test edildi:

| Sabit stop | Toplam getiri | `stop_loss` işlem sayısı | Max drawdown |
|---|---|---|---|
| **-%20 (mevcut)** | **+8.55%** | 1 / 219 (%0.5) | %6.8 |
| -%10 | +3.86% | 14 / 227 (%6) | %9.8 |
| -%5 | **-7.14%** | 87 / 280 (%31!) | %16.0 |

Sonuç net: stop sıkılaştıkça hem getiri düşüyor HEM drawdown artıyor (ikisi
birden kötüleşiyor — tipik whipsaw imzası). -%5'te `stop_loss` işlemlerin
**üçte biri** olup modelin kârlı `freqai_down` sinyalini eziyor (-%41.3 toplam
katkı). **GERİ ALINDI** — -%20 (mevcut) aynen korunuyor, ATR denemesi (#10)
ile aynı ders: bu stop zaten bir "felaket tavanı", sıkılaştırmak "daha
dikkatli risk yönetimi" değil, normal 4h oynaklıkta erken/gereksiz çıkış
demek. Kâr artırmak için önceliğe bkz: `buy_proba`/DI/class-imbalance/hyperopt.

### #12 — buy_proba taraması (0.65 → 0.70, UYGULANDI)

Aynı 66-coin pairlist, 3 aylık pencere (2026-06-15 → 2026-09-15), sadece
`buy_proba` degistirildi:

| buy_proba | İşlem | Toplam getiri | Sharpe | Max DD |
|---|---|---|---|---|
| 0.65 (önceki) | 219 | +8.55% | 3.35 | %6.8-7.0 |
| 0.68 | 193 | +9.90% | 3.65 | %4.7-5.0 |
| **0.70** | 178 | **+10.48%** | **3.73** | **%4.3-5.0** |
| 0.72 | 161 | +9.62% | 3.45 | %4.3-4.9 |
| 0.75 (üst sınır) | 141 | +7.65% | 2.70 | %4.5-5.3 |

0.70'te getiri/Sharpe/drawdown ÜÇÜ birden iyileşiyor (0.65'e göre), 0.72'den
sonra ornek kucalup getiri geriliyor. V1'in orijinal varsayılanının da 0.70
olması ilginç bir tutarlılık. **UYGULANDI**: `AiCryptoFreqAIStrategy.json` +
class default → 0.70. (Önceki adımda 0.5 → 0.65 idi; bu ikinci bir yükseltme.)

### #13 — DI_threshold taraması (0 → 0.6, UYGULANDI)

Öncelik listesindeki #3 madde. buy_proba=0.70 sabit, aynı pairlist. İlk pencere
(2026-06-15 → 2026-09-15, tuning):

| DI_threshold | Getiri | Sharpe |
|---|---|---|
| 0.3 | -1.65% | -0.48 |
| 0.4 | +7.24% | 2.54 |
| 0.5 | +13.84% | 4.96 |
| 0.55 | +7.39% | 2.79 |
| 0.6 | +14.88% | 5.27 |
| 0.65 | +15.83% | 5.64 |
| 0.7 | +10.32% | 3.82 |
| 0.8 | +8.09% | 3.03 |
| 1.0 | +10.59% | 3.82 |
| 0 (kapalı, önceki) | +10.48% | 3.73 |

Eğri düzensiz/gürültülü (0.5→0.55'te ani düşüş) — tek pencereye overfit riski
(deney #7'deki hyperopt dersi). **OOS doğrulama** — farklı bir pencerede
(2026-03-15 → 2026-06-15, tuning'in görmediği veri):

| DI_threshold | Getiri | Sharpe |
|---|---|---|
| 0 | +3.01% | 1.10 |
| 0.5 | +3.82% | 1.48 |
| **0.6** | **+6.00%** | **2.26** |
| 0.65 | +4.70% | 1.76 |

Mutlak büyüklük farklı (bu pencere genel olarak zayıf) ama yön/sıralama
tutarlı: filtreleme (0.5-0.65) her zaman kapalıdan iyi, **0.6 iki pencerede
de en iyi/en iyiye yakın** — tek pencerenin mutlak zirvesi (0.65) ikincide
geriliyor. **UYGULANDI**: `config.freqai.json` → `DI_threshold: 0.6` (0.65
değil, daha sağlam nokta seçildi).

### #14 — scale_pos_weight denemesi (sınıf dengesizliği; GERİ ALINDI)

Öncelik listesindeki #5 madde. Gerçek sınıf dağılımı ölçüldü: **%35.8 "up" /
%64.2 "down"** (docs'taki ~%40 tahminiyle uyumlu). "Ders kitabı" formülü
(`down/up`) → 1.796. buy_proba=0.70 + DI_threshold=0.6 sabit, aynı pencere:

| scale_pos_weight | Getiri | Sharpe |
|---|---|---|
| **1.0 (kapalı/varsayılan)** | **+14.88%** | **5.27** |
| 1.5 | +14.57% | 5.24 |
| 1.8 (hesaplanan "dengeli") | +5.76% | 1.98 |
| 2.5 | +7.16% | 2.37 |

Sonuç net: dengeleme performansı BOZUYOR, düzeltmiyor. Model zaten
`buy_proba`+`DI_threshold` ile yeterince seçici; "up" sınıfına yapay ağırlık
vermek modeli daha hevesli/az güvenilir hale getiriyor. **GERİ ALINDI** —
`model_training_parameters`'a `scale_pos_weight` eklenmedi, varsayılan (yok)
korunuyor.

### #15 — weight_factor denemesi (yeni veriye ağırlık; GERİ ALINDI)

Öncelik listesindeki #4 madde. buy_proba=0.70 + DI_threshold=0.6 sabit:

| weight_factor | Getiri | Sharpe |
|---|---|---|
| **0 (kapalı, mevcut)** | **+14.88%** | **5.27** |
| 0.3 | +3.45% | 1.33 |
| 0.5 | +5.32% | 1.96 |
| 0.7 | +7.94% | 2.92 |
| 0.9 | +14.32% | 4.92 |

0→0.9 monoton artıyor ama hiçbiri kapalı halini geçemiyor. Yorum: haftalık
walk-forward retrain (`backtest_period_days=7`) zaten modeli güncel tutuyor;
üstüne exponansiyel recency-weighting eklemek eğitim verisini fakirleştirip
zarar veriyor. **GERİ ALINDI** — `weight_factor=0` (varsayılan) korunuyor.

### #16 — label_period_candles denemesi (4 → 6/8; GERİ ALINDI)

Öncelik listesindeki #6 madde. buy_proba=0.70 + DI_threshold=0.6 sabit:

| label_period_candles | Ufuk | Getiri | Sharpe |
|---|---|---|---|
| **4 (mevcut)** | 16h | +14.88% | **5.27** |
| 6 | 24h | +15.20% | 4.94 |
| 8 | 32h | +10.61% | 3.32 |

6'da getiri marjinal artıyor (+%0.3) ama Sharpe düşüyor — net bir kazanç
değil, gürültü sınırında. 8 net kötü. **GERİ ALINDI** — `label_period_candles
=4` (varsayılan) korunuyor, hedef tanımını değiştirmenin (daha büyük yapısal
değişiklik) karşılığı yok.

### ⚠️ KRİTİK: DI_threshold canlı/dry-run modda ÇÖKÜYOR (deney #13 düzeltmesi)

`DI_threshold=0.6` backtest'te sorunsuzdu ve UYGULANMIŞTI (#13), ama **canlı
(`freqtrade trade`) modda her mum döngüsünde çöküyor**:

```
KeyError: 'DI_values'
  File ".../freqtrade/freqai/data_drawer.py", line 468, in append_model_predictions
    DI_values_loc = df.columns.get_loc("DI_values")
```

Sebep: backtest `start_backtesting` kod yolunu kullanıyor, canlı `start_live`
→ `append_model_predictions` farklı bir yol izliyor ve bu freqtrade 2026.8
sürümünde `DI_values` kolonu canlıda hiç set edilmiyor (muhtemelen freqtrade/
freqai kütüphanesinde bir bug/versiyon uyumsuzluğu). **Sonuç: 16 Eylül
07:21 → 18 Eylül 09:04 arası (~2 gün) bot tamamen sessiz kaldı, TEK bir
işlem bile açmadı** — `_analyze_ticker_internal` her parite/her döngüde
istisna fırlatıp hiçbir sinyal üretemedi (65 paritenin hepsi, 4000+ hata
logda). KAVA pozisyonu bu yüzden 2 gün gecikmeli kapandı (+%3.21, şans
eseri zararlı değildi).

**18 Eylül 09:07'de `DI_threshold=0 (kapalı)`'ya geri alındı, canlı bot
yeniden başlatıldı, hata durdu.** buy_proba=0.70 aynen korunuyor (o parametre
bu hatadan etkilenmiyor, sadece giriş filtresi, FreqAI'nin dahili DI
hesaplama koduna dokunmuyor).

**Yan bulgu — `MaxDrawdown` koruması varsayılan "ratios" modunda yanıltıcı:**
düzeltme sonrası KAVA nihayet kapanınca (2 gün gecikmeli, +%3.21), strateji
`protections` listesindeki `MaxDrawdown` (lookback 48 mum/8 gün, eşik %10)
devreye girdi — **%11.46, sonra %18.97** düşüş raporlayıp botu sırasıyla
20 ve 22 Eylül'e kadar kilitledi. Kaynağı okundu
(`freqtrade/plugins/protections/max_drawdown_protection.py`): varsayılan
`calculation_mode="ratios"` **pozisyon büyüklüğünü/hesap bakiyesini hiç
hesaba katmıyor** — her işlemin `close_profit` ORANINI ham ham üst üste
topluyor, zirveden düşüşü buna göre ölçüyor. Gerçek (equity/$ bazlı) düşüş
o an sadece **~%3.1-3.7** idi (10.126$ zirve → 9.750-9.808$) — koruma
gereğinden çok daha erken/sert tetiklenmiş. **Düzeltme**: `protections`
listesindeki `MaxDrawdown` bloğuna `"calculation_mode": "equity"` eklendi
(gerçek $ bazlı hesap), canlıya alındı; eski yanlış-hesaplanmış iki kilit
(`/locks` DELETE ile) elle temizlendi. Yeni modda aynı durum tekrarlanırsa
gerçek risk seviyesini yansıtacak.

**DERS — bundan sonra:** backtest'te doğrulanmış bir FreqAI
`feature_parameters` değişikliği canlıya alınmadan önce, en az birkaç saat
canlı/dry-run'da **hatasız çalıştığı** (log'da ERROR yok) doğrulanmadan
"uygulandı" sayılmasın.

**20 Eylül — ikinci deneme, KESİN SONUÇ: kök neden önbellek değilmiş.**
Hipotez: `user_data/models/aicrypto-xgb-v1/historic_predictions.pkl` eski
şemayla (DI_threshold=0 zamanından, `DI_values` sütunu yok) kalmıştı; bu
dosya silinip DI_threshold=0.6 ile temiz bir restart yapıldı. İlk ~50 dakika
hatasız göründü (log rotasyonu yüzünden YANLIŞ ölçüldü — eski marker satırı
artık dosyada yoktu, "0 hata" sonucu anlamsızdı). Bir sonraki mum kapanışında
(08:00 UTC) **aynı `KeyError('DI_values')` aynı yerden (`data_drawer.py:468`)
geri döndü**, 65 paritenin hepsini ~1 saat felç etti (REZ pozisyonunun çıkış
sinyali de bu sürede değerlendirilemedi). Önbellek temizleme YETERSİZ —
sorun `set_initial_historic_predictions`/`append_model_predictions` arasındaki
başka bir tutarsızlıktan kaynaklanıyor, kaynağı tam tespit edilemedi.
**KESİN KARAR: `DI_threshold` FreqTrade 2026.8'in (PyPI'deki EN GÜNCEL sürüm
— yükseltme seçeneği yok) canlı-mod kod yolunda kalıcı olarak bozuk. Bir
daha DENENMEYECEK** — gerçek çözüm FreqTrade kaynak kodunu yamalamak
gerektirir, bu da ayrı bir risk; kâr/risk dengesi buna değmiyor. `buy_proba
=0.70` (kanıtlanmış, sorunsuz) tek başına yeterli kabul edildi.

### #17 — max_open_trades denemesi (5 → 8/10/15; GERİ ÇEVRİLDİ)

23 Eylül, testnet'te 5/5 slot dolunca soruldu: "daha fazla fırsat için
artıralım mı?" buy_proba=0.70 + DI_threshold=0 (canlı ayarlar) sabit:

| max_open_trades | İşlem | Getiri | Sharpe | Max DD |
|---|---|---|---|---|
| **5 (mevcut)** | 178 | **+10.48%** | **3.73** | **%4.3** |
| 8 | 237 | +2.72% | 1.05 | %13.5 |
| 10 | 249 | +0.06% | 0.02 | %15.7 |
| 15 | 263 | +3.68% | 1.41 | %12.9 |

Net ve tek yönlü kötüleşme. Sebep: `stake_percent=0.10` HER pozisyon için
sabit (max_open_trades'e bölünmüyor) — slot artışı = eş zamanlı sermaye
maruziyeti artışı (5 slotta ~%50, 10 slotta ~%100), kripto'nun yüksek
korelasyonu yüzünden bu çeşitlendirme değil risk çoğaltması. **5'te
kalınıyor**, artırma denenmeyecek (stake_percent mimarisi değişmeden).

### Öncelik listesi durumu (Aşama 3, güncel)

1. ✅ ATR-bazlı custom_stoploss — denendi, GERİ ALINDI (#10)
2. ✅ buy_proba ↑ — 0.5→0.65→**0.70**, UYGULANDI
3. ⚠️ DI_threshold ↓ — backtest'te 0→0.6 doğrulandı ama CANLIDA ÇÖKÜYOR
   (yukarıdaki KRİTİK not), 18 Eylül'de 0'a GERİ ALINDI — bkz. yukarısı
4. ✅ weight_factor — denendi, GERİ ALINDI (#15)
5. ✅ scale_pos_weight (sınıf dengesizliği) — denendi, GERİ ALINDI (#14)
6. ✅ `label_period_candles` 6-8 — denendi, GERİ ALINDI (#16)
7. ⬜ Fee etkisi analizi (henüz yapılmadı)
8. ⬜ Feature importance / SHAP (henüz yapılmadı)

Kümülatif: kapalı-hal → buy_proba+DI_threshold ile ~+10.5%'ten **+14.88%**'e
(aynı 3 aylık pencere, güncel 66-coin pairlist).

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

## Gözlenen ara sıra hata: `KeyError: 'labels_std'` (dry-run, canlı)

`webui/`'nin `/system` log sayfası üzerinden fark edildi: `XGBoostClassifier.
predict()` bazen `dk.data["labels_std"]` bulamayıp `KeyError` atıyor
(`freqtrade.strategy.strategy_wrapper` tarafından yakalanıp ERROR olarak
loglanıyor — **bot çökmüyor**, o mumda ilgili parite için analiz/tahmin o
döngüde atlanıyor, bir sonraki döngüde normale dönüyor). Walk-forward retrain
sonrası modelin `dk.data` icindeki metadata'sı henuz tam yuklenmeden bir
tahmin cagrisi gelirse olusuyor gibi gorunuyor (FreqAI'nin retrain/swap
sirasindaki bir yarisma durumu olabilir). Siniflandirici oldugumuz icin
`labels_std` degerleri zaten `{"down":0,"up":0}` — kritik bilgi kaybi yok,
ama sik olursa (özellikle retrain'in hemen ardindan gelen mum) o
dongude sinyal kacirilmis olabilir. Izlemeye deger; siklik artarsa
`train_period_days`/`backtest_period_days` ayarlarini gozden gecir veya
upstream Freqtrade/FreqAI issue'larina bak.
