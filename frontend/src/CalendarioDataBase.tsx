import { useEffect, useRef, useState } from 'react'
import type { DataBaseDetalhe } from './types'

function rotuloMesNome(mes: number): string {
  return new Date(2000, mes, 1).toLocaleDateString('pt-BR', { month: 'long' })
}

const MESES_PT = Array.from({ length: 12 }, (_, i) => ({
  valor: i,
  nome: rotuloMesNome(i),
}))

export function CalendarioDataBase({
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
