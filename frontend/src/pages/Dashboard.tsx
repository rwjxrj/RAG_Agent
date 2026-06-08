import { useState, useEffect } from 'react'
import { dashboard } from '../api/client'
import {
  BarChart3,
  Loader2,
  TrendingUp,
  Activity,
  Zap,
  MessageSquare,
  Clock,
  RefreshCw,
  Sparkles,
} from 'lucide-react'

const CARD_STYLES = [
  { gradient: 'from-violet-500/15 via-violet-500/5 to-transparent', glow: 'rgba(124,58,237,0.12)', iconColor: 'text-violet-400', borderColor: 'rgba(124,58,237,0.15)' },
  { gradient: 'from-emerald-500/15 via-emerald-500/5 to-transparent', glow: 'rgba(16,185,129,0.12)', iconColor: 'text-emerald-400', borderColor: 'rgba(16,185,129,0.15)' },
  { gradient: 'from-amber-500/15 via-amber-500/5 to-transparent', glow: 'rgba(245,158,11,0.12)', iconColor: 'text-amber-400', borderColor: 'rgba(245,158,11,0.15)' },
  { gradient: 'from-cyan-500/15 via-cyan-500/5 to-transparent', glow: 'rgba(6,182,212,0.12)', iconColor: 'text-cyan-400', borderColor: 'rgba(6,182,212,0.15)' },
  { gradient: 'from-blue-500/15 via-blue-500/5 to-transparent', glow: 'rgba(59,130,246,0.12)', iconColor: 'text-blue-400', borderColor: 'rgba(59,130,246,0.15)' },
  { gradient: 'from-rose-500/15 via-rose-500/5 to-transparent', glow: 'rgba(244,63,94,0.12)', iconColor: 'text-rose-400', borderColor: 'rgba(244,63,94,0.15)' },
]

type DashboardCard = {
  key: string
  label: string
  value: number
  hint: string
  icon: typeof Activity
  valueType?: 'number' | 'currency'
}

