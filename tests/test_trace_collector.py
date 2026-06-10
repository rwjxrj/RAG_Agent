from app.services.trace_collector import TraceCollector


def test_trace_collector_builds_snapshot_with_required_fields():
    trace = TraceCollector(trace_id="trace-1", source="reply")

    trace.start_node("intent_cache")
    trace.skip_node("intent_cache", reason="miss")
    trace.start_node("agentic_router")
    trace.complete_node(
        "agentic_router",
        selected_tool="rag_search",
        decision_reason="support_knowledge_question",
        tool_result={"route": "rag_search", "confidence": 0.86},
    )
    trace.set_tool_result(
        decision="PASS",
        citations_count=2,
        followup_count=0,
        confidence=0.7,
    )
    trace.set_latency({"query_extract": 0.012, "retrieve": 0.2, "total": 0.5})

    snapshot = trace.to_debug()

    assert snapshot["trace_id"] == "trace-1"
    assert snapshot["source"] == "reply"
    assert snapshot["status"] == "completed"
    assert snapshot["selected_tool"] == "rag_search"
    assert snapshot["decision_reason"] == "support_knowledge_question"
    assert snapshot["node_path"] == ["intent_cache", "agentic_router"]
    assert snapshot["tool_result"] == {
        "decision": "PASS",
        "citations_count": 2,
        "followup_count": 0,
        "confidence": 0.7,
    }
    assert snapshot["latency"]["total_ms"] == 500
    assert snapshot["latency"]["nodes"]["retrieve"] == 200
    assert snapshot["nodes"][0]["status"] == "skipped"
    assert snapshot["nodes"][1]["status"] == "completed"
