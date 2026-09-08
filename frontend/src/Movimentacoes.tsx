import { useEffect, useMemo, useState } from 'react'
import { API_BASE } from './types'
import './App.css'

type AbaMov = 'aquisicoes' | 'liquidacoes'

type LinhaAq = {
  data: string
  data_iso: string
  vencimento: string | null
  vencimento_iso: string | null
  cedente: string
  sacado: string
  valor: number
  valor_face: number
  taxa_am: number | null
  du: number
  seu_numero: string
}

type LinhaLiq = {
  data: string
  data_iso: string
  cedente: string
  sacado: string
  ocorrencia: string
  situacao: string
  vencimento: string | null
  vencimento_iso: string | null
  valor_pago: number
  ajuste: number
  tipo_recebivel: string
}

type RespostaMov = {
  tipo: AbaMov
  inicio: string
  fim: string
  cedentes: string[]
  sacados: string[]
  totais: {
    n: number
    valor?: number
    valor_face?: number
    taxa_am_media?: number | null
    valor_pago?: number
    ajuste?: number
  }
  linhas: Array<LinhaAq | LinhaLiq>
}

type Coluna = { id: string; rotulo: string; numerico?: boolean }

const COLUNAS_AQ: Coluna[] = [
  { id: 'data_iso', rotulo: 'Data' },
  { id: 'vencimento_iso', rotulo: 'Vencimento' },
  { id: 'cedente', rotulo: 'Cedente' },
  { id: 'sacado', rotulo: 'Sacado' },
  { id: 'valor', rotulo: 'Valor', numerico: true },
  { id: 'valor_face', rotulo: 'Valor de face', numerico: true },
  { id: 'taxa_am', rotulo: 'Taxa a.m.', numerico: true },
  { id: 'seu_numero', rotulo: 'Seu número' },
]

const COLUNAS_LIQ: Coluna[] = [
  { id: 'data_iso', rotulo: 'Data' },
  { id: 'cedente', rotulo: 'Cedente' },
  { id: 'sacado', rotulo: 'Sacado' },
  { id: 'ocorrencia', rotulo: 'Ocorrência' },
  { id: 'situacao', rotulo: 'Situação' },
  { id: 'vencimento_iso', rotulo: 'Data de vencimento' },
  { id: 'valor_pago', rotulo: 'Valor pago', numerico: true },
  { id: 'ajuste', rotulo: 'Ajuste', numerico: true },
  { id: 'tipo_recebivel', rotulo: 'Tipo recebível' },
]

function formatarMoeda(valor: number | null | undefined): string {
  return Number(valor ?? 0).toLocaleString('pt-BR', {
    style: 'currency',
    currency: 'BRL',
    maximumFractionDigits: 2,
  })
}

function formatarPct(valor: number | null | undefined): string {
  if (valor == null || Number.isNaN(Number(valor))) return '—'
  return `${Number(valor).toLocaleString('pt-BR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  })}%`
}

