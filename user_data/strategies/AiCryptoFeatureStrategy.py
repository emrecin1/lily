"""
AiCryptoFeatureStrategy — V1 feature seti + ayni EMA/RSI kural mantigi.

Amac (docs/MIGRATION.md Asama 2):
  1. V1'in `src/features/indicators.add_indicators()` fonksiyonunu DOGRUDAN
     cagirarak 25 feature'i Freqtrade tarafinda BIREBIR ayni uretmek
     (talib degil, V1 ile ayni `ta` kutuphanesi -> numerik parity).
  2. Giris/cikis kurali AiCryptoRuleStrategy ile ozdes (yalnizca ema20/ema50/rsi
     kullanir) -> iki strateji ayni islemleri uretmeli; uretmezse fark
     tamamen talib<->ta EMA/RSI farkindan gelir ve olculur.

FreqAI'ye (Asama 3) gecince bu 25 feature `feature_engineering_*` callback'lerine
taşınır; simdilik populate_indicators icinde tek blok.
"""

from __future__ import annotations

import sys
from pathlib import Path

from pandas import DataFrame

from freqtrade.strategy import IStrategy, IntParameter

# --- V1 feature fonksiyonunu import et (tek dogruluk kaynagi) --------------
# user_data/strategies/AiCryptoFeatureStrategy.py -> repo koku 2 seviye yukarida.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.features.indicators import FeatureColumns as FC  # noqa: E402
from src.features.indicators import add_indicators  # noqa: E402

# ml.dataset.feature_columns() 25 model feature'ini sirali dondurur.
from src.ml.dataset import feature_columns as v1_feature_columns  # noqa: E402


class AiCryptoFeatureStrategy(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "4h"
    can_short = False

    minimal_roi = {"0": 0.15}
    stoploss = -0.08
    trailing_stop = True
    trailing_stop_positive = 0.20
    trailing_stop_positive_offset = 0.22
    trailing_only_offset_is_reached = True

    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    startup_candle_count: int = 400  # EMA200 warmup (parity notlari: docs/parity-notes.md)

    buy_rsi_max = IntParameter(20, 60, default=45, space="buy", optimize=True)
    sell_rsi_max = IntParameter(55, 90, default=70, space="sell", optimize=True)

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
            {
                "method": "LowProfitPairs",
                "lookback_period_candles": 24,
                "trade_limit": 2,
                "stop_duration_candles": 12,
                "required_profit": 0.0,
            },
        ]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # V1 ile BIREBIR ayni hesap: ayni fonksiyon, ayni `ta` kutuphanesi.
        # add_indicators() OHLCV kolonlarini bekler (Freqtrade df'sinde mevcut),
        # 25 feature + ema100/ema200 vb. ekler, satir sayisini/index'i korur.
        out = add_indicators(dataframe)

        # Kolon adlarini FeatureColumns uzerinden dogrula (drift kontrolu).
        expected = set(v1_feature_columns())
        missing = expected - set(out.columns)
        if missing:
            raise RuntimeError(f"add_indicators eksik feature uretti: {sorted(missing)}")
        return out

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe[FC.EMA20] > dataframe[FC.EMA50])
                & (dataframe[FC.RSI] < self.buy_rsi_max.value)
                & (dataframe["volume"] > 0)
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "trend_up_rsi_ok")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (
                    (dataframe[FC.EMA20] < dataframe[FC.EMA50])
                    | (dataframe[FC.RSI] > self.sell_rsi_max.value)
                )
                & (dataframe["volume"] > 0)
            ),
            ["exit_long", "exit_tag"],
        ] = (1, "trend_down_or_rsi_high")
        return dataframe
