import { Cpu, FileText, RefreshCw, SlidersHorizontal, Sparkles, Zap } from 'lucide-react'

export type SettingsSection = 'llm' | 'embedding' | 'reranker' | 'prompt' | 'pipeline' | 'cache'

export const SETTINGS_SECTIONS: Array<{
  id: SettingsSection
  label: string
  description: string
  icon: typeof Cpu
}> = [
  { id: 'llm', label: 'LLM 配置', description: '主模型与接口', icon: Cpu },
  { id: 'embedding', label: '向量模型', description: '知识库向量化', icon: Sparkles },
  { id: 'reranker', label: '重排序', description: '检索结果排序', icon: Zap },
  { id: 'prompt', label: '系统提示词', description: '回复角色与规则', icon: FileText },
  { id: 'pipeline', label: '回答流程', description: '质量与性能策略', icon: SlidersHorizontal },
  { id: 'cache', label: '缓存维护', description: '刷新会话缓存', icon: RefreshCw },
]

export function isSettingsSection(value: string | null): value is SettingsSection {
  return SETTINGS_SECTIONS.some((section) => section.id === value)
}

export default function SettingsNavigation({
  active,
  dirtySections,
  onChange,
}: {
  active: SettingsSection
  dirtySections: ReadonlySet<SettingsSection>
  onChange: (section: SettingsSection) => void
}) {
  const selectAndFocus = (section: SettingsSection) => {
    onChange(section)
    window.requestAnimationFrame(() => document.getElementById(`settings-tab-${section}`)?.focus())
  }

  const moveFocus = (direction: number) => {
    const index = SETTINGS_SECTIONS.findIndex((section) => section.id === active)
    selectAndFocus(SETTINGS_SECTIONS[(index + direction + SETTINGS_SECTIONS.length) % SETTINGS_SECTIONS.length].id)
  }

  return (
    <div className="glass rounded-2xl p-2">
      <label htmlFor="settings-section" className="sr-only">选择设置项</label>
      <select
        id="settings-section"
        value={active}
        onChange={(event) => onChange(event.target.value as SettingsSection)}
        className="input-glass w-full rounded-xl px-4 py-3 text-sm md:hidden"
      >
        {SETTINGS_SECTIONS.map((section) => (
          <option key={section.id} value={section.id}>
            {section.label}{dirtySections.has(section.id) ? '（未保存）' : ''}
          </option>
        ))}
      </select>

      <div role="tablist" aria-label="设置分类" className="hidden grid-cols-6 gap-1 md:grid">
        {SETTINGS_SECTIONS.map((section) => {
          const Icon = section.icon
          const selected = active === section.id
          const dirty = dirtySections.has(section.id)
          return (
            <button
              key={section.id}
              id={`settings-tab-${section.id}`}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={`settings-panel-${section.id}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => onChange(section.id)}
              onKeyDown={(event) => {
                if (event.key === 'ArrowRight') { event.preventDefault(); moveFocus(1) }
                if (event.key === 'ArrowLeft') { event.preventDefault(); moveFocus(-1) }
                if (event.key === 'Home') { event.preventDefault(); selectAndFocus(SETTINGS_SECTIONS[0].id) }
                if (event.key === 'End') { event.preventDefault(); selectAndFocus(SETTINGS_SECTIONS.at(-1)!.id) }
              }}
              className={`relative min-h-16 rounded-xl px-2.5 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
                selected
                  ? 'bg-blue-500/12 text-blue-700 ring-1 ring-blue-400/30'
                  : 'text-slate-500 hover:bg-white/60 hover:text-slate-800'
              }`}
            >
              <span className="flex items-center gap-1.5 text-xs font-semibold">
                <Icon size={14} aria-hidden="true" />
                {section.label}
              </span>
              <span className="mt-1 block text-[11px] text-slate-400">{dirty ? '未保存' : section.description}</span>
              {dirty && <span className="absolute right-2 top-2 h-2 w-2 rounded-full bg-amber-500" aria-hidden="true" />}
            </button>
          )
        })}
      </div>
    </div>
  )
}
