import { useState, useEffect, useRef } from 'react'
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
  CheckCircle2,
  AlertCircle,
} from 'lucide-react'

const SUPPORTED_UPLOAD_EXTENSIONS = ['.txt', '.md', '.pdf'] as const
const SUPPORTED_UPLOAD_ACCEPT = SUPPORTED_UPLOAD_EXTENSIONS.join(',')
const SUPPORTED_UPLOAD_LABEL = SUPPORTED_UPLOAD_EXTENSIONS.join('、')

function getUploadFileError(file: File) {
  const lowerName = file.name.toLowerCase()
  const isSupported = SUPPORTED_UPLOAD_EXTENSIONS.some((ext) => lowerName.endsWith(ext))
  return isSupported ? null : `仅支持 ${SUPPORTED_UPLOAD_LABEL} 文件`
}

function getFileTitle(file: File) {
  return file.name.replace(/\.[^.]+$/, '') || file.name
}

function formatFileSize(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

type UploadQueueStatus = 'pending' | 'uploading' | 'success' | 'error' | 'invalid'

type UploadQueueItem = {
  id: string
  file: File
  status: UploadQueueStatus
  message?: string
}

function createUploadQueue(files: File[]) {
  return files.map((file, index) => {
    const fileError = getUploadFileError(file)
    return {
      id: `${file.name}-${file.size}-${file.lastModified}-${index}`,
      file,
      status: fileError ? 'invalid' : 'pending',
      message: fileError ?? undefined,
    } satisfies UploadQueueItem
  })
}

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
  const dropzoneInputRef = useRef<HTMLInputElement>(null)
  const dragDepthRef = useRef(0)
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
  const [uploadInitialFiles, setUploadInitialFiles] = useState<File[]>([])
  const [dropzoneDragging, setDropzoneDragging] = useState(false)
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

  const openUploadModal = (files: File[] = []) => {
    setUploadInitialFiles(files)
    setShowUploadModal(true)
  }

  const handleDropzoneFiles = (files: FileList | null) => {
    const selectedFiles = Array.from(files ?? [])
    if (selectedFiles.length === 0) return
    openUploadModal(selectedFiles)
  }

  const handleDropzoneDragEnter = (e: React.DragEvent<HTMLButtonElement>) => {
    e.preventDefault()
    dragDepthRef.current += 1
    setDropzoneDragging(true)
  }

  const handleDropzoneDragOver = (e: React.DragEvent<HTMLButtonElement>) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
  }

  const handleDropzoneDragLeave = (e: React.DragEvent<HTMLButtonElement>) => {
    e.preventDefault()
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1)
    if (dragDepthRef.current === 0) setDropzoneDragging(false)
  }

  const handleDropzoneDrop = (e: React.DragEvent<HTMLButtonElement>) => {
    e.preventDefault()
    dragDepthRef.current = 0
    setDropzoneDragging(false)
    handleDropzoneFiles(e.dataTransfer.files)
  }

  const totalPages = Math.ceil(total / pageSize)
  const visibleChunks = items.reduce((sum, item) => sum + item.chunks_count, 0)
  const crawlableCount = items.filter((item) => isCrawlable(item.source_url)).length
  const hasActiveFilters = Boolean(filterDocType || filterQApplied)
  const activeFilterCount = Number(Boolean(filterDocType)) + Number(Boolean(filterQApplied))

  return (
    <div className="space-y-6 animate-slide-up">
      <header className="relative overflow-hidden rounded-[28px] border border-sky-100 bg-[linear-gradient(135deg,rgba(255,255,255,0.92),rgba(239,246,255,0.9))] shadow-[0_22px_55px_rgba(37,99,235,0.1)]">
        <div className="absolute inset-x-0 top-0 h-32 bg-[linear-gradient(180deg,rgba(219,234,254,0.72),transparent)]" />
        <div className="relative p-6 lg:p-7">
          <div className="flex flex-col gap-6 xl:flex-row xl:items-start xl:justify-between">
            <div className="max-w-3xl">
              <div className="inline-flex items-center gap-2 rounded-full border border-sky-200 bg-sky-50 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.24em] text-blue-700">
                <Database size={12} />
                知识库
              </div>
              <h1 className="mt-4 text-3xl font-semibold tracking-tight text-black sm:text-[2rem]">文档库</h1>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400 sm:text-[15px]">
                管理检索文档、刷新在线来源，并保持知识库内容整洁，以提高回答准确性。
              </p>
            </div>

            <div className="grid w-full gap-3 sm:grid-cols-2 xl:w-auto xl:min-w-[460px]">
              <div className="rounded-2xl border border-sky-100 bg-white/70 p-4 backdrop-blur-md">
                <div className="flex items-center justify-between text-xs uppercase tracking-[0.2em] text-zinc-500">
                  <span>文档总数</span>
                  <FileText size={14} className="text-cyan-300" />
                </div>
                <div className="mt-3 text-3xl font-semibold tracking-tight text-white">{total.toLocaleString()}</div>
                <div className="mt-1 text-xs text-zinc-500">覆盖所有已索引来源</div>
              </div>
              <div className="rounded-2xl border border-sky-100 bg-white/70 p-4 backdrop-blur-md">
                <div className="flex items-center justify-between text-xs uppercase tracking-[0.2em] text-zinc-500">
                  <span>当前页展示</span>
                  <Layers size={14} className="text-emerald-300" />
                </div>
                <div className="mt-3 text-3xl font-semibold tracking-tight text-white">{items.length}</div>
                <div className="mt-1 text-xs text-zinc-500">当前视图包含 {visibleChunks.toLocaleString()} 个分块</div>
              </div>
              <div className="rounded-2xl border border-sky-100 bg-white/70 p-4 backdrop-blur-md">
                <div className="flex items-center justify-between text-xs uppercase tracking-[0.2em] text-zinc-500">
                  <span>HTTP 来源</span>
                  <Globe size={14} className="text-blue-300" />
                </div>
                <div className="mt-3 text-3xl font-semibold tracking-tight text-white">{crawlableCount}</div>
                <div className="mt-1 text-xs text-zinc-500">当前可重新抓取</div>
              </div>
              <div className="rounded-2xl border border-sky-100 bg-white/70 p-4 backdrop-blur-md">
                <div className="flex items-center justify-between text-xs uppercase tracking-[0.2em] text-zinc-500">
                  <span>筛选条件</span>
                  <Filter size={14} className="text-amber-300" />
                </div>
                <div className="mt-3 text-3xl font-semibold tracking-tight text-white">{activeFilterCount}</div>
                <div className="mt-1 text-xs text-zinc-500">{hasActiveFilters ? '当前为自定义视图' : '正在显示全部文档'}</div>
              </div>
            </div>
          </div>

          <input
            ref={dropzoneInputRef}
            type="file"
            accept={SUPPORTED_UPLOAD_ACCEPT}
            multiple
            className="hidden"
            onChange={(e) => {
              handleDropzoneFiles(e.target.files)
              e.target.value = ''
            }}
          />
          <button
            type="button"
            onClick={() => dropzoneInputRef.current?.click()}
            onDragEnter={handleDropzoneDragEnter}
            onDragOver={handleDropzoneDragOver}
            onDragLeave={handleDropzoneDragLeave}
            onDrop={handleDropzoneDrop}
            className={`mt-6 flex min-h-[132px] w-full flex-col items-center justify-center rounded-2xl border border-dashed px-6 py-6 text-center transition-colors ${
              dropzoneDragging
                ? 'border-blue-400 bg-blue-50/80 shadow-[0_12px_28px_rgba(37,99,235,0.12)]'
                : 'border-sky-200 bg-white/45 hover:border-blue-300 hover:bg-white/70'
            }`}
            aria-label="拖入或批量选择文件上传到文档库"
          >
            <span className="mb-3 inline-flex h-10 w-10 items-center justify-center rounded-full bg-blue-600 text-white shadow-[0_10px_20px_rgba(37,99,235,0.2)]">
              <Upload size={18} />
            </span>
            <span className="text-base font-semibold text-zinc-900">
              拖入一个或多个文件上传到知识库
            </span>
            <span className="mt-2 text-sm leading-6 text-zinc-500">
              或点击批量选择文件，支持 {SUPPORTED_UPLOAD_LABEL}
            </span>
          </button>

          <div className="mt-5 border-t border-white/[0.06] pt-5">
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
                onClick={() => openUploadModal()}
              >
                <Upload size={15} />
                上传文件
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
                          <div className="font-medium text-black">{d.title || '（未命名）'}</div>
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
          initialFiles={uploadInitialFiles}
          docTypeOptions={docTypeOptions}
          onSuccess={(docs, totalFiles) => {
            load()
            if (docs.length === 1 && totalFiles === 1) {
              setShowUploadModal(false)
              setUploadInitialFiles([])
            }
          }}
          onCancel={() => {
            setShowUploadModal(false)
            setUploadInitialFiles([])
          }}
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
  const [renderJs, setRenderJs] = useState(false)

  const handleFetchFromUrl = async () => {
    if (!url.trim()) {
      setError('请先输入 URL')
      return
    }
    setFetching(true)
    setError(null)
    try {
      const res = await documents.fetchFromUrl(url.trim(), { render_js: renderJs })
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
            <label className="mt-2 flex items-center gap-2.5 text-sm text-zinc-400 cursor-pointer">
              <input
                type="checkbox"
                checked={renderJs}
                onChange={(e) => setRenderJs(e.target.checked)}
                disabled={fetching}
                className="rounded border-white/10 bg-transparent"
              />
              使用浏览器渲染 JavaScript 后获取内容
            </label>
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
  initialFiles,
  docTypeOptions,
  onSuccess,
  onCancel,
}: {
  initialFiles?: File[]
  docTypeOptions: Array<{ key: string; label: string }>
  onSuccess: (docs: Document[], totalFiles: number) => void
  onCancel: () => void
}) {
  const [uploadItems, setUploadItems] = useState<UploadQueueItem[]>(() => createUploadQueue(initialFiles ?? []))
  const [singleTitle, setSingleTitle] = useState(() => initialFiles?.length === 1 ? getFileTitle(initialFiles[0]) : '')
  const [docType, setDocType] = useState('other')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [completed, setCompleted] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<{ done: number; total: number } | null>(null)

  useEffect(() => {
    const files = initialFiles ?? []
    setUploadItems(createUploadQueue(files))
    setSingleTitle(files.length === 1 ? getFileTitle(files[0]) : '')
    setError(null)
    setCompleted(false)
    setUploadProgress(null)
  }, [initialFiles])

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    setError(null)
    setCompleted(false)
    setUploadProgress(null)
    if (files.length === 0) {
      setUploadItems([])
      setSingleTitle('')
      return
    }
    setUploadItems(createUploadQueue(files))
    setSingleTitle(files.length === 1 ? getFileTitle(files[0]) : '')
  }

  const handleSubmit = async () => {
    if (uploadItems.length === 0) {
      setError('请选择文件')
      return
    }
    const uploadableItems = uploadItems.filter((item) => item.status !== 'invalid')
    if (uploadableItems.length === 0) {
      setError('没有可上传的有效文件')
      return
    }
    setSubmitting(true)
    setCompleted(false)
    setError(null)
    setUploadProgress({ done: 0, total: uploadableItems.length })
    const uploadedDocs: Document[] = []
    let processed = 0
    try {
      for (const item of uploadableItems) {
        setUploadItems((prev) => prev.map((current) => (
          current.id === item.id ? { ...current, status: 'uploading', message: '上传中' } : current
        )))
        try {
          const doc = await documents.upload(item.file, {
            title: uploadItems.length === 1 ? singleTitle.trim() || getFileTitle(item.file) : getFileTitle(item.file),
            doc_type: docType,
          })
          uploadedDocs.push(doc)
          setUploadItems((prev) => prev.map((current) => (
            current.id === item.id ? { ...current, status: 'success', message: '上传成功' } : current
          )))
        } catch (e) {
          setUploadItems((prev) => prev.map((current) => (
            current.id === item.id
              ? { ...current, status: 'error', message: e instanceof Error ? e.message : '上传失败' }
              : current
          )))
        } finally {
          processed += 1
          setUploadProgress({ done: processed, total: uploadableItems.length })
        }
      }
      setCompleted(true)
      if (uploadedDocs.length > 0) onSuccess(uploadedDocs, uploadItems.length)
    } finally {
      setSubmitting(false)
    }
  }

  const successCount = uploadItems.filter((item) => item.status === 'success').length
  const failedCount = uploadItems.filter((item) => item.status === 'error').length
  const invalidCount = uploadItems.filter((item) => item.status === 'invalid').length
  const pendingCount = uploadItems.filter((item) => item.status === 'pending').length
  const hasSingleEditableFile = uploadItems.length === 1 && uploadItems[0].status !== 'invalid'
  const uploadButtonLabel = submitting && uploadProgress
    ? `上传中 ${uploadProgress.done}/${uploadProgress.total}`
    : completed
      ? '上传完成'
      : uploadItems.length > 1
        ? `上传 ${uploadItems.filter((item) => item.status !== 'invalid').length} 个文件`
        : '上传'

  const renderItemStatus = (item: UploadQueueItem) => {
    if (item.status === 'uploading') return <Loader2 size={15} className="animate-spin-slow text-blue-300" />
    if (item.status === 'success') return <CheckCircle2 size={15} className="text-emerald-300" />
    if (item.status === 'error' || item.status === 'invalid') return <AlertCircle size={15} className="text-red-300" />
    return <FileText size={15} className="text-zinc-500" />
  }

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-md flex items-center justify-center z-[1000] p-4 animate-fade-in" onClick={() => { if (!submitting) onCancel() }}>
      <div className="glass rounded-2xl w-full max-w-[560px] max-h-[90vh] overflow-y-auto shadow-2xl animate-slide-up gradient-border" onClick={(e) => e.stopPropagation()}>
        <div className="flex justify-between items-center px-6 py-5 border-b border-white/[0.04]">
          <h2 className="text-base font-semibold text-white">上传文件</h2>
          <button className="p-2 rounded-xl text-zinc-500 hover:text-white hover:bg-white/[0.06] transition-colors disabled:opacity-40 disabled:cursor-not-allowed" onClick={onCancel} disabled={submitting} aria-label="关闭">
            <X size={18} />
          </button>
        </div>
        <div className="p-6 space-y-4">
          {error && <div className="p-3.5 rounded-xl bg-danger/10 border border-danger/20 text-red-300 text-sm">{error}</div>}
          {completed && (
            <div className="p-3.5 rounded-xl bg-white/[0.04] border border-white/[0.07] text-sm text-zinc-300">
              批量处理完成：成功 {successCount} 个，失败 {failedCount} 个，跳过 {invalidCount} 个。
            </div>
          )}
          <div>
            <label className="block text-sm font-medium text-zinc-400 mb-2">文件 <span className="text-danger">*</span></label>
            <input
              type="file"
              accept={SUPPORTED_UPLOAD_ACCEPT}
              multiple
              disabled={submitting}
              onChange={handleFileChange}
              className="block w-full text-sm text-zinc-300 file:mr-4 file:py-2.5 file:px-4 file:rounded-xl file:border-0 file:text-sm file:font-medium file:bg-violet-500/10 file:text-violet-400 hover:file:bg-violet-500/15 file:cursor-pointer file:transition-colors disabled:opacity-50"
            />
            <p className="mt-2 text-xs text-zinc-500">支持 {SUPPORTED_UPLOAD_LABEL}</p>
          </div>
          {uploadItems.length > 0 && (
            <div className="max-h-56 space-y-2 overflow-y-auto rounded-xl border border-white/[0.06] bg-black/10 p-2">
              {uploadItems.map((item) => (
                <div key={item.id} className="flex items-start gap-3 rounded-lg bg-white/[0.03] px-3 py-2">
                  <div className="mt-0.5 shrink-0">{renderItemStatus(item)}</div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-zinc-200">{item.file.name}</div>
                    <div className="mt-0.5 text-xs text-zinc-500">{formatFileSize(item.file.size)}</div>
                    {item.message && (
                      <div className={`mt-1 text-xs ${
                        item.status === 'success'
                          ? 'text-emerald-300'
                          : item.status === 'error' || item.status === 'invalid'
                            ? 'text-red-300'
                            : 'text-blue-300'
                      }`}>
                        {item.message}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
          {hasSingleEditableFile && (
            <div>
            <label className="block text-sm font-medium text-zinc-400 mb-2">标题</label>
            <input type="text" value={singleTitle} onChange={(e) => setSingleTitle(e.target.value)} disabled={submitting} placeholder="文档标题（默认使用文件名）" className="w-full px-4 py-2.5 rounded-xl input-glass text-sm disabled:opacity-50" />
            </div>
          )}
          <div>
            <label className="block text-sm font-medium text-zinc-400 mb-2">类型</label>
            <select value={docType} onChange={(e) => setDocType(e.target.value)} disabled={submitting} className="w-full px-4 py-2.5 rounded-xl input-glass text-sm disabled:opacity-50" aria-label="类型">
              {docTypeOptions.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
            </select>
          </div>
        </div>
        <div className="flex justify-end gap-2.5 px-6 py-5 border-t border-white/[0.04]">
          <button className="btn-ghost px-4 py-2.5 rounded-xl text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed" onClick={onCancel} disabled={submitting}>
            {completed ? '完成' : '取消'}
          </button>
          <button
            className="btn-primary inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
            onClick={handleSubmit}
            disabled={submitting || completed || uploadItems.length === 0 || pendingCount === 0}
          >
            {submitting && <Loader2 size={14} className="animate-spin-slow" />}
            {uploadButtonLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

