import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { admin, type ArchiConfig } from '../api/client'
import SettingsNavigation, {
  isSettingsSection,
  type SettingsSection,
} from './settings/SettingsNavigation'
import {
  Loader2,
  Cpu,
  Key,
  Link2,
  Save,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  Sparkles,
  FileText,
  Globe,
  Zap,
  ShieldCheck,
  SlidersHorizontal,
  ChevronDown,
} from 'lucide-react'

type LlmProviderPresetKey =
  | 'custom'
  | 'deepseek'
  | 'dashscope_qwen'
  | 'zhipu_glm'
  | 'moonshot_kimi'
  | 'siliconflow'

type AnswerMode = 'fast' | 'balanced' | 'strict' | 'debug'

type AnswerModePreset = {
  label: string
  shortLabel: string
  description: string
  icon: typeof Zap
  flags: {
    languageDetect: boolean
    decisionRouterLlm: boolean
    evidenceEvaluator: boolean
    evidenceQualityUseLlm: boolean
    evidenceQualityLlmV2: boolean
    debugLlmCalls: boolean
    selfCritic: boolean
    finalPolish: boolean
    docTypeClassifier: boolean
    retrievalDocTypeUseLlm: boolean
    pageKindFilterEnabled: boolean
    llmTaskAwareRouting: boolean
  }
}

const ANSWER_MODE_PRESETS: Record<AnswerMode, AnswerModePreset> = {
  fast: {
    label: '极速模式',
    shortLabel: '极速',
    description: '减少辅助 LLM 调用，优先降低等待时间。',
    icon: Zap,
    flags: {
      languageDetect: true,
      decisionRouterLlm: false,
      evidenceEvaluator: false,
      evidenceQualityUseLlm: false,
      evidenceQualityLlmV2: false,
      debugLlmCalls: false,
      selfCritic: false,
      finalPolish: false,
      docTypeClassifier: false,
      retrievalDocTypeUseLlm: false,
      pageKindFilterEnabled: false,
      llmTaskAwareRouting: true,
    },
  },
  balanced: {
    label: '平衡模式',
    shortLabel: '平衡',
    description: '推荐日常使用，保留必要校验，减少慢速辅助步骤。',
    icon: SlidersHorizontal,
    flags: {
      languageDetect: true,
      decisionRouterLlm: false,
      evidenceEvaluator: false,
      evidenceQualityUseLlm: false,
      evidenceQualityLlmV2: false,
      debugLlmCalls: false,
      selfCritic: false,
      finalPolish: false,
      docTypeClassifier: false,
      retrievalDocTypeUseLlm: false,
      pageKindFilterEnabled: false,
      llmTaskAwareRouting: true,
    },
  },
  strict: {
    label: '严谨模式',
    shortLabel: '严谨',
    description: '质量优先，适合退款、价格、条款等高风险问题。',
    icon: ShieldCheck,
    flags: {
      languageDetect: true,
      decisionRouterLlm: false,
      evidenceEvaluator: false,
      evidenceQualityUseLlm: true,
      evidenceQualityLlmV2: true,
      debugLlmCalls: false,
      selfCritic: false,
      finalPolish: false,
      docTypeClassifier: false,
      retrievalDocTypeUseLlm: false,
      pageKindFilterEnabled: false,
      llmTaskAwareRouting: true,
    },
  },
  debug: {
    label: '调试模式',
    shortLabel: '调试',
    description: '开发排查用，保留更多日志和 LLM 判断。',
    icon: Sparkles,
    flags: {
      languageDetect: true,
      decisionRouterLlm: true,
      evidenceEvaluator: true,
      evidenceQualityUseLlm: true,
      evidenceQualityLlmV2: true,
      debugLlmCalls: true,
      selfCritic: false,
      finalPolish: false,
      docTypeClassifier: false,
      retrievalDocTypeUseLlm: false,
      pageKindFilterEnabled: false,
      llmTaskAwareRouting: true,
    },
  },
}

function inferAnswerMode(flags: AnswerModePreset['flags']): AnswerMode {
  const entries = Object.entries(ANSWER_MODE_PRESETS) as Array<[AnswerMode, AnswerModePreset]>
  const matched = entries.find(([, preset]) =>
    Object.entries(preset.flags).every(([key, value]) => flags[key as keyof AnswerModePreset['flags']] === value)
  )
  return matched?.[0] ?? 'debug'
}

const LLM_PROVIDER_PRESETS: Record<
  LlmProviderPresetKey,
  {
    label: string
    baseUrl: string
    primaryModel: string
    fallbackModel: string
    economyModel: string
    description: string
  }
> = {
  custom: {
    label: '自定义 / 手动填写',
    baseUrl: '',
    primaryModel: '',
    fallbackModel: '',
    economyModel: '',
    description: '适用于任意 OpenAI-compatible 服务，手动填写模型名和 Base URL。',
  },
  deepseek: {
    label: 'DeepSeek',
    baseUrl: 'https://api.deepseek.com',
    primaryModel: 'deepseek-chat',
    fallbackModel: 'deepseek-chat',
    economyModel: 'deepseek-chat',
    description: 'DeepSeek 官方 OpenAI-compatible 接口。',
  },
  dashscope_qwen: {
    label: '阿里云百炼 / Qwen',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    primaryModel: 'qwen-plus',
    fallbackModel: 'qwen-turbo',
    economyModel: 'qwen-turbo',
    description: '阿里云百炼北京地域 OpenAI 兼容模式；其他地域请手动调整 Base URL。',
  },
  zhipu_glm: {
    label: '智谱 GLM',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    primaryModel: 'glm-4-plus',
    fallbackModel: 'glm-4-flash',
    economyModel: 'glm-4-flash',
    description: '智谱 AI 开放平台 OpenAI 兼容接口。',
  },
  moonshot_kimi: {
    label: '月之暗面 / Kimi',
    baseUrl: 'https://api.moonshot.cn/v1',
    primaryModel: 'kimi-k2.5',
    fallbackModel: 'moonshot-v1-32k',
    economyModel: 'moonshot-v1-8k',
    description: 'Kimi API 开放平台 OpenAI-compatible 接口。',
  },
  siliconflow: {
    label: '硅基流动 SiliconFlow',
    baseUrl: 'https://api.siliconflow.cn/v1',
    primaryModel: 'deepseek-ai/DeepSeek-V3',
    fallbackModel: 'Qwen/Qwen2.5-7B-Instruct',
    economyModel: 'Qwen/Qwen2.5-7B-Instruct',
    description: '硅基流动模型名需使用模型广场中的完整名称。',
  },
}

