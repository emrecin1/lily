"""
AiCryptoFreqAIStrategy — V1 ML pipeline'inin FreqAI portu.

docs/MIGRATION.md Asama 3.

Fikir:
  - Feature'lar : V1'in 25 feature'i (src.features.indicators.add_indicators),
                  `%-` on ekiyle FreqAI'ye verilir  -> V1 ile ayni girdi.
  - Hedef      : V1 ile ayni  ->  future_return(label_period_candles) >= min_return
                  ikili siniflandirma ("up" / "down").
  - Model      : XGBoostClassifier (--freqaimodel XGBoostClassifier).
                  Hiperparametreler config.freqai.json > model_training_parameters
                  (V1 MLConfig degerleri).
  - Giris      : do_predict == 1  AND  tahmin == "up"  AND  P(up) >= esik.
  - Cikis      : do_predict == 1  AND  tahmin == "down"   (stop/roi/trailing ayrica).

V1'den farklar (bilincli):
  - Tek sabit split yerine FreqAI **walk-forward** (backtest_period_days).
  - label_period_candles = 4  ->  4x4h = 16h ileri ufuk (V1 ML'i 1h veride 4h idi).
    Ayarlanabilir; bkz. config.freqai.json.
  - `scale_pos_weight` yok; sinif dengesizligi icin ilk kosudan sonra
    model_training_parameters'a eklenebilir (docs/hyperopt-notes.md ruhu).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import DecimalParameter, IStrategy, RealParameter

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.features.indicators import add_indicators  # noqa: E402
from src.ml.dataset import feature_columns as v1_feature_columns  # noqa: E402

MIN_RETURN = 0.008  # V1 MLConfig.target_return


class AiCryptoFreqAIStrategy(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "4h"
    can_short = False

    # Cikis KARARI esas olarak modele ait (freqai_down sinyali). Backtest
    # (docs/freqai-notes.md): freqai_down cikislari kârli; kayip, modelin kotu
    # yanildigi azinlik girisin sert stop'a dusmesinden. Sabit stop = GENIS
    # katastrofi backstop'u; kâr korumasi custom_stoploss (breakeven+trail) ile.
    # Deney gecmisi (docs/freqai-notes.md):
    #  - -%8 sabit stop  -> -21.8% (whipsaw)
    #  - -%20 sabit stop -> -10.7%
    #  - + buy_proba 0.62 -> -6.3%  (en iyi)
    #  - + breakeven custom_stoploss -> -22% (kazananlari kesti; GERI ALINDI)
    # Sonuc: modelin kâr tarafina karisma. Tek sorun = azinlik yanlis girisin
    # -%20'ye dusmesi. Cozum: eski+zararda pozisyonlar icin zaman-stop.
    minimal_roi = {"0": 0.15}
    stoploss = -0.20
    trailing_stop = False

    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False

    startup_candle_count: int = 400

    # P(up) giris esigi. V1 varsayilani 0.70 idi ve hic sinyal uretmiyordu.
    buy_proba = RealParameter(0.50, 0.75, default=0.65, space="buy", optimize=True)
    # Zaman-stop: trade time_stop_candles'tan eski VE kâr < time_stop_loss ise cik.
    time_stop_candles = DecimalParameter(6, 24, default=12, decimals=0,
                                         space="sell", optimize=True)
    time_stop_loss = DecimalParameter(-0.12, -0.02, default=-0.05, decimals=2,
                                      space="sell", optimize=True)

    # Gunluk kayip limiti (V1 RiskManager MAX_DAILY_LOSS ~%1.5). Bugun (UTC)
    # realize kayip baslangic sermayesinin bu oranini asarsa yeni giris yok.
    # Freqtrade "protections" (StoplossGuard/MaxDrawdown) mum bazli; bu
    # takvim-gunu bazli, stratejiden bagimsiz bir sert kapi. .env / config ile
    # override edilebilir olsun diye sabit (hyperopt'a acmiyoruz).
    max_daily_loss_pct: float = 0.02

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 2},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 24,
                "trade_limit": 3,
                "stop_duration_candles": 12,
                "only_per_pair": False,
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 48,
                "trade_limit": 5,
                "stop_duration_candles": 24,
                "max_allowed_drawdown": 0.10,
            },
        ]

    # ------------------------------------------------------------------ #
    # FreqAI feature engineering
    # ------------------------------------------------------------------ #

    def feature_engineering_expand_all(
        self, dataframe: DataFrame, period: int, metadata: dict, **kwargs
    ) -> DataFrame:
        """indicator_periods_candles uzerinde otomatik genisleyen birkac ek
        feature (V1'in 25'ine ilave sinyal). Hepsi `%-` on ekli."""
        import talib.abstract as ta

        dataframe["%-rsi-period"] = ta.RSI(dataframe, timeperiod=period)
        dataframe["%-adx-period"] = ta.ADX(dataframe, timeperiod=period)
        dataframe["%-cci-period"] = ta.CCI(dataframe, timeperiod=period)
        dataframe["%-relvol-period"] = (
            dataframe["volume"] / dataframe["volume"].rolling(period).mean()
        )
        return dataframe

    def feature_engineering_expand_basic(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        """V1'in TAM feature seti — src.features.indicators.add_indicators ile
        birebir (Asama 2 parity), `%-` on ekiyle FreqAI'ye verilir."""
        feats = add_indicators(dataframe)
        for col in v1_feature_columns():
            dataframe[f"%-{col}"] = feats[col].to_numpy()
        return dataframe

    def feature_engineering_standard(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        dataframe["%-day_of_week"] = dataframe["date"].dt.dayofweek
        dataframe["%-hour_of_day"] = dataframe["date"].dt.hour
        return dataframe

    def set_freqai_targets(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        """V1 hedefi: future_return(h) >= MIN_RETURN  ->  'up', aksi 'down'."""
        h = int(self.freqai_info["feature_parameters"]["label_period_candles"])
        future_return = dataframe["close"].shift(-h) / dataframe["close"] - 1
        dataframe["&-trend"] = np.where(future_return >= MIN_RETURN, "up", "down")
        return dataframe

    # ------------------------------------------------------------------ #
    # Strategy
    # ------------------------------------------------------------------ #

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = self.freqai.start(dataframe, metadata, self)
        # Giris trend filtresi icin duz (model'e verilmeyen) EMA kolonlari.
        feats = add_indicators(dataframe)
        dataframe["ema20"] = feats["ema20"].to_numpy()
        dataframe["ema50"] = feats["ema50"].to_numpy()
        return dataframe

    # ------------------------------------------------------------------ #
    # Gunluk kayip kapisi
    # ------------------------------------------------------------------ #

    def _starting_capital(self) -> float:
        """Backtest'te dry_run_wallet; canlida ilk bakiyeye en iyi tahmin."""
        w = self.config.get("dry_run_wallet")
        if w:
            return float(w)
        try:
            return float(self.wallets.get_total_stake_amount())  # yaklasik
        except Exception:  # noqa: BLE001
            return float(self.config.get("stake_amount", 1000)) * max(
                int(self.config.get("max_open_trades", 1)), 1
            )

    def _today_realized_pnl(self, now: datetime) -> float:
        """Bugun (UTC) kapanan trade'lerin toplam realize PnL'i (mutlak)."""
        today = now.astimezone(timezone.utc).date()
        total = 0.0
        try:
            closed = Trade.get_trades_proxy(is_open=False)
        except Exception:  # noqa: BLE001
            return 0.0
        for t in closed:
            cd = getattr(t, "close_date", None)
            if cd is None:
                continue
            if cd.tzinfo is None:
                cd = cd.replace(tzinfo=timezone.utc)
            if cd.astimezone(timezone.utc).date() == today:
                total += float(t.close_profit_abs or 0.0)
        return total

    def confirm_trade_entry(
        self, pair: str, order_type: str, amount: float, rate: float,
        time_in_force: str, current_time: datetime, entry_tag, side: str, **kwargs
    ) -> bool:
        limit = -abs(self.max_daily_loss_pct) * self._starting_capital()
        day_pnl = self._today_realized_pnl(current_time)
        if day_pnl <= limit:
            return False  # gunluk kayip limiti — bugun yeni giris yok
        return True

    def custom_exit(
        self, pair: str, trade, current_time, current_rate: float,
        current_profit: float, **kwargs
    ) -> str | None:
        """Zaman-stop: modelin 'down' demedigi ama uzun suredir zararda olan
        pozisyonlari kes. Sert -%20 stop'a dusen 19 felaket islemi hedefler,
        kazananlara dokunmaz (onlar ya kârda ya kisa omurlu)."""
        age = (current_time - trade.open_date_utc).total_seconds() / 3600 / 4
        if age >= self.time_stop_candles.value and current_profit <= self.time_stop_loss.value:
            return "time_stop"
        return None

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        up_proba = df["up"] if "up" in df.columns else 0.0
        # Trend filtresi: modelin dusus trendine alim yapmasini engelle.
        # OOS'ta kayip, modelin yanildigi girislerin duse duse time_stop'a
        # gitmesinden geliyordu — bunlarin cogu EMA20<EMA50 rejiminde.
        df.loc[
            (
                (df["do_predict"] == 1)
                & (df["&-trend"] == "up")
                & (up_proba >= self.buy_proba.value)
                & (df["ema20"] > df["ema50"])
                & (df["volume"] > 0)
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "freqai_up_trend")
        return df

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df.loc[
            (
                (df["do_predict"] == 1)
                & (df["&-trend"] == "down")
                & (df["volume"] > 0)
            ),
            ["exit_long", "exit_tag"],
        ] = (1, "freqai_down")
        return df
