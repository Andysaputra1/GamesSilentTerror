"""Model SVM intent: hanya NLU cadangan otak NPC bila IndoBERT tidak tersedia (lihat NLUCadangan)."""

from __future__ import annotations

import logging
from typing import Any

import joblib

from config.settings import settings

logger = logging.getLogger("shadow_heist.analysis")


class IntentModelNotReadyError(RuntimeError):
    """Raised when the trained intent classifier is not available yet."""


class AnalysisService:
    """Owns the loaded SVM intent model."""

    # CONSTRUCTOR: siapkan slot model SVM untuk instance ini.
    def __init__(self) -> None:
        self._model: Any | None = None

    @property
    # PROPERTY: laporkan apakah artifact SVM berhasil dimuat ke memori.
    def model_ready(self) -> bool:
        return self._model is not None

    # METHOD STARTUP: muat artifact SVM tepercaya dari konfigurasi; kegagalan membuat model tidak siap.
    def load_model(self) -> None:
        # Default: backend/artifacts/svm/intent_classifier.pkl. Hanya muat file tepercaya.
        try:
            self._model = joblib.load(settings.intent_model_path)
            logger.info("Model SVM dimuat dari %s", settings.intent_model_path)
        except Exception:
            self._model = None
            logger.exception("Model SVM gagal dimuat dari %s", settings.intent_model_path)

    # METHOD SVM: prediksi label intent dari teks; tolak jika model belum tersedia.
    def predict_intent(self, message: str) -> str:
        if self._model is None:
            raise IntentModelNotReadyError("Model intent belum siap.")
        return str(self._model.predict([message])[0])


analysis_service = AnalysisService()
