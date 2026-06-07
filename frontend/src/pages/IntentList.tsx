import { useState, useEffect } from 'react'
import { admin, type Intent, type IntentCreate } from '../api/client'
import {
  Plus,
  Trash2,
  Edit2,
  Loader2,
  MessageSquare,
  ChevronDown,
  ChevronRight,
  Check,
  X,
} from 'lucide-react'

export default function IntentList() {
  const [items, setItems] = useState<Intent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await admin.listIntents()
      setItems(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载意图缓存失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (!confirm('确定删除此意图？删除后将不再匹配用户查询。')) return
    try {
      await admin.deleteIntent(id)
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '删除失败')
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-3 py-24 animate-fade-in">
        <Loader2 size={22} className="animate-spin-slow text-accent" />
        <span className="text-zinc-500">正在加载意图缓存...</span>
      </div>
    )
  }

  return (
    <div className="animate-slide-up">
      <header className="flex justify-between items-start mb-8">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">意图缓存</h1>
          <p className="text-sm text-zinc-500 mt-1.5">
            为常见问题预设即时回答（例如“你是谁”“你能做什么”“你好”等）。
          </p>
        </div>
        <button
          className="btn-primary inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium"
          onClick={() => setShowCreateModal(true)}
        >
          <Plus size={16} />
          添加意图
        </button>
      </header>

      {error && (
        <div className="p-3.5 rounded-xl mb-5 bg-red-500/10 border border-red-500/20 text-red-300 text-sm">
          {error}
        </div>
      )}

      {items.length === 0 ? (
        <div className="flex flex-col items-center py-24 text-zinc-500 glass rounded-2xl">
          <MessageSquare size={40} className="mb-4 text-zinc-600" />
          <p className="font-semibold text-zinc-400 mb-1.5">暂无意图</p>
          <p className="text-sm mb-5">添加意图后，可对常见问题直接返回即时回答</p>
          <button
            className="btn-primary inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm"
            onClick={() => setShowCreateModal(true)}
          >
            <Plus size={16} />
            添加第一个意图
          </button>
        </div>
      ) : (
        <div className="space-y-2">
          {items.map((intent) => (
            <div
              key={intent.id}
              className="glass rounded-xl overflow-hidden"
            >
              <div
                className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-white/[0.03] transition-colors"
                onClick={() => setExpandedId(expandedId === intent.id ? null : intent.id)}
              >
                <button className="p-1 text-zinc-500">
                  {expandedId === intent.id ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                </button>
                <span
                  className={`px-2.5 py-1 rounded-lg text-xs font-medium ${
                    intent.enabled ? 'bg-emerald-500/20 text-emerald-400' : 'bg-zinc-500/20 text-zinc-500'
                  }`}
                >
                  {intent.enabled ? '开启' : '关闭'}
                </span>
                <span className="font-mono text-sm text-violet-400">{intent.key}</span>
                <span className="text-zinc-600">·</span>
                <span className="text-sm text-zinc-400 truncate flex-1">
                  {intent.answer.slice(0, 60)}
                  {intent.answer.length > 60 ? '…' : ''}
                </span>
                <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                  <button
                    className="p-2 rounded-lg text-zinc-500 hover:text-white hover:bg-white/5"
                    onClick={() => setEditingId(editingId === intent.id ? null : intent.id)}
                  >
                    <Edit2 size={14} />
                  </button>
                  <button
                    className="p-2 rounded-lg text-zinc-500 hover:text-red-400 hover:bg-red-500/10"
                    onClick={(e) => handleDelete(intent.id, e)}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
              {expandedId === intent.id && (
                <div className="px-4 pb-4 pt-0 border-t border-white/[0.04] mt-0">
                  <div className="mt-3 space-y-3 text-sm">
                    <div>
                      <div className="text-zinc-500 text-xs mb-1">匹配模式（正则）</div>
                      <pre className="font-mono text-xs text-zinc-300 bg-black/20 p-3 rounded-lg overflow-x-auto">
                        {intent.patterns}
                      </pre>
                    </div>
                    <div>
                      <div className="text-zinc-500 text-xs mb-1">回答</div>
                      <div className="text-zinc-300 bg-black/20 p-3 rounded-lg whitespace-pre-wrap">
                        {intent.answer}
                      </div>
                    </div>
                  </div>
                </div>
              )}
              {editingId === intent.id && (
                <IntentEditForm
                  intent={intent}
                  onSave={() => {
                    setEditingId(null)
                    load()
                  }}
                  onCancel={() => setEditingId(null)}
                />
              )}
            </div>
          ))}
        </div>
      )}

      {showCreateModal && (
        <IntentCreateModal
          onClose={() => setShowCreateModal(false)}
          onCreated={() => {
            setShowCreateModal(false)
            load()
          }}
        />
      )}
    </div>
  )
}

