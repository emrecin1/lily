# Lily — AI Crypto Trading Bot (V1)

AI destekli, risk yönetimi öncelikli bir **BTC/USDT spot long-only** trading botu.

> ⚠️ **UYARI:** Bu proje finansal tavsiye değildir. Backtest performansı gelecekteki
> performansı garanti etmez. Kripto para trading'i yüksek risk içerir.

> 🔄 **V2 geçişi sürüyor.** Real-time / otomatik alım-satım için proje
> **Freqtrade + FreqAI** omurgasına taşınıyor. Aşağıda anlatılan V1 CLI pipeline'ı
> (`src/`, `main.py`) **araştırma / referans** olarak korunuyor.
> - Hedef mimari: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
> - Omurga kararı: [`docs/adr/0001-backbone.md`](docs/adr/0001-backbone.md)
> - Aşama aşama geçiş: [`docs/MIGRATION.md`](docs/MIGRATION.md)

## Amaç

Bu proje, AI destekli sinyaller üreten ancak nihai kararı **Signal Engine + Risk Manager**'a
bırakan, güvenli ve tekrarlanabilir bir trading sistemi kurmayı hedefler. **V1'de gerçek para
ile işlem yapılmaz.**

## V1 Kapsamı

| Özellik | Durum |
|---|---|
| Market data (CCXT) | ✅ Public API |
| Feature Engineering | ✅ |
| ML modeli (XGBoost) | ✅|
| Backtest | ✅ |
| Paper trading | ✅ |
| Live trading | ❌ Devre dışı (`LIVE_TRADING=false`) |
| Futures / Kaldıraç | ❌ |
| Short pozisyon | ❌ |

## Mimari

```
Market Data (Exchange)
      ↓
Data Validation & Database (SQLite)
      ↓
Feature Engineering (indicators)
      ↓
XGBoost Prediction (probability)
      ↓
Signal Engine (BUY/HOLD/EXIT)
      ↓
Risk Manager (size, stop, daily loss, pause)
      ↓
Backtest / Paper Trader
```

**Karar zinciri:** AI yalnızca olasılık üretir. Nihai karar `Signal Engine + Risk Manager`
tarafından verilir.

## Kurulum

```bash
# 1. Sanal ortam oluştur ve aktifleştir
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 2. İkinci bağımlılık kur
pip install -r requirements.txt

# 3. Ortam değişkenlerini kur
cp .env.example .env
```

`.env` dosyasını asla git'e commit etme.

## Komutlar

```bash
python main.py download-data    # OHLCV verisi indir
python main.py build-features   # Feature hesapla
python main.py train            # XGBoost eğit
python main.py evaluate         # Model değerlendir
python main.py backtest         # Backtest çalıştır
python main.py paper            # Paper trading başlat
python main.py demo             # Kural bazlı AL/SAT demo (4 coin, 4h)
python main.py dashboard        # Web dashbboard'u başlat (FastAPI)
```

## Kural Bazlı Demo Sinyal Sistemi

Karar verdiğiniz yaklaşım: **BTC, ETH, SOL, BNB** üzerinde **4h** veriyle, **kural bazlı**
(trend + RSI) AL/SAT sinyalleri ve **demo bakiye** ile simülasyon.

```bash
python main.py demo
```

- **AL**  — EMA20 > EMA50 (yükseliş trendi) VE RSI < 45
- **SAT** — pozisyon açıkken EMA20 < EMA50 VEYA RSI > 70, veya TP/SL/trailing tetiklenirse
- **TP/SL** — yüzde bazlı: kâr hedefi (+%15) ve stop-loss (−%8)
- **Trailing stop** — örnekteki gibi: 1.0'dan 2.0'a çıktıysa, ~2.0·(1−0.20)=1.6'ya gerilerken kapatır
- **Risk kontrolü** — her coin'in bakiyesi asla negatife düşmez; pozisyon miktarı mevcut bakiyeyle sınırlı; fee+slippage uygulanır; **gerçek emir asla gönderilmez**

