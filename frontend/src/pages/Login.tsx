import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bot, Sparkles } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await login(username, password)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className="min-h-screen flex items-center justify-center p-4"
      style={{
        background: 'linear-gradient(180deg, #f8fbff 0%, #eef6ff 100%)',
      }}
    >
      <div className="w-full max-w-sm">
        <div className="flex items-center justify-center gap-3 mb-8">
          <div
            className="w-12 h-12 rounded-xl flex items-center justify-center"
            style={{ background: 'linear-gradient(135deg, #2563eb 0%, #0ea5e9 100%)' }}
          >
            <Bot size={24} style={{ color: '#fff' }} />
          </div>
          <div>
            <div className="font-semibold text-lg text-white flex items-center gap-1.5">
              诡诡RAG搜索
              <Sparkles size={14} className="text-violet-400" />
            </div>
            <div className="text-sm text-zinc-500">管理控制台</div>
          </div>
        </div>

        <form
          onSubmit={handleSubmit}
          className="rounded-2xl p-6 space-y-4"
          style={{
            background: 'rgba(255,255,255,0.88)',
            border: '1px solid rgba(148,163,184,0.22)',
            boxShadow: '0 22px 55px rgba(37,99,235,0.12)',
          }}
        >
          <div>
            <label className="block text-sm font-medium text-zinc-400 mb-1.5">用户名</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-4 py-2.5 rounded-xl input-glass text-sm"
              placeholder="admin"
              required
              autoComplete="username"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-zinc-400 mb-1.5">密码</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-4 py-2.5 rounded-xl input-glass text-sm"
              placeholder="••••••••"
              required
              autoComplete="current-password"
            />
          </div>
          {error && (
            <div className="text-sm text-red-400 bg-red-500/10 rounded-lg px-3 py-2">{error}</div>
          )}
          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 rounded-xl font-medium text-white transition-all disabled:opacity-50"
            style={{
              background: 'linear-gradient(135deg, #2563eb 0%, #0ea5e9 100%)',
              color: '#fff',
            }}
          >
            {loading ? '登录中...' : '登录'}
          </button>
        </form>
      </div>
    </div>
  )
}
