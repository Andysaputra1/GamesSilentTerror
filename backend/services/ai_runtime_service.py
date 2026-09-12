"""Override provider satu proses. .env tetap sumber default setelah restart."""
from threading import RLock
from config.settings import settings


class AIRuntimeService:
    def __init__(self):
        self.lock = RLock()
        self.override = None

    # Snapshot per request: pergantian panel tidak mengubah request yang sudah berjalan.
    def current(self, base=None):
        base = settings if base is None else base
        with self.lock:
            return base.model_copy(update=self.override) if self.override else base

    def select(self, provider, model):
        if provider not in {'api', 'docker'} or model not in {'8', '14'}:
            raise ValueError('Provider/model tidak valid.')
        with self.lock:
            self.override = {'ai_provider': provider, 'ollama_model': f'qwen3:{model}b'}

    def reset(self):
        with self.lock:
            self.override = None


ai_runtime = AIRuntimeService()
