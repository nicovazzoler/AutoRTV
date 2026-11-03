"""Las herramientas del agente del chat, en tres niveles.

- ver: el servidor las corre al momento y le devuelve el resultado (cualquier señal, lo que la persona puede ver);
- página: la web las hace sola (ir a una pantalla, abrir Agregar señal); no cambian datos;
- cambio: quedan como tarjeta con «Hacerlo» para la persona; el agente nunca cambia nada solo.
"""
import json
from dataclasses import dataclass, field

from app import almacen, historial, pautas, semanas

MAX_RESULTADO = 6000
MAX_FILAS = 20
PANTALLAS = ["inicio", "semana", "base", "configuracion", "administrar"]


def _tool(nombre: str, descripcion: str, propiedades: dict, requeridas: list[str]) -> dict:
    return {"name": nombre, "description": descripcion,
            "input_schema": {"type": "object", "properties": propiedades, "required": requeridas,
                             "additionalProperties": False}}


_SENAL = {"type": "string", "description": "id de la señal (de listar_senales)"}

VER = [
    _tool("listar_senales", "Las señales que hay, con su semana abierta: fechas, cuántas para revisar y si se confirmó.",
          {"texto": {"type": "string", "description": "parte del nombre para filtrar; vacío = todas"}}, []),
    _tool("ver_semana", "La semana abierta de una señal: el resumen y las pautas de un grupo con su motivo.",
          {"senal": _SENAL, "grupo": {"type": "string", "enum": ["revisar", "nuevas"]}}, ["senal"]),
    _tool("buscar_pautas", "Pautas guardadas en la base de una señal (cómo quedó cada programa o capítulo).",
          {"senal": _SENAL, "texto": {"type": "string", "description": "texto a buscar; vacío = las últimas"},
           "columna": {"type": "string"}, "valor": {"type": "string", "description": "con columna: filtra por ese valor"}},
          ["senal"]),
    _tool("ver_reglas", "Las reglas (tarjetas) de una señal, en orden, y cómo se lee su grilla.", {"senal": _SENAL}, ["senal"]),
    _tool("ver_historial", "Las últimas cargas de semanas con lo que se cambió (corregidas, aceptadas, reglas).",
          {"senal": {"type": "string", "description": "id de la señal; vacío = todas"}}, []),
]
PAGINA = [
    _tool("ir_a", "Llevar a la persona a una pantalla. Para semana, base y configuracion hace falta la señal.",
          {"pantalla": {"type": "string", "enum": PANTALLAS}, "senal": {"type": "string"}}, ["pantalla"]),
    _tool("nueva_senal", "Abrir Agregar señal con el nombre ya escrito.", {"nombre": {"type": "string"}}, ["nombre"]),
]
CAMBIO = [
    _tool("armar_reglas", "Que el agente de reglas arme las reglas de la señal desde sus ejemplos.", {"senal": _SENAL},
          ["senal"]),
    _tool("corregir_pautas", "Cambiar una columna en todas las pautas de la base que cumplen un filtro.",
          {"senal": _SENAL, "filtro": {"type": "object", "description": "{columna: valor} de las pautas a cambiar",
                                       "additionalProperties": {"type": "string"}},
           "columna": {"type": "string"}, "valor": {"type": "string", "description": "vacío = dejarla vacía"}},
          ["senal", "filtro", "columna", "valor"]),
    _tool("confirmar_semana", "Confirmar la semana abierta de la señal: lo nuevo pasa a la base.", {"senal": _SENAL},
          ["senal"]),
]
OTRAS = [
    _tool("proponer_reglas", "Pedirle al agente de reglas una propuesta de cambios de tarjetas, columnas o de la base "
                             "para una señal. Él la prueba y la persona la aplica.",
          {"senal": {"type": "string", "description": "vacío = la señal activa"},
           "pedido": {"type": "string", "description": "qué cambiar, en las palabras de la persona"}}, ["pedido"]),
    _tool("recordar", "Guardar algo de la persona para las próximas charlas (cómo trabaja, qué señales lleva).",
          {"texto": {"type": "string"}}, ["texto"]),
]
DEFINICIONES = VER + PAGINA + CAMBIO + OTRAS
NIVEL = {t["name"]: n for n, lista in (("ver", VER), ("pagina", PAGINA), ("cambio", CAMBIO), ("otra", OTRAS))
         for t in lista}