Çıktı: `data/processed/rules_demo.json` (coin bazlı sinyal geçmişi, trade'ler, açık pozisyon, bakiye).
Dashboard üzerinden "Demo sinyalleri üret" butonuyla tetiklenir.

> **Dürüst sonuç:** Bu basit kural stratejisi, 4h veri üzerinde ve bu parametrelerle
> (RSI<45 alım, RSI>70 satım, %15 TP / %8 SL, %20 trailing) geriye dönük testte kârlı
> çıkmamıştır (~−80%). Bunun sebebi 4 coinde whipsaw (yalpalama) ve komisyon birikmesidir.
> Sinyal ve risk mekanizması kusursuz çalışır; ama strateji parametreleri kâr için
> iyileştirilmeye açıktır. Tüm parametreler ortam değişkenleriyle ayarlanabilir
> (aşağıya bakın) — dashboard'da her coin'in sinyal/trade/pozisyon akışını görüp
> inceleyebilirsin.

### Kural parametreleri (`.env`)

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `RULES_SYMBOLS` | `BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT` | İzlenecek coinler |
| `RULES_TIMEFRAME` | `4h` | Zaman dilimi |
| `DEMO_BALANCE` | `10000` | Demo başlangıç bakiyesi |
| `ALLOCATION_PER_COIN` | `0.25` | Her coine ayrılan oran |
| `RULES_RSI_BUY_MAX` | `45` | AL için RSI üst sınırı |
| `RULES_RSI_SELL_MAX` | `70` | SAT için RSI alt sınırı |
| `RULES_TP_PCT` | `0.15` | Kâr hedefi (%15) |
| `RULES_SL_PCT` | `0.08` | Stop-loss (%8) |
| `RULES_TRAILING_PCT` | `0.20` | Trailing stop mesafesi |
| `RULES_USE_TRAILING` | `true` | Trailing stop aktif mi |

## Web Dashboard (Phase 9)

FastAPI + React tabanlı web arayüzü. **Backend**: crypto avcılığından izole, yalnızca
persisted çıktıları (equity curve, trades, paper predictions, model evaluation) okur ve
read-only'dir — exchange'e emir göndermez.

```bash
# 1) FastAPI backend'i başlat
python main.py dashboard          # http://127.0.0.1:8000
#   veya:  ./start-dashboard.sh   (arka planda kalıcı başlatır)

# 2) React frontend'i başlat (ayrı terminal)
cd frontend
npm install
npm run dev                       # http://127.0.0.1:5173 (proxy ile backend'e bağlanır)
```

### Dashboard'ı kullanma (adım adım)

1. Tarayıcıda `http://127.0.0.1:5173` adresini aç.
2. Üstteki dört özet kartı oku: **Market** (varlık), **Model** (test başarısı),
   **Backtest** (geçmiş sonuç), **Paper** (sanal hesap).
3. **"Backtest çalıştır"** butonuna bas → geçmiş veri üzerinde strateji koşar,
   equity grafiği ve trade tablosu anında güncellenir.
4. **"Paper Run (sanal)"** butonuna bas → canlı (public) fiyatla sanal işlem simülasyonu
   yapar. Bu buton **gerçek emir asla göndermez**; sonucu `real orders sent: 0` olarak raporlar.
5. Her kartın altında ne anlama geldiğini açıklayan açıklama metni vardır.

> Model zayıf olduğu için (test ROC-AUC ~0.64) varsayılan eşikte (0.70) backtest 0 işlem
> üretebilir — bu dürüst bir sonuçtur, ayar hatası değildir. İşlem görmek istersen
> `AI_THRESHOLD=0.55 python main.py backtest` gibi düşük bir eşikle deneyebilirsin.

Endpoint'ler:
- `GET /api/summary` — özet kartları (market/model/backtest/paper)
- `GET /api/equity` — backtest equity curve
- `GET /api/backtest/trades`, `GET /api/paper/trades` — trade listeleri
- `GET /api/paper/predictions` — per-candle structured prediction audit log
- `GET /api/evaluation` — model değerlendirme metrikleri
- `POST /api/paper/run` — bir paper-trading oturumu çalıştır (sanal, gerçek emir yok)
- `POST /api/backtest/run` — panel üzerinden backtest çalıştır
- `GET /api/rules/demo` — kural bazlı demo portföyü (coin bazlı sinyal/trade/pozisyon)
- `POST /api/rules/demo/run` — panel üzerinden demo sinyallerini üret
- `WS  /ws/paper` — paper durumu WebSocket kanalı

## Konfigürasyon

Tüm parametreler `src/config.py` üzerinden yönetilir. Değerler ortam değişkenleriyle
override edilebilir:

```bash
export SYMBOL="BTC/USDT"
export TIMEFRAME="1h"
export INITIAL_CAPITAL=10000
export MAX_RISK_PER_TRADE=0.005
export MAX_DAILY_LOSS=0.015
```

Önemli parametreler:

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `MAX_RISK_PER_TRADE` | 0.005 | İşlem başına risk (%0.5) |
| `MAX_DAILY_LOSS` | 0.015 | Günlük maksimum kayıp (%1.5) |
| `MAX_OPEN_POSITIONS` | 1 | Maksimum açık pozisyon |
| `AI_THRESHOLD` | 0.70 | AI sinyal eşiği |
| `ATR_STOP_MULTIPLIER` | 1.5 | ATR bazlı stop mesafesi çarpanı |
| `TAKER_FEE` | 0.001 | Taker komisyonu (per trade) |
| `SLIPPAGE` | 0.0005 | Kayma (slippage) |

## Risk Yönetimi

- **Position sizing:** `risk_amount / stop_distance` formülüyle hesaplanır.
- **Stop loss:** `entry_price - (ATR * 1.5)`
- **Take profit:** Risk:Reward = 1:2
- **Daily loss protection:** Günlük kayıp %1.5'i aşarsa `TRADING_DISABLED`.
- **Consecutive loss protection:** 3 ardışık kayıptan sonra trading duraklatılır.

## Güvenlik

- `LIVE_TRADING=false` iken gerçek exchange order API'sine **hiçbir emir gönderilmez**.
- API key'ler `.env` üzerinden okunur, `settings.py` içine **asla** yazılmaz.
- 💼 **Withdrawal permission'ı gerektiren API key kullanma.** Sadece okuma içerikli key yeterli.
- Futures, kaldıraç, short pozisyon **desteklenmez.**

## Veri Akışı

- Data `data/raw/` altında toplanır.
- İşlenen veriler `data/processed/` altında saklanır.
- SQLite database `data/database/bot.db` içinde tutulur.
- Modeller `models/` altında `joblib` ile saklanır.

## Bilinen Kısıtlar ve Sürecin Durumu

- **V1 — Phase 1–8 tamamlandı:** Market verisi, veri doğrulama, feature engineering,
  model eğitimi/değerlendirme, backtest, risk yönetimi ve **paper trading** bitmiştir.
  Geriye sadece Phase 9 (dokümantasyon/temizlik) kalmıştır.
- Veri indirme, feature engineering, model eğitimi, backtest ve paper trading ilgili
  komutlarla ayrı aşamalarda yapılır.
- Backtest ve paper trading **aynı RiskManager**'ı kullanır; risk limitleri iki süreçte
  de özdeş davranır.

## Paper Trading

Canlı (public) market verisiyle sanal hesap üzerinde çalışır; **gerçek emir asla gönderilmez**.

```bash
AI_THRESHOLD=0.55 python main.py paper
```

- Pipeline: canlı veri → feature → XGBoost → signal → risk → sanal trade.
- Çıktılar: `data/processed/paper_trades.csv` ve `data/processed/paper_predictions.csv`
  (per-candle structured audit log: timestamp/symbol/price/model_probability/signal/RSI/
  EMA20/EMA50/ATR/position_size/stop_price/target_price).
- `PaperTrader` exchange order API'sine erişmez; `LIVE_TRADING` olsa bile gerçek emir
  gönderme yeteneğine sahip değildir.

## Test

```bash
pytest
```

Testler, feature hesaplama, target oluşturma, no-lookahead, pozisyon büyüklüğü,
stop-loss, risk limitleri, günlük kayıp, ardışık kayıp, sinyal oluşumu, backtest
muhasebesi, komisyon hesaplama ve paper trading dahil olmak üzere kapsamlı bir
güvenlik kontrolü sağlar.

## Disclaimer

Bu proje **eğitim/araştırma amaçlıdır** ve finansal tavsiye değildir. Backtest
sonuçları geçmiş veriye dayanır ve gelecekteki performansı garanti etmez. Kripto
para yatırımları yüksek kayıp riski taşır.