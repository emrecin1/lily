"""Model evaluation on the held-out TEST split (never used in training).

Also reports trading-oriented metrics derived from test-set model signals.
"""

import json

import joblib
import numpy as np

from src.config import Config
from src.logging_config import get_logger
from src.ml.dataset import make_dataset
from src.ml.metrics import classification_report, probability_distribution


logger = get_logger("ml.evaluate")


def load_model(cfg: Config):
    """Load the persisted model and its metadata."""
    model_path = cfg.data.models_dir / "model.joblib"
    meta_path = cfg.data.models_dir / "model_metadata.json"
    if not model_path.exists():
        raise FileNotFoundError(
            f"No model found at {model_path}. Run `python main.py train` first."
        )
    model = joblib.load(model_path)
    metadata = {}
    if meta_path.exists():
        with open(meta_path) as f:
            metadata = json.load(f)
    return model, metadata


def evaluate_model(cfg: Config, dataset=None, threshold: float | None = None):
    """Evaluate the trained model on the TEST split.

    Args:
        cfg: Application configuration.
        dataset: Optional precomputed DatasetSplits.
        threshold: Decision threshold. Defaults to cfg.trading.ai_threshold.

    Returns:
        dict of evaluation results including classification metrics and a
        trading-oriented summary. The results are also written to
        ``models/evaluation.json``.
    """
    model, metadata = load_model(cfg)

    splits = dataset or make_dataset(cfg)
    threshold = threshold if threshold is not None else cfg.trading.ai_threshold

    evaluations = {}

    for name in ["train", "val", "test"]:
        X = getattr(splits, f"X_{name}")
        y = getattr(splits, f"y_{name}")
        probs = model.predict_proba(X)[:, 1]
        report = classification_report(y, probs, threshold=threshold)
        evaluations[name] = {
            "n_samples": report["n_samples"],
            "accuracy": report["accuracy"],
            "precision": report["precision"],
            "recall": report["recall"],
            "f1": report["f1"],
            "roc_auc": report["roc_auc"],
            "confusion": {
                "tn": report["true_0_pred_0"],
                "fp": report["true_0_pred_1"],
                "fn": report["true_1_pred_0"],
                "tp": report["true_1_pred_1"],
            },
            "positive_rate": report["positive_rate"],
            "prob_distribution": probability_distribution(report["probabilities"]),
        }
        logger.info(
            "%s: acc=%.4f prec=%.4f rec=%.4f f1=%.4f auc=%.4f (n=%d)",
            name,
            report["accuracy"],
            report["precision"],
            report["recall"],
            report["f1"],
            report["roc_auc"],
            report["n_samples"],
        )

    # Trading-oriented view: binary accuracy on 'up >= threshold in window'
    # is NOT predictive, but we expose it for transparency.
    test = evaluations["test"]

    result = {
        "metadata": metadata,
        "threshold": threshold,
        "evaluations": evaluations,
        "test_summary": {
            "accuracy": test["accuracy"],
            "precision": test["precision"],
            "recall": test["recall"],
            "f1": test["f1"],
            "roc_auc": test["roc_auc"],
            "n_samples": test["n_samples"],
        },
    }

    eval_path = cfg.data.models_dir / "evaluation.json"
    with open(eval_path, "w") as f:
        json.dump(result, f, indent=2, default=_json_default)
    logger.info("Wrote evaluation to %s", eval_path)

    return result


def _json_default(o):
    """Handle numpy types when serializing to JSON."""
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)