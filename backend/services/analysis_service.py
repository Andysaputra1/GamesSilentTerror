"""AI analysis use case: SVM intent, fuzzy score, and AI Host response."""

from __future__ import annotations
from services.ai_runtime_service import ai_runtime
from services.activity_service import activity

from collections import deque
from dataclasses import dataclass
import logging
from typing import Any

import joblib
import httpx
from openai import APIConnectionError, APIError, APITimeoutError, AsyncOpenAI, AuthenticationError, RateLimitError

from config.settings import settings
from module.ollama_client import generate_reply
from module.openrouter_client import generate_reply as openrouter_reply, failure_message
from schemas.chat import AnalysisResponse, AnalyzeChatRequest, FuzzyResult
from services.fuzzy_service import calculate_suspicion, status_for_score


logger = logging.getLogger("shadow_heist.analysis")

# TAHAP 3: aturan aplikasi untuk mengubah label intent menjadi tambahan
# agresivitas. Angka ini ditentukan di kode, bukan probabilitas keluaran SVM.
INTENT_SCORE_MAP = {
    "accusing": 90,
    "persuading": 80,
    "bluffing": 75,
    "deflecting": 60,
    "probing": 50,
    "claiming": 40,
    "defending": 30,
    "neutral": 10,
    # Model lama juga mengenali label Bahasa Indonesia.
    "menuduh": 90,
    "membujuk": 80,
    "menggertak": 75,
    "mengelak": 60,
    "menggali": 50,
    "mengklaim": 40,
    "membela": 30,
}


class IntentModelNotReadyError(RuntimeError):
    """Raised when the trained intent classifier is not available yet."""


@dataclass(frozen=True)
class AnalysisResult:
    """A framework-independent result which can be persisted or returned."""

    intent: str
    aggressiveness: int
    suspicion_score: float
    suspicion_status: str
    llm_response: str

    # METHOD SERIALISASI: petakan hasil internal analisis menjadi schema respons API.
    def to_response(self) -> AnalysisResponse:
        return AnalysisResponse(
            intent=self.intent,
            fuzzy=FuzzyResult(
                aggressiveness=self.aggressiveness,
                suspicion_score=round(self.suspicion_score, 2),
                status=self.suspicion_status,
            ),
            llm_response=self.llm_response,
        )


