"""Chat completions router — OpenAI-compatible endpoint."""

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.schemas.chat import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    MessageContent,
    ResponseChoice,
    UsageInfo,
)
from app.services.llm_service import get_chat_completion, stream_chat_completion
from app.utils.sse_generator import sse_stream

router = APIRouter()


@router.post("/v1/chat/completions", response_model=None)
async def chat_completions(request: ChatCompletionRequest) -> Response:
    messages = [{"role": m.role, "content": m.content} for m in request.messages]

    if request.stream:
        result = await stream_chat_completion(
            messages=messages,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
        # Fail Soft: if result is a string, it's an error message
        if isinstance(result, str):
            return JSONResponse(status_code=502, content={"error": {"message": result, "type": "proxy_error"}})

        return StreamingResponse(
            sse_stream(result),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        result = await get_chat_completion(
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
                prompt_tokens=getattr(result.usage, "prompt_tokens", 0),
                completion_tokens=getattr(result.usage, "completion_tokens", 0),
                total_tokens=getattr(result.usage, "total_tokens", 0),
            ),
        )
        return JSONResponse(content=response.model_dump())