def _corto(v, largo: int = 80):
    return v if not isinstance(v, str) or len(v) <= largo else v[:largo] + "…"


@dataclass
class Estado:
    """Lo que juntó una charla: lo que la web hace sola, lo que espera «Hacerlo» y lo que se propone."""
    usuario: str
    admin: bool
    activa: str | None
    senales: dict[str, str]  # id → nombre
    acciones: list[dict] = field(default_factory=list)
    propuestas: list[dict] = field(default_factory=list)
    recordar: str = ""

    def usar(self, nombre: str, datos: dict) -> str:
        """Corre o anota una herramienta y devuelve el texto que vuelve al agente."""
        nivel = NIVEL.get(nombre)
        if nivel is None:
            return f"No existe la herramienta {nombre}."
        senal = str(datos.get("senal") or "")
        if senal and senal not in self.senales:
            return f"No existe la señal «{senal}». Usá listar_senales para ver los ids."
        try:
            if nivel == "ver":
                texto = json.dumps(getattr(self, "_" + nombre)(**datos), ensure_ascii=False, default=str)
                return texto[:MAX_RESULTADO]
            return getattr(self, "_" + nombre)(**datos)
        except TypeError as e:
            return f"Parámetros mal puestos: {e}"
        except Exception as e:  # un dato que no está (sin semana abierta, etc.) vuelve como texto
            return f"No se pudo: {getattr(e, 'detail', None) or e}"

    def _accion(self, nivel: str, tipo: str, senal: str, descripcion: str, **extra) -> None:
        self.acciones.append({"nivel": nivel, "tipo": tipo, "senal": senal, "nombre_senal": self.senales.get(senal, ""),
                              "otra_senal": bool(senal) and senal != self.activa, "descripcion": descripcion,
                              "pantalla": "", "nombre": "", **extra})

    # --- ver ---

    def _listar_senales(self, texto: str = "") -> list[dict]:
        abiertas = semanas.todas()
        lista = []
        for i, nombre in self.senales.items():
            if texto.lower() not in nombre.lower():
                continue
            resumen = (abiertas.get(i) or {}).get("resumen") or {}
            lista.append({"id": i, "nombre": nombre, "activa": i == self.activa,
                          "semana": {k: resumen.get(k) for k in ("desde", "hasta", "revisar", "filas")} if resumen else None,
                          "confirmada": bool((abiertas.get(i) or {}).get("confirmada"))})
        return lista

    def _ver_semana(self, senal: str, grupo: str = "revisar") -> dict:
        from app.api import rutas

        abierta = rutas._semana_abierta(senal, rutas._receta(senal))
        if abierta.get("semana") is None:
            return {"semana": None, "nota": "No tiene semana abierta: hay que subir la grilla."}
        pautas_grupo = abierta["revisar" if grupo == "revisar" else "nuevas"]
        return {"resumen": abierta["semana"]["resumen"], "grupo": grupo, "total": len(pautas_grupo),
                "pautas": [{"hash": g["hash"], "veces": g["veces"], "motivos": g["motivos"],
                            "salida": {k: _corto(v) for k, v in g["salida"].items() if v not in (None, "")}}
                           for g in pautas_grupo[:MAX_FILAS]]}

    def _buscar_pautas(self, senal: str, texto: str = "", columna: str = "", valor: str = "") -> dict:
        r = pautas.listar(senal, None, texto, 0, {columna: valor} if columna and valor else None)
        return {"total": r["total"], "pautas": [
            {"hash": p["hash"], "estado": p["estado"],
             "salida": {k: _corto(v) for k, v in (p["salida"] or {}).items() if v not in (None, "")}}
            for p in r["pautas"][:MAX_FILAS]]}

    def _ver_reglas(self, senal: str) -> dict:
        receta = almacen.leer(senal)
        return {"entrada": receta.entrada.model_dump(exclude_defaults=True),
                "tarjetas": [t.model_dump(exclude_none=True) for t in receta.tarjetas],
                "columnas_salida": receta.salida.columnas}

    def _ver_historial(self, senal: str = "") -> list[dict]:
        cargas = historial.cargas(None if self.admin else self.usuario)
        return [c for c in cargas if not senal or c["senal_id"] == senal][:MAX_FILAS]

    # --- página ---

    def _ir_a(self, pantalla: str, senal: str = "") -> str:
        if pantalla not in PANTALLAS:
            return f"Las pantallas son {', '.join(PANTALLAS)}."
        if pantalla in ("semana", "base", "configuracion") and not senal:
            return "Para esa pantalla decime la señal."
        if pantalla == "administrar" and not self.admin:
            return "Administrar es solo para admin."
        destino = f"{pantalla} de {self.senales[senal]}" if senal else pantalla
        self._accion("pagina", "ir_a", senal, f"Ir a {destino}", pantalla=pantalla)
        return "Listo: la web la abre sola."

    def _nueva_senal(self, nombre: str) -> str:
        self._accion("pagina", "nueva_senal", "", f"Abrir Agregar señal con «{nombre}»", nombre=nombre)
        return "Listo: la web abre Agregar señal con ese nombre."

    # --- cambio ---

    def _armar_reglas(self, senal: str) -> str:
        if not almacen.listar_ejemplos(senal):
            return "Esa señal no tiene ejemplos: sin ejemplo no se pueden armar las reglas solas."
        self._accion("cambio", "armar_reglas", senal, f"Armar las reglas de {self.senales[senal]} desde sus ejemplos")
        return "Quedó como propuesta: la persona lo confirma con «Hacerlo»."

    def _columnas(self, senal: str) -> list[str]:
        """Las columnas del EPG de la señal; si no eligió ninguna, las que guarda su base."""
        elegidas = almacen.leer(senal).salida.columnas
        return elegidas or list(dict.fromkeys(c for p in pautas.base(senal).values() for c in p["salida"]))

    def _corregir_pautas(self, senal: str, filtro: dict, columna: str, valor: str) -> str:
        if not filtro:
            return "Hace falta un filtro: no se cambian todas las pautas de una."
        validas = self._columnas(senal)
        # Una columna que no existe filtra por "vacío" y coincidiría con todas las pautas.
        malas = [c for c in [*filtro, columna] if c not in validas]
        if malas:
            return (f"Esas columnas no existen en {self.senales[senal]}: {', '.join(map(str, malas))}. "
                    f"Las columnas son: {', '.join(validas)}.")
        hashes = pautas.hashes_filtrados(senal, filtros={str(k): str(v) for k, v in filtro.items()})
        if not hashes:
            return "Ninguna pauta cumple ese filtro: probá buscar_pautas para ver cómo están escritas."
        cuantas = "1 pauta" if len(hashes) == 1 else f"{len(hashes)} pautas"
        condicion = ", ".join(f"{k} = {v}" for k, v in filtro.items())
        self._accion("cambio", "corregir_pautas", senal,
                     f"En {self.senales[senal]}, en {'' if len(hashes) == 1 else 'las '}{cuantas} con {condicion}, "
                     f"poner {columna} = {valor or '(vacío)'}",
                     filtro=filtro, hashes=hashes, columna=columna, valor=valor or None, pautas=len(hashes))
        return f"Quedó como propuesta para {cuantas}: la persona lo confirma con «Hacerlo»."

    def _confirmar_semana(self, senal: str) -> str:
        if semanas.leer(senal) is None:
            return "Esa señal no tiene semana abierta."
        self._accion("cambio", "confirmar_semana", senal, f"Confirmar la semana de {self.senales[senal]}")
        return "Quedó como propuesta: la persona lo confirma con «Hacerlo»."

    # --- otras ---

    def _proponer_reglas(self, pedido: str, senal: str = "") -> str:
        senal = senal or self.activa or ""
        if not senal:
            return "No hay una señal activa: preguntale en cuál, o llevala a la señal con ir_a."
        self.propuestas.append({"senal": senal, "nombre_senal": self.senales.get(senal, ""), "pedido": pedido,
                                "otra_senal": senal != self.activa})
        return "El agente de reglas arma la propuesta y la prueba; la persona la ve con «Aplicar»."

    def _recordar(self, texto: str) -> str:
        self.recordar = texto
        return "Anotado."
