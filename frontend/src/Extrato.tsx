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
  empresas?: string[]
  empresa?: string | null
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

type EmpresaItem = {
  empresa: string
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
  const [empresas, setEmpresas] = useState<EmpresaItem[]>([])
  /** null = Todas; Set = filtro; empty Set + nenhuma = desmarcadas */
  const [empresasFiltro, setEmpresasFiltro] = useState<Set<string>>(new Set())
  const [empresasNenhuma, setEmpresasNenhuma] = useState(false)
  const [buscaEmpresa, setBuscaEmpresa] = useState('')
  const [sugestoesEmpresaAberto, setSugestoesEmpresaAberto] = useState(false)
  const [sacados, setSacados] = useState<SacadoItem[]>([])
  /** null = ainda não escolhido (auto 1º); '' = Todos; nome = sacado */
  const [sacadoSel, setSacadoSel] = useState<string | null>(null)
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

  const empresasOrdenadas = useMemo(
    () => [...empresas].sort((a, b) => compararNomes(a.empresa, b.empresa)),
    [empresas],
  )

  const empresasParam = useMemo(() => {
    if (empresasNenhuma) return '__nenhuma__'
    if (empresasFiltro.size === 0) return ''
    return [...empresasFiltro].sort(compararNomes).join('|')
  }, [empresasFiltro, empresasNenhuma])

  const termoBuscaEmpresa = useMemo(
    () => normalizarBusca(buscaEmpresa),
    [buscaEmpresa],
  )

  const empresasNaLista = useMemo(() => {
    if (termoBuscaEmpresa.length < 3) return empresasOrdenadas
    return empresasOrdenadas.filter((e) =>
      normalizarBusca(e.empresa).includes(termoBuscaEmpresa),
    )
  }, [empresasOrdenadas, termoBuscaEmpresa])

  const sugestoesEmpresa = useMemo(() => {
    if (termoBuscaEmpresa.length < 3) return []
    return empresasNaLista.slice(0, 30)
  }, [empresasNaLista, termoBuscaEmpresa])

  const valorSelectEmpresa = useMemo(() => {
    if (empresasNenhuma) return '__nenhuma__'
    if (empresasFiltro.size === 0) return ''
    if (empresasFiltro.size === 1) return [...empresasFiltro][0]
    return '__multi__'
  }, [empresasFiltro, empresasNenhuma])

  const sacadosPorEmpresa = useMemo(() => {
    if (empresasNenhuma) return []
    if (empresasFiltro.size === 0) return sacados
    return sacados.filter((s) =>
      (s.empresas ?? []).some((e) => empresasFiltro.has(e)),
    )
  }, [sacados, empresasFiltro, empresasNenhuma])

  const sacadosOrdenados = useMemo(
    () => [...sacadosPorEmpresa].sort((a, b) => compararNomes(a.sacado, b.sacado)),
    [sacadosPorEmpresa],
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

  function selecionarTodasEmpresas() {
    setEmpresasNenhuma(false)
    setEmpresasFiltro(new Set())
  }

  function desmarcarTodasEmpresas() {
    setEmpresasNenhuma(true)
    setEmpresasFiltro(new Set())
  }

  function escolherEmpresa(nome: string) {
    if (!empresasNenhuma && empresasFiltro.size === 0) {
      setEmpresasNenhuma(false)
      setEmpresasFiltro(new Set([nome]))
      return
    }
    const prox = new Set(empresasFiltro)
    if (prox.has(nome)) prox.delete(nome)
    else prox.add(nome)
    if (prox.size === 0) {
      desmarcarTodasEmpresas()
      return
    }
    if (prox.size === empresasOrdenadas.length) {
      selecionarTodasEmpresas()
      return
    }
    setEmpresasNenhuma(false)
    setEmpresasFiltro(prox)
  }

  function onEmpresaSelectChange(value: string) {
    if (value === '') {
      selecionarTodasEmpresas()
      return
    }
    if (value === '__nenhuma__') {
      desmarcarTodasEmpresas()
      return
    }
    if (value === '__multi__') return
    escolherEmpresa(value)
  }

  useEffect(() => {
    if (!sugestoesEmpresaAberto) return
    function fechar(ev: MouseEvent) {
      const alvo = ev.target as HTMLElement | null
      if (alvo?.closest('.extrato-empresa-filtro')) return
      setSugestoesEmpresaAberto(false)
    }
    document.addEventListener('mousedown', fechar)
    return () => document.removeEventListener('mousedown', fechar)
  }, [sugestoesEmpresaAberto])

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
          setEmpresas([])
          setSacados([])
          return
        }
        setCedentes((json.cedentes ?? []) as CedenteItem[])
        const listaEmp = (json.empresas ?? []) as EmpresaItem[]
        setEmpresas(listaEmp)
        setEmpresasFiltro((atual) => {
          if (atual.size === 0) return atual
          const nomes = new Set(listaEmp.map((e) => e.empresa))
          const prox = new Set([...atual].filter((e) => nomes.has(e)))
          if (prox.size === 0) {
            setEmpresasNenhuma(true)
            return new Set()
          }
          if (prox.size === nomes.size) {
            setEmpresasNenhuma(false)
            return new Set()
          }
          return prox
        })
        setBuscaEmpresa('')
        const lista = (json.sacados ?? []) as SacadoItem[]
        setSacados(lista)
        setBuscaSacado('')
        setSacadoSel((atual) => {
          if (atual === '') return ''
          const ordenada = [...lista].sort((a, b) =>
            compararNomes(a.sacado, b.sacado),
          )
          if (atual && ordenada.some((s) => s.sacado === atual)) return atual
          return ordenada[0]?.sacado ?? ''
        })
      } catch {
        if (!cancelado) {
          setCedentes([])
          setEmpresas([])
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
    if (!dataBase || sacadoSel === null) {
      setExtrato(null)
      return
    }
    let cancelado = false
    const ctrl = new AbortController()
    const timer = window.setTimeout(() => ctrl.abort(), 180_000)
    async function carregarExtrato() {
      setCarregando(true)
      setErro(null)
      try {
        const params = new URLSearchParams({
          dataBase,
          sacado: sacadoSel || 'Todos',
          modo,
        })
        if (cedenteSel) params.set('cedente', cedenteSel)
        if (empresasParam) params.set('empresas', empresasParam)
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
            'Tempo esgotado. O servidor pode estar ocupado — tente novamente ou filtre por empresa/sacado.',
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
  }, [dataBase, sacadoSel, modo, cedenteSel, empresasParam])

  useEffect(() => {
    if (sacadoSel === null || sacadoSel === '') return
    if (!sacadosOrdenados.some((s) => s.sacado === sacadoSel)) {
      setSacadoSel('')
    }
  }, [sacadosOrdenados, sacadoSel])

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
              {sacadoSel || 'Todos os sacados'} · Desde {extrato.inicio} ·{' '}
              {extrato.modo_label}
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

          <div className="select-cotista extrato-empresa-filtro">
            <label htmlFor="extrato-busca-empresa">Empresa</label>
            <input
              id="extrato-busca-empresa"
              type="search"
              className="extrato-busca-sacado"
              placeholder="Digite ao menos 3 letras…"
              value={buscaEmpresa}
              onChange={(e) => {
                setBuscaEmpresa(e.target.value)
                setSugestoesEmpresaAberto(true)
              }}
              onFocus={() => setSugestoesEmpresaAberto(true)}
              disabled={empresasOrdenadas.length === 0}
              autoComplete="off"
            />
            {sugestoesEmpresaAberto && termoBuscaEmpresa.length >= 3 && (
              <div className="extrato-empresa-sugestoes" role="listbox">
                {sugestoesEmpresa.length === 0 ? (
                  <div className="extrato-empresa-sugestao vazio">Nenhuma empresa</div>
                ) : (
                  sugestoesEmpresa.map((e) => (
                    <button
                      key={e.empresa}
                      type="button"
                      className={
                        empresasFiltro.has(e.empresa)
                          ? 'extrato-empresa-sugestao ativo'
                          : 'extrato-empresa-sugestao'
                      }
                      onClick={() => {
                        escolherEmpresa(e.empresa)
                        setBuscaEmpresa('')
                        setSugestoesEmpresaAberto(false)
                      }}
                    >
                      {e.empresa}
                      <span>VP {formatarMoeda(e.vp)}</span>
                    </button>
                  ))
                )}
              </div>
            )}
            <select
              value={
                valorSelectEmpresa === '' ||
                valorSelectEmpresa === '__nenhuma__' ||
                valorSelectEmpresa === '__multi__' ||
                empresasOrdenadas.some((e) => e.empresa === valorSelectEmpresa)
                  ? valorSelectEmpresa
                  : ''
              }
              onChange={(e) => onEmpresaSelectChange(e.target.value)}
              disabled={empresasOrdenadas.length === 0}
            >
              <option value="">Todos</option>
              <option value="__nenhuma__">Nenhuma selecionada</option>
              {empresasFiltro.size > 1 && (
                <option value="__multi__">
                  {empresasFiltro.size} selecionadas
                </option>
              )}
              {empresasNaLista.length === 0 && termoBuscaEmpresa.length >= 3 && (
                <option value="__none__" disabled>
                  Nenhum na busca
                </option>
              )}
              {empresasNaLista.map((e) => (
                <option key={e.empresa} value={e.empresa}>
                  {empresasFiltro.has(e.empresa) ? '✓ ' : ''}
                  {e.empresa} — VP {formatarMoeda(e.vp)}
                </option>
              ))}
            </select>
            {empresasFiltro.size > 0 && (
              <div className="extrato-empresa-chips">
                {[...empresasFiltro].sort(compararNomes).map((nome) => (
                  <button
                    key={nome}
                    type="button"
                    className="extrato-empresa-chip"
                    title="Remover"
                    onClick={() => escolherEmpresa(nome)}
                  >
                    {nome} ×
                  </button>
                ))}
              </div>
            )}
          </div>

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
                sacadoSel === null
                  ? ''
                  : !sacadoSel ||
                      sacadosFiltrados.some((s) => s.sacado === sacadoSel)
                    ? sacadoSel
                    : ''
              }
              onChange={(e) => setSacadoSel(e.target.value)}
              disabled={sacadoSel === null && sacadosOrdenados.length === 0}
            >
              <option value="">Todos</option>
              {sacadosFiltrados.length === 0 && buscaSacado.trim() && (
                <option value="__none__" disabled>
                  Nenhum sacado na busca
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
