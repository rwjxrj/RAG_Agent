## ADDED Requirements

### Requirement: Trace exposes RAG execution progress
The system SHALL expose a structured, optional trace for supported question-answering flows so the frontend can show the current execution progress.

#### Scenario: Final response includes trace snapshot
- **WHEN** a supported non-streaming question-answering request completes
- **THEN** the response metadata MUST be able to include a trace snapshot containing execution status, node path, selected tool, decision reason, tool result, and latency summary

#### Scenario: Trace remains optional
- **WHEN** a client does not read trace metadata
- **THEN** the existing top-level API response fields MUST remain compatible and sufficient for normal answer rendering

### Requirement: Trace records intent and Agentic Router decisions
The system SHALL record intent cache and Agentic Router decision information in the trace when those stages are reached.

#### Scenario: Intent cache hit is visible
- **WHEN** intent cache matches a configured intent
- **THEN** the trace MUST indicate the matched intent key and MUST indicate that Agentic Router was skipped

#### Scenario: Router-selected tool is visible
- **WHEN** intent cache misses and Agentic Router selects a route
- **THEN** the trace MUST include `selected_tool`, `decision_reason`, and Router confidence or fallback status when available

### Requirement: Trace node path uses stable logical names
The system SHALL represent execution path with stable logical node names rather than implementation-specific function or class names.

#### Scenario: RAG path records logical nodes
- **WHEN** a request enters the standard RAG path
- **THEN** `node_path` MUST include logical nodes such as `guardrails`, `intent_cache`, `agentic_router`, `query_extract`, `retrieve`, `assess_evidence`, `generate`, and `verify`

#### Scenario: Non-RAG path records terminal tool
- **WHEN** Agentic Router selects `direct_response`, `clarify`, or `human_handoff`
- **THEN** `node_path` MUST include the selected terminal tool node and MUST NOT imply that retrieval or generation ran

### Requirement: Trace reports tool result summaries
The system SHALL summarize tool outcomes without exposing sensitive internal details.

#### Scenario: RAG result summarizes evidence output
- **WHEN** the RAG path completes
- **THEN** `tool_result` MUST be able to include the final decision, citation count, follow-up count, and confidence when available

#### Scenario: Human handoff hides internal details
- **WHEN** the route is `human_handoff`
- **THEN** `tool_result` MUST summarize the handoff decision without exposing private account, billing, security, or exception details

### Requirement: Trace reports latency by total and node
The system SHALL report latency in a frontend-friendly format.

#### Scenario: Total latency is available
- **WHEN** a trace snapshot is produced
- **THEN** it MUST include total latency in milliseconds when measurable

#### Scenario: Node latency is available when measured
- **WHEN** a node or RAG phase timing is measured
- **THEN** the trace MUST expose that timing as node-level latency in milliseconds

### Requirement: Streaming entrypoint can emit trace progress events
The system SHALL allow the streaming conversation entrypoint to emit optional trace progress events before the final answer is complete.

#### Scenario: Stream emits running node event
- **WHEN** a streaming request starts a traceable node
- **THEN** the stream MAY emit a trace event containing `trace_id`, `node_id`, `status`, and current `node_path`

#### Scenario: Clients can ignore trace events
- **WHEN** a client does not support trace events
- **THEN** the stream MUST still deliver the answer using the existing response behavior

### Requirement: Trace remains workflow-framework agnostic
The system SHALL keep trace fields independent from any workflow framework and MUST NOT require LangGraph.

#### Scenario: Node path remains stable across internal refactors
- **WHEN** the RAG flow internals are refactored without changing user-facing behavior
- **THEN** existing trace consumers MUST be able to render the flow from `node_path` and node status without requiring a new top-level response contract

#### Scenario: Unknown future nodes are renderable
- **WHEN** a future implementation emits additional node IDs
- **THEN** the frontend MUST be able to render them as generic trace nodes rather than failing
