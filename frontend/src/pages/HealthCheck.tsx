import { useState } from 'react'
import {
  Activity,
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
  RefreshCw,
  Database,
  Cpu,
  Zap,
  Search,
  HardDrive,
} from 'lucide-react'
import { runHealthCheck, type HealthCheckItem, type HealthCheckResponse } from '../api/client'

const STATUS_CONFIG = {
  healthy: { color: 'bg-green-100 text-green-800 border-green-300', icon: CheckCircle2, label: '全部正常' },
  degraded: { color: 'bg-amber-100 text-amber-800 border-amber-300', icon: Clock, label: '部分异常或有注意项' },
  unhealthy: { color: 'bg-red-100 text-red-800 border-red-300', icon: XCircle, label: '严重异常' },
}

const ITEM_ICON_MAP: Record<string, typeof Activity> = {
  'LLM': Cpu,
  'Embedding': Zap,
  'Reranker': Search,
  'PostgreSQL': Database,
  'Redis': HardDrive,
  'Qdrant': Database,
  'OpenSearch': Search,
}

function getItemIcon(name: string) {
  for (const [key, Icon] of Object.entries(ITEM_ICON_MAP)) {
    if (name.includes(key)) return Icon
  }
  return Activity
}

function ItemCard({ item }: { item: HealthCheckItem }) {
  const Icon = getItemIcon(item.name)
  const isOk = item.status === 'ok'
  const hasWarning = isOk && item.warning

  return (
    <div
      className={`rounded-lg border p-4 flex items-start gap-3 transition-colors ${
        !isOk
          ? item.status === 'timeout'
            ? 'bg-yellow-50 border-yellow-200'
            : 'bg-red-50 border-red-200'
          : hasWarning
          ? 'bg-amber-50 border-amber-200'
          : 'bg-green-50 border-green-200'
      }`}
    >
      <div className={`mt-0.5 ${!isOk ? (item.status === 'timeout' ? 'text-yellow-600' : 'text-red-600') : hasWarning ? 'text-amber-600' : 'text-green-600'}`}>
        <Icon size={20} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <h3 className="font-medium text-gray-900 truncate">{item.name}</h3>
          <span
            className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${
              !isOk
                ? item.status === 'timeout'
                  ? 'bg-yellow-100 text-yellow-700'
                  : 'bg-red-100 text-red-700'
                : hasWarning
                ? 'bg-amber-100 text-amber-700'
                : 'bg-green-100 text-green-700'
            }`}
          >
            {!isOk ? (item.status === 'timeout' ? '超时' : '异常') : hasWarning ? '注意' : '正常'}
          </span>
        </div>
        <p className="text-sm text-gray-600 mt-1 truncate">{item.detail}</p>
        {item.warning && (
          <p className="text-xs text-amber-700 mt-1.5 bg-amber-50 rounded px-2 py-1">{item.warning}</p>
        )}
        <p className="text-xs text-gray-400 mt-1">{item.latency_ms}ms</p>
      </div>
    </div>
  )
}

export default function HealthCheck() {
  const [result, setResult] = useState<HealthCheckResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleCheck = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await runHealthCheck()
      setResult(data)
    } catch (e: any) {
      setError(e.message || '检查失败')
    } finally {
      setLoading(false)
    }
  }

  const statusConfig = result ? STATUS_CONFIG[result.status] : null
  const StatusIcon = statusConfig?.icon

  return (
    <div className="max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">健康检查</h1>
          <p className="text-sm text-gray-500 mt-1">检查 RAG 系统核心服务的连通性</p>
        </div>
        <button
          onClick={handleCheck}
          disabled={loading}
          className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? (
            <>
              <Loader2 size={16} className="animate-spin" />
              检查中...
            </>
          ) : (
            <>
              <RefreshCw size={16} />
              {result ? '重新检查' : '开始检查'}
            </>
          )}
        </button>
      </div>

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
          {error}
        </div>
      )}

      {result && (
        <>
          {/* Status summary */}
          <div
            className={`mb-6 p-4 rounded-lg border flex items-center gap-3 ${statusConfig?.color}`}
          >
            {StatusIcon && <StatusIcon size={24} />}
            <div>
              <p className="font-semibold text-lg">{statusConfig?.label}</p>
              <p className="text-sm opacity-80">
                {result.summary.ok}/{result.summary.total} 项正常
                {result.summary.failed > 0 && `，${result.summary.failed} 项异常`}
                {result.summary.warnings > 0 && `，${result.summary.warnings} 项注意`}
              </p>
            </div>
          </div>

          {/* Check cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {result.checks.map((item, i) => (
              <ItemCard key={i} item={item} />
            ))}
          </div>
        </>
      )}

      {!result && !loading && !error && (
        <div className="text-center py-20 text-gray-400">
          <Activity size={48} className="mx-auto mb-4 opacity-50" />
          <p>点击"开始检查"按钮检测系统状态</p>
        </div>
      )}
    </div>
  )
}
