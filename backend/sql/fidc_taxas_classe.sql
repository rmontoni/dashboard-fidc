-- Histórico de taxas por classe (GetSettledFeeHistory).
-- Rodar no SQL Editor do Supabase.

create table if not exists public.fidc_taxas_classe (
  data_historico date not null,
  id_carteira integer not null,
  id_tipo_taxa integer not null default 0,
  tipo_taxa text not null default '',
  valor_dia numeric not null default 0,
  valor_acumulado numeric not null default 0,
  pl_base numeric,
  data_fim_apropriacao date,
  data_pagamento date,
  fonte text not null default 'idsf_fee_history',
  atualizado_em timestamptz not null default now(),
  primary key (data_historico, id_carteira, id_tipo_taxa, tipo_taxa)
);

create index if not exists fidc_taxas_classe_carteira_idx
  on public.fidc_taxas_classe (id_carteira, data_historico desc);

comment on table public.fidc_taxas_classe is
  'Taxas apropriadas/liquidadas por classe (API GetSettledFeeHistory).';
