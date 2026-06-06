import { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { conversations, type Conversation, type SourceType } from '../api/client'
import {
  Plus,
  Trash2,
  ExternalLink,
  ChevronLeft,
  ChevronRight,
  Loader2,
  MessageSquare,
  Ticket,
  Radio,
  X,
  Sparkles,
} from 'lucide-react'

export default function ConversationList() {
  const navigate = useNavigate()
  const [items, setItems] = useState<Conversation[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showCreateModal, setShowCreateModal] = useState(false)
  const pageSize = 15

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await conversations.list(page, pageSize)
      setItems(res.items)
      setTotal(res.total)
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载数据失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [page])

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (!confirm('确定要删除这条会话吗？')) return
    try {
      await conversations.delete(id)
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '删除失败')
    }
  }

  const totalPages = Math.ceil(total / pageSize)

  return (
    <div className="animate-slide-up">
      <header className="flex justify-between items-start mb-8">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">会话</h1>
          <p className="text-sm text-zinc-500 mt-1.5">管理并查看所有客户会话</p>
        </div>
        <button
          className="btn-primary inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium"
          onClick={() => setShowCreateModal(true)}
        >
          <Plus size={16} />
          新建会话
        </button>
      </header>

      {error && (
        <div className="flex items-center gap-2 p-3.5 rounded-xl mb-5 bg-danger/10 border border-danger/20 text-red-300 text-sm animate-fade-in">
          {error}
        </div>
      )}

      <div className="glass rounded-2xl overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center gap-3 py-20 text-zinc-500">
            <Loader2 size={20} className="animate-spin-slow text-accent" />
            <span className="text-sm">正在加载会话...</span>
          </div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center py-20 text-zinc-500">
            <div className="w-16 h-16 rounded-2xl glass-accent flex items-center justify-center mb-5 glow-sm">
              <MessageSquare size={28} className="text-violet-400" />
            </div>
            <p className="font-semibold text-zinc-300 mb-1.5">暂无会话</p>
            <p className="text-sm mb-5 text-zinc-500">创建第一条会话以开始使用</p>
            <button
              className="btn-primary inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium"
              onClick={() => setShowCreateModal(true)}
            >
              <Sparkles size={15} />
              创建会话
            </button>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/[0.04]">
                <th className="px-5 py-3.5 text-left text-zinc-500 font-medium text-xs uppercase tracking-wider">ID</th>
                <th className="px-5 py-3.5 text-left text-zinc-500 font-medium text-xs uppercase tracking-wider">来源</th>
                <th className="px-5 py-3.5 text-left text-zinc-500 font-medium text-xs uppercase tracking-wider">来源 ID</th>
                <th className="px-5 py-3.5 text-left text-zinc-500 font-medium text-xs uppercase tracking-wider">创建时间</th>
                <th className="px-5 py-3.5 text-right text-zinc-500 font-medium text-xs uppercase tracking-wider">操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr
                  key={c.id}
                  className="border-b border-white/[0.03] last:border-b-0 hover:bg-white/[0.02] transition-colors duration-200 cursor-pointer group"
                  onClick={() => navigate(`/conversations/${c.id}`)}
                >
                  <td className="px-5 py-4">
                    <code className="text-xs text-violet-400 bg-violet-500/10 px-2 py-1 rounded-lg font-mono">
                      {c.id.slice(0, 8)}
                    </code>
                  </td>
                  <td className="px-5 py-4">
                    <SourceBadge type={c.source_type} />
                  </td>
                  <td className="px-5 py-4 text-zinc-400">{c.source_id}</td>
                  <td className="px-5 py-4 text-zinc-400">
                    {new Date(c.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                    <span className="text-zinc-600 ml-1.5 text-xs">
                      {new Date(c.created_at).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </td>
                  <td className="px-5 py-4">
                    <div className="flex items-center justify-end gap-1.5 opacity-0 group-hover:opacity-100 transition-all duration-200">
                      <Link
                        to={`/conversations/${c.id}`}
                        className="p-2 rounded-lg text-zinc-500 hover:text-white hover:bg-white/[0.06] transition-colors"
                        onClick={(e) => e.stopPropagation()}
                        title="查看"
                      >
                        <ExternalLink size={14} />
                      </Link>
                      <button
                        className="p-2 rounded-lg text-zinc-500 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                        onClick={(e) => handleDelete(c.id, e)}
                        title="删除"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-5">
          <span className="text-sm text-zinc-500">
            共 {total} 条 · 第 {page} / {totalPages} 页
          </span>
          <div className="flex items-center gap-1">
            <button
              className="p-2 rounded-xl text-zinc-500 hover:text-white hover:bg-white/[0.05] disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
            >
              <ChevronLeft size={18} />
            </button>
            {Array.from({ length: Math.min(totalPages, 5) }, (_, i) => {
              const p = page <= 3 ? i + 1 : page + i - 2
              if (p < 1 || p > totalPages) return null
              return (
                <button
                  key={p}
                  className={`w-9 h-9 rounded-xl text-sm font-medium transition-all duration-200
                    ${p === page
                      ? 'btn-primary'
                      : 'text-zinc-500 hover:text-white hover:bg-white/[0.05]'
                    }`}
                  onClick={() => setPage(p)}
                >
                  {p}
                </button>
              )
            })}
            <button
              className="p-2 rounded-xl text-zinc-500 hover:text-white hover:bg-white/[0.05] disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => p + 1)}
            >
              <ChevronRight size={18} />
            </button>
          </div>
        </div>
      )}

      {showCreateModal && (
        <CreateConversationModal
          onSuccess={(conv) => {
            setShowCreateModal(false)
            navigate(`/conversations/${conv.id}`)
          }}
          onCancel={() => setShowCreateModal(false)}
        />
      )}
    </div>
  )
}

