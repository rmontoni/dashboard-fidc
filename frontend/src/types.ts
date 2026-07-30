export interface Kpis {
  pl_fundo: number
  pl_direitos_creditorios?: number
  caixa?: number
  provisoes?: number
  aplicacoes?: number
  /** ALPHA VALID: aporte em cotas ainda não emitido (ajuste de passivo) */
  passivo_aporte?: number
  provisao_pdd: number
  operacoes_ativas: number
  volume_cedido: number
  valor_presente: number
  prazo_medio: number
  hhi: number
  inadimplencia: number
  receita_projetada: number
  taxa_media: number
  taxa_recompra: number
  taxa_baixa: number
  /** (baixa + recompra) / (liquidações + baixas + recompras), histórico BDR */
  taxa_baixa_recompra?: number
  tem_recompra?: boolean
  credit_var_historico_95: number
  credit_var_parametrico_95: number
  n_obs?: number
}

export interface PosicaoLiquidez {
  categoria: string
  ativo: string
  tipo: string
  valor_liquido: number
  valor_bruto?: number
  qtd_linhas?: number
  id_carteira?: number
  carteira?: string
  agente?: string | null
}

export interface PosicoesLiquidez {
  data_posicao?: string | null
  id_carteira?: number
  carteira?: string | null
  caixa: PosicaoLiquidez[]
  aplicacoes: PosicaoLiquidez[]
  total_caixa: number
  total_provisoes?: number
  total_aplicacoes: number
  total_liquidez: number
  total_dc_idsf?: number
  fonte?: string | null
  aviso?: string
}

export interface DataBaseDetalhe {
  data: string
  data_iso: string
  status: string
  conciliada: boolean
  estoque_linhas?: number | null
  observacao?: string | null
  escopo?: string
  tem_liquidez?: boolean
  caixa?: number | null
  aplicacoes?: number | null
  pl_estimado?: number | null
  dc_bdr?: number | null
  dc_idsf?: number | null
  delta_dc?: number | null
}

export interface ConciliacaoDc {
  dc_bdr: number
  dc_idsf: number
  dc_idsf_liquido?: number
  pdd_bdr?: number
  pdd_idsf?: number
  delta_dc: number
  delta_pdd?: number
  vp_int?: number
  dc_int?: number
  pdd_int?: number
  pdd_idsf_int?: number
  vp_bate?: boolean
  pdd_bate?: boolean
  tolerancia: number
  conciliada_idsf: boolean
  tem_divergencia_residual?: boolean
  passivo_aporte?: number
}

export interface ConcentracaoItem {
  nome: string
  valor: number
  peso: string
  pd_estimada?: number
  perc_recompra?: number
  perc_baixa?: number
}

export interface FatiaDistribuicao {
  nome: string
  valor: number
  peso: number
}

export interface TituloAging {
  documento: string
  cedente: string
  sacado: string
  status: string
  data_vencimento: string
  dias_atraso: number
  valor_face: number
  valor_com_pdd?: number
}

export interface FaixaAging {
  faixa: string
  valor: number
  valor_com_pdd?: number
  qtd: number
  peso: number
  titulos?: TituloAging[]
}

export interface PontoEvolucao {
  mes_ano_emissao: string
  volume_originado: number
  receita_projetada: number
  taxa_media: number
}

export interface PontoFluxoCaixa {
  mes_ano: string
  fluxo_caixa: number
}

export interface RespostaRisco {
  erro?: string
  aviso_idsf?: string | null
  modo?: 'completo' | 'parcial'
  fonte_carteira?: string
  conciliacao_dc?: ConciliacaoDc
  kpis?: Kpis
  posicoes_liquidez?: PosicoesLiquidez
  top_cedentes?: ConcentracaoItem[]
  top_sacados?: ConcentracaoItem[]
  distribuicao_cedentes?: FatiaDistribuicao[]
  distribuicao_sacados?: FatiaDistribuicao[]
  distribuicao_tipos?: FatiaDistribuicao[]
  aging_inadimplencia?: FaixaAging[]
  top_sacados_inadimplentes?: ConcentracaoItem[]
  top_cedentes_inadimplentes?: ConcentracaoItem[]
  grafico_fluxo_caixa?: PontoFluxoCaixa[]
  grafico_evolucao?: PontoEvolucao[]
}

export interface Fundo {
  id: number
  codigo: string
  nome: string
  cnpj: string
  cnpj_formatado: string
  data_inicio: string | null
  idsf_carteiras: string
  tabela_estoque: string
  bdr_tp_contabil_estoque: string
  bdr_tp_contabil_mov: string
  ativo: boolean
  observacao?: string | null
}

export const API_BASE = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8003'
