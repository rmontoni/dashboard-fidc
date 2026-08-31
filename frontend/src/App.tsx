import { useEffect, useState } from 'react'
import Configuracoes from './Configuracoes'
import Dashboard from './Dashboard'
import Divergencias from './Divergencias'
import Extrato from './Extrato'
import FluxoCaixa from './FluxoCaixa'
import Inadimplencia from './Inadimplencia'
import Passivo from './Passivo'
import Pdd from './Pdd'
import type { Fundo } from './types'
import { API_BASE } from './types'
import './App.css'

type Pagina =
  | 'dashboard'
  | 'passivo'
  | 'extrato'
  | 'pdd'
  | 'inadimplencia'
  | 'fluxo-caixa'
  | 'configuracoes'
  | 'divergencias'

type AtualizacaoItem = {
  id: string
  label: string
  data: string | null
  data_iso: string | null
  alvo?: string | null
  alvo_iso?: string | null
  politica?: 'd2' | 'idsf' | string
  atualizado?: boolean
}

type EtapaAtualizacao = {
  id: string
  label: string
  status: 'running' | 'ok' | 'erro' | string
  detalhe?: unknown
}

type StatusAtualizacao = {
  status: 'idle' | 'running' | 'ok' | 'erro' | string
  etapa?: string | null
  etapas?: EtapaAtualizacao[]
  erro?: string | null
  atualizacoes?: { itens?: AtualizacaoItem[] } | null
}

const STORAGE_FUNDO = 'fidc_fundo_selecionado_id'
const STORAGE_ATUALIZACOES_ABERTO = 'fidc_atualizacoes_aberto'
const STORAGE_PAGINA = 'fidc_pagina'
export const STORAGE_DATA_BASE = 'fidc_data_base'

const PAGINAS: Pagina[] = [
  'dashboard',
  'passivo',
  'extrato',
  'pdd',
  'inadimplencia',
  'fluxo-caixa',
  'configuracoes',
  'divergencias',
]

function paginaInicial(): Pagina {
  const salva = localStorage.getItem(STORAGE_PAGINA) || ''
  return PAGINAS.includes(salva as Pagina) ? (salva as Pagina) : 'dashboard'
}

