import { useEffect, useMemo, useState } from 'react'
import { CalendarioDataBase } from './CalendarioDataBase'
import type { DataBaseDetalhe } from './types'
import { API_BASE } from './types'
import './App.css'

type TituloVenc = {
  documento: string
  cedente: string
  sacado: string
  tipo: string
  status: string
  data_vencimento: string
  data_vencimento_iso: string
  face: number
  vp: number
  pdd: number
}

type DiaVenc = {
  data: string
  data_iso: string
  n: number
  face: number
  vp: number
  pdd: number
}

type RespostaVenc = {
  data_base: string
  data_base_iso: string
  inicio: string
  inicio_iso: string
  fim: string
  fim_iso: string
  totais: { n: number; face: number; vp: number; pdd: number }
  por_data: DiaVenc[]
  titulos: TituloVenc[]
}

const STORAGE_DATA_BASE = 'fidc_data_base'

function formatarMoeda(valor: number | null | undefined): string {
  return Number(valor ?? 0).toLocaleString('pt-BR', {
    style: 'currency',
    currency: 'BRL',
    maximumFractionDigits: 2,
  })
}

function isoDeBr(data: string): string {
  const m = data.match(/^(\d{2})\/(\d{2})\/(\d{4})$/)
  if (!m) return ''
  return `${m[3]}-${m[2]}-${m[1]}`
}

