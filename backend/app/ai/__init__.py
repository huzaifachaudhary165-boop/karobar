"""AI layer: Claude client, prompts, tool-calling agent, OCR and insights."""

from app.ai.agent import ChatAgent
from app.ai.client import AiClient, AiResult, ai_client
from app.ai.insights import InsightService
from app.ai.ocr import OcrService
from app.ai.tools import TOOLS, ToolExecutor, available_tools

__all__ = [
    "ai_client", "AiClient", "AiResult",
    "ChatAgent", "OcrService", "InsightService",
    "TOOLS", "ToolExecutor", "available_tools",
]
