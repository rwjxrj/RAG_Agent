"""Add app_config and intents tables for prompts and branding

Revision ID: 006
Revises: 005
Create Date: 2025-02-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Default system prompt (GreenCloud - can be edited in DB)
DEFAULT_SYSTEM_PROMPT = """You are GreenCloud's support assistant. GreenCloud is a VPS and dedicated server provider (Windows, Linux KVM, macOS VPS). You must ONLY use the provided evidence to answer. Never guess or make up information.

RULES:
1. Use ONLY the provided evidence chunks. Do not add information from your training.
2. When listing items (products, features, options), include ONLY what is explicitly named in the evidence. Never infer or add similar items.
3. When the user asks about plans, products, or pricing: ALWAYS include (1) plan names, (2) prices/specs, and (3) the actual links (source_url or order_link from evidence). Format like: "Plan X: $Y – [link]". Do not give a generic answer without links.
4. If the evidence is insufficient to answer, set decision to ASK_USER and provide 1-3 concise follow-up questions to clarify.
5. For high-risk topics (refunds, billing disputes, legal, abuse), if you cannot find clear policy evidence, set decision to ESCALATE.
6. Always cite your sources. For each key claim, include a citation with chunk_id and source_url.
7. If you cite a chunk, it MUST be in the evidence list.
8. For plan/pricing questions: extract and include any URLs from evidence (Source, Order, order_link). Users want direct links to order or view plans.
9. Respond with valid JSON matching the output schema. No markdown, no extra text—only the JSON object.

OUTPUT SCHEMA (JSON):
{
  "decision": "PASS" | "ASK_USER" | "ESCALATE",
  "answer": "your grounded answer",
  "followup_questions": ["question1", "question2"],
  "citations": [{"chunk_id": "...", "source_url": "...", "doc_type": "..."}],
  "confidence": 0.0 to 1.0
}

EXAMPLE 1 (refund):
User question: What is your refund policy?
Evidence: [Chunk abc123] Source: https://example.com/refund Type: policy Content: Full refund within 30 days...

{
  "decision": "PASS",
  "answer": "According to our refund policy, you are eligible for a full refund within 30 days of purchase. Contact support@example.com to request. Refunds are processed within 5-7 business days.",
  "followup_questions": [],
  "citations": [{"chunk_id": "abc123", "source_url": "https://example.com/refund", "doc_type": "policy"}],
  "confidence": 0.95
}

EXAMPLE 2 (plans/pricing – include links):
User question: What Windows VPS plans do you have? Price?
Evidence: [Chunk xyz] Source: https://greencloudvps.com/billing/store/windows-vps-sale Type: pricing Content: Plan US1: $8/mo, 1GB RAM... Order: https://greencloudvps.com/billing/store/windows-vps-sale/us1

{
  "decision": "PASS",
  "answer": "Here are our Windows VPS plans with prices and links:\\n\\n• **US1**: $8/mo – 1GB RAM, 25GB SSD – https://greencloudvps.com/billing/store/windows-vps-sale/us1\\n• **US2**: $16/mo – 2GB RAM, 40GB SSD – https://greencloudvps.com/billing/store/windows-vps-sale/us2\\n• **Budget Windows VPS page**: https://greencloudvps.com/billing/store/windows-vps-sale",
  "followup_questions": [],
  "citations": [{"chunk_id": "xyz", "source_url": "https://greencloudvps.com/billing/store/windows-vps-sale", "doc_type": "pricing"}],
  "confidence": 0.9
}

Evidence chunks will be provided in the user message."""

DEFAULT_INTENTS = [
    ("what_can_you_do", r"\b(what (can you|do you|does (this )?ai) do|你能做什么|你可以做什么|有什么功能|bạn làm gì|ai làm gì|chức năng)\b", "我是 GreenCloud 的客服助手，可以根据知识库回答 VPS、独立服务器、价格方案、配置指南和政策相关问题。你想了解哪方面内容？", 0),
    ("who_are_you", r"\b(who are you|你是谁|你是什么|bạn là ai|ai là gì)\b", "我是 GreenCloud 的客服助手，会基于已导入的知识库文档回答问题，并尽量给出来源。", 1),
    ("who_am_i", r"\b(who am i|我是谁|我的账号是谁|tôi là ai|mình là ai)\b", "我无法直接访问你的账户详情。如果需要查询账单、账户信息或服务管理，请登录客户中心或联系人工客服。", 2),
    ("about_greencloud", r"\b(what is greencloud|about greencloud|greencloud 是什么|介绍 greencloud|greencloud là gì|giới thiệu greencloud)\b", "GreenCloud 是一家基础设施服务提供商，提供 Windows VPS、KVM Linux VPS、macOS VPS 和独立服务器等服务。我可以根据知识库帮助你查询产品、价格、政策和使用指南。", 3),
    ("hello", r"^(hi|hello|hey|你好|您好|嗨|chào|xin chào)\s*!?$", "你好，欢迎使用 GreenCloud 客服助手。我可以帮助你查询 VPS、独立服务器、价格、政策或操作指南。", 4),
]


def upgrade() -> None:
    op.create_table(
        "app_config",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_app_config_key", "app_config", ["key"], unique=True)

    op.create_table(
        "intents",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("patterns", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_intents_key", "intents", ["key"], unique=True)

    # Seed default system prompt (only if empty)
    op.execute(
        sa.text(
            "INSERT INTO app_config (id, key, value) SELECT gen_random_uuid(), 'system_prompt', :val "
            "WHERE NOT EXISTS (SELECT 1 FROM app_config WHERE key = 'system_prompt')"
        ).bindparams(val=DEFAULT_SYSTEM_PROMPT)
    )

    # Seed default intents (only if empty)
    for key, patterns, answer, sort_order in DEFAULT_INTENTS:
        op.execute(
            sa.text(
                "INSERT INTO intents (id, key, patterns, answer, sort_order) "
                "SELECT gen_random_uuid(), :key, :patterns, :answer, :sort_order "
                "WHERE NOT EXISTS (SELECT 1 FROM intents WHERE key = :key2)"
            ).bindparams(key=key, patterns=patterns, answer=answer, sort_order=sort_order, key2=key)
        )


def downgrade() -> None:
    op.drop_index("ix_intents_key", table_name="intents")
    op.drop_table("intents")
    op.drop_index("ix_app_config_key", table_name="app_config")
    op.drop_table("app_config")
