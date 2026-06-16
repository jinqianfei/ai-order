"""Compatibility shim for ``learn.llm.provider``."""
from learning.llm.provider import ChatRequest, ChatResponse, LLMProvider

__all__ = ["LLMProvider", "ChatRequest", "ChatResponse"]
