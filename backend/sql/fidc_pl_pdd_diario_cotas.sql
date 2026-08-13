-- Amplia fidc_pl_pdd_diario com qtde/valor de cota (PlCota da Composition).
-- Rodar no SQL Editor do Supabase (após fidc_pl_pdd_diario.sql).

alter table public.fidc_pl_pdd_diario
  add column if not exists qtde_cotas numeric;

alter table public.fidc_pl_pdd_diario
  add column if not exists valor_cota numeric;

comment on column public.fidc_pl_pdd_diario.qtde_cotas is
  'PlCota.Qtde da Composition IDSF (null no consolidado id_carteira=0).';

comment on column public.fidc_pl_pdd_diario.valor_cota is
  'PlCota.Cota da Composition IDSF (referência; app também calcula PL/qtde).';
