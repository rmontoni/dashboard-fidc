import { Fragment, useEffect, useState } from 'react'
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
  ConsignadoEmpresa,
  DataBaseDetalhe,
  FaixaAging,
  FatiaDistribuicao,
  Kpis,
  PontoEvolucao,
  PontoFluxoCaixa,
  PosicaoLiquidez,
  PosicoesLiquidez,
  RespostaConsignado,
  RespostaRisco,
} from './types'
import { API_BASE } from './types'
import { CalendarioDataBase } from './CalendarioDataBase'
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
  inadimplencia_vnp: 0,
  inadimplencia_vencimentos: 0,
  subordinacao_pct: null,
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
  const [consignado, setConsignado] = useState<RespostaConsignado | null>(null)
  const [empresaConsignadoAberta, setEmpresaConsignadoAberta] = useState<string | null>(
    null,
  )
  const [avisoConsignado, setAvisoConsignado] = useState<string | null>(null)
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
    // Última data disponível: conciliada, ou com liquidez IDSF (dados existem).
    const disponiveis = detalhe.filter((d) => d.status === 'ok' || d.conciliada || d.tem_liquidez)
    const ultima =
      (disponiveis.length > 0 ? disponiveis : detalhe).at(-1) ?? null
    if (preferirAtual) {
      setDataBaseFiltro((atual) => {
        if (atual && detalhe.some((d) => d.data === atual)) return atual
        const salvo = localStorage.getItem('fidc_data_base') || ''
        if (salvo && detalhe.some((d) => d.data === salvo)) return salvo
        const proxima = ultima?.data ?? ''
        if (proxima) localStorage.setItem('fidc_data_base', proxima)
        return proxima
      })
    } else if (ultima) {
      setDataBaseFiltro(ultima.data)
      localStorage.setItem('fidc_data_base', ultima.data)
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
      setAvisoConsignado(null)

      try {
        // Consignado depois do risco: evita disputa de soquete no Windows
        // (WinError 10035) quando os dois batem no Supabase juntos.
        const res = await fetch(
          `${API_BASE}/fidc/risco?dataBase=${encodeURIComponent(dataBaseFiltro)}`,
        )
        const bruto = await res.text()
        let dados: Record<string, unknown> = {}
        try {
          dados = bruto ? (JSON.parse(bruto) as Record<string, unknown>) : {}
        } catch {
          setErro(
            res.status
              ? `Falha ao buscar risco (HTTP ${res.status}).`
              : 'Falha ao buscar dados de risco na API.',
          )
          setIndicadores(KPI_VAZIO)
          setPosicoesLiquidez(POSICOES_VAZIAS)
          return
        }

        const buscarConsignado = async (tentativa: number): Promise<void> => {
          const resCons = await fetch(
            `${API_BASE}/fidc/consignado?dataBase=${encodeURIComponent(dataBaseFiltro)}`,
          )
          if (resCons.ok) {
            const cons = (await resCons.json()) as RespostaConsignado
            setConsignado(cons)
            setAvisoConsignado(cons.aviso ?? null)
            setEmpresaConsignadoAberta(null)
            return
          }
          const consErr = await resCons.json().catch(() => ({}))
          const detail =
            typeof consErr.detail === 'string'
              ? consErr.detail
              : 'Consignado Privado indisponível para esta data.'
          const transiente =
            /10035|10054|10060|timeout|timed out|socket|conexão|connection/i.test(
              detail,
            )
          if (transiente && tentativa < 3) {
            await new Promise((r) => setTimeout(r, 400 * tentativa))
            return buscarConsignado(tentativa + 1)
          }
          setConsignado(null)
          setAvisoConsignado(
            transiente
              ? 'Consignado temporariamente indisponível — tente atualizar a data base.'
              : detail,
          )
        }
        await buscarConsignado(1)

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
        const msg = error instanceof Error ? error.message : ''
        setErro(
          /timeout|network|failed to fetch|aborted/i.test(msg)
            ? 'A API de risco não respondeu a tempo. No Vercel o cache BDR não está disponível — use o backend local para o motor completo.'
            : 'Falha ao buscar dados de risco na API.',
        )
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

  return (
    <div className="dashboard">
      <header className="topbar">
        <div>
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
          onSelect={(data) => {
            setDataBaseFiltro(data)
            localStorage.setItem('fidc_data_base', data)
          }}
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
          <small className="kpi-nota">VNP / vencimentos totais</small>
        </article>
        <article className="kpi">
          <span>% Subordinação</span>
          <strong>
            {indicadores.subordinacao_pct != null
              ? `${num(indicadores.subordinacao_pct).toFixed(2)}%`
              : '—'}
          </strong>
          <small className="kpi-nota">PL SUB / PL consolidado</small>
        </article>
        <article className="kpi">
          <span>Receita total projetada</span>
          <strong>{formatarMoeda(indicadores.receita_projetada)}</strong>
        </article>
      </section>

      <section className="kpis kpis-baixa-var">
        <article className="kpi">
          <span>Taxa média a.m.</span>
          <strong>{num(indicadores.taxa_media).toFixed(2)}%</strong>
        </article>
        <article className="kpi">
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
          dados={distCedentes}
        />
        <GraficoPizza
          titulo="Distribuição por sacado"
          dados={distSacados}
        />
      </section>

      <section className="grades">
        <ConcentracaoTabela
          titulo="Top 10 Cedentes"
          itens={topCedentes}
        />
        <ConcentracaoTabela
          titulo="Top 10 Sacados"
          itens={topSacados}
          mostrarPd
        />
      </section>

      <section className="painel">
        <h2>Concentração por tipo de recebível</h2>
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

      <section className="painel consignado-painel">
        <div className="painel-cabecalho">
          <div>
            <h2>Consignado Privado</h2>
          </div>
          {consignado && (
            <div className="painel-totais">
              <div className="painel-total">
                <span>VP</span>
                <strong>{formatarMoeda(consignado.totais.vp)}</strong>
              </div>
              <div className="painel-total">
                <span>A vencer</span>
                <strong>{formatarMoeda(consignado.totais.a_vencer)}</strong>
              </div>
              <div className="painel-total">
                <span>Vencidos</span>
                <strong>{formatarMoeda(consignado.totais.vencidos)}</strong>
              </div>
              <div className="painel-total">
                <span>PDD</span>
                <strong>{formatarMoeda(consignado.totais.pdd)}</strong>
              </div>
            </div>
          )}
        </div>
        {avisoConsignado && <p className="aviso-inline">{avisoConsignado}</p>}
        {!consignado || consignado.empresas.length === 0 ? (
          <p className="vazio">
            Sem posição de consignado privado para esta data base.
          </p>
        ) : (
          <div className="consignado-tabela-scroll">
          <table className="tabela-aging tabela-consignado">
            <thead>
              <tr>
                <th></th>
                <th>Empresa</th>
                <th>VP</th>
                <th>A vencer</th>
                <th>Vencidos</th>
                <th>PDD</th>
                <th>Qtd</th>
              </tr>
            </thead>
            <tbody>
              {consignado.empresas.map((emp: ConsignadoEmpresa) => {
                const chave = emp.empresa_vazia ? '__vazia__' : emp.empresa
                const aberta = empresaConsignadoAberta === chave
                return (
                  <Fragment key={chave}>
                    <tr
                      className={`linha-aging${aberta ? ' aberta' : ''}${emp.empresa_vazia ? ' empresa-vazia' : ''}`}
                      onClick={() =>
                        setEmpresaConsignadoAberta(aberta ? null : chave)
                      }
                    >
                      <td className="col-expandir">{aberta ? '▼' : '▶'}</td>
                      <td>
                        {emp.empresa}
                        {emp.empresa_vazia ? ' · pendente tratamento' : ''}
                      </td>
                      <td>{formatarMoeda(emp.vp)}</td>
                      <td>{formatarMoeda(emp.a_vencer)}</td>
                      <td>{formatarMoeda(emp.vencidos)}</td>
                      <td>{formatarMoeda(emp.pdd)}</td>
                      <td>{emp.n}</td>
                    </tr>
                    {aberta && (
                      <tr className="linha-detalhe-aging">
                        <td colSpan={7}>
                          <table className="tabela-titulos-aging">
                            <thead>
                              <tr>
                                <th>Sacado</th>
                                <th>Evento</th>
                                <th>Data</th>
                                <th>Saída afastamento</th>
                                <th>VP</th>
                                <th>A vencer</th>
                                <th>Vencidos</th>
                                <th>PDD</th>
                              </tr>
                            </thead>
                            <tbody>
                              {emp.sacados.map((sac) => {
                                const linhas =
                                  sac.eventos.length > 1
                                    ? sac.eventos.map((ev) => ({
                                        key: `${sac.doc_sacado}-${ev.tipo_evento}-${ev.entrada}-${ev.saida_afastamento}`,
                                        sacado: sac.sacado,
                                        evento: ev.tipo_evento || '—',
                                        data: ev.entrada || '—',
                                        saida:
                                          (ev.tipo_evento || '').toLowerCase() ===
                                          'afastamento'
                                            ? ev.saida_afastamento || '—'
                                            : '—',
                                        vp: ev.vp,
                                        a_vencer: ev.a_vencer,
                                        vencidos: ev.vencidos,
                                        pdd: ev.pdd,
                                      }))
                                    : [
                                        {
                                          key: `${sac.doc_sacado}-unico`,
                                          sacado: sac.sacado,
                                          evento: sac.tipo_evento || '—',
                                          data: sac.entrada || '—',
                                          saida:
                                            (sac.tipo_evento || '').toLowerCase() ===
                                            'afastamento'
                                              ? sac.saida_afastamento || '—'
                                              : '—',
                                          vp: sac.vp,
                                          a_vencer: sac.a_vencer,
                                          vencidos: sac.vencidos,
                                          pdd: sac.pdd,
                                        },
                                      ]
                                return linhas.map((linha) => (
                                  <tr key={linha.key}>
                                    <td>{linha.sacado}</td>
                                    <td>{linha.evento}</td>
                                    <td>{linha.data}</td>
                                    <td>{linha.saida}</td>
                                    <td>{formatarMoeda(linha.vp)}</td>
                                    <td>{formatarMoeda(linha.a_vencer)}</td>
                                    <td>{formatarMoeda(linha.vencidos)}</td>
                                    <td>{formatarMoeda(linha.pdd)}</td>
                                  </tr>
                                ))
                              })}
                            </tbody>
                          </table>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
          </div>
        )}
      </section>
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
  subtitulo?: string
  dados: FatiaDistribuicao[]
}) {
  return (
    <div className="painel">
      <h2>{titulo}</h2>
      {subtitulo ? <p className="subtitulo">{subtitulo}</p> : null}
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
  const colunas = 3 + (mostrarPd ? 1 : 0)

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
                {mostrarPd && <td>{num(item.pd_estimada).toFixed(2)}%</td>}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}

export default Dashboard