function somarDiasIso(iso: string, dias: number): string {
  const d = new Date(`${iso}T12:00:00`)
  if (Number.isNaN(d.getTime())) return iso
  d.setDate(d.getDate() + dias)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function Vencimentos() {
  const [dataBase, setDataBase] = useState(
    () => localStorage.getItem(STORAGE_DATA_BASE) || '',
  )
  const [datasDetalhe, setDatasDetalhe] = useState<DataBaseDetalhe[]>([])
  const [feriados, setFeriados] = useState<Map<string, string>>(new Map())
  const [mesCalendario, setMesCalendario] = useState(() => {
    const hoje = new Date()
    return { ano: hoje.getFullYear(), mes: hoje.getMonth() }
  })
  const [inicio, setInicio] = useState('')
  const [fim, setFim] = useState('')
  const [busca, setBusca] = useState('')
  const [dados, setDados] = useState<RespostaVenc | null>(null)
  const [carregando, setCarregando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)

  const mapaDatas = useMemo(
    () => new Map(datasDetalhe.map((d) => [d.data_iso, d])),
    [datasDetalhe],
  )
  const dataSelecionada = datasDetalhe.find((d) => d.data === dataBase)

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
        const disponiveis = detalhe.filter((d) => d.status === 'ok' || d.conciliada)
        const ultima = (disponiveis.length ? disponiveis : detalhe).at(-1) ?? null
        setDataBase((atual) => {
          if (atual && detalhe.some((d) => d.data === atual)) return atual
          const salvo = localStorage.getItem(STORAGE_DATA_BASE) || ''
          if (salvo && detalhe.some((d) => d.data === salvo && (d.status === 'ok' || d.conciliada))) {
            return salvo
          }
          const proxima = ultima?.data ?? ''
          if (proxima) localStorage.setItem(STORAGE_DATA_BASE, proxima)
          return proxima
        })
        if (ultima?.data_iso) {
          const [y, m] = ultima.data_iso.split('-').map(Number)
          setMesCalendario({ ano: y, mes: m - 1 })
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
    const iso = isoDeBr(dataBase)
    if (!iso) return
    setInicio((atual) => atual || iso)
    setFim((atual) => atual || somarDiasIso(iso, 90))
  }, [dataBase])

  useEffect(() => {
    if (!dataBase || !inicio || !fim) return
    let cancelado = false
    async function carregar() {
      setCarregando(true)
      setErro(null)
      try {
        const qs = new URLSearchParams({
          dataBase,
          inicio,
          fim,
        })
        const res = await fetch(`${API_BASE}/fidc/vencimentos?${qs}`)
        const json = await res.json()
        if (cancelado) return
        if (!res.ok) {
          setErro(json.detail || 'Falha ao carregar vencimentos.')
          setDados(null)
          return
        }
        setDados(json)
      } catch (err) {
        if (!cancelado) {
          setErro(err instanceof Error ? err.message : 'Falha ao carregar vencimentos.')
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
  }, [dataBase, inicio, fim])

  function selecionarData(data: string) {
    setDataBase(data)
    localStorage.setItem(STORAGE_DATA_BASE, data)
    const iso = isoDeBr(data)
    if (iso) {
      setInicio(iso)
      setFim(somarDiasIso(iso, 90))
    }
  }

  const termo = busca.trim().toLowerCase()
  const titulos = useMemo(() => {
    const lista = dados?.titulos ?? []
    if (!termo) return lista
    return lista.filter((t) => {
      const blob = `${t.documento} ${t.cedente} ${t.sacado} ${t.status}`.toLowerCase()
      return blob.includes(termo)
    })
  }, [dados, termo])

  return (
    <div className="dashboard">
      <header className="topbar">
        <div>
          <p className="eyebrow">Carteira · títulos abertos na data base</p>
          <h1>Vencimentos — {dataBase || '…'}</h1>
          {dados && (
            <p className="subtitulo">
              Vencimento de {dados.inicio} a {dados.fim}
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
            Vencimento de
            <input
              type="date"
              value={inicio}
              onChange={(e) => setInicio(e.target.value)}
            />
          </label>
          <label className="select-cotista">
            até
            <input
              type="date"
              value={fim}
              onChange={(e) => setFim(e.target.value)}
            />
          </label>
          <label className="select-cotista">
            Busca
            <input
              type="search"
              className="extrato-busca-sacado"
              placeholder="Sacado, cedente ou documento…"
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
              autoComplete="off"
            />
          </label>
        </div>

        {dados?.totais && (
          <div className="painel-totais passivo-kpis extrato-kpis">
            <div className="painel-total">
              <span>Títulos</span>
              <strong>{dados.totais.n.toLocaleString('pt-BR')}</strong>
            </div>
            <div className="painel-total">
              <span>Face</span>
              <strong>{formatarMoeda(dados.totais.face)}</strong>
            </div>
            <div className="painel-total">
              <span>VP</span>
              <strong>{formatarMoeda(dados.totais.vp)}</strong>
            </div>
            <div className="painel-total">
              <span>PDD</span>
              <strong>{formatarMoeda(dados.totais.pdd)}</strong>
            </div>
          </div>
        )}
      </section>

      {carregando && <p className="vazio">Carregando carteira da data base…</p>}
      {erro && <div className="banner-status banner-data">{erro}</div>}

      {!carregando && dados && (
        <section className="painel">
          <div className="painel-cabecalho">
            <h2>Por data de vencimento</h2>
          </div>
          <div className="tabela-scroll">
            <table className="tabela-passivo">
              <thead>
                <tr>
                  <th>Vencimento</th>
                  <th>Títulos</th>
                  <th>Face</th>
                  <th>VP</th>
                  <th>PDD</th>
                </tr>
              </thead>
              <tbody>
                {(dados.por_data ?? []).map((d) => (
                  <tr key={d.data_iso}>
                    <td>{d.data}</td>
                    <td>{d.n.toLocaleString('pt-BR')}</td>
                    <td>{formatarMoeda(d.face)}</td>
                    <td>{formatarMoeda(d.vp)}</td>
                    <td>{formatarMoeda(d.pdd)}</td>
                  </tr>
                ))}
                {(dados.por_data ?? []).length === 0 && (
                  <tr>
                    <td colSpan={5}>Nenhum vencimento no intervalo.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {!carregando && dados && (
        <section className="painel">
          <div className="painel-cabecalho">
            <h2>Títulos</h2>
            {termo && (
              <p className="subtitulo">
                {titulos.length} de {dados.titulos.length}
              </p>
            )}
          </div>
          <div className="tabela-scroll extrato-serie-scroll">
            <table className="tabela-passivo">
              <thead>
                <tr>
                  <th>Vencimento</th>
                  <th>Sacado</th>
                  <th>Cedente</th>
                  <th>Documento</th>
                  <th>Status</th>
                  <th>Face</th>
                  <th>VP</th>
                  <th>PDD</th>
                </tr>
              </thead>
              <tbody>
                {titulos.map((t, i) => (
                  <tr key={`${t.documento}-${t.data_vencimento_iso}-${i}`}>
                    <td>{t.data_vencimento}</td>
                    <td>{t.sacado || '—'}</td>
                    <td>{t.cedente || '—'}</td>
                    <td>{t.documento || '—'}</td>
                    <td>{t.status || '—'}</td>
                    <td>{formatarMoeda(t.face)}</td>
                    <td>{formatarMoeda(t.vp)}</td>
                    <td>{formatarMoeda(t.pdd)}</td>
                  </tr>
                ))}
                {titulos.length === 0 && (
                  <tr>
                    <td colSpan={8}>Nenhum título no filtro.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}

export default Vencimentos
