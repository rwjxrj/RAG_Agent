"""Tests for source loader taxonomy enrichment."""

import json

from app.services.source_loaders import load_all_docs, load_pages_json


def test_load_pages_json_enriches_page_kind_and_product_family(tmp_path):
    path = tmp_path / "pricing.json"
    payload = {
        "source": "unit_test",
        "doc_type": "pricing",
        "pages": [
            {
                "url": "https://example.com/order/windows-vps",
                "title": "Windows VPS Order",
                "text": "Buy Windows VPS instantly with monthly billing and immediate setup support included.",
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    docs = load_pages_json(path)

    assert len(docs) == 1
    metadata = docs[0]["metadata"] or {}
    assert metadata.get("page_kind") == "order_page"
    assert metadata.get("product_family") == "windows_vps"


def test_load_pages_json_reads_utf8_chinese_pages(tmp_path):
    path = tmp_path / "retrieval_benchmark_v1.json"
    payload = {
        "version": "1.0",
        "source": "synthetic_retrieval_benchmark_v1",
        "doc_type": "faq",
        "pages": [
            {
                "url": "eval://retrieval/doc-001",
                "title": "棉岚服饰服务时间",
                "text": "棉岚服饰线上客服采用分段值班。工作日在线接待为9:00至22:30，周六、周日为10:00至22:00。机器人可全天提供订单流程、退换货入口和常见政策说明。",
            }
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    docs = load_pages_json(path)

    assert len(docs) == 1
    assert docs[0]["url"] == "eval://retrieval/doc-001"
    assert docs[0]["raw_text"].startswith("棉岚服饰")


def test_load_all_docs_uses_benchmark_file_doc_type(tmp_path):
    path = tmp_path / "retrieval_benchmark_v1.json"
    payload = {
        "version": "1.0",
        "source": "synthetic_retrieval_benchmark_v1",
        "doc_type": "faq",
        "pages": [
            {
                "url": "eval://retrieval/doc-001",
                "title": "棉岚服饰服务时间",
                "text": "棉岚服饰线上客服采用分段值班。工作日在线接待为9:00至22:30，周六、周日为10:00至22:00。机器人可全天提供订单流程、退换货入口和常见政策说明。",
            }
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    docs = load_all_docs(tmp_path, files=["retrieval_benchmark_v1.json"])

    assert len(docs) == 1
    assert docs[0]["doc_type"] == "faq"
