import { useEffect, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { CalendarioDataBase } from './CalendarioDataBase'
import type { DataBaseDetalhe } from './types'
import { API_BASE } from './types'
import './App.css'

type EmpresaPdd = {
  empresa: string
  via_cedente?: boolean
  afastamento: number
  demissao: number
  rescisao: number
  nc_outros: number
  total: number
  pct: number
  n: number
}

type OutroPdd = {
  empresa: string
  faixa: string
  pdd: number
  n: number
  faixas?: { faixa: string; pdd: number }[]
}

type Fatia = { nome: string; valor: number; peso: number }

type HistoricoPonto = {
  mes: string
  label: string
  data_iso: string
  pdd: number
}

type RespostaPdd = {
  data_base: string
  data_base_iso?: string
  totais: {
    afastamento: number
    demissao: number
    rescisao: number
    nc_outros: number
    total: number
    pct: number
    n: number
    pdd_carteira?: number
  }
  empresas: EmpresaPdd[]
  outros?: OutroPdd[]
  totais_outros?: { pdd: number; n: number; n_empresas: number }
  historico: HistoricoPonto[]
  e_consig: {
    face_total: number
    face_com_pdd: number
    face_sem_pdd: number
    pdd: number
    face_pdd_vencido?: number
    face_pdd_a_vencer?: number
    pizza_face: Fatia[]
    pizza_pdd: Fatia[]
  }
  aviso?: string | null
}

const STORAGE_DATA_BASE = 'fidc_data_base'
const CORES_PIZZA_FACE = ['#8eb6c8', '#1f4e79']
const CORES_PIZZA_PDD = ['#5b8fa8', '#9e2a2b']

function formatarMoeda(valor: number | null | undefined): string {
  return Number(valor ?? 0).toLocaleString('pt-BR', {
    style: 'currency',
    currency: 'BRL',
    maximumFractionDigits: 2,
  })
}

function formatarPct(valor: number | null | undefined): string {
  return `${Number(valor ?? 0).toLocaleString('pt-BR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}%`
}

function PizzaComLegenda({
  fatias,
  cores,
  total,
  rotuloTotal = 'Total',
}: {
  fatias: Fatia[]
  cores: string[]
  total: number
  rotuloTotal?: string
}) {
  const visiveis = fatias.filter((f) => Number(f.valor) > 0)
  return (
    <div className="chart-wrap pdd-pizza">
      <ResponsiveContainer width="100%" height={200}>
        <PieChart>
          <Pie
            data={visiveis.length ? visiveis : fatias}
            dataKey="valor"
            nameKey="nome"
            cx="50%"
            cy="50%"
            innerRadius={48}
            outerRadius={78}
            paddingAngle={2}
          >
            {(visiveis.length ? visiveis : fatias).map((_, i) => (
              <Cell key={i} fill={cores[i % cores.length]} />
            ))}
          </Pie>
          <Tooltip
            formatter={(valor, nome) => [
              formatarMoeda(Number(valor ?? 0)),
              String(nome),
            ]}
          />
        </PieChart>
      </ResponsiveContainer>
      <ul className="pdd-pizza-legenda">
        {fatias.map((f, i) => (
          <li key={f.nome} className="pdd-pizza-legenda-item">
            <span
              className="pdd-pizza-swatch"
              style={{ background: cores[i % cores.length] }}
            />
            <span className="pdd-pizza-legenda-nome">{f.nome}</span>
            <span className="pdd-pizza-legenda-valor">
              {formatarMoeda(f.valor)} · {formatarPct(f.peso)}
            </span>
          </li>
        ))}
      </ul>
      <p className="pdd-pizza-total">
        {rotuloTotal}: {formatarMoeda(total)}
      </p>
    </div>
  )
}

export default function Pdd() {
  const [dataBase, setDataBase] = useState(
    () => localStorage.getItem(STORAGE_DATA_BASE) || '',
  )
  const [datasDetalhe, setDatasDetalhe] = useState<DataBaseDetalhe[]>([])
  const [feriados, setFeriados] = useState<Map<string, string>>(new Map())
  const [mesCalendario, setMesCalendario] = useState(() => {
    const hoje = new Date()
    return { ano: hoje.getFullYear(), mes: hoje.getMonth() }
  })
  const [dados, setDados] = useState<RespostaPdd | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [carregando, setCarregando] = useState(false)

  const dataSelecionada = datasDetalhe.find((d) => d.data === dataBase)
  const mapaDatas = new Map(datasDetalhe.map((d) => [d.data_iso, d]))

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
        const res = await fetch(
          `${API_BASE}/fidc/pdd?dataBase=${encodeURIComponent(dataBase)}`,
        )
        const json = await res.json()
        if (cancelado) return
        if (!res.ok) {
          setErro(json.detail || 'Falha ao carregar PDD.')
          setDados(null)
          return
        }
        setDados(json)
      } catch (err) {
        if (!cancelado) {
          setErro(err instanceof Error ? err.message : 'Falha ao carregar PDD.')
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
  }, [dataBase])

  function selecionarData(data: string) {
    setDataBase(data)
    localStorage.setItem(STORAGE_DATA_BASE, data)
  }

  const totais = dados?.totais
  const historico = dados?.historico ?? []

  return (
    <div className="dashboard pdd-page">
      <header className="topbar">
        <div>
          <p className="eyebrow">PDD · carteira completa</p>
          <h1>PDD — {dataBase || '…'}</h1>
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
          {totais && (
            <div className="painel-totais">
              <div className="painel-total">
                <span>PDD carteira</span>
                <strong>
                  {formatarMoeda(totais.pdd_carteira ?? totais.total)}
                </strong>
              </div>
              <div className="painel-total">
                <span>Consignado</span>
                <strong>{formatarMoeda(totais.total)}</strong>
              </div>
              <div className="painel-total">
                <span>Títulos</span>
                <strong>{totais.n.toLocaleString('pt-BR')}</strong>
              </div>
            </div>
          )}
        </div>
      </header>

      {!dataBase && <p className="vazio">Carregando datas disponíveis…</p>}
      {carregando && <p className="vazio">Carregando PDD…</p>}
      {erro && <div className="banner-status banner-data">{erro}</div>}
      {dados?.aviso && <p className="aviso-inline">{dados.aviso}</p>}

      {!carregando && dados && (
        <div className="pdd-layout">
          <section className="painel pdd-tabela-painel">
            <div className="painel-cabecalho">
              <div>
                <h2>PDD consignado privado</h2>
              </div>
            </div>
            <div className="pdd-tabela-scroll">
              <table className="tabela-pdd">
                <thead>
                  <tr>
                    <th>Empresas</th>
                    <th>Afastamento</th>
                    <th>Demissão</th>
                    <th>NC/Outros</th>
                    <th>Rescisão</th>
                    <th>Total</th>
                    <th>%</th>
                  </tr>
                </thead>
                <tbody>
                  {dados.empresas.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="vazio">
                        Sem PDD de consignado nesta data.
                      </td>
                    </tr>
                  ) : (
                    dados.empresas.map((emp) => (
                      <tr
                        key={`${emp.via_cedente ? 'ced' : 'emp'}|${emp.empresa}`}
                        className={emp.via_cedente ? 'via-cedente' : undefined}
                      >
                        <td>
                          {emp.empresa}
                          {emp.via_cedente ? (
                            <span className="pdd-tag-cedente">nm_cedente</span>
                          ) : null}
                        </td>
                        <td>{formatarMoeda(emp.afastamento)}</td>
                        <td>{formatarMoeda(emp.demissao)}</td>
                        <td>{formatarMoeda(emp.nc_outros)}</td>
                        <td>{formatarMoeda(emp.rescisao)}</td>
                        <td>{formatarMoeda(emp.total)}</td>
                        <td>{formatarPct(emp.pct)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
                {totais && dados.empresas.length > 0 && (
                  <tfoot>
                    <tr>
                      <th>Total</th>
                      <th>{formatarMoeda(totais.afastamento)}</th>
                      <th>{formatarMoeda(totais.demissao)}</th>
                      <th>{formatarMoeda(totais.nc_outros)}</th>
                      <th>{formatarMoeda(totais.rescisao)}</th>
                      <th>{formatarMoeda(totais.total)}</th>
                      <th>{formatarPct(100)}</th>
                    </tr>
                  </tfoot>
                )}
              </table>
            </div>
          </section>

          <section className="painel pdd-outros-painel">
            <div className="painel-cabecalho">
              <div>
                <h2>Demais títulos</h2>
              </div>
              {dados.totais_outros && (
                <div className="painel-total">
                  <span>PDD</span>
                  <strong>{formatarMoeda(dados.totais_outros.pdd)}</strong>
                </div>
              )}
            </div>
            <div className="pdd-tabela-scroll pdd-outros-scroll">
              <table className="tabela-pdd tabela-pdd-outros">
                <thead>
                  <tr>
                    <th>Empresa</th>
                    <th>Faixa</th>
                    <th>PDD</th>
                  </tr>
                </thead>
                <tbody>
                  {(dados.outros ?? []).length === 0 ? (
                    <tr>
                      <td colSpan={3} className="vazio">
                        Sem PDD fora do consignado nesta data.
                      </td>
                    </tr>
                  ) : (
                    (dados.outros ?? []).map((emp) => (
                      <tr key={emp.empresa}>
                        <td>
                          {emp.empresa}
                          {(emp.faixas?.length ?? 0) > 1 ? (
                            <span className="pdd-faixas-detalhe">
                              {emp.faixas!
                                .map((f) => `${f.faixa} ${formatarMoeda(f.pdd)}`)
                                .join(' · ')}
                            </span>
                          ) : null}
                        </td>
                        <td>
                          <span className={`pdd-faixa faixa-${emp.faixa}`}>
                            {emp.faixa}
                          </span>
                        </td>
                        <td>{formatarMoeda(emp.pdd)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
                {dados.totais_outros && (dados.outros ?? []).length > 0 && (
                  <tfoot>
                    <tr>
                      <th>Total</th>
                      <th />
                      <th>{formatarMoeda(dados.totais_outros.pdd)}</th>
                    </tr>
                  </tfoot>
                )}
              </table>
            </div>
          </section>

          <div className="pdd-pizzas">
            <section className="painel">
              <div className="painel-cabecalho">
                <h2>Valor face e-consig</h2>
                <p className="subtitulo">BMP · Via Capital</p>
              </div>
              <PizzaComLegenda
                fatias={dados.e_consig.pizza_face}
                cores={CORES_PIZZA_FACE}
                total={dados.e_consig.face_total}
              />
            </section>

            <section className="painel">
              <div className="painel-cabecalho">
                <h2>PDD e-consig</h2>
                <p className="subtitulo">BMP · Via Capital</p>
              </div>
              <PizzaComLegenda
                fatias={dados.e_consig.pizza_pdd}
                cores={CORES_PIZZA_PDD}
                total={dados.e_consig.face_com_pdd}
                rotuloTotal="Total face em PDD"
              />
            </section>
          </div>

          <section className="painel pdd-historico-painel">
            <div className="painel-cabecalho">
              <div>
                <h2>PDD histórico</h2>
              </div>
            </div>
            {historico.length === 0 ? (
              <p className="vazio">Sem série histórica do motor.</p>
            ) : (
              <div className="chart-wrap">
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={historico}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="label" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
                    <YAxis
                      tickFormatter={(v) =>
                        `${(Number(v) / 1_000_000).toLocaleString('pt-BR', {
                          maximumFractionDigits: 1,
                        })}M`
                      }
                      width={48}
                    />
                    <Tooltip
                      formatter={(valor) => [formatarMoeda(Number(valor ?? 0)), 'PDD']}
                      labelFormatter={(label) => String(label)}
                    />
                    <Bar dataKey="pdd" name="PDD" fill="#1f4e79" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  )
}
