"""Chat and AI analysis REST controllers."""

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import require_authenticated_user
from schemas.chat import AnalyzeChatRequest, LegacyAIChatRequest, LegacyGameChatRequest
from services.analysis_service import IntentModelNotReadyError, analysis_service
from services.auth_service import AuthenticatedUser
from services.persistence_service import PersistenceError, persistence_service


router = APIRouter(prefix="/api", tags=["game"])


async def _analyze_and_store(request: AnalyzeChatRequest):
    try:
        result = await analysis_service.analyze(request)
    except IntentModelNotReadyError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    try:
        persistence_service.record_analysis(
            player_name=request.player_name,
            message=request.message,
            result=result,
        )
    except PersistenceError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return result


@router.post("/analyze")
async def analyze_chat(
    request: AnalyzeChatRequest,
    user: AuthenticatedUser = Depends(require_authenticated_user),
) -> dict[str, object]:
    """Analyze one message, save it and its AI analysis to MySQL."""
    authenticated_request = request.model_copy(update={"player_name": user.username})
    return _analyze_response(await _analyze_and_store(authenticated_request))


@router.post("/game/chat")
async def game_chat(
    request: LegacyGameChatRequest,
    user: AuthenticatedUser = Depends(require_authenticated_user),
) -> dict[str, object]:
    """Compatibility endpoint for the prior Express API."""
    analysis = await _analyze_and_store(
        AnalyzeChatRequest(
            player_name=user.username,
            message=request.message,
            silence_percentage=50,
        )
    )
    response = _analyze_response(analysis)
    return {
        "success": True,
        "sender": "AI_BOT",
        "reply": response["llm_response"],
        "analysis": response,
    }


@router.post("/ai-chat")
async def ai_chat(
    request: LegacyAIChatRequest,
    user: AuthenticatedUser = Depends(require_authenticated_user),
) -> dict[str, str]:
    """Compatibility endpoint for existing old Node-to-Python callers."""
    analysis = await _analyze_and_store(
        AnalyzeChatRequest(
            player_name=user.username,
            message=request.player_message,
            silence_percentage=50,
        )
    )
    return {"reply": analysis.llm_response}


@router.delete("/reset")
async def reset_history(
    _: AuthenticatedUser = Depends(require_authenticated_user),
) -> dict[str, str]:
    """Clear only temporary LLM context; persisted audit rows remain intact."""
    analysis_service.reset_history()
    return {"message": "Histori chat game berhasil di-reset."}


def _analyze_response(result) -> dict[str, object]:
    return result.to_response().model_dump()
