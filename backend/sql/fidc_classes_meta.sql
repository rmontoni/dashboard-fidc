-- Cadastro / metadados das classes de cota (GetPortfolio + Composition).
-- Rodar no SQL Editor do Supabase.

create table if not exists public.fidc_classes_meta (
  id_carteira integer primary key,
  apelido text not null default '',
  classe text not null,
  vencimento date,
  pct_cdi numeric,
  cota_inicial numeric,
  data_inicio_cota date,
  dados jsonb,
  atualizado_em timestamptz not null default now()
);

comment on table public.fidc_classes_meta is
  'Master das classes (MEZ/SUB): apelido, %CDI, cota inicial e vencimento.';

comment on column public.fidc_classes_meta.classe is
  'Código estável: MEZ, MEZ_II, MEZ_III, MEZ_IV, SUB.';

comment on column public.fidc_classes_meta.pct_cdi is
  'Percentual do CDI (ex.: 170 = 170% CDI), da Composition Posicoes.Ativo.';
