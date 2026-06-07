"""Intent-based shortcut cache for common queries.

Returns predefined answers without calling LLM/retrieval. Configurable via env.
"""

import re
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class IntentMatch:
    """Result of intent matching."""

    intent: str
    answer: str


def _default_intents() -> dict[str, dict[str, str]]:
    app_name = (get_settings().app_name or "").strip()
    prefix = f"{app_name} 的" if app_name else ""
    welcome = f"欢迎使用 {app_name} 客服。" if app_name else "欢迎。"
    return {
        "what_can_you_do": {
            "patterns": r"\b(what (can you|do you|does (this )?ai) do|你能做什么|你可以做什么|有什么功能|bạn làm gì|ai làm gì|chức năng)\b",
            "answer": f"我是{prefix}AI 客服助手，可以帮助查询产品、政策和操作指南等知识库内容。你想了解什么？",
        },
        "who_are_you": {
            "patterns": r"\b(who are you|你是谁|你是什么|bạn là ai|ai là gì)\b",
            "answer": f"我是{prefix}AI 客服助手，会基于已导入的文档回答问题。有什么可以帮你？",
        },
        "who_am_i": {
            "patterns": r"\b(who am i|我是谁|我的账号是谁|tôi là ai|mình là ai)\b",
            "answer": "我无法直接访问你的账户详情。如果需要查询账单或账户信息，请登录客户中心或联系人工客服。",
        },
        "about": {
            "patterns": r"\b(what is|about|who are you|介绍|giới thiệu)\s+(?:this (?:company|service)|us|your (?:company|service)|这家公司|这个服务|你们)\b",
            "answer": f"我是{prefix}AI 客服助手，会根据我们的文档帮助回答问题。你想了解哪方面内容？",
        },
        "hello": {
            "patterns": r"^(hi|hello|hey|你好|您好|嗨|chào|xin chào)\s*!?$",
            "answer": f"你好！{welcome}我可以帮助你查询产品、价格、政策或操作指南。",
        },
    }


def _load_intent_responses() -> dict[str, dict[str, str]]:
    """Load intent config from settings or use defaults."""
    return _default_intents()


def match_intent(query: str) -> IntentMatch | None:
    """Check if query matches a cached intent. Returns (intent, answer) or None."""
    settings = get_settings()
    if not getattr(settings, "intent_cache_enabled", True):
        return None

    q = query.strip().lower()
    if len(q) > 200:
        return None

    intents = _load_intent_responses()
    for intent_key, config in intents.items():
        patterns = config.get("patterns", "")
        answer = config.get("answer", "")
        if not patterns or not answer:
            continue
        try:
            if re.search(patterns, q, re.IGNORECASE):
                return IntentMatch(intent=intent_key, answer=answer)
        except re.error:
            logger.warning("intent_pattern_invalid", intent=intent_key, pattern=patterns)
            continue
    return None
