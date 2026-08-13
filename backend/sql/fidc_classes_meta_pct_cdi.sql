-- Amplia fidc_classes_meta com %CDI, cota inicial e data início.
-- Rodar no SQL Editor do Supabase (após fidc_classes_meta.sql).

alter table public.fidc_classes_meta
  add column if not exists pct_cdi numeric;

alter table public.fidc_classes_meta
  add column if not exists cota_inicial numeric;

alter table public.fidc_classes_meta
  add column if not exists data_inicio_cota date;

comment on column public.fidc_classes_meta.pct_cdi is
  'Percentual do CDI (ex.: 170 = 170% CDI), extraído de Posicoes.Ativo na Composition.';

comment on column public.fidc_classes_meta.cota_inicial is
  'CotaInicial do GetPortfolio (base da marcação).';

comment on column public.fidc_classes_meta.data_inicio_cota is
  'DataInicioCota do GetPortfolio (início da marcação).';
