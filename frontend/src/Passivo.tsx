import { useEffect, useMemo, useState } from 'react'
import {
  Bar,
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

type ClassePassivo = {
  id_carteira: number
  classe: string
  nome: string
  apelido: string
  pl: number
  pdd: number
  qtde_cotas: number | null
  valor_cota_idsf: number | null
  valor_cota_app: number | null
  pct_cdi: number | null
  delta_cota: number | null
  delta_pct: number | null
  ok_marcacao: boolean | null
  vencimento: string | null
  n_cotistas: number | null
  aviso_marcacao?: string | null
}

type ConferenciaSub = {
  pl_fundo: number | null
  fonte_pl?: string
  passivo_mez: number
  passivo_mez_vp?: number
  passivo_mez_liquidacao?: number
  passivo_mez_app?: number
  passivo_aporte_valid?: number | null
  pl_sub_calc: number | null
  pl_sub_idsf: number
  delta: number | null
  ok: boolean
  pl_sub_via_app?: number | null
  delta_via_app?: number | null
  cota_sub_calc?: number | null
  cota_sub_idsf?: number | null
  formula?: string
}

type RespostaPassivo = {
  data_base: string
  dt_ref_pl_br?: string | null
  pl_consolidado?: number
  subordinacao_pct: number | null
  conferencia_sub?: ConferenciaSub | null
  classes: ClassePassivo[]
  aviso?: string | null
}

type VencimentosResp = {
  data_ref: string
  kpis: {
    aplicado: number
    vp: number
    n_cotistas: number
    n_parcelas_abertas: number
    proximo: string | null
    proximo_valor: number | null
  }
  por_classe: Array<{
    classe_id: number
    classe: string
    percentual_cdi: number
    aplicado: number
    vp: number
    n_cotistas: number
    n_chamadas: number
    n_parcelas_abertas: number
    proximo: string | null
  }>
  por_data: Array<{
    data: string
    data_iso: string
    status: string
    n: number
    aplicado: number
    vp_hoje: number
    valor_liquidacao: number
  }>
}

type CotistaLista = { id: number; nome: string; documento: string }

type ParcelaPos = {
  ordem: number
  rotulo: string
  data_vencimento: string
  fracao: number
  valor_original: number
  valor_presente: number
  valor_na_liquidacao: number
  liquidada: boolean
}

type ChamadaPos = {
  chamada_id: number
  numero: number
  data_prazo: string
  data_aporte: string
  valor_nominal: number
  valor_presente_remanescente: number
  parcelas: ParcelaPos[]
}

type PosicaoResp = {
  data_ref: string
  cotista: CotistaLista
  kpis: { aplicado: number; vp: number; n_chamadas: number }
  por_classe: Array<{ classe: string; chamadas: ChamadaPos[] }>
}

type AbaPassivo = 'classes' | 'vencimentos' | 'cotista' | 'extrato-cotista'

type ClasseCadastro = { id: number; nome: string }

type PontoExtratoCotista = {
  data: string
  label: string
  saldo: number
  vp: number
  aporte: number
  amortizacao: number
  juros: number
  n_chamadas: number
  /** @deprecated use saldo */
  aplicado?: number
}

type ExtratoCotistaResp = {
  data_ref: string
  inicio: string | null
  serie: PontoExtratoCotista[]
  kpis: {
    saldo: number
    vp: number
    total_aportado: number
    n_chamadas: number
    aplicado?: number
  }
  classes: ClasseCadastro[]
}

function formatarMoeda(valor: number | null | undefined): string {
  return Number(valor ?? 0).toLocaleString('pt-BR', {
    style: 'currency',
    currency: 'BRL',
    maximumFractionDigits: 2,
  })
}

function formatarCota(valor: number | null | undefined): string {
  if (valor == null || Number.isNaN(Number(valor))) return '—'
  return Number(valor).toLocaleString('pt-BR', {
    minimumFractionDigits: 6,
    maximumFractionDigits: 8,
  })
}

function formatarQtde(valor: number | null | undefined): string {
  if (valor == null || Number.isNaN(Number(valor))) return '—'
  return Number(valor).toLocaleString('pt-BR', {
    maximumFractionDigits: 4,
  })
}

function formatarPctCdi(valor: number | null | undefined): string {
  if (valor == null || Number.isNaN(Number(valor))) return '—'
  const n = Number(valor)
  const txt = Number.isInteger(n) ? String(n) : n.toLocaleString('pt-BR', { maximumFractionDigits: 2 })
  return `${txt}% CDI`
}

function formatarDelta(valor: number | null | undefined): string {
  if (valor == null || Number.isNaN(Number(valor))) return '—'
  const n = Number(valor)
  const sinal = n > 0 ? '+' : ''
  return sinal + n.toLocaleString('pt-BR', { minimumFractionDigits: 6, maximumFractionDigits: 8 })
}

const STORAGE_DATA_BASE = 'fidc_data_base'

type PassivoProps = {
  dataBase?: string
}

function Passivo({ dataBase: dataBaseProp }: PassivoProps) {
  const [dataBase, setDataBase] = useState(
    () => dataBaseProp || localStorage.getItem(STORAGE_DATA_BASE) || '',
  )
  const [datasDetalhe, setDatasDetalhe] = useState<DataBaseDetalhe[]>([])
  const [feriados, setFeriados] = useState<Map<string, string>>(new Map())
  const [mesCalendario, setMesCalendario] = useState(() => {
    const hoje = new Date()
    return { ano: hoje.getFullYear(), mes: hoje.getMonth() }
  })
  const [dados, setDados] = useState<RespostaPassivo | null>(null)
  const [vencimentos, setVencimentos] = useState<VencimentosResp | null>(null)
  const [cotistas, setCotistas] = useState<CotistaLista[]>([])
  const [cotistaId, setCotistaId] = useState<number | ''>('')
  const [posicao, setPosicao] = useState<PosicaoResp | null>(null)
  const [classesCadastro, setClassesCadastro] = useState<ClasseCadastro[]>([])
  const [classesFiltro, setClassesFiltro] = useState<Set<number>>(new Set())
  const [extratoCotista, setExtratoCotista] = useState<ExtratoCotistaResp | null>(null)
  const [carregandoExtrato, setCarregandoExtrato] = useState(false)
  const [erroExtrato, setErroExtrato] = useState<string | null>(null)
  const [aba, setAba] = useState<AbaPassivo>('classes')
  const [erro, setErro] = useState<string | null>(null)
  const [carregando, setCarregando] = useState(false)

  const dataSelecionada = datasDetalhe.find((d) => d.data === dataBase)
  const mapaDatas = new Map(datasDetalhe.map((d) => [d.data_iso, d]))

  useEffect(() => {
    if (dataBaseProp && dataBaseProp !== dataBase) {
      setDataBase(dataBaseProp)
    }
  }, [dataBaseProp]) // eslint-disable-line react-hooks/exhaustive-deps

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
        const [resPassivo, resVenc, resCot, resCls] = await Promise.all([
          fetch(`${API_BASE}/fidc/passivo?dataBase=${encodeURIComponent(dataBase)}`),
          fetch(
            `${API_BASE}/fidc/passivo/vencimentos?dataBase=${encodeURIComponent(dataBase)}`,
          ),
          fetch(`${API_BASE}/fidc/passivo/cotistas`),
          fetch(`${API_BASE}/fidc/passivo/classes`),
        ])
        if (cancelado) return

        const jsonPassivo = await resPassivo.json()
        if (!resPassivo.ok) {
          setErro(
            typeof jsonPassivo.detail === 'string'
              ? jsonPassivo.detail
              : 'Falha ao carregar passivo.',
          )
          setDados(null)
        } else {
          setDados(jsonPassivo as RespostaPassivo)
        }

        if (resVenc.ok) {
          setVencimentos((await resVenc.json()) as VencimentosResp)
        } else {
          setVencimentos(null)
        }

        if (resCot.ok) {
          const jc = await resCot.json()
          const lista = (jc.cotistas ?? []) as CotistaLista[]
          setCotistas(lista)
          setCotistaId((atual) => {
            if (atual !== '' && lista.some((c) => c.id === atual)) return atual
            return lista[0]?.id ?? ''
          })
        }

        if (resCls.ok) {
          const jcl = await resCls.json()
          const cls = ((jcl.classes ?? []) as Array<{ id: number; nome: string }>).map(
            (c) => ({ id: c.id, nome: c.nome }),
          )
          setClassesCadastro(cls)
        }
      } catch (e) {
        if (!cancelado) {
          setErro(e instanceof Error ? e.message : 'Erro de rede')
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

  useEffect(() => {
    if (!dataBase || cotistaId === '') {
      setPosicao(null)
      return
    }
    let cancelado = false
    async function carregarPos() {
      try {
        const res = await fetch(
          `${API_BASE}/fidc/passivo/cotistas/${cotistaId}?dataBase=${encodeURIComponent(dataBase)}`,
        )
        const json = await res.json()
        if (cancelado) return
        if (!res.ok) {
          setPosicao(null)
          return
        }
        setPosicao(json as PosicaoResp)
      } catch {
        if (!cancelado) setPosicao(null)
      }
    }
    void carregarPos()
    return () => {
      cancelado = true
    }
  }, [dataBase, cotistaId])

  const classeIdsParam = useMemo(() => {
    if (classesFiltro.size === 0 || classesFiltro.size === classesCadastro.length) {
      return ''
    }
    return [...classesFiltro].join(',')
  }, [classesFiltro, classesCadastro.length])

  useEffect(() => {
    if (!dataBase || cotistaId === '' || aba !== 'extrato-cotista') {
      setExtratoCotista(null)
      return
    }
    let cancelado = false
    const ctrl = new AbortController()
    const timer = window.setTimeout(() => ctrl.abort(), 120_000)
    async function carregarExtrato() {
      setCarregandoExtrato(true)
      setErroExtrato(null)
      try {
        const qs = new URLSearchParams({
          dataBase,
          cotistaId: String(cotistaId),
        })
        if (classeIdsParam) qs.set('classeIds', classeIdsParam)
        const res = await fetch(`${API_BASE}/fidc/passivo/extrato-cotista?${qs}`, {
          signal: ctrl.signal,
        })
        if (cancelado) return
        if (res.status === 404) {
          setExtratoCotista(null)
          setErroExtrato(
            'Endpoint não encontrado no servidor — faça deploy do backend na VPS (push + setup.sh).',
          )
          return
        }
        const json = await res.json()
        if (cancelado) return
        if (!res.ok) {
          setExtratoCotista(null)
          const det =
            typeof json.detail === 'string'
              ? json.detail
              : 'Falha ao carregar extrato.'
          setErroExtrato(
            det.toLowerCase().includes('server disconnected')
              ? 'Conexão com o banco interrompida — tente de novo em alguns segundos.'
              : det,
          )
          return
        }
        setExtratoCotista(json as ExtratoCotistaResp)
      } catch (e) {
        if (cancelado) return
        setExtratoCotista(null)
        if (e instanceof DOMException && e.name === 'AbortError') {
          setErroExtrato(
            'Tempo esgotado (2 min). O servidor pode estar ocupado com a atualização da série — aguarde terminar ou use o backend local.',
          )
        } else {
          setErroExtrato(e instanceof Error ? e.message : 'Erro de rede')
        }
      } finally {
        window.clearTimeout(timer)
        if (!cancelado) setCarregandoExtrato(false)
      }
    }
    void carregarExtrato()
    return () => {
      cancelado = true
      ctrl.abort()
      window.clearTimeout(timer)
    }
  }, [dataBase, cotistaId, classeIdsParam, aba])

  const graficoExtratoCotista = useMemo(() => {
    if (!extratoCotista?.serie?.length) return []
    const comMovimento = extratoCotista.serie.filter(
      (p) => p.aporte > 0 || p.amortizacao > 0 || p.juros > 0,
    )
    const step = Math.max(1, Math.floor(extratoCotista.serie.length / 100))
    const amostra = extratoCotista.serie.filter(
      (_, i) => i % step === 0 || i === extratoCotista.serie.length - 1,
    )
    const datasAmostra = new Set(amostra.map((p) => p.data))
    for (const p of comMovimento) {
      datasAmostra.add(p.data)
    }
    return extratoCotista.serie.filter((p) => datasAmostra.has(p.data))
  }, [extratoCotista])

  function alternarClasseFiltro(id: number) {
    setClassesFiltro((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function selecionarTodasClasses() {
    setClassesFiltro(new Set())
  }

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
          <h1>Passivo — {dataBase || '…'}</h1>
          {dados?.dt_ref_pl_br && dados.dt_ref_pl_br !== dataBase && (
            <p className="subtitulo">PL IDSF em {dados.dt_ref_pl_br}</p>
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
          {dados?.subordinacao_pct != null && (
            <div className="painel-totais">
              <div className="painel-total">
                <span>Subordinação</span>
                <strong>{Number(dados.subordinacao_pct).toFixed(2)}%</strong>
              </div>
              <div className="painel-total">
                <span>PL motor</span>
                <strong>{formatarMoeda(dados.pl_consolidado)}</strong>
              </div>
            </div>
          )}
        </div>
      </header>

      <nav className="abas-passivo" aria-label="Seções do passivo">
        {(
          [
            ['classes', 'Classes'],
            ['vencimentos', 'Vencimentos'],
            ['cotista', 'Posição do cotista'],
            ['extrato-cotista', 'Extrato cotista'],
          ] as const
        ).map(([id, rotulo]) => (
          <button
            key={id}
            type="button"
            className={aba === id ? 'aba ativa' : 'aba'}
            onClick={() => setAba(id)}
          >
            {rotulo}
          </button>
        ))}
      </nav>

      {!dataBase && <p className="vazio">Carregando datas disponíveis…</p>}
      {carregando && <p className="vazio">Carregando passivo…</p>}
      {erro && <div className="banner-status banner-data">{erro}</div>}
      {dados?.aviso && <p className="aviso-inline">{dados.aviso}</p>}

      {aba === 'classes' && !carregando && dados && (
        <section className="painel">
          <table className="tabela-passivo">
            <thead>
              <tr>
                <th>Classe</th>
                <th>PL</th>
                <th>Qtd cotas</th>
                <th>Taxa</th>
                <th>Valor cota (app)</th>
                <th>Valor cota (IDSF)</th>
                <th>Δ cota</th>
                <th>Cotistas</th>
                <th>Vencimento</th>
              </tr>
            </thead>
            <tbody>
              {dados.classes.length === 0 ? (
                <tr>
                  <td colSpan={9} className="vazio">
                    Sem classes nesta data. Confira a carga de PL/PDD.
                  </td>
                </tr>
              ) : (
                dados.classes.map((c) => {
                  const status =
                    c.ok_marcacao == null
                      ? ''
                      : c.ok_marcacao
                        ? 'ok'
                        : 'divergente'
                  return (
                    <tr key={c.id_carteira} className={status ? `linha-marcacao-${status}` : ''}>
                      <td>
                        <strong>{c.nome}</strong>
                        <div className="muted-line">{c.apelido}</div>
                      </td>
                      <td>{formatarMoeda(c.pl)}</td>
                      <td>{formatarQtde(c.qtde_cotas)}</td>
                      <td>{formatarPctCdi(c.pct_cdi)}</td>
                      <td>{formatarCota(c.valor_cota_app)}</td>
                      <td>{formatarCota(c.valor_cota_idsf)}</td>
                      <td title={c.aviso_marcacao || undefined}>
                        {formatarDelta(c.delta_cota)}
                        {c.ok_marcacao === false && (
                          <span className="badge-divergencia"> divergente</span>
                        )}
                        {c.ok_marcacao === true && (
                          <span className="badge-ok"> ok</span>
                        )}
                      </td>
                      <td>{c.n_cotistas ?? '—'}</td>
                      <td>{c.vencimento ?? '—'}</td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </section>
      )}

      {aba === 'classes' && !carregando && dados?.conferencia_sub && (
        <section
          className={`painel conferencia-sub ${dados.conferencia_sub.ok ? 'ok' : 'divergente'}`}
        >
          <div className="painel-cabecalho">
            <div>
              <h2>Conferência da subordinada</h2>
            </div>
            <div className="painel-total">
              <span>Status</span>
              <strong>
                {dados.conferencia_sub.ok ? 'ok' : 'divergente'}
              </strong>
            </div>
          </div>
          <div className="conferencia-sub-grid">
            <div className="painel-total">
              <span>PL fundo (motor)</span>
              <strong>{formatarMoeda(dados.conferencia_sub.pl_fundo)}</strong>
            </div>
            <div className="painel-total">
              <span>Passivo mez (VP)</span>
              <strong>{formatarMoeda(dados.conferencia_sub.passivo_mez)}</strong>
            </div>
            <div className="painel-total">
              <span>PL SUB calc</span>
              <strong>{formatarMoeda(dados.conferencia_sub.pl_sub_calc)}</strong>
            </div>
            <div className="painel-total">
              <span>PL SUB IDSF</span>
              <strong>{formatarMoeda(dados.conferencia_sub.pl_sub_idsf)}</strong>
            </div>
            <div className="painel-total">
              <span>Δ SUB</span>
              <strong>
                {(dados.conferencia_sub.delta ?? 0) > 0 ? '+' : ''}
                {formatarMoeda(dados.conferencia_sub.delta)}
              </strong>
            </div>
          </div>
        </section>
      )}

      {aba === 'vencimentos' && (
        <>
          {vencimentos?.kpis && (
            <div className="painel-totais passivo-kpis">
              <div className="painel-total">
                <span>Aplicado</span>
                <strong>{formatarMoeda(vencimentos.kpis.aplicado)}</strong>
              </div>
              <div className="painel-total">
                <span>VP remanescente</span>
                <strong>{formatarMoeda(vencimentos.kpis.vp)}</strong>
              </div>
              <div className="painel-total">
                <span>Cotistas</span>
                <strong>{vencimentos.kpis.n_cotistas}</strong>
              </div>
              <div className="painel-total">
                <span>Parcelas abertas</span>
                <strong>{vencimentos.kpis.n_parcelas_abertas}</strong>
              </div>
              <div className="painel-total">
                <span>Próximo venc.</span>
                <strong>
                  {vencimentos.kpis.proximo ?? '—'}
                  {vencimentos.kpis.proximo_valor != null && (
                    <span className="muted-line">
                      {formatarMoeda(vencimentos.kpis.proximo_valor)}
                    </span>
                  )}
                </strong>
              </div>
            </div>
          )}

          <section className="painel">
            <h2>Por classe</h2>
            <div className="tabela-scroll">
              <table className="tabela-passivo">
                <thead>
                  <tr>
                    <th>Classe</th>
                    <th>%CDI</th>
                    <th>Aplicado</th>
                    <th>VP</th>
                    <th>Cotistas</th>
                    <th>Chamadas</th>
                    <th>Parcelas abertas</th>
                    <th>Próximo</th>
                  </tr>
                </thead>
                <tbody>
                  {(vencimentos?.por_classe ?? []).length === 0 ? (
                    <tr>
                      <td colSpan={8} className="vazio">
                        Sem chamadas migradas. Rode o SQL e `migrar_passivo_alpha.py`.
                      </td>
                    </tr>
                  ) : (
                    vencimentos!.por_classe.map((c) => (
                      <tr key={c.classe_id}>
                        <td>{c.classe}</td>
                        <td>{formatarPctCdi(c.percentual_cdi)}</td>
                        <td>{formatarMoeda(c.aplicado)}</td>
                        <td>{formatarMoeda(c.vp)}</td>
                        <td>{c.n_cotistas}</td>
                        <td>{c.n_chamadas}</td>
                        <td>{c.n_parcelas_abertas}</td>
                        <td>{c.proximo ?? '—'}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section className="painel">
            <h2>Por data de vencimento</h2>
            <div className="tabela-scroll">
              <table className="tabela-passivo">
                <thead>
                  <tr>
                    <th>Data</th>
                    <th>Status</th>
                    <th>Parcelas</th>
                    <th>Aplicado</th>
                    <th>VP hoje</th>
                    <th>Valor na liquidação</th>
                  </tr>
                </thead>
                <tbody>
                  {(vencimentos?.por_data ?? []).map((d) => (
                    <tr key={d.data_iso} className={`status-parcela-${d.status}`}>
                      <td>{d.data}</td>
                      <td>{d.status}</td>
                      <td>{d.n}</td>
                      <td>{formatarMoeda(d.aplicado)}</td>
                      <td>{formatarMoeda(d.vp_hoje)}</td>
                      <td>{formatarMoeda(d.valor_liquidacao)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}

      {aba === 'cotista' && (
        <section className="painel">
          <div className="painel-cabecalho">
            <div>
              <h2>Posição do cotista</h2>
            </div>
            <label className="select-cotista">
              Cotista
              <select
                value={cotistaId === '' ? '' : String(cotistaId)}
                onChange={(e) =>
                  setCotistaId(e.target.value ? Number(e.target.value) : '')
                }
              >
                {cotistas.length === 0 && <option value="">Sem cotistas</option>}
                {cotistas.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.nome}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {posicao && (
            <>
              <div className="painel-totais passivo-kpis">
                <div className="painel-total">
                  <span>Aplicado</span>
                  <strong>{formatarMoeda(posicao.kpis.aplicado)}</strong>
                </div>
                <div className="painel-total">
                  <span>VP</span>
                  <strong>{formatarMoeda(posicao.kpis.vp)}</strong>
                </div>
                <div className="painel-total">
                  <span>Chamadas</span>
                  <strong>{posicao.kpis.n_chamadas}</strong>
                </div>
              </div>

              {posicao.por_classe.map((bloco) => (
                <div key={bloco.classe} className="bloco-classe-cotista">
                  <h3>{bloco.classe}</h3>
                  {bloco.chamadas.map((ch) => (
                    <div key={ch.chamada_id} className="chamada-detalhe">
                      <p className="subtitulo">
                        Chamada #{ch.numero} · prazo {ch.data_prazo} · aporte{' '}
                        {ch.data_aporte} · face {formatarMoeda(ch.valor_nominal)} · VP{' '}
                        {formatarMoeda(ch.valor_presente_remanescente)}
                      </p>
                      <table className="tabela-passivo">
                        <thead>
                          <tr>
                            <th>Parcela</th>
                            <th>Vencimento</th>
                            <th>Fração</th>
                            <th>Original</th>
                            <th>VP</th>
                            <th>Na liquidação</th>
                            <th>Status</th>
                          </tr>
                        </thead>
                        <tbody>
                          {ch.parcelas.map((p) => (
                            <tr
                              key={`${ch.chamada_id}-${p.ordem}`}
                              className={
                                p.liquidada
                                  ? 'status-parcela-liquidado'
                                  : 'status-parcela-aberto'
                              }
                            >
                              <td>{p.rotulo}</td>
                              <td>{p.data_vencimento}</td>
                              <td>{(p.fracao * 100).toFixed(0)}%</td>
                              <td>{formatarMoeda(p.valor_original)}</td>
                              <td>{formatarMoeda(p.valor_presente)}</td>
                              <td>{formatarMoeda(p.valor_na_liquidacao)}</td>
                              <td>{p.liquidada ? 'liquidada' : 'aberta'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ))}
                </div>
              ))}
              {posicao.por_classe.length === 0 && (
                <p className="vazio">Este cotista não tem chamadas abertas.</p>
              )}
            </>
          )}
        </section>
      )}

      {aba === 'extrato-cotista' && (
        <section className="painel">
          <div className="painel-cabecalho extrato-filtros">
            <div>
              <h2>Extrato cotista</h2>
              {extratoCotista?.inicio && (
                <p className="subtitulo">Desde {extratoCotista.inicio}</p>
              )}
            </div>
            <label className="select-cotista">
              Cotista
              <select
                value={cotistaId === '' ? '' : String(cotistaId)}
                onChange={(e) =>
                  setCotistaId(e.target.value ? Number(e.target.value) : '')
                }
              >
                {cotistas.length === 0 && <option value="">Sem cotistas</option>}
                {cotistas.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.nome}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {classesCadastro.length > 0 && (
            <div className="filtro-classes-cota">
              <span>Tipo de cota</span>
              <button type="button" className={classesFiltro.size === 0 ? 'ativo' : ''} onClick={selecionarTodasClasses}>
                Todas
              </button>
              {classesCadastro.map((c) => (
                <label key={c.id} className="check-classe-cota">
                  <input
                    type="checkbox"
                    checked={classesFiltro.size === 0 || classesFiltro.has(c.id)}
                    onChange={() => {
                      if (classesFiltro.size === 0) {
                        const todas = new Set(classesCadastro.map((x) => x.id))
                        todas.delete(c.id)
                        setClassesFiltro(todas)
                      } else {
                        alternarClasseFiltro(c.id)
                      }
                    }}
                  />
                  {c.nome}
                </label>
              ))}
            </div>
          )}

          {extratoCotista?.kpis && (
            <div className="painel-totais passivo-kpis">
              <div className="painel-total">
                <span>Saldo principal</span>
                <strong>{formatarMoeda(extratoCotista.kpis.saldo ?? extratoCotista.kpis.aplicado)}</strong>
              </div>
              <div className="painel-total">
                <span>VP (bruto)</span>
                <strong>{formatarMoeda(extratoCotista.kpis.vp)}</strong>
              </div>
              <div className="painel-total">
                <span>Total aportado</span>
                <strong>{formatarMoeda(extratoCotista.kpis.total_aportado ?? 0)}</strong>
              </div>
              <div className="painel-total">
                <span>Chamadas</span>
                <strong>{extratoCotista.kpis.n_chamadas}</strong>
              </div>
            </div>
          )}

          {carregandoExtrato && <p className="vazio">Calculando extrato (motor passivo)…</p>}
          {erroExtrato && <div className="banner-status banner-data">{erroExtrato}</div>}

          {!carregandoExtrato && graficoExtratoCotista.length > 0 && (
            <>
              <h3 className="extrato-serie-titulo">Evolução dia a dia</h3>
              <div className="chart-wrap chart-fluxo">
                <ComposedChart
                  responsive
                  width="100%"
                  height={360}
                  data={graficoExtratoCotista}
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
                    const row = payload?.[0]?.payload as PontoExtratoCotista | undefined
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
                <Bar
                  dataKey="aporte"
                  name="Aporte"
                  fill="#2d8a6e"
                  radius={[2, 2, 0, 0]}
                  barSize={6}
                  isAnimationActive={false}
                />
                <Bar
                  dataKey="amortizacao"
                  name="Amortização"
                  fill="#9e2a2b"
                  radius={[2, 2, 0, 0]}
                  barSize={6}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="vp"
                  name="VP (bruto)"
                  stroke="#1f6f8b"
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="saldo"
                  name="Saldo principal"
                  stroke="#64748b"
                  strokeWidth={1.5}
                  strokeDasharray="4 4"
                  dot={false}
                  isAnimationActive={false}
                />
              </ComposedChart>
              </div>

              {extratoCotista && extratoCotista.serie.length > 0 && (
                <div className="tabela-scroll extrato-serie-scroll">
                  <table className="tabela-passivo">
                    <thead>
                      <tr>
                        <th>Data</th>
                        <th>Saldo principal</th>
                        <th>VP (bruto)</th>
                        <th>Aporte</th>
                        <th>Amortização</th>
                        <th>Juros</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[...extratoCotista.serie]
                        .reverse()
                        .filter(
                          (row, i, arr) =>
                            i === 0 ||
                            row.saldo !== arr[i - 1]?.saldo ||
                            row.vp !== arr[i - 1]?.vp ||
                            row.aporte > 0 ||
                            row.amortizacao > 0 ||
                            row.juros > 0,
                        )
                        .map((row) => (
                        <tr key={row.data}>
                          <td>{row.data.split('-').reverse().join('/')}</td>
                          <td>{formatarMoeda(row.saldo)}</td>
                          <td>{formatarMoeda(row.vp)}</td>
                          <td>{row.aporte > 0 ? formatarMoeda(row.aporte) : '—'}</td>
                          <td>{row.amortizacao > 0 ? formatarMoeda(row.amortizacao) : '—'}</td>
                          <td>{row.juros > 0 ? formatarMoeda(row.juros) : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}

          {!carregandoExtrato && extratoCotista && extratoCotista.serie.length === 0 && (
            <p className="vazio">Sem chamadas para os filtros selecionados.</p>
          )}
        </section>
      )}
    </div>
  )
}

export default Passivo
