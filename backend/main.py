import os
import threading
import time

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field

from auth import exigir_admin, exigir_usuario
from conciliacao import (
    ATRASO_DIAS_UTEIS,
    conciliar_estoque_existente,
    data_base_maxima,
    data_base_minima,
    listar_datas_detalhe,
)
from db import listar_datas_base
from fundos import atualizar_fundo, criar_fundo, listar_fundos, obter_fundo
from risco import calcular_pl_liquidez, calcular_risco_fidc

app = FastAPI(title="API Risco FIDC", version="1.0.0")


def _preaquecer() -> None:
    """Pré-aquece o cache do risco na última data conciliada (roda em background no startup)."""
    try:
        import time as _time
        _time.sleep(3)  # aguarda uvicorn terminar de subir
        from conciliacao import data_base_maxima, listar_datas_detalhe
        detalhe = listar_datas_detalhe()
        conciliadas = [d for d in detalhe if d.get("conciliada")]
        if not conciliadas:
            return
        ultima = conciliadas[-1]["data"]
        t0 = _time.perf_counter()
        out = calcular_risco_fidc(ultima)
        if isinstance(out, dict) and not out.get("erro"):
            _RISCO_CACHE[ultima] = (_time.monotonic(), out)
        print(f"[warmup] risco {ultima} em {_time.perf_counter()-t0:.1f}s", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[warmup] erro: {exc}", flush=True)


threading.Thread(target=_preaquecer, daemon=True, name="warmup-risco").start()


def _origens_cors() -> list[str]:
    origens = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ]
    for parte in os.getenv("CORS_ORIGINS", "").split(","):
        origem = parte.strip().rstrip("/")
        if origem and origem not in origens:
            origens.append(origem)
    return origens


