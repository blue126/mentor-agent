"""Echo tool — sample tool for validating tool use loop completeness."""


async def echo(message: str) -> str:
    """Echo back the given message. Fail Soft: exceptions return error strings."""
    try:
        return message
    except Exception as exc:
        return f"Error: echo failed: {exc}. Hint: check input format"
