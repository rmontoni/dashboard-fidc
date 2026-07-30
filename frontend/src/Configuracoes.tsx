import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import type { Fundo } from './types'
import { API_BASE } from './types'

const FUNDO_VAZIO = {
  codigo: '',
  nome: '',
  cnpj: '',
  data_inicio: '',
  idsf_carteiras: '',
  tabela_estoque: 'BD_Estoque',
  bdr_tp_contabil_estoque: 'P',
  bdr_tp_contabil_mov: 'A',
  ativo: true,
  observacao: '',
}

type ConfiguracoesProps = {
  fundoSelecionadoId: number | null
  onSelecionarFundo: (fundo: Fundo) => void
}

export default function Configuracoes({
  fundoSelecionadoId,
  onSelecionarFundo,
}: ConfiguracoesProps) {
  const [fundos, setFundos] = useState<Fundo[]>([])
  const [erro, setErro] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [carregando, setCarregando] = useState(false)
  const [editandoId, setEditandoId] = useState<number | null>(null)
  const [form, setForm] = useState({ ...FUNDO_VAZIO })

  async function carregar() {
    setErro(null)
    setCarregando(true)
    try {
      const res = await fetch(`${API_BASE}/fidc/fundos`)
      if (!res.ok) {
        const detalhe = await res.json().catch(() => ({}))
        throw new Error(detalhe.detail || `HTTP ${res.status}`)
      }
      const dados = await res.json()
      const lista: Fundo[] = dados.fundos ?? []
      setFundos(lista)
      if (lista.length > 0 && fundoSelecionadoId == null) {
        onSelecionarFundo(lista.find((f) => f.ativo) ?? lista[0])
      }
    } catch (e) {
      setErro(
        e instanceof Error
          ? e.message
          : 'Falha ao carregar fundos. Confirme se o SQL fidc_fundos.sql foi executado.',
      )
    } finally {
      setCarregando(false)
    }
  }

  useEffect(() => {
    void carregar()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function iniciarNovo() {
    setEditandoId(null)
    setForm({ ...FUNDO_VAZIO })
    setOk(null)
    setErro(null)
  }

  function iniciarEdicao(fundo: Fundo) {
    setEditandoId(fundo.id)
    setForm({
      codigo: fundo.codigo,
      nome: fundo.nome,
      cnpj: fundo.cnpj,
      data_inicio: fundo.data_inicio ?? '',
      idsf_carteiras: fundo.idsf_carteiras ?? '',
      tabela_estoque: fundo.tabela_estoque || 'BD_Estoque',
      bdr_tp_contabil_estoque: fundo.bdr_tp_contabil_estoque || 'P',
      bdr_tp_contabil_mov: fundo.bdr_tp_contabil_mov || 'A',
      ativo: fundo.ativo,
      observacao: fundo.observacao ?? '',
    })
    setOk(null)
    setErro(null)
  }

  async function salvar(e: FormEvent) {
    e.preventDefault()
    setErro(null)
    setOk(null)
    setCarregando(true)
    try {
      const payload = {
        ...form,
        codigo: form.codigo.trim().toLowerCase(),
        data_inicio: form.data_inicio || null,
      }
      const res = await fetch(
        editandoId == null
          ? `${API_BASE}/fidc/fundos`
          : `${API_BASE}/fidc/fundos/${editandoId}`,
        {
          method: editandoId == null ? 'POST' : 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(
            editandoId == null
              ? payload
              : {
                  nome: payload.nome,
                  cnpj: payload.cnpj,
                  data_inicio: payload.data_inicio,
                  idsf_carteiras: payload.idsf_carteiras,
                  tabela_estoque: payload.tabela_estoque,
                  bdr_tp_contabil_estoque: payload.bdr_tp_contabil_estoque,
                  bdr_tp_contabil_mov: payload.bdr_tp_contabil_mov,
                  ativo: payload.ativo,
                  observacao: payload.observacao,
                },
          ),
        },
      )
      if (!res.ok) {
        const detalhe = await res.json().catch(() => ({}))
        throw new Error(detalhe.detail || `HTTP ${res.status}`)
      }
      const salvo: Fundo = await res.json()
      setOk(editandoId == null ? 'Fundo criado.' : 'Fundo atualizado.')
      await carregar()
      onSelecionarFundo(salvo)
      if (editandoId == null) iniciarNovo()
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Falha ao salvar fundo')
    } finally {
      setCarregando(false)
    }
  }

  return (
    <div className="config-page">
      <header className="topbar">
        <div>
          <p className="eyebrow">Multi-FIDC</p>
          <h1>Configurações</h1>
        </div>
        <button type="button" className="btn-primario" onClick={iniciarNovo}>
          Novo fundo
        </button>
      </header>

      <p className="subtitulo">
        Cadastre FIDCs genéricos (CNPJ, início, carteiras IDSF e tabela de estoque). O
        dashboard e as cargas BDR usam o fundo selecionado.
      </p>

      {erro && <div className="banner-erro">{erro}</div>}
      {ok && <div className="banner-ok">{ok}</div>}
      {carregando && <div className="banner-status">Processando…</div>}

      <div className="config-grid">
        <section className="painel">
          <h2>Fundos cadastrados</h2>
          <div className="tabela-wrap">
            <table>
              <thead>
                <tr>
                  <th>Código</th>
                  <th>Nome</th>
                  <th>CNPJ</th>
                  <th>Início</th>
                  <th>Ativo</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {fundos.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="vazio">
                      Nenhum fundo. Execute o SQL e cadastre o Alpha.
                    </td>
                  </tr>
                ) : (
                  fundos.map((f) => (
                    <tr
                      key={f.id}
                      className={fundoSelecionadoId === f.id ? 'linha-ativa' : undefined}
                    >
                      <td>
                        <code>{f.codigo}</code>
                      </td>
                      <td>{f.nome}</td>
                      <td>{f.cnpj_formatado || f.cnpj}</td>
                      <td>{f.data_inicio ?? '—'}</td>
                      <td>{f.ativo ? 'Sim' : 'Não'}</td>
                      <td className="acoes-fundo">
                        <button type="button" onClick={() => onSelecionarFundo(f)}>
                          Usar
                        </button>
                        <button type="button" onClick={() => iniciarEdicao(f)}>
                          Editar
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="painel">
          <h2>{editandoId == null ? 'Novo fundo' : `Editar #${editandoId}`}</h2>
          <form className="form-fundo" onSubmit={salvar}>
            <label>
              Código
              <input
                value={form.codigo}
                onChange={(e) => setForm({ ...form, codigo: e.target.value })}
                placeholder="alpha"
                required
                disabled={editandoId != null}
              />
            </label>
            <label>
              Nome
              <input
                value={form.nome}
                onChange={(e) => setForm({ ...form, nome: e.target.value })}
                placeholder="FIDC Alpha"
                required
              />
            </label>
            <label>
              CNPJ
              <input
                value={form.cnpj}
                onChange={(e) => setForm({ ...form, cnpj: e.target.value })}
                placeholder="34691300000186"
                required
              />
            </label>
            <label>
              Data início
              <input
                type="date"
                value={form.data_inicio}
                onChange={(e) => setForm({ ...form, data_inicio: e.target.value })}
              />
            </label>
            <label>
              Carteiras IDSF
              <input
                value={form.idsf_carteiras}
                onChange={(e) => setForm({ ...form, idsf_carteiras: e.target.value })}
                placeholder="34691,34691302,..."
              />
            </label>
            <label>
              Tabela estoque
              <input
                value={form.tabela_estoque}
                onChange={(e) => setForm({ ...form, tabela_estoque: e.target.value })}
              />
            </label>
            <label>
              tpContabil estoque
              <input
                value={form.bdr_tp_contabil_estoque}
                onChange={(e) =>
                  setForm({ ...form, bdr_tp_contabil_estoque: e.target.value })
                }
              />
            </label>
            <label>
              tpContabil movimentações
              <input
                value={form.bdr_tp_contabil_mov}
                onChange={(e) => setForm({ ...form, bdr_tp_contabil_mov: e.target.value })}
              />
            </label>
            <label className="check-linha">
              <input
                type="checkbox"
                checked={form.ativo}
                onChange={(e) => setForm({ ...form, ativo: e.target.checked })}
              />
              Fundo ativo
            </label>
            <label>
              Observação
              <textarea
                value={form.observacao}
                onChange={(e) => setForm({ ...form, observacao: e.target.value })}
                rows={3}
              />
            </label>
            <div className="form-acoes">
              <button type="submit" className="btn-primario" disabled={carregando}>
                Salvar
              </button>
              <button type="button" onClick={iniciarNovo}>
                Limpar
              </button>
            </div>
          </form>
        </section>
      </div>
    </div>
  )
}