function App() {
  const [pagina, setPaginaState] = useState<Pagina>(paginaInicial)
  const [fundo, setFundo] = useState<Fundo | null>(null)
  const [menuAberto, setMenuAberto] = useState(true)
  const [atualizacoes, setAtualizacoes] = useState<AtualizacaoItem[]>([])
  const [atualizacoesAberto, setAtualizacoesAberto] = useState(
    () => localStorage.getItem(STORAGE_ATUALIZACOES_ABERTO) !== '0',
  )
  const [atualizando, setAtualizando] = useState(false)
  const [statusAtualizacao, setStatusAtualizacao] = useState<StatusAtualizacao | null>(null)

  function setPagina(proxima: Pagina) {
    setPaginaState(proxima)
    localStorage.setItem(STORAGE_PAGINA, proxima)
  }

  function alternarAtualizacoes() {
    setAtualizacoesAberto((aberto) => {
      const proximo = !aberto
      localStorage.setItem(STORAGE_ATUALIZACOES_ABERTO, proximo ? '1' : '0')
      return proximo
    })
  }

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

  async function carregarAtualizacoes() {
    try {
      const res = await fetch(`${API_BASE}/fidc/atualizacoes`)
      if (!res.ok) return
      const dados = await res.json()
      setAtualizacoes(dados.itens ?? [])
    } catch {
      /* backend pode estar reiniciando */
    }
  }

  useEffect(() => {
    void carregarAtualizacoes()
  }, [])

  useEffect(() => {
    if (!atualizando) return
    let cancelado = false
    let idleSeguidos = 0
    const timer = window.setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/fidc/atualizar/status`)
        if (!res.ok || cancelado) return
        const dados: StatusAtualizacao = await res.json()
        if (cancelado) return
        setStatusAtualizacao(dados)
        if (dados.status === 'ok') {
          setAtualizando(false)
          if (dados.atualizacoes?.itens) {
            setAtualizacoes(dados.atualizacoes.itens)
          } else {
            void carregarAtualizacoes()
          }
        } else if (dados.status === 'erro') {
          setAtualizando(false)
        } else if (dados.status === 'idle') {
          // Job sumiu (restart) ou status de outro worker — não fica preso.
          idleSeguidos += 1
          if (idleSeguidos >= 3) {
            setAtualizando(false)
            setStatusAtualizacao({
              status: 'erro',
              erro: 'Atualização interrompida ou não encontrada no servidor. Tente de novo.',
            })
          }
        } else {
          idleSeguidos = 0
        }
      } catch {
        /* ignora falhas transitórias de polling */
      }
    }, 2000)
    return () => {
      cancelado = true
      window.clearInterval(timer)
    }
  }, [atualizando])

  async function cancelarAtualizacao() {
    try {
      const res = await fetch(`${API_BASE}/fidc/atualizar/cancelar`, { method: 'POST' })
      const dados = await res.json()
      setStatusAtualizacao(dados)
      setAtualizando(false)
    } catch {
      /* ignora */
    }
  }

  async function iniciarAtualizacao() {
    if (atualizando) return
    setAtualizando(true)
    setStatusAtualizacao({ status: 'running', etapa: 'Iniciando…', etapas: [] })
    try {
      const res = await fetch(`${API_BASE}/fidc/atualizar`, { method: 'POST' })
      const dados = await res.json()
      if (!res.ok || dados.aceito === false) {
        setAtualizando(false)
        setStatusAtualizacao({
          status: 'erro',
          erro: dados.motivo || dados.detail || 'Não foi possível iniciar a atualização.',
        })
        return
      }
      setStatusAtualizacao(dados)
    } catch (err) {
      setAtualizando(false)
      setStatusAtualizacao({
        status: 'erro',
        erro: err instanceof Error ? err.message : 'Falha ao iniciar atualização.',
      })
    }
  }

  function selecionarFundo(f: Fundo) {
    setFundo(f)
    localStorage.setItem(STORAGE_FUNDO, String(f.id))
  }

  const etapaAtual =
    statusAtualizacao?.etapa ||
    statusAtualizacao?.etapas?.find((e) => e.status === 'running')?.label

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
            className={pagina === 'passivo' ? 'nav-item ativo' : 'nav-item'}
            onClick={() => setPagina('passivo')}
          >
            Passivo
          </button>
          <button
            type="button"
            className={pagina === 'extrato' ? 'nav-item ativo' : 'nav-item'}
            onClick={() => setPagina('extrato')}
          >
            Extrato
          </button>
          <button
            type="button"
            className={pagina === 'pdd' ? 'nav-item ativo' : 'nav-item'}
            onClick={() => setPagina('pdd')}
          >
            PDD
          </button>
          <button
            type="button"
            className={pagina === 'inadimplencia' ? 'nav-item ativo' : 'nav-item'}
            onClick={() => setPagina('inadimplencia')}
          >
            Inadimplência
          </button>
          <button
            type="button"
            className={pagina === 'fluxo-caixa' ? 'nav-item ativo' : 'nav-item'}
            onClick={() => setPagina('fluxo-caixa')}
          >
            Fluxo de caixa
          </button>
          <button
            type="button"
            className={pagina === 'configuracoes' ? 'nav-item ativo' : 'nav-item'}
            onClick={() => setPagina('configuracoes')}
          >
            Configurações
          </button>
          <button
            type="button"
            className={pagina === 'divergencias' ? 'nav-item ativo' : 'nav-item'}
            onClick={() => setPagina('divergencias')}
          >
            Divergências
          </button>
        </nav>
        <div className="sidebar-atualizacoes-bloco">
          <button
            type="button"
            className="sidebar-atualizar-btn"
            onClick={() => void iniciarAtualizacao()}
            disabled={atualizando}
          >
            {atualizando ? 'Atualizando…' : 'Atualizar'}
          </button>
          {atualizando && etapaAtual && (
            <span className="sidebar-atualizar-etapa">{etapaAtual}</span>
          )}
          {atualizando && (
            <button
              type="button"
              className="sidebar-cancelar-atualizacao"
              onClick={() => void cancelarAtualizacao()}
            >
              Cancelar atualização
            </button>
          )}
          {!atualizando && statusAtualizacao?.status === 'erro' && statusAtualizacao.erro && (
            <span className="sidebar-atualizar-erro" title={statusAtualizacao.erro}>
              {statusAtualizacao.erro}
            </span>
          )}
          {!atualizando && statusAtualizacao?.status === 'ok' && (
            <span className="sidebar-atualizar-ok">Bases atualizadas</span>
          )}
          {atualizacoes.length > 0 && (
            <div className="sidebar-atualizacoes">
              <button
                type="button"
                className="sidebar-atualizacoes-cabecalho"
                onClick={alternarAtualizacoes}
                aria-expanded={atualizacoesAberto}
              >
                <span className="sidebar-atualizacoes-titulo">Última atualização</span>
                <span className="sidebar-atualizacoes-seta" aria-hidden>
                  {atualizacoesAberto ? '▾' : '▸'}
                </span>
              </button>
              {atualizacoesAberto && (
                <ul>
                  {atualizacoes.map((item) => (
                    <li
                      key={item.id}
                      className={
                        item.atualizado === false ? 'sidebar-atualizacao-pendente' : undefined
                      }
                      title={
                        item.atualizado === false && item.alvo
                          ? `Alvo: ${item.alvo} (${item.politica === 'd2' ? 'D-2' : 'IDSF'})`
                          : undefined
                      }
                    >
                      <span>{item.label}</span>
                      <strong>{item.data ?? '—'}</strong>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
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
        {pagina === 'dashboard' && <Dashboard fundoNome={fundo?.nome} />}
        {pagina === 'passivo' && <Passivo />}
        {pagina === 'extrato' && <Extrato />}
        {pagina === 'pdd' && <Pdd />}
        {pagina === 'inadimplencia' && <Inadimplencia />}
        {pagina === 'fluxo-caixa' && <FluxoCaixa />}
        {pagina === 'configuracoes' && (
          <Configuracoes
            fundoSelecionadoId={fundo?.id ?? null}
            onSelecionarFundo={selecionarFundo}
          />
        )}
        {pagina === 'divergencias' && <Divergencias />}
      </main>
    </div>
  )
}

export default App
