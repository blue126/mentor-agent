"""Chat completions router — OpenAI-compatible endpoint."""

import logging
import time

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import get_providers, resolve_provider

logger = logging.getLogger(__name__)
from app.schemas.chat import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    MessageContent,
    ResponseChoice,
    UsageInfo,
)
from app.services import agent_service

router = APIRouter()


def _model_payload(provider_id: str, display_name: str) -> dict[str, str | int]:
    return {
        "id": provider_id,
        "object": "model",
        "created": int(time.time()),
        "owned_by": display_name,
    }


@router.get("/v1/models")
async def list_models() -> JSONResponse:
    providers = get_providers()
    return JSONResponse(
        content={
            "object": "list",
            "data": [_model_payload(p.id, p.display_name) for p in providers],
        }
    )


@router.get("/v1/models/{model_id}")
async def get_model(model_id: str) -> JSONResponse:
    provider = resolve_provider(model_id)
    if provider is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Model not found: {model_id}", "type": "not_found_error"}},
        )
    return JSONResponse(content=_model_payload(provider.id, provider.display_name))


@router.post("/v1/chat/completions", response_model=None)
async def chat_completions(request: ChatCompletionRequest) -> Response:
    provider = resolve_provider(request.model)
    if provider is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Model not found: {request.model}", "type": "not_found_error"}},
        )

    messages = [{"role": m.role, "content": m.content} for m in request.messages]

    if request.stream:
        return StreamingResponse(
            agent_service.run_agent_loop_streaming(
                messages=messages,
                provider=provider,
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
            provider=provider,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
        if isinstance(result, str):
            # Map upstream provider errors to 503 Service Unavailable
            if "unavailable" in result.lower() or "connection" in result.lower():
                logger.error("Provider unavailable: %s — %s", provider.id, result)
                return JSONResponse(
                    status_code=503,
                    content={
                        "error": {
                            "message": f"Provider unavailable: {provider.id}. Please check configuration or try another provider.",
                            "type": "service_unavailable",
                        }
                    },
                )
            return JSONResponse(status_code=502, content={"error": {"message": result, "type": "proxy_error"}})

        if not getattr(result, "choices", None):
            return JSONResponse(
                status_code=502,
                content={"error": {"message": "Error: LLM returned empty choices", "type": "proxy_error"}},
            )

        selected_model = provider.id

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
