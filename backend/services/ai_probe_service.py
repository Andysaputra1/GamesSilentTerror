"""Isolated game scenario: real classifier/provider, no mutation of player matches."""

import asyncio
from time import perf_counter
from uuid import uuid4
from datetime import datetime, timezone

from services.ai_runtime_service import ai_runtime
from services.analysis_service import analysis_service, IntentModelNotReadyError
from services.ai_diagnostics import capture_exchange, measure
from services.fuzzy_service import calculate_suspicion, status_for_score
from services.match_engine import Match
from services.npc_service import npc_context, decision_prompt, request_decision
from module.openrouter_client import failure_message


async def run_probe(message, scenario):
    started = perf_counter()
    config = ai_runtime.current()
    trace = {
        "id": uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scenario": scenario,
        "message": message,
        "stage": "preparing",
        "active": False,
        "valid_decision": False,
        "timings": {},
        "provider": config.ai_provider,
        "model": (
            config.ollama_model
            if config.ai_provider == "docker"
            else (
                config.openrouter_model
                if config.api_backend == "openrouter"
                else config.openai_model
            )
        ),
        "request": None,
        "response": None,
        "output": None,
        "note": "Skenario terisolasi; tidak mengirim chat atau menjalankan aksi di room pemain. SVM/fuzzy adalah analisis pendamping, bukan pengetahuan role NPC.",
    }
    try:
        with measure(trace, "analysis_ms"):
            try:
                intent = analysis_service.predict_intent(message)
                weight = analysis_service.aggressiveness_for_intent(intent)
                score = calculate_suspicion(weight, 20)
                trace["analysis"] = {
                    "status": "complete",
                    "intent": intent,
                    "aggressiveness": weight,
                    "silence_percentage": 20,
                    "suspicion_score": round(score, 2),
                    "suspicion_status": status_for_score(score),
                }
            except IntentModelNotReadyError:
                trace["analysis"] = {
                    "status": "skipped",
                    "reason": "Model SVM belum dimuat; pengujian keputusan NPC tetap berjalan.",
                }
        with measure(trace, "prompt_ms"):
            match = Match(["Pemain_A", "Pemain_B", "Pemain_C", "Pemain_D", "Pemain_E"], ["NOX"])
            for name, role in zip(
                match.players, ["hitman", "stalker", "civilian", "civilian", "civilian", "spy"]
            ):
                match.players[name].role = role
            match.phase = {"discussion": "day", "vote": "tribunal", "night": "night"}[scenario]
            match.add_message("Pemain_A", message)
            context = npc_context(match, "NOX")
            trace["context"] = context
            trace["prompt"] = decision_prompt(context)
        trace["stage"] = "llm_pending"
        with capture_exchange(trace):
            decision = await asyncio.wait_for(request_decision(trace["prompt"], config), timeout=35)
        trace["active"] = True
        trace["output"] = decision.model_dump()
        with measure(trace, "validation_ms"):
            if decision.action == "wait":
                legal = decision.target is None
            else:
                legal = decision.target in context["legal_actions"].get(decision.action, [])
            legal = legal and (context["me"]["can_chat"] or not decision.message.strip())
            trace["valid_decision"] = legal
        trace["stage"] = "complete" if legal else "invalid_decision"
        trace["message_status"] = (
            "AI merespons dan keputusan valid."
            if legal
            else "AI merespons, tetapi keputusan tidak sesuai aturan skenario."
        )
    except Exception as error:
        response = trace.get("response") or {}
        trace["active"] = bool(response.get("body", {}).get("output"))
        trace["stage"] = "invalid_response" if trace["active"] else "failed"
        trace["error_type"] = type(error).__name__
        trace["message_status"] = (
            "Provider merespons, tetapi output bukan JSON keputusan yang valid."
            if trace["active"]
            else failure_message(error)
        )
    finally:
        trace["duration_ms"] = round((perf_counter() - started) * 1000, 2)
        response = trace.get("response") or {}
        trace["provider_reachable"] = 200 <= response.get("status_code", 0) < 300
        if not trace["active"] and trace["provider_reachable"]:
            trace["message_status"] = (
                "Provider terhubung, tetapi output kosong karena batas token tercapai."
                if response.get("body", {}).get("finish_reason") == "length"
                else "Provider terhubung, tetapi belum menghasilkan teks yang dapat digunakan."
            )
    return trace
