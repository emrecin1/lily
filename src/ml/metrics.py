"""Shared performance metrics for model and trading evaluation.

Contains classification metrics (accuracy, precision, recall, F1, ROC-AUC,
confusion matrix, probability distribution) and trading metrics (returns,
drawdown, Sharpe, Sortino, profit factor, etc.).

These trading metrics are pure functions of an equity/pnl series and are
reused by both model evaluation and the backtesting engine.
"""

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- #
# Classification metrics
# --------------------------------------------------------------------------- #

def classification_report(y_true, y_pred_proba: np.ndarray, threshold: float = 0.5):
    """Compute classification metrics at a given decision threshold.

    Args:
        y_true: Ground-truth binary labels.
        y_pred_proba: Predicted positive-class probabilities.
        threshold: Probability threshold for the positive class.

    Returns:
        dict of accuracy, precision, recall, f1, roc_auc, confusion matrix
        counts, and the raw probability array.
    """
    from sklearn.metrics import (
        accuracy_score,
        confusion_matrix,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )

    y_true = np.asarray(y_true)
    probs = np.asarray(y_pred_proba)
    y_pred = (probs >= threshold).astype(int)

    labels = sorted(set(y_true) | set(y_pred))
    cm = confusion_matrix(y_true, y_pred, labels=labels)
    tn = int(cm[0, 0]) if cm.shape[0] > 1 else int(y_true.sum() == 0)
    fp = int(cm[0, 1]) if cm.shape[0] > 1 and cm.shape[1] > 1 else 0
    fn = int(cm[1, 0]) if cm.shape[0] > 1 and cm.shape[1] > 1 else 0
    tp = int(cm[1, 1]) if cm.shape[0] > 1 and cm.shape[1] > 1 else int(y_true.sum())
    if len(labels) == 1:
        if labels[0] == 0:
            tn = len(y_true)
            tp, fp, fn = 0, 0, 0
        else:
            tp = len(y_true)
            tn, fp, fn = 0, 0, 0

    has_two_classes = len(np.unique(y_true)) > 1
    roc_auc = float(roc_auc_score(y_true, probs)) if has_two_classes else float("nan")

    return {
        "threshold": threshold,
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "roc_auc": roc_auc,
        "true_0_pred_0": tn,
        "true_0_pred_1": fp,
        "true_1_pred_0": fn,
        "true_1_pred_1": tp,
        "n_samples": int(len(y_true)),
        "positive_rate": float(np.mean(y_true)),
        "probabilities": probs,
    }


def probability_distribution(probs: np.ndarray, bins: int = 10):
    """Histogram of predicted probabilities across equally sized bins."""
    probs = np.asarray(probs)
    counts, edges = np.histogram(probs, bins=bins, range=(0.0, 1.0))
    return {
        "bins": int(bins),
        "edges": edges.tolist(),
        "counts": counts.tolist(),
    }


# --------------------------------------------------------------------------- #
# Trading metrics (pure functions)
# --------------------------------------------------------------------------- #

def max_drawdown(equity_curve: np.ndarray) -> float:
    """Maximum peak-to-trough drawdown of an equity curve.

    Returns a positive fraction (0.2 = 20% drawdown).
    """
    eq = np.asarray(equity_curve, dtype=float)
    if len(eq) == 0:
        return 0.0
    running_max = np.maximum.accumulate(eq)
    drawdown = 1.0 - eq / np.where(running_max == 0, np.nan, running_max)
    return float(np.nanmax(drawdown)) if np.isfinite(drawdown).any() else 0.0


def sharpe_ratio(returns: np.ndarray, rf: float = 0.0) -> float:
    """Annualized Sharpe ratio from per-period log/simple returns."""
    r = np.asarray(returns, dtype=float)
    if len(r) < 2:
        return 0.0
    std = np.std(r)
    if std == 0 or not np.isfinite(std):
        return 0.0
    # Annualized assuming hourly data (8760 periods/year); the caller can
    # override via a periodicity argument if a different timeframe is used.
    ppy = 8760.0
    return float((np.mean(r) - rf) / std * np.sqrt(ppy))


def sortino_ratio(returns: np.ndarray, rf: float = 0.0) -> float:
    """Annualized Sortino ratio (downside deviation only)."""
    r = np.asarray(returns, dtype=float)
    if len(r) < 2:
        return 0.0
    downside = r[r < 0]
    if len(downside) == 0:
        return 0.0
    dd = np.std(downside)
    if dd == 0 or not np.isfinite(dd):
        return 0.0
    ppy = 8760.0
    return float((np.mean(r) - rf) / dd * np.sqrt(ppy))


def largest_losing_streak(trade_pnls: np.ndarray) -> int:
    """Longest run of consecutive losing trades."""
    pnls = np.asarray(trade_pnls, dtype=float)
    max_streak = 0
    current = 0
    for p in pnls:
        if p < 0:
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0
    return int(max_streak)


def trade_statistics(trade_pnls: np.ndarray):
    """Summary stats over a series of trade PnLs (in units)."""
    pnls = np.asarray(trade_pnls, dtype=float)
    if len(pnls) == 0:
        return {
            "num_trades": 0,
            "win_rate": 0.0,
            "average_pnl": 0.0,
            "average_win": 0.0,
            "average_loss": 0.0,
            "profit_factor": 0.0,
            "total_pnl": 0.0,
            "largest_losing_streak": 0,
        }

    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    gross_profit = wins.sum()
    gross_loss = abs(losses.sum())

    return {
        "num_trades": int(len(pnls)),
        "win_rate": float((pnls > 0).mean()),
        "average_pnl": float(pnls.mean()),
        "average_win": float(wins.mean()) if len(wins) else 0.0,
        "average_loss": float(losses.mean()) if len(losses) else 0.0,
        "profit_factor": float(gross_profit / gross_loss) if gross_loss > 0 else float("inf"),
        "total_pnl": float(pnls.sum()),
        "largest_losing_streak": largest_losing_streak(pnls),
    }


def total_return_from_equity(initial: float, final: float) -> float:
    """Fractional total return from capital values."""
    if initial <= 0:
        return 0.0
    return float((final / initial) - 1.0)