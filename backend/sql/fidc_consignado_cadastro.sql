-- Cadastro de consignado privado (atributos por contrato).
-- Chave = nm_cessao_bdr do EstoqueBDR = documento do motor.
-- Incremental: só inclui contratos novos; não espelha estoque dia a dia.
-- Rodar no SQL Editor do Supabase.

create table if not exists public.fidc_consignado_cadastro (
  documento text primary key,
  empresa text,
  cnpj_empresa text,
  tipo_evento text,
  entrada_afastamento_rescisao text,
  saida_afastamento text,
  nm_cedente text,
  doc_cedente text,
  tp_cedente text,
  nm_sacado text,
  doc_sacado text,
  tp_sacado text,
  nm_cessao text,
  n_controle_lastro_origem text,
  fonte_dt_ref date,
  atualizado_em timestamptz not null default now()
);

create index if not exists fidc_consignado_cadastro_empresa_idx
  on public.fidc_consignado_cadastro (empresa);

create index if not exists fidc_consignado_cadastro_cedente_idx
  on public.fidc_consignado_cadastro (doc_cedente, tp_sacado);

comment on table public.fidc_consignado_cadastro is
  'Atributos de consignado privado por contrato (documento = nm_cessao_bdr). VP/PDD vêm do motor.';

comment on column public.fidc_consignado_cadastro.documento is
  'nm_cessao_bdr (EstoqueBDR) = documento (motor)';

comment on column public.fidc_consignado_cadastro.entrada_afastamento_rescisao is
  'CSV EstoqueBDR: entrada_afastamento/rescisao';
