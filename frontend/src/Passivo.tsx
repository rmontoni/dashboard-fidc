import { useEffect, useState } from 'react'
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
  passivo_mez_app?: number
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
        const res = await fetch(
          `${API_BASE}/fidc/passivo?dataBase=${encodeURIComponent(dataBase)}`,
        )
        const json = await res.json()
        if (cancelado) return
        if (!res.ok) {
          setErro(
            typeof json.detail === 'string'
              ? json.detail
              : 'Falha ao carregar passivo.',
          )
          setDados(null)
          return
        }
        setDados(json as RespostaPassivo)
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
          <p className="eyebrow">Passivo · emissão de cotas</p>
          <h1>Classes — {dataBase || '…'}</h1>
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

      {!dataBase && <p className="vazio">Carregando datas disponíveis…</p>}
      {carregando && <p className="vazio">Carregando passivo…</p>}
      {erro && <div className="banner-status banner-data">{erro}</div>}
      {dados?.aviso && <p className="aviso-inline">{dados.aviso}</p>}

      {!carregando && dados?.conferencia_sub && (
        <section
          className={`painel conferencia-sub ${dados.conferencia_sub.ok ? 'ok' : 'divergente'}`}
        >
          <div className="painel-cabecalho">
            <div>
              <h2>Conferência da subordinada</h2>
              <p className="subtitulo">
                PL do motor − PL das cotas mezanino = PL da subordinada
              </p>
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
              <span>Passivo mez</span>
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
          {dados.conferencia_sub.delta_via_app != null && (
            <p className="subtitulo conferencia-sub-nota">
              Com cota app das mez: PL SUB {formatarMoeda(dados.conferencia_sub.pl_sub_via_app)}{' '}
              (Δ {(dados.conferencia_sub.delta_via_app ?? 0) > 0 ? '+' : ''}
              {formatarMoeda(dados.conferencia_sub.delta_via_app)} vs IDSF) — residual da marcação I/II.
            </p>
          )}
        </section>
      )}

      {!carregando && dados && (
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
          <p className="subtitulo passivo-nota">
            Cota (app) nas mez = CotaInicial × fatores diários %CDI (BCB), abatendo
            Amortização+Juros / qtde em cada data de distribuição. Δ = app − IDSF.
            SUB usa PL ÷ quantidade.
          </p>
        </section>
      )}
    </div>
  )
}

export default Passivo
