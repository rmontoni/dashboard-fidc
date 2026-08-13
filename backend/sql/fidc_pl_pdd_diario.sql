-- Série diária de PL e PDD por carteira (e consolidado do fundo).
-- Rodar no SQL Editor do Supabase.

create table if not exists public.fidc_pl_pdd_diario (
  data_posicao date not null,
  id_carteira integer not null,
  apelido text not null,
  pl numeric not null default 0,
  pdd numeric not null default 0,
  qtde_cotas numeric,
  valor_cota numeric,
  fonte text not null default 'idsf_json',
  atualizado_em timestamptz not null default now(),
  primary key (data_posicao, id_carteira)
);

comment on table public.fidc_pl_pdd_diario is
  'PL e PDD diários por carteira IDSF; id_carteira=0 representa o consolidado do fundo.';

comment on column public.fidc_pl_pdd_diario.id_carteira is
  'IdCarteira IDSF; 0 = consolidado (soma das classes).';

create index if not exists fidc_pl_pdd_diario_data_idx
  on public.fidc_pl_pdd_diario (data_posicao desc);
