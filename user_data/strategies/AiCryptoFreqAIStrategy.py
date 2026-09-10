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
from pathlib import Path

import numpy as np
from pandas import DataFrame

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
        return dataframe

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
        df.loc[
            (
                (df["do_predict"] == 1)
                & (df["&-trend"] == "up")
                & (up_proba >= self.buy_proba.value)
                & (df["volume"] > 0)
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "freqai_up")
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
