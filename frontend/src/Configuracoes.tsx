import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import type { UsuarioSessao } from './auth'
import UsuariosConfig from './UsuariosConfig'
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

const CLASSE_VAZIA = {
  nome: '',
  id_carteira: '',
  percentual_cdi: '100',
  meses_primeira: '12',
  meses_segunda: '24',
  perc_primeira: '50',
  ativo: true,
}

const COTISTA_VAZIO = { nome: '', documento: '' }

const CHAMADA_VAZIA = {
  classe_id: '',
  cotista_id: '',
  numero: '1',
  data_prazo: '',
  data_aporte: '',
  valor_nominal: '',
  origem: '',
  principal_amortizado: '0',
  valor_amortizado_bruto: '0',
  perc_primeira: '',
  credito_vp: '0',
}

type AbaConfig = 'fundos' | 'classes' | 'cotistas' | 'chamadas' | 'pd' | 'usuarios'

type ParametrosPd = {
  pd_min_consignado: number
  pd_consignado_vencido: number
  redutor: number
}

const PD_VAZIO = {
  pd_min_consignado: '15',
  pd_consignado_vencido: '80',
  redutor: '0.5',
}

type ClasseRow = {
  id: number
  nome: string
  id_carteira: number | null
  percentual_cdi: number
  meses_primeira: number
  meses_segunda: number
  perc_primeira: number
  ativo: boolean
}

type CotistaRow = { id: number; nome: string; documento: string }

type ChamadaRow = {
  id: number
  classe_id: number
  cotista_id: number
  numero: number
  data_prazo: string
  data_aporte: string
  valor_nominal: number
  origem: string | null
  principal_amortizado: number
  valor_amortizado_bruto: number
  perc_primeira: number | null
  credito_vp: number
}

type ConfiguracoesProps = {
  fundoSelecionadoId: number | null
  onSelecionarFundo: (fundo: Fundo) => void
  usuarioLogado: UsuarioSessao
}

