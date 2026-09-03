import { useEffect, useMemo, useState } from 'react'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { CalendarioDataBase } from './CalendarioDataBase'
import type { DataBaseDetalhe } from './types'
import { API_BASE } from './types'
import './App.css'

type TotalCaixaLinha = {
  mes: string
  aquisicao: number
  pago: number
  tir_am: number | null
  pct_cdi: number | null
  tir_esp_am?: number | null
  pct_cdi_esp?: number | null
  face_a_vencer?: number
  vnp_pct?: number
  residual_esperado?: number
}

type MatrizCaixa = {
  linhas: string[]
  colunas: string[]
  labels_linha: string[]
  labels_coluna: string[]
  celulas: { valor: number }[][]
  totais_linha: TotalCaixaLinha[]
  totais_coluna: { mes: string; valor: number }[]
  total: { aquisicao: number; pago: number }
  max_celula: number
}

type RespostaCaixa = {
  data_base: string
  data_base_iso?: string
  matriz_caixa?: MatrizCaixa
  aviso?: string | null
}

type PontoProjecao = {
  mes: string
  mes_ano: string
  entradas_ativos: number
  entradas_brutas?: number
  saidas_passivo: number
  liquido: number
  caixa: number
  tipo?: 'real' | 'projetado' | string
  ponto?: string
  data?: string | null
}

type RespostaProjecao = {
  data_ref?: string
  ultima_liquidez?: string | null
  caixa_inicial?: number
  caixa_final?: number
  serie?: PontoProjecao[]
  totais?: {
    entradas_ativos: number
    entradas_brutas?: number
    saidas_passivo: number
    liquido: number
  }
}

const STORAGE_DATA_BASE = 'fidc_data_base'
const STORAGE_ANO = 'fidc_fluxo_ano'
const ANO_TODOS = 'todos'

function formatarMoeda(valor: number | null | undefined): string {
  return Number(valor ?? 0).toLocaleString('pt-BR', {
    style: 'currency',
    currency: 'BRL',
    maximumFractionDigits: 2,
  })
}

function formatarMoedaCurta(valor: number | null | undefined): string {
  const n = Number(valor ?? 0)
  if (n === 0) return ''
  const abs = Math.abs(n)
  if (abs >= 1_000_000) {
    return `${(n / 1_000_000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })}M`
  }
  if (abs >= 1_000) {
    return `${(n / 1_000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })}k`
  }
  return n.toLocaleString('pt-BR', { maximumFractionDigits: 0 })
}

function formatarPct(valor: number | null | undefined): string {
  return `${Number(valor ?? 0).toLocaleString('pt-BR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}%`
}

function corCelula(valor: number, max: number): { bg: string; fg: string } {
  if (!valor || max <= 0) {
    return { bg: 'transparent', fg: 'var(--muted)' }
  }
  const t = Math.min(1, Math.max(0, valor / max))
  const r = Math.round(253 + (158 - 253) * t)
  const g = Math.round(232 + (42 - 232) * t)
  const b = Math.round(232 + (43 - 232) * t)
  return {
    bg: `rgb(${r}, ${g}, ${b})`,
    fg: t > 0.55 ? '#fff' : '#5a1a1b',
  }
}

