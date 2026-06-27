# 100 条无泄漏检索评测数据集生成提示词

## 使用方式

将下方“完整提示词”原样发送给具备长文本输出能力的 AI。AI 必须生成两个文件：

- `knowledge_base.json`：放入项目 `source/` 后再执行入库。
- `eval_cases.json`：只用于评测，严禁放入 `source/` 或知识库。

默认业务领域为“服装电商企业客服”。如需测试真实业务，请仅替换提示词中的“业务背景”，不要修改 JSON 字段和 URL 规则。

## 完整提示词

```text
你是一名企业客服知识库工程师和信息检索评测专家。请为一个 RAG 系统生成一套严格无答案泄漏的中文检索基准数据集。

【业务背景】
领域：服装电商企业客服。
覆盖主题：店铺服务时间、售前导购、尺码、库存与补货、颜色与批次、优惠与价保、会员积分、下单、支付、发票、订单修改、物流、偏远地区、签收异常、退换货、退款、运费险、质量问题、洗护、特殊品类、预售、赠品、错发漏发、破损、投诉升级、隐私与账户安全。

所有公司、商品、金额、时效和政策必须是虚构但内部一致的数据。不得引用真实品牌或平台政策。涉及动态订单状态、实时库存、实时价格、账户余额的问题，知识库只能说明查询流程和边界，不能虚构实时结果。

【最终交付】
严格生成两个独立 JSON 文件：knowledge_base.json 和 eval_cases.json。除两个 JSON 代码块外，不要输出解释、摘要或省略号。JSON 必须能被标准解析器直接解析，禁止注释、尾逗号、Markdown 占位符、TBD 或 TODO。

====================
文件一：knowledge_base.json
====================

结构必须为：
{
  "source": "synthetic_retrieval_benchmark_v1",
  "doc_type": "faq",
  "pages": [
    {
      "url": "eval://retrieval/doc-001",
      "title": "文档标题",
      "text": "知识正文"
    }
  ]
}

生成要求：
1. pages 必须恰好包含 40 篇知识文档，URL 从 eval://retrieval/doc-001 连续编号到 eval://retrieval/doc-040，不得重复或缺号。
2. 每篇正文为 300–700 个中文字符，包含明确事实、适用条件、例外、处理步骤和转人工边界。
3. 每篇文档聚焦一个清晰主题，但至少 12 篇文档需要与其他文档存在容易混淆的相邻概念，用于制造真实干扰。例如：退款时效与退货条件、物流停滞与签收异常、库存查询与补货计划。
4. 至少 10 组文档包含可区分的数字、条件或时间限制；同组数字不能完全相同。
5. 文档正文必须自然，像真实客服内部知识文档，而不是关键词堆砌。
6. 知识库正文严禁出现以下内容：
   - “用户问法”“用户问题”“标准答复”“期望答案”“评测问题”
   - eval case id
   - expected_source_urls、difficulty、tags
   - 为了匹配问题而单独罗列的检索关键词或同义词表
7. 不得在文档中复制 eval_cases.json 的问题句子。知识正文与任一问题不得有连续 12 个以上完全相同的中文字符，必要的产品名和法定术语除外。
8. 不得把多个文档合并到一个 page，不得让两个 page 使用相同 title 或 url。

====================
文件二：eval_cases.json
====================

结构必须为：
{
  "version": "1.0",
  "name": "synthetic_retrieval_benchmark_v1",
  "cases": [
    {
      "id": "EVAL-001",
      "question": "用户自然语言问题",
      "expected_source_urls": ["eval://retrieval/doc-001"],
      "standard_answer": "基于期望知识文档整理的参考答案",
      "tags": ["paraphrase", "single-hop"],
      "difficulty": "medium"
    }
  ]
}

生成要求：
1. cases 必须恰好包含 100 条，id 从 EVAL-001 连续编号到 EVAL-100，不得重复或缺号。
2. 难度严格分布：easy 20 条、medium 50 条、hard 30 条。
3. 推理类型严格分布：single-hop 70 条、multi-hop 30 条。multi-hop 的 expected_source_urls 必须包含 2–3 个不同 URL。
4. 每个知识文档至少被一条 case 引用；单篇文档最多被 6 条 case 引用。
5. expected_source_urls 中的 URL 必须全部存在于 knowledge_base.json。
6. question 必须像真实客服输入，包含口语、省略、错别字、上下文不足、同义改写或间接表达；不得直接复制文档标题或正文句子。
7. 100 条问题中至少满足：
   - 30 条 lexical-gap：问题和文档使用明显不同的措辞。
   - 20 条 distractor：存在主题相近但条件不符的干扰文档。
   - 15 条 numeric-condition：必须靠数字、时间或条件区分。
   - 15 条 negative-condition：问题询问不适用、例外、拒绝或限制情况。
   - 10 条 ambiguity：表达不完整，但仍有一个最合理的知识来源。
   - 30 条 multi-hop，与第 3 条保持一致。
   同一 case 可以拥有多个 tags。
8. tags 只能从以下集合选择：
   paraphrase, lexical-gap, single-hop, multi-hop, distractor, ambiguity, policy, procedure, numeric-condition, negative-condition, escalation-boundary
9. easy 问题可以直接改写单篇文档；medium 必须包含同义替换或干扰条件；hard 必须包含多跳、强词汇差异、否定条件、数字边界或多个干扰因素中的至少两项。
10. standard_answer 仅供人工核验，必须由 expected_source_urls 对应文档支持，不得增加知识库没有的承诺、数字或政策。
11. question 和 standard_answer 严禁出现在 knowledge_base.json 中。
12. 不生成无法由知识库回答的开放问题；不依赖实时 API、用户订单号、当前库存、实时价格或外部网页才能确定答案。

【输出前强制自检】
在内部完成以下检查，但不要输出检查过程：
1. 两个 JSON 均可解析。
2. pages=40，cases=100。
3. URL 和 case id 连续、唯一。
4. easy/medium/hard 数量为 20/50/30。
5. single-hop/multi-hop 数量为 70/30。
6. 所有 expected_source_urls 均存在。
7. 每篇文档被引用 1–6 次。
8. knowledge_base.json 不包含任何 question、standard_answer、case id 或评测字段。
9. 所有 standard_answer 均可被对应文档完整支持。
10. 如果任一检查失败，先在内部修正，再输出最终两个 JSON。
```

## 保存位置

建议保存为：

```text
source/retrieval_benchmark_v1.json                 # knowledge_base.json 的内容
artifacts/offline_eval/datasets/eval_cases_v1.json # eval_cases.json 的内容
```

只有第一个文件可以入库。第二个文件必须保持在 `source/` 之外。
