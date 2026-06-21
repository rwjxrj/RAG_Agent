"""Tests for the consolidated normalization module.

Verifies that app.services.normalization correctly replaces all
duplicated normalization functions across the codebase.
"""

from app.services.normalization import (
    normalize_answer_mode,
    normalize_support_level,
    normalize_answer_type,
    normalize_product_family,
    configured_exact_answer_types,
    infer_page_kind,
    sanitize_doc_type_list,
    to_str_list,
)


# ---------------------------------------------------------------------------
# normalize_answer_mode
# ---------------------------------------------------------------------------

class TestNormalizeAnswerMode:
    def test_canonical_values_pass_through(self):
        assert normalize_answer_mode("PASS_EXACT") == "PASS_EXACT"
        assert normalize_answer_mode("PASS_PARTIAL") == "PASS_PARTIAL"
        assert normalize_answer_mode("ASK_USER") == "ASK_USER"

    def test_aliases_resolve(self):
        assert normalize_answer_mode("EXACT") == "PASS_EXACT"
        assert normalize_answer_mode("PARTIAL") == "PASS_PARTIAL"
        assert normalize_answer_mode("PASS_WEAK") == "PASS_PARTIAL"
        assert normalize_answer_mode("PASS_STRONG") == "PASS_EXACT"
        assert normalize_answer_mode("CLARIFY") == "ASK_USER"

    def test_case_insensitive(self):
        assert normalize_answer_mode("exact") == "PASS_EXACT"
        assert normalize_answer_mode("partial") == "PASS_PARTIAL"

    def test_empty_and_none_default(self):
        assert normalize_answer_mode("") == "PASS_EXACT"
        assert normalize_answer_mode(None) == "PASS_EXACT"

    def test_garbage_returns_default(self):
        assert normalize_answer_mode("garbage") == "PASS_EXACT"
        assert normalize_answer_mode("garbage", default="PASS_PARTIAL") == "PASS_PARTIAL"


# ---------------------------------------------------------------------------
# normalize_support_level
# ---------------------------------------------------------------------------

class TestNormalizeSupportLevel:
    def test_canonical_values(self):
        assert normalize_support_level("strong") == "strong"
        assert normalize_support_level("partial") == "partial"
        assert normalize_support_level("weak") == "weak"

    def test_case_insensitive(self):
        assert normalize_support_level("STRONG") == "strong"
        assert normalize_support_level("Partial") == "partial"

    def test_empty_and_none_default(self):
        assert normalize_support_level("") == "strong"
        assert normalize_support_level(None) == "strong"

    def test_garbage_returns_default(self):
        assert normalize_support_level("garbage") == "strong"
        assert normalize_support_level("garbage", default="weak") == "weak"


# ---------------------------------------------------------------------------
# normalize_answer_type
# ---------------------------------------------------------------------------

class TestNormalizeAnswerType:
    def test_canonical_values_pass_through(self):
        assert normalize_answer_type("direct_link") == "direct_link"
        assert normalize_answer_type("pricing") == "pricing"
        assert normalize_answer_type("policy") == "policy"
        assert normalize_answer_type("general") == "general"

    def test_aliases_resolve(self):
        assert normalize_answer_type("link") == "direct_link"
        assert normalize_answer_type("order_link") == "direct_link"
        assert normalize_answer_type("buy_link") == "direct_link"
        assert normalize_answer_type("price") == "pricing"
        assert normalize_answer_type("price_lookup") == "pricing"
        assert normalize_answer_type("refund_policy") == "policy"
        assert normalize_answer_type("general_info") == "general"
        assert normalize_answer_type("ask_user") == "clarification"
        assert normalize_answer_type("ambiguous") == "clarification"

    def test_empty_and_none_default_to_general(self):
        assert normalize_answer_type("") == "general"
        assert normalize_answer_type(None) == "general"

    def test_custom_default(self):
        assert normalize_answer_type("", default="pricing") == "pricing"


# ---------------------------------------------------------------------------
# normalize_product_family
# ---------------------------------------------------------------------------

