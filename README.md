# Dashboard FIDC

Dashboard de risco de carteira FIDC com backend Python (FastAPI + pandas) e frontend React (Vite).  
Fonte de dados: **Supabase** (`BD_FIDC_Recebiveis`).

## Estrutura

- `backend/` — API FastAPI, leitura do Supabase e cálculo `calcular_risco_fidc`
- `frontend/` — Dashboard React consumindo `/fidc/risco`

## Configuração

Copie `backend/.env.example` para `backend/.env` e preencha:

```env
SUPABASE_URL=https://SEU_PROJECT_ID.supabase.co
SUPABASE_SERVICE_ROLE_KEY=sua_service_role_key
SUPABASE_TABLE=BD_FIDC_Recebiveis
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

## Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/fidc/datas` | Datas base disponíveis no Supabase |
| GET | `/fidc/risco?dataBase=29/05/2026` | KPIs, tops e gráfico de evolução |
