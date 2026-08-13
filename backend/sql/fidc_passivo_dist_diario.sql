-- Distribuições de passivo (amortização/juros) agregadas por dia/classe.
-- Fonte: PortfolioLiabilityMovements. Rodar no SQL Editor do Supabase.

create table if not exists public.fidc_passivo_dist_diario (
  data date not null,
  id_carteira integer not null,
  amort_bruto numeric not null default 0,
  juros_bruto numeric not null default 0,
  juros_ir numeric not null default 0,
  qtde_cotas numeric,
  n_lancamentos integer not null default 0,
  atualizado_em timestamptz not null default now(),
  primary key (data, id_carteira)
);

create index if not exists fidc_passivo_dist_carteira_idx
  on public.fidc_passivo_dist_diario (id_carteira, data desc);

comment on table public.fidc_passivo_dist_diario is
  'Amortização + Juros (ValorBruto) por dia/classe; abatem a cota unitária.';