export default function Configuracoes({
  fundoSelecionadoId,
  onSelecionarFundo,
  usuarioLogado,
}: ConfiguracoesProps) {
  const [aba, setAba] = useState<AbaConfig>('fundos')
  const [fundos, setFundos] = useState<Fundo[]>([])
  const [classes, setClasses] = useState<ClasseRow[]>([])
  const [cotistas, setCotistas] = useState<CotistaRow[]>([])
  const [chamadas, setChamadas] = useState<ChamadaRow[]>([])
  const [erro, setErro] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [carregando, setCarregando] = useState(false)

  const [editandoFundoId, setEditandoFundoId] = useState<number | null>(null)
  const [formFundo, setFormFundo] = useState({ ...FUNDO_VAZIO })

  const [editandoClasseId, setEditandoClasseId] = useState<number | null>(null)
  const [formClasse, setFormClasse] = useState({ ...CLASSE_VAZIA })

  const [editandoCotistaId, setEditandoCotistaId] = useState<number | null>(null)
  const [formCotista, setFormCotista] = useState({ ...COTISTA_VAZIO })

  const [editandoChamadaId, setEditandoChamadaId] = useState<number | null>(null)
  const [formChamada, setFormChamada] = useState({ ...CHAMADA_VAZIA })

  const [formPd, setFormPd] = useState({ ...PD_VAZIO })
  const [descricaoPd, setDescricaoPd] = useState<Record<string, string>>({})

  async function carregarFundos() {
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
  }

  async function carregarPassivoCadastro() {
    const [rc, rco, rch] = await Promise.all([
      fetch(`${API_BASE}/fidc/passivo/classes`),
      fetch(`${API_BASE}/fidc/passivo/cotistas`),
      fetch(`${API_BASE}/fidc/passivo/chamadas`),
    ])
    if (rc.ok) setClasses(((await rc.json()).classes ?? []) as ClasseRow[])
    else setClasses([])
    if (rco.ok) setCotistas(((await rco.json()).cotistas ?? []) as CotistaRow[])
    else setCotistas([])
    if (rch.ok) setChamadas(((await rch.json()).chamadas ?? []) as ChamadaRow[])
    else setChamadas([])
  }

  async function carregarPd() {
    const res = await fetch(`${API_BASE}/fidc/config/pd`)
    if (!res.ok) {
      const detalhe = await res.json().catch(() => ({}))
      throw new Error(detalhe.detail || `HTTP ${res.status}`)
    }
    const dados = await res.json()
    const p = (dados.parametros ?? {}) as ParametrosPd
    setFormPd({
      pd_min_consignado: String(p.pd_min_consignado ?? PD_VAZIO.pd_min_consignado),
      pd_consignado_vencido: String(
        p.pd_consignado_vencido ?? PD_VAZIO.pd_consignado_vencido,
      ),
      redutor: String(p.redutor ?? PD_VAZIO.redutor),
    })
    setDescricaoPd(dados.descricao ?? {})
  }

  async function salvarPd(e: FormEvent) {
    e.preventDefault()
    setErro(null)
    setOk(null)
    setCarregando(true)
    try {
      const payload = {
        pd_min_consignado: Number(formPd.pd_min_consignado),
        pd_consignado_vencido: Number(formPd.pd_consignado_vencido),
        redutor: Number(formPd.redutor),
      }
      const res = await fetch(`${API_BASE}/fidc/config/pd`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        const detalhe = await res.json().catch(() => ({}))
        throw new Error(detalhe.detail || `HTTP ${res.status}`)
      }
      const dados = await res.json()
      const p = dados.parametros as ParametrosPd
      setFormPd({
        pd_min_consignado: String(p.pd_min_consignado),
        pd_consignado_vencido: String(p.pd_consignado_vencido),
        redutor: String(p.redutor),
      })
      setDescricaoPd(dados.descricao ?? {})
      setOk('Parâmetros de PD salvos.')
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Falha ao salvar parâmetros de PD')
    } finally {
      setCarregando(false)
    }
  }

  async function carregar() {
    setErro(null)
    setCarregando(true)
    try {
      await carregarFundos()
      await carregarPassivoCadastro()
      await carregarPd()
    } catch (e) {
      setErro(
        e instanceof Error
          ? e.message
          : 'Falha ao carregar. Confirme o SQL e a API.',
      )
    } finally {
      setCarregando(false)
    }
  }

  useEffect(() => {
    void carregar()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function iniciarNovoFundo() {
    setEditandoFundoId(null)
    setFormFundo({ ...FUNDO_VAZIO })
    setOk(null)
    setErro(null)
  }

  function iniciarEdicaoFundo(fundo: Fundo) {
    setEditandoFundoId(fundo.id)
    setFormFundo({
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

  async function salvarFundo(e: FormEvent) {
    e.preventDefault()
    setErro(null)
    setOk(null)
    setCarregando(true)
    try {
      const payload = {
        ...formFundo,
        codigo: formFundo.codigo.trim().toLowerCase(),
        data_inicio: formFundo.data_inicio || null,
      }
      const res = await fetch(
        editandoFundoId == null
          ? `${API_BASE}/fidc/fundos`
          : `${API_BASE}/fidc/fundos/${editandoFundoId}`,
        {
          method: editandoFundoId == null ? 'POST' : 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(
            editandoFundoId == null
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
      setOk(editandoFundoId == null ? 'Fundo criado.' : 'Fundo atualizado.')
      await carregarFundos()
      onSelecionarFundo(salvo)
      if (editandoFundoId == null) iniciarNovoFundo()
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Falha ao salvar fundo')
    } finally {
      setCarregando(false)
    }
  }

  function iniciarNovaClasse() {
    setEditandoClasseId(null)
    setFormClasse({ ...CLASSE_VAZIA })
    setOk(null)
    setErro(null)
  }

  function iniciarEdicaoClasse(c: ClasseRow) {
    setEditandoClasseId(c.id)
    setFormClasse({
      nome: c.nome,
      id_carteira: c.id_carteira != null ? String(c.id_carteira) : '',
      percentual_cdi: String(c.percentual_cdi),
      meses_primeira: String(c.meses_primeira),
      meses_segunda: String(c.meses_segunda),
      perc_primeira: String(c.perc_primeira),
      ativo: c.ativo,
    })
    setOk(null)
    setErro(null)
  }

  async function salvarClasse(e: FormEvent) {
    e.preventDefault()
    setErro(null)
    setOk(null)
    setCarregando(true)
    try {
      const payload = {
        nome: formClasse.nome.trim(),
        id_carteira: formClasse.id_carteira
          ? Number(formClasse.id_carteira)
          : null,
        percentual_cdi: Number(formClasse.percentual_cdi),
        meses_primeira: Number(formClasse.meses_primeira),
        meses_segunda: Number(formClasse.meses_segunda),
        perc_primeira: Number(formClasse.perc_primeira),
        ativo: formClasse.ativo,
      }
      const res = await fetch(
        editandoClasseId == null
          ? `${API_BASE}/fidc/passivo/classes`
          : `${API_BASE}/fidc/passivo/classes/${editandoClasseId}`,
        {
          method: editandoClasseId == null ? 'POST' : 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
      )
      if (!res.ok) {
        const detalhe = await res.json().catch(() => ({}))
        throw new Error(detalhe.detail || `HTTP ${res.status}`)
      }
      setOk(editandoClasseId == null ? 'Classe criada.' : 'Classe atualizada.')
      await carregarPassivoCadastro()
      if (editandoClasseId == null) iniciarNovaClasse()
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Falha ao salvar classe')
    } finally {
      setCarregando(false)
    }
  }

  async function excluirClasse(id: number) {
    if (!confirm('Excluir esta classe?')) return
    setErro(null)
    setOk(null)
    try {
      const res = await fetch(`${API_BASE}/fidc/passivo/classes/${id}`, {
        method: 'DELETE',
      })
      if (!res.ok) {
        const detalhe = await res.json().catch(() => ({}))
        throw new Error(detalhe.detail || `HTTP ${res.status}`)
      }
      setOk('Classe excluída.')
      await carregarPassivoCadastro()
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Falha ao excluir')
    }
  }

  function iniciarNovoCotista() {
    setEditandoCotistaId(null)
    setFormCotista({ ...COTISTA_VAZIO })
    setOk(null)
    setErro(null)
  }

  function iniciarEdicaoCotista(c: CotistaRow) {
    setEditandoCotistaId(c.id)
    setFormCotista({ nome: c.nome, documento: c.documento })
    setOk(null)
    setErro(null)
  }

  async function salvarCotista(e: FormEvent) {
    e.preventDefault()
    setErro(null)
    setOk(null)
    setCarregando(true)
    try {
      const payload = {
        nome: formCotista.nome.trim(),
        documento: formCotista.documento,
      }
      const res = await fetch(
        editandoCotistaId == null
          ? `${API_BASE}/fidc/passivo/cotistas`
          : `${API_BASE}/fidc/passivo/cotistas/${editandoCotistaId}`,
        {
          method: editandoCotistaId == null ? 'POST' : 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
      )
      if (!res.ok) {
        const detalhe = await res.json().catch(() => ({}))
        throw new Error(detalhe.detail || `HTTP ${res.status}`)
      }
      setOk(editandoCotistaId == null ? 'Cotista criado.' : 'Cotista atualizado.')
      await carregarPassivoCadastro()
      if (editandoCotistaId == null) iniciarNovoCotista()
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Falha ao salvar cotista')
    } finally {
      setCarregando(false)
    }
  }

  async function excluirCotista(id: number) {
    if (!confirm('Excluir este cotista?')) return
    setErro(null)
    setOk(null)
    try {
      const res = await fetch(`${API_BASE}/fidc/passivo/cotistas/${id}`, {
        method: 'DELETE',
      })
      if (!res.ok) {
        const detalhe = await res.json().catch(() => ({}))
        throw new Error(detalhe.detail || `HTTP ${res.status}`)
      }
      setOk('Cotista excluído.')
      await carregarPassivoCadastro()
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Falha ao excluir')
    }
  }

  function iniciarNovaChamada() {
    setEditandoChamadaId(null)
    setFormChamada({
      ...CHAMADA_VAZIA,
      classe_id: classes[0] ? String(classes[0].id) : '',
      cotista_id: cotistas[0] ? String(cotistas[0].id) : '',
    })
    setOk(null)
    setErro(null)
  }

  function iniciarEdicaoChamada(c: ChamadaRow) {
    setEditandoChamadaId(c.id)
    setFormChamada({
      classe_id: String(c.classe_id),
      cotista_id: String(c.cotista_id),
      numero: String(c.numero),
      data_prazo: String(c.data_prazo).slice(0, 10),
      data_aporte: String(c.data_aporte).slice(0, 10),
      valor_nominal: String(c.valor_nominal),
      origem: c.origem ?? '',
      principal_amortizado: String(c.principal_amortizado ?? 0),
      valor_amortizado_bruto: String(c.valor_amortizado_bruto ?? 0),
      perc_primeira: c.perc_primeira != null ? String(c.perc_primeira) : '',
      credito_vp: String(c.credito_vp ?? 0),
    })
    setOk(null)
    setErro(null)
  }

  async function salvarChamada(e: FormEvent) {
    e.preventDefault()
    setErro(null)
    setOk(null)
    setCarregando(true)
    try {
      const payload: Record<string, unknown> = {
        classe_id: Number(formChamada.classe_id),
        cotista_id: Number(formChamada.cotista_id),
        numero: Number(formChamada.numero),
        data_prazo: formChamada.data_prazo,
        data_aporte: formChamada.data_aporte,
        valor_nominal: Number(formChamada.valor_nominal),
        origem: formChamada.origem || null,
        principal_amortizado: Number(formChamada.principal_amortizado || 0),
        valor_amortizado_bruto: Number(formChamada.valor_amortizado_bruto || 0),
        credito_vp: Number(formChamada.credito_vp || 0),
      }
      if (formChamada.perc_primeira !== '') {
        payload.perc_primeira = Number(formChamada.perc_primeira)
      }
      const res = await fetch(
        editandoChamadaId == null
          ? `${API_BASE}/fidc/passivo/chamadas`
          : `${API_BASE}/fidc/passivo/chamadas/${editandoChamadaId}`,
        {
          method: editandoChamadaId == null ? 'POST' : 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
      )
      if (!res.ok) {
        const detalhe = await res.json().catch(() => ({}))
        throw new Error(detalhe.detail || `HTTP ${res.status}`)
      }
      setOk(editandoChamadaId == null ? 'Chamada criada.' : 'Chamada atualizada.')
      await carregarPassivoCadastro()
      if (editandoChamadaId == null) iniciarNovaChamada()
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Falha ao salvar chamada')
    } finally {
      setCarregando(false)
    }
  }

  async function excluirChamada(id: number) {
    if (!confirm('Excluir esta chamada?')) return
    setErro(null)
    setOk(null)
    try {
      const res = await fetch(`${API_BASE}/fidc/passivo/chamadas/${id}`, {
        method: 'DELETE',
      })
      if (!res.ok) {
        const detalhe = await res.json().catch(() => ({}))
        throw new Error(detalhe.detail || `HTTP ${res.status}`)
      }
      setOk('Chamada excluída.')
      await carregarPassivoCadastro()
    } catch (err) {
      setErro(err instanceof Error ? err.message : 'Falha ao excluir')
    }
  }

  const mapaClasse = new Map(classes.map((c) => [c.id, c.nome]))
  const mapaCotista = new Map(cotistas.map((c) => [c.id, c.nome]))

  return (
    <div className="config-page">
      <header className="topbar">
        <div>
          <p className="eyebrow">Multi-FIDC</p>
          <h1>Configurações</h1>
        </div>
      </header>

      <nav className="abas-passivo" aria-label="Abas de configuração">
        {(
          [
            ['fundos', 'Fundos'],
            ['classes', 'Classes'],
            ['cotistas', 'Cotistas'],
            ['chamadas', 'Chamadas'],
            ['pd', 'PD estimada'],
            ...(usuarioLogado.perfil === 'admin'
              ? ([['usuarios', 'Usuários']] as const)
              : []),
          ] as readonly [AbaConfig, string][]
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

      {erro && <div className="banner-erro">{erro}</div>}
      {ok && <div className="banner-ok">{ok}</div>}
      {carregando && <div className="banner-status">Processando…</div>}

      {aba === 'fundos' && (
        <>
          <div className="config-toolbar">
            <button type="button" className="btn-primario" onClick={iniciarNovoFundo}>
              Novo fundo
            </button>
          </div>
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
                          className={
                            fundoSelecionadoId === f.id ? 'linha-ativa' : undefined
                          }
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
                            <button type="button" onClick={() => iniciarEdicaoFundo(f)}>
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
              <h2>
                {editandoFundoId == null ? 'Novo fundo' : `Editar #${editandoFundoId}`}
              </h2>
              <form className="form-fundo" onSubmit={salvarFundo}>
                <label>
                  Código
                  <input
                    value={formFundo.codigo}
                    onChange={(e) =>
                      setFormFundo({ ...formFundo, codigo: e.target.value })
                    }
                    placeholder="alpha"
                    required
                    disabled={editandoFundoId != null}
                  />
                </label>
                <label>
                  Nome
                  <input
                    value={formFundo.nome}
                    onChange={(e) =>
                      setFormFundo({ ...formFundo, nome: e.target.value })
                    }
                    placeholder="FIDC Alpha"
                    required
                  />
                </label>
                <label>
                  CNPJ
                  <input
                    value={formFundo.cnpj}
                    onChange={(e) =>
                      setFormFundo({ ...formFundo, cnpj: e.target.value })
                    }
                    placeholder="34691300000186"
                    required
                  />
                </label>
                <label>
                  Data início
                  <input
                    type="date"
                    value={formFundo.data_inicio}
                    onChange={(e) =>
                      setFormFundo({ ...formFundo, data_inicio: e.target.value })
                    }
                  />
                </label>
                <label>
                  Carteiras IDSF
                  <input
                    value={formFundo.idsf_carteiras}
                    onChange={(e) =>
                      setFormFundo({ ...formFundo, idsf_carteiras: e.target.value })
                    }
                    placeholder="34691,34691302,..."
                  />
                </label>
                <label>
                  Tabela estoque
                  <input
                    value={formFundo.tabela_estoque}
                    onChange={(e) =>
                      setFormFundo({ ...formFundo, tabela_estoque: e.target.value })
                    }
                  />
                </label>
                <label>
                  tpContabil estoque
                  <input
                    value={formFundo.bdr_tp_contabil_estoque}
                    onChange={(e) =>
                      setFormFundo({
                        ...formFundo,
                        bdr_tp_contabil_estoque: e.target.value,
                      })
                    }
                  />
                </label>
                <label>
                  tpContabil movimentações
                  <input
                    value={formFundo.bdr_tp_contabil_mov}
                    onChange={(e) =>
                      setFormFundo({
                        ...formFundo,
                        bdr_tp_contabil_mov: e.target.value,
                      })
                    }
                  />
                </label>
                <label className="check-linha">
                  <input
                    type="checkbox"
                    checked={formFundo.ativo}
                    onChange={(e) =>
                      setFormFundo({ ...formFundo, ativo: e.target.checked })
                    }
                  />
                  Fundo ativo
                </label>
                <label>
                  Observação
                  <textarea
                    value={formFundo.observacao}
                    onChange={(e) =>
                      setFormFundo({ ...formFundo, observacao: e.target.value })
                    }
                    rows={3}
                  />
                </label>
                <div className="form-acoes">
                  <button type="submit" className="btn-primario" disabled={carregando}>
                    Salvar
                  </button>
                  <button type="button" onClick={iniciarNovoFundo}>
                    Limpar
                  </button>
                </div>
              </form>
            </section>
          </div>
        </>
      )}

      {aba === 'classes' && (
        <>
          <div className="config-toolbar">
            <button type="button" className="btn-primario" onClick={iniciarNovaClasse}>
              Nova classe
            </button>
          </div>
          <div className="config-grid">
            <section className="painel">
              <h2>Classes</h2>
              <div className="tabela-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Nome</th>
                      <th>IDSF</th>
                      <th>%CDI</th>
                      <th>1ª / 2ª (meses)</th>
                      <th>% 1ª</th>
                      <th>Ativo</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {classes.length === 0 ? (
                      <tr>
                        <td colSpan={7} className="vazio">
                          Sem classes. Rode `fidc_passivo_alpha.sql` e a migração.
                        </td>
                      </tr>
                    ) : (
                      classes.map((c) => (
                        <tr key={c.id}>
                          <td>{c.nome}</td>
                          <td>{c.id_carteira ?? '—'}</td>
                          <td>{c.percentual_cdi}</td>
                          <td>
                            {c.meses_primeira} / {c.meses_segunda}
                          </td>
                          <td>{c.perc_primeira}%</td>
                          <td>{c.ativo ? 'Sim' : 'Não'}</td>
                          <td className="acoes-fundo">
                            <button type="button" onClick={() => iniciarEdicaoClasse(c)}>
                              Editar
                            </button>
                            <button type="button" onClick={() => void excluirClasse(c.id)}>
                              Excluir
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
              <h2>
                {editandoClasseId == null
                  ? 'Nova classe'
                  : `Editar classe #${editandoClasseId}`}
              </h2>
              <form className="form-fundo" onSubmit={salvarClasse}>
                <label>
                  Nome
                  <input
                    value={formClasse.nome}
                    onChange={(e) =>
                      setFormClasse({ ...formClasse, nome: e.target.value })
                    }
                    required
                  />
                </label>
                <label>
                  Id carteira IDSF
                  <input
                    value={formClasse.id_carteira}
                    onChange={(e) =>
                      setFormClasse({ ...formClasse, id_carteira: e.target.value })
                    }
                    placeholder="34691"
                  />
                </label>
                <label>
                  % CDI
                  <input
                    type="number"
                    step="0.01"
                    value={formClasse.percentual_cdi}
                    onChange={(e) =>
                      setFormClasse({ ...formClasse, percentual_cdi: e.target.value })
                    }
                    required
                  />
                </label>
                <label>
                  Meses 1ª parcela
                  <input
                    type="number"
                    value={formClasse.meses_primeira}
                    onChange={(e) =>
                      setFormClasse({ ...formClasse, meses_primeira: e.target.value })
                    }
                    required
                  />
                </label>
                <label>
                  Meses 2ª parcela
                  <input
                    type="number"
                    value={formClasse.meses_segunda}
                    onChange={(e) =>
                      setFormClasse({ ...formClasse, meses_segunda: e.target.value })
                    }
                    required
                  />
                </label>
                <label>
                  % 1ª parcela
                  <input
                    type="number"
                    step="0.01"
                    value={formClasse.perc_primeira}
                    onChange={(e) =>
                      setFormClasse({ ...formClasse, perc_primeira: e.target.value })
                    }
                    required
                  />
                </label>
                <label className="check-linha">
                  <input
                    type="checkbox"
                    checked={formClasse.ativo}
                    onChange={(e) =>
                      setFormClasse({ ...formClasse, ativo: e.target.checked })
                    }
                  />
                  Ativa
                </label>
                <div className="form-acoes">
                  <button type="submit" className="btn-primario" disabled={carregando}>
                    Salvar
                  </button>
                  <button type="button" onClick={iniciarNovaClasse}>
                    Limpar
                  </button>
                </div>
              </form>
            </section>
          </div>
        </>
      )}

      {aba === 'cotistas' && (
        <>
          <div className="config-toolbar">
            <button type="button" className="btn-primario" onClick={iniciarNovoCotista}>
              Novo cotista
            </button>
          </div>
          <div className="config-grid">
            <section className="painel">
              <h2>Cotistas ({cotistas.length})</h2>
              <div className="tabela-wrap tabela-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Nome</th>
                      <th>Documento</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {cotistas.map((c) => (
                      <tr key={c.id}>
                        <td>{c.nome}</td>
                        <td>{c.documento}</td>
                        <td className="acoes-fundo">
                          <button type="button" onClick={() => iniciarEdicaoCotista(c)}>
                            Editar
                          </button>
                          <button type="button" onClick={() => void excluirCotista(c.id)}>
                            Excluir
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
            <section className="painel">
              <h2>
                {editandoCotistaId == null
                  ? 'Novo cotista'
                  : `Editar cotista #${editandoCotistaId}`}
              </h2>
              <form className="form-fundo" onSubmit={salvarCotista}>
                <label>
                  Nome
                  <input
                    value={formCotista.nome}
                    onChange={(e) =>
                      setFormCotista({ ...formCotista, nome: e.target.value })
                    }
                    required
                  />
                </label>
                <label>
                  Documento
                  <input
                    value={formCotista.documento}
                    onChange={(e) =>
                      setFormCotista({ ...formCotista, documento: e.target.value })
                    }
                    placeholder="CPF ou CNPJ"
                    required
                  />
                </label>
                <div className="form-acoes">
                  <button type="submit" className="btn-primario" disabled={carregando}>
                    Salvar
                  </button>
                  <button type="button" onClick={iniciarNovoCotista}>
                    Limpar
                  </button>
                </div>
              </form>
            </section>
          </div>
        </>
      )}

      {aba === 'chamadas' && (
        <>
          <div className="config-toolbar">
            <button type="button" className="btn-primario" onClick={iniciarNovaChamada}>
              Nova chamada
            </button>
          </div>
          <div className="config-grid">
            <section className="painel">
              <h2>Chamadas ({chamadas.length})</h2>
              <div className="tabela-wrap tabela-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Classe</th>
                      <th>Cotista</th>
                      <th>#</th>
                      <th>Prazo</th>
                      <th>Aporte</th>
                      <th>Face</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {chamadas.map((c) => (
                      <tr key={c.id}>
                        <td>{mapaClasse.get(c.classe_id) ?? c.classe_id}</td>
                        <td>{mapaCotista.get(c.cotista_id) ?? c.cotista_id}</td>
                        <td>{c.numero}</td>
                        <td>{String(c.data_prazo).slice(0, 10)}</td>
                        <td>{String(c.data_aporte).slice(0, 10)}</td>
                        <td>
                          {Number(c.valor_nominal).toLocaleString('pt-BR', {
                            style: 'currency',
                            currency: 'BRL',
                          })}
                        </td>
                        <td className="acoes-fundo">
                          <button type="button" onClick={() => iniciarEdicaoChamada(c)}>
                            Editar
                          </button>
                          <button type="button" onClick={() => void excluirChamada(c.id)}>
                            Excluir
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
            <section className="painel">
              <h2>
                {editandoChamadaId == null
                  ? 'Nova chamada'
                  : `Editar chamada #${editandoChamadaId}`}
              </h2>
              <form className="form-fundo" onSubmit={salvarChamada}>
                <label>
                  Classe
                  <select
                    value={formChamada.classe_id}
                    onChange={(e) =>
                      setFormChamada({ ...formChamada, classe_id: e.target.value })
                    }
                    required
                  >
                    <option value="">Selecione</option>
                    {classes.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.nome}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Cotista
                  <select
                    value={formChamada.cotista_id}
                    onChange={(e) =>
                      setFormChamada({ ...formChamada, cotista_id: e.target.value })
                    }
                    required
                  >
                    <option value="">Selecione</option>
                    {cotistas.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.nome}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Número
                  <input
                    type="number"
                    value={formChamada.numero}
                    onChange={(e) =>
                      setFormChamada({ ...formChamada, numero: e.target.value })
                    }
                    required
                  />
                </label>
                <label>
                  Data prazo
                  <input
                    type="date"
                    value={formChamada.data_prazo}
                    onChange={(e) =>
                      setFormChamada({ ...formChamada, data_prazo: e.target.value })
                    }
                    required
                  />
                </label>
                <label>
                  Data aporte
                  <input
                    type="date"
                    value={formChamada.data_aporte}
                    onChange={(e) =>
                      setFormChamada({ ...formChamada, data_aporte: e.target.value })
                    }
                    required
                  />
                </label>
                <label>
                  Valor nominal
                  <input
                    type="number"
                    step="0.01"
                    value={formChamada.valor_nominal}
                    onChange={(e) =>
                      setFormChamada({
                        ...formChamada,
                        valor_nominal: e.target.value,
                      })
                    }
                    required
                  />
                </label>
                <label>
                  Origem
                  <input
                    value={formChamada.origem}
                    onChange={(e) =>
                      setFormChamada({ ...formChamada, origem: e.target.value })
                    }
                  />
                </label>
                <label>
                  Principal amortizado
                  <input
                    type="number"
                    step="0.01"
                    value={formChamada.principal_amortizado}
                    onChange={(e) =>
                      setFormChamada({
                        ...formChamada,
                        principal_amortizado: e.target.value,
                      })
                    }
                  />
                </label>
                <label>
                  Valor amortizado bruto
                  <input
                    type="number"
                    step="0.01"
                    value={formChamada.valor_amortizado_bruto}
                    onChange={(e) =>
                      setFormChamada({
                        ...formChamada,
                        valor_amortizado_bruto: e.target.value,
                      })
                    }
                  />
                </label>
                <label>
                  % 1ª (override)
                  <input
                    type="number"
                    step="0.01"
                    value={formChamada.perc_primeira}
                    onChange={(e) =>
                      setFormChamada({
                        ...formChamada,
                        perc_primeira: e.target.value,
                      })
                    }
                  />
                </label>
                <label>
                  Crédito VP
                  <input
                    type="number"
                    step="0.01"
                    value={formChamada.credito_vp}
                    onChange={(e) =>
                      setFormChamada({ ...formChamada, credito_vp: e.target.value })
                    }
                  />
                </label>
                <div className="form-acoes">
                  <button type="submit" className="btn-primario" disabled={carregando}>
                    Salvar
                  </button>
                  <button type="button" onClick={iniciarNovaChamada}>
                    Limpar
                  </button>
                </div>
              </form>
            </section>
          </div>
        </>
      )}

      {aba === 'usuarios' && usuarioLogado.perfil === 'admin' && (
        <UsuariosConfig usuarioLogado={usuarioLogado} />
      )}

      {aba === 'pd' && (
        <div className="config-grid config-grid-unica">
          <section className="painel">
            <h2>PD estimada (projeção de caixa)</h2>
            <p className="texto-auxiliar">
              Usada no Dashboard e no fluxo de caixa projetado. Alterações passam a valer
              imediatamente na API (persistidas em disco no servidor).
            </p>
            <form className="form-fundo form-pd" onSubmit={salvarPd}>
              <label>
                PD mínima — consignado (%)
                <input
                  type="number"
                  step="0.1"
                  min={0}
                  max={100}
                  value={formPd.pd_min_consignado}
                  onChange={(e) =>
                    setFormPd({ ...formPd, pd_min_consignado: e.target.value })
                  }
                  required
                />
                {descricaoPd.pd_min_consignado && (
                  <span className="hint-campo">{descricaoPd.pd_min_consignado}</span>
                )}
              </label>
              <label>
                PD consignado com parcela vencida (%)
                <input
                  type="number"
                  step="0.1"
                  min={0}
                  max={100}
                  value={formPd.pd_consignado_vencido}
                  onChange={(e) =>
                    setFormPd({ ...formPd, pd_consignado_vencido: e.target.value })
                  }
                  required
                />
                {descricaoPd.pd_consignado_vencido && (
                  <span className="hint-campo">{descricaoPd.pd_consignado_vencido}</span>
                )}
              </label>
              <label>
                Redutor da fórmula base
                <input
                  type="number"
                  step="0.05"
                  min={0}
                  max={10}
                  value={formPd.redutor}
                  onChange={(e) => setFormPd({ ...formPd, redutor: e.target.value })}
                  required
                />
                {descricaoPd.redutor && (
                  <span className="hint-campo">{descricaoPd.redutor}</span>
                )}
              </label>
              <div className="form-acoes">
                <button type="submit" className="btn-primario" disabled={carregando}>
                  Salvar parâmetros
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </div>
  )
}
