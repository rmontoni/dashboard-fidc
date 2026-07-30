-- Cadastro genérico de FIDCs (multi-fundo).
-- Rodar no SQL Editor do Supabase (junto ou após fidc_movimentacoes_bdr.sql).

create table if not exists public.fidc_fundos (
  id serial primary key,
  codigo text not null unique,
  nome text not null,
  cnpj text not null unique,
  data_inicio date,
  idsf_carteiras text not null default '',
  tabela_estoque text not null default 'BD_Estoque',
  bdr_tp_contabil_estoque text not null default 'P',
  bdr_tp_contabil_mov text not null default 'A',
  ativo boolean not null default true,
  observacao text,
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now()
);

create index if not exists fidc_fundos_ativo_idx
  on public.fidc_fundos (ativo, nome);

comment on table public.fidc_fundos is
  'Cadastro de fundos FIDC. CNPJ e parâmetros BDR/IDSF por fundo; o dashboard escolhe um fundo ativo.';

-- Seed inicial: Legatus Alpha
insert into public.fidc_fundos (
  codigo, nome, cnpj, data_inicio, idsf_carteiras, tabela_estoque, ativo, observacao
) values (
  'alpha',
  'FIDC Alpha',
  '34691300000186',
  '2021-03-01',
  '34691,34691302,34691303,34691304,566391',
  'BD_Estoque',
  true,
  'Fundo piloto do dashboard'
)
on conflict (codigo) do update set
  nome = excluded.nome,
  cnpj = excluded.cnpj,
  data_inicio = excluded.data_inicio,
  idsf_carteiras = excluded.idsf_carteiras,
  tabela_estoque = excluded.tabela_estoque,
  atualizado_em = now();

-- Liga conciliação ao fundo (se a tabela já existir)
do $$
begin
  if exists (
    select 1 from information_schema.tables
    where table_schema = 'public' and table_name = 'fidc_conciliacao_data_base'
  ) then
    alter table public.fidc_conciliacao_data_base
      add column if not exists id_fundo integer references public.fidc_fundos(id);
  end if;
end $$;
