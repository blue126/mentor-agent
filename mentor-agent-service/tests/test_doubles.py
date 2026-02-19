class MockChunk:
    def __init__(self, content: str | None, finish_reason: str | None = None, model: str = "test-model"):
        self._content = content
        self._finish_reason = finish_reason
        self._model = model

    def model_dump(self, exclude_none: bool = False) -> dict:
        delta: dict[str, str] = {}
        if self._content is not None:
            delta["content"] = self._content

        choice: dict[str, object] = {"index": 0, "delta": delta, "finish_reason": self._finish_reason}
        result: dict[str, object] = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": self._model,
            "choices": [choice],
        }

        if exclude_none:
            choice = {k: v for k, v in choice.items() if v is not None}
            result["choices"] = [choice]

        return result
