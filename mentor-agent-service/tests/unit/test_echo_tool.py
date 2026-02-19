"""Unit tests for echo tool — normal return and Fail Soft behavior."""

from app.tools.echo_tool import echo


async def test_echo_returns_message():
    result = await echo(message="hello world")
    assert result == "hello world"


async def test_echo_returns_empty_string():
    result = await echo(message="")
    assert result == ""


async def test_echo_returns_unicode():
    result = await echo(message="你好世界")
    assert result == "你好世界"
