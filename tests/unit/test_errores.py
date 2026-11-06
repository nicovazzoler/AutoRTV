import json
from types import SimpleNamespace

import anthropic
import httpx
from fastapi.testclient import TestClient

from app.agent import cliente as modulo
from app.main import app
from tests.unit.test_api import GRILLA, RECETA

BIEN = {"explicacion": "Listo", "tarjetas_json": json.dumps(RECETA["tarjetas"]), "columnas_salida": None,
        "correcciones_base_json": "[]"}


def _error(clase, estado: int, mensaje: str):
    respuesta = httpx.Response(estado, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    return clase(mensaje, response=respuesta, body=None)


def _respuesta(modelo: str):
    uso = SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    return SimpleNamespace(usage=uso, stop_reason="end_turn", model=modelo,
                           content=[SimpleNamespace(type="text", text=json.dumps(BIEN))])


def _claude(monkeypatch, crear):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-prueba")
    c = modulo.Claude()
    mensajes = SimpleNamespace(create=crear)
    c._cliente = SimpleNamespace(beta=SimpleNamespace(messages=mensajes), messages=mensajes)
    return c


def test_si_el_modelo_fuerte_no_existe_usa_el_barato(monkeypatch):
    modelos = []

    def crear(model, **_):
        modelos.append(model)
        if model == modulo.MODELO_FUERTE:
            raise _error(anthropic.NotFoundError, 404, "model: claude-sonnet-5-5")
        return _respuesta(model)

    r = _claude(monkeypatch, crear).pedir("sistema", [], "medium", fuerte=True)
    assert modelos == [modulo.MODELO_FUERTE, modulo.MODELO]
    assert r.datos == BIEN and "modelo barato" in r.aviso


def test_los_errores_de_anthropic_se_cuentan_en_castellano(monkeypatch):
    casos = [
        (_error(anthropic.AuthenticationError, 401, "invalid x-api-key"), "no es válida"),
        (_error(anthropic.BadRequestError, 400, "Your credit balance is too low"), "sin crédito"),
        (_error(anthropic.RateLimitError, 429, "rate limit"), "por minuto"),
        (_error(anthropic.InternalServerError, 529, "Overloaded"), "saturado"),
        (anthropic.APITimeoutError(request=httpx.Request("POST", "https://api.anthropic.com")), "tardó"),
    ]
    for error, esperado in casos:
        def crear(**_):
            raise error
        try:
            _claude(monkeypatch, crear).pedir("sistema", [], "low")
            raise AssertionError("tenía que fallar")
        except modulo.ErrorAgente as e:
            assert esperado in str(e), (error, str(e))


def test_el_asistente_responde_502_con_el_motivo(cliente, monkeypatch):
    class Caido(modulo.Grabado):
        def pedir(self, *a, **k):
            raise modulo.ErrorAgente("Anthropic está saturado o con problemas. Probá en unos minutos.")

        charlar = pedir

    monkeypatch.setattr(modulo, "proveedor_configurado", lambda: Caido([BIEN]))
    tabla_id = cliente.post("/api/tablas", files={"archivo": ("g.xlsx", GRILLA)}).json()["tabla_id"]
    for ruta in ("/api/asistente", "/api/asistente/charla"):
        r = cliente.post(ruta, json={"senal": RECETA, "pedido": "hola", "tabla_id": tabla_id})
        assert r.status_code == 502 and "saturado" in r.json()["detail"], r.text


def test_crear_senal_con_un_archivo_ilegible_da_422(cliente):
    r = cliente.post("/api/senales/crear", data={"nombre": "Rota"},
                     files={"grilla_cruda": ("g.xlsx", b"PK no es un excel"), "ejemplo": ("e.xlsx", GRILLA)})
    assert r.status_code == 422 and "No se pudo leer la grilla" in r.json()["detail"]


def test_un_error_inesperado_dice_que_fallo(cliente, monkeypatch):
    from app import almacen

    def roto():
        raise KeyError("columna")

    monkeypatch.setattr(almacen, "listar", roto)
    sin_tirar = TestClient(app, raise_server_exceptions=False, cookies=cliente.cookies)
    r = sin_tirar.get("/api/senales")
    assert r.status_code == 500
    assert r.json()["detail"].startswith("Error interno E-") and "KeyError" in r.json()["detail"]
