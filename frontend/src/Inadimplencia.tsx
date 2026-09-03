import { useEffect, useMemo, useState } from 'react'
import { CalendarioDataBase } from './CalendarioDataBase'
import type { DataBaseDetalhe } from './types'
import { API_BASE } from './types'
import './App.css'

type Celula = { valor: number; n: number }
type TotalEixo = { mes: string; valor: number; n: number; aquisicao?: number }
type CelulaVnp = {
  pct: number
  vnp: number
  vencimentos: number
  n: number
}
type TotalVnpLinha = {
  mes: string
  pct: number
  vnp: number
  vencimentos: number
  a_vencer: number
  aquisicao?: number
}
type TotalVnpColuna = {
  mes: string
  pct: number
  vnp: number
  vencimentos: number
}

type MatrizVnp = {
  linhas: string[]
  colunas: string[]
  labels_linha: string[]
  labels_coluna: string[]
  celulas: CelulaVnp[][]
  totais_linha: TotalVnpLinha[]
  totais_coluna: TotalVnpColuna[]
  total: {
    pct: number
    vnp: number
    vencimentos: number
    a_vencer: number
    aquisicao?: number
    n: number
  }
  max_pct: number
}

type RespostaInad = {
  data_base: string
  data_base_iso?: string
  linhas: string[]
  colunas: string[]
  labels_linha: string[]
  labels_coluna: string[]
  celulas: Celula[][]
  totais_linha: TotalEixo[]
  totais_coluna: TotalEixo[]
  total: {
    valor: number
    n: number
    face_consig: number
    n_consig: number
    pct: number
  }
  max_celula: number
  matriz_vnp?: MatrizVnp
  aviso?: string | null
}

const STORAGE_DATA_BASE = 'fidc_data_base'
const STORAGE_ANO = 'fidc_inad_ano'
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

