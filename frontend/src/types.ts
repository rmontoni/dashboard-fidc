export interface Kpis {
  pl_fundo: number
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
  credit_var_historico_95: number
  credit_var_parametrico_95: number
  n_obs?: number
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
  kpis?: Kpis
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

export const API_BASE = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8003'