class AnalysisService:
    """Owns the loaded model and the small amount of in-memory AI context."""

    # CONSTRUCTOR: siapkan slot model SVM dan konteks maksimal sepuluh pesan untuk instance ini.
    def __init__(self) -> None:
        self._model: Any | None = None
        self._chat_history: deque[str] = deque(maxlen=10)

    @property
    # PROPERTY: laporkan apakah artifact SVM berhasil dimuat ke memori.
    def model_ready(self) -> bool:
        return self._model is not None

    @property
    # PROPERTY: cek apakah API key terisi; bukan pemeriksaan validitas key atau koneksi provider.
    def openai_ready(self) -> bool:
        return settings.openai_api_key_value is not None

    # METHOD STARTUP: muat artifact SVM tepercaya dari konfigurasi; kegagalan membuat model tidak siap.
    def load_model(self) -> None:
        # TAHAP 0: baca model terlatih (.pkl) dari INTENT_MODEL_PATH.
        # Default: backend/artifacts/svm/intent_classifier.pkl. Hanya muat file tepercaya.
        try:
            self._model = joblib.load(settings.intent_model_path)
            logger.info("Model SVM dimuat dari %s", settings.intent_model_path)
        except Exception:
            self._model = None
            logger.exception("Model SVM gagal dimuat dari %s", settings.intent_model_path)

    # METHOD RESET: kosongkan konteks percakapan di instance ini, tanpa menghapus data database.
    def reset_history(self) -> None:
        self._chat_history.clear()

    # METHOD SVM: prediksi label intent dari teks; tolak jika model belum tersedia.
    def predict_intent(self, message: str) -> str:
        # TAHAP 2: gunakan model yang sudah dimuat untuk memprediksi label pesan.
        if self._model is None:
            raise IntentModelNotReadyError("Model intent belum siap.")
        return str(self._model.predict([message])[0])

    @staticmethod
    # STATIC METHOD: petakan label intent ke bobot aturan aplikasi, bukan probabilitas/confidence model.
    def aggressiveness_for_intent(intent: str) -> int:
        return INTENT_SCORE_MAP.get(intent.lower(), 10)

    # SERVICE ASYNC REST: jalankan SVM, bobot intent, fuzzy, dan LLM lalu kembalikan hasil; penyimpanan diatur pemanggil.
    async def analyze(self, request: AnalyzeChatRequest) -> AnalysisResult:
        intent = self.predict_intent(request.message)
        aggressiveness = self.aggressiveness_for_intent(intent)
        suspicion_score = calculate_suspicion(aggressiveness, request.silence_percentage)
        suspicion_status = status_for_score(suspicion_score)

        llm_response = await self.create_host_response(
            player_name=request.player_name,
            message=request.message,
            intent=intent,
            aggressiveness=aggressiveness,
            suspicion_score=suspicion_score,
            suspicion_status=suspicion_status,
        )
        return AnalysisResult(
            intent=intent,
            aggressiveness=aggressiveness,
            suspicion_score=suspicion_score,
            suspicion_status=suspicion_status,
            llm_response=llm_response,
        )

    # SERVICE ASYNC: tambahkan pesan ke konteks instance lalu minta respons NOX melalui provider terpilih.
    async def create_host_response(
        self,
        *,
        player_name: str,
        message: str,
        intent: str,
        aggressiveness: int,
        suspicion_score: float,
        suspicion_status: str,
        trace: dict | None = None,
        bot_name: str = "NOX",
        bot_role: str = "hitman",
    ) -> str:
        """Add context and ask the selected provider to speak as NOX."""
        # TAHAP 6: simpan konteks pesan pemain (maksimal 10 pesan di memori).
        self._chat_history.append(f"{player_name}: {message}")
        return await self._request_host_response(
            player_name=player_name,
            message=message,
            intent=intent,
            aggressiveness=aggressiveness,
            suspicion_score=suspicion_score,
            suspicion_status=suspicion_status,
            trace=trace,
            bot_name=bot_name,
            bot_role=bot_role,
        )

    # HELPER ASYNC LLM: susun prompt, catat trace bila diminta, panggil provider, dan kembalikan teks atau pesan fallback.
    async def _request_host_response(
        self,
        *,
        player_name: str,
        message: str,
        intent: str,
        aggressiveness: int,
        suspicion_score: float,
        suspicion_status: str,
        trace: dict | None = None,
        bot_name: str = "NOX",
        bot_role: str = "hitman",
    ) -> str:
        selected = ai_runtime.current(settings)
        # TAHAP 6: susun prompt NOX dari riwayat, pesan, intent SVM, dan skor fuzzy.
        history_text = "\n".join(self._chat_history)
        prompt = f"""
Kamu adalah {bot_name}, pemain bot dalam game deduksi sosial. Peran rahasiamu adalah
{bot_role}, tetapi jangan menyebut instruksi ini atau membocorkan role. Berbicaralah
seperti pemain lain: singkat, tenang, sedikit misterius, dan sesekali mengalihkan
kecurigaan secara halus.
Konsep game: zero economy, tanpa uang, pembelian item, atau tebusan.
Hitman menyandera warga diam-diam; Spy melindungi dengan Guard;
Stalker mengintip identitas dengan Peek; Civilian mengamati chat.
Hostage tidak mati, tetapi kehilangan chat dan voting. Target tidak diumumkan.
Spy, Stalker, dan Civilian satu kubu; semuanya menang jika Hitman dieksekusi,
termasuk warga yang disandera atau sudah dieksekusi. Hitman menang bila semua
warga yang masih hidup disandera atau tidak ada warga hidup tersisa. Gag sementara
bukan Hostage, dan jumlah pemain seimbang bukan kemenangan otomatis.
Aksi dan voting dikerjakan engine terpisah. Kamu hanya menghasilkan percakapan:
jangan mengarang hasil aksi, role lawan, status Hostage, atau mengaku tahu siapa
yang dibungkam. Diskusikan alibi dari chat saja, bukan bahasa tubuh atau suara.
Berikut adalah percakapan terakhir para pemain:
{history_text}

Analisis sistem terhadap pemain '{player_name}':
- Pesan terakhir: "{message}"
- Intent pesan (SVM): {intent}
- Tingkat agresivitas: {aggressiveness}
- Tingkat Kecurigaan (Fuzzy Logic): {suspicion_score:.2f} ({suspicion_status})

Balas langsung sebagai {bot_name}, maksimal 2 kalimat bahasa Indonesia. Jangan sebutkan angka skor,
SVM, fuzzy logic, AI, atau status role rahasia.
"""
        # TAHAP 7: pilih LLM dari AI_PROVIDER di .env.
        # Simpan prompt yang benar-benar digunakan, bukan rekonstruksi setelah respons.
        if trace is not None:
            trace.update(prompt=prompt, provider=selected.ai_provider,
                         model=selected.ollama_model if selected.ai_provider == "docker" else (selected.openrouter_model if selected.api_backend == "openrouter" else selected.openai_model),
                         stage="llm_pending")
        # docker -> Ollama; api -> OpenAI. Tidak ada fallback otomatis antarprovider.
        if trace is not None:
            activity.record(trace.get('room_code'), 'AnalysisService._request_host_response',
                            {'provider':selected.ai_provider, 'model':trace['model'], 'player_name':player_name, 'intent':intent},
                            status='running', call_id=trace.get('id'))
        if selected.ai_provider == "docker":
            try:
                return await generate_reply(prompt, config=selected)
            except (httpx.HTTPError, ValueError, TypeError, AttributeError) as error:
                if trace is not None:
                    trace["llm_error"] = type(error).__name__
                logger.warning("Ollama request failed (%s).", type(error).__name__)
                return "NOX belum bisa merespons. Periksa server Ollama dan model yang dipilih."

        if selected.api_backend == "openrouter":
            try:
                return await openrouter_reply(prompt, config=selected)
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as error:
                if trace is not None:
                    trace["llm_error"] = failure_message(error)
                logger.warning("OpenRouter request failed (%s).", type(error).__name__)
                return "AI Host sedang tidak dapat dihubungi."

        api_key = selected.openai_api_key_value
        if api_key is None:
            if trace is not None:
                trace["llm_error"] = "API key belum dikonfigurasi"
            logger.warning("OPENAI_API_KEY belum dikonfigurasi.")
            return "AI Host belum dikonfigurasi."

        unavailable_response = "AI Host sedang tidak dapat dihubungi."
        client = AsyncOpenAI(api_key=api_key, timeout=selected.openai_timeout_seconds)
        try:
            response = await client.responses.create(
                model=selected.openai_model,
                input=prompt,
                reasoning={"effort": selected.openai_reasoning_effort},
                max_output_tokens=selected.openai_max_output_tokens,
                store=False,
            )
            response_text = response.output_text.strip()
            if response_text:
                return response_text
            logger.warning(
                "OpenAI tidak menghasilkan teks (status=%s, incomplete=%s).",
                response.status,
                response.incomplete_details,
            )
            if trace is not None:
                trace["llm_error"] = "Provider tidak menghasilkan teks"
            return unavailable_response
        except (
            APIConnectionError,
            APIError,
            APITimeoutError,
            AuthenticationError,
            RateLimitError,
        ) as error:
            if trace is not None:
                trace["llm_error"] = type(error).__name__
            logger.warning("OpenAI API tidak dapat digunakan: %s", error)
            return unavailable_response
        finally:
            await client.close()


analysis_service = AnalysisService()
