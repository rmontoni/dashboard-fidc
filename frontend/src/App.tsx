import { Fragment, useEffect, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type {
  ConcentracaoItem,
  FaixaAging,
  FatiaDistribuicao,
  Kpis,
  PontoEvolucao,
  PontoFluxoCaixa,
  RespostaRisco,
} from './types'
import { API_BASE } from './types'
import './App.css'

const KPI_VAZIO: Kpis = {
  operacoes_ativas: 0,
  volume_cedido: 0,
  valor_presente: 0,
  prazo_medio: 0,
  hhi: 0,
  inadimplencia: 0,
  receita_projetada: 0,
  taxa_media: 0,
}

const CORES_PIZZA = [
  '#1f6f8b',
  '#99c24d',
  '#e09f3e',
  '#9e2a2b',
  '#335c67',
  '#540b0e',
  '#84a98c',
  '#7b8c9c',
]

function formatarMoeda(valor: number | undefined | null): string {
  return Number(valor ?? 0).toLocaleString('pt-BR', {
    style: 'currency',
    currency: 'BRL',
    maximumFractionDigits: 0,
  })
}

function num(valor: number | undefined | null): number {
  return Number(valor ?? 0)
}

function App() {
  const [datasDisponiveis, setDatasDisponiveis] = useState<string[]>([])
  const [dataBaseFiltro, setDataBaseFiltro] = useState('')
  const [aCarregar, setACarregar] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const [indicadores, setIndicadores] = useState<Kpis>(KPI_VAZIO)
  const [topCedentes, setTopCedentes] = useState<ConcentracaoItem[]>([])
  const [topSacados, setTopSacados] = useState<ConcentracaoItem[]>([])
  const [distCedentes, setDistCedentes] = useState<FatiaDistribuicao[]>([])
  const [distSacados, setDistSacados] = useState<FatiaDistribuicao[]>([])
  const [graficoFluxo, setGraficoFluxo] = useState<PontoFluxoCaixa[]>([])
  const [graficoEvolucao, setGraficoEvolucao] = useState<PontoEvolucao[]>([])
  const [agingInad, setAgingInad] = useState<FaixaAging[]>([])
  const [topSacadosInad, setTopSacadosInad] = useState<ConcentracaoItem[]>([])
  const [topCedentesInad, setTopCedentesInad] = useState<ConcentracaoItem[]>([])
  const [faixaAgingAberta, setFaixaAgingAberta] = useState<string | null>(null)

  async function carregarDatas() {
    setErro(null)
    try {
      const res = await fetch(`${API_BASE}/fidc/datas`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const dados = await res.json()
      const datas: string[] = dados.datas ?? []
      setDatasDisponiveis(datas)
      if (datas.length > 0) {
        setDataBaseFiltro((atual) => atual || datas[datas.length - 1])
      }
    } catch (error) {
      console.error('Erro ao carregar datas:', error)
      setErro('Não foi possível conectar à API. Verifique se o backend está rodando.')
    }
  }

  useEffect(() => {
    let cancelado = false
    let tentativas = 0

    async function tentar() {
      try {
        const res = await fetch(`${API_BASE}/fidc/datas`)
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const dados = await res.json()
        if (cancelado) return
        const datas: string[] = dados.datas ?? []
        setDatasDisponiveis(datas)
        if (datas.length > 0) {
          setDataBaseFiltro(datas[datas.length - 1])
        }
        setErro(null)
      } catch (error) {
        console.error('Erro ao carregar datas:', error)
        if (cancelado) return
        tentativas += 1
        if (tentativas < 5) {
          setTimeout(tentar, 1000 * tentativas)
          return
        }
        setErro('Não foi possível conectar à API. Verifique se o backend está rodando.')
      }
    }

    tentar()
    return () => {
      cancelado = true
    }
  }, [])

  useEffect(() => {
    async function buscarDadosDaApiPython() {
      if (!dataBaseFiltro) return
      setACarregar(true)
      setErro(null)

      try {
        const res = await fetch(
          `${API_BASE}/fidc/risco?dataBase=${encodeURIComponent(dataBaseFiltro)}`,
        )
        const dados: RespostaRisco = await res.json()

        if (dados.erro) {
          setErro(dados.erro)
          setIndicadores(KPI_VAZIO)
          setTopCedentes([])
          setTopSacados([])
          setDistCedentes([])
          setDistSacados([])
          setGraficoFluxo([])
          setGraficoEvolucao([])
          setAgingInad([])
          setTopSacadosInad([])
          setTopCedentesInad([])
          setFaixaAgingAberta(null)
          return
        }

        setIndicadores({ ...KPI_VAZIO, ...(dados.kpis ?? {}) })
        setTopCedentes(dados.top_cedentes ?? [])
        setTopSacados(dados.top_sacados ?? [])
        setDistCedentes(dados.distribuicao_cedentes ?? [])
        setDistSacados(dados.distribuicao_sacados ?? [])
        setGraficoFluxo(dados.grafico_fluxo_caixa ?? [])
        setGraficoEvolucao(dados.grafico_evolucao ?? [])
        setAgingInad(dados.aging_inadimplencia ?? [])
        setTopSacadosInad(dados.top_sacados_inadimplentes ?? [])
        setTopCedentesInad(dados.top_cedentes_inadimplentes ?? [])
        setFaixaAgingAberta(null)
      } catch (error) {
        console.error('Erro na API Python:', error)
        setErro('Falha ao buscar dados de risco na API.')
      } finally {
        setACarregar(false)
      }
    }

    buscarDadosDaApiPython()
  }, [dataBaseFiltro])

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <p className="eyebrow">Monitoramento de carteira</p>
          <h1>Dashboard FIDC</h1>
        </div>
        <label className="filtro">
          <span>Data base</span>
          <select
            value={dataBaseFiltro}
            onChange={(e) => setDataBaseFiltro(e.target.value)}
            disabled={datasDisponiveis.length === 0}
          >
            {datasDisponiveis.map((data) => (
              <option key={data} value={data}>
                {data}
              </option>
            ))}
          </select>
        </label>
      </header>

      {erro && (
        <div className="banner-erro">
          <span>{erro}</span>
          <button type="button" className="btn-retry" onClick={carregarDatas}>
            Tentar novamente
          </button>
        </div>
      )}
      {aCarregar && <div className="banner-status">Carregando indicadores…</div>}

      <section className="kpis kpis-carteira">
        <article className="kpi">
          <span>Operações ativas</span>
          <strong>{num(indicadores.operacoes_ativas).toLocaleString('pt-BR')}</strong>
        </article>
        <article className="kpi">
          <span>Volume cedido</span>
          <strong>{formatarMoeda(indicadores.volume_cedido)}</strong>
        </article>
        <article className="kpi">
          <span>Valor presente</span>
          <strong>{formatarMoeda(indicadores.valor_presente)}</strong>
        </article>
        <article className="kpi">
          <span>Prazo médio</span>
          <strong>{num(indicadores.prazo_medio).toFixed(1)} dias</strong>
        </article>
      </section>

      <section className="kpis kpis-risco">
        <article className="kpi">
          <span>HHI (sacados)</span>
          <strong>{num(indicadores.hhi).toLocaleString('pt-BR')}</strong>
        </article>
        <article className="kpi">
          <span>Inadimplência</span>
          <strong>{num(indicadores.inadimplencia).toFixed(2)}%</strong>
        </article>
        <article className="kpi">
          <span>Receita total projetada</span>
          <strong>{formatarMoeda(indicadores.receita_projetada)}</strong>
        </article>
        <article className="kpi">
          <span>Taxa média</span>
          <strong>{num(indicadores.taxa_media).toFixed(2)}%</strong>
        </article>
      </section>

      <section className="grades">
        <GraficoPizza
          titulo="Distribuição por cedente"
          subtitulo="Participação no valor presente (top 7 + outros)"
          dados={distCedentes}
        />
        <GraficoPizza
          titulo="Distribuição por sacado"
          subtitulo="Participação no valor presente (top 7 + outros)"
          dados={distSacados}
        />
      </section>

      <section className="painel">
        <div className="painel-cabecalho">
          <div>
            <h2>Aging de inadimplência</h2>
            <p className="subtitulo">
              Títulos com status VENCIDO por faixa de atraso (dias desde o vencimento até a data
              base)
            </p>
          </div>
          <div className="painel-total">
            <span>VNP Total</span>
            <strong>
              {formatarMoeda(agingInad.reduce((acc, f) => acc + num(f.valor), 0))}
            </strong>
          </div>
        </div>
        {agingInad.length === 0 ? (
          <p className="vazio">Carregue os dados ou selecione outra data base.</p>
        ) : (
          <table className="tabela-aging">
            <thead>
              <tr>
                <th></th>
                <th>Faixa</th>
                <th>Valor</th>
                <th>Qtd</th>
                <th>Peso</th>
              </tr>
            </thead>
            <tbody>
              {agingInad.map((faixa) => {
                const aberta = faixaAgingAberta === faixa.faixa
                const titulos = faixa.titulos ?? []
                return (
                  <Fragment key={faixa.faixa}>
                    <tr
                      className={`linha-aging${aberta ? ' aberta' : ''}${faixa.qtd === 0 ? ' desabilitada' : ''}`}
                      onClick={() => {
                        if (faixa.qtd === 0) return
                        setFaixaAgingAberta(aberta ? null : faixa.faixa)
                      }}
                    >
                      <td className="col-expandir">{aberta ? '▼' : '▶'}</td>
                      <td>{faixa.faixa}</td>
                      <td>{formatarMoeda(faixa.valor)}</td>
                      <td>{faixa.qtd}</td>
                      <td>{num(faixa.peso).toFixed(1)}%</td>
                    </tr>
                    {aberta && (
                      <tr className="linha-detalhe-aging">
                        <td colSpan={5}>
                          {titulos.length === 0 ? (
                            <p className="vazio">Nenhum título nesta faixa.</p>
                          ) : (
                            <table className="tabela-titulos-aging">
                              <thead>
                                <tr>
                                  <th>Documento</th>
                                  <th>Cedente</th>
                                  <th>Sacado</th>
                                  <th>Vencimento</th>
                                  <th>Dias atraso</th>
                                  <th>Status</th>
                                  <th>Valor face</th>
                                </tr>
                              </thead>
                              <tbody>
                                {titulos.map((titulo) => (
                                  <tr
                                    key={`${titulo.documento}-${titulo.sacado}-${titulo.data_vencimento}-${titulo.valor_face}`}
                                  >
                                    <td>{titulo.documento}</td>
                                    <td>{titulo.cedente}</td>
                                    <td>{titulo.sacado}</td>
                                    <td>{titulo.data_vencimento}</td>
                                    <td>{titulo.dias_atraso}</td>
                                    <td>{titulo.status}</td>
                                    <td>{formatarMoeda(titulo.valor_face)}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        )}
      </section>

      <section className="grades">
        <ConcentracaoTabela
          titulo="Top 5 Cedentes inadimplentes"
          itens={topCedentesInad}
          colunaValor="Valor em atraso"
        />
        <ConcentracaoTabela
          titulo="Top 5 Sacados inadimplentes"
          itens={topSacadosInad}
          colunaValor="Valor em atraso"
        />
      </section>

      <section className="painel">
        <div className="painel-cabecalho">
          <div>
            <h2>Fluxo de caixa projetado</h2>
            <p className="subtitulo">
              Entradas esperadas por mês de vencimento, ajustadas pela PD de cada sacado
            </p>
          </div>
          <div className="painel-total">
            <span>Total (após PD)</span>
            <strong>
              {formatarMoeda(graficoFluxo.reduce((acc, p) => acc + num(p.fluxo_caixa), 0))}
            </strong>
          </div>
        </div>
        <div className="chart-wrap chart-fluxo">
          {graficoFluxo.length === 0 ? (
            <p className="vazio">Sem dados de fluxo de caixa para a data base selecionada.</p>
          ) : (
            <BarChart
              responsive
              width="100%"
              height={340}
              data={graficoFluxo}
              margin={{ top: 12, right: 20, left: 8, bottom: 8 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#d8e0ea" />
              <XAxis dataKey="mes_ano" tick={{ fill: '#5a6b7d', fontSize: 12 }} />
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
                formatter={(value) => formatarMoeda(Number(value ?? 0))}
                contentStyle={{
                  background: '#0f2740',
                  border: 'none',
                  borderRadius: 8,
                  color: '#fff',
                }}
              />
              <Legend />
              <Bar
                dataKey="fluxo_caixa"
                name="Fluxo de caixa projetado"
                fill="#1f6f8b"
                radius={[4, 4, 0, 0]}
                maxBarSize={48}
              />
            </BarChart>
          )}
        </div>
      </section>

      <section className="painel">
        <h2>Evolução da originação</h2>
        <p className="subtitulo">Volume originado e receita por mês de emissão</p>
        <div className="chart-wrap">
          <ResponsiveContainer width="100%" height={320}>
            <BarChart data={graficoEvolucao}>
              <CartesianGrid strokeDasharray="3 3" stroke="#d8e0ea" />
              <XAxis dataKey="mes_ano_emissao" tick={{ fill: '#5a6b7d', fontSize: 12 }} />
              <YAxis
                tick={{ fill: '#5a6b7d', fontSize: 12 }}
                tickFormatter={(v) =>
                  Number(v).toLocaleString('pt-BR', {
                    notation: 'compact',
                    maximumFractionDigits: 1,
                  })
                }
              />
              <Tooltip
                formatter={(value) => formatarMoeda(Number(value ?? 0))}
                contentStyle={{
                  background: '#0f2740',
                  border: 'none',
                  borderRadius: 8,
                  color: '#fff',
                }}
              />
              <Legend />
              <Bar dataKey="volume_originado" name="Volume originado" fill="#1f6f8b" radius={[4, 4, 0, 0]} />
              <Bar dataKey="receita_projetada" name="Receita" fill="#99c24d" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="grades">
        <ConcentracaoTabela titulo="Top 10 Cedentes" itens={topCedentes} />
        <ConcentracaoTabela titulo="Top 10 Sacados" itens={topSacados} mostrarPd />
      </section>
    </div>
  )
}

function GraficoPizza({
  titulo,
  subtitulo,
  dados,
}: {
  titulo: string
  subtitulo: string
  dados: FatiaDistribuicao[]
}) {
  return (
    <div className="painel">
      <h2>{titulo}</h2>
      <p className="subtitulo">{subtitulo}</p>
      <div className="chart-wrap chart-pizza">
        {dados.length === 0 ? (
          <p className="vazio">Sem dados</p>
        ) : (
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={dados}
                dataKey="valor"
                nameKey="nome"
                cx="42%"
                cy="50%"
                innerRadius={52}
                outerRadius={96}
                paddingAngle={2}
              >
                {dados.map((fatia, index) => (
                  <Cell
                    key={fatia.nome}
                    fill={CORES_PIZZA[index % CORES_PIZZA.length]}
                    stroke="#fff"
                    strokeWidth={1}
                  />
                ))}
              </Pie>
              <Tooltip
                formatter={(value, _name, item) => {
                  const peso = Number(item?.payload?.peso ?? 0)
                  return [`${formatarMoeda(Number(value ?? 0))} (${peso.toFixed(1)}%)`, 'Valor presente']
                }}
                contentStyle={{
                  background: '#0f2740',
                  border: 'none',
                  borderRadius: 8,
                  color: '#fff',
                }}
              />
              <Legend
                layout="vertical"
                align="right"
                verticalAlign="middle"
                wrapperStyle={{ fontSize: 12, maxWidth: 160 }}
                formatter={(value) => {
                  const fatia = dados.find((d) => d.nome === value)
                  return fatia ? `${value} (${fatia.peso.toFixed(1)}%)` : String(value)
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}

function ConcentracaoTabela({
  titulo,
  itens,
  mostrarPd = false,
  colunaValor = 'Valor face',
}: {
  titulo: string
  itens: ConcentracaoItem[]
  mostrarPd?: boolean
  colunaValor?: string
}) {
  const colunas = mostrarPd ? 4 : 3

  return (
    <div className="painel">
      <h2>{titulo}</h2>
      <table>
        <thead>
          <tr>
            <th>Nome</th>
            <th>{colunaValor}</th>
            <th>Peso</th>
            {mostrarPd && <th>PD estimada</th>}
          </tr>
        </thead>
        <tbody>
          {itens.length === 0 ? (
            <tr>
              <td colSpan={colunas} className="vazio">
                Sem dados
              </td>
            </tr>
          ) : (
            itens.map((item) => (
              <tr key={item.nome}>
                <td>{item.nome}</td>
                <td>{formatarMoeda(item.valor)}</td>
                <td>{item.peso}</td>
                {mostrarPd && (
                  <td>{num(item.pd_estimada).toFixed(2)}%</td>
                )}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}

export default App