function SourceBadge({ type }: { type: string }) {
  const isTicket = type === 'ticket'
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-lg
        ${isTicket
          ? 'bg-amber-500/10 text-amber-400 border border-amber-500/15'
          : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/15'
        }`}
    >
      {isTicket ? <Ticket size={12} /> : <Radio size={12} />}
      {type === 'ticket' ? '工单会话' : '在线聊天会话'}
    </span>
  )
}

function CreateConversationModal({
  onSuccess,
  onCancel,
}: {
  onSuccess: (c: Conversation) => void
  onCancel: () => void
}) {
  const [sourceType, setSourceType] = useState<SourceType>('ticket')
  const [sourceId, setSourceId] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async () => {
    if (!sourceId.trim()) {
      setError('请输入会话 ID')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const conv = await conversations.create(sourceType, sourceId.trim())
      onSuccess(conv)
    } catch (e) {
      setError(e instanceof Error ? e.message : '创建失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-md flex items-center justify-center z-[1000] p-4 animate-fade-in" onClick={onCancel}>
      <div
        className="glass rounded-2xl w-full max-w-[480px] shadow-2xl animate-slide-up gradient-border"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center px-6 py-5 border-b border-white/[0.04]">
          <h2 className="text-base font-semibold text-white">新建会话</h2>
          <button
            className="p-2 rounded-xl text-zinc-500 hover:text-white hover:bg-white/[0.06] transition-colors"
            onClick={onCancel}
            aria-label="关闭"
          >
            <X size={18} />
          </button>
        </div>
        <div className="p-6 space-y-4">
          {error && (
            <div className="p-3.5 rounded-xl bg-danger/10 border border-danger/20 text-red-300 text-sm">
              {error}
            </div>
          )}
          <div>
            <label className="block text-sm font-medium text-zinc-400 mb-2">会话来源</label>
            <select
              value={sourceType}
              onChange={(e) => setSourceType(e.target.value as SourceType)}
              className="w-full px-4 py-2.5 rounded-xl input-glass text-sm"
              aria-label="来源类型"
            >
              <option value="ticket">工单会话</option>
              <option value="livechat">在线聊天会话</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-zinc-400 mb-2">会话 ID</label>
            <input
              type="text"
              placeholder="例如：会话 ID"
              value={sourceId}
              onChange={(e) => setSourceId(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
              className="w-full px-4 py-2.5 rounded-xl input-glass text-sm"
              aria-label="ID"
            />
          </div>
        </div>
        <div className="flex justify-end gap-2.5 px-6 py-5 border-t border-white/[0.04]">
          <button
            className="btn-ghost px-4 py-2.5 rounded-xl text-sm font-medium"
            onClick={onCancel}
          >
            取消
          </button>
          <button
            className="btn-primary inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
            onClick={handleSubmit}
            disabled={submitting}
          >
            {submitting && <Loader2 size={14} className="animate-spin-slow" />}
            {submitting ? '创建中...' : '创建'}
          </button>
        </div>
      </div>
    </div>
  )
}
