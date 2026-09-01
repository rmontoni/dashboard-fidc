import { useEffect, useState, type FormEvent } from 'react'
import { authHeaders } from './auth'
import type { UsuarioSessao } from './auth'
import { API_BASE } from './types'

const USUARIO_VAZIO = {
  nome: '',
  username: '',
  senha: '',
  perfil: 'usuario' as 'admin' | 'usuario',
  ativo: true,
}

type UsuarioRow = {
  id: number
  nome: string
  username: string
  perfil: 'admin' | 'usuario'
  ativo: boolean
}

type UsuariosConfigProps = {
  usuarioLogado: UsuarioSessao
}

export default function UsuariosConfig({ usuarioLogado }: UsuariosConfigProps) {
  const [usuarios, setUsuarios] = useState<UsuarioRow[]>([])
  const [editandoId, setEditandoId] = useState<number | null>(null)
  const [form, setForm] = useState({ ...USUARIO_VAZIO })
  const [erro, setErro] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [carregando, setCarregando] = useState(false)

  async function carregar() {
    setErro(null)
    try {
      const res = await fetch(`${API_BASE}/fidc/usuarios`, { headers: authHeaders() })
      const json = await res.json()
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`)
      setUsuarios((json.usuarios ?? []) as UsuarioRow[])
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Falha ao carregar usuários.')
      setUsuarios([])
    }
  }

  useEffect(() => {
    void carregar()
  }, [])

  function iniciarNovo() {
    setEditandoId(null)
    setForm({ ...USUARIO_VAZIO })
    setOk(null)
    setErro(null)
  }

  function iniciarEdicao(u: UsuarioRow) {
    setEditandoId(u.id)
    setForm({
      nome: u.nome,
      username: u.username,
      senha: '',
      perfil: u.perfil,
      ativo: u.ativo,
    })
    setOk(null)
    setErro(null)
  }

  async function salvar(e: FormEvent) {
    e.preventDefault()
    setErro(null)
    setOk(null)
    setCarregando(true)
    try {
      const payload: Record<string, unknown> = {
        nome: form.nome.trim(),
        username: form.username.trim(),
        perfil: form.perfil,
        ativo: form.ativo,
      }
      if (form.senha.trim()) payload.senha = form.senha

      const url =
        editandoId == null
          ? `${API_BASE}/fidc/usuarios`
          : `${API_BASE}/fidc/usuarios/${editandoId}`
      const res = await fetch(url, {
        method: editandoId == null ? 'POST' : 'PATCH',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(
          editandoId == null
            ? { ...payload, senha: form.senha }
            : payload,
        ),
      })
      const json = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`)
      setOk(editandoId == null ? 'Usuário criado.' : 'Usuário atualizado.')
      await carregar()
      if (editandoId == null) iniciarNovo()
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Falha ao salvar.')
    } finally {
      setCarregando(false)
    }
  }

  async function excluir(id: number) {
    if (id === usuarioLogado.id) {
      setErro('Você não pode excluir o próprio usuário.')
      return
    }
    if (!confirm('Excluir este usuário?')) return
    setErro(null)
    setOk(null)
    try {
      const res = await fetch(`${API_BASE}/fidc/usuarios/${id}`, {
        method: 'DELETE',
        headers: authHeaders(),
      })
      if (!res.ok) {
        const json = await res.json().catch(() => ({}))
        throw new Error(json.detail || `HTTP ${res.status}`)
      }
      setOk('Usuário excluído.')
      await carregar()
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Falha ao excluir.')
    }
  }

  return (
    <>
      {erro && <div className="banner-erro">{erro}</div>}
      {ok && <div className="banner-ok">{ok}</div>}
      <div className="config-toolbar">
        <button type="button" className="btn-primario" onClick={iniciarNovo}>
          Novo usuário
        </button>
      </div>
      <div className="config-grid">
        <section className="painel">
          <h2>Usuários ({usuarios.length})</h2>
          <div className="tabela-wrap tabela-scroll">
            <table>
              <thead>
                <tr>
                  <th>Nome</th>
                  <th>Username</th>
                  <th>Perfil</th>
                  <th>Ativo</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {usuarios.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="vazio">
                      Nenhum usuário cadastrado.
                    </td>
                  </tr>
                ) : (
                  usuarios.map((u) => (
                    <tr key={u.id} className={u.id === usuarioLogado.id ? 'linha-ativa' : undefined}>
                      <td>{u.nome}</td>
                      <td>{u.username}</td>
                      <td>{u.perfil === 'admin' ? 'Administrador' : 'Usuário'}</td>
                      <td>{u.ativo ? 'Sim' : 'Não'}</td>
                      <td className="acoes-fundo">
                        <button type="button" onClick={() => iniciarEdicao(u)}>
                          Editar
                        </button>
                        <button type="button" onClick={() => void excluir(u.id)}>
                          Excluir
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="painel">
          <h2>{editandoId == null ? 'Novo usuário' : `Editar usuário #${editandoId}`}</h2>
          <form className="form-fundo" onSubmit={salvar}>
            <label>
              Nome
              <input
                value={form.nome}
                onChange={(e) => setForm({ ...form, nome: e.target.value })}
                required
              />
            </label>
            <label>
              Username
              <input
                type="text"
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
                required
                autoComplete="off"
              />
            </label>
            <label>
              Senha {editandoId != null && '(deixe vazio para manter)'}
              <input
                type="password"
                value={form.senha}
                onChange={(e) => setForm({ ...form, senha: e.target.value })}
                required={editandoId == null}
                autoComplete="new-password"
              />
            </label>
            <label>
              Perfil
              <select
                value={form.perfil}
                onChange={(e) =>
                  setForm({
                    ...form,
                    perfil: e.target.value as 'admin' | 'usuario',
                  })
                }
              >
                <option value="usuario">Usuário</option>
                <option value="admin">Administrador</option>
              </select>
            </label>
            <label className="check-linha">
              <input
                type="checkbox"
                checked={form.ativo}
                onChange={(e) => setForm({ ...form, ativo: e.target.checked })}
              />
              Ativo
            </label>
            <div className="form-acoes">
              <button type="submit" className="btn-primario" disabled={carregando}>
                Salvar
              </button>
              <button type="button" onClick={iniciarNovo}>
                Limpar
              </button>
            </div>
          </form>
        </section>
      </div>
    </>
  )
}
