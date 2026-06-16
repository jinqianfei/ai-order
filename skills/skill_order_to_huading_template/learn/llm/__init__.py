"""learn.llm shim for backward compatibility.

The canonical LLM provider implementation lives in workspace-level
``learning.llm``. This package keeps old ``from learn.llm ...`` imports alive.
"""
import os
import sys

_ws = os.environ.get(
    "AI_ORDER_WORKSPACE",
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
)
if _ws not in sys.path:
    sys.path.insert(0, _ws)

from learning.llm import (  # noqa: F401
    ChatRequest,
    ChatResponse,
    CustomHTTPProvider,
    LLMProvider,
    LLMRouter,
    OpenAICompatProvider,
    OpenAIProvider,
    OpenClawProvider,
)

__all__ = [
    "LLMProvider",
    "ChatRequest",
    "ChatResponse",
    "LLMRouter",
    "OpenClawProvider",
    "OpenAIProvider",
    "OpenAICompatProvider",
    "CustomHTTPProvider",
]
