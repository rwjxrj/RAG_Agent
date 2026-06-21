"""Shared normalization and validation functions.

Single source of truth for answer mode, support level, answer type,
product family, page kind, doc type, and string list utilities.

Consolidates duplicated logic from:
- answer_utils.py, reviewer.py, decision_router.py
- retrieval_planner.py, source_loaders.py
- normalizer.py, evidence_quality.py, offline_eval.py
"""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings

# ---------------------------------------------------------------------------
# Answer mode
# ---------------------------------------------------------------------------

_ALLOWED_ANSWER_MODES = {"PASS_EXACT", "PASS_PARTIAL", "ASK_USER"}

_ANSWER_MODE_ALIASES: dict[str, str] = {
    "EXACT": "PASS_EXACT",
    "PARTIAL": "PASS_PARTIAL",
    "PASS_WEAK": "PASS_PARTIAL",
    "PASS_STRONG": "PASS_EXACT",
    "CLARIFY": "ASK_USER",
}


def normalize_answer_mode(value: Any, *, default: str = "PASS_EXACT") -> str:
    """Normalize answer mode to canonical form."""
    raw = str(value or "").strip().upper()
    if raw in _ALLOWED_ANSWER_MODES:
        return raw
    return _ANSWER_MODE_ALIASES.get(raw, default) if raw else default


# Keep legacy name as alias for callers that haven't migrated yet
_sanitize_answer_mode = normalize_answer_mode
_normalize_answer_mode = normalize_answer_mode

# ---------------------------------------------------------------------------
# Support level
# ---------------------------------------------------------------------------

_ALLOWED_SUPPORT_LEVELS = {"strong", "partial", "weak"}


def normalize_support_level(value: Any, *, default: str = "strong") -> str:
    """Normalize support level to canonical form."""
    raw = str(value or "").strip().lower()
    if raw in _ALLOWED_SUPPORT_LEVELS:
        return raw
    return default


_sanitize_support_level = normalize_support_level
_normalize_support_level = normalize_support_level

# ---------------------------------------------------------------------------
# Answer type
# ---------------------------------------------------------------------------

_ALLOWED_ANSWER_TYPES = {
    "direct_link",
    "pricing",
    "policy",
    "troubleshooting",
    "general",
    "clarification",
    "account",
}

_ANSWER_TYPE_ALIASES: dict[str, str] = {
    "link": "direct_link",
    "order_link": "direct_link",
    "buy_link": "direct_link",
    "price": "pricing",
    "price_lookup": "pricing",
    "refund_policy": "policy",
    "general_info": "general",
    "ask_user": "clarification",
    "ambiguous": "clarification",
}


def normalize_answer_type(value: Any, *, default: str = "general") -> str:
    """Normalize answer type to canonical form. Always returns a non-empty string."""
    raw = str(value or "").strip().lower()
    if raw in _ALLOWED_ANSWER_TYPES:
        return raw
    if raw:
        return _ANSWER_TYPE_ALIASES.get(raw, default)
    return default


_sanitize_answer_type = normalize_answer_type

# ---------------------------------------------------------------------------
# Product family
# ---------------------------------------------------------------------------

_PRODUCT_FAMILIES = {"windows_vps", "kvm_vps", "macos_vps", "dedicated"}

_PRODUCT_FAMILY_ALIASES: dict[str, str] = {
    "windows": "windows_vps",
    "windows vps": "windows_vps",
    "windows_vps": "windows_vps",
    "windows-rdp": "windows_vps",
    "rdp": "windows_vps",
    "kvm": "kvm_vps",
    "kvm vps": "kvm_vps",
    "kvm_vps": "kvm_vps",
    "linux_vps": "kvm_vps",
    "linux vps": "kvm_vps",
    "linux": "kvm_vps",
    "macos": "macos_vps",
    "mac": "macos_vps",
    "macos vps": "macos_vps",
    "macos_vps": "macos_vps",
    "dedicated": "dedicated",
    "dedicated_server": "dedicated",
    "dedicated server": "dedicated",
    "dedicated_servers": "dedicated",
}


