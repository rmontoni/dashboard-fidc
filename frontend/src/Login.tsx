import { useState, type FormEvent } from 'react'
import { login } from './auth'
import type { UsuarioSessao } from './auth'
import './App.css'

type LoginProps = {
  onSucesso: (usuario: UsuarioSessao) => void
}

export default function Login({ onSucesso }: LoginProps) {
  const [username, setUsername] = useState('')
  const [senha, setSenha] = useState('')
  const [erro, setErro] = useState<string | null>(null)
  const [carregando, setCarregando] = useState(false)

  async function enviar(e: FormEvent) {
    e.preventDefault()
    setErro(null)
    setCarregando(true)
    try {
      const usuario = await login(username.trim(), senha)
      onSucesso(usuario)
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Falha no login.')
    } finally {
      setCarregando(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <p className="eyebrow">Legatus FIDC</p>
        <h1>Entrar</h1>

        {erro && <div className="banner-erro">{erro}</div>}

        <form className="form-fundo login-form" onSubmit={enviar}>
          <label>
            Username
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
            />
          </label>
          <label>
            Senha
            <input
              type="password"
              value={senha}
              onChange={(e) => setSenha(e.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          <button type="submit" className="btn-primario login-btn" disabled={carregando}>
            {carregando ? 'Entrando…' : 'Entrar'}
          </button>
        </form>
      </div>
    </div>
  )
}