export default function Dashboard() {
  const [metrics, setMetrics] = useState<Record<string, number>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  const load = async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true)
    else setLoading(true)
    setError(null)
    try {
      const res = await dashboard.stats()
      setMetrics(res.metrics || {})
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载统计数据失败')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const cards = buildDashboardCards(metrics)

  if (loading) return (
      <div className="flex items-center justify-center gap-3 py-24 animate-fade-in">
        <Loader2 size={22} className="animate-spin-slow text-accent" />
      <span className="text-zinc-500">正在加载仪表盘...</span>
    </div>
  )

  if (error && cards.length === 0) return (
    <div className="animate-fade-in">
      <div className="p-3.5 rounded-xl mb-5 bg-danger/10 border border-danger/20 text-red-300 text-sm">{error}</div>
    </div>
  )

  return (
    <div className="animate-slide-up">
      <header className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">仪表盘</h1>
          <p className="text-sm text-zinc-500 mt-1.5">来自 Prometheus 的实时指标</p>
        </div>
        <button
          className="btn-ghost inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium disabled:opacity-50 transition-all"
          onClick={() => load(true)}
          disabled={refreshing}
        >
          <RefreshCw size={14} className={refreshing ? 'animate-spin-slow' : ''} />
          刷新
        </button>
      </header>

      {error && (
        <div className="p-3.5 rounded-xl mb-5 bg-danger/10 border border-danger/20 text-red-300 text-sm animate-fade-in">
          {error}
        </div>
      )}

      {cards.length === 0 ? (
        <div className="flex flex-col items-center py-24 text-zinc-500">
          <div className="w-16 h-16 rounded-2xl glass-accent flex items-center justify-center mb-5 glow-sm">
            <BarChart3 size={30} className="text-violet-400" />
          </div>
          <p className="font-semibold text-zinc-300 mb-1.5">暂无可用指标</p>
          <p className="text-sm">系统开始处理请求后，指标会显示在这里</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {cards.map((card, index) => {
            const Icon = card.icon
            const style = CARD_STYLES[index % CARD_STYLES.length]

            return (
              <div
                key={card.key}
                className={`relative overflow-hidden rounded-2xl p-5 transition-all duration-300 card-hover`}
                style={{
                  background: `linear-gradient(135deg, ${style.glow}, rgba(255,255,255,0.86) 60%)`,
                  border: `1px solid ${style.borderColor}`,
                  backdropFilter: 'blur(12px)',
                  boxShadow: '0 14px 32px rgba(37,99,235,0.08)',
                }}
              >
                <div className="absolute inset-0 dot-pattern opacity-30" />
                <div className="relative">
                  <div className="flex items-start justify-between mb-4">
                    <div
                      className={`w-10 h-10 rounded-xl flex items-center justify-center ${style.iconColor}`}
                      style={{ background: 'rgba(219,234,254,0.72)' }}
                    >
                      <Icon size={19} />
                    </div>
                    <Sparkles size={14} className="text-zinc-600" />
                  </div>
                  <div className="text-3xl font-bold tracking-tight text-white mb-1.5">
                    {formatMetricValue(card.value, card.valueType)}
                  </div>
                  <div className="text-xs font-medium text-zinc-500">
                    {card.label} · {card.hint}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function buildDashboardCards(metrics: Record<string, number>): DashboardCard[] {
  const cards: DashboardCard[] = [
    {
      key: 'llm_requests',
      label: 'LLM 请求',
      value: sumMetric(metrics, 'support_ai_llm_requests_total'),
      hint: '所有模型调用汇总',
      icon: Zap,
    },
    {
      key: 'llm_input_tokens',
      label: '输入 Token',
      value: sumMetric(metrics, 'support_ai_llm_tokens_total', 'type=input'),
      hint: '所有模型汇总',
      icon: Activity,
    },
    {
      key: 'llm_output_tokens',
      label: '输出 Token',
      value: sumMetric(metrics, 'support_ai_llm_tokens_total', 'type=output'),
      hint: '所有模型汇总',
      icon: Activity,
    },
    {
      key: 'llm_cost',
      label: 'LLM 成本',
      value: sumMetric(metrics, 'support_ai_llm_cost_usd_total'),
      hint: 'USD 估算',
      icon: TrendingUp,
      valueType: 'currency',
    },
    {
      key: 'retrieval_requests',
      label: '检索请求',
      value: sumMetric(metrics, 'support_ai_retrieval_requests_total'),
      hint: '知识库查询',
      icon: BarChart3,
    },
    {
      key: 'retrieval_hits',
      label: '检索命中',
      value: sumMetric(metrics, 'support_ai_retrieval_hits_total'),
      hint: '返回证据片段',
      icon: MessageSquare,
    },
    {
      key: 'retrieval_misses',
      label: '检索未命中',
      value: sumMetric(metrics, 'support_ai_retrieval_misses_total'),
      hint: '无证据结果',
      icon: Clock,
    },
    {
      key: 'api_requests',
      label: 'API 请求',
      value: sumMetric(metrics, 'support_ai_api_requests_total'),
      hint: '全部接口汇总',
      icon: Activity,
    },
  ]

  return cards.filter((card) => card.value > 0)
}

function sumMetric(metrics: Record<string, number>, metricName: string, labelContains?: string): number {
  return Object.entries(metrics).reduce((total, [key, value]) => {
    const isMetric = key === metricName || key.startsWith(`${metricName}{`)
    if (!isMetric) return total
    if (labelContains && !key.includes(labelContains)) return total
    return total + (Number.isFinite(value) ? value : 0)
  }, 0)
}

function formatMetricValue(value: number, valueType: DashboardCard['valueType'] = 'number'): string {
  if (valueType === 'currency') return `$${value.toFixed(value >= 1 ? 2 : 4)}`
  if (typeof value !== 'number') return String(value)
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`
  if (Number.isInteger(value)) return value.toLocaleString()
  return value.toFixed(2)
}
