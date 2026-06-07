import { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { documents, admin, docTypeLabel, type Document, type DocType } from '../api/client'
import {
  Plus,
  Trash2,
  ExternalLink,
  ChevronLeft,
  ChevronRight,
  Loader2,
  FileText,
  Search,
  Filter,
  X,
  Layers,
  Download,
  Database,
  Upload,
  Globe,
  Sparkles,
  RefreshCw,
} from 'lucide-react'

const DOC_TYPE_COLORS: Record<string, string> = {
  policy: 'text-blue-400 bg-blue-500/10 border-blue-500/15',
  tos: 'text-purple-400 bg-purple-500/10 border-purple-500/15',
  faq: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/15',
  howto: 'text-cyan-400 bg-cyan-500/10 border-cyan-500/15',
  pricing: 'text-amber-400 bg-amber-500/10 border-amber-500/15',
  other: 'text-zinc-400 bg-white/[0.03] border-white/[0.06]',
}

export default function DocumentList() {
  const navigate = useNavigate()
  const [items, setItems] = useState<Document[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [filterDocType, setFilterDocType] = useState<string>('')
  const [filterQ, setFilterQ] = useState('')
  const [filterQApplied, setFilterQApplied] = useState('')
  const [ingesting, setIngesting] = useState(false)
  const [ingestResult, setIngestResult] = useState<{ ok: number; skipped: number; error: number } | null>(null)
  const [showUploadModal, setShowUploadModal] = useState(false)
  const [showCrawlModal, setShowCrawlModal] = useState(false)
  const [reCrawlAllLoading, setReCrawlAllLoading] = useState(false)
  const [reCrawlAllResult, setReCrawlAllResult] = useState<{ total: number; updated: number; skipped: number; error: number; errors: string[] } | null>(null)
  const [reCrawlId, setReCrawlId] = useState<string | null>(null)
  const [docTypes, setDocTypes] = useState<DocType[]>([])
  const pageSize = 15

  const docTypeOptions = docTypes

  useEffect(() => {
    admin.listDocTypes().then(setDocTypes).catch(() => {})
  }, [])

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await documents.list(page, pageSize, filterDocType || undefined, filterQApplied || undefined)
      setItems(res.items)
      setTotal(res.total)
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载文档失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    setPage(1)
  }, [filterDocType, filterQApplied])

  useEffect(() => {
    load()
  }, [page, filterDocType, filterQApplied])

  useEffect(() => {
    if (!ingestResult) return
    const t = setTimeout(() => setIngestResult(null), 5000)
    return () => clearTimeout(t)
  }, [ingestResult])

  useEffect(() => {
    if (!reCrawlAllResult) return
    const t = setTimeout(() => setReCrawlAllResult(null), 6000)
    return () => clearTimeout(t)
  }, [reCrawlAllResult])

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (!confirm('确定要删除这个文档吗？相关分块和索引也会被移除。')) return
    try {
      await documents.delete(id)
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '删除失败')
    }
  }

  const handleReCrawlAll = async () => {
    if (!confirm('确定要重新抓取所有包含 http(s) URL 的文档吗？这会获取最新内容并重新入库。')) return
    setReCrawlAllLoading(true)
    setError(null)
    setReCrawlAllResult(null)
    try {
      const res = await documents.reCrawlAll()
      setReCrawlAllResult({ total: res.total, updated: res.updated, skipped: res.skipped, error: res.error, errors: res.errors || [] })
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '重新抓取失败')
    } finally {
      setReCrawlAllLoading(false)
    }
  }

  const handleReCrawl = async (id: string, e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setReCrawlId(id)
    setError(null)
    try {
      await documents.reCrawl(id)
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '重新抓取失败')
    } finally {
      setReCrawlId(null)
    }
  }

  const isCrawlable = (url: string) => url && (url.startsWith('http://') || url.startsWith('https://'))

  const handleIngestFromSource = async () => {
    if (!confirm('确定要从 source/ 目录导入文档吗（custom_docs.json、sample_docs.json、sample_conversations.json 等）？')) return
    setIngesting(true)
    setError(null)
    setIngestResult(null)
    try {
      const res = await admin.ingestFromSource()
      setIngestResult(res.results ?? null)
      load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '导入失败')
    } finally {
      setIngesting(false)
    }
  }

  const totalPages = Math.ceil(total / pageSize)
  const visibleChunks = items.reduce((sum, item) => sum + item.chunks_count, 0)
  const crawlableCount = items.filter((item) => isCrawlable(item.source_url)).length
  const hasActiveFilters = Boolean(filterDocType || filterQApplied)
  const activeFilterCount = Number(Boolean(filterDocType)) + Number(Boolean(filterQApplied))

  return (
    <div className="space-y-6 animate-slide-up">
      <header className="relative overflow-hidden rounded-[28px] border border-white/8 bg-[linear-gradient(135deg,rgba(12,20,33,0.95),rgba(10,14,24,0.92))] shadow-[0_24px_70px_rgba(0,0,0,0.35)]">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(6,182,212,0.16),transparent_36%),radial-gradient(circle_at_left,rgba(59,130,246,0.12),transparent_30%)]" />
        <div className="relative p-6 lg:p-7">
          <div className="flex flex-col gap-6 xl:flex-row xl:items-start xl:justify-between">
            <div className="max-w-3xl">
              <div className="inline-flex items-center gap-2 rounded-full border border-cyan-400/20 bg-cyan-400/8 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.24em] text-cyan-300">
                <Database size={12} />
                知识库
              </div>
              <h1 className="mt-4 text-3xl font-semibold tracking-tight text-white sm:text-[2rem]">文档库</h1>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400 sm:text-[15px]">
                管理检索文档、刷新在线来源，并保持知识库内容整洁，以提高回答准确性。
              </p>
            </div>

            <div className="grid w-full gap-3 sm:grid-cols-2 xl:w-auto xl:min-w-[460px]">
              <div className="rounded-2xl border border-white/8 bg-white/[0.03] p-4 backdrop-blur-md">
                <div className="flex items-center justify-between text-xs uppercase tracking-[0.2em] text-zinc-500">
                  <span>文档总数</span>
                  <FileText size={14} className="text-cyan-300" />
                </div>
                <div className="mt-3 text-3xl font-semibold tracking-tight text-white">{total.toLocaleString()}</div>
                <div className="mt-1 text-xs text-zinc-500">覆盖所有已索引来源</div>
              </div>
              <div className="rounded-2xl border border-white/8 bg-white/[0.03] p-4 backdrop-blur-md">
                <div className="flex items-center justify-between text-xs uppercase tracking-[0.2em] text-zinc-500">
                  <span>当前页展示</span>
                  <Layers size={14} className="text-emerald-300" />
                </div>
                <div className="mt-3 text-3xl font-semibold tracking-tight text-white">{items.length}</div>
                <div className="mt-1 text-xs text-zinc-500">当前视图包含 {visibleChunks.toLocaleString()} 个分块</div>
              </div>
              <div className="rounded-2xl border border-white/8 bg-white/[0.03] p-4 backdrop-blur-md">
                <div className="flex items-center justify-between text-xs uppercase tracking-[0.2em] text-zinc-500">
                  <span>HTTP 来源</span>
                  <Globe size={14} className="text-blue-300" />
                </div>
                <div className="mt-3 text-3xl font-semibold tracking-tight text-white">{crawlableCount}</div>
                <div className="mt-1 text-xs text-zinc-500">当前可重新抓取</div>
              </div>
              <div className="rounded-2xl border border-white/8 bg-white/[0.03] p-4 backdrop-blur-md">
                <div className="flex items-center justify-between text-xs uppercase tracking-[0.2em] text-zinc-500">
                  <span>筛选条件</span>
                  <Filter size={14} className="text-amber-300" />
                </div>
                <div className="mt-3 text-3xl font-semibold tracking-tight text-white">{activeFilterCount}</div>
                <div className="mt-1 text-xs text-zinc-500">{hasActiveFilters ? '当前为自定义视图' : '正在显示全部文档'}</div>
              </div>
            </div>
          </div>

          <div className="mt-6 border-t border-white/[0.06] pt-5">
            <div className="flex flex-wrap gap-2.5">
              <button
                className="btn-primary inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium"
                onClick={() => setShowCreateModal(true)}
              >
                <Plus size={16} />
                添加文档
              </button>
              <button
                className="btn-ghost inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium"
                onClick={() => setShowUploadModal(true)}
              >
                <Upload size={15} />
                上传文件
              </button>
              <button
                className="btn-ghost inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium"
                onClick={() => setShowCrawlModal(true)}
                title="抓取整个网站并将所有页面作为文档添加"
              >
                <Globe size={15} />
                抓取网站
              </button>
              <button
                className="btn-ghost inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                onClick={handleIngestFromSource}
                disabled={ingesting}
                title="从 source/custom_docs.json、sample_docs.json、sample_conversations.json 等文件导入"
              >
                {ingesting ? <Loader2 size={15} className="animate-spin-slow" /> : <Database size={15} />}
                {ingesting ? '导入中...' : '从 source 导入'}
              </button>
              <button
                className="btn-ghost inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                onClick={handleReCrawlAll}
                disabled={reCrawlAllLoading}
                title="重新抓取所有包含 http(s) URL 的文档"
              >
                {reCrawlAllLoading ? <Loader2 size={16} className="animate-spin-slow" /> : <RefreshCw size={16} />}
                重新抓取全部（更新内容）
              </button>
            </div>
          </div>
        </div>
      </header>

      <section className="glass rounded-[24px] border border-white/[0.06] p-4 sm:p-5">
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="text-sm font-semibold text-white">筛选文档</div>
              <div className="text-xs text-zinc-500">可按类型筛选，或按标题和来源 URL 搜索。</div>
            </div>
            <div className="text-xs text-zinc-500">
              {hasActiveFilters ? `已启用 ${activeFilterCount} 个筛选条件` : '未启用筛选条件'}
            </div>
          </div>

          <div className="grid gap-3 lg:grid-cols-[minmax(180px,220px)_minmax(260px,1fr)_auto_auto]">
            <div className="relative">
              <Filter size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-zinc-600 pointer-events-none" />
              <select
                value={filterDocType}
                onChange={(e) => setFilterDocType(e.target.value)}
                className="w-full min-w-0 appearance-none rounded-xl border border-white/[0.06] bg-white/[0.03] py-2.5 pl-9 pr-4 text-sm text-zinc-200"
                aria-label="按类型筛选"
              >
                <option value="">全部类型</option>
                {docTypeOptions.map((t) => (
                  <option key={t.key} value={t.key}>{t.label}</option>
                ))}
              </select>
            </div>
            <div className="relative">
              <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-zinc-600 pointer-events-none" />
              <input
                type="search"
                placeholder="搜索标题、来源 URL 或关键词"
                value={filterQ}
                onChange={(e) => setFilterQ(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && setFilterQApplied(filterQ.trim())}
                className="w-full rounded-xl border border-white/[0.06] bg-white/[0.03] py-2.5 pl-9 pr-4 text-sm text-zinc-200 placeholder:text-zinc-600"
                aria-label="搜索"
              />
            </div>
            <button
              className="btn-ghost px-4 py-2.5 rounded-xl text-sm font-medium"
              onClick={() => setFilterQApplied(filterQ.trim())}
            >
              搜索
            </button>
            <button
              className={`px-4 py-2.5 rounded-xl text-sm font-medium transition-colors ${
                hasActiveFilters
                  ? 'text-zinc-300 hover:bg-white/[0.05] hover:text-white'
                  : 'text-zinc-600 cursor-not-allowed'
              }`}
              onClick={() => {
                if (!hasActiveFilters) return
                setFilterDocType('')
                setFilterQ('')
                setFilterQApplied('')
              }}
              disabled={!hasActiveFilters}
            >
              清空
            </button>
          </div>
        </div>
      </section>

      {error && (
        <div className="flex items-center gap-2 rounded-2xl border border-danger/20 bg-danger/10 px-4 py-3.5 text-sm text-red-300 animate-fade-in">
          {error}
        </div>
      )}
      {ingestResult && (
        <div className="flex items-center gap-2 rounded-2xl border border-emerald-500/20 bg-emerald-500/10 px-4 py-3.5 text-sm text-emerald-300 animate-fade-in">
          导入完成：新增 {ingestResult.ok}，跳过 {ingestResult.skipped}，错误 {ingestResult.error}
        </div>
      )}
      {reCrawlAllResult && (
        <div className="flex flex-col gap-1 rounded-2xl border border-cyan-500/20 bg-cyan-500/10 px-4 py-3.5 text-sm text-cyan-300 animate-fade-in">
          <span>重新抓取完成：更新 {reCrawlAllResult.updated}，未变化 {reCrawlAllResult.skipped}，错误 {reCrawlAllResult.error}</span>
          {reCrawlAllResult.errors.length > 0 && (
            <ul className="mt-1 list-disc pl-4 text-xs text-cyan-400/90">
              {reCrawlAllResult.errors.slice(0, 5).map((err, i) => <li key={i}>{err}</li>)}
            </ul>
          )}
        </div>
      )}

      <div className="glass overflow-hidden rounded-[24px] border border-white/[0.06]">
        {loading ? (
          <div className="flex items-center justify-center gap-3 py-20 text-zinc-500">
            <Loader2 size={20} className="animate-spin-slow text-accent" />
            <span className="text-sm">正在加载文档...</span>
          </div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center py-20 text-zinc-500">
            <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-2xl border border-cyan-500/15 bg-cyan-500/10">
              <FileText size={28} className="text-cyan-300" />
            </div>
            <p className="mb-1.5 font-semibold text-zinc-200">未找到文档</p>
            <p className="mb-5 text-sm">
              {hasActiveFilters ? '请尝试放宽筛选条件或搜索关键词。' : '添加第一份文档以开始填充文档库。'}
            </p>
            {!hasActiveFilters && (
              <button
                className="btn-primary inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium"
                onClick={() => setShowCreateModal(true)}
              >
                <Sparkles size={15} />
                添加文档
              </button>
            )}
          </div>
        ) : (
          <>
            <div className="flex flex-col gap-2 border-b border-white/[0.04] px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <div className="text-sm font-medium text-zinc-200">当前文档列表</div>
                <div className="text-xs text-zinc-500">
                  显示 {items.length} / {total.toLocaleString()} 份文档
                </div>
              </div>
              <div className="text-xs text-zinc-500">
                {hasActiveFilters ? `已应用 ${activeFilterCount} 条筛选规则` : '按最近更新时间排序'}
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full min-w-[940px] text-sm">
                <thead>
                  <tr className="border-b border-white/[0.04] bg-white/[0.015]">
                    <th className="px-5 py-3.5 text-left text-xs font-medium uppercase tracking-wider text-zinc-500">ID</th>
                    <th className="px-5 py-3.5 text-left text-xs font-medium uppercase tracking-wider text-zinc-500">文档</th>
                    <th className="px-5 py-3.5 text-left text-xs font-medium uppercase tracking-wider text-zinc-500">类型</th>
                    <th className="px-5 py-3.5 text-left text-xs font-medium uppercase tracking-wider text-zinc-500">分块数</th>
                    <th className="px-5 py-3.5 text-left text-xs font-medium uppercase tracking-wider text-zinc-500">更新时间</th>
                    <th className="px-5 py-3.5 text-right text-xs font-medium uppercase tracking-wider text-zinc-500">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((d) => (
                    <tr
                      key={d.id}
                      className="cursor-pointer border-b border-white/[0.03] last:border-b-0 transition-colors duration-200 hover:bg-white/[0.02]"
                      onClick={() => navigate(`/documents/${d.id}`)}
                    >
                      <td className="px-5 py-4 align-top">
                        <code className="inline-flex rounded-lg bg-cyan-500/8 px-2.5 py-1 text-xs font-medium text-cyan-300 ring-1 ring-cyan-500/10">
                          {d.id.slice(0, 8)}
                        </code>
                      </td>
                      <td className="px-5 py-4 align-top">
                        <div className="space-y-1.5">
                          <div className="font-medium text-zinc-100">{d.title || '（未命名）'}</div>
                          <div className="max-w-[420px] truncate text-xs text-zinc-500">
                            {d.source_url || '未提供来源 URL'}
                          </div>
                        </div>
                      </td>
                      <td className="px-5 py-4 align-top">
                        <span className={`inline-flex items-center gap-1 rounded-lg border px-2.5 py-1 text-xs font-medium ${DOC_TYPE_COLORS[d.doc_type] || DOC_TYPE_COLORS.other}`}>
                          {docTypeLabel(d.doc_type)}
                        </span>
                      </td>
                      <td className="px-5 py-4 align-top">
                        <span className="inline-flex items-center gap-1.5 text-zinc-400">
                          <Layers size={13} className="text-zinc-600" />
                          {d.chunks_count.toLocaleString()}
                        </span>
                      </td>
                      <td className="px-5 py-4 align-top text-zinc-400">
                        <div>{new Date(d.updated_at).toLocaleDateString('zh-CN')}</div>
                        <div className="mt-1 text-xs text-zinc-600">
                          {new Date(d.updated_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
                        </div>
                      </td>
                      <td className="px-5 py-4 align-top">
                        <div className="flex items-center justify-end gap-1.5">
                          {isCrawlable(d.source_url) && (
                            <button
                              className="rounded-lg p-2 text-zinc-500 transition-colors hover:bg-cyan-500/10 hover:text-cyan-300 disabled:opacity-50"
                              onClick={(e) => handleReCrawl(d.id, e)}
                              disabled={reCrawlId === d.id}
                              title="Re-crawl latest content"
                            >
                              {reCrawlId === d.id ? <Loader2 size={14} className="animate-spin-slow" /> : <RefreshCw size={14} />}
                            </button>
                          )}
                          <Link
                            to={`/documents/${d.id}`}
                            className="rounded-lg p-2 text-zinc-500 transition-colors hover:bg-white/[0.06] hover:text-white"
                            onClick={(e) => e.stopPropagation()}
                            title="查看"
                          >
                            <ExternalLink size={14} />
                          </Link>
                          <button
                            className="rounded-lg p-2 text-zinc-500 transition-colors hover:bg-red-500/10 hover:text-red-400"
                            onClick={(e) => handleDelete(d.id, e)}
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
            </div>
          </>
        )}
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <span className="hidden text-sm text-zinc-500" aria-hidden="true">
            共 {total} 条 · 第 {page} / {totalPages} 页
          </span>
          <span className="hidden text-sm text-zinc-500" aria-hidden="true">
            共 {total.toLocaleString()} 条 · 第 {page} / {totalPages} 页
          </span>
          <span className="text-sm text-zinc-500">
            共 {total.toLocaleString()} 条 | 第 {page} / {totalPages} 页
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
                  className={`w-9 h-9 rounded-xl text-sm font-medium transition-all duration-200 ${
                    p === page
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
        <CreateDocumentModal
          docTypeOptions={docTypeOptions}
          onSuccess={(doc) => {
            setShowCreateModal(false)
            navigate(`/documents/${doc.id}`)
          }}
          onCancel={() => setShowCreateModal(false)}
        />
      )}
      {showUploadModal && (
        <UploadFileModal
          docTypeOptions={docTypeOptions}
          onSuccess={(doc) => {
            setShowUploadModal(false)
            load()
            navigate(`/documents/${doc.id}`)
          }}
          onCancel={() => setShowUploadModal(false)}
        />
      )}
      {showCrawlModal && (
        <CrawlWebsiteModal
          onSuccess={() => {
            setShowCrawlModal(false)
            load()
          }}
          onCancel={() => setShowCrawlModal(false)}
        />
      )}
    </div>
  )
}

function CreateDocumentModal({
  docTypeOptions,
  onSuccess,
  onCancel,
}: {
  docTypeOptions: Array<{ key: string; label: string }>
  onSuccess: (doc: Document) => void
  onCancel: () => void
}) {
  const [url, setUrl] = useState('')
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [docType, setDocType] = useState('other')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [fetching, setFetching] = useState(false)

  const handleFetchFromUrl = async () => {
    if (!url.trim()) {
      setError('请先输入 URL')
      return
    }
    setFetching(true)
    setError(null)
    try {
      const res = await documents.fetchFromUrl(url.trim())
      setTitle(res.title)
      setContent(res.content)
    } catch (e) {
      setError(e instanceof Error ? e.message : '从 URL 获取内容失败')
    } finally {
      setFetching(false)
    }
  }

  const handleSubmit = async () => {
    if (!url.trim()) {
      setError('请输入 URL')
      return
    }
    if (!content.trim()) {
      setError('请输入内容')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const doc = await documents.create({
        url: url.trim(),
        title: title.trim() || '未命名',
        content: content.trim(),
        doc_type: docType,
      })
      onSuccess(doc)
    } catch (e) {
      setError(e instanceof Error ? e.message : '创建失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-md flex items-center justify-center z-[1000] p-4 animate-fade-in" onClick={onCancel}>
      <div
        className="glass rounded-2xl w-full max-w-[600px] max-h-[90vh] overflow-y-auto shadow-2xl animate-slide-up gradient-border"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center px-6 py-5 border-b border-white/[0.04]">
          <h2 className="text-base font-semibold text-white">添加文档</h2>
          <button className="p-2 rounded-xl text-zinc-500 hover:text-white hover:bg-white/[0.06] transition-colors" onClick={onCancel} aria-label="关闭">
            <X size={18} />
          </button>
        </div>
        <div className="p-6 space-y-4">
          {error && <div className="p-3.5 rounded-xl bg-danger/10 border border-danger/20 text-red-300 text-sm">{error}</div>}
          <div>
            <label className="block text-sm font-medium text-zinc-400 mb-2">URL <span className="text-danger">*</span></label>
            <div className="flex gap-2.5">
              <input type="url" value={url} onChange={(e) => { setUrl(e.target.value); setError(null) }} placeholder="https://..." className="flex-1 px-4 py-2.5 rounded-xl input-glass text-sm" />
              <button
                type="button"
                onClick={handleFetchFromUrl}
                disabled={fetching || !url.trim()}
                className="btn-ghost shrink-0 inline-flex items-center gap-1.5 px-4 py-2.5 rounded-xl text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                title="自动从 URL 获取内容"
              >
                {fetching ? <Loader2 size={14} className="animate-spin-slow" /> : <Download size={14} />}
                {fetching ? '获取中...' : '获取内容'}
              </button>
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-zinc-400 mb-2">标题</label>
            <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="文档标题" className="w-full px-4 py-2.5 rounded-xl input-glass text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium text-zinc-400 mb-2">类型</label>
            <select value={docType} onChange={(e) => setDocType(e.target.value)} className="w-full px-4 py-2.5 rounded-xl input-glass text-sm" aria-label="类型">
              {docTypeOptions.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-zinc-400 mb-2">内容 <span className="text-danger">*</span></label>
            <textarea value={content} onChange={(e) => setContent(e.target.value)} placeholder="粘贴文本或 HTML 内容..." className="w-full px-4 py-2.5 rounded-xl input-glass text-sm" rows={6} />
          </div>
        </div>
        <div className="flex justify-end gap-2.5 px-6 py-5 border-t border-white/[0.04]">
          <button className="btn-ghost px-4 py-2.5 rounded-xl text-sm font-medium" onClick={onCancel}>取消</button>
          <button
            className="btn-primary inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
            onClick={handleSubmit}
            disabled={submitting}
          >
            {submitting && <Loader2 size={14} className="animate-spin-slow" />}
            {submitting ? '处理中...' : '添加文档'}
          </button>
        </div>
      </div>
    </div>
  )
}

function UploadFileModal({
  docTypeOptions,
  onSuccess,
  onCancel,
}: {
  docTypeOptions: Array<{ key: string; label: string }>
  onSuccess: (doc: Document) => void
  onCancel: () => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [docType, setDocType] = useState('other')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    setFile(f ?? null)
    setError(null)
    if (f) setTitle((prev) => prev || f.name.replace(/\.[^.]+$/, ''))
  }

  const handleSubmit = async () => {
    if (!file) {
      setError('请选择文件')
      return
    }
    const ext = file.name.toLowerCase().split('.').pop()
    if (!['txt', 'md', 'pdf'].includes(ext || '')) {
      setError('仅支持 .txt、.md 和 .pdf 文件')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const doc = await documents.upload(file, {
        title: title.trim() || undefined,
        doc_type: docType,
      })
      onSuccess(doc)
    } catch (e) {
      setError(e instanceof Error ? e.message : '上传失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-md flex items-center justify-center z-[1000] p-4 animate-fade-in" onClick={onCancel}>
      <div className="glass rounded-2xl w-full max-w-[480px] shadow-2xl animate-slide-up gradient-border" onClick={(e) => e.stopPropagation()}>
        <div className="flex justify-between items-center px-6 py-5 border-b border-white/[0.04]">
          <h2 className="text-base font-semibold text-white">上传文件</h2>
          <button className="p-2 rounded-xl text-zinc-500 hover:text-white hover:bg-white/[0.06] transition-colors" onClick={onCancel} aria-label="关闭">
            <X size={18} />
          </button>
        </div>
        <div className="p-6 space-y-4">
          {error && <div className="p-3.5 rounded-xl bg-danger/10 border border-danger/20 text-red-300 text-sm">{error}</div>}
          <div>
            <label className="block text-sm font-medium text-zinc-400 mb-2">文件 <span className="text-danger">*</span></label>
            <input
              type="file"
              accept=".txt,.md,.pdf"
              onChange={handleFileChange}
              className="block w-full text-sm text-zinc-300 file:mr-4 file:py-2.5 file:px-4 file:rounded-xl file:border-0 file:text-sm file:font-medium file:bg-violet-500/10 file:text-violet-400 hover:file:bg-violet-500/15 file:cursor-pointer file:transition-colors"
            />
            {file && (
              <p className="mt-2 text-xs text-zinc-500">{file.name} ({(file.size / 1024).toFixed(1)} KB)</p>
            )}
          </div>
          <div>
            <label className="block text-sm font-medium text-zinc-400 mb-2">标题</label>
            <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="文档标题（默认使用文件名）" className="w-full px-4 py-2.5 rounded-xl input-glass text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium text-zinc-400 mb-2">类型</label>
            <select value={docType} onChange={(e) => setDocType(e.target.value)} className="w-full px-4 py-2.5 rounded-xl input-glass text-sm" aria-label="类型">
              {docTypeOptions.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
            </select>
          </div>
        </div>
        <div className="flex justify-end gap-2.5 px-6 py-5 border-t border-white/[0.04]">
          <button className="btn-ghost px-4 py-2.5 rounded-xl text-sm font-medium" onClick={onCancel}>取消</button>
          <button
            className="btn-primary inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
            onClick={handleSubmit}
            disabled={submitting || !file}
          >
            {submitting && <Loader2 size={14} className="animate-spin-slow" />}
            {submitting ? '处理中...' : '上传'}
          </button>
        </div>
      </div>
    </div>
  )
}

function CrawlWebsiteModal({
  onSuccess,
  onCancel,
}: {
  onSuccess: () => void
  onCancel: () => void
}) {
  const [url, setUrl] = useState('')
  const [maxPages, setMaxPages] = useState(50)
  const [maxDepth, setMaxDepth] = useState(3)
  const [ingest, setIngest] = useState(true)
  const [excludePrefixes, setExcludePrefixes] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [crawling, setCrawling] = useState(false)
  const [result, setResult] = useState<{ pages_crawled: number; pages_ingested: number; pages: Array<{ url: string; title: string }> } | null>(null)

  const handleCrawl = async () => {
    if (!url.trim()) {
      setError('请输入网站 URL')
      return
    }
    setCrawling(true)
    setError(null)
    setResult(null)
    try {
      const prefixes = excludePrefixes
        .split('\n')
        .map((p) => p.trim())
        .filter(Boolean)
      const res = await documents.crawlWebsite({
        url: url.trim(),
        max_pages: maxPages,
        max_depth: maxDepth,
        ingest,
        exclude_prefixes: prefixes.length > 0 ? prefixes : undefined,
      })
      setResult({
        pages_crawled: res.pages_crawled,
        pages_ingested: res.pages_ingested,
        pages: res.pages,
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : '抓取失败')
    } finally {
      setCrawling(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-md flex items-center justify-center z-[1000] p-4 animate-fade-in" onClick={onCancel}>
      <div className="glass rounded-2xl w-full max-w-[560px] max-h-[90vh] overflow-y-auto shadow-2xl animate-slide-up gradient-border" onClick={(e) => e.stopPropagation()}>
        <div className="flex justify-between items-center px-6 py-5 border-b border-white/[0.04]">
          <h2 className="text-base font-semibold text-white">抓取网站</h2>
          <button className="p-2 rounded-xl text-zinc-500 hover:text-white hover:bg-white/[0.06] transition-colors" onClick={onCancel} aria-label="关闭">
            <X size={18} />
          </button>
        </div>
        <div className="p-6 space-y-4">
          <p className="text-sm text-zinc-500">
            从一个起始 URL 抓取整站页面。只会抓取同一域名下的页面。
          </p>
          {error && <div className="p-3.5 rounded-xl bg-danger/10 border border-danger/20 text-red-300 text-sm">{error}</div>}
          <div>
            <label className="block text-sm font-medium text-zinc-400 mb-2">网站 URL <span className="text-danger">*</span></label>
            <input type="url" value={url} onChange={(e) => { setUrl(e.target.value); setError(null) }} placeholder="https://example.com" className="w-full px-4 py-2.5 rounded-xl input-glass text-sm" disabled={crawling} />
          </div>
          <div>
            <label className="block text-sm font-medium text-zinc-400 mb-2">排除的 URL 前缀</label>
            <textarea
              value={excludePrefixes}
              onChange={(e) => setExcludePrefixes(e.target.value)}
              placeholder={'https://example.com/admin\nhttps://example.com/private'}
              rows={2}
              className="w-full px-4 py-2.5 rounded-xl input-glass text-sm font-mono resize-y"
              disabled={crawling}
              aria-label="排除前缀"
            />
            <p className="mt-1.5 text-xs text-zinc-500">每行一个前缀。匹配任意前缀的 URL 都会被跳过。</p>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-zinc-400 mb-2">最大页面数</label>
              <input type="number" min={1} max={500} value={maxPages} onChange={(e) => setMaxPages(Math.min(500, Math.max(1, parseInt(e.target.value, 10) || 50)))} className="w-full px-4 py-2.5 rounded-xl input-glass text-sm" disabled={crawling} />
            </div>
            <div>
              <label className="block text-sm font-medium text-zinc-400 mb-2">最大深度</label>
              <input type="number" min={1} max={10} value={maxDepth} onChange={(e) => setMaxDepth(Math.min(10, Math.max(1, parseInt(e.target.value, 10) || 3)))} className="w-full px-4 py-2.5 rounded-xl input-glass text-sm" disabled={crawling} />
            </div>
          </div>
          <label className="flex items-center gap-2.5 text-sm text-zinc-400 cursor-pointer">
            <input type="checkbox" checked={ingest} onChange={(e) => setIngest(e.target.checked)} disabled={crawling} className="rounded border-white/10 bg-transparent" />
            将抓取到的页面导入知识库
          </label>
          {result && (
            <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 text-sm animate-fade-in">
              <p className="font-medium mb-1.5">抓取完成</p>
              <p>共抓取 <strong>{result.pages_crawled}</strong> 个页面，已导入 <strong>{result.pages_ingested}</strong> 个。</p>
              {result.pages.length > 0 && (
                <div className="mt-3 max-h-40 overflow-y-auto space-y-1 text-xs">
                  {result.pages.slice(0, 15).map((p) => (
                    <div key={p.url} className="truncate text-emerald-200/80" title={p.url}>{p.title || p.url}</div>
                  ))}
                  {result.pages.length > 15 && <div className="text-zinc-500">... 以及另外 {result.pages.length - 15} 个</div>}
                </div>
              )}
            </div>
          )}
        </div>
        <div className="flex justify-end gap-2.5 px-6 py-5 border-t border-white/[0.04]">
          <button className="btn-ghost px-4 py-2.5 rounded-xl text-sm font-medium" onClick={onCancel}>
            {result ? '关闭' : '取消'}
          </button>
          {!result && (
            <button
              className="btn-primary inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
              onClick={handleCrawl}
              disabled={crawling || !url.trim()}
            >
              {crawling && <Loader2 size={14} className="animate-spin-slow" />}
              {crawling ? '抓取中...（可能需要几分钟）' : '开始抓取'}
            </button>
          )}
          {result && (
            <button className="btn-primary inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium" onClick={onSuccess}>
              完成
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
