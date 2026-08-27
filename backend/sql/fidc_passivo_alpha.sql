-- Passivo mezanino (cotistas, classes, chamadas) — portado do acompanhamento-passivo-alpha.
-- Rodar no SQL Editor do Supabase.

create table if not exists public.fidc_passivo_classes (
  id bigint primary key,
  id_carteira integer,
  nome text not null unique,
  percentual_cdi numeric not null,
  meses_primeira integer not null,
  meses_segunda integer not null,
  perc_primeira numeric not null default 50,
  ativo boolean not null default true,
  atualizado_em timestamptz not null default now()
);

comment on table public.fidc_passivo_classes is
  'Classes de cota mezanino (parâmetros de vencimento e %CDI).';
comment on column public.fidc_passivo_classes.id_carteira is
  'IdCarteira IDSF (34691, 34691302, …); null se ainda não vinculado.';

create table if not exists public.fidc_cotistas (
  id bigint primary key,
  nome text not null,
  documento text not null unique,
  atualizado_em timestamptz not null default now()
);

comment on table public.fidc_cotistas is
  'Cotistas do passivo (CPF 11 ou CNPJ 14, só dígitos).';

create table if not exists public.fidc_passivo_chamadas (
  id bigint primary key,
  classe_id bigint not null references public.fidc_passivo_classes(id),
  cotista_id bigint not null references public.fidc_cotistas(id),
  numero integer not null,
  data_prazo date not null,
  data_aporte date not null,
  valor_nominal numeric not null,
  origem text,
  principal_amortizado numeric not null default 0,
  valor_amortizado_bruto numeric not null default 0,
  perc_primeira numeric,
  credito_vp numeric not null default 0,
  atualizado_em timestamptz not null default now(),
  unique (classe_id, cotista_id, numero)
);

create index if not exists fidc_passivo_chamadas_cotista_idx
  on public.fidc_passivo_chamadas (cotista_id);
create index if not exists fidc_passivo_chamadas_classe_idx
  on public.fidc_passivo_chamadas (classe_id);

comment on table public.fidc_passivo_chamadas is
  'Chamadas de capital (cotista × classe × número) com amortização Britech.';

-- Sequências para novos IDs após migração (ajustar max após carga).
create sequence if not exists public.fidc_passivo_classes_id_seq;
create sequence if not exists public.fidc_cotistas_id_seq;
create sequence if not exists public.fidc_passivo_chamadas_id_seq;