class TestNormalizeProductFamily:
    def test_canonical_values(self):
        assert normalize_product_family("windows_vps") == "windows_vps"
        assert normalize_product_family("kvm_vps") == "kvm_vps"
        assert normalize_product_family("macos_vps") == "macos_vps"
        assert normalize_product_family("dedicated") == "dedicated"

    def test_aliases_include_space_variants(self):
        assert normalize_product_family("windows vps") == "windows_vps"
        assert normalize_product_family("kvm vps") == "kvm_vps"
        assert normalize_product_family("macos vps") == "macos_vps"
        assert normalize_product_family("dedicated server") == "dedicated"

    def test_common_aliases(self):
        assert normalize_product_family("windows") == "windows_vps"
        assert normalize_product_family("rdp") == "windows_vps"
        assert normalize_product_family("kvm") == "kvm_vps"
        assert normalize_product_family("linux") == "kvm_vps"
        assert normalize_product_family("macos") == "macos_vps"
        assert normalize_product_family("mac") == "macos_vps"

    def test_empty_and_none_return_none(self):
        assert normalize_product_family("") is None
        assert normalize_product_family(None) is None

    def test_unknown_returns_none(self):
        assert normalize_product_family("unknown_product") is None


# ---------------------------------------------------------------------------
# configured_exact_answer_types
# ---------------------------------------------------------------------------

class TestConfiguredExactAnswerTypes:
    def test_returns_set_of_strings(self):
        result = configured_exact_answer_types()
        assert isinstance(result, set)
        assert all(isinstance(x, str) for x in result)

    def test_defaults_include_standard_types(self):
        result = configured_exact_answer_types()
        assert "direct_link" in result
        assert "pricing" in result
        assert "policy" in result


# ---------------------------------------------------------------------------
# infer_page_kind
# ---------------------------------------------------------------------------

class TestInferPageKind:
    def test_conversation_by_doc_type(self):
        assert infer_page_kind(url="http://x", doc_type="conversation") == "conversation"

    def test_conversation_by_ticket_url(self):
        assert infer_page_kind(url="ticket://123", doc_type="other") == "conversation"

    def test_faq_doc_type(self):
        assert infer_page_kind(url="http://x", doc_type="faq") == "faq"

    def test_howto_doc_type(self):
        assert infer_page_kind(url="http://x", doc_type="howto") == "howto"
        assert infer_page_kind(url="http://x", doc_type="docs") == "howto"

    def test_policy_doc_type(self):
        assert infer_page_kind(url="http://x", doc_type="policy") == "policy"
        assert infer_page_kind(url="http://x", doc_type="tos") == "policy"

    def test_pricing_from_url(self):
        assert infer_page_kind(url="http://x.com/pricing", doc_type="other") == "pricing_table"

    def test_product_page_from_url(self):
        assert infer_page_kind(url="http://x.com/vps-servers", doc_type="other") == "product_page"

    def test_default_is_blog(self):
        assert infer_page_kind(url="http://x.com/random", doc_type="other") == "blog"


# ---------------------------------------------------------------------------
# sanitize_doc_type_list
# ---------------------------------------------------------------------------

class TestSanitizeDocTypeList:
    def test_filters_valid_types(self):
        result = sanitize_doc_type_list(["pricing", "policy", "invalid_type"])
        assert "pricing" in result
        assert "policy" in result
        assert "invalid_type" not in result

    def test_deduplicates(self):
        result = sanitize_doc_type_list(["pricing", "pricing", "policy"])
        assert result.count("pricing") == 1

    def test_empty_input(self):
        assert sanitize_doc_type_list([]) == []
        assert sanitize_doc_type_list(None) == []


# ---------------------------------------------------------------------------
# to_str_list
# ---------------------------------------------------------------------------

class TestToStrList:
    def test_basic_list(self):
        assert to_str_list(["a", "b", "c"]) == ["a", "b", "c"]

    def test_deduplicates(self):
        assert to_str_list(["a", "a", "b"]) == ["a", "b"]

    def test_strips_whitespace(self):
        assert to_str_list(["  a  ", " b "]) == ["a", "b"]

    def test_limit(self):
        assert to_str_list(["a", "b", "c", "d"], limit=2) == ["a", "b"]

    def test_none_returns_empty(self):
        assert to_str_list(None) == []

    def test_empty_list_returns_empty(self):
        assert to_str_list([]) == []

    def test_scalar_wrapped_in_list(self):
        assert to_str_list("scalar") == ["scalar"]
        assert to_str_list(42) == ["42"]

    def test_empty_scalar_returns_empty(self):
        assert to_str_list("") == []