function detectLlmProviderPreset(baseUrl: string, model: string): LlmProviderPresetKey {
  const normalizedBaseUrl = baseUrl.trim().replace(/\/+$/, '')
  const normalizedModel = model.trim()
  const found = (Object.entries(LLM_PROVIDER_PRESETS) as Array<[LlmProviderPresetKey, (typeof LLM_PROVIDER_PRESETS)[LlmProviderPresetKey]]>)
    .find(([key, preset]) =>
      key !== 'custom' &&
      preset.baseUrl.replace(/\/+$/, '') === normalizedBaseUrl &&
      (!normalizedModel || preset.primaryModel === normalizedModel)
    )
  return found?.[0] ?? 'custom'
}

export default function Settings() {
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedSection = searchParams.get('section')
  const activeSection: SettingsSection = isSettingsSection(requestedSection) ? requestedSection : 'llm'
  const [loadStates, setLoadStates] = useState<Record<SettingsSection, 'idle' | 'loading' | 'ready' | 'error'>>({
    llm: 'idle', embedding: 'idle', reranker: 'idle', prompt: 'idle', pipeline: 'idle', cache: 'ready',
  })
  const loadedSections = useRef<Set<SettingsSection>>(new Set(['cache']))
  const [dirtySections, setDirtySections] = useState<Set<SettingsSection>>(new Set())
  const [saving, setSaving] = useState(false)
  const [savingEmbedding, setSavingEmbedding] = useState(false)
  const [savingArchi, setSavingArchi] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [refreshingConversationCache, setRefreshingConversationCache] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [answerMode, setAnswerMode] = useState<AnswerMode>('balanced')
  const [advancedOpen, setAdvancedOpen] = useState(false)

  const [llmModel, setLlmModel] = useState('')
  const [llmFallbackModel, setLlmFallbackModel] = useState('')
  const [llmApiKey, setLlmApiKey] = useState('')
  const [llmBaseUrl, setLlmBaseUrl] = useState('')
  const [llmProviderPreset, setLlmProviderPreset] = useState<LlmProviderPresetKey>('custom')

  const [embeddingProvider, setEmbeddingProvider] = useState<'openai' | 'custom' | 'ollama'>('openai')
  const [embeddingModel, setEmbeddingModel] = useState('')
  const [embeddingDimensions, setEmbeddingDimensions] = useState(1536)
  const [embeddingApiKey, setEmbeddingApiKey] = useState('')
  const [embeddingBaseUrl, setEmbeddingBaseUrl] = useState('')

  const [savingReranker, setSavingReranker] = useState(false)
  const [rerankerProvider, setRerankerProvider] = useState<'local' | 'cloud' | 'custom'>('local')
  const [rerankerModel, setRerankerModel] = useState('')
  const [rerankerUrl, setRerankerUrl] = useState('')
  const [rerankerApiFormat, setRerankerApiFormat] = useState<'rerank' | 'openai'>('rerank')
  const [rerankerBaseUrl, setRerankerBaseUrl] = useState('')
  const [rerankerApiKey, setRerankerApiKey] = useState('')

  const [languageDetect, setLanguageDetect] = useState(true)
  const [decisionRouterLlm, setDecisionRouterLlm] = useState(false)
  const [evidenceEvaluator, setEvidenceEvaluator] = useState(false)
  const [evidenceQualityUseLlm, setEvidenceQualityUseLlm] = useState(true)
  const [evidenceQualityLlmV2, setEvidenceQualityLlmV2] = useState(false)
  const [debugLlmCalls, setDebugLlmCalls] = useState(false)
  const [selfCritic, setSelfCritic] = useState(false)
  const [finalPolish, setFinalPolish] = useState(false)
  const [docTypeClassifier, setDocTypeClassifier] = useState(false)
  const [retrievalDocTypeUseLlm, setRetrievalDocTypeUseLlm] = useState(false)
  const [pageKindFilterEnabled, setPageKindFilterEnabled] = useState(false)
  const [llmModelEconomy, setLlmModelEconomy] = useState('gpt-4o-mini')
  const [llmTaskAwareRouting, setLlmTaskAwareRouting] = useState(true)

  const [systemPrompt, setSystemPrompt] = useState('')
  const [savingPrompt, setSavingPrompt] = useState(false)
  const [autoGenUrl, setAutoGenUrl] = useState('')
  const [autoGenLoading, setAutoGenLoading] = useState(false)

  const markDirty = (section: SettingsSection) => {
    setDirtySections((current) => new Set(current).add(section))
  }

  const markSaved = (section: SettingsSection) => {
    setDirtySections((current) => {
      const next = new Set(current)
      next.delete(section)
      return next
    })
  }

  const syncArchiState = (archiData: ArchiConfig) => {
    const flags = {
      languageDetect: archiData.language_detect_enabled,
      decisionRouterLlm: archiData.decision_router_use_llm,
      evidenceEvaluator: archiData.evidence_evaluator_enabled,
      evidenceQualityUseLlm: archiData.evidence_quality_use_llm ?? true,
      evidenceQualityLlmV2: archiData.evidence_quality_llm_v2 ?? false,
      debugLlmCalls: archiData.debug_llm_calls ?? false,
      selfCritic: archiData.self_critic_enabled,
      finalPolish: archiData.final_polish_enabled,
      docTypeClassifier: archiData.doc_type_classifier_enabled ?? false,
      retrievalDocTypeUseLlm: archiData.retrieval_doc_type_use_llm ?? false,
      pageKindFilterEnabled: archiData.page_kind_filter_enabled ?? false,
      llmTaskAwareRouting: archiData.llm_task_aware_routing_enabled ?? true,
    }
    setLanguageDetect(flags.languageDetect)
    setDecisionRouterLlm(flags.decisionRouterLlm)
    setEvidenceEvaluator(flags.evidenceEvaluator)
    setEvidenceQualityUseLlm(flags.evidenceQualityUseLlm)
    setEvidenceQualityLlmV2(flags.evidenceQualityLlmV2)
    setDebugLlmCalls(flags.debugLlmCalls)
    setSelfCritic(flags.selfCritic)
    setFinalPolish(flags.finalPolish)
    setDocTypeClassifier(flags.docTypeClassifier)
    setRetrievalDocTypeUseLlm(flags.retrievalDocTypeUseLlm)
    setPageKindFilterEnabled(flags.pageKindFilterEnabled)
    setLlmModelEconomy(archiData.llm_model_economy ?? 'gpt-4o-mini')
    setLlmTaskAwareRouting(flags.llmTaskAwareRouting)
    setAnswerMode(inferAnswerMode(flags))
  }

  const applyAnswerMode = (mode: AnswerMode) => {
    const flags = ANSWER_MODE_PRESETS[mode].flags
    setAnswerMode(mode)
    setLanguageDetect(flags.languageDetect)
    setDecisionRouterLlm(flags.decisionRouterLlm)
    setEvidenceEvaluator(flags.evidenceEvaluator)
    setEvidenceQualityUseLlm(flags.evidenceQualityUseLlm)
    setEvidenceQualityLlmV2(flags.evidenceQualityLlmV2)
    setDebugLlmCalls(flags.debugLlmCalls)
    setSelfCritic(flags.selfCritic)
    setFinalPolish(flags.finalPolish)
    setDocTypeClassifier(flags.docTypeClassifier)
    setRetrievalDocTypeUseLlm(flags.retrievalDocTypeUseLlm)
    setPageKindFilterEnabled(flags.pageKindFilterEnabled)
    setLlmTaskAwareRouting(flags.llmTaskAwareRouting)
    markDirty('pipeline')
  }

  const loadSection = useCallback(async (section: SettingsSection, force = false) => {
    if (!force && loadedSections.current.has(section)) return
    if (section === 'cache') return
    loadedSections.current.add(section)
    setLoadStates((current) => ({ ...current, [section]: 'loading' }))
    setError(null)
    try {
      if (section === 'llm') {
        const llmData = await admin.getLLMConfig()
        setLlmModel(llmData.llm_model)
        setLlmFallbackModel(llmData.llm_fallback_model)
        setLlmApiKey(llmData.llm_api_key)
        setLlmBaseUrl(llmData.llm_base_url)
        setLlmProviderPreset(detectLlmProviderPreset(llmData.llm_base_url, llmData.llm_model))
      } else if (section === 'embedding') {
        const embeddingData = await admin.getEmbeddingConfig()
        setEmbeddingProvider(embeddingData.embedding_provider)
        setEmbeddingModel(embeddingData.embedding_model)
        setEmbeddingDimensions(embeddingData.embedding_dimensions)
        setEmbeddingApiKey(embeddingData.embedding_api_key)
        setEmbeddingBaseUrl(embeddingData.embedding_base_url)
      } else if (section === 'reranker') {
        const rerankerData = await admin.getRerankerConfig()
        setRerankerProvider(rerankerData.reranker_provider)
        setRerankerModel(rerankerData.reranker_model)
        setRerankerUrl(rerankerData.reranker_url)
        setRerankerApiFormat(rerankerData.reranker_api_format || 'rerank')
        setRerankerBaseUrl(rerankerData.reranker_base_url || '')
        setRerankerApiKey(rerankerData.reranker_api_key || '')
      } else if (section === 'pipeline') {
        const archiData = await admin.getArchiConfig()
        syncArchiState(archiData)
      } else if (section === 'prompt') {
        const promptData = await admin.getSystemPrompt()
        setSystemPrompt(promptData.value)
      }
      setLoadStates((current) => ({ ...current, [section]: 'ready' }))
    } catch (e) {
      loadedSections.current.delete(section)
      setError(e instanceof Error ? e.message : '加载配置失败')
      setLoadStates((current) => ({ ...current, [section]: 'error' }))
    }
  }, [])

  useEffect(() => {
    void loadSection(activeSection)
  }, [activeSection, loadSection])

  useEffect(() => {
    if (!isSettingsSection(requestedSection)) {
      setSearchParams({ section: 'llm' }, { replace: true })
    }
  }, [requestedSection, setSearchParams])

  useEffect(() => {
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      if (dirtySections.size === 0) return
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warnBeforeUnload)
    return () => window.removeEventListener('beforeunload', warnBeforeUnload)
  }, [dirtySections])

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSuccess(null)
    setSaving(true)
    try {
      await admin.updateLLMConfig({
        llm_model: llmModel.trim(),
        llm_fallback_model: llmFallbackModel.trim(),
        llm_api_key: llmApiKey,
        llm_base_url: llmBaseUrl.trim(),
      })
      setSuccess('配置已保存，缓存已刷新。')
      const data = await admin.getLLMConfig()
      setLlmModel(data.llm_model)
      setLlmFallbackModel(data.llm_fallback_model)
      setLlmApiKey(data.llm_api_key)
      setLlmBaseUrl(data.llm_base_url)
      setLlmProviderPreset(detectLlmProviderPreset(data.llm_base_url, data.llm_model))
      markSaved('llm')
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleSaveEmbedding = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSuccess(null)
    setSavingEmbedding(true)
    try {
      await admin.updateEmbeddingConfig({
        embedding_provider: embeddingProvider,
        embedding_model: embeddingModel.trim(),
        embedding_dimensions: embeddingDimensions,
        embedding_api_key: embeddingApiKey,
        embedding_base_url: embeddingBaseUrl.trim(),
      })
      const data = await admin.getEmbeddingConfig()
      setEmbeddingProvider(data.embedding_provider)
      setEmbeddingModel(data.embedding_model)
      setEmbeddingDimensions(data.embedding_dimensions)
      setEmbeddingApiKey(data.embedding_api_key)
      setEmbeddingBaseUrl(data.embedding_base_url)
      setSuccess('向量化模型配置已保存，缓存已刷新。')
      markSaved('embedding')
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存向量化配置失败')
    } finally {
      setSavingEmbedding(false)
    }
  }

  const handleSaveReranker = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSuccess(null)
    setSavingReranker(true)
    try {
      await admin.updateRerankerConfig({
        reranker_provider: rerankerProvider,
        reranker_model: rerankerModel.trim(),
        reranker_url: rerankerUrl.trim(),
        reranker_api_format: rerankerApiFormat,
        reranker_base_url: rerankerBaseUrl.trim(),
        reranker_api_key: rerankerApiKey,
      })
      const data = await admin.getRerankerConfig()
      setRerankerProvider(data.reranker_provider)
      setRerankerModel(data.reranker_model)
      setRerankerUrl(data.reranker_url)
      setRerankerApiFormat(data.reranker_api_format || 'rerank')
      setRerankerBaseUrl(data.reranker_base_url || '')
      setRerankerApiKey(data.reranker_api_key || '')
      setSuccess('重排序模型配置已保存，缓存已刷新。')
      markSaved('reranker')
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存重排序配置失败')
    } finally {
      setSavingReranker(false)
    }
  }

  const handleRefresh = async () => {
    if (dirtySections.has(activeSection) && !window.confirm('重新加载会放弃当前设置项尚未保存的修改，是否继续？')) return
    setError(null)
    setSuccess(null)
    setRefreshing(true)
    try {
      await admin.refreshConfigCache()
      await loadSection(activeSection, true)
      markSaved(activeSection)
      setSuccess('当前配置已从数据库重新加载。')
    } catch (e) {
      setError(e instanceof Error ? e.message : '刷新失败')
    } finally {
      setRefreshing(false)
    }
  }

  const handleRefreshConversationCache = async () => {
    setError(null)
    setSuccess(null)
    setRefreshingConversationCache(true)
    try {
      const res = await admin.refreshConversationCache()
      const queryRewriterSummary = res.query_rewriter.enabled
        ? `${res.query_rewriter.deleted_keys} 个查询重写缓存键`
        : '查询重写缓存已禁用'
      setSuccess(
        `会话缓存已刷新：${queryRewriterSummary}，${res.llm_cache.deleted_keys} 个 LLM 缓存键。`
      )
    } catch (e) {
      setError(e instanceof Error ? e.message : '刷新会话缓存失败')
    } finally {
      setRefreshingConversationCache(false)
    }
  }

  const handleSaveArchi = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSuccess(null)
    setSavingArchi(true)
    try {
      await admin.updateArchiConfig({
        language_detect_enabled: languageDetect,
        decision_router_use_llm: decisionRouterLlm,
        evidence_evaluator_enabled: evidenceEvaluator,
        evidence_quality_use_llm: evidenceQualityUseLlm,
        evidence_quality_llm_v2: evidenceQualityLlmV2,
        debug_llm_calls: debugLlmCalls,
        self_critic_enabled: selfCritic,
        final_polish_enabled: finalPolish,
        doc_type_classifier_enabled: docTypeClassifier,
        retrieval_doc_type_use_llm: retrievalDocTypeUseLlm,
        page_kind_filter_enabled: pageKindFilterEnabled,
        llm_model_economy: llmModelEconomy.trim(),
        llm_task_aware_routing_enabled: llmTaskAwareRouting,
      })
      setSuccess('Archi v3 配置已保存。')
      const data = await admin.getArchiConfig()
      syncArchiState(data)
      markSaved('pipeline')
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存 Archi 配置失败')
    } finally {
      setSavingArchi(false)
    }
  }

  const handleProviderPresetChange = (value: LlmProviderPresetKey) => {
    setLlmProviderPreset(value)
    const preset = LLM_PROVIDER_PRESETS[value]
    if (value === 'custom') return
    setLlmModel(preset.primaryModel)
    setLlmFallbackModel(preset.fallbackModel)
    setLlmBaseUrl(preset.baseUrl)
  }

  const handleEmbeddingProviderChange = (value: 'openai' | 'custom' | 'ollama') => {
    setEmbeddingProvider(value)
    if (value === 'ollama') {
      setEmbeddingModel('nomic-embed-text')
      setEmbeddingDimensions(768)
      setEmbeddingApiKey('')
      setEmbeddingBaseUrl('http://host.docker.internal:11434')
    }
  }

  const handleAutoGenerate = async () => {
    if (!autoGenUrl.trim()) return
    setError(null)
    setSuccess(null)
    setAutoGenLoading(true)
    try {
      const res = await admin.autoGenerateBrandingFromDomain(autoGenUrl.trim())
      const promptData = await admin.getSystemPrompt()
      setSystemPrompt(promptData.value)
      setSuccess(
        `已从 ${autoGenUrl} 生成。域名：${res.prompt_domain}${res.app_name ? `，应用：${res.app_name}` : ''}。已保存到数据库。`
      )
    } catch (e) {
      setError(e instanceof Error ? e.message : '自动生成失败')
    } finally {
      setAutoGenLoading(false)
    }
  }

  const handleSavePrompt = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSuccess(null)
    setSavingPrompt(true)
    try {
      await admin.updateSystemPrompt({ value: systemPrompt })
      setSuccess('系统提示词已保存，缓存已刷新。')
      markSaved('prompt')
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存提示词失败')
    } finally {
      setSavingPrompt(false)
    }
  }

  return (
    <div className="animate-slide-up max-w-5xl space-y-6">
      <header className="mb-2 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">设置</h1>
          <p className="text-sm text-zinc-500 mt-1.5">
            配置 LLM 模型、API Token 和 Base URL。优先使用数据库配置，缺省时回退到环境变量。
          </p>
        </div>
        {activeSection !== 'cache' && <button
          type="button"
          onClick={handleRefresh}
          disabled={refreshing || loadStates[activeSection] === 'loading'}
          className="flex items-center gap-2 px-4 py-2 rounded-xl input-glass text-sm text-zinc-400 hover:text-white transition-colors disabled:opacity-50"
        >
          {refreshing ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
          刷新当前配置
        </button>}
      </header>

      <SettingsNavigation
        active={activeSection}
        dirtySections={dirtySections}
        onChange={(section) => {
          setError(null)
          setSuccess(null)
          setSearchParams({ section })
        }}
      />

      {(error || success) && loadStates[activeSection] !== 'error' && (
        <div
          role={error ? 'alert' : 'status'}
          className={`flex items-center gap-3 px-4 py-3 rounded-xl ${
            error ? 'bg-red-500/10 text-red-400 border border-red-500/20' : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
          }`}
        >
          {error ? <AlertCircle size={18} /> : <CheckCircle2 size={18} />}
          <span className="text-sm">{error || success}</span>
        </div>
      )}

      {loadStates[activeSection] === 'loading' && (
        <div className="glass flex min-h-64 items-center justify-center rounded-2xl" role="status">
          <Loader2 size={28} className="animate-spin text-blue-500" />
          <span className="ml-3 text-sm text-slate-500">正在加载当前配置…</span>
        </div>
      )}

      {loadStates[activeSection] === 'error' && (
        <div className="glass rounded-2xl p-8 text-center" role="alert">
          <AlertCircle size={24} className="mx-auto text-red-500" />
          <p className="mt-3 text-sm text-slate-600">当前配置加载失败，其他设置项仍可正常使用。</p>
          <button type="button" onClick={() => void loadSection(activeSection, true)} className="mt-4 rounded-xl bg-blue-600 px-4 py-2 text-sm font-medium text-white">
            重新加载
          </button>
        </div>
      )}

      {activeSection === 'llm' && loadStates.llm === 'ready' && <section id="settings-panel-llm" role="tabpanel" aria-labelledby="settings-tab-llm" className="glass max-w-3xl rounded-2xl p-6">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2.5 mb-5">
          <div className="w-7 h-7 rounded-lg bg-violet-500/10 flex items-center justify-center">
            <Cpu size={15} className="text-violet-400" />
          </div>
          LLM 配置
        </h2>
        <p className="text-sm text-zinc-400 mb-5">
          配置模型名称、API key（Token）和 Base URL。可选择中国模型预设，也可手动填写任意 OpenAI-compatible 服务。
        </p>
        <form onSubmit={handleSave} onChange={() => markDirty('llm')} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-zinc-500 mb-1.5">模型供应商预设</label>
            <select
              value={llmProviderPreset}
              onChange={(e) => handleProviderPresetChange(e.target.value as LlmProviderPresetKey)}
              className="w-full px-4 py-2.5 rounded-xl input-glass text-sm"
              disabled={saving}
            >
              {(Object.entries(LLM_PROVIDER_PRESETS) as Array<[LlmProviderPresetKey, (typeof LLM_PROVIDER_PRESETS)[LlmProviderPresetKey]]>)
                .map(([key, preset]) => (
                  <option key={key} value={key}>
                    {preset.label}
                  </option>
                ))}
            </select>
            <p className="text-xs text-zinc-500 mt-1">{LLM_PROVIDER_PRESETS[llmProviderPreset].description}</p>
          </div>
          <div>
            <label className="block text-xs font-medium text-zinc-500 mb-1.5">主模型</label>
            <input
              type="text"
              value={llmModel}
              onChange={(e) => {
                setLlmModel(e.target.value)
                setLlmProviderPreset('custom')
              }}
              placeholder="gpt-4o-mini"
              className="w-full px-4 py-2.5 rounded-xl input-glass text-sm"
              disabled={saving}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-zinc-500 mb-1.5">备用模型</label>
            <input
              type="text"
              value={llmFallbackModel}
              onChange={(e) => {
                setLlmFallbackModel(e.target.value)
                setLlmProviderPreset('custom')
              }}
              placeholder="gpt-3.5-turbo"
              className="w-full px-4 py-2.5 rounded-xl input-glass text-sm"
              disabled={saving}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-zinc-500 mb-1.5 flex items-center gap-1.5">
              <Key size={12} />
              API key（Token）
            </label>
            <input
              type="password"
              value={llmApiKey}
              onChange={(e) => setLlmApiKey(e.target.value)}
              placeholder="sk-..."
              className="w-full px-4 py-2.5 rounded-xl input-glass text-sm font-mono"
              disabled={saving}
              autoComplete="off"
            />
            <p className="text-xs text-zinc-500 mt-1">留空将保留当前值或使用环境变量</p>
          </div>
          <div>
            <label className="block text-xs font-medium text-zinc-500 mb-1.5 flex items-center gap-1.5">
              <Link2 size={12} />
              Base URL
            </label>
            <input
              type="url"
              value={llmBaseUrl}
              onChange={(e) => {
                setLlmBaseUrl(e.target.value)
                setLlmProviderPreset('custom')
              }}
              placeholder="https://api.openai.com/v1（留空 = 默认）"
              className="w-full px-4 py-2.5 rounded-xl input-glass text-sm font-mono"
              disabled={saving}
            />
            <p className="text-xs text-zinc-500 mt-1">留空则使用 OpenAI 默认地址；中国模型一般需要填写对应厂商的兼容接口地址。</p>
          </div>
          <button
            type="submit"
            disabled={saving}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium text-white transition-all"
            style={{
              background: 'linear-gradient(135deg, #7c3aed 0%, #6d28d9 100%)',
            }}
          >
            {saving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
            保存
          </button>
        </form>
      </section>}

      {activeSection === 'embedding' && loadStates.embedding === 'ready' && <section id="settings-panel-embedding" role="tabpanel" aria-labelledby="settings-tab-embedding" className="glass max-w-3xl rounded-2xl p-6">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2.5 mb-5">
          <div className="w-7 h-7 rounded-lg bg-violet-500/10 flex items-center justify-center">
            <Cpu size={15} className="text-violet-400" />
          </div>
          向量化模型
        </h2>
        <p className="text-sm text-zinc-400 mb-5">
          上传知识库时用于生成向量，和 LLM 是两类模型。Ollama 本地模型建议使用 nomic-embed-text。
        </p>
        <form onSubmit={handleSaveEmbedding} onChange={() => markDirty('embedding')} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-zinc-500 mb-1.5">向量化供应商</label>
            <select
              value={embeddingProvider}
              onChange={(e) => handleEmbeddingProviderChange(e.target.value as 'openai' | 'custom' | 'ollama')}
              className="w-full px-4 py-2.5 rounded-xl input-glass text-sm"
              disabled={savingEmbedding}
            >
              <option value="openai">OpenAI-compatible</option>
              <option value="custom">自定义 OpenAI-compatible</option>
              <option value="ollama">Ollama 本地</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-zinc-500 mb-1.5">向量化模型</label>
            <input
              type="text"
              value={embeddingModel}
              onChange={(e) => setEmbeddingModel(e.target.value)}
              placeholder={embeddingProvider === 'ollama' ? 'nomic-embed-text' : 'text-embedding-3-small'}
              className="w-full px-4 py-2.5 rounded-xl input-glass text-sm"
              disabled={savingEmbedding}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-zinc-500 mb-1.5">向量维度</label>
            <input
              type="number"
              min={1}
              value={embeddingDimensions}
              onChange={(e) => setEmbeddingDimensions(Number(e.target.value) || 1)}
              placeholder={embeddingProvider === 'ollama' ? '768' : '1536'}
              className="w-full px-4 py-2.5 rounded-xl input-glass text-sm"
              disabled={savingEmbedding}
            />
            <p className="text-xs text-zinc-500 mt-1">更换模型或维度后，已有知识库通常需要重新上传或重新入库。</p>
          </div>
          <div>
            <label className="block text-xs font-medium text-zinc-500 mb-1.5 flex items-center gap-1.5">
              <Key size={12} />
              API key（Token）
            </label>
            <input
              type="password"
              value={embeddingApiKey}
              onChange={(e) => setEmbeddingApiKey(e.target.value)}
              placeholder={embeddingProvider === 'ollama' ? 'Ollama 通常留空' : '留空则回退到 LLM API key'}
              className="w-full px-4 py-2.5 rounded-xl input-glass text-sm font-mono"
              disabled={savingEmbedding}
              autoComplete="off"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-zinc-500 mb-1.5 flex items-center gap-1.5">
              <Link2 size={12} />
              Base URL
            </label>
            <input
              type="url"
              value={embeddingBaseUrl}
              onChange={(e) => setEmbeddingBaseUrl(e.target.value)}
              placeholder={embeddingProvider === 'ollama' ? 'http://host.docker.internal:11434' : 'https://api.openai.com/v1'}
              className="w-full px-4 py-2.5 rounded-xl input-glass text-sm font-mono"
              disabled={savingEmbedding}
            />
            <p className="text-xs text-zinc-500 mt-1">
              Docker 中访问宿主机 Ollama 用 host.docker.internal；非 Docker 同机运行可用 http://localhost:11434。
            </p>
          </div>
          <button
            type="submit"
            disabled={savingEmbedding || !embeddingModel.trim()}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium text-white transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            style={{
              background: 'linear-gradient(135deg, #7c3aed 0%, #6d28d9 100%)',
            }}
          >
            {savingEmbedding ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
            保存向量化配置
          </button>
        </form>
      </section>}

      {activeSection === 'reranker' && loadStates.reranker === 'ready' && <section id="settings-panel-reranker" role="tabpanel" aria-labelledby="settings-tab-reranker" className="glass max-w-3xl rounded-2xl p-6">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2.5 mb-5">
          <div className="w-7 h-7 rounded-lg bg-orange-500/10 flex items-center justify-center">
            <Zap size={15} className="text-orange-400" />
          </div>
          重排序模型
        </h2>
        <p className="text-sm text-zinc-400 mb-5">
          检索后对结果进行重排序，提升相关性。本地模式使用 sentence-transformers 交叉编码器，云端模式使用 Cohere Rerank API。
        </p>
        <form onSubmit={handleSaveReranker} onChange={() => markDirty('reranker')} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-zinc-500 mb-1.5">重排序供应商</label>
            <select
              value={rerankerProvider}
              onChange={(e) => setRerankerProvider(e.target.value as 'local' | 'cloud' | 'custom')}
              className="w-full px-4 py-2.5 rounded-xl input-glass text-sm"
              disabled={savingReranker}
            >
              <option value="local">本地 (sentence-transformers)</option>
              <option value="cloud">云端 Rerank API</option>
              <option value="custom">不使用重排序 (identity)</option>
            </select>
          </div>
          {rerankerProvider === 'local' && (
            <>
              <div>
                <label className="block text-xs font-medium text-zinc-500 mb-1.5">模型名称</label>
                <input
                  type="text"
                  value={rerankerModel}
                  onChange={(e) => setRerankerModel(e.target.value)}
                  placeholder="cross-encoder/ms-marco-MiniLM-L-6-v2"
                  className="w-full px-4 py-2.5 rounded-xl input-glass text-sm"
                  disabled={savingReranker}
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-zinc-500 mb-1.5 flex items-center gap-1.5">
                  <Link2 size={12} />
                  服务地址
                </label>
                <input
                  type="url"
                  value={rerankerUrl}
                  onChange={(e) => setRerankerUrl(e.target.value)}
                  placeholder="http://localhost:8001/rerank"
                  className="w-full px-4 py-2.5 rounded-xl input-glass text-sm font-mono"
                  disabled={savingReranker}
                />
                <p className="text-xs text-zinc-500 mt-1">
                  本地 reranker HTTP 服务地址，需要实现 POST /rerank 接口。
                </p>
              </div>
            </>
          )}
          {rerankerProvider === 'cloud' && (
            <>
              <div>
                <label className="block text-xs font-medium text-zinc-500 mb-1.5">API 格式</label>
                <select
                  value={rerankerApiFormat}
                  onChange={(e) => setRerankerApiFormat(e.target.value as 'rerank' | 'openai')}
                  className="w-full px-4 py-2.5 rounded-xl input-glass text-sm"
                  disabled={savingReranker}
                >
                  <option value="rerank">Rerank API (Cohere/Jina/硅基流动/自定义)</option>
                  <option value="openai">OpenAI Chat Completions 格式</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-zinc-500 mb-1.5 flex items-center gap-1.5">
                  <Link2 size={12} />
                  API Base URL
                </label>
                <input
                  type="url"
                  value={rerankerBaseUrl}
                  onChange={(e) => setRerankerBaseUrl(e.target.value)}
                  placeholder={rerankerApiFormat === 'rerank' ? 'https://api.cohere.com/v1' : 'https://api.openai.com/v1'}
                  className="w-full px-4 py-2.5 rounded-xl input-glass text-sm font-mono"
                  disabled={savingReranker}
                />
                <p className="text-xs text-zinc-500 mt-1">
                  {rerankerApiFormat === 'rerank'
                    ? '支持 Cohere (api.cohere.com/v1)、Jina (api.jina.ai/v1)、硅基流动 (api.siliconflow.cn/v1) 等。'
                    : 'OpenAI 兼容的 chat/completions 端点。'}
                </p>
              </div>
              <div>
                <label className="block text-xs font-medium text-zinc-500 mb-1.5">模型名称</label>
                <input
                  type="text"
                  value={rerankerModel}
                  onChange={(e) => setRerankerModel(e.target.value)}
                  placeholder={rerankerApiFormat === 'rerank' ? 'rerank-multilingual-v3.0' : 'gpt-4o-mini'}
                  className="w-full px-4 py-2.5 rounded-xl input-glass text-sm"
                  disabled={savingReranker}
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-zinc-500 mb-1.5 flex items-center gap-1.5">
                  <Key size={12} />
                  API Key
                </label>
                <input
                  type="password"
                  value={rerankerApiKey}
                  onChange={(e) => setRerankerApiKey(e.target.value)}
                  placeholder="输入 API Key"
                  className="w-full px-4 py-2.5 rounded-xl input-glass text-sm font-mono"
                  disabled={savingReranker}
                  autoComplete="off"
                />
              </div>
            </>
          )}
          {rerankerProvider === 'custom' && (
            <p className="text-sm text-zinc-500 bg-zinc-800/50 rounded-lg p-3">
              使用 identity reranker，检索结果按原始分数排序，无重排序效果。适合嵌入模型质量较高或数据量较小的场景。
            </p>
          )}
          <button
            type="submit"
            disabled={savingReranker}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium text-white transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            style={{
              background: 'linear-gradient(135deg, #f97316 0%, #ea580c 100%)',
            }}
          >
            {savingReranker ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
            保存重排序配置
          </button>
        </form>
      </section>}

      {activeSection === 'cache' && <section id="settings-panel-cache" role="tabpanel" aria-labelledby="settings-tab-cache" className="glass max-w-3xl rounded-2xl p-6">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2.5 mb-5">
          <div className="w-7 h-7 rounded-lg bg-violet-500/10 flex items-center justify-center">
            <RefreshCw size={15} className="text-violet-400" />
          </div>
          会话缓存
        </h2>
        <p className="text-sm text-zinc-400 mb-5">
          清除查询重写缓存和 LLM 响应缓存，避免提示词或检索配置变更后继续使用旧结果。
        </p>
        <button
          type="button"
          onClick={handleRefreshConversationCache}
          disabled={refreshingConversationCache}
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium text-white transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          style={{
            background: 'linear-gradient(135deg, #7c3aed 0%, #6d28d9 100%)',
          }}
        >
          {refreshingConversationCache ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
          刷新会话缓存
        </button>
      </section>}

      {activeSection === 'prompt' && loadStates.prompt === 'ready' && <section id="settings-panel-prompt" role="tabpanel" aria-labelledby="settings-tab-prompt" className="glass max-w-3xl rounded-2xl p-6">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2.5 mb-5">
          <div className="w-7 h-7 rounded-lg bg-violet-500/10 flex items-center justify-center">
            <FileText size={15} className="text-violet-400" />
          </div>
          系统提示词
        </h2>
        <p className="text-sm text-zinc-400 mb-5">
          生成回复时发送给 LLM 的系统提示词。修改后可定制聊天机器人行为，保存到数据库并刷新缓存。
        </p>
        <div className="mb-5 p-4 rounded-xl bg-violet-500/5 border border-violet-500/20">
          <div className="flex items-center gap-2 mb-2">
            <Globe size={16} className="text-violet-400" />
            <span className="text-sm font-medium text-violet-200">从域名自动生成</span>
          </div>
          <p className="text-xs text-zinc-500 mb-3">
            输入网站 URL，AI 会抓取并生成角色设定、领域预设和自定义规则，然后保存到数据库。
          </p>
          <div className="flex gap-2">
            <input
              type="url"
              value={autoGenUrl}
              onChange={(e) => setAutoGenUrl(e.target.value)}
              placeholder="https://example.com"
              className="flex-1 px-4 py-2 rounded-xl input-glass text-sm"
              disabled={autoGenLoading}
            />
            <button
              type="button"
              onClick={handleAutoGenerate}
              disabled={autoGenLoading || !autoGenUrl.trim()}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-white bg-violet-600 hover:bg-violet-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {autoGenLoading ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
              {autoGenLoading ? '生成中...' : '从 URL 生成'}
            </button>
          </div>
        </div>
        <form onSubmit={handleSavePrompt} onChange={() => markDirty('prompt')} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-zinc-500 mb-1.5">提示词</label>
            <textarea
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder="你是一名支持助手..."
              rows={14}
              className="w-full px-4 py-2.5 rounded-xl input-glass text-sm font-mono resize-y min-h-[200px]"
              disabled={savingPrompt}
            />
          </div>
          <button
            type="submit"
            disabled={savingPrompt || !systemPrompt.trim()}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium text-white transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            style={{
              background: 'linear-gradient(135deg, #7c3aed 0%, #6d28d9 100%)',
            }}
          >
            {savingPrompt ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
            保存提示词
          </button>
        </form>
      </section>}

      {activeSection === 'pipeline' && loadStates.pipeline === 'ready' && <section id="settings-panel-pipeline" role="tabpanel" aria-labelledby="settings-tab-pipeline" className="glass max-w-3xl rounded-2xl p-6">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2.5 mb-5">
          <div className="w-7 h-7 rounded-lg bg-violet-500/10 flex items-center justify-center">
            <Sparkles size={15} className="text-violet-400" />
          </div>
          回答流程
        </h2>
        <p className="text-sm text-zinc-400 mb-5">
          选择日常回答策略。推荐使用平衡模式；需要排查问题时再展开高级设置。
        </p>
        <form
          onSubmit={handleSaveArchi}
          onChange={() => markDirty('pipeline')}
          onClick={(event) => {
            if ((event.target as HTMLElement).closest('[role="switch"]')) markDirty('pipeline')
          }}
          className="space-y-4"
        >
          <div>
            <div className="flex items-center justify-between gap-3 mb-3">
              <div>
                <div className="text-sm font-medium text-white">回答模式</div>
                <div className="text-xs text-zinc-500 mt-0.5">选择后点击保存才会生效。</div>
              </div>
              <span className="text-xs px-2.5 py-1 rounded-lg bg-violet-500/10 text-violet-200 border border-violet-500/20">
                当前：{ANSWER_MODE_PRESETS[answerMode].label}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {(Object.entries(ANSWER_MODE_PRESETS) as Array<[AnswerMode, AnswerModePreset]>).map(([mode, preset]) => {
                const Icon = preset.icon
                const active = answerMode === mode
                return (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => applyAnswerMode(mode)}
                    disabled={savingArchi}
                    className={`text-left px-3 py-3 rounded-lg border transition-colors ${
                      active
                        ? 'border-violet-400/70 bg-violet-500/15 text-white'
                        : 'border-white/[0.08] bg-white/[0.03] text-zinc-300 hover:border-white/[0.16] hover:bg-white/[0.06]'
                    } ${savingArchi ? 'opacity-50 cursor-not-allowed' : ''}`}
                  >
                    <div className="flex items-center gap-2 text-sm font-medium">
                      <Icon size={15} className={active ? 'text-violet-200' : 'text-zinc-500'} />
                      {preset.shortLabel}
                    </div>
                    <div className="text-xs text-zinc-500 mt-1 leading-relaxed">{preset.description}</div>
                  </button>
                )
              })}
            </div>
          </div>

          <button
            type="button"
            onClick={() => setAdvancedOpen((v) => !v)}
            className="w-full flex items-center justify-between gap-3 py-3 border-t border-white/[0.06] text-sm text-zinc-300 hover:text-white transition-colors"
            aria-expanded={advancedOpen}
          >
            <span className="flex items-center gap-2">
              <SlidersHorizontal size={15} className="text-zinc-500" />
              高级设置
            </span>
            <ChevronDown size={16} className={`text-zinc-500 transition-transform ${advancedOpen ? 'rotate-180' : ''}`} />
          </button>

          {advancedOpen && (
            <div className="space-y-4">
              <ToggleRow
                label="语言识别"
                description="自动识别用户输入语言，不调用 LLM。"
                checked={languageDetect}
                onChange={setLanguageDetect}
                disabled={savingArchi}
              />
              <ToggleRow
                label="问题理解增强"
                description="用 LLM 参与灰区决策，可能增加响应时间。"
                checked={decisionRouterLlm}
                onChange={setDecisionRouterLlm}
                disabled={savingArchi}
              />
              <ToggleRow
                label="证据相关性评估"
                description="用 LLM 判断检索证据是否相关，并给重试提供建议。"
                checked={evidenceEvaluator}
                onChange={setEvidenceEvaluator}
                disabled={savingArchi}
              />
              <ToggleRow
                label="证据可靠性检查"
                description="用 LLM 判断证据质量。关闭后使用规则检查，速度更快。"
                checked={evidenceQualityUseLlm}
                onChange={setEvidenceQualityUseLlm}
                disabled={savingArchi}
              />
              <ToggleRow
                label="证据可靠性快速判定"
                description="用单次通过/失败判断替代详细评分。开启后覆盖上面的详细判断。"
                checked={evidenceQualityLlmV2}
                onChange={setEvidenceQualityLlmV2}
                disabled={savingArchi}
              />
              <ToggleRow
                label="记录完整 LLM 调用"
                description="保存每次 LLM 的完整提示词和响应，仅建议排查问题时开启。"
                checked={debugLlmCalls}
                onChange={setDebugLlmCalls}
                disabled={savingArchi}
              />
              <ToggleRow
                label="生成后自检"
                description="答案自检失败时重新生成，质量更稳但更慢。"
                checked={selfCritic}
                onChange={setSelfCritic}
                disabled={savingArchi}
              />
              <ToggleRow
                label="答案润色"
                description="用 LLM 优化表达清晰度、结构和语气。"
                checked={finalPolish}
                onChange={setFinalPolish}
                disabled={savingArchi}
              />
              <ToggleRow
                label="入库文档自动分类"
                description="抓取或上传文档时，用 LLM 判断文档类型。"
                checked={docTypeClassifier}
                onChange={setDocTypeClassifier}
                disabled={savingArchi}
              />
              <ToggleRow
                label="检索范围智能选择"
                description="根据问题语义用 LLM 选择要检索的文档类型。"
                checked={retrievalDocTypeUseLlm}
                onChange={setRetrievalDocTypeUseLlm}
                disabled={savingArchi}
              />
              <ToggleRow
                label="按页面类型过滤"
                description="按 howto、faq 等 page_kind 筛选结果；分块缺少 page_kind 时建议关闭。"
                checked={pageKindFilterEnabled}
                onChange={setPageKindFilterEnabled}
                disabled={savingArchi}
              />
              <ToggleRow
                label="模型自动分工"
                description="生成用主模型，理解、评估、润色等辅助任务用经济模型。"
                checked={llmTaskAwareRouting}
                onChange={setLlmTaskAwareRouting}
                disabled={savingArchi}
              />
              <div>
                <label className="block text-xs font-medium text-zinc-500 mb-1.5">经济模型</label>
                <input
                  type="text"
                  value={llmModelEconomy}
                  onChange={(e) => setLlmModelEconomy(e.target.value)}
                  placeholder="gpt-4o-mini"
                  className="w-full px-4 py-2.5 rounded-xl input-glass text-sm"
                  disabled={savingArchi}
                />
                <p className="text-xs text-zinc-500 mt-1">用于问题理解、证据评估、证据质量、答案润色等辅助任务。</p>
              </div>
            </div>
          )}
          <button
            type="submit"
            disabled={savingArchi}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium text-white transition-all"
            style={{
              background: 'linear-gradient(135deg, #7c3aed 0%, #6d28d9 100%)',
            }}
          >
            {savingArchi ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
            保存回答流程
          </button>
        </form>
      </section>}
    </div>
  )
}

function ToggleRow({
  label,
  description,
  checked,
  onChange,
  disabled,
}: {
  label: string
  description: string
  checked: boolean
  onChange: (v: boolean) => void
  disabled?: boolean
}) {
  return (
    <div className="flex items-center justify-between gap-4 py-2">
      <div>
        <div className="text-sm font-medium text-white">{label}</div>
        <div className="text-xs text-zinc-500 mt-0.5">{description}</div>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked ? 'true' : 'false'}
        aria-label={`${label}：${checked ? '开启' : '关闭'}`}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`
          relative w-11 h-6 rounded-full transition-colors shrink-0
          ${checked ? 'bg-violet-500' : 'bg-zinc-600'}
          ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
        `}
      >
        <span
          className={`
            absolute top-1 left-1 w-4 h-4 rounded-full bg-white transition-transform
            ${checked ? 'translate-x-5' : 'translate-x-0'}
          `}
        />
      </button>
    </div>
  )
}