export default function Inadimplencia() {
  const [dataBase, setDataBase] = useState(
    () => localStorage.getItem(STORAGE_DATA_BASE) || '',
  )
  const [datasDetalhe, setDatasDetalhe] = useState<DataBaseDetalhe[]>([])
  const [feriados, setFeriados] = useState<Map<string, string>>(new Map())
  const [mesCalendario, setMesCalendario] = useState(() => {
    const hoje = new Date()
    return { ano: hoje.getFullYear(), mes: hoje.getMonth() }
  })
  const [dados, setDados] = useState<RespostaInad | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [carregando, setCarregando] = useState(false)
  const [ano, setAno] = useState(() => localStorage.getItem(STORAGE_ANO) || '')

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
        const disponiveis = detalhe.filter((d) => d.status === 'ok' || d.conciliada || d.tem_liquidez)
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
          `${API_BASE}/fidc/inadimplencia?dataBase=${encodeURIComponent(dataBase)}`,
        )
        const json = await res.json()
        if (cancelado) return
        if (!res.ok) {
          setErro(json.detail || 'Falha ao carregar inadimplência.')
          setDados(null)
          return
        }
        setDados(json)
      } catch (err) {
        if (!cancelado) {
          setErro(
            err instanceof Error ? err.message : 'Falha ao carregar inadimplência.',
          )
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

  const anos = useMemo(() => {
    if (!dados) return []
    const set = new Set<string>()
    for (const m of dados.linhas) set.add(m.slice(0, 4))
    return [...set].sort()
  }, [dados])

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
    if (!dados || !ano) return null
    const idxLinhas = dados.linhas
      .map((m, i) => (ano === ANO_TODOS || m.startsWith(ano) ? i : -1))
      .filter((i) => i >= 0)
    const inicioCol = ano === ANO_TODOS ? (dados.colunas[0] ?? '') : `${ano}-01`
    const idxColunas = dados.colunas
      .map((m, i) => (ano === ANO_TODOS || m >= inicioCol ? i : -1))
      .filter((i) => i >= 0)

    let max = 0
    let totalValor = 0
    let totalN = 0
    const totaisLinha = idxLinhas.map((i) => {
      let valor = 0
      let n = 0
      for (const j of idxColunas) {
        const cel = dados.celulas[i]?.[j] ?? { valor: 0, n: 0 }
        valor += cel.valor
        n += cel.n
        if (cel.valor > max) max = cel.valor
      }
      totalValor += valor
      totalN += n
      return {
        valor,
        n,
        aquisicao: dados.totais_linha[i]?.aquisicao ?? 0,
      }
    })
    const totaisColuna = idxColunas.map((j) => {
      let valor = 0
      let n = 0
      for (const i of idxLinhas) {
        const cel = dados.celulas[i]?.[j] ?? { valor: 0, n: 0 }
        valor += cel.valor
        n += cel.n
      }
      return { valor, n }
    })
    const totalAquisicao = totaisLinha.reduce((s, t) => s + (t.aquisicao || 0), 0)

    return {
      idxLinhas,
      idxColunas,
      totaisLinha,
      totaisColuna,
      max,
      totalValor,
      totalN,
      totalAquisicao,
    }
  }, [dados, ano])

  const visaoVnp = useMemo(() => {
    const m = dados?.matriz_vnp
    if (!m || !ano) return null
    const idxLinhas = m.linhas
      .map((mes, i) => (ano === ANO_TODOS || mes.startsWith(ano) ? i : -1))
      .filter((i) => i >= 0)
    const inicioCol = ano === ANO_TODOS ? (m.colunas[0] ?? '') : `${ano}-01`
    const idxColunas = m.colunas
      .map((mes, i) => (ano === ANO_TODOS || mes >= inicioCol ? i : -1))
      .filter((i) => i >= 0)

    let max = 0
    const celulas = idxLinhas.map((i) => {
      let runV = 0
      let runVenc = 0
      return idxColunas.map((j) => {
        const cel = m.celulas[i]?.[j]
        runV += cel?.vnp ?? 0
        runVenc += cel?.vencimentos ?? 0
        const pct = runVenc > 0 ? (100 * runV) / runVenc : 0
        if (runVenc > 0 && pct > max) max = pct
        return { pct, vnp: runV, vencimentos: runVenc }
      })
    })

    let vnp = 0
    let vencimentos = 0
    let aVencer = 0
    let aquisicao = 0
    const totaisLinha = celulas.map((row, ri) => {
      const last = row.at(-1)
      const totOrig = m.totais_linha[idxLinhas[ri]]
      const av = totOrig?.a_vencer ?? 0
      const aq = totOrig?.aquisicao ?? 0
      vnp += last?.vnp ?? 0
      vencimentos += last?.vencimentos ?? 0
      aVencer += av
      aquisicao += aq
      return {
        pct: last?.pct ?? 0,
        vnp: last?.vnp ?? 0,
        vencimentos: last?.vencimentos ?? 0,
        a_vencer: av,
        aquisicao: aq,
      }
    })
    const totaisColuna = idxColunas.map((_, k) => {
      let v = 0
      let venc = 0
      for (const row of celulas) {
        v += row[k]?.vnp ?? 0
        venc += row[k]?.vencimentos ?? 0
      }
      return { pct: venc > 0 ? (100 * v) / venc : 0, vnp: v, vencimentos: venc }
    })

    return {
      idxLinhas,
      idxColunas,
      celulas,
      totaisLinha,
      totaisColuna,
      max,
      pct: vencimentos > 0 ? (100 * vnp) / vencimentos : 0,
      vnp,
      vencimentos,
      aVencer,
      aquisicao,
    }
  }, [dados, ano])

  function selecionarAno(proximo: string) {
    setAno(proximo)
    localStorage.setItem(STORAGE_ANO, proximo)
  }

  const max = visao?.max ?? 0

  return (
    <div className="dashboard inad-page">
      <header className="topbar">
        <div>
          <p className="eyebrow">Inadimplência · consignado privado</p>
          <h1>Vencidos por cessão — {dataBase || '…'}</h1>
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

      {!carregando && dados && dados.linhas.length === 0 && (
        <p className="vazio">Sem títulos de consignado privado nesta data.</p>
      )}

      {!carregando && dados?.matriz_vnp && dados.matriz_vnp.linhas.length > 0 && (
        <section className="painel">
          <div className="painel-cabecalho">
            <div>
              <h2>VNP / vencimentos</h2>
            </div>
            <div className="inad-escala" aria-hidden>
              <span>menor %</span>
              <span className="inad-escala-barra" />
              <span>maior %</span>
            </div>
          </div>
          {visaoVnp && visaoVnp.idxLinhas.length > 0 && visaoVnp.idxColunas.length > 0 ? (
            <div className="inad-matriz-scroll">
              <table className="inad-matriz inad-matriz-vnp">
                <thead>
                  <tr>
                    <th className="inad-canto">Cessão \\ Vencimento</th>
                    <th className="inad-total-col">Aquisição</th>
                    {visaoVnp.idxColunas.map((j) => (
                      <th key={dados.matriz_vnp!.colunas[j]}>
                        {dados.matriz_vnp!.labels_coluna[j]}
                      </th>
                    ))}
                    <th className="inad-total-col">% VNP</th>
                    <th className="inad-total-col">A vencer</th>
                  </tr>
                </thead>
                <tbody>
                  {visaoVnp.idxLinhas.map((i, ri) => {
                    const totL = visaoVnp.totaisLinha[ri]
                    const mv = dados.matriz_vnp!
                    return (
                      <tr key={mv.linhas[i]}>
                        <th>{mv.labels_linha[i]}</th>
                        <td
                          className="inad-total-cel"
                          title={`Aquisição ${formatarMoeda(totL?.aquisicao)}`}
                        >
                          {formatarMoedaCurta(totL?.aquisicao)}
                        </td>
                        {visaoVnp.idxColunas.map((j, k) => {
                          const cel = visaoVnp.celulas[ri]?.[k]
                          const tem = (cel?.vencimentos ?? 0) > 0
                          const { bg, fg } = corCelula(
                            tem ? cel!.pct : 0,
                            visaoVnp.max,
                          )
                          return (
                            <td
                              key={mv.colunas[j]}
                              style={{ background: bg, color: fg }}
                              title={
                                tem
                                  ? `${mv.labels_linha[i]} até ${mv.labels_coluna[j]}: ${formatarPct(cel!.pct)} · VNP acum. ${formatarMoeda(cel!.vnp)} / venc. ${formatarMoeda(cel!.vencimentos)}`
                                  : `${mv.labels_linha[i]} × ${mv.labels_coluna[j]}: sem vencimentos`
                              }
                            >
                              {tem ? formatarPct(cel!.pct) : ''}
                            </td>
                          )
                        })}
                        <td
                          className="inad-total-cel"
                          title={`VNP ${formatarMoeda(totL?.vnp)} / vencimentos ${formatarMoeda(totL?.vencimentos)}`}
                        >
                          {formatarPct(totL?.pct)}
                        </td>
                        <td className="inad-total-cel">
                          {formatarMoedaCurta(totL?.a_vencer)}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
                <tfoot>
                  <tr>
                    <th>Total</th>
                    <td
                      className="inad-total-cel inad-total-geral"
                      title={`Aquisição ${formatarMoeda(visaoVnp.aquisicao)}`}
                    >
                      {formatarMoedaCurta(visaoVnp.aquisicao)}
                    </td>
                    {visaoVnp.totaisColuna.map((tot, k) => (
                      <td
                        key={dados.matriz_vnp!.colunas[visaoVnp.idxColunas[k]]}
                        className="inad-total-cel"
                        title={`VNP ${formatarMoeda(tot.vnp)} / venc. ${formatarMoeda(tot.vencimentos)}`}
                      >
                        {tot.vencimentos > 0 ? formatarPct(tot.pct) : ''}
                      </td>
                    ))}
                    <td
                      className="inad-total-cel inad-total-geral"
                      title={`VNP ${formatarMoeda(visaoVnp.vnp)} / venc. ${formatarMoeda(visaoVnp.vencimentos)}`}
                    >
                      {formatarPct(visaoVnp.pct)}
                    </td>
                    <td className="inad-total-cel inad-total-geral">
                      {formatarMoedaCurta(visaoVnp.aVencer)}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          ) : (
            <p className="vazio">Sem vencimentos neste recorte.</p>
          )}
        </section>
      )}

      {!carregando && dados && dados.linhas.length > 0 && (
        <section className="painel">
          <div className="painel-cabecalho">
            <div>
              <h2>Matriz de vencidos</h2>
            </div>
            <div className="inad-escala" aria-hidden>
              <span>menor</span>
              <span className="inad-escala-barra" />
              <span>maior</span>
            </div>
          </div>
          {visao && visao.idxLinhas.length > 0 && visao.idxColunas.length > 0 ? (
          <div className="inad-matriz-scroll">
            <table className="inad-matriz">
              <thead>
                <tr>
                  <th className="inad-canto">Cessão \\ Vencido</th>
                  <th className="inad-total-col">Aquisição</th>
                  {visao.idxColunas.map((j) => (
                    <th key={dados.colunas[j]}>{dados.labels_coluna[j]}</th>
                  ))}
                  <th className="inad-total-col">Total</th>
                </tr>
              </thead>
              <tbody>
                {visao.idxLinhas.map((i, ri) => {
                  const totL = visao.totaisLinha[ri]
                  return (
                    <tr key={dados.linhas[i]}>
                      <th>{dados.labels_linha[i]}</th>
                      <td
                        className="inad-total-cel"
                        title={`Aquisição ${formatarMoeda(totL?.aquisicao)}`}
                      >
                        {formatarMoedaCurta(totL?.aquisicao)}
                      </td>
                      {visao.idxColunas.map((j) => {
                        const cel = dados.celulas[i]?.[j] ?? { valor: 0, n: 0 }
                        const { bg, fg } = corCelula(cel.valor, max)
                        return (
                          <td
                            key={dados.colunas[j]}
                            style={{ background: bg, color: fg }}
                            title={`${dados.labels_linha[i]} × ${dados.labels_coluna[j]}: ${formatarMoeda(cel.valor)} (${cel.n} títulos)`}
                          >
                            {formatarMoedaCurta(cel.valor)}
                          </td>
                        )
                      })}
                      <td className="inad-total-cel">
                        {formatarMoedaCurta(totL?.valor)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
              <tfoot>
                <tr>
                  <th>Total</th>
                  <td
                    className="inad-total-cel inad-total-geral"
                    title={`Aquisição ${formatarMoeda(visao.totalAquisicao)}`}
                  >
                    {formatarMoedaCurta(visao.totalAquisicao)}
                  </td>
                  {visao.totaisColuna.map((tot, k) => (
                    <td key={dados.colunas[visao.idxColunas[k]]} className="inad-total-cel">
                      {formatarMoedaCurta(tot.valor)}
                    </td>
                  ))}
                  <td className="inad-total-cel inad-total-geral">
                    {formatarMoedaCurta(visao.totalValor)}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
          ) : (
            <p className="vazio">Sem vencidos neste ano.</p>
          )}
        </section>
      )}
    </div>
  )
}
