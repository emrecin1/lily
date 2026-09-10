# ADR 0001 — Real-time omurga: Freqtrade + FreqAI

- **Durum:** Kabul edildi
- **Tarih:** 2026-09-10
- **Karar veren:** proje sahibi (tek geliştirici, kişisel kullanım)

## Bağlam

V1, tek seferlik CLI komutlarından oluşan bir pipeline (veri indir → feature →
XGBoost eğit → backtest → paper). Hedef değişti: **7/24 çalışan, canlı piyasa
takibi yapan, ileride Binance spot'ta otomatik alım-satıma geçecek** bir sistem.
Geliştirici bu alanda uzman değil ve önceliği açıkça "sorunsuz, güvenli" bir
altyapı.

Bu, tek-seferlik script'lerden **event-driven, uzun ömürlü servise** geçiş
demek. En riskli parça: order/execution management (idempotency, kısmi dolum,
red/retry, rate-limit, borsa kesintisi, restart sonrası mutabakat). Buradaki
hatalar gerçek para kaybettirir.

## Değerlendirilen seçenekler

### A. Kendi event-driven çekirdeğimiz (asyncio + Redis/NATS bus)

- (+) Tam kontrol, mevcut `src/` mimarisiyle uyumlu, elle yazılan backtest motoru kalır.
- (−) Execution/OMS'i güvenli yazmak aylar alır; test yüzeyi çok geniş.
- (−) Reconnect, kısmi dolum, rate-limit, mutabakat — hepsi sıfırdan ve hatası pahalı.
- (−) Tek geliştirici + sınırlı deneyim ile risk/efor oranı kötü.

### B. NautilusTrader omurga

- (+) Production-grade, event-driven, tick seviyesi, backtest=live parity, gerçek OMS.
- (−) Dik öğrenme eğrisi; kavram yoğunluğu yüksek.
- (−) Mum-bazlı ML sinyali için fazla ağır (YAGNI). Tick/egzotik emir ihtiyacı yok.
- (−) UI/kontrol düzlemi zayıf; Telegram/dashboard'u kendin kurarsın.

### C. Freqtrade + FreqAI omurga  ← SEÇİLDİ

- (+) `dry_run: true` varsayılan; gerçek işleme geçiş explicit config + flag zinciri gerektirir → kazara canlı işlem yapılamaz.
- (+) Binance + Binance testnet native destek.
- (+) Telegram kontrol (`/stop`, `/forceexit`, `/reload_config`) + FreqUI + REST API hazır.
- (+) Reconnect / kısmi dolum / rate-limit / borsa tuhaflıkları binlerce canlı kullanıcıda çözülmüş.
- (+) Dahili `backtesting` + `hyperopt` → README'nin işaret ettiği parametre araması bedava.
- (+) **FreqAI** projenin şekliyle birebir: rolling retrain, feature pipeline, XGBoost/LightGBM/CatBoost, tahmin → sinyal.
- (+) "protections" eklentileri (StoplossGuard, MaxDrawdown, CooldownPeriod, LowProfitPairs) = hazır risk katmanı.
- (−) Opinionated ve mum-bazlı; tick seviyesi / egzotik emir tipleri kısıtlı.
- (−) Elle yazılan backtest motoru, CLI fazları ve React frontend "referans"a düşer — batık emek.
- (−) Framework'ün strateji arayüzüne (`IStrategy`, FreqAI callback'leri) uyum zorunlu.

## Karar

**Freqtrade + FreqAI** omurga olarak benimsenir.

`src/` pipeline'ı silinmez: feature tanımları, ML hedef tasarımı, risk kuralları
ve V1 backtest motoru **araştırma + çapraz-kontrol referansı** olarak korunur.
Yeni runtime `user_data/` + `config/` altında Freqtrade sözleşmesine göre kurulur.

Geçiş, `docs/MIGRATION.md`'deki aşamalarla, her aşama dry-run'da doğrulanarak
yapılır. Gerçek paraya geçiş yalnızca dry-run → testnet merdiveni tamamlanınca.

## Sonuçlar

- Yeni bağımlılık: `freqtrade` (kendi ortamında; `pyproject.toml`'a opsiyonel
  `runtime` grubu). `ccxt` zaten vardı.
- `main.py` CLI'si araştırma komutları için kalır; canlı çalışma `freqtrade
  trade` ile.
- Frontend: FreqUI kullanılacak; `frontend/` (React) arşivlenir.
- İlk hedef borsa: **Binance spot**, ilk ortam **testnet**.
- Bu karar, tick seviyesi veri / co-location / egzotik emir ihtiyacı doğarsa
  (ADR-000X ile) yeniden değerlendirilir; o noktada NautilusTrader tekrar masada.
