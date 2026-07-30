# Dashboard FIDC

Dashboard de risco de carteira FIDC com backend Python (FastAPI + pandas) e frontend React (Vite).  
Fonte de dados: **Supabase** (`BD_Estoque`).

## Estrutura

- `backend/` — API FastAPI, leitura do Supabase e cálculo `calcular_risco_fidc`
- `frontend/` — Dashboard React consumindo `/fidc/risco`

## Configuração

Copie `backend/.env.example` para `backend/.env` e preencha:

```env
SUPABASE_URL=https://SEU_PROJECT_ID.supabase.co
SUPABASE_SERVICE_ROLE_KEY=sua_service_role_key
SUPABASE_TABLE=BD_Estoque
IDSF_TOKEN=seu_token_idsf
IDSF_CARTEIRAS=34691,34691302,34691303,566391
```

## Como rodar

### 1. Backend

```bash
cd backend
python -m pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8003
```

API: http://127.0.0.1:8003  
Docs: http://127.0.0.1:8003/docs

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

App: http://localhost:5173

### 3. Série diária PL/PDD (Credit VaR — carga)

1. No Supabase SQL Editor, execute `backend/sql/fidc_pl_pdd_diario.sql`.
2. Preencha `IDSF_TOKEN` (e opcionalmente `IDSF_CARTEIRAS`) no `backend/.env`.
3. Rode a carga dos últimos 12 meses:

```bash
cd backend
python carregar_pl_pdd.py
```

A tabela `fidc_pl_pdd_diario` recebe uma linha por dia/carteira e a consolidação do fundo (`id_carteira = 0`).

### 4. Fundos (multi-FIDC) + movimentações BDR

1. No Supabase SQL Editor, execute nesta ordem:
   - `backend/sql/fidc_movimentacoes_bdr.sql`
   - `backend/sql/fidc_fundos.sql` (cria `fidc_fundos` e seed do **Alpha** `34691300000186`)
2. Preencha no `.env`: `BDR_BASIC_USER`, `BDR_BASIC_PASSWORD` (CNPJ fica no cadastro do fundo).
3. No frontend: menu **Configurações** para cadastrar/editar FIDCs e escolher o fundo ativo.
4. Carga histórica de movimentações do fundo:

```bash
cd backend
python carregar_movimentacoes_bdr.py --fundo alpha
```

5. Conciliação de uma data base:

```bash
python conciliar_data_base_bdr.py --data 2026-06-30
```

## Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/fidc/datas` | Datas base disponíveis no Supabase |
| GET | `/fidc/risco?dataBase=29/05/2026` | KPIs, tops e gráfico de evolução |
