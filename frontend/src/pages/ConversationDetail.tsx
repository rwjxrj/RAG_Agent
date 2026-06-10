import { useState, useEffect, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  conversations,
  decisionLabel,
  docTypeLabel,
  queryExtractionModeLabel,
  sourceTypeLabel,
  terminationReasonLabel,
  type ConversationDetail as ConvDetail,
  type Message,
  type FlowDebug,
  type TraceEventData,
  type TraceNode,
  type TraceSnapshot,
} from '../api/client'
import {
  ArrowLeft,
  Copy,
  Check,
  Send,
  Loader2,
  Bot,
  User,
  ChevronDown,
  ChevronRight,
  Zap,
  Search,
  Database,
  FileText,
  Brain,
  AlertTriangle,
  ExternalLink,
  Sparkles,
  MessageSquare,
} from 'lucide-react'

export default function ConversationDetail() {
  const { id } = useParams<{ id: string }>()
  const [conv, setConv] = useState<ConvDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [streamingContent, setStreamingContent] = useState('')
  const [streamTrace, setStreamTrace] = useState<TraceSnapshot | null>(null)
  const [useStreaming, setUseStreaming] = useState(true)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const load = async () => {
    if (!id) return
    setLoading(true)
    setError(null)
    try {
      const data = await conversations.get(id)
      setConv(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载会话失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [id])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [conv?.messages])

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!id || !input.trim() || sending) return
    const content = input.trim()
    setInput('')
    setSending(true)
    setError(null)
    setStreamingContent('')
    setStreamTrace(null)

    try {
      if (useStreaming) {
        const res = await conversations.sendMessageStream(id, content)
        if (!res.ok) throw new Error(res.statusText)
        const reader = res.body?.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let streamDone = false
        if (reader) {
          while (!streamDone) {
            const { done, value } = await reader.read()
            if (done) break
            buffer += decoder.decode(value, { stream: true })
            const events = buffer.split('\n\n')
            buffer = events.pop() || ''
            for (const ev of events) {
              const m = ev.match(/^data:\s*(.+)$/m)
              if (m) {
                let data: { type?: string; data?: unknown } | null = null
                try {
                  data = JSON.parse(m[1])
                } catch {}
                if (data?.type === 'content') setStreamingContent((prev) => prev + String(data.data || ''))
                else if (data?.type === 'trace') {
                  const traceEvent = data.data
                  if (isTraceEventData(traceEvent)) {
                    setStreamTrace((prev) => mergeTraceEvent(prev, traceEvent))
                  }
                }
                else if (data?.type === 'error') throw new Error(String(data.data || '生成回复失败'))
                else if (data?.type === 'done') {
                  streamDone = true
                  break
                }
              }
            }
          }
          if (streamDone) reader.cancel().catch(() => {})
        }
        await load()
      } else {
        await conversations.sendMessage(id, content)
        await load()
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '发送消息失败')
      setInput(content)
    } finally {
      setSending(false)
      setStreamingContent('')
      setStreamTrace(null)
    }
  }

  if (!id) return null

  if (loading) return (
    <div className="flex items-center justify-center gap-3 py-24 animate-fade-in">
      <Loader2 size={22} className="animate-spin-slow text-accent" />
      <span className="text-zinc-500">正在加载会话...</span>
    </div>
  )

  if (error && !conv) {
    return (
      <div className="animate-fade-in">
        <div className="p-3.5 rounded-xl mb-5 bg-danger/10 border border-danger/20 text-red-300 text-sm">{error}</div>
        <Link to="/" className="inline-flex items-center gap-2 text-sm text-zinc-500 hover:text-white transition-colors">
          <ArrowLeft size={16} /> 返回会话列表
        </Link>
      </div>
    )
  }

  if (!conv) return null

  return (
    <div className="flex flex-col h-[calc(100vh-3rem)] lg:h-[calc(100vh-2rem)] animate-slide-up">
      <header className="flex items-center gap-3 pb-4 mb-0 shrink-0" style={{ borderBottom: '1px solid rgba(148,163,184,0.22)' }}>
        <Link
          to="/"
          className="p-2 rounded-xl text-zinc-500 hover:text-blue-700 hover:bg-sky-100 transition-colors"
        >
          <ArrowLeft size={18} />
        </Link>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-semibold text-white truncate">会话详情</h1>
            <CopyableId id={conv.id} />
          </div>
          <div className="flex items-center gap-3 text-xs text-zinc-500 mt-0.5">
            <span>{sourceTypeLabel(conv.source_type)} / {conv.source_id}</span>
            <span className="text-zinc-700">·</span>
            <span>{new Date(conv.created_at).toLocaleDateString('zh-CN')}</span>
            <span className="text-zinc-700">·</span>
            <span>{conv.messages.length} 条消息</span>
          </div>
        </div>
      </header>

      {error && (
        <div className="p-3.5 rounded-xl my-3 bg-danger/10 border border-danger/20 text-red-300 text-sm animate-fade-in">
          {error}
        </div>
      )}

      <div className="flex-1 overflow-y-auto py-5 space-y-4">
        {conv.messages.length === 0 && (
          <div className="flex flex-col items-center justify-center py-20 text-zinc-500">
            <div className="w-14 h-14 rounded-2xl glass-accent flex items-center justify-center mb-4 glow-sm">
              <Sparkles size={24} className="text-violet-400" />
            </div>
            <p className="text-sm">发送一条消息开始对话</p>
          </div>
        )}
        {conv.messages.map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}
        {streamingContent && (
          <div className="flex items-start gap-3 animate-fade-in">
            <div
              className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0 mt-0.5"
              style={{ background: 'linear-gradient(135deg, rgba(219,234,254,0.88), rgba(186,230,253,0.72))' }}
            >
              <Bot size={16} className="text-violet-400" />
            </div>
            <div className="glass rounded-2xl rounded-tl-lg px-4 py-3.5 max-w-[85%]">
              <div className="text-zinc-200 whitespace-pre-wrap text-sm leading-relaxed">{streamingContent}</div>
              <TraceTimeline trace={streamTrace} />
              <span className="inline-block w-2 h-4 ml-0.5 bg-violet-400 animate-pulse" />
            </div>
          </div>
        )}
        {sending && !streamingContent && (
          <div className="flex items-start gap-3 animate-fade-in">
            <div
              className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0 mt-0.5"
              style={{ background: 'linear-gradient(135deg, rgba(219,234,254,0.88), rgba(186,230,253,0.72))' }}
            >
              <Bot size={16} className="text-violet-400" />
            </div>
            <div className="glass rounded-2xl rounded-tl-lg px-4 py-3.5">
              <div className="flex items-center gap-2.5 text-zinc-500 text-sm">
                <div className="flex gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse-soft" style={{ animationDelay: '0ms' }} />
                  <span className="w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse-soft" style={{ animationDelay: '200ms' }} />
                  <span className="w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse-soft" style={{ animationDelay: '400ms' }} />
                </div>
                正在思考...
              </div>
              <TraceTimeline trace={streamTrace} />
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <form
        className="flex flex-col gap-2 pt-4 shrink-0"
        style={{ borderTop: '1px solid rgba(148,163,184,0.22)' }}
        onSubmit={handleSend}
      >
        <div className="flex items-end gap-3">
        <div className="flex-1 relative">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="输入消息..."
            disabled={sending}
            maxLength={10000}
            className="w-full px-5 py-3.5 rounded-2xl input-glass text-sm disabled:opacity-50 pr-4"
          />
        </div>
        <button
          type="submit"
          className="btn-primary p-3.5 rounded-2xl disabled:opacity-30 disabled:cursor-not-allowed shrink-0"
          disabled={sending || !input.trim()}
        >
          {sending ? <Loader2 size={18} className="animate-spin-slow" /> : <Send size={18} />}
        </button>
        </div>
        <label className="flex items-center gap-2 text-xs text-zinc-500 cursor-pointer w-fit">
          <input
            type="checkbox"
            checked={useStreaming}
            onChange={(e) => setUseStreaming(e.target.checked)}
            className="rounded border-white/10"
          />
          流式响应
        </label>
      </form>
    </div>
  )
}

function CopyableId({ id }: { id: string }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard.writeText(id)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <button
      onClick={copy}
      className="inline-flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs font-mono text-zinc-500
                 bg-sky-50 hover:bg-sky-100 hover:text-blue-700 transition-colors"
      title="复制 ID"
    >
      {id.slice(0, 8)}...
      {copied ? <Check size={11} className="text-emerald-400" /> : <Copy size={11} />}
    </button>
  )
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'
  const [showFlow, setShowFlow] = useState(false)
  const debug = message.debug
  const hasDebug = debug && (
    debug.trace || debug.agentic_router || debug.decision != null || debug.confidence != null || debug.trace_id ||
    debug.source_lang || debug.evidence_eval || debug.self_critic_regenerated || debug.final_polish_applied ||
    (debug.stage_reasons && debug.stage_reasons.length > 0) || debug.termination_reason ||
    debug.conversation_relevance
  )

  return (
    <div className={`flex items-start gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div
        className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0 mt-0.5"
        style={isUser
          ? { background: 'linear-gradient(135deg, #2563eb, #0ea5e9)' }
          : { background: 'linear-gradient(135deg, rgba(219,234,254,0.9), rgba(186,230,253,0.72))' }
        }
      >
        {isUser ? <User size={15} style={{ color: '#fff' }} /> : <Bot size={15} className="text-violet-400" />}
      </div>

      <div className={`max-w-[80%] min-w-0 ${isUser ? 'items-end' : 'items-start'} flex flex-col`}>
        <div
          className={`px-4 py-3 text-sm leading-relaxed
            ${isUser
              ? 'rounded-2xl rounded-tr-lg text-white'
              : 'glass rounded-2xl rounded-tl-lg'
            }`}
          style={isUser
            ? { background: 'linear-gradient(135deg, #2563eb, #0ea5e9)', color: '#fff' }
            : undefined
          }
        >
          <div className="whitespace-pre-wrap break-words">{message.content}</div>
        </div>

        <div className={`flex items-center gap-2 mt-1.5 px-1 ${isUser ? 'flex-row-reverse' : ''}`}>
          <span className="text-[11px] text-zinc-600">
            {new Date(message.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
          </span>
        </div>

        {message.citations && message.citations.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {message.citations.map((c, i) => (
              <a
                key={i}
                href={c.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-lg
                           bg-violet-500/10 text-violet-400 border border-violet-500/15
                           hover:bg-violet-500/15 transition-colors"
              >
                <ExternalLink size={10} />
                {docTypeLabel(c.doc_type) || c.source_url || c.chunk_id}
              </a>
            ))}
          </div>
        )}

        {!isUser && hasDebug && (
          <div className="mt-2.5 w-full">
            <div className="flex flex-wrap items-center gap-1.5 mb-1.5">
              {debug.decision != null && (
                <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-medium bg-violet-500/10 text-violet-400 border border-violet-500/15">
                  <Zap size={10} />
                  {decisionLabel(debug.decision)}
                </span>
              )}
              {debug.confidence != null && (
                <ConfidenceBadge value={debug.confidence} />
              )}
              {debug.intent_cache && (
                  <span className="px-2.5 py-1 rounded-lg text-[11px] bg-sky-50 text-zinc-400 border border-sky-100">
                  意图命中：{debug.intent_cache}
                </span>
              )}
            </div>
            <button
              type="button"
              className="inline-flex items-center gap-1.5 text-[11px] text-zinc-600 hover:text-blue-700 transition-colors py-1"
              onClick={() => setShowFlow((v) => !v)}
            >
              {showFlow ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
              调试详情
            </button>
            {showFlow && <FlowDebugPanel debug={debug} />}
          </div>
        )}
      </div>
    </div>
  )
}

function ConfidenceBadge({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color = pct >= 80
    ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/15'
    : pct >= 50
      ? 'text-amber-400 bg-amber-500/10 border-amber-500/15'
      : 'text-red-400 bg-red-500/10 border-red-500/15'
  return (
    <span className={`px-2.5 py-1 rounded-lg text-[11px] font-medium border ${color}`}>
      {pct}%
    </span>
  )
}

function FlowDebugPanel({ debug }: { debug: FlowDebug }) {
  return (
    <div className="mt-2 glass rounded-2xl overflow-hidden text-xs animate-slide-up">
      {debug.trace && (
        <DebugSection icon={<Zap size={13} />} title="执行 Trace">
          <TraceTimeline trace={debug.trace} />
        </DebugSection>
      )}

      {debug.agentic_router && (
        <DebugSection icon={<Brain size={13} />} title="Agentic Router">
          <div className="space-y-1.5 text-zinc-400">
            {debug.agentic_router.route && <div>路由：<span className="text-zinc-300">{debug.agentic_router.route}</span></div>}
            {debug.agentic_router.tool && <div>工具：<span className="text-zinc-300">{debug.agentic_router.tool}</span></div>}
            {debug.agentic_router.reason && <div>原因：<span className="text-zinc-300">{debug.agentic_router.reason}</span></div>}
            {debug.agentic_router.confidence != null && <div>置信度：<span className="text-zinc-300">{(debug.agentic_router.confidence * 100).toFixed(1)}%</span></div>}
            {debug.agentic_router.fallback_to_rag && <div className="text-amber-400">已回退到 RAG</div>}
            {debug.agentic_router.skipped && <div className="text-zinc-500">已跳过</div>}
          </div>
        </DebugSection>
      )}

      {(debug.stage_reasons && debug.stage_reasons.length > 0) || debug.termination_reason ? (
        <DebugSection icon={<Zap size={13} />} title="决策路径">
          <div className="space-y-1.5 text-zinc-400">
            {debug.termination_reason && (
              <div>结束原因：<span className="text-zinc-300">{terminationReasonLabel(debug.termination_reason)}</span></div>
            )}
            {debug.stage_reasons && debug.stage_reasons.length > 0 && (
              <div>
                <div className="mb-1 text-zinc-500">流程时间线：</div>
                <ol className="list-decimal pl-4 space-y-0.5">
                  {debug.stage_reasons.map((s, i) => (
                    <li key={i} className="text-zinc-300 font-mono text-[11px]">{s}</li>
                  ))}
                </ol>
              </div>
            )}
          </div>
        </DebugSection>
      ) : null}

      {(debug.decision != null || debug.confidence != null || debug.followup_questions?.length || debug.decision_router?.reason_human) && (
        <DebugSection icon={<Zap size={13} />} title="决策与置信度">
          <div className="space-y-1.5 text-zinc-400">
            {debug.decision != null && <div>决策：<span className="text-zinc-300">{decisionLabel(debug.decision)}</span></div>}
            {debug.decision_router?.reason_human && (
              <div>原因：<span className="text-zinc-300">{debug.decision_router.reason_human}</span></div>
            )}
            {debug.confidence != null && <div>置信度：<span className="text-zinc-300">{(debug.confidence * 100).toFixed(1)}%</span></div>}
            {debug.followup_questions && debug.followup_questions.length > 0 && (
              <div>
                <div className="mb-1">追问问题：</div>
                <ul className="list-disc pl-4 space-y-0.5">
                  {debug.followup_questions.map((q, i) => <li key={i} className="text-zinc-300">{q}</li>)}
                </ul>
              </div>
            )}
          </div>
        </DebugSection>
      )}

      <DebugSection icon={<Brain size={13} />} title="追踪与模型">
        <div className="space-y-1 text-zinc-400">
          {debug.trace_id && <div>追踪 ID：<span className="font-mono text-zinc-500">{debug.trace_id}</span></div>}
          {debug.model_used && <div>模型：<span className="text-zinc-300">{debug.model_used}</span></div>}
          {debug.attempt != null && <div>尝试次数：<span className="text-zinc-300">{debug.attempt}</span></div>}
          {debug.intent_cache && <div>意图缓存：<span className="text-zinc-300">{debug.intent_cache}</span></div>}
          {debug.query_spec?.extraction_mode && (
            <div>查询提取：<span className="text-zinc-300">{queryExtractionModeLabel(debug.query_spec.extraction_mode)}</span></div>
          )}
        </div>
      </DebugSection>

      {debug.conversation_relevance && (
        <DebugSection icon={<MessageSquare size={13} />} title="会话相关性">
          <div className="space-y-1 text-zinc-400">
            <div>是否相关：<span className={debug.conversation_relevance.relevant ? 'text-emerald-400' : 'text-amber-400'}>{debug.conversation_relevance.relevant ? '是' : '否'}</span></div>
            {debug.conversation_relevance.reason && <div>原因：<span className="text-zinc-300">{debug.conversation_relevance.reason}</span></div>}
            {debug.conversation_relevance.relevant_turn_count != null && <div>使用轮次：<span className="text-zinc-300">{String(debug.conversation_relevance.relevant_turn_count)}</span></div>}
          </div>
        </DebugSection>
      )}

      {debug.query_rewrite && (
        <DebugSection icon={<Search size={13} />} title="查询改写">
          <div className="font-mono bg-sky-50 p-3 rounded-xl space-y-1.5 text-zinc-400 text-[11px] border border-sky-100">
            <div>关键词：<span className="text-zinc-300">{debug.query_rewrite.keyword_query}</span></div>
            <div>语义查询：<span className="text-zinc-300">{debug.query_rewrite.semantic_query}</span></div>
          </div>
        </DebugSection>
      )}

      {debug.retrieval_stats && (
        <DebugSection icon={<Database size={13} />} title="检索">
          <div className="space-y-2">
            <div className="flex flex-wrap gap-2">
              <StatPill label="BM25" value={debug.retrieval_stats.bm25_count} />
              <StatPill label="向量" value={debug.retrieval_stats.vector_count} />
              <StatPill label="合并" value={debug.retrieval_stats.merged_count} />
              <StatPill label="重排" value={debug.retrieval_stats.reranked_count} />
            </div>
            {debug.quality_report?.hard_requirement_coverage && Object.keys(debug.quality_report.hard_requirement_coverage).length > 0 && (
              <div>
                <div className="mb-1 text-zinc-500">硬性要求覆盖：</div>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(debug.quality_report.hard_requirement_coverage).map(([req, covered]) => (
                    <span
                      key={req}
                      className={`px-2 py-0.5 rounded text-[10px] ${covered ? 'bg-emerald-500/20 text-emerald-400' : 'bg-amber-500/20 text-amber-400'}`}
                    >
                      {req}: {covered ? '✓' : '✗'}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </DebugSection>
      )}

      {debug.evidence_summary && debug.evidence_summary.length > 0 && (
        <DebugSection icon={<FileText size={13} />} title={`证据（${debug.evidence_summary.length} 个片段）`}>
          <div className="space-y-2">
            {debug.evidence_summary.map((e, i) => (
              <div key={i} className="p-3 bg-sky-50 rounded-xl border border-sky-100">
                <div className="flex items-center gap-2 mb-1.5">
                  <a href={e.source_url} target="_blank" rel="noopener noreferrer" className="text-violet-400 hover:text-violet-300 text-xs">
                    {docTypeLabel(e.doc_type)} · {e.chunk_id.slice(0, 8)}
                  </a>
                  {e.score != null && (
                    <span className="text-zinc-600 text-[10px] ml-auto">分数：{e.score.toFixed(3)}</span>
                  )}
                </div>
                <div className="text-zinc-500 whitespace-pre-wrap break-words text-[11px] max-h-32 overflow-y-auto leading-relaxed">
                  {e.snippet}
                </div>
              </div>
            ))}
          </div>
        </DebugSection>
      )}

      {debug.prompt_preview && (
        <DebugSection icon={<FileText size={13} />} title="提示词预览">
          <div className="space-y-2.5">
            <div>
              <div className="text-zinc-600 mb-1">系统提示词（{debug.prompt_preview.system_length} 字符）</div>
              <pre className="font-mono text-[11px] whitespace-pre-wrap break-words bg-sky-50 p-3 rounded-xl text-zinc-500 max-h-96 overflow-y-auto border border-sky-100">
                {debug.prompt_preview.system_preview}
              </pre>
            </div>
            <div>
              <div className="text-zinc-600 mb-1">用户提示词（{debug.prompt_preview.user_length} 字符）</div>
              <pre className="font-mono text-[11px] whitespace-pre-wrap break-words bg-sky-50 p-3 rounded-xl text-zinc-500 max-h-96 overflow-y-auto border border-sky-100">
                {debug.prompt_preview.user_preview}
              </pre>
            </div>
          </div>
        </DebugSection>
      )}

      {(debug.llm_tokens || debug.cost_usd != null) && (
        <DebugSection icon={<Brain size={13} />} title="LLM 用量与成本">
          <div className="flex flex-wrap gap-3 items-center">
            {debug.llm_tokens && (
              <>
                <StatPill label="输入" value={debug.llm_tokens.input} />
                <StatPill label="输出" value={debug.llm_tokens.output} />
              </>
            )}
            {debug.cost_usd != null && debug.cost_usd > 0 && (
              <StatPill label="成本" value={`$${debug.cost_usd.toFixed(6)}`} />
            )}
          </div>
          {debug.llm_usage_breakdown && debug.llm_usage_breakdown.length > 0 && (
            <div className="mt-2 space-y-1 text-[11px] text-zinc-500">
              {debug.llm_usage_breakdown.map((u, i) => (
                <div key={i} className="flex gap-2">
                  <span className="text-zinc-400">{u.model}</span>
                  <span>in:{u.input} out:{u.output}</span>
                  <span className="text-emerald-400">${(u.cost_usd ?? 0).toFixed(6)}</span>
                </div>
              ))}
            </div>
          )}
        </DebugSection>
      )}

      {(debug.reviewer_reasons?.length || debug.claim_to_citation_map) && (
        <DebugSection icon={<AlertTriangle size={13} />} title="审核器">
          <div className="space-y-2 text-zinc-400">
            {debug.reviewer_reasons && debug.reviewer_reasons.length > 0 && (
              <ul className="list-disc pl-4 space-y-0.5">
                {debug.reviewer_reasons.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            )}
            {debug.claim_to_citation_map && Object.keys(debug.claim_to_citation_map).length > 0 && (
              <div>
                <div className="mb-1 text-zinc-500">结论 → 引用：</div>
                <div className="font-mono text-[11px] space-y-1">
                  {Object.entries(debug.claim_to_citation_map).slice(0, 5).map(([claim, ids]) => (
                    <div key={claim} className="break-words">
                      <span className="text-zinc-300">{claim.length > 50 ? claim.slice(0, 50) + '…' : claim}</span>
                      <span className="text-zinc-500"> → [{ids.join(', ')}]</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </DebugSection>
      )}

      {(debug.source_lang || debug.evidence_eval || debug.self_critic_regenerated || debug.final_polish_applied) && (
        <DebugSection icon={<Sparkles size={13} />} title="Archi v3">
          <div className="space-y-1.5 text-zinc-400">
            {debug.source_lang && (
              <div>源语言：<span className="text-zinc-300">{debug.source_lang}</span></div>
            )}
            {debug.evidence_eval && (
              <div className="space-y-1">
                {debug.evidence_eval.relevance_score != null && (
                  <div>相关性：<span className="text-zinc-300">{debug.evidence_eval.relevance_score.toFixed(2)}</span></div>
                )}
                {debug.evidence_eval.retry_needed != null && (
                  <div>是否需要重试：<span className="text-zinc-300">{debug.evidence_eval.retry_needed ? '是' : '否'}</span></div>
                )}
                {debug.evidence_eval.coverage_gaps && debug.evidence_eval.coverage_gaps.length > 0 && (
                  <div>
                    <div className="mb-0.5">覆盖缺口：</div>
                    <ul className="list-disc pl-4 text-[11px]">
                      {debug.evidence_eval.coverage_gaps.map((g, i) => <li key={i}>{g}</li>)}
                    </ul>
                  </div>
                )}
              </div>
            )}
            {debug.self_critic_regenerated && (
              <div className="text-amber-400">自我审查：已重新生成</div>
            )}
            {debug.final_polish_applied && (
              <div className="text-violet-400">最终润色：已应用</div>
            )}
          </div>
        </DebugSection>
      )}

      {debug.llm_call_log && debug.llm_call_log.length > 0 && (
        <DebugSection icon={<Brain size={13} />} title="LLM 调用日志（提示词与响应）">
          <div className="space-y-4">
            {debug.llm_call_log.map((call, i) => (
              <div key={i} className="p-3 bg-sky-50 rounded-xl border border-sky-100">
                <div className="flex items-center gap-2 mb-2 text-zinc-400">
                  <span className="font-medium text-violet-400">{call.task}</span>
                  <span className="text-[10px]">{call.model}</span>
                  <span className="text-[10px]">输入:{call.input_tokens} 输出:{call.output_tokens}</span>
                  <span className="text-emerald-500/80 text-[10px]">${call.cost_usd?.toFixed(6)}</span>
                </div>
                <div className="space-y-2 text-[11px]">
                  {call.messages?.map((m, j) => (
                    <div key={j}>
                      <div className="text-zinc-500 mb-0.5">{m.role}:</div>
                      <pre className="whitespace-pre-wrap break-words text-zinc-400 max-h-48 overflow-y-auto p-2 rounded bg-white border border-sky-100">
                        {m.content}
                      </pre>
                    </div>
                  ))}
                  <div>
                    <div className="text-zinc-500 mb-0.5">响应：</div>
                    <pre className="whitespace-pre-wrap break-words text-zinc-300 max-h-48 overflow-y-auto p-2 rounded bg-white border border-sky-100">
                      {call.response_content}
                    </pre>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </DebugSection>
      )}

      {debug.max_attempts_reached && (
        <div className="px-4 py-3 bg-amber-500/10 border-t border-white/[0.04] text-amber-400 text-xs flex items-center gap-2">
          <AlertTriangle size={12} />
          已达到最大检索尝试次数
        </div>
      )}
    </div>
  )
}

function isTraceEventData(value: unknown): value is TraceEventData {
  return Boolean(value && typeof value === 'object')
}

function mergeTraceEvent(prev: TraceSnapshot | null, event: TraceEventData): TraceSnapshot {
  const nodeId = event.node_id || 'unknown'
  const existingNodes = prev?.nodes ?? []
  const nextNode: TraceNode = {
    id: nodeId,
    label: traceNodeLabel(nodeId),
    status: event.status || 'running',
    latency_ms: event.latency_ms,
    selected_tool: event.selected_tool,
    decision_reason: event.decision_reason,
    tool_result: event.tool_result,
  }
  const nodes = existingNodes.some((node) => node.id === nodeId)
    ? existingNodes.map((node) => node.id === nodeId ? { ...node, ...nextNode } : node)
    : [...existingNodes, nextNode]
  return {
    ...(prev ?? {}),
    trace_id: event.trace_id ?? prev?.trace_id,
    selected_tool: event.selected_tool ?? prev?.selected_tool,
    decision_reason: event.decision_reason ?? prev?.decision_reason,
    node_path: event.node_path ?? prev?.node_path ?? nodes.map((node) => node.id),
    nodes,
  }
}

function TraceTimeline({ trace }: { trace?: TraceSnapshot | null }) {
  if (!trace) return null
  const nodes: TraceNode[] = trace.nodes?.length
    ? trace.nodes
    : (trace.node_path ?? []).map((id) => ({
        id,
        label: traceNodeLabel(id),
        status: 'completed',
        latency_ms: trace.latency?.nodes?.[id],
        selected_tool: null,
        decision_reason: null,
        tool_result: null,
      }))
  if (!nodes.length) return null
  return (
    <div className="mt-2 rounded-xl border border-sky-100 bg-sky-50 p-3 text-xs">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-zinc-500">
        {trace.selected_tool && <span>工具：<span className="text-zinc-300">{trace.selected_tool}</span></span>}
        {trace.decision_reason && <span>原因：<span className="text-zinc-300 break-all">{trace.decision_reason}</span></span>}
        {trace.latency?.total_ms != null && <span>耗时：<span className="text-zinc-300">{trace.latency.total_ms}ms</span></span>}
        {trace.intent?.matched && trace.intent.key && <span>意图：<span className="text-zinc-300">{trace.intent.key}</span></span>}
      </div>
      <ol className="space-y-1.5">
        {nodes.map((node) => (
          <li key={node.id} className="flex min-w-0 items-center gap-2">
            <span className={`h-2 w-2 shrink-0 rounded-full ${traceStatusClass(node.status)}`} />
            <span className="min-w-0 flex-1 truncate text-zinc-300">{node.label || traceNodeLabel(node.id)}</span>
            {node.selected_tool && <span className="hidden shrink-0 text-zinc-500 sm:inline">{node.selected_tool}</span>}
            {node.latency_ms != null && <span className="shrink-0 text-zinc-500">{node.latency_ms}ms</span>}
            <span className="shrink-0 text-zinc-500">{traceStatusLabel(node.status)}</span>
          </li>
        ))}
      </ol>
      {trace.tool_result && Object.keys(trace.tool_result).length > 0 && (
        <div className="mt-2 flex flex-wrap gap-2 text-zinc-500">
          {traceToolResultSummary(trace.tool_result).map((item) => (
            <span key={item} className="rounded-lg border border-sky-100 bg-white px-2 py-1">{item}</span>
          ))}
        </div>
      )}
    </div>
  )
}

function traceNodeLabel(id: string) {
  const labels: Record<string, string> = {
    guardrails: '安全检查',
    intent_cache: '意图缓存',
    agentic_router: 'Agentic Router',
    query_extract: '问题理解',
    retrieve: '知识检索',
    assess_evidence: '证据评估',
    retry: '检索重试',
    generate: '生成回答',
    verify: '回答校验',
    direct_response: '直接回复',
    clarify: '追问用户',
    human_handoff: '转人工',
  }
  return labels[id] || id.replace(/_/g, ' ')
}

function traceStatusClass(status?: string) {
  if (status === 'completed') return 'bg-emerald-400'
  if (status === 'running') return 'bg-violet-400 animate-pulse'
  if (status === 'skipped') return 'bg-zinc-500'
  if (status === 'fallback') return 'bg-amber-400'
  if (status === 'failed') return 'bg-red-400'
  return 'bg-zinc-600'
}

function traceStatusLabel(status?: string) {
  if (status === 'completed') return '完成'
  if (status === 'running') return '执行中'
  if (status === 'skipped') return '跳过'
  if (status === 'fallback') return '回退'
  if (status === 'failed') return '失败'
  return status || '待执行'
}

function traceToolResultSummary(result: Record<string, unknown>) {
  const items: string[] = []
  if (typeof result.decision === 'string') items.push(`决策：${result.decision}`)
  if (typeof result.citations_count === 'number') items.push(`引用：${result.citations_count}`)
  if (typeof result.followup_count === 'number') items.push(`追问：${result.followup_count}`)
  if (typeof result.confidence === 'number') items.push(`置信度：${Math.round(result.confidence * 100)}%`)
  return items.length ? items : Object.entries(result).slice(0, 4).map(([key, value]) => `${key}：${String(value)}`)
}

function DebugSection({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="px-4 py-3.5 border-b border-white/[0.04] last:border-b-0">
      <div className="flex items-center gap-2 text-zinc-500 font-medium mb-2.5">
        {icon}
        {title}
      </div>
      {children}
    </div>
  )
}

function StatPill({ label, value }: { label: string; value?: string | number | null }) {
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 bg-sky-50 rounded-lg border border-sky-100">
      <span className="text-zinc-500">{label}</span>
      <span className="text-zinc-300 font-medium">{value ?? '-'}</span>
    </div>
  )
}