function hojeIso(): string {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function somarDiasIso(iso: string, dias: number): string {
  const d = new Date(`${iso}T12:00:00`)
  if (Number.isNaN(d.getTime())) return iso
  d.setDate(d.getDate() + dias)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function valorCelula(row: Record<string, unknown>, id: string): unknown {
  if (id === 'vencimento_iso') return row.vencimento || row.vencimento_iso
  if (id === 'data_iso') return row.data || row.data_iso
  return row[id]
}

function Movimentacoes() {
  const [aba, setAba] = useState<AbaMov>('aquisicoes')
  const [inicio, setInicio] = useState(() => somarDiasIso(hojeIso(), -30))
  const [fim, setFim] = useState(() => hojeIso())
  const [cedente, setCedente] = useState('')
  const [sacado, setSacado] = useState('')
  const [buscaSacado, setBuscaSacado] = useState('')
  const [dados, setDados] = useState<RespostaMov | null>(null)
  const [carregando, setCarregando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const [ordenarPor, setOrdenarPor] = useState('data_iso')
  const [ordenarDir, setOrdenarDir] = useState<'asc' | 'desc'>('desc')

  const colunas = aba === 'aquisicoes' ? COLUNAS_AQ : COLUNAS_LIQ

  useEffect(() => {
    let cancelado = false
    async function carregar() {
      setCarregando(true)
      setErro(null)
      try {
        const qs = new URLSearchParams({ inicio, fim })
        if (cedente) qs.set('cedente', cedente)
        if (sacado) qs.set('sacado', sacado)
        const res = await fetch(`${API_BASE}/fidc/movimentacoes/${aba}?${qs}`)
        const json = await res.json()
        if (cancelado) return
        if (!res.ok) {
          setErro(json.detail || 'Falha ao carregar movimentações.')
          setDados(null)
          return
        }
        setDados(json)
      } catch (err) {
        if (!cancelado) {
          setErro(err instanceof Error ? err.message : 'Falha ao carregar movimentações.')
          setDados(null)
        }
      } finally {
        if (!cancelado) setCarregando(false)
      }
    }
    void carregar()
    return () => {
      cancelado = true
    }
  }, [aba, inicio, fim, cedente, sacado])

  const cedentes = useMemo(
    () => [...(dados?.cedentes ?? [])].sort((a, b) => a.localeCompare(b, 'pt-BR')),
    [dados],
  )

  const sacadosFiltrados = useMemo(() => {
    const lista = [...(dados?.sacados ?? [])].sort((a, b) =>
      a.localeCompare(b, 'pt-BR'),
    )
    const termo = buscaSacado.trim().toLowerCase()
    if (!termo) return lista
    return lista.filter((s) => s.toLowerCase().includes(termo))
  }, [dados, buscaSacado])

  const linhas = useMemo(() => {
    const lista = (dados?.linhas ?? []) as Array<Record<string, unknown>>
    const sinal = ordenarDir === 'asc' ? 1 : -1
    return [...lista].sort((a, b) => {
      const va = a[ordenarPor]
      const vb = b[ordenarPor]
      if (typeof va === 'number' && typeof vb === 'number') {
        return (va - vb) * sinal
      }
      if (va == null && vb == null) return 0
      if (va == null) return 1
      if (vb == null) return -1
      return (
        String(va).localeCompare(String(vb), 'pt-BR', {
          numeric: true,
          sensitivity: 'base',
        }) * sinal
      )
    })
  }, [dados, ordenarPor, ordenarDir])

  function clicarColuna(id: string, numerico?: boolean) {
    if (ordenarPor === id) {
      setOrdenarDir((d) => (d === 'asc' ? 'desc' : 'asc'))
      return
    }
    setOrdenarPor(id)
    setOrdenarDir(numerico ? 'desc' : 'asc')
  }

  function trocarAba(proxima: AbaMov) {
    setAba(proxima)
    setCedente('')
    setSacado('')
    setBuscaSacado('')
    setOrdenarPor('data_iso')
    setOrdenarDir('desc')
  }

  return (
    <div className="dashboard">
      <header className="topbar">
        <div>
          <p className="eyebrow">BDR · histórico de movimentações</p>
          <h1>Movimentações</h1>
        </div>
      </header>

      <nav className="abas-passivo" aria-label="Tipo de movimentação">
        <button
          type="button"
          className={aba === 'aquisicoes' ? 'aba ativa' : 'aba'}
          onClick={() => trocarAba('aquisicoes')}
        >
          Aquisições
        </button>
        <button
          type="button"
          className={aba === 'liquidacoes' ? 'aba ativa' : 'aba'}
          onClick={() => trocarAba('liquidacoes')}
        >
          Liquidações
        </button>
      </nav>

      <section className="painel">
        <div className="painel-cabecalho extrato-filtros">
          <label className="select-cotista">
            De
            <input
              type="date"
              value={inicio}
              onChange={(e) => setInicio(e.target.value)}
            />
          </label>
          <label className="select-cotista">
            Até
            <input type="date" value={fim} onChange={(e) => setFim(e.target.value)} />
          </label>
          <label className="select-cotista">
            Cedente
            <select
              value={cedente}
              onChange={(e) => setCedente(e.target.value)}
              disabled={!dados}
            >
              <option value="">Todos</option>
              {cedentes.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <div className="select-cotista extrato-sacado-filtro">
            <label htmlFor="mov-busca-sacado">Sacado</label>
            <input
              id="mov-busca-sacado"
              type="search"
              className="extrato-busca-sacado"
              placeholder="Buscar sacado…"
              value={buscaSacado}
              onChange={(e) => setBuscaSacado(e.target.value)}
              disabled={!dados}
              autoComplete="off"
            />
            <select
              value={sacadosFiltrados.includes(sacado) ? sacado : ''}
              onChange={(e) => setSacado(e.target.value)}
              disabled={sacadosFiltrados.length === 0}
            >
              <option value="">Todos</option>
              {sacadosFiltrados.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
        </div>

        {dados?.totais && (
          <div className="painel-totais passivo-kpis extrato-kpis">
            <div className="painel-total">
              <span>Linhas</span>
              <strong>{Number(dados.totais.n || 0).toLocaleString('pt-BR')}</strong>
            </div>
            {aba === 'aquisicoes' ? (
              <>
                <div className="painel-total">
                  <span>Valor (compra)</span>
                  <strong>{formatarMoeda(dados.totais.valor)}</strong>
                </div>
                <div className="painel-total">
                  <span>Valor de face</span>
                  <strong>{formatarMoeda(dados.totais.valor_face)}</strong>
                </div>
                <div className="painel-total">
                  <span>Taxa a.m. média</span>
                  <strong>{formatarPct(dados.totais.taxa_am_media ?? null)}</strong>
                </div>
              </>
            ) : (
              <>
                <div className="painel-total">
                  <span>Valor pago</span>
                  <strong>{formatarMoeda(dados.totais.valor_pago)}</strong>
                </div>
                <div className="painel-total">
                  <span>Ajuste</span>
                  <strong>{formatarMoeda(dados.totais.ajuste)}</strong>
                </div>
              </>
            )}
          </div>
        )}
      </section>

      {carregando && <p className="vazio">Carregando movimentações…</p>}
      {erro && <div className="banner-status banner-data">{erro}</div>}

      {!carregando && dados && (
        <section className="painel">
          <div className="painel-cabecalho">
            <h2>{aba === 'aquisicoes' ? 'Aquisições' : 'Liquidações'}</h2>
            <p className="subtitulo">
              {dados.inicio} a {dados.fim}
            </p>
          </div>
          <div className="tabela-scroll extrato-serie-scroll mov-tabela-scroll">
            <table className="tabela-passivo">
              <thead>
                <tr>
                  {colunas.map((col) => (
                    <th key={col.id}>
                      <button
                        type="button"
                        className="th-ordenar"
                        onClick={() => clicarColuna(col.id, col.numerico)}
                      >
                        {col.rotulo}
                        {ordenarPor === col.id
                          ? ordenarDir === 'asc'
                            ? ' ↑'
                            : ' ↓'
                          : ''}
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {linhas.map((row, i) => (
                  <tr key={`${String(row.seu_numero || '')}-${String(row.data_iso)}-${i}`}>
                    {colunas.map((col) => {
                      const raw = valorCelula(row, col.id)
                      let texto: string
                      if (col.id === 'taxa_am') {
                        texto = formatarPct(raw as number | null)
                      } else if (col.numerico) {
                        texto = formatarMoeda(Number(raw ?? 0))
                      } else {
                        texto = String(raw || '—')
                      }
                      return <td key={col.id}>{texto}</td>
                    })}
                  </tr>
                ))}
                {linhas.length === 0 && (
                  <tr>
                    <td colSpan={colunas.length}>Nenhuma movimentação no filtro.</td>
                  </tr>
                )}
              </tbody>
              {linhas.length > 0 && (
                <tfoot className="mov-totais-fixo">
                  <tr>
                    {colunas.map((col, idx) => {
                      if (idx === 0) {
                        return (
                          <td key={col.id}>
                            <strong>Total ({dados.totais.n})</strong>
                          </td>
                        )
                      }
                      if (aba === 'aquisicoes') {
                        if (col.id === 'valor') {
                          return (
                            <td key={col.id}>
                              <strong>{formatarMoeda(dados.totais.valor)}</strong>
                            </td>
                          )
                        }
                        if (col.id === 'valor_face') {
                          return (
                            <td key={col.id}>
                              <strong>{formatarMoeda(dados.totais.valor_face)}</strong>
                            </td>
                          )
                        }
                        if (col.id === 'taxa_am') {
                          return (
                            <td key={col.id}>
                              <strong>
                                {formatarPct(dados.totais.taxa_am_media ?? null)}
                              </strong>
                            </td>
                          )
                        }
                      } else {
                        if (col.id === 'valor_pago') {
                          return (
                            <td key={col.id}>
                              <strong>{formatarMoeda(dados.totais.valor_pago)}</strong>
                            </td>
                          )
                        }
                        if (col.id === 'ajuste') {
                          return (
                            <td key={col.id}>
                              <strong>{formatarMoeda(dados.totais.ajuste)}</strong>
                            </td>
                          )
                        }
                      }
                      return <td key={col.id} />
                    })}
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        </section>
      )}
    </div>
  )
}

export default Movimentacoes
