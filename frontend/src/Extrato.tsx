import { useEffect, useMemo, useState } from 'react'
import {
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { CalendarioDataBase } from './CalendarioDataBase'
import type { DataBaseDetalhe } from './types'
import { API_BASE } from './types'
import './App.css'

type SacadoItem = {
  sacado: string
  doc_sacado: string | null
  cedente?: string
  face: number
  vp: number
  pdd: number
  n_titulos: number
}

type CedenteItem = {
  cedente: string
  face: number
  vp: number
  n_sacados: number
  n_titulos: number
}

type PontoExtrato = {
  data: string
  label: string
  aquisicao: number
  face: number
  juros: number
  liquidacao: number
  vp: number
  vencido: number
  pdd: number
}

type RespostaExtrato = {
  data_ref: string
  sacado: string
  modo: string
  modo_label: string
  inicio: string | null
  serie: PontoExtrato[]
  kpis: {
    face: number
    vp: number
    vencido: number
    pdd: number
    aquisicao?: number
    juros?: number
    liquidacao?: number
  }
  kpis_hoje?: {
    data: string
    data_iso: string
    face: number
    vp: number
    vencido: number
    pdd: number
  }
}

const STORAGE_DATA_BASE = 'fidc_data_base'

function formatarMoeda(valor: number | null | undefined): string {
  return Number(valor ?? 0).toLocaleString('pt-BR', {
    style: 'currency',
    currency: 'BRL',
    maximumFractionDigits: 2,
  })
}

function celulaFluxo(valor: number): string {
  return valor > 0 ? formatarMoeda(valor) : '—'
}

function celulaJuros(valor: number): string {
  return Math.abs(valor) >= 0.01 ? formatarMoeda(valor) : '—'
}

function normalizarBusca(texto: string): string {
  return texto
    .normalize('NFD')
    .replace(/\p{M}/gu, '')
    .toLowerCase()
    .trim()
}

function compararNomes(a: string, b: string): number {
  return a.localeCompare(b, 'pt-BR', { sensitivity: 'base' })
}

function Extrato() {
  const [dataBase, setDataBase] = useState(
    () => localStorage.getItem(STORAGE_DATA_BASE) || '',
  )
  const [datasDetalhe, setDatasDetalhe] = useState<DataBaseDetalhe[]>([])
  const [feriados, setFeriados] = useState<Map<string, string>>(new Map())
  const [mesCalendario, setMesCalendario] = useState(() => {
    const hoje = new Date()
    return { ano: hoje.getFullYear(), mes: hoje.getMonth() }
  })
  const [cedentes, setCedentes] = useState<CedenteItem[]>([])
  const [cedenteSel, setCedenteSel] = useState('')
  const [sacados, setSacados] = useState<SacadoItem[]>([])
  const [sacadoSel, setSacadoSel] = useState('')
  const [buscaSacado, setBuscaSacado] = useState('')
  const [modo, setModo] = useState<'motor' | 'juros_pos_venc'>('motor')
  const [extrato, setExtrato] = useState<RespostaExtrato | null>(null)
  const [carregando, setCarregando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)

  const mapaDatas = useMemo(
    () => new Map(datasDetalhe.map((d) => [d.data_iso, d])),
    [datasDetalhe],
  )
  const dataSelecionada = datasDetalhe.find((d) => d.data === dataBase)

  const cedentesOrdenados = useMemo(
    () => [...cedentes].sort((a, b) => compararNomes(a.cedente, b.cedente)),
    [cedentes],
  )

  const sacadosOrdenados = useMemo(
    () => [...sacados].sort((a, b) => compararNomes(a.sacado, b.sacado)),
    [sacados],
  )

  const sacadosFiltrados = useMemo(() => {
    const termo = normalizarBusca(buscaSacado)
    if (!termo) return sacadosOrdenados
    return sacadosOrdenados.filter((s) => {
      const nome = normalizarBusca(s.sacado)
      const doc = normalizarBusca(s.doc_sacado ?? '')
      return nome.includes(termo) || doc.includes(termo)
    })
  }, [sacadosOrdenados, buscaSacado])

  useEffect(() => {
    let cancelado = false
    async function carregarDatas() {
      try {
        const res = await fetch(`${API_BASE}/fidc/datas`)
        if (!res.ok || cancelado) return
        const json = await res.json()
        const detalhe: DataBaseDetalhe[] =
          json.detalhe?.length > 0
            ? json.detalhe
            : (json.datas ?? []).map((data: string) => ({
                data,
                data_iso: data,
                status: 'ok',
                conciliada: true,
              }))
        setDatasDetalhe(detalhe)
        const mapaFer = new Map<string, string>()
        for (const f of json.feriados ?? []) {
          if (f?.data && f?.nome) mapaFer.set(String(f.data), String(f.nome))
        }
        setFeriados(mapaFer)
        if (!dataBase && detalhe.length > 0) {
          const ultima = detalhe[detalhe.length - 1]
          setDataBase(ultima.data)
          localStorage.setItem(STORAGE_DATA_BASE, ultima.data)
          if (ultima.data_iso) {
            const [y, m] = ultima.data_iso.split('-').map(Number)
            setMesCalendario({ ano: y, mes: m - 1 })
          }
        }
      } catch {
        /* backend offline */
      }
    }
    void carregarDatas()
    return () => {
      cancelado = true
    }
  }, [])

  useEffect(() => {
    if (!dataBase) return
    let cancelado = false
    async function carregarSacados() {
      try {
        const params = new URLSearchParams({ dataBase })
        if (cedenteSel) params.set('cedente', cedenteSel)
        const res = await fetch(`${API_BASE}/fidc/extrato/sacados?${params}`)
        const json = await res.json()
        if (cancelado) return
        if (!res.ok) {
          setCedentes([])
          setSacados([])
          return
        }
        setCedentes((json.cedentes ?? []) as CedenteItem[])
        const lista = (json.sacados ?? []) as SacadoItem[]
        setSacados(lista)
        setBuscaSacado('')
        setSacadoSel((atual) => {
          const ordenada = [...lista].sort((a, b) => compararNomes(a.sacado, b.sacado))
          if (atual && ordenada.some((s) => s.sacado === atual)) return atual
          return ordenada[0]?.sacado ?? ''
        })
      } catch {
        if (!cancelado) {
          setCedentes([])
          setSacados([])
        }
      }
    }
    void carregarSacados()
    return () => {
      cancelado = true
    }
  }, [dataBase, cedenteSel])

  useEffect(() => {
    if (!dataBase || !sacadoSel) {
      setExtrato(null)
      return
    }
    let cancelado = false
    const ctrl = new AbortController()
    const timer = window.setTimeout(() => ctrl.abort(), 120_000)
    async function carregarExtrato() {
      setCarregando(true)
      setErro(null)
      try {
        const params = new URLSearchParams({
          dataBase,
          sacado: sacadoSel,
          modo,
        })
        if (cedenteSel) params.set('cedente', cedenteSel)
        const res = await fetch(`${API_BASE}/fidc/extrato/sacado?${params}`, {
          signal: ctrl.signal,
        })
        const json = await res.json()
        if (cancelado) return
        if (!res.ok) {
          setExtrato(null)
          setErro(typeof json.detail === 'string' ? json.detail : 'Falha ao carregar extrato.')
          return
        }
        setExtrato(json as RespostaExtrato)
      } catch (e) {
        if (cancelado) return
        setExtrato(null)
        if (e instanceof DOMException && e.name === 'AbortError') {
          setErro(
            'Tempo esgotado (2 min). O servidor pode estar ocupado com a atualização — tente novamente em alguns minutos.',
          )
        } else {
          setErro(e instanceof Error ? e.message : 'Erro de rede')
        }
      } finally {
        window.clearTimeout(timer)
        if (!cancelado) setCarregando(false)
      }
    }
    void carregarExtrato()
    return () => {
      cancelado = true
      ctrl.abort()
      window.clearTimeout(timer)
    }
  }, [dataBase, sacadoSel, modo, cedenteSel])

  const grafico = useMemo(() => {
    if (!extrato?.serie?.length) return []
    const step = Math.max(1, Math.floor(extrato.serie.length / 120))
    return extrato.serie.filter((_, i) => i % step === 0 || i === extrato.serie.length - 1)
  }, [extrato])

  function selecionarData(data: string) {
    setDataBase(data)
    localStorage.setItem(STORAGE_DATA_BASE, data)
    const item = datasDetalhe.find((d) => d.data === data)
    if (item?.data_iso) {
      const [y, m] = item.data_iso.split('-').map(Number)
      setMesCalendario({ ano: y, mes: m - 1 })
    }
  }

  return (
    <div className="dashboard">
      <header className="topbar">
        <div>
          <h1>Extrato — {dataBase || '…'}</h1>
          {extrato?.inicio && (
            <p className="subtitulo">
              Desde {extrato.inicio} · {extrato.modo_label}
            </p>
          )}
        </div>
        <div className="topbar-direita">
          <CalendarioDataBase
            ano={mesCalendario.ano}
            mes={mesCalendario.mes}
            selecionada={dataBase}
            itemSelecionado={dataSelecionada}
            mapa={mapaDatas}
            feriados={feriados}
            onMesChange={(ano, mes) => setMesCalendario({ ano, mes })}
            onSelect={selecionarData}
          />
        </div>
      </header>

      <section className="painel">
        <div className="painel-cabecalho extrato-filtros">
          <label className="select-cotista">
            Cedente
            <select
              value={cedenteSel}
              onChange={(e) => setCedenteSel(e.target.value)}
              disabled={cedentesOrdenados.length === 0}
            >
              <option value="">Todos</option>
              {cedentesOrdenados.map((c) => (
                <option key={c.cedente} value={c.cedente}>
                  {c.cedente} — VP {formatarMoeda(c.vp)}
                </option>
              ))}
            </select>
          </label>
          <div className="select-cotista extrato-sacado-filtro">
            <label htmlFor="extrato-busca-sacado">Sacado</label>
            <input
              id="extrato-busca-sacado"
              type="search"
              className="extrato-busca-sacado"
              placeholder="Buscar por nome ou documento…"
              value={buscaSacado}
              onChange={(e) => setBuscaSacado(e.target.value)}
              disabled={sacadosOrdenados.length === 0}
              autoComplete="off"
            />
            <select
              value={
                sacadosFiltrados.some((s) => s.sacado === sacadoSel) ? sacadoSel : ''
              }
              onChange={(e) => setSacadoSel(e.target.value)}
              disabled={sacadosFiltrados.length === 0}
            >
              {sacadosFiltrados.length === 0 && (
                <option value="">
                  {sacadosOrdenados.length === 0
                    ? 'Sem sacados'
                    : 'Nenhum sacado na busca'}
                </option>
              )}
              {sacadosFiltrados.map((s) => (
                <option key={s.sacado} value={s.sacado}>
                  {s.sacado}
                  {s.doc_sacado ? ` (${s.doc_sacado})` : ''} — VP{' '}
                  {formatarMoeda(s.vp)}
                </option>
              ))}
            </select>
            {buscaSacado.trim() && sacadosFiltrados.length > 0 && (
              <span className="extrato-busca-contagem">
                {sacadosFiltrados.length} de {sacadosOrdenados.length}
              </span>
            )}
          </div>

          <div className="extrato-modos" role="group" aria-label="Modo de marcação">
            <span className="extrato-modos-label">Marcação</span>
            <button
              type="button"
              className={modo === 'motor' ? 'ativo' : ''}
              onClick={() => setModo('motor')}
            >
              1 — Sem juros após vencimento
            </button>
            <button
              type="button"
              className={modo === 'juros_pos_venc' ? 'ativo' : ''}
              onClick={() => setModo('juros_pos_venc')}
            >
              2 — Juros após vencimento
            </button>
          </div>
        </div>

        {extrato?.kpis && (
          <div className="painel-totais passivo-kpis extrato-kpis">
            <div className="painel-total">
              <span>Face (data base)</span>
              <strong>{formatarMoeda(extrato.kpis.face)}</strong>
            </div>
            <div className="painel-total">
              <span>VP (data base)</span>
              <strong>{formatarMoeda(extrato.kpis.vp)}</strong>
            </div>
            <div className="painel-total">
              <span>Vencido (data base)</span>
              <strong>{formatarMoeda(extrato.kpis.vencido)}</strong>
            </div>
            <div className="painel-total">
              <span>PDD (data base)</span>
              <strong>{formatarMoeda(extrato.kpis.pdd)}</strong>
            </div>
          </div>
        )}

        {extrato?.kpis_hoje && (
          <div className="painel-totais passivo-kpis extrato-kpis extrato-kpis-hoje">
            <p className="extrato-kpis-hoje-titulo">
              Projeção em {extrato.kpis_hoje.data} (calendário)
            </p>
            <div className="painel-total">
              <span>VP hoje</span>
              <strong>{formatarMoeda(extrato.kpis_hoje.vp)}</strong>
            </div>
            <div className="painel-total">
              <span>Vencido hoje</span>
              <strong>{formatarMoeda(extrato.kpis_hoje.vencido)}</strong>
            </div>
            <div className="painel-total">
              <span>Face hoje</span>
              <strong>{formatarMoeda(extrato.kpis_hoje.face)}</strong>
            </div>
            <div className="painel-total">
              <span>PDD hoje</span>
              <strong>{formatarMoeda(extrato.kpis_hoje.pdd)}</strong>
            </div>
          </div>
        )}
      </section>

      {carregando && <p className="vazio">Calculando extrato (motor)…</p>}
      {erro && <div className="banner-status banner-data">{erro}</div>}

      {!carregando && grafico.length > 0 && (
        <section className="painel">
          <div className="painel-cabecalho">
            <h2>Evolução diária</h2>
          </div>
          <div className="chart-wrap chart-fluxo">
            <ComposedChart
              responsive
              width="100%"
              height={360}
              data={grafico}
              margin={{ top: 12, right: 20, left: 8, bottom: 8 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#e8edf2" />
              <XAxis
                dataKey="label"
                tick={{ fill: '#5a6b7d', fontSize: 11 }}
                interval="preserveStartEnd"
                minTickGap={28}
              />
              <YAxis
                tick={{ fill: '#5a6b7d', fontSize: 12 }}
                tickFormatter={(v) =>
                  Number(v).toLocaleString('pt-BR', {
                    notation: 'compact',
                    maximumFractionDigits: 1,
                  })
                }
                width={56}
              />
              <Tooltip
                formatter={(value, name) => [
                  formatarMoeda(Number(value ?? 0)),
                  String(name),
                ]}
                labelFormatter={(_label, payload) => {
                  const row = payload?.[0]?.payload as PontoExtrato | undefined
                  if (!row?.data) return ''
                  return row.data.split('-').reverse().join('/')
                }}
                contentStyle={{
                  background: '#0f2740',
                  border: 'none',
                  borderRadius: 8,
                  color: '#fff',
                }}
              />
              <Legend />
              <Line
                type="monotone"
                dataKey="vp"
                name="VP"
                stroke="#1f6f8b"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="vencido"
                name="Vencido"
                stroke="#dc2626"
                strokeWidth={1.5}
                dot={false}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="face"
                name="Face"
                stroke="#9a3412"
                strokeWidth={1.5}
                strokeDasharray="4 4"
                dot={false}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="pdd"
                name="PDD"
                stroke="#b45309"
                strokeWidth={1.5}
                dot={false}
                isAnimationActive={false}
              />
            </ComposedChart>
          </div>

          {extrato && extrato.serie.length > 0 && (
            <div className="tabela-scroll extrato-serie-scroll">
              <table className="tabela-passivo">
                <thead>
                  <tr>
                    <th>Data</th>
                    <th>Aquisição</th>
                    <th>Face</th>
                    <th>Juros</th>
                    <th>Liquidações</th>
                    <th>VP</th>
                    <th>Vencido</th>
                    <th>PDD</th>
                  </tr>
                </thead>
                <tbody>
                  {[...extrato.serie].reverse().map((row) => (
                    <tr key={row.data}>
                      <td>{row.data.split('-').reverse().join('/')}</td>
                      <td>{celulaFluxo(row.aquisicao)}</td>
                      <td>{formatarMoeda(row.face)}</td>
                      <td>{celulaJuros(row.juros)}</td>
                      <td>{celulaFluxo(row.liquidacao)}</td>
                      <td>{formatarMoeda(row.vp)}</td>
                      <td>{formatarMoeda(row.vencido ?? 0)}</td>
                      <td>{formatarMoeda(row.pdd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {!carregando && extrato && extrato.serie.length === 0 && (
        <p className="vazio">Sem posição para este sacado no período.</p>
      )}
    </div>
  )
}

export default Extrato