def normalize_product_family(value: Any) -> str | None:
    """Normalize product family to canonical form. Returns None if unrecognized."""
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    if raw in _PRODUCT_FAMILIES:
        return raw
    return _PRODUCT_FAMILY_ALIASES.get(raw) if raw else None


# Legacy aliases for callers that haven't migrated
_normalize_product_family = normalize_product_family

# ---------------------------------------------------------------------------
# Exact answer types (from settings)
# ---------------------------------------------------------------------------

_DEFAULT_EXACT_ANSWER_TYPES = {"direct_link", "pricing", "policy"}


def configured_exact_answer_types() -> set[str]:
    """Read exact answer types from settings, falling back to defaults."""
    raw = getattr(get_settings(), "exact_answer_types", None)
    if isinstance(raw, str):
        configured = [item.strip() for item in raw.split(",") if item.strip()]
    elif isinstance(raw, (list, tuple, set)):
        configured = list(raw)
    else:
        configured = []
    normalized = {
        str(item).strip().lower()
        for item in configured
        if str(item).strip()
    }
    return normalized or set(_DEFAULT_EXACT_ANSWER_TYPES)


_configured_exact_answer_types = configured_exact_answer_types

# ---------------------------------------------------------------------------
# Page kind inference
# ---------------------------------------------------------------------------

_VALID_PAGE_KINDS = {
    "conversation", "faq", "howto", "policy", "blog",
    "order_page", "pricing_table", "product_page",
}


def infer_page_kind(
    *,
    url: str,
    doc_type: str,
    title: str = "",
    text: str = "",
) -> str:
    """Infer lightweight page taxonomy for retrieval weighting."""
    dt = (doc_type or "").strip().lower()
    if dt == "conversation" or url.startswith("ticket://"):
        return "conversation"
    if dt in {"faq"}:
        return "faq"
    if dt in {"howto", "docs"}:
        return "howto"
    if dt in {"policy", "tos"}:
        return "policy"
    if dt == "blog":
        return "blog"

    blob = f"{url} {title} {text}".lower()
    if any(token in blob for token in ("/order", "checkout", "cart", "buy now", "purchase")):
        return "order_page"
    if dt == "pricing" or any(token in blob for token in ("pricing", "plans", "price", "/mo")):
        return "pricing_table"
    if any(token in blob for token in ("vps", "server", "dedicated", "product")):
        return "product_page"
    return "blog"


_infer_page_kind = infer_page_kind

# ---------------------------------------------------------------------------
# Doc type validation
# ---------------------------------------------------------------------------

_DEFAULT_DOC_TYPES = {"pricing", "policy", "tos", "faq", "howto", "docs", "conversation", "blog"}


def valid_doc_types() -> set[str]:
    """Read valid doc types from settings, falling back to defaults."""
    from app.services.doc_type_service import get_valid_doc_type_keys

    valid = {str(x).strip().lower() for x in get_valid_doc_type_keys() if str(x).strip()}
    return valid or set(_DEFAULT_DOC_TYPES)


_valid_doc_types = valid_doc_types


def sanitize_doc_type_list(values: list[Any] | None) -> list[str]:
    """Filter and deduplicate doc types against the valid set."""
    valid = valid_doc_types()
    out: list[str] = []
    for item in values or []:
        text = str(item).strip().lower()
        if text and text in valid and text not in out:
            out.append(text)
    return out


_sanitize_doc_type_list = sanitize_doc_type_list

# ---------------------------------------------------------------------------
# String list utilities
# ---------------------------------------------------------------------------


def to_str_list(value: Any, *, limit: int | None = None, strip: bool = True) -> list[str]:
    """Convert a value to a deduplicated list of strings.

    - If *value* is a list, each element is str()-ified.
    - If *value* is a scalar, it is wrapped in a single-element list.
    - *None* / empty returns [].
    - *limit* caps the output length (None = no cap).
    - *strip* controls whether whitespace is stripped.
    """
    if value is None:
        return []
    if not isinstance(value, list):
        text = str(value).strip() if strip else str(value)
        return [text] if text else []
    out: list[str] = []
    for item in value:
        text = str(item).strip() if strip else str(item)
        if text and text not in out:
            out.append(text)
        if limit is not None and len(out) >= limit:
            break
    return out


# Legacy aliases with different default limits
_to_str_list = to_str_list