export default function FluxoCaixa() {
  const [dataBase, setDataBase] = useState(
    () => localStorage.getItem(STORAGE_DATA_BASE) || '',
  )
  const [datasDetalhe, setDatasDetalhe] = useState<DataBaseDetalhe[]>([])
  const [feriados, setFeriados] = useState<Map<string, string>>(new Map())
  const [mesCalendario, setMesCalendario] = useState(() => {
    const hoje = new Date()
    return { ano: hoje.getFullYear(), mes: hoje.getMonth() }
  })
  const [dados, setDados] = useState<RespostaCaixa | null>(null)
  const [projecao, setProjecao] = useState<RespostaProjecao | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [carregando, setCarregando] = useState(false)
  const [ano, setAno] = useState(() => localStorage.getItem(STORAGE_ANO) || '')

  const dataSelecionada = datasDetalhe.find((d) => d.data === dataBase)
  const mapaDatas = new Map(datasDetalhe.map((d) => [d.data_iso, d]))
  const matriz = dados?.matriz_caixa

  const serieProjecao = useMemo(() => {
    return (projecao?.serie ?? []).map((p) => ({
      mes: String(p.mes || ''),
      mes_ano: String(p.mes_ano || p.mes || ''),
      data: String(p.data || ''),
      entradas_ativos: Number(p.entradas_ativos ?? 0),
      saidas_passivo: Number(p.saidas_passivo ?? 0),
      liquido: Number(p.liquido ?? 0),
      caixa: Number(p.caixa ?? 0),
      tipo: p.tipo === 'projetado' ? 'projetado' : 'real',
    }))
  }, [projecao])

  const caixaInicial = Number(projecao?.caixa_inicial ?? serieProjecao[0]?.caixa ?? 0)
  const caixaFinal = Number(
    projecao?.caixa_final ?? serieProjecao.at(-1)?.caixa ?? 0,
  )

  useEffect(() => {
    let cancelado = false
    async function carregarDatas() {
      try {
        const res = await fetch(`${API_BASE}/fidc/datas`)
        if (!res.ok) return
        const json = await res.json()
        if (cancelado) return
        const mapaFer = new Map<string, string>()
        for (const f of json.feriados ?? []) {
          if (f?.data && f?.nome) mapaFer.set(String(f.data), String(f.nome))
        }
        setFeriados(mapaFer)
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
        const disponiveis = detalhe.filter((d) => d.status === 'ok' || d.conciliada)
        const ultima = (disponiveis.length ? disponiveis : detalhe).at(-1) ?? null
        setDataBase((atual) => {
          if (atual && detalhe.some((d) => d.data === atual)) return atual
          const salvo = localStorage.getItem(STORAGE_DATA_BASE) || ''
          if (salvo && detalhe.some((d) => d.data === salvo)) return salvo
          const proxima = ultima?.data ?? ''
          if (proxima) localStorage.setItem(STORAGE_DATA_BASE, proxima)
          return proxima
        })
        if (ultima?.data_iso) {
          const [y, m] = ultima.data_iso.split('-').map(Number)
          setMesCalendario({ ano: y, mes: m - 1 })
        }
      } catch {
        /* ignore */
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
    async function carregar() {
      setCarregando(true)
      setErro(null)
      try {
        const [resMatriz, resProj] = await Promise.all([
          fetch(
            `${API_BASE}/fidc/fluxo-caixa?dataBase=${encodeURIComponent(dataBase)}`,
          ),
          fetch(
            `${API_BASE}/fidc/passivo/fluxo-caixa?dataBase=${encodeURIComponent(dataBase)}`,
          ),
        ])
        const json = await resMatriz.json()
        const jsonProj = await resProj.json().catch(() => null)
        if (cancelado) return
        if (!resMatriz.ok) {
          setErro(json.detail || 'Falha ao carregar fluxo de caixa.')
          setDados(null)
        } else {
          setDados(json)
        }
        if (resProj.ok && jsonProj) {
          setProjecao(jsonProj)
        } else {
          setProjecao(null)
        }
      } catch (err) {
        if (!cancelado) {
          setErro(
            err instanceof Error ? err.message : 'Falha ao carregar fluxo de caixa.',
          )
          setDados(null)
          setProjecao(null)
        }
      } finally {
        if (!cancelado) setCarregando(false)
      }
    }
    void carregar()
    return () => {
      cancelado = true
    }
  }, [dataBase])

  function selecionarData(data: string) {
    setDataBase(data)
    localStorage.setItem(STORAGE_DATA_BASE, data)
  }

  const anos = useMemo(() => {
    if (!matriz) return []
    const set = new Set<string>()
    for (const m of matriz.linhas) set.add(m.slice(0, 4))
    return [...set].sort()
  }, [matriz])

  useEffect(() => {
    if (anos.length === 0) return
    if (ano === ANO_TODOS) return
    if (ano && anos.includes(ano)) return
    const doBase = dados?.data_base_iso?.slice(0, 4)
    const proximo =
      (doBase && anos.includes(doBase) ? doBase : anos.at(-1)) || ANO_TODOS
    setAno(proximo)
    localStorage.setItem(STORAGE_ANO, proximo)
  }, [anos, ano, dados?.data_base_iso])

  const visao = useMemo(() => {
    if (!matriz || !ano) return null
    const idxLinhas = matriz.linhas
      .map((m, i) => (ano === ANO_TODOS || m.startsWith(ano) ? i : -1))
      .filter((i) => i >= 0)
    const inicioCol = ano === ANO_TODOS ? (matriz.colunas[0] ?? '') : `${ano}-01`
    const idxColunas = matriz.colunas
      .map((m, i) => (ano === ANO_TODOS || m >= inicioCol ? i : -1))
      .filter((i) => i >= 0)

    let max = 0
    let aquisicao = 0
    let pago = 0
    const totaisLinha = idxLinhas.map((i) => {
      const tot = matriz.totais_linha[i]
      aquisicao += tot?.aquisicao ?? 0
      let pagoLinha = 0
      for (const j of idxColunas) {
        const v = matriz.celulas[i]?.[j]?.valor ?? 0
        pagoLinha += v
        if (v > max) max = v
      }
      pago += pagoLinha
      return {
        aquisicao: tot?.aquisicao ?? 0,
        pago: pagoLinha,
        tir_am: tot?.tir_am ?? null,
        pct_cdi: tot?.pct_cdi ?? null,
        tir_esp_am: tot?.tir_esp_am ?? null,
        pct_cdi_esp: tot?.pct_cdi_esp ?? null,
        face_a_vencer: tot?.face_a_vencer ?? 0,
        vnp_pct: tot?.vnp_pct ?? 0,
        residual_esperado: tot?.residual_esperado ?? 0,
      }
    })
    const totaisColuna = idxColunas.map((j) => {
      let valor = 0
      for (const i of idxLinhas) {
        valor += matriz.celulas[i]?.[j]?.valor ?? 0
      }
      return { valor }
    })

    return {
      idxLinhas,
      idxColunas,
      totaisLinha,
      totaisColuna,
      max,
      aquisicao,
      pago,
    }
  }, [matriz, ano])

  function selecionarAno(proximo: string) {
    setAno(proximo)
    localStorage.setItem(STORAGE_ANO, proximo)
  }

  return (
    <div className="dashboard inad-page">
      <header className="topbar">
        <div>
          <p className="eyebrow">Fluxo de caixa · consignado privado</p>
          <h1>Fluxo de caixa — {dataBase || '…'}</h1>
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

      {erro && <p className="erro">{erro}</p>}
      {dados?.aviso && <p className="aviso">{dados.aviso}</p>}
      {carregando && <p className="vazio">Carregando matriz…</p>}

      {!carregando && serieProjecao.length > 0 && (
        <section className="painel">
          <div className="painel-cabecalho">
            <div>
              <h2>Caixa projetado</h2>
            </div>
            <div className="painel-totais">
              <div className="painel-total">
                <span>Caixa + aplicações</span>
                <strong>{formatarMoeda(caixaInicial)}</strong>
              </div>
              <div className="painel-total">
                <span>Caixa final</span>
                <strong>{formatarMoeda(caixaFinal)}</strong>
              </div>
              <div className="painel-total">
                <span>Entradas (após PD)</span>
                <strong>{formatarMoeda(projecao?.totais?.entradas_ativos)}</strong>
              </div>
              <div className="painel-total">
                <span>Amortizações</span>
                <strong>{formatarMoeda(projecao?.totais?.saidas_passivo)}</strong>
              </div>
            </div>
          </div>
          <div className="chart-wrap chart-fluxo">
            <ComposedChart
              key={`proj-${serieProjecao.length}-${serieProjecao[0]?.mes ?? ''}-${caixaFinal}`}
              responsive
              width="100%"
              height={360}
              data={serieProjecao}
              margin={{ top: 12, right: 20, left: 8, bottom: 8 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#d8e0ea" />
              <XAxis
                dataKey="mes_ano"
                tick={{ fill: '#5a6b7d', fontSize: 10 }}
                interval="preserveStartEnd"
                minTickGap={36}
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
                  const row = payload?.[0]?.payload as
                    | { data?: string; mes_ano?: string; tipo?: string }
                    | undefined
                  const dia = row?.data
                    ? row.data.split('-').reverse().join('/')
                    : String(row?.mes_ano ?? '')
                  const sufixo = row?.tipo === 'projetado' ? ' · projetado' : ' · real'
                  return `${dia}${sufixo}`
                }}
                contentStyle={{
                  background: '#0f2740',
                  border: 'none',
                  borderRadius: 8,
                  color: '#fff',
                }}
              />
              <Legend />
              <Area
                type="monotone"
                dataKey="caixa"
                name="Caixa acumulado"
                stroke="#1f6f8b"
                fill="#1f6f8b"
                fillOpacity={0.18}
                strokeWidth={2.5}
                dot={false}
                activeDot={{ r: 4 }}
                isAnimationActive={false}
              />
            </ComposedChart>
          </div>
        </section>
      )}

      {!carregando && anos.length > 0 && (
        <div className="inad-filtro-ano">
          <span>Ano de originação</span>
          <div className="inad-anos" role="group" aria-label="Ano de originação">
            <button
              type="button"
              className={ano === ANO_TODOS ? 'ativo' : ''}
              onClick={() => selecionarAno(ANO_TODOS)}
            >
              Todos
            </button>
            {anos.map((a) => (
              <button
                key={a}
                type="button"
                className={ano === a ? 'ativo' : ''}
                onClick={() => selecionarAno(a)}
              >
                {a}
              </button>
            ))}
          </div>
        </div>
      )}

      {!carregando && matriz && matriz.linhas.length === 0 && (
        <p className="vazio">Sem títulos de consignado privado nesta data.</p>
      )}

      {!carregando && visao && visao.idxLinhas.length > 0 && matriz && (
        <section className="painel">
          <div className="painel-cabecalho">
            <div>
              <h2>Caixa · aquisição × liquidações</h2>
            </div>
            <div className="inad-escala" aria-hidden>
              <span>menor</span>
              <span className="inad-escala-barra" />
              <span>maior</span>
            </div>
          </div>
          <div className="inad-matriz-scroll">
            <table className="inad-matriz inad-matriz-caixa">
              <thead>
                <tr>
                  <th className="inad-canto">Cessão</th>
                  <th className="inad-total-col">Aquisição</th>
                  {visao.idxColunas.map((j) => (
                    <th key={matriz.colunas[j]}>{matriz.labels_coluna[j]}</th>
                  ))}
                  <th className="inad-total-col">Total pago</th>
                  <th className="inad-total-col">TIR a.m.</th>
                  <th className="inad-total-col">% CDI</th>
                  <th className="inad-total-col">TIR esp.</th>
                  <th className="inad-total-col">% CDI esp.</th>
                </tr>
              </thead>
              <tbody>
                {visao.idxLinhas.map((i, ri) => {
                  const totL = visao.totaisLinha[ri]
                  return (
                    <tr key={matriz.linhas[i]}>
                      <th>{matriz.labels_linha[i]}</th>
                      <td className="inad-total-cel">
                        {formatarMoedaCurta(totL.aquisicao)}
                      </td>
                      {visao.idxColunas.map((j) => {
                        const v = matriz.celulas[i]?.[j]?.valor ?? 0
                        const { bg, fg } = corCelula(v, visao.max)
                        return (
                          <td
                            key={matriz.colunas[j]}
                            style={{ background: bg, color: fg }}
                            title={`${matriz.labels_linha[i]} × ${matriz.labels_coluna[j]}: ${formatarMoeda(v)}`}
                          >
                            {formatarMoedaCurta(v)}
                          </td>
                        )
                      })}
                      <td className="inad-total-cel">
                        {formatarMoedaCurta(totL.pago)}
                      </td>
                      <td className="inad-total-cel">
                        {totL.tir_am == null ? '—' : formatarPct(totL.tir_am)}
                      </td>
                      <td className="inad-total-cel">
                        {totL.pct_cdi == null ? '—' : formatarPct(totL.pct_cdi)}
                      </td>
                      <td
                        className="inad-total-cel"
                        title={`Face a vencer ${formatarMoeda(totL.face_a_vencer)} · VNP ${formatarPct(totL.vnp_pct)} · esperado ${formatarMoeda(totL.residual_esperado)}`}
                      >
                        {totL.tir_esp_am == null ? '—' : formatarPct(totL.tir_esp_am)}
                      </td>
                      <td className="inad-total-cel">
                        {totL.pct_cdi_esp == null ? '—' : formatarPct(totL.pct_cdi_esp)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
              <tfoot>
                <tr>
                  <th>Total</th>
                  <td className="inad-total-cel inad-total-geral">
                    {formatarMoedaCurta(visao.aquisicao)}
                  </td>
                  {visao.totaisColuna.map((tot, k) => (
                    <td
                      key={matriz.colunas[visao.idxColunas[k]]}
                      className="inad-total-cel"
                    >
                      {formatarMoedaCurta(tot.valor)}
                    </td>
                  ))}
                  <td className="inad-total-cel inad-total-geral">
                    {formatarMoedaCurta(visao.pago)}
                  </td>
                  <td className="inad-total-cel inad-total-geral">—</td>
                  <td className="inad-total-cel inad-total-geral">—</td>
                  <td className="inad-total-cel inad-total-geral">—</td>
                  <td className="inad-total-cel inad-total-geral">—</td>
                </tr>
              </tfoot>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}
