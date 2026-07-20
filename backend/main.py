from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from db import listar_datas_base
from risco import calcular_risco_fidc

app = FastAPI(title="API Risco FIDC", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "fonte": "supabase"}


@app.get("/fidc/datas")
def datas_base():
    """Retorna as datas base disponíveis no Supabase (formato dd/mm/yyyy)."""
    return {"datas": listar_datas_base()}


@app.get("/fidc/risco")
def risco_fidc(dataBase: str = Query(..., description="Data base no formato dd/mm/yyyy")):
    return calcular_risco_fidc(dataBase)
