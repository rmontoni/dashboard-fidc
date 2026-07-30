-- Liquidez diária (caixa saldo + aplicações) extraída da composição IDSF.
-- API: GetPortfolioComposition/{IdCarteira}/{dataInicio}/{dataFim}/JSON
-- Rodar no SQL Editor do Supabase.

create table if not exists public.fidc_liquidez_diaria (
  data_posicao date not null,
  id_carteira integer not null,
  carteira text,
  caixa numeric not null default 0,
  caixa_cpr numeric not null default 0,
  aplicacoes numeric not null default 0,
  dc_idsf numeric not null default 0,
  pl_carteira numeric not null default 0,
  pl_estimado numeric not null default 0,
  detalhes jsonb not null default '{}'::jsonb,
  fonte text not null default 'idsf_json',
  atualizado_em timestamptz not null default now(),
  primary key (data_posicao, id_carteira)
);

comment on table public.fidc_liquidez_diaria is
  'Caixa (Conta Corrente - Saldo), CPR, aplicações (Fundo) e DC IDSF por dia.';

comment on column public.fidc_liquidez_diaria.caixa is
  'Somente Conta Corrente - Saldo (entra no PL).';

comment on column public.fidc_liquidez_diaria.caixa_cpr is
  'Conta Corrente - CPR (não entra no PL; provisões/liquidações).';

comment on column public.fidc_liquidez_diaria.dc_idsf is
  'Outros Ativos (proxy de DC quando a data ainda não está conciliada).';

comment on column public.fidc_liquidez_diaria.pl_estimado is
  'caixa + aplicacoes + dc_idsf (PL dia a dia sem conciliação de estoque).';

create index if not exists fidc_liquidez_diaria_data_idx
  on public.fidc_liquidez_diaria (data_posicao desc);
