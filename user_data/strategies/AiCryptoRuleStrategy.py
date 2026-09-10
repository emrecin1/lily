"""
AiCryptoRuleStrategy — deterministik Trend + RSI (EMA20/EMA50 + RSI14).

V1'deki src/rules/signal.py mantiginin Freqtrade IStrategy (v3) portu.
ML YOK. Amac: dry-run boru hattini (veri -> indikator -> sinyal -> risk ->
execution -> FreqUI/Telegram) ucdan uca dogrulamak.  Bkz. docs/MIGRATION.md Asama 1.

Kural:
    Giris (long)  : EMA_fast > EMA_slow  VE  RSI < rsi_buy_max
    Cikis (long)  : EMA_fast < EMA_slow  VEYA RSI > rsi_sell_max
    ayrica        : minimal_roi (+%15 TP), stoploss (-%8), trailing (%20 geri verme)

Parametreler hyperopt'a acik (Asama 2):
    freqtrade hyperopt --strategy AiCryptoRuleStrategy \
        --hyperopt-loss SharpeHyperOptLoss --spaces buy sell roi stoploss trailing
"""

from __future__ import annotations

import talib.abstract as ta
from pandas import DataFrame

from freqtrade.strategy import IStrategy, IntParameter


class AiCryptoRuleStrategy(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "4h"
    can_short = False

    # --- Cikis muhasebesi (V1 RulesConfig varsayilanlari) --------------------
    # +%15 take-profit (zamana bagli kademe yok, sabit hedef).
    minimal_roi = {"0": 0.15}
    # -%8 sabit stop-loss.
    stoploss = -0.08
    # Trailing: kar moduna girince tepe fiyatin %20 altinda kapat.
    trailing_stop = True
    trailing_stop_positive = 0.20
    trailing_stop_positive_offset = 0.22
    trailing_only_offset_is_reached = True

    # Sinyal yalnizca mum KAPANISINDA uretilir (tekrarlanabilirlik).
    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    # EMA200 isinmasi + guvenli pay.
    startup_candle_count: int = 240

    # --- Hyperopt parametreleri --------------------------------------------
    buy_rsi_max = IntParameter(20, 60, default=45, space="buy", optimize=True)
    sell_rsi_max = IntParameter(55, 90, default=70, space="sell", optimize=True)
    ema_fast_period = IntParameter(10, 30, default=20, space="buy", optimize=False)
    ema_slow_period = IntParameter(40, 100, default=50, space="buy", optimize=False)

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    # --- Risk korumalari --------------------------------------------------
    # Freqtrade yeni surumlerinde 'protections' config'de DEGIL burada tanimlanir.
    # Degerler: docs/ARCHITECTURE.md §6.
    @property
    def protections(self):
        return [
            {
                "method": "CooldownPeriod",
                "stop_duration_candles": 2,
            },
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
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=int(self.ema_fast_period.value))
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=int(self.ema_slow_period.value))
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["ema_fast"] > dataframe["ema_slow"])
                & (dataframe["rsi"] < self.buy_rsi_max.value)
                & (dataframe["volume"] > 0)
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "trend_up_rsi_ok")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (
                    (dataframe["ema_fast"] < dataframe["ema_slow"])
                    | (dataframe["rsi"] > self.sell_rsi_max.value)
                )
                & (dataframe["volume"] > 0)
            ),
            ["exit_long", "exit_tag"],
        ] = (1, "trend_down_or_rsi_high")
        return dataframe
