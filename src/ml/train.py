"""Model training (XGBoost Classifier).

Trains on the chronological TRAIN split only. The validation split is used
for early stopping (fit progress), and the TEST split is NEVER touched during
training. Results and full metadata are persisted under ``models/``.
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import joblib
import xgboost as xgb

from src.config import Config
from src.logging_config import get_logger
from src.ml.dataset import feature_columns, make_dataset
from src.ml.metrics import classification_report, probability_distribution


logger = get_logger("ml.train")


@dataclass
class ModelMetadata:
    """Serializable metadata describing a trained model."""

    model_type: str
    training_start: str
    training_end: str
    validation_start: str
    validation_end: str
    features: list[str]
    target_definition: str
    model_params: dict
    validation_metrics: dict
    training_timestamp: str
    horizon: int
    min_return: float


def build_xgb_params(cfg: Config) -> dict:
    """Construct XGBClassifier parameters from configuration."""
    return {
        "n_estimators": cfg.ml.n_estimators,
        "max_depth": cfg.ml.max_depth,
        "learning_rate": cfg.ml.learning_rate,
        "subsample": cfg.ml.subsample,
        "colsample_bytree": cfg.ml.colsample_bytree,
        "objective": cfg.ml.objective,
        "eval_metric": cfg.ml.eval_metric,
        "random_state": cfg.ml.random_state,
        "n_jobs": -1,
    }


def train_model(cfg: Config, dataset=None):
    """Train the XGBoost classifier on the chronological train split.

    Args:
        cfg: Application configuration.
        dataset: Optional precomputed DatasetSplits. If None, it is built
            from the processed features (via make_dataset).

    Returns:
        A tuple (model, metadata_dict, splits) for reuse in tests. The model
        is also persisted to ``models/``.
    """
    splits = dataset or make_dataset(cfg)

    # Train ONLY on the training split. Validation is used solely for early
    # stopping / tracking; test data is never passed to fit.
    X_train, y_train = splits.X_train, splits.y_train
    X_val, y_val = splits.X_val, splits.y_val

    if X_train.empty:
        raise RuntimeError("Training split is empty — cannot train.")

    params = build_xgb_params(cfg)

    model = xgb.XGBClassifier(**params)

    # Validation set is used ONLY for early stopping, not to fit weights.
    if not X_val.empty:
        model.fit(
            X_train,
            y_train,
            eval_set=[(X_val, y_val)],
            verbose=False,
        )
    else:
        model.fit(X_train, y_train)

    # Compute validation metrics (validation set — not test).
    val_metrics = {}
    if not X_val.empty:
        val_probs = model.predict_proba(X_val)[:, 1]
        report = classification_report(y_val, val_probs, threshold=cfg.trading.ai_threshold)
        val_metrics = {
            "accuracy": report["accuracy"],
            "precision": report["precision"],
            "recall": report["recall"],
            "f1": report["f1"],
            "roc_auc": report["roc_auc"],
            "prob_distribution": probability_distribution(report["probabilities"]),
        }

    model_params = {k: v for k, v in params.items() if isinstance(v, (int, float, str))}

    metadata = ModelMetadata(
        model_type=cfg.ml.model_type,
        training_start=cfg.data.train_start,
        training_end=cfg.data.train_end,
        validation_start=cfg.data.val_start,
        validation_end=cfg.data.val_end,
        features=feature_columns(),
        target_definition=(
            f"future_return_{cfg.ml.target_horizon}h = close.shift(-{cfg.ml.target_horizon})/close - 1; "
            f"target = (future_return >= {cfg.ml.target_return}).astype(int)"
        ),
        model_params=model_params,
        validation_metrics=val_metrics,
        training_timestamp=datetime.now(timezone.utc).isoformat(),
        horizon=cfg.ml.target_horizon,
        min_return=cfg.ml.target_return,
    )

    # Persist model + metadata.
    cfg.data.models_dir.mkdir(parents=True, exist_ok=True)
    model_path = cfg.data.models_dir / "model.joblib"
    meta_path = cfg.data.models_dir / "model_metadata.json"

    joblib.dump(model, model_path)
    with open(meta_path, "w") as f:
        json.dump(asdict(metadata), f, indent=2)

    logger.info(
        "Trained %s on %d samples. Model -> %s",
        cfg.ml.model_type,
        len(X_train),
        model_path,
    )
    if val_metrics:
        logger.info("Validation roc_auc=%.4f f1=%.4f", val_metrics["roc_auc"], val_metrics["f1"])

    return model, asdict(metadata), splits