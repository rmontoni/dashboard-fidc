import { useEffect, useMemo, useState } from 'react'
import { API_BASE } from './types'

type DiaDivergencia = {
  data: string
  data_iso: string
  n_titulos: number
  vp_motor: number
  pdd_motor: number
  vp_idsf: number
  pdd_idsf: number
  delta_vp: number
  delta_pdd: number
  delta_vp_limpo: number
  delta_pdd_limpo: number
  tem_estoque_bdr: boolean
  excecao_residuos?: boolean
}

type TituloDiv = {
  documento: string
  sacado: string
  vencimento?: string
  vp_motor: number
  vp_bdr: number
  delta_vp: number
  pdd_motor: number
  pdd_bdr: number
  delta_pdd: number
  fx_motor: string
  fx_bdr: string
}

type DetalheDiv = {
  data: string
  data_iso: string
  tolerancia: number
  acima_tolerancia: boolean
  resumo: {
    motor: { n: number; vp: number; pdd: number; face: number }
    idsf: { vp: number; pdd: number; fonte?: string | null }
    bdr: {
      disponivel: boolean
      n?: number
      vp?: number
      pdd?: number
      face?: number
      arquivo?: string | null
    }
    delta_motor_idsf: { vp: number; pdd: number }
    delta_motor_bdr: { vp: number; pdd: number } | null
    delta_bdr_idsf: { vp: number; pdd: number } | null
  }
  titulos: TituloDiv[]
  so_motor: { documento: string; sacado: string; vp_motor: number }[]
  so_bdr: { documento: string; vp_bdr: number }[]
  n_titulos_divergentes: number
  n_so_motor: number
  n_so_bdr: number
}

function brl(n: number | null | undefined) {
  if (n == null || Number.isNaN(n)) return '—'
  return n.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

function sinal(n: number) {
  const cls = Math.abs(n) < 0.005 ? '' : n > 0 ? 'delta-pos' : 'delta-neg'
  const txt = n.toLocaleString('pt-BR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
  return <span className={cls}>{n > 0 ? `+${txt}` : txt}</span>
}

export default function Divergencias() {
  const [dias, setDias] = useState<DiaDivergencia[]>([])
  const [tol, setTol] = useState(500)
  const [dataSel, setDataSel] = useState('')
  const [detalhe, setDetalhe] = useState<DetalheDiv | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [carregandoLista, setCarregandoLista] = useState(false)
  const [carregandoDetalhe, setCarregandoDetalhe] = useState(false)

  const mapaDias = useMemo(() => {
    const m = new Map<string, DiaDivergencia>()
    for (const d of dias) m.set(d.data_iso, d)
    return m
  }, [dias])

  useEffect(() => {
    let cancelado = false
    async function carregar() {
      setCarregandoLista(true)
      setErro(null)
      try {
        const res = await fetch(`${API_BASE}/fidc/divergencias`)
        if (!res.ok) {
          const body = await res.json().catch(() => ({}))
          throw new Error(body.detail || `HTTP ${res.status}`)
        }
        const dados = await res.json()
        if (cancelado) return
        const lista: DiaDivergencia[] = dados.dias ?? []
        setDias(lista)
        setTol(Number(dados.tolerancia) || 500)
        if (lista.length > 0) {
          setDataSel((atual) => {
            if (atual && lista.some((d) => d.data_iso === atual)) return atual
            return lista[lista.length - 1].data_iso
          })
        }
      } catch (e) {
        if (!cancelado) {
          setErro(e instanceof Error ? e.message : 'Falha ao carregar divergências')
        }
      } finally {
        if (!cancelado) setCarregandoLista(false)
      }
    }
    void carregar()
    return () => {
      cancelado = true
    }
  }, [])

  useEffect(() => {
    if (!dataSel) {
      setDetalhe(null)
      return
    }
    let cancelado = false
    async function carregarDetalhe() {
      setCarregandoDetalhe(true)
      setErro(null)
      try {
        const dia = mapaDias.get(dataSel)
        const dataBase = dia?.data ?? dataSel
        const res = await fetch(
          `${API_BASE}/fidc/divergencias/detalhe?dataBase=${encodeURIComponent(dataBase)}`,
        )
        if (!res.ok) {
          const body = await res.json().catch(() => ({}))
          throw new Error(body.detail || `HTTP ${res.status}`)
        }
        const dados = await res.json()
        if (!cancelado) setDetalhe(dados)
      } catch (e) {
        if (!cancelado) {
          setDetalhe(null)
          setErro(e instanceof Error ? e.message : 'Falha ao carregar detalhe')
        }
      } finally {
        if (!cancelado) setCarregandoDetalhe(false)
      }
    }
    void carregarDetalhe()
    return () => {
      cancelado = true
    }
  }, [dataSel, mapaDias])

  const resumoLista = mapaDias.get(dataSel)

  return (
    <div className="divergencias-page">
      <header className="topo">
        <div>
          <p className="eyebrow">Controles</p>
          <h1>Divergências</h1>
          <p className="subtitulo">
            Motor × BDR × IDSF — apenas dias com diferença acima de {brl(tol)}
          </p>
        </div>
        <label className="filtro-dia">
          <span>Data</span>
          <select
            value={dataSel}
            onChange={(e) => setDataSel(e.target.value)}
            disabled={dias.length === 0}
          >
            {dias.length === 0 && <option value="">Nenhuma divergência</option>}
            {[...dias].reverse().map((d) => (
              <option key={d.data_iso} value={d.data_iso}>
                {d.data} · ΔVP {d.delta_vp_limpo >= 0 ? '+' : ''}
                {d.delta_vp_limpo.toFixed(2)} · ΔPDD{' '}
                {d.delta_pdd_limpo >= 0 ? '+' : ''}
                {d.delta_pdd_limpo.toFixed(2)}
              </option>
            ))}
          </select>
        </label>
      </header>

      {erro && <p className="aviso-erro">{erro}</p>}
      {carregandoLista && <p className="muted">Carregando lista…</p>}

      {!carregandoLista && dias.length === 0 && !erro && (
        <p className="aviso-ok">
          Nenhuma divergência acima da tolerância na série diária.
        </p>
      )}

      {resumoLista && (
        <section className="div-cards">
          <article className="div-card">
            <span>ΔVP limpo (motor − IDSF)</span>
            <strong>{sinal(resumoLista.delta_vp_limpo)}</strong>
          </article>
          <article className="div-card">
            <span>ΔPDD limpo (motor − IDSF)</span>
            <strong>{sinal(resumoLista.delta_pdd_limpo)}</strong>
          </article>
          <article className="div-card">
            <span>Estoque BDR do dia</span>
            <strong>{resumoLista.tem_estoque_bdr ? 'Disponível' : 'Sem CSV'}</strong>
          </article>
          <article className="div-card">
            <span>Títulos (motor)</span>
            <strong>{resumoLista.n_titulos.toLocaleString('pt-BR')}</strong>
          </article>
        </section>
      )}

      {carregandoDetalhe && <p className="muted">Calculando detalhe do dia…</p>}

      {detalhe && !carregandoDetalhe && (
        <>
          <section className="painel">
            <div className="painel-cabecalho">
              <h2>Totais — {detalhe.data}</h2>
              <p className="subtitulo">
                {detalhe.acima_tolerancia
                  ? 'Acima da tolerância'
                  : 'Dentro da tolerância no detalhe'}
              </p>
            </div>
            <div className="div-tabela-wrap">
              <table className="tabela-div">
                <thead>
                  <tr>
                    <th>Fonte</th>
                    <th>Títulos</th>
                    <th>VP / DC</th>
                    <th>PDD</th>
                    <th>ΔVP vs motor</th>
                    <th>ΔPDD vs motor</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>Motor</td>
                    <td>{detalhe.resumo.motor.n.toLocaleString('pt-BR')}</td>
                    <td>{brl(detalhe.resumo.motor.vp)}</td>
                    <td>{brl(detalhe.resumo.motor.pdd)}</td>
                    <td>—</td>
                    <td>—</td>
                  </tr>
                  <tr>
                    <td>IDSF</td>
                    <td>—</td>
                    <td>{brl(detalhe.resumo.idsf.vp)}</td>
                    <td>{brl(detalhe.resumo.idsf.pdd)}</td>
                    <td>{sinal(detalhe.resumo.delta_motor_idsf.vp)}</td>
                    <td>{sinal(detalhe.resumo.delta_motor_idsf.pdd)}</td>
                  </tr>
                  <tr>
                    <td>
                      BDR
                      {!detalhe.resumo.bdr.disponivel && (
                        <small className="muted"> (sem estoque)</small>
                      )}
                    </td>
                    <td>
                      {detalhe.resumo.bdr.disponivel
                        ? (detalhe.resumo.bdr.n ?? 0).toLocaleString('pt-BR')
                        : '—'}
                    </td>
                    <td>
                      {detalhe.resumo.bdr.disponivel
                        ? brl(detalhe.resumo.bdr.vp)
                        : '—'}
                    </td>
                    <td>
                      {detalhe.resumo.bdr.disponivel
                        ? brl(detalhe.resumo.bdr.pdd)
                        : '—'}
                    </td>
                    <td>
                      {detalhe.resumo.delta_motor_bdr
                        ? sinal(detalhe.resumo.delta_motor_bdr.vp)
                        : '—'}
                    </td>
                    <td>
                      {detalhe.resumo.delta_motor_bdr
                        ? sinal(detalhe.resumo.delta_motor_bdr.pdd)
                        : '—'}
                    </td>
                  </tr>
                  {detalhe.resumo.delta_bdr_idsf && (
                    <tr className="linha-secundaria">
                      <td colSpan={4}>BDR − IDSF</td>
                      <td>{sinal(detalhe.resumo.delta_bdr_idsf.vp)}</td>
                      <td>{sinal(detalhe.resumo.delta_bdr_idsf.pdd)}</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          {detalhe.resumo.bdr.disponivel && (
            <section className="painel">
              <div className="painel-cabecalho">
                <h2>Títulos divergentes (motor × BDR)</h2>
                <p className="subtitulo">
                  {detalhe.n_titulos_divergentes} com |Δ| ≥ R$ 0,01
                  {detalhe.n_so_motor > 0 &&
                    ` · ${detalhe.n_so_motor} só no motor`}
                  {detalhe.n_so_bdr > 0 && ` · ${detalhe.n_so_bdr} só na BDR`}
                </p>
              </div>
              <div className="div-tabela-wrap">
                <table className="tabela-div tabela-titulos-div">
                  <thead>
                    <tr>
                      <th>Documento</th>
                      <th>Sacado</th>
                      <th>Faixa</th>
                      <th>VP motor</th>
                      <th>VP BDR</th>
                      <th>ΔVP</th>
                      <th>ΔPDD</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detalhe.titulos.length === 0 && (
                      <tr>
                        <td colSpan={7} className="muted">
                          Sem diferença título a título ≥ R$ 0,01
                        </td>
                      </tr>
                    )}
                    {detalhe.titulos.map((t) => (
                      <tr key={t.documento}>
                        <td>{t.documento}</td>
                        <td>{t.sacado}</td>
                        <td>
                          {t.fx_motor}
                          {t.fx_bdr && t.fx_bdr !== t.fx_motor
                            ? ` / ${t.fx_bdr}`
                            : ''}
                        </td>
                        <td>{brl(t.vp_motor)}</td>
                        <td>{brl(t.vp_bdr)}</td>
                        <td>{sinal(t.delta_vp)}</td>
                        <td>{sinal(t.delta_pdd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <section className="painel">
            <div className="painel-cabecalho">
              <h2>Histórico de dias fora da tolerância</h2>
              <p className="subtitulo">{dias.length} dia(s)</p>
            </div>
            <div className="div-tabela-wrap">
              <table className="tabela-div">
                <thead>
                  <tr>
                    <th>Data</th>
                    <th>ΔVP limpo</th>
                    <th>ΔPDD limpo</th>
                    <th>VP motor</th>
                    <th>VP IDSF</th>
                    <th>BDR</th>
                  </tr>
                </thead>
                <tbody>
                  {[...dias].reverse().map((d) => (
                    <tr
                      key={d.data_iso}
                      className={d.data_iso === dataSel ? 'linha-ativa' : ''}
                      onClick={() => setDataSel(d.data_iso)}
                    >
                      <td>{d.data}</td>
                      <td>{sinal(d.delta_vp_limpo)}</td>
                      <td>{sinal(d.delta_pdd_limpo)}</td>
                      <td>{brl(d.vp_motor)}</td>
                      <td>{brl(d.vp_idsf)}</td>
                      <td>{d.tem_estoque_bdr ? 'sim' : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  )
}
