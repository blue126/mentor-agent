"""Chat completions router — OpenAI-compatible endpoint."""

import time

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import settings
from app.schemas.chat import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    MessageContent,
    ResponseChoice,
    UsageInfo,
)
from app.services import agent_service

router = APIRouter()


def _model_payload(model_id: str) -> dict[str, str | int]:
    return {
        "id": model_id,
        "object": "model",
        "created": int(time.time()),
        "owned_by": "mentor-agent-service",
    }


@router.get("/v1/models")
async def list_models() -> JSONResponse:
    model_id = settings.litellm_model
    return JSONResponse(content={"object": "list", "data": [_model_payload(model_id)]})


@router.get("/v1/models/{model_id}")
async def get_model(model_id: str) -> JSONResponse:
    if model_id != settings.litellm_model:
        return JSONResponse(status_code=404, content={"error": {"message": "Model not found", "type": "not_found_error"}})
    return JSONResponse(content=_model_payload(model_id))


@router.post("/v1/chat/completions", response_model=None)
async def chat_completions(request: ChatCompletionRequest) -> Response:
    messages = [{"role": m.role, "content": m.content} for m in request.messages]

    if request.stream:
        return StreamingResponse(
            agent_service.run_agent_loop_streaming(
                messages=messages,
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        result = await agent_service.run_agent_loop(
            messages=messages,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
        if isinstance(result, str):
            return JSONResponse(status_code=502, content={"error": {"message": result, "type": "proxy_error"}})

        if not getattr(result, "choices", None):
            return JSONResponse(
                status_code=502,
                content={"error": {"message": "Error: LLM returned empty choices", "type": "proxy_error"}},
            )

        selected_model = request.model or getattr(result, "model", "") or ""

        usage_obj = getattr(result, "usage", None)
        response = ChatCompletionResponse(
            model=selected_model,
            choices=[
                ResponseChoice(
                    message=MessageContent(
                        role=result.choices[0].message.role,
                        content=result.choices[0].message.content,
                    ),
                    finish_reason=result.choices[0].finish_reason or "stop",
                )
            ],
            usage=UsageInfo(
                prompt_tokens=getattr(usage_obj, "prompt_tokens", 0),
                completion_tokens=getattr(usage_obj, "completion_tokens", 0),
                total_tokens=getattr(usage_obj, "total_tokens", 0),
            ),
        )
        return JSONResponse(content=response.model_dump())
