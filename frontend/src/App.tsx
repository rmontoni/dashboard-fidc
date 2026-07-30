import { useEffect, useState } from 'react'
import Configuracoes from './Configuracoes'
import Dashboard from './Dashboard'
import type { Fundo } from './types'
import { API_BASE } from './types'
import './App.css'

type Pagina = 'dashboard' | 'configuracoes'

const STORAGE_FUNDO = 'fidc_fundo_selecionado_id'

function App() {
  const [pagina, setPagina] = useState<Pagina>('dashboard')
  const [fundo, setFundo] = useState<Fundo | null>(null)
  const [menuAberto, setMenuAberto] = useState(true)

  useEffect(() => {
    let cancelado = false
    async function bootstrap() {
      try {
        const res = await fetch(`${API_BASE}/fidc/fundos?ativos=true`)
        if (!res.ok) return
        const dados = await res.json()
        const lista: Fundo[] = dados.fundos ?? []
        if (cancelado || lista.length === 0) return
        const salvo = Number(localStorage.getItem(STORAGE_FUNDO) || 0)
        const preferido =
          lista.find((f) => f.id === salvo) ||
          lista.find((f) => f.codigo === 'alpha') ||
          lista[0]
        setFundo(preferido)
      } catch {
        /* tabela pode ainda não existir */
      }
    }
    void bootstrap()
    return () => {
      cancelado = true
    }
  }, [])

  function selecionarFundo(f: Fundo) {
    setFundo(f)
    localStorage.setItem(STORAGE_FUNDO, String(f.id))
  }

  return (
    <div className={`shell ${menuAberto ? 'shell-menu-aberto' : 'shell-menu-fechado'}`}>
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="sidebar-eyebrow">Legatus</span>
          <strong>FIDC Risk</strong>
        </div>
        <nav className="sidebar-nav">
          <button
            type="button"
            className={pagina === 'dashboard' ? 'nav-item ativo' : 'nav-item'}
            onClick={() => setPagina('dashboard')}
          >
            Dashboard
          </button>
          <button
            type="button"
            className={pagina === 'configuracoes' ? 'nav-item ativo' : 'nav-item'}
            onClick={() => setPagina('configuracoes')}
          >
            Configurações
          </button>
        </nav>
        {fundo && (
          <div className="sidebar-fundo">
            <span>Fundo ativo</span>
            <strong>{fundo.nome}</strong>
            <small>{fundo.cnpj_formatado || fundo.cnpj}</small>
          </div>
        )}
        <button
          type="button"
          className="sidebar-toggle"
          onClick={() => setMenuAberto((v) => !v)}
          aria-label={menuAberto ? 'Recolher menu' : 'Expandir menu'}
        >
          {menuAberto ? '«' : '»'}
        </button>
      </aside>

      <main className="shell-conteudo">
        {pagina === 'dashboard' ? (
          <Dashboard fundoNome={fundo?.nome} />
        ) : (
          <Configuracoes
            fundoSelecionadoId={fundo?.id ?? null}
            onSelecionarFundo={selecionarFundo}
          />
        )}
      </main>
    </div>
  )
}

export default App
