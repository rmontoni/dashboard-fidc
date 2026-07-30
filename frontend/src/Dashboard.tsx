import { Fragment, useEffect, useRef, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  LabelList,
  Legend,
  Line,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type {
  ConcentracaoItem,
  ConciliacaoDc,
  DataBaseDetalhe,
  FaixaAging,
  FatiaDistribuicao,
  Kpis,
  PontoEvolucao,
  PontoFluxoCaixa,
  PosicaoLiquidez,
  PosicoesLiquidez,
  RespostaRisco,
} from './types'
import { API_BASE } from './types'
import './App.css'

const KPI_VAZIO: Kpis = {
  pl_fundo: 0,
  pl_direitos_creditorios: 0,
  caixa: 0,
  provisoes: 0,
  aplicacoes: 0,
  provisao_pdd: 0,
  operacoes_ativas: 0,
  volume_cedido: 0,
  valor_presente: 0,
  prazo_medio: 0,
  hhi: 0,
  inadimplencia: 0,
  receita_projetada: 0,
  taxa_media: 0,
  taxa_recompra: 0,
  taxa_baixa: 0,
  taxa_baixa_recompra: 0,
  tem_recompra: false,
  credit_var_historico_95: 0,
  credit_var_parametrico_95: 0,
  n_obs: 0,
}

const POSICOES_VAZIAS: PosicoesLiquidez = {
  caixa: [],
  aplicacoes: [],
  total_caixa: 0,
  total_provisoes: 0,
  total_aplicacoes: 0,
  total_liquidez: 0,
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

function formatarMoedaCentavos(valor: number | undefined | null): string {
  return Number(valor ?? 0).toLocaleString('pt-BR', {
    style: 'currency',
    currency: 'BRL',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

function num(valor: number | undefined | null): number {
  return Number(valor ?? 0)
}

type DashboardProps = {
  fundoNome?: string
}

function Dashboard({ fundoNome }: DashboardProps) {
  const [datasDetalhe, setDatasDetalhe] = useState<DataBaseDetalhe[]>([])
  const [feriados, setFeriados] = useState<Map<string, string>>(new Map())
  const [dataBaseFiltro, setDataBaseFiltro] = useState('')
  const [aCarregar, setACarregar] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const [indicadores, setIndicadores] = useState<Kpis>(KPI_VAZIO)
  const [topCedentes, setTopCedentes] = useState<ConcentracaoItem[]>([])
  const [topSacados, setTopSacados] = useState<ConcentracaoItem[]>([])
  const [distCedentes, setDistCedentes] = useState<FatiaDistribuicao[]>([])
  const [distSacados, setDistSacados] = useState<FatiaDistribuicao[]>([])
  const [distTipos, setDistTipos] = useState<FatiaDistribuicao[]>([])
  const [graficoFluxo, setGraficoFluxo] = useState<PontoFluxoCaixa[]>([])
  const [graficoEvolucao, setGraficoEvolucao] = useState<PontoEvolucao[]>([])
  const [agingInad, setAgingInad] = useState<FaixaAging[]>([])
  const [topSacadosInad, setTopSacadosInad] = useState<ConcentracaoItem[]>([])
  const [topCedentesInad, setTopCedentesInad] = useState<ConcentracaoItem[]>([])
  const [faixaAgingAberta, setFaixaAgingAberta] = useState<string | null>(null)
  const [posicoesLiquidez, setPosicoesLiquidez] = useState<PosicoesLiquidez>(POSICOES_VAZIAS)
  const [avisoIdsf, setAvisoIdsf] = useState<string | null>(null)
  const [conciliacaoDc, setConciliacaoDc] = useState<ConciliacaoDc | null>(null)
  const [mesCalendario, setMesCalendario] = useState(() => {
    const hoje = new Date()
    return { ano: hoje.getFullYear(), mes: hoje.getMonth() }
  })

  const dataSelecionada = datasDetalhe.find((d) => d.data === dataBaseFiltro)
  const mapaDatas = new Map(datasDetalhe.map((d) => [d.data_iso, d]))

  function aplicarDatas(detalhe: DataBaseDetalhe[], preferirAtual = false) {
    setDatasDetalhe(detalhe)
    // Sempre a última data disponível no motor (status ok / conciliada).
    const disponiveis = detalhe.filter((d) => d.status === 'ok' || d.conciliada)
    const ultima =
      (disponiveis.length > 0 ? disponiveis : detalhe).at(-1) ?? null
    if (preferirAtual) {
      setDataBaseFiltro((atual) => {
        if (atual && detalhe.some((d) => d.data === atual)) return atual
        return ultima?.data ?? ''
      })
    } else if (ultima) {
      setDataBaseFiltro(ultima.data)
    }
    if (ultima?.data_iso) {
      const [y, m] = ultima.data_iso.split('-').map(Number)
      setMesCalendario({ ano: y, mes: m - 1 })
    }
  }

  async function carregarDatas() {
    setErro(null)
    try {
      const res = await fetch(`${API_BASE}/fidc/datas`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const dados = await res.json()
      const mapaFer = new Map<string, string>()
      for (const f of dados.feriados ?? []) {
        if (f?.data && f?.nome) mapaFer.set(String(f.data), String(f.nome))
      }
      setFeriados(mapaFer)
      const detalhe: DataBaseDetalhe[] =
        dados.detalhe?.length > 0
          ? dados.detalhe
          : (dados.datas ?? []).map((data: string) => ({
              data,
              data_iso: data,
              status: 'ok',
              conciliada: true,
            }))
      aplicarDatas(detalhe, true)
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
        const mapaFer = new Map<string, string>()
        for (const f of dados.feriados ?? []) {
          if (f?.data && f?.nome) mapaFer.set(String(f.data), String(f.nome))
        }
        setFeriados(mapaFer)
        const detalhe: DataBaseDetalhe[] =
          dados.detalhe?.length > 0
            ? dados.detalhe
            : (dados.datas ?? []).map((data: string) => ({
                data,
                data_iso: data,
                status: 'ok',
                conciliada: true,
              }))
        aplicarDatas(detalhe)
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
        const dados = await res.json()

        if (!res.ok) {
          const detail = dados.detail ?? dados.erro ?? `HTTP ${res.status}`
          setErro(typeof detail === 'string' ? detail : JSON.stringify(detail))
          setIndicadores(KPI_VAZIO)
          setPosicoesLiquidez(POSICOES_VAZIAS)
          setAvisoIdsf(null)
          setConciliacaoDc(null)
          setTopCedentes([])
          setTopSacados([])
          setDistCedentes([])
          setDistSacados([])
          setDistTipos([])
          setGraficoFluxo([])
          setGraficoEvolucao([])
          setAgingInad([])
          setTopSacadosInad([])
          setTopCedentesInad([])
          setFaixaAgingAberta(null)
          return
        }

        const risco = dados as RespostaRisco
        if (risco.erro) {
          setErro(risco.erro)
          setIndicadores(KPI_VAZIO)
          setPosicoesLiquidez(POSICOES_VAZIAS)
          setAvisoIdsf(null)
          setConciliacaoDc(null)
          setTopCedentes([])
          setTopSacados([])
          setDistCedentes([])
          setDistSacados([])
          setDistTipos([])
          setGraficoFluxo([])
          setGraficoEvolucao([])
          setAgingInad([])
          setTopSacadosInad([])
          setTopCedentesInad([])
          setFaixaAgingAberta(null)
          return
        }

        setIndicadores({ ...KPI_VAZIO, ...(risco.kpis ?? {}) })
        setPosicoesLiquidez(risco.posicoes_liquidez ?? POSICOES_VAZIAS)
        setAvisoIdsf(risco.aviso_idsf ?? null)
        setConciliacaoDc(risco.conciliacao_dc ?? null)
        if (risco.conciliacao_dc) {
          const conciliada = Boolean(risco.conciliacao_dc.conciliada_idsf)
          const status = conciliada ? 'ok' : 'pendente'
          setDatasDetalhe((atual) => {
            const idx = atual.findIndex((d) => d.data === dataBaseFiltro)
            if (idx < 0) return atual
            const item = atual[idx]
            if (item.conciliada === conciliada && item.status === status) return atual
            const proximo = [...atual]
            proximo[idx] = { ...item, conciliada, status }
            return proximo
          })
        }
        setTopCedentes(risco.top_cedentes ?? [])
        setTopSacados(risco.top_sacados ?? [])
        setDistCedentes(risco.distribuicao_cedentes ?? [])
        setDistSacados(risco.distribuicao_sacados ?? [])
        setDistTipos(risco.distribuicao_tipos ?? [])
        setGraficoFluxo(risco.grafico_fluxo_caixa ?? [])
        setGraficoEvolucao(risco.grafico_evolucao ?? [])
        setAgingInad(risco.aging_inadimplencia ?? [])
        setTopSacadosInad(risco.top_sacados_inadimplentes ?? [])
        setTopCedentesInad(risco.top_cedentes_inadimplentes ?? [])
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

  const taxaBaixaRecompra =
    num(indicadores.taxa_baixa_recompra) > 0
      ? num(indicadores.taxa_baixa_recompra)
      : num(indicadores.taxa_baixa) + num(indicadores.taxa_recompra)
  const temRecompra =
    indicadores.tem_recompra === true || num(indicadores.taxa_recompra) > 0

  return (
    <div className="dashboard">
      <header className="topbar">
        <div>
          <p className="eyebrow">
            Números do motor próprio · conciliação com IDSF
            {conciliacaoDc?.tolerancia != null && (
              <> (tol. {formatarMoeda(conciliacaoDc.tolerancia)})</>
            )}
          </p>
          <h1>{fundoNome ? `Dashboard — ${fundoNome}` : 'Dashboard FIDC'}</h1>
        </div>
        <CalendarioDataBase
          ano={mesCalendario.ano}
          mes={mesCalendario.mes}
          selecionada={dataBaseFiltro}
          itemSelecionado={dataSelecionada}
          mapa={mapaDatas}
          feriados={feriados}
          onMesChange={(ano, mes) => setMesCalendario({ ano, mes })}
          onSelect={(data) => setDataBaseFiltro(data)}
        />
      </header>

      {conciliacaoDc && !conciliacaoDc.conciliada_idsf && (
        <div className="banner-status banner-data">
          Divergência motor × IDSF fora da tolerância (
          {formatarMoedaCentavos(conciliacaoDc.tolerancia)}): VP Δ{' '}
          {formatarMoedaCentavos(conciliacaoDc.delta_dc)}
          {conciliacaoDc.delta_pdd != null && (
            <> · PDD Δ {formatarMoedaCentavos(conciliacaoDc.delta_pdd)}</>
          )}{' '}
          (VP {formatarMoeda(conciliacaoDc.dc_bdr)} vs DC{' '}
          {formatarMoeda(conciliacaoDc.dc_idsf)}
          {conciliacaoDc.pdd_bdr != null && conciliacaoDc.pdd_idsf != null && (
            <>
              ; PDD {formatarMoeda(conciliacaoDc.pdd_bdr)} vs{' '}
              {formatarMoeda(conciliacaoDc.pdd_idsf)}
            </>
          )}
          )
        </div>
      )}
      {conciliacaoDc?.conciliada_idsf &&
        conciliacaoDc.tem_divergencia_residual && (
          <div className="banner-status banner-data">
            Conciliado com resíduo de marcação (tol.{' '}
            {formatarMoedaCentavos(conciliacaoDc.tolerancia)}): VP Δ{' '}
            {formatarMoedaCentavos(conciliacaoDc.delta_dc)}
            {conciliacaoDc.delta_pdd != null && (
              <> · PDD Δ {formatarMoedaCentavos(conciliacaoDc.delta_pdd)}</>
            )}
          </div>
        )}
      {conciliacaoDc?.conciliada_idsf &&
        !conciliacaoDc.tem_divergencia_residual && (
          <div className="banner-ok banner-data">
            Números do motor conciliados com IDSF (VP e PDD)
          </div>
        )}

      {erro && (
        <div className="banner-erro">
          <span>{erro}</span>
          <button type="button" className="btn-retry" onClick={carregarDatas}>
            Tentar novamente
          </button>
        </div>
      )}
      {aCarregar && <div className="banner-status">Carregando indicadores…</div>}

      <section className="kpis kpis-pl">
        <article className="kpi kpi-destaque">
          <span>PL do Fundo</span>
          <strong>{formatarMoeda(indicadores.pl_fundo)}</strong>
          <span className="kpi-nota">
            DC {formatarMoeda(indicadores.pl_direitos_creditorios)} + CC saldo{' '}
            {formatarMoeda(indicadores.caixa)} + aplicações{' '}
            {formatarMoeda(indicadores.aplicacoes)}
            {num(indicadores.provisoes) !== 0
              ? ` + provisões ${formatarMoeda(indicadores.provisoes)}`
              : ''}
            {num(indicadores.passivo_aporte) !== 0
              ? ` + VALID ${formatarMoeda(indicadores.passivo_aporte)}`
              : ''}
          </span>
        </article>
      </section>

      <section className="kpis kpis-liquidez">
        <article className="kpi">
          <span>Direitos creditórios (líq. PDD)</span>
          <strong>{formatarMoeda(indicadores.pl_direitos_creditorios)}</strong>
        </article>
        <article className="kpi">
          <span>Caixa — CC Saldo</span>
          <strong>{formatarMoeda(indicadores.caixa)}</strong>
        </article>
        <article className="kpi">
          <span>Aplicações (IDSF)</span>
          <strong>{formatarMoeda(indicadores.aplicacoes)}</strong>
        </article>
      </section>

      {avisoIdsf && (
        <div className="banner-status">Liquidez IDSF: {avisoIdsf}</div>
      )}

      <section className="grades grades-liquidez">
        <TabelaPosicoes
          titulo="Caixa (Conta Corrente — Saldo)"
          subtitulo="Saldo em conta corrente"
          total={posicoesLiquidez.total_caixa}
          linhas={posicoesLiquidez.caixa}
        />
        <TabelaPosicoes
          titulo="Aplicações"
          subtitulo="Fundos (FIRF, DI, etc.)"
          total={posicoesLiquidez.total_aplicacoes}
          linhas={posicoesLiquidez.aplicacoes}
        />
      </section>

      <section className="kpis kpis-carteira">
        <article className="kpi">
          <span>Operações ativas</span>
          <strong>{num(indicadores.operacoes_ativas).toLocaleString('pt-BR')}</strong>
        </article>
        <article className="kpi">
          <span>Valor presente</span>
          <strong>{formatarMoeda(indicadores.valor_presente)}</strong>
        </article>
        <article className="kpi">
          <span>PDD total</span>
          <strong>{formatarMoeda(indicadores.provisao_pdd)}</strong>
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
          <span>Taxa média a.m.</span>
          <strong>{num(indicadores.taxa_media).toFixed(2)}%</strong>
        </article>
      </section>

      <section className="kpis kpis-baixa-var">
        <article className={`kpi ${classeAlertaPct(taxaBaixaRecompra)}`}>
          <span>Taxa de Baixa/Recompra</span>
          <strong>{taxaBaixaRecompra.toFixed(2)}%</strong>
        </article>
        <article className="kpi">
          <span>Credit VaR 95% (histórico)</span>
          <strong>{num(indicadores.credit_var_historico_95).toFixed(2)}%</strong>
        </article>
        <article className="kpi">
          <span>Credit VaR 95% (paramétrico)</span>
          <strong>{num(indicadores.credit_var_parametrico_95).toFixed(2)}%</strong>
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
        <h2>Concentração por tipo de recebível</h2>
        <p className="subtitulo">Participação no valor presente das operações ativas</p>
        <div className="chart-wrap chart-tipos">
          {distTipos.length === 0 ? (
            <p className="vazio">Sem dados</p>
          ) : (
            <ResponsiveContainer width="100%" height={Math.max(180, distTipos.length * 56)}>
              <BarChart
                data={[...distTipos].sort((a, b) => b.peso - a.peso)}
                layout="vertical"
                margin={{ top: 8, right: 88, left: 8, bottom: 8 }}
              >
                <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#d8e0ea" />
                <XAxis
                  type="number"
                  domain={[0, 100]}
                  tickFormatter={(v) => `${v}%`}
                  stroke="#6b7c93"
                  fontSize={12}
                />
                <YAxis
                  type="category"
                  dataKey="nome"
                  width={100}
                  stroke="#6b7c93"
                  fontSize={13}
                />
                <Tooltip
                  formatter={(value, _name, item) => {
                    const fatia = item?.payload as FatiaDistribuicao | undefined
                    return [
                      `${formatarMoeda(Number(fatia?.valor ?? 0))} (${Number(value ?? 0).toFixed(1)}%)`,
                      'Valor presente',
                    ]
                  }}
                  contentStyle={{
                    background: '#0f2740',
                    border: 'none',
                    borderRadius: 8,
                    color: '#fff',
                  }}
                />
                <Bar dataKey="peso" radius={[0, 6, 6, 0]} barSize={28} name="Peso">
                  {[...distTipos]
                    .sort((a, b) => b.peso - a.peso)
                    .map((fatia, index) => (
                      <Cell
                        key={fatia.nome}
                        fill={CORES_PIZZA[index % CORES_PIZZA.length]}
                      />
                    ))}
                  <LabelList
                    dataKey="peso"
                    position="right"
                    formatter={(label) => `${Number(label ?? 0).toFixed(1)}%`}
                    style={{ fill: '#334155', fontSize: 12, fontWeight: 600 }}
                  />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
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
          <div className="painel-totais">
            <div className="painel-total">
              <span>VNP Total</span>
              <strong>
                {formatarMoeda(agingInad.reduce((acc, f) => acc + num(f.valor), 0))}
              </strong>
            </div>
            <div className="painel-total">
              <span>Valor com PDD</span>
              <strong>
                {formatarMoeda(
                  agingInad.reduce((acc, f) => acc + num(f.valor_com_pdd), 0),
                )}
              </strong>
            </div>
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
                <th>Valor com PDD</th>
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
                      <td>{formatarMoeda(faixa.valor_com_pdd)}</td>
                      <td>{faixa.qtd}</td>
                      <td>{num(faixa.peso).toFixed(1)}%</td>
                    </tr>
                    {aberta && (
                      <tr className="linha-detalhe-aging">
                        <td colSpan={6}>
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
                                  <th>Valor com PDD</th>
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
                                    <td>{formatarMoeda(titulo.valor_com_pdd)}</td>
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
        <p className="subtitulo">
          Volume e taxa média a.m. dos últimos 60 dias (por dia de emissão)
        </p>
        <div className="chart-wrap chart-fluxo">
          {graficoEvolucao.length === 0 ? (
            <p className="vazio">Sem dados de originação para a data base selecionada.</p>
          ) : (
            <ComposedChart
              responsive
              width="100%"
              height={340}
              data={graficoEvolucao}
              margin={{ top: 28, right: 48, left: 8, bottom: 8 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#d8e0ea" />
              <XAxis dataKey="mes_ano_emissao" tick={{ fill: '#5a6b7d', fontSize: 12 }} />
              <YAxis
                yAxisId="volume"
                tick={{ fill: '#5a6b7d', fontSize: 12 }}
                tickFormatter={(v) =>
                  Number(v).toLocaleString('pt-BR', {
                    notation: 'compact',
                    maximumFractionDigits: 1,
                  })
                }
                width={56}
              />
              <YAxis
                yAxisId="taxa"
                orientation="right"
                tick={{ fill: '#9e2a2b', fontSize: 12 }}
                tickFormatter={(v) => `${Number(v).toFixed(1)}%`}
                width={44}
              />
              <Tooltip
                formatter={(value, name) => {
                  if (name === 'Taxa média a.m.') {
                    return [`${Number(value ?? 0).toFixed(2)}%`, name]
                  }
                  if (name === 'Volume originado') {
                    return [formatarMoeda(Number(value ?? 0)), name]
                  }
                  return [value, name]
                }}
                contentStyle={{
                  background: '#0f2740',
                  border: 'none',
                  borderRadius: 8,
                  color: '#fff',
                }}
              />
              <Legend />
              <Bar
                yAxisId="volume"
                dataKey="volume_originado"
                name="Volume originado"
                fill="#1f6f8b"
                radius={[4, 4, 0, 0]}
              />
              <Line
                yAxisId="taxa"
                type="monotone"
                dataKey="taxa_media"
                name="Taxa média a.m."
                stroke="#9e2a2b"
                strokeWidth={2.5}
                dot={{ r: 4, fill: '#9e2a2b' }}
                activeDot={{ r: 5 }}
              />
            </ComposedChart>
          )}
        </div>
      </section>

      <section className="grades">
        <ConcentracaoTabela
          titulo="Top 10 Cedentes"
          itens={topCedentes}
          mostrarRecompraBaixa={temRecompra}
          mostrarBaixa
        />
        <ConcentracaoTabela
          titulo="Top 10 Sacados"
          itens={topSacados}
          mostrarPd
          mostrarRecompraBaixa={temRecompra}
          mostrarBaixa
        />
      </section>
    </div>
  )
}

function rotuloMesNome(mes: number): string {
  return new Date(2000, mes, 1).toLocaleDateString('pt-BR', { month: 'long' })
}

const MESES_PT = Array.from({ length: 12 }, (_, i) => ({
  valor: i,
  nome: rotuloMesNome(i),
}))

function CalendarioDataBase({
  ano,
  mes,
  selecionada,
  itemSelecionado,
  mapa,
  feriados,
  onMesChange,
  onSelect,
}: {
  ano: number
  mes: number
  selecionada: string
  itemSelecionado?: DataBaseDetalhe
  mapa: Map<string, DataBaseDetalhe>
  feriados: Map<string, string>
  onMesChange: (ano: number, mes: number) => void
  onSelect: (data: string) => void
}) {
  const [aberto, setAberto] = useState(false)
  const [editandoMes, setEditandoMes] = useState(false)
  const [editandoAno, setEditandoAno] = useState(false)
  const raizRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!aberto) {
      setEditandoMes(false)
      setEditandoAno(false)
    }
  }, [aberto])

  useEffect(() => {
    if (!aberto) return
    function fecharFora(ev: MouseEvent) {
      if (raizRef.current && !raizRef.current.contains(ev.target as Node)) {
        setAberto(false)
      }
    }
    function fecharEsc(ev: KeyboardEvent) {
      if (ev.key === 'Escape') setAberto(false)
    }
    document.addEventListener('mousedown', fecharFora)
    document.addEventListener('keydown', fecharEsc)
    return () => {
      document.removeEventListener('mousedown', fecharFora)
      document.removeEventListener('keydown', fecharEsc)
    }
  }, [aberto])

  const primeiro = new Date(ano, mes, 1)
  const desloc = (primeiro.getDay() + 6) % 7 // segunda = 0
  const diasNoMes = new Date(ano, mes + 1, 0).getDate()
  const celulas: Array<{ dia: number; iso: string; item?: DataBaseDetalhe } | null> = []
  for (let i = 0; i < desloc; i += 1) celulas.push(null)
  for (let dia = 1; dia <= diasNoMes; dia += 1) {
    const iso = `${ano}-${String(mes + 1).padStart(2, '0')}-${String(dia).padStart(2, '0')}`
    celulas.push({ dia, iso, item: mapa.get(iso) })
  }

  function navegar(delta: number) {
    const d = new Date(ano, mes + delta, 1)
    onMesChange(d.getFullYear(), d.getMonth())
  }

  const anosDisponiveis = (() => {
    const set = new Set<number>()
    for (const item of mapa.values()) {
      const y = Number(item.data_iso.slice(0, 4))
      if (Number.isFinite(y)) set.add(y)
    }
    set.add(ano)
    return Array.from(set).sort((a, b) => a - b)
  })()

  const statusTrigger = itemSelecionado?.conciliada
    ? 'conciliada'
    : itemSelecionado
      ? 'pendente'
      : ''

  return (
    <div className={`filtro-data-base${aberto ? ' aberto' : ''}`} ref={raizRef}>
      <span className="filtro-data-label">Data base</span>
      <button
        type="button"
        className={`filtro-data-trigger${statusTrigger ? ` ${statusTrigger}` : ''}`}
        aria-haspopup="dialog"
        aria-expanded={aberto}
        onClick={() => setAberto((v) => !v)}
      >
        <span className="filtro-data-valor">{selecionada || '—'}</span>
        <span className="filtro-data-seta" aria-hidden>
          ▾
        </span>
      </button>

      {aberto && (
        <div className="calendario-db calendario-popover" role="dialog" aria-label="Calendário data base">
          <div className="calendario-nav">
            <button type="button" onClick={() => navegar(-1)} aria-label="Mês anterior">
              ‹
            </button>
            <div className="calendario-titulo">
              {editandoMes ? (
                <select
                  className="calendario-edit-mes"
                  value={mes}
                  autoFocus
                  aria-label="Mês"
                  onChange={(e) => {
                    onMesChange(ano, Number(e.target.value))
                    setEditandoMes(false)
                  }}
                  onBlur={() => setEditandoMes(false)}
                >
                  {MESES_PT.map((m) => (
                    <option key={m.valor} value={m.valor}>
                      {m.nome}
                    </option>
                  ))}
                </select>
              ) : (
                <button
                  type="button"
                  className="calendario-edit-btn"
                  title="Alterar mês"
                  onClick={() => {
                    setEditandoAno(false)
                    setEditandoMes(true)
                  }}
                >
                  {rotuloMesNome(mes)}
                </button>
              )}
              {editandoAno ? (
                <select
                  className="calendario-edit-ano"
                  value={ano}
                  autoFocus
                  aria-label="Ano"
                  onChange={(e) => {
                    onMesChange(Number(e.target.value), mes)
                    setEditandoAno(false)
                  }}
                  onBlur={() => setEditandoAno(false)}
                >
                  {anosDisponiveis.map((y) => (
                    <option key={y} value={y}>
                      {y}
                    </option>
                  ))}
                </select>
              ) : (
                <button
                  type="button"
                  className="calendario-edit-btn"
                  title="Alterar ano"
                  onClick={() => {
                    setEditandoMes(false)
                    setEditandoAno(true)
                  }}
                >
                  {ano}
                </button>
              )}
            </div>
            <button type="button" onClick={() => navegar(1)} aria-label="Próximo mês">
              ›
            </button>
          </div>
          <div className="calendario-semana">
            {['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'].map((d) => (
              <span key={d}>{d}</span>
            ))}
          </div>
          <div className="calendario-grid">
            {celulas.map((cel, idx) => {
              if (!cel) return <span key={`e-${idx}`} className="cal-dia vazio" />
              const item = cel.item
              const nomeFeriado = feriados.get(cel.iso)
              const util = Boolean(item) && !nomeFeriado
              const classes = [
                'cal-dia',
                util ? 'util' : 'inativo',
                nomeFeriado ? 'feriado' : '',
                item?.conciliada ? 'conciliada' : '',
                item && !item.conciliada ? 'pendente' : '',
                item?.data === selecionada ? 'selecionado' : '',
              ]
                .filter(Boolean)
                .join(' ')
              return (
                <button
                  key={cel.iso}
                  type="button"
                  className={classes}
                  disabled={!util}
                  title={
                    nomeFeriado
                      ? `${cel.iso} · feriado: ${nomeFeriado} · indisponível`
                      : item
                        ? `${item.data}${item.conciliada ? ' · conciliada' : ''}${
                            item.tem_liquidez ? ' · liquidez IDSF' : ''
                          }${item.pl_estimado != null ? ` · PL est. ${item.pl_estimado}` : ''}`
                        : 'Indisponível (fim de semana ou sem relatório)'
                  }
                  onClick={() => {
                    if (!item || nomeFeriado) return
                    onSelect(item.data)
                    setAberto(false)
                  }}
                >
                  {cel.dia}
                </button>
              )
            })}
          </div>
          <div className="calendario-legenda">
            <span className="leg conciliada">Conciliado</span>
            <span className="leg pendente">Pendente</span>
            <span className="leg feriado">Feriado</span>
          </div>
        </div>
      )}
    </div>
  )
}

function TabelaPosicoes({
  titulo,
  subtitulo,
  total,
  linhas,
}: {
  titulo: string
  subtitulo: string
  total: number
  linhas: PosicaoLiquidez[]
}) {
  return (
    <div className="painel">
      <div className="painel-cabecalho">
        <div>
          <h2>{titulo}</h2>
          <p className="subtitulo">{subtitulo}</p>
        </div>
        <div className="painel-total">
          <span>Total</span>
          <strong>{formatarMoeda(total)}</strong>
        </div>
      </div>
      <table className="tabela-posicoes">
        <thead>
          <tr>
            <th>Ativo</th>
            <th>Tipo</th>
            <th>Valor líquido</th>
          </tr>
        </thead>
        <tbody>
          {linhas.length === 0 ? (
            <tr>
              <td colSpan={3} className="vazio">
                Sem posições na data
              </td>
            </tr>
          ) : (
            linhas.map((linha) => (
              <tr key={`${linha.categoria}-${linha.ativo}-${linha.tipo}`}>
                <td>
                  <span className="posicao-ativo">{linha.ativo}</span>
                  {linha.agente && <small className="posicao-agente">{linha.agente}</small>}
                </td>
                <td>{linha.tipo}</td>
                <td className={num(linha.valor_liquido) < 0 ? 'valor-negativo' : undefined}>
                  {formatarMoeda(linha.valor_liquido)}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
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

function classeAlertaPct(valor: number | undefined | null): string {
  const v = num(valor)
  if (v > 25) return 'alerta-pct alerta-pct-alto'
  if (v >= 10) return 'alerta-pct alerta-pct-medio'
  return 'alerta-pct'
}

function ConcentracaoTabela({
  titulo,
  itens,
  mostrarPd = false,
  mostrarRecompraBaixa = false,
  mostrarBaixa = false,
  colunaValor = 'Valor face',
}: {
  titulo: string
  itens: ConcentracaoItem[]
  mostrarPd?: boolean
  mostrarRecompraBaixa?: boolean
  mostrarBaixa?: boolean
  colunaValor?: string
}) {
  const mostraBaixa = mostrarBaixa || mostrarRecompraBaixa
  const colunas =
    3 + (mostrarPd ? 1 : 0) + (mostrarRecompraBaixa ? 1 : 0) + (mostraBaixa ? 1 : 0)

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
            {mostrarRecompraBaixa && <th>% Recompra</th>}
            {mostraBaixa && <th>% Baixa</th>}
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
                {mostrarPd && <td>{num(item.pd_estimada).toFixed(2)}%</td>}
                {mostrarRecompraBaixa && (
                  <td className={classeAlertaPct(item.perc_recompra)}>
                    {num(item.perc_recompra).toFixed(2)}%
                  </td>
                )}
                {mostraBaixa && (
                  <td className={classeAlertaPct(item.perc_baixa)}>
                    {num(item.perc_baixa).toFixed(2)}%
                  </td>
                )}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}

export default Dashboard
