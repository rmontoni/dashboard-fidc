-- Movimentações BDR (aquisições e liquidações) + conciliação de data base.
-- Rodar no SQL Editor do Supabase.
-- Estoque completo só entra em BD_Estoque (ou tabela espelho) quando a data base é conciliada.

-- ---------------------------------------------------------------------------
-- Aquisições
-- ---------------------------------------------------------------------------
create table if not exists public.fidc_aquisicoes (
  id bigserial primary key,
  cnpj_fundo text not null,
  data_movimento date,
  linha_hash text not null,
  dados jsonb not null,
  ticket text,
  periodo_inicio date,
  periodo_fim date,
  fonte text not null default 'bdr_arquivos',
  carregado_em timestamptz not null default now(),
  unique (cnpj_fundo, linha_hash)
);

create index if not exists fidc_aquisicoes_data_idx
  on public.fidc_aquisicoes (cnpj_fundo, data_movimento);

create index if not exists fidc_aquisicoes_dados_gin
  on public.fidc_aquisicoes using gin (dados);

comment on table public.fidc_aquisicoes is
  'Linhas de aquisições (API BDR /arquivos/aquisicoes). dados = linha CSV normalizada.';

-- ---------------------------------------------------------------------------
-- Liquidações
-- ---------------------------------------------------------------------------
create table if not exists public.fidc_liquidacoes (
  id bigserial primary key,
  cnpj_fundo text not null,
  data_movimento date,
  linha_hash text not null,
  dados jsonb not null,
  ticket text,
  periodo_inicio date,
  periodo_fim date,
  fonte text not null default 'bdr_arquivos',
  carregado_em timestamptz not null default now(),
  unique (cnpj_fundo, linha_hash)
);

create index if not exists fidc_liquidacoes_data_idx
  on public.fidc_liquidacoes (cnpj_fundo, data_movimento);

create index if not exists fidc_liquidacoes_dados_gin
  on public.fidc_liquidacoes using gin (dados);

comment on table public.fidc_liquidacoes is
  'Linhas de liquidações (API BDR /arquivos/liquidacoes). dados = linha CSV normalizada.';

-- ---------------------------------------------------------------------------
-- Conciliação diária (estoque baixado só quando a data base entra no dashboard)
-- ---------------------------------------------------------------------------
create table if not exists public.fidc_conciliacao_data_base (
  data_base date primary key,
  cnpj_fundo text not null,
  status text not null default 'pendente'
    check (status in ('pendente', 'baixando', 'ok', 'divergente', 'erro')),
  ticket_estoque text,
  estoque_linhas integer,
  estoque_vl_face numeric,
  estoque_vl_aquisicao numeric,
  estoque_vl_pdd numeric,
  observacao text,
  conferido_em timestamptz,
  atualizado_em timestamptz not null default now()
);

create index if not exists fidc_conciliacao_status_idx
  on public.fidc_conciliacao_data_base (status, data_base desc);

comment on table public.fidc_conciliacao_data_base is
  'Controle de conciliação: estoque da data base é baixado e conferido (totais) antes do OK.';
