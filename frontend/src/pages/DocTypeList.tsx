import { useState, useEffect } from 'react'
import { admin, type DocType, type DocTypeCreate, type DocTypeUpdate } from '../api/client'
import {
  Plus,
  Trash2,
  Edit2,
  Loader2,
  FileType,
  ChevronDown,
  ChevronRight,
  Check,
  X,
} from 'lucide-react'

export default function DocTypeList() {
  const [items, setItems] = useState<DocType[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await admin.listDocTypes()
      setItems(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载文档类型失败')
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
    if (!confirm('确定删除此文档类型？使用它的文档可能会显示为“other”。')) return
    try {
      await admin.deleteDocType(id)
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '删除失败')
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-3 py-24 animate-fade-in">
        <Loader2 size={22} className="animate-spin-slow text-accent" />
        <span className="text-zinc-500">正在加载文档类型...</span>
      </div>
    )
  }

  return (
    <div className="animate-slide-up">
      <header className="flex justify-between items-start mb-8">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">文档类型</h1>
          <p className="text-sm text-zinc-500 mt-1.5">
            用于分类器和文档表单的文档类型目录（policy、faq、howto 等）。
          </p>
        </div>
        <button
          className="btn-primary inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium"
          onClick={() => setShowCreateModal(true)}
        >
          <Plus size={16} />
          添加文档类型
        </button>
      </header>

      {error && (
        <div className="p-3.5 rounded-xl mb-5 bg-red-500/10 border border-red-500/20 text-red-300 text-sm">
          {error}
        </div>
      )}

      {items.length === 0 ? (
        <div className="flex flex-col items-center py-24 text-zinc-500 glass rounded-2xl">
          <FileType size={40} className="mb-4 text-zinc-600" />
          <p className="font-semibold text-zinc-400 mb-1.5">暂无文档类型</p>
          <p className="text-sm mb-5">添加文档类型后，可用于文档分类和表单选择</p>
          <button
            className="btn-primary inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm"
            onClick={() => setShowCreateModal(true)}
          >
            <Plus size={16} />
            添加第一个文档类型
          </button>
        </div>
      ) : (
        <div className="space-y-2">
          {items.map((dt) => (
            <div key={dt.id} className="glass rounded-xl overflow-hidden">
              <div
                className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-white/[0.03] transition-colors"
                onClick={() => setExpandedId(expandedId === dt.id ? null : dt.id)}
              >
                <button className="p-1 text-zinc-500">
                  {expandedId === dt.id ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                </button>
                <span
                  className={`px-2.5 py-1 rounded-lg text-xs font-medium ${
                    dt.enabled ? 'bg-emerald-500/20 text-emerald-400' : 'bg-zinc-500/20 text-zinc-500'
                  }`}
                >
                  {dt.enabled ? '开启' : '关闭'}
                </span>
                <span className="font-mono text-sm text-violet-400">{dt.key}</span>
                <span className="text-zinc-600">·</span>
                <span className="text-sm text-zinc-400 truncate flex-1">{dt.label}</span>
                <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                  <button
                    className="p-2 rounded-lg text-zinc-500 hover:text-white hover:bg-white/5"
                    onClick={() => setEditingId(editingId === dt.id ? null : dt.id)}
                  >
                    <Edit2 size={14} />
                  </button>
                  <button
                    className="p-2 rounded-lg text-zinc-500 hover:text-red-400 hover:bg-red-500/10"
                    onClick={(e) => handleDelete(dt.id, e)}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
              {expandedId === dt.id && (
                <div className="px-4 pb-4 pt-0 border-t border-white/[0.04] mt-0">
                  <div className="mt-3 space-y-3 text-sm">
                    {dt.description && (
                      <div>
                        <div className="text-zinc-500 text-xs mb-1">描述</div>
                        <div className="text-zinc-300 bg-black/20 p-3 rounded-lg">{dt.description}</div>
                      </div>
                    )}
                  </div>
                </div>
              )}
              {editingId === dt.id && (
                <DocTypeEditForm
                  docType={dt}
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
        <DocTypeCreateModal
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

function DocTypeEditForm({
  docType,
  onSave,
  onCancel,
}: {
  docType: DocType
  onSave: () => void
  onCancel: () => void
}) {
  const [label, setLabel] = useState(docType.label)
  const [description, setDescription] = useState(docType.description ?? '')
  const [enabled, setEnabled] = useState(docType.enabled)
  const [sortOrder, setSortOrder] = useState(docType.sort_order)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setErr(null)
    setSaving(true)
    try {
      const data: DocTypeUpdate = { label, description: description || null, enabled, sort_order: sortOrder }
      await admin.updateDocType(docType.id, data)
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
        <label className="block text-xs text-zinc-500 mb-1">标签</label>
        <input
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          className="w-full px-3 py-2 rounded-lg input-glass text-sm"
          required
        />
      </div>
      <div>
        <label className="block text-xs text-zinc-500 mb-1">描述</label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
          className="w-full px-3 py-2 rounded-lg input-glass text-sm"
          placeholder="例如：隐私政策、数据政策..."
        />
      </div>
      <div>
        <label className="block text-xs text-zinc-500 mb-1">排序值</label>
        <input
          type="number"
          value={sortOrder}
          onChange={(e) => setSortOrder(parseInt(e.target.value, 10) || 0)}
          className="w-full px-3 py-2 rounded-lg input-glass text-sm"
        />
      </div>
      <label className="flex items-center gap-2 text-sm text-zinc-400">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
          className="rounded border-white/10"
        />
        启用（用于分类器和表单）
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

function DocTypeCreateModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [key, setKey] = useState('')
  const [label, setLabel] = useState('')
  const [description, setDescription] = useState('')
  const [enabled, setEnabled] = useState(true)
  const [sortOrder, setSortOrder] = useState(0)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setErr(null)
    setSaving(true)
    try {
      const data: DocTypeCreate = {
        key: key.trim().toLowerCase().replace(/\s+/g, '_'),
        label: label.trim(),
        description: description.trim() || null,
        enabled,
        sort_order: sortOrder,
      }
      await admin.createDocType(data)
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
          <h2 className="text-lg font-semibold text-white">添加文档类型</h2>
          <button onClick={onClose} className="p-2 rounded-lg text-zinc-500 hover:text-white">
            <X size={18} />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          {err && <div className="text-red-400 text-sm">{err}</div>}
          <div>
            <label className="block text-xs text-zinc-500 mb-1">Key（唯一 ID，小写）</label>
            <input
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder="例如：policy, faq, howto"
              className="w-full px-3 py-2 rounded-lg input-glass text-sm font-mono"
              required
            />
          </div>
          <div>
            <label className="block text-xs text-zinc-500 mb-1">标签</label>
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="例如：政策"
              className="w-full px-3 py-2 rounded-lg input-glass text-sm"
              required
            />
          </div>
          <div>
            <label className="block text-xs text-zinc-500 mb-1">描述</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="例如：隐私政策、数据政策、通用政策"
              rows={2}
              className="w-full px-3 py-2 rounded-lg input-glass text-sm"
            />
          </div>
          <div>
            <label className="block text-xs text-zinc-500 mb-1">排序值</label>
            <input
              type="number"
              value={sortOrder}
              onChange={(e) => setSortOrder(parseInt(e.target.value, 10) || 0)}
              className="w-full px-3 py-2 rounded-lg input-glass text-sm"
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