function IntentEditForm({
  intent,
  onSave,
  onCancel,
}: {
  intent: Intent
  onSave: () => void
  onCancel: () => void
}) {
  const [patterns, setPatterns] = useState(intent.patterns)
  const [answer, setAnswer] = useState(intent.answer)
  const [enabled, setEnabled] = useState(intent.enabled)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setErr(null)
    setSaving(true)
    try {
      await admin.updateIntent(intent.id, { patterns, answer, enabled })
      onSave()
    } catch (e) {
      setErr(e instanceof Error ? e.message : '更新失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="p-4 border-t border-white/[0.04] space-y-3">
      {err && <div className="text-red-400 text-sm">{err}</div>}
      <div>
        <label className="block text-xs text-zinc-500 mb-1">匹配模式（正则）</label>
        <textarea
          value={patterns}
          onChange={(e) => setPatterns(e.target.value)}
          rows={2}
          className="w-full px-3 py-2 rounded-lg input-glass text-sm font-mono"
          required
        />
      </div>
      <div>
        <label className="block text-xs text-zinc-500 mb-1">回答</label>
        <textarea
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          rows={4}
          className="w-full px-3 py-2 rounded-lg input-glass text-sm"
          required
        />
      </div>
      <label className="flex items-center gap-2 text-sm text-zinc-400">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
          className="rounded border-white/10"
        />
        启用
      </label>
      <div className="flex gap-2">
        <button type="submit" disabled={saving} className="btn-primary px-4 py-2 rounded-lg text-sm flex items-center gap-2">
          {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
          保存
        </button>
        <button type="button" onClick={onCancel} className="px-4 py-2 rounded-lg text-sm text-zinc-400 hover:text-white">
          取消
        </button>
      </div>
    </form>
  )
}

function IntentCreateModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [key, setKey] = useState('')
  const [patterns, setPatterns] = useState('')
  const [answer, setAnswer] = useState('')
  const [enabled, setEnabled] = useState(true)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setErr(null)
    setSaving(true)
    try {
      const data: IntentCreate = { key: key.trim(), patterns, answer, enabled }
      await admin.createIntent(data)
      onCreated()
    } catch (e) {
      setErr(e instanceof Error ? e.message : '创建失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="glass rounded-2xl p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-5">
          <h2 className="text-lg font-semibold text-white">添加意图</h2>
          <button onClick={onClose} className="p-2 rounded-lg text-zinc-500 hover:text-white">
            <X size={18} />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          {err && <div className="text-red-400 text-sm">{err}</div>}
          <div>
            <label className="block text-xs text-zinc-500 mb-1">标识（唯一 ID）</label>
            <input
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder="例如：who_are_you"
              className="w-full px-3 py-2 rounded-lg input-glass text-sm font-mono"
              required
            />
          </div>
          <div>
            <label className="block text-xs text-zinc-500 mb-1">匹配模式（正则，可每行一个或组合填写）</label>
            <textarea
              value={patterns}
              onChange={(e) => setPatterns(e.target.value)}
              placeholder={"\\b(你是谁|你能做什么|你好)\\b"}
              rows={3}
              className="w-full px-3 py-2 rounded-lg input-glass text-sm font-mono"
              required
            />
          </div>
          <div>
            <label className="block text-xs text-zinc-500 mb-1">回答</label>
            <textarea
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              placeholder="我是客服助手，可以根据知识库回答产品、价格、政策和操作问题。"
              rows={4}
              className="w-full px-3 py-2 rounded-lg input-glass text-sm"
              required
            />
          </div>
          <label className="flex items-center gap-2 text-sm text-zinc-400">
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} className="rounded border-white/10" />
            启用
          </label>
          <div className="flex gap-2 pt-2">
            <button type="submit" disabled={saving} className="btn-primary px-4 py-2.5 rounded-xl text-sm flex items-center gap-2">
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
              创建
            </button>
            <button type="button" onClick={onClose} className="px-4 py-2.5 rounded-xl text-sm text-zinc-400 hover:text-white">
              取消
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