app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origens_cors(),
    allow_origin_regex=os.getenv(
        "CORS_ORIGIN_REGEX",
        r"https://([a-z0-9-]+\.)*vercel\.app",
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cache curto do /fidc/risco (payload ~4MB, ~20s de CPU) para evitar 502 no proxy.
_RISCO_CACHE: dict[str, tuple[float, dict]] = {}
_RISCO_CACHE_TTL_S = float(os.getenv("RISCO_CACHE_TTL_S", "300"))


class FundoCreate(BaseModel):
    codigo: str
    nome: str
    cnpj: str
    data_inicio: str | None = None
    idsf_carteiras: str = ""
    tabela_estoque: str = "BD_Estoque"
    bdr_tp_contabil_estoque: str = "P"
    bdr_tp_contabil_mov: str = "A"
    ativo: bool = True
    observacao: str | None = None


class FundoUpdate(BaseModel):
    nome: str | None = None
    cnpj: str | None = None
    data_inicio: str | None = None
    idsf_carteiras: str | None = None
    tabela_estoque: str | None = None
    bdr_tp_contabil_estoque: str | None = None
    bdr_tp_contabil_mov: str | None = None
    ativo: bool | None = None
    observacao: str | None = Field(default=None)


class ConciliarLocalBody(BaseModel):
    data_base: str
    fundo: str = "alpha"
    observacao: str | None = None


class PdParametrosBody(BaseModel):
    pd_min_consignado: float = Field(ge=0, le=100)
    pd_consignado_vencido: float = Field(ge=0, le=100)
    redutor: float = Field(ge=0, le=10)


class LoginBody(BaseModel):
    username: str
    senha: str


class UsuarioCreateBody(BaseModel):
    nome: str
    username: str
    senha: str
    perfil: str = "usuario"
    ativo: bool = True


class UsuarioUpdateBody(BaseModel):
    nome: str | None = None
    username: str | None = None
    senha: str | None = None
    perfil: str | None = None
    ativo: bool | None = None


@app.get("/health")
def health():
    return {
        "status": "ok",
        "fonte": "supabase+idsf",
        "escopo_atual": "direitos_creditorios+caixa+aplicacoes",
        "pl_completo": True,
        "nota": "PL = DC + CC Saldo + Aplicações + Provisões (CPR/taxas)",
    }


@app.post("/fidc/auth/login")
def post_auth_login(body: LoginBody):
    from auth import criar_token
    from usuarios import autenticar

    user = autenticar(body.username, body.senha)
    if not user:
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos.")
    token = criar_token(user)
    return {"token": token, "usuario": user}


@app.get("/fidc/auth/me")
def get_auth_me(usuario: dict = Depends(exigir_usuario)):
    return {"usuario": usuario}


@app.get("/fidc/usuarios")
def get_usuarios(_admin: dict = Depends(exigir_admin)):
    from usuarios import listar_usuarios

    return {"usuarios": listar_usuarios()}


@app.post("/fidc/usuarios", status_code=201)
def post_usuario(body: UsuarioCreateBody, _admin: dict = Depends(exigir_admin)):
    from usuarios import criar_usuario

    try:
        return criar_usuario(
            nome=body.nome,
            username=body.username,
            senha=body.senha,
            perfil=body.perfil,
            ativo=body.ativo,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/fidc/usuarios/{usuario_id}")
def patch_usuario(
    usuario_id: int,
    body: UsuarioUpdateBody,
    _admin: dict = Depends(exigir_admin),
):
    from usuarios import atualizar_usuario

    try:
        return atualizar_usuario(
            usuario_id,
            nome=body.nome,
            username=body.username,
            senha=body.senha,
            perfil=body.perfil,
            ativo=body.ativo,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/fidc/usuarios/{usuario_id}", status_code=204)
def delete_usuario(usuario_id: int, _admin: dict = Depends(exigir_admin)):
    from usuarios import excluir_usuario

    try:
        excluir_usuario(usuario_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return None


@app.get("/fidc/fundos")
def get_fundos(ativos: bool = Query(False, description="Se true, só fundos ativos")):
    try:
        return {"fundos": listar_fundos(apenas_ativos=ativos)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail=f"Não foi possível listar fundos (rode sql/fidc_fundos.sql?): {exc}",
        ) from exc


@app.get("/fidc/fundos/{id_fundo}")
def get_fundo(id_fundo: int):
    fundo = obter_fundo(id_fundo=id_fundo)
    if not fundo:
        raise HTTPException(status_code=404, detail="Fundo não encontrado")
    return fundo


@app.post("/fidc/fundos", status_code=201)
def post_fundo(body: FundoCreate):
    try:
        return criar_fundo(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/fidc/fundos/{id_fundo}")
def patch_fundo(id_fundo: int, body: FundoUpdate):
    try:
        dados = body.model_dump(exclude_unset=True)
        return atualizar_fundo(id_fundo, dados)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/fidc/config/pd")
def get_config_pd():
    """Parâmetros da PD estimada (fluxo de caixa e dashboard)."""
    try:
        from pd_estimada import carregar_config_pd, parametros_pd

        return {"parametros": carregar_config_pd(), "descricao": _descricao_pd()}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.patch("/fidc/config/pd")
def patch_config_pd(body: PdParametrosBody):
    try:
        from pd_estimada import salvar_parametros_pd

        params = salvar_parametros_pd(body.model_dump())
        if params["pd_consignado_vencido"] < params["pd_min_consignado"]:
            raise ValueError("PD consignado vencido deve ser >= PD mínima.")
        return {"parametros": params, "descricao": _descricao_pd()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _descricao_pd() -> dict[str, str]:
    return {
        "pd_min_consignado": "Piso de PD (%) para crédito consignado sem parcela vencida.",
        "pd_consignado_vencido": "PD (%) aplicada ao consignado desde a 1ª parcela vencida do sacado.",
        "redutor": "Multiplicador sobre (face em atraso / face total do sacado) × 100.",
    }


@app.get("/fidc/datas")
def datas_base(
    fundo: str | None = Query(None, description="Código do fundo (default: padrao)"),
    todas: bool = Query(
        True,
        description="Se true, retorna calendário desde o início com flag de conciliação",
    ),
):
    """
    Datas base do fundo.

    - `datas`: apenas conciliadas (ok) — usáveis no motor
    - `detalhe`: calendário completo (dias úteis) com status/conciliada
    """
    try:
        detalhe = listar_datas_detalhe(codigo=fundo)
        conciliadas = [d["data"] for d in detalhe if d["conciliada"]]
        limite = data_base_maxima()
        from calendario import e_feriado, nome_feriado
        from datetime import timedelta

        feriados = []
        cursor = data_base_minima()
        while cursor <= limite:
            if e_feriado(cursor):
                feriados.append(
                    {
                        "data": cursor.isoformat(),
                        "nome": nome_feriado(cursor) or "Feriado",
                    }
                )
            cursor += timedelta(days=1)
        if not todas:
            return {
                "datas": conciliadas,
                "escopo": "direitos_creditorios",
                "data_limite": limite.isoformat(),
                "data_limite_br": limite.strftime("%d/%m/%Y"),
                "feriados": feriados,
            }
        return {
            "datas": conciliadas,
            "detalhe": detalhe,
            "feriados": feriados,
            "escopo": "direitos_creditorios+caixa+aplicacoes",
            "nota": "PL = DC(BDR) + CC Saldo + Aplicações + Provisões; conciliação = DC BDR × DC IDSF",
            "data_limite": limite.isoformat(),
            "data_limite_br": limite.strftime("%d/%m/%Y"),
            "atraso_dias_uteis": ATRASO_DIAS_UTEIS,
            "fonte_carteira": "movimentacoes_bdr",
        }
    except Exception as exc:  # noqa: BLE001
        # Fallback legado
        return {"datas": listar_datas_base(), "detalhe": [], "erro": str(exc)}


@app.post("/fidc/conciliacao/local")
def post_conciliacao_local(body: ConciliarLocalBody):
    """Marca data como conciliada usando estoque já no BD (direitos creditórios)."""
    try:
        return conciliar_estoque_existente(
            body.data_base,
            codigo_fundo=body.fundo,
            observacao=body.observacao,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class LiquidezLoadBody(BaseModel):
    inicio: str | None = None
    fim: str | None = None
    pendentes: bool = True


@app.post("/fidc/liquidez/carregar")
def post_carregar_liquidez(body: LiquidezLoadBody):
    """Carrega histórico de caixa/aplicações via GetPortfolioComposition (por período)."""
    try:
        from carregar_liquidez_idsf import carregar, _parse_date

        return carregar(
            inicio=_parse_date(body.inicio),
            fim=_parse_date(body.fim),
            so_pendentes=body.pendentes,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/fidc/atualizacoes")
def get_atualizacoes():
    """Datas da última atualização de cada fonte (IDSF, BDR, carteira própria)."""
    try:
        from atualizacoes import status_atualizacoes

        return status_atualizacoes()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/fidc/atualizar")
def post_atualizar_bases():
    """Inicia atualização de todas as bases até a última data disponível."""
    try:
        from atualizar_bases import iniciar_atualizacao

        return iniciar_atualizacao()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/fidc/atualizar/status")
def get_atualizar_status():
    """Status do job de atualização em background."""
    try:
        from atualizar_bases import status_job

        return status_job()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/fidc/atualizar/cancelar")
def post_cancelar_atualizacao():
    """Cancela job de atualização em andamento (libera servidor)."""
    try:
        from atualizar_bases import cancelar_job

        return cancelar_job()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/fidc/atualizar/reconciliar", dependencies=[Depends(exigir_admin)])
def post_reconciliar():
    """Recalcula campo 'conciliada' na série para dias marcados incorretamente como DIV."""
    try:
        from atualizar_bases import _reconciliar_conciliacao_serie
        return _reconciliar_conciliacao_serie()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/fidc/consignado")
def get_consignado(
    dataBase: str = Query(..., description="Data base dd/mm/yyyy ou YYYY-MM-DD"),
):
    """Consignado Privado (EstoqueBDR no Supabase): empresa → sacado/evento."""
    try:
        from consignado import montar_consignado

        return montar_consignado(dataBase)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/fidc/pdd")
def get_pdd(
    dataBase: str = Query(..., description="Data base dd/mm/yyyy ou YYYY-MM-DD"),
):
    """PDD por empresa (motor): afastamento/demissão/rescisão/NC + histórico."""
    try:
        from pdd import montar_pdd

        return montar_pdd(dataBase)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/fidc/inadimplencia")
def get_inadimplencia(
    dataBase: str = Query(..., description="Data base dd/mm/yyyy ou YYYY-MM-DD"),
):
    """Matriz de vencidos do consignado privado: mês de cessão × mês de vencimento."""
    try:
        from inadimplencia import montar_inadimplencia

        return montar_inadimplencia(dataBase)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/fidc/fluxo-caixa")
def get_fluxo_caixa(
    dataBase: str = Query(..., description="Data base dd/mm/yyyy ou YYYY-MM-DD"),
):
    """Aquisição × liquidações do consignado privado: TIR mensal e %CDI."""
    try:
        from inadimplencia import montar_fluxo_caixa

        return montar_fluxo_caixa(dataBase)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/fidc/passivo")
def get_passivo(
    dataBase: str = Query(..., description="Data base dd/mm/yyyy ou YYYY-MM-DD"),
):
    """Passivo por classe: PL, qtde, %CDI, cota marcada (app) vs IDSF."""
    try:
        from passivo import montar_passivo

        return montar_passivo(dataBase)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/fidc/passivo/vencimentos")
def get_passivo_vencimentos(
    dataBase: str = Query(..., description="Data base dd/mm/yyyy ou YYYY-MM-DD"),
):
    """Vencimentos mezanino agregados (classe / data / cotista)."""
    try:
        from passivo_vencimentos import montar_vencimentos

        return montar_vencimentos(dataBase)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/fidc/passivo/vencimentos/detalhe")
def get_passivo_vencimento_detalhe(
    dataVencimento: str = Query(..., description="Data de vencimento dd/mm/yyyy ou ISO"),
    dataBase: str = Query(..., description="Data base dd/mm/yyyy ou ISO"),
):
    """Cotistas e parcelas com amortização na data de vencimento."""
    try:
        from passivo_vencimentos import montar_detalhe_vencimento

        return montar_detalhe_vencimento(dataVencimento, dataBase)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/fidc/passivo/fluxo-caixa")
def get_passivo_fluxo_caixa(
    dataBase: str = Query(..., description="Data base dd/mm/yyyy ou YYYY-MM-DD"),
):
    """Caixa projetado: saídas de passivo + entradas de ativo (motor)."""
    try:
        from passivo_vencimentos import montar_fluxo_passivo_caixa

        return montar_fluxo_passivo_caixa(dataBase)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/fidc/passivo/cotistas")
def get_passivo_cotistas_lista():
    """Lista cotistas cadastrados (passivo Alpha)."""
    try:
        from passivo_cadastro import listar_cotistas

        return {"cotistas": listar_cotistas()}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/fidc/passivo/cotistas/{cotista_id}")
def get_passivo_cotista_posicao(
    cotista_id: int,
    dataBase: str = Query(..., description="Data base dd/mm/yyyy ou YYYY-MM-DD"),
):
    """Posição detalhada do cotista na data base."""
    try:
        from passivo_vencimentos import montar_posicao_cotista

        return montar_posicao_cotista(cotista_id, dataBase)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/fidc/passivo/extrato-cotista")
def get_passivo_extrato_cotista(
    cotistaId: int = Query(..., description="ID do cotista"),
    dataBase: str = Query(..., description="Data base dd/mm/yyyy ou YYYY-MM-DD"),
    classeIds: str | None = Query(
        None,
        description="IDs de classe separados por vírgula (vazio = todas)",
    ),
):
    """Evolução diária da posição do cotista (motor passivo)."""
    try:
        from passivo_vencimentos import montar_extrato_cotista

        ids: list[int] | None = None
        if classeIds and classeIds.strip():
            ids = [int(x.strip()) for x in classeIds.split(",") if x.strip()]
        return montar_extrato_cotista(cotistaId, dataBase, classe_ids=ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/fidc/passivo/cotistas/{cotista_id}/extrato")
def get_passivo_cotista_extrato(
    cotista_id: int,
    dataBase: str = Query(..., description="Data base dd/mm/yyyy ou YYYY-MM-DD"),
    classeIds: str | None = Query(
        None,
        description="IDs de classe separados por vírgula (vazio = todas)",
    ),
):
    """Evolução diária da posição do cotista (motor passivo)."""
    try:
        from passivo_vencimentos import montar_extrato_cotista

        ids: list[int] | None = None
        if classeIds and classeIds.strip():
            ids = [int(x.strip()) for x in classeIds.split(",") if x.strip()]
        return montar_extrato_cotista(cotista_id, dataBase, classe_ids=ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/fidc/extrato/sacados")
def get_extrato_sacados_lista(
    dataBase: str = Query(..., description="Data base dd/mm/yyyy ou YYYY-MM-DD"),
    cedente: str | None = Query(None, description="Filtrar por cedente"),
):
    """Lista sacados com posição na data base."""
    try:
        from extrato_sacado import listar_sacados

        return listar_sacados(dataBase, cedente=cedente)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/fidc/extrato/sacado")
def get_extrato_sacado(
    sacado: str = Query(..., description="Nome ou documento do sacado"),
    dataBase: str = Query(..., description="Data base dd/mm/yyyy ou YYYY-MM-DD"),
    modo: str = Query(
        "motor",
        description="motor (sem juros pós-venc) ou juros_pos_venc",
    ),
    cedente: str | None = Query(None, description="Filtrar por cedente"),
):
    """Evolução diária da posição do sacado (motor de carteira)."""
    try:
        from extrato_sacado import montar_extrato_sacado

        return montar_extrato_sacado(sacado, dataBase, modo=modo, cedente=cedente)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/fidc/passivo/classes")
def get_passivo_classes():
    try:
        from passivo_cadastro import listar_classes

        return {"classes": listar_classes()}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/fidc/passivo/classes")
def post_passivo_classe(body: dict):
    try:
        from passivo_cadastro import criar_classe

        return criar_classe(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.patch("/fidc/passivo/classes/{classe_id}")
def patch_passivo_classe(classe_id: int, body: dict):
    try:
        from passivo_cadastro import atualizar_classe

        return atualizar_classe(classe_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.delete("/fidc/passivo/classes/{classe_id}")
def delete_passivo_classe(classe_id: int):
    try:
        from passivo_cadastro import excluir_classe

        excluir_classe(classe_id)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/fidc/passivo/cotistas")
def post_passivo_cotista(body: dict):
    try:
        from passivo_cadastro import criar_cotista

        return criar_cotista(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.patch("/fidc/passivo/cotistas/{cotista_id}")
def patch_passivo_cotista(cotista_id: int, body: dict):
    try:
        from passivo_cadastro import atualizar_cotista

        return atualizar_cotista(cotista_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.delete("/fidc/passivo/cotistas/{cotista_id}")
def delete_passivo_cotista(cotista_id: int):
    try:
        from passivo_cadastro import excluir_cotista

        excluir_cotista(cotista_id)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/fidc/passivo/chamadas")
def get_passivo_chamadas(
    classe_id: int | None = Query(None),
    cotista_id: int | None = Query(None),
):
    try:
        from passivo_cadastro import listar_chamadas

        return {"chamadas": listar_chamadas(classe_id=classe_id, cotista_id=cotista_id)}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/fidc/passivo/chamadas")
def post_passivo_chamada(body: dict):
    try:
        from passivo_cadastro import criar_chamada

        return criar_chamada(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.patch("/fidc/passivo/chamadas/{chamada_id}")
def patch_passivo_chamada(chamada_id: int, body: dict):
    try:
        from passivo_cadastro import atualizar_chamada

        return atualizar_chamada(chamada_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.delete("/fidc/passivo/chamadas/{chamada_id}")
def delete_passivo_chamada(chamada_id: int):
    try:
        from passivo_cadastro import excluir_chamada

        excluir_chamada(chamada_id)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/fidc/divergencias")
def get_divergencias(
    desde: str | None = Query(None, description="YYYY-MM-DD ou dd/mm/yyyy"),
    ate: str | None = Query(None, description="YYYY-MM-DD ou dd/mm/yyyy"),
):
    """Lista dias com |ΔVP| ou |ΔPDD| (limpo) acima da tolerância (motor × IDSF)."""
    from divergencias import listar_divergencias

    def _opt(texto: str | None):
        if not texto:
            return None
        from divergencias import _parse_data

        return _parse_data(texto)

    try:
        return listar_divergencias(desde=_opt(desde), ate=_opt(ate))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/fidc/divergencias/detalhe")
def get_divergencia_detalhe(
    dataBase: str = Query(..., description="Data base dd/mm/yyyy ou YYYY-MM-DD"),
):
    """Resumo motor × BDR × IDSF e títulos divergentes vs EstoqueBDR do dia."""
    from divergencias import detalhe_divergencia

    try:
        return detalhe_divergencia(dataBase)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/fidc/risco")
def risco_fidc(
    dataBase: str = Query(..., description="Data base no formato dd/mm/yyyy"),
    fundo: str | None = Query(None, description="Código do fundo"),
):
    """Risco pela carteira BDR (aq−liq) + liquidez IDSF. Até D-2."""
    from datetime import datetime

    try:
        d = datetime.strptime(dataBase.strip()[:10], "%d/%m/%Y").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Data inválida: {dataBase}") from exc
    limite = data_base_maxima()
    minima = data_base_minima()
    if d < minima:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Data base {dataBase} indisponível. "
                f"Dashboard a partir de {minima.strftime('%d/%m/%Y')}."
            ),
        )
    if d > limite:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Data base {dataBase} ainda não liberada. "
                f"Sistema disponível até D-2 ({limite.strftime('%d/%m/%Y')})."
            ),
        )
    from calendario import e_dia_util, e_feriado, nome_feriado

    if not e_dia_util(d):
        if e_feriado(d):
            nome = nome_feriado(d) or "feriado"
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Data base {dataBase} é feriado ({nome}). "
                    "Não há acúmulo de juros nem relatório disponível."
                ),
            )
        raise HTTPException(
            status_code=400,
            detail=(
                f"Data base {dataBase} não é dia útil. "
                "Dashboard disponível apenas em dias úteis bancários."
            ),
        )
    # Motor sempre pelas movimentações BDR (sem BD_Estoque)
    from carteira_movimentacoes import CACHE_PATH

    if os.getenv("VERCEL") and not CACHE_PATH.exists():
        return calcular_pl_liquidez(dataBase)

    agora = time.monotonic()
    hit = _RISCO_CACHE.get(dataBase)
    if hit is not None and (agora - hit[0]) < _RISCO_CACHE_TTL_S:
        return hit[1]

    out = calcular_risco_fidc(dataBase)
    if isinstance(out, dict) and not out.get("erro"):
        _RISCO_CACHE[dataBase] = (agora, out)
        # Evita crescimento ilimitado se o usuário navegar muitas datas.
        if len(_RISCO_CACHE) > 64:
            mais_antigo = min(_RISCO_CACHE.items(), key=lambda kv: kv[1][0])[0]
            _RISCO_CACHE.pop(mais_antigo, None)
    return out
