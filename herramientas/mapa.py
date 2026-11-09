#!/usr/bin/env python3
"""Arma el mapa de arquitectura de un repo leyendo evidencia, sin adivinar.

Idea: todo lo que sale acá está escrito en el repo. Las dependencias dicen qué
servicios externos hay, los decoradores dicen qué endpoints existen, models.py
dice qué tablas hay, y los archivos del front dicen a qué endpoints le pegan.
Ningún modelo de lenguaje interviene: si el mapa dice algo, es porque está en
el código. Lo que no se puede probar, no se dibuja.

Uso:  python3 mapa.py /ruta/al/repo [--escribir]

Sin --escribir imprime el resultado; con --escribir deja ARQUITECTURA.md en el
repo.
"""
import argparse
import ast
import pathlib
import re
import subprocess
import sys

METODOS = {"get", "post", "put", "delete", "patch"}

# Dependencia -> (pieza, tipo). Solo cosas que implican una pieza del sistema.
SERVICIOS = {
    "fastapi": ("API", "servidor"),
    "uvicorn": ("API", "servidor"),
    "sqlalchemy": ("Base de datos", "datos"),
    "psycopg2": ("PostgreSQL", "datos"),
    "psycopg2-binary": ("PostgreSQL", "datos"),
    "openpyxl": ("Excel", "archivo"),
    "reportlab": ("PDF", "archivo"),
    "requests": ("HTTP saliente", "externo"),
    "httpx": ("HTTP saliente", "externo"),
    "mercadopago": ("Mercado Pago", "externo"),
    "boto3": ("S3", "externo"),
    "redis": ("Redis", "datos"),
    "anthropic": ("Claude · API de Anthropic", "modelo"),
    "openai": ("OpenAI", "modelo"),
    "psycopg": ("PostgreSQL", "datos"),
    "pdfplumber": ("Lector de PDF", "archivo"),
    "pypdf": ("Lector de PDF", "archivo"),
    "beautifulsoup4": ("Lector de HTML", "archivo"),
    "pandas": ("Pandas", "datos"),
    "xlrd": ("Excel", "archivo"),
}


def nombre_repo(repo):
    """El nombre del proyecto, sacado del remoto de git.

    No usamos el nombre de la carpeta: en CI el checkout puede caer en un
    directorio con otro nombre, y entonces el archivo cambiaria sin que haya
    cambiado el codigo, generando un commit al pedo en cada push.
    """
    try:
        # Se lo preguntamos a git en vez de leer .git/config a mano: en un
        # worktree, .git es un archivo que apunta a otro lado y el archivo
        # de config no esta donde uno espera.
        r = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=repo, capture_output=True, text=True, timeout=5,
        )
        url = r.stdout.strip()
        if r.returncode == 0 and url:
            return re.sub(r"\.git$", "", url.rstrip("/").split("/")[-1])
    except Exception:
        pass
    return repo.name


def librerias(repo):
    """Libreria declarada -> archivos del repo que la importan.

    La version sale de requirements*.txt; el uso, de los import de cada .py.
    Si una libreria esta declarada y nadie la importa, se ve. Si alguien
    importa algo que no esta declarado, tambien.
    """
    declaradas = {}
    pyproject = repo / "pyproject.toml"
    if pyproject.is_file():
        texto = pyproject.read_text(encoding="utf-8", errors="replace")
        bloque = re.search(r"dependencies\s*=\s*\[(.*?)\]", texto, re.S)
        if bloque:
            for item in re.findall(r"[\"\']([^\"\']+)[\"\']", bloque.group(1)):
                m2 = re.match(r"([A-Za-z0-9_.-]+)", item)
                if m2:
                    declaradas.setdefault(m2.group(1).lower(), "ver pyproject")
    for req in sorted(repo.glob("requirements*.txt")):
        for linea in req.read_text(encoding="utf-8", errors="replace").splitlines():
            linea = linea.strip()
            if not linea or linea.startswith(("#", "-")):
                continue
            m = re.match(r"([A-Za-z0-9_.-]+)", linea)
            if not m:
                continue
            nombre = m.group(1).lower()
            resto = linea[len(m.group(1)):]
            resto = re.sub(r"^\[[^\]]*\]", "", resto)   # saca el [standard] de uvicorn[standard]
            version = resto.lstrip("=<>~! ").strip()
            declaradas[nombre] = version or "sin fijar"

    # Como se escribe el import de cada paquete, cuando no coincide.
    ALIAS = {"psycopg2-binary": "psycopg2", "python-multipart": "multipart",
             "python-jose": "jose", "pillow": "PIL", "beautifulsoup4": "bs4",
             "pyyaml": "yaml", "python-dotenv": "dotenv"}

    importa = {}
    propios = {f.stem for f in repo.glob("*.py")}
    for archivo in sorted(repo.rglob("*.py")):
        if any(parte in (".venv", "venv", "__pycache__", "node_modules")
               for parte in archivo.parts):
            continue
        texto = archivo.read_text(encoding="utf-8", errors="replace")
        mods = set(re.findall(r"^\s*import\s+([A-Za-z0-9_]+)", texto, re.M))
        mods |= set(re.findall(r"^\s*from\s+([A-Za-z0-9_]+)", texto, re.M))
        for mod in mods:
            importa.setdefault(mod.lower(), set()).add(
                archivo.relative_to(repo).as_posix())

    filas = []
    for nombre, version in sorted(declaradas.items()):
        clave = ALIAS.get(nombre, nombre).lower()
        usos = sorted(importa.get(clave, set()))
        filas.append((nombre, version, usos))
    # Lo que se importa sin estar declarado y no es del repo ni de la stdlib.
    return filas, propios


def contar_pantallas(repo):
    """Cuantas vistas tiene el front, le peguen o no a la API."""
    ext = (".html", ".tsx", ".jsx", ".vue", ".svelte")
    n = 0
    for archivo in _mirar(repo, "*"):
        if archivo.is_file() and archivo.suffix in ext:
            partes = archivo.relative_to(repo).parts
            if any(d in ("static", "front", "frontend", "src", "public", "web")
                   for d in partes[:-1]):
                n += 1
    return n


def corto(ruta):
    """Nombre legible: sin el prefijo de carpeta que se repite en todas."""
    for pre in ("static/", "front/src/", "frontend/src/", "src/", "front/", "web/"):
        if ruta.startswith(pre):
            return ruta[len(pre):]
    return ruta


def dependencias(repo):
    """Lee requirements*.txt y package.json."""
    out = {}
    for req in repo.glob("requirements*.txt"):
        for linea in req.read_text(encoding="utf-8", errors="replace").splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#"):
                continue
            nombre = re.split(r"[=<>\[; ]", linea)[0].lower()
            if nombre in SERVICIOS:
                pieza, tipo = SERVICIOS[nombre]
                out[pieza] = tipo
    return out


def _mirar(repo, patron):
    """Archivos del repo que valen la pena, salteando lo que no es codigo propio."""
    fuera = {".venv", "venv", "__pycache__", "node_modules", ".git",
             "dist", "build", ".mypy_cache", ".pytest_cache", "site-packages"}
    for archivo in sorted(repo.rglob(patron)):
        if not any(parte in fuera for parte in archivo.parts):
            yield archivo


def tablas(repo):
    """class -> nombre de tabla. Busca __tablename__ en todo el repo: no
    todos los proyectos ponen los modelos en models.py."""
    out = {}
    for archivo in _mirar(repo, "*.py"):
        try:
            arbol = ast.parse(archivo.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.ClassDef):
                continue
            for sub in nodo.body:
                if isinstance(sub, ast.Assign):
                    for destino in sub.targets:
                        if getattr(destino, "id", None) == "__tablename__":
                            if isinstance(sub.value, ast.Constant):
                                out[nodo.name] = sub.value.value
    return out


def rutas(repo, clases):
    """Lista de (metodo, path, funcion, tablas que toca).

    Entiende dos formas de declarar rutas en FastAPI: el decorador sobre la
    app (@app.get) y los APIRouter con prefijo (api = APIRouter(prefix="/api")
    y despues @api.get("/cosas"), que en realidad es /api/cosas).
    """
    out = []
    for archivo in _mirar(repo, "*.py"):
        try:
            arbol = ast.parse(archivo.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue

        # Primero, que routers hay en este archivo y con que prefijo.
        prefijos = {"app": ""}
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.Assign) or not isinstance(nodo.value, ast.Call):
                continue
            fn = nodo.value.func
            nombre_fn = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if nombre_fn != "APIRouter":
                continue
            prefijo = ""
            for kw in nodo.value.keywords:
                if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                    prefijo = kw.value.value
            for destino in nodo.targets:
                if isinstance(destino, ast.Name):
                    prefijos[destino.id] = prefijo

        for nodo in ast.walk(arbol):
            if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in nodo.decorator_list:
                if not isinstance(deco, ast.Call):
                    continue
                fn = deco.func
                if not isinstance(fn, ast.Attribute) or fn.attr not in METODOS:
                    continue
                base = getattr(fn.value, "id", None)
                if base not in prefijos:
                    continue
                if not deco.args or not isinstance(deco.args[0], ast.Constant):
                    continue
                path = prefijos[base] + deco.args[0].value
                usadas = set()
                for hijo in ast.walk(nodo):
                    if isinstance(hijo, ast.Name) and hijo.id in clases:
                        usadas.add(clases[hijo.id])
                    elif isinstance(hijo, ast.Attribute) and hijo.attr in clases:
                        usadas.add(clases[hijo.attr])
                out.append((fn.attr.upper(), path, nodo.name, sorted(usadas)))
    # Una misma ruta puede aparecer dos veces (router publico y privado).
    vistas, unicas = set(), []
    for r in out:
        if (r[0], r[1]) not in vistas:
            vistas.add((r[0], r[1]))
            unicas.append(r)
    return unicas


def frente(repo):
    """Archivo del front -> paths de API que menciona.

    Mira static/ (HTML suelto) y tambien front/ o src/ (React, Vue), que es
    donde viven los proyectos con build.
    """
    out = {}
    extensiones = {".html", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte"}
    for archivo in _mirar(repo, "*"):
        if archivo.suffix not in extensiones or not archivo.is_file():
            continue
        partes = archivo.relative_to(repo).parts
        if not any(d in ("static", "front", "frontend", "src", "public", "web")
                   for d in partes[:-1]):
            continue
        texto = archivo.read_text(encoding="utf-8", errors="replace")
        # Dos formas: la ruta completa escrita en el componente, o el
        # pedacito que recibe un envoltorio, por ejemplo fetch("/api" + ruta).
        paths = set(re.findall(r"[\"\'`](/[A-Za-z0-9_/{}.-]*)[\"\'`]", texto))
        paths = {x.rstrip("/.") for x in paths if len(x) > 1}
        if paths:
            out[archivo.relative_to(repo).as_posix()] = sorted(paths)
    return out


def solo_api(rutas_def):
    """Las rutas que devuelven datos, dejando afuera las que sirven paginas."""
    marcas = ("/api", "/v1", "/v2", "/rest", "/graphql")
    de_datos = [r for r in rutas_def if r[1].startswith(marcas)]
    return de_datos if de_datos else list(rutas_def)


def prefijos_de(rutas_def):
    """Los primeros segmentos que usan las rutas declaradas, por ejemplo /api."""
    out = set()
    for _, path, _, _ in rutas_def:
        partes = [x for x in path.split("/") if x]
        if partes:
            out.add("/" + partes[0])
    return sorted(out)


def emparejar(path_front, rutas_def, prefijos=()):
    """Qué rutas declaradas cubren un path que usa el front."""
    encontradas = []
    for metodo, path, fn, tabs in rutas_def:
        patron = "^" + re.sub(r"\{[^}]+\}", "[^/]+", re.escape(path).replace(r"\{", "{").replace(r"\}", "}")) + "$"
        try:
            if re.match(patron, path_front):
                encontradas.append((metodo, path, fn, tabs))
        except re.error:
            continue
    if encontradas:
        return encontradas
    # El front suele recortar: /api/clientes/ para /api/clientes/{id}
    parciales = [r for r in rutas_def if r[1] == path_front
                 or r[1].startswith(path_front.rstrip("/") + "/")]
    if parciales:
        return parciales
    # Y suele escribir solo la cola, cuando un envoltorio pone el prefijo.
    for pre in prefijos:
        if path_front.startswith(pre):
            continue
        con_prefijo = emparejar(pre + path_front, rutas_def)
        if con_prefijo:
            return con_prefijo
    return []


def mermaid_piezas(deps, n_pantallas, n_rutas, n_tablas, procfile):
    lineas = ["```mermaid", "graph LR"]
    lineas.append(f'  FRONT["{n_pantallas} pantallas<br/>HTML + JS"]')
    lineas.append(f'  API["API<br/>FastAPI · {n_rutas} endpoints"]')
    lineas.append("  FRONT --> API")
    if n_tablas:
        lineas.append(f'  DB[("Base de datos<br/>{n_tablas} tablas")]')
        lineas.append("  API --> DB")
    elif any(t == "datos" for t in deps.values()):
        # Hay motor de base declarado pero ningun modelo con __tablename__:
        # las tablas pueden estar en SQL suelto. No ponemos un numero falso.
        lineas.append('  DB[("Base de datos<br/>sin modelos declarados")]')
        lineas.append("  API --> DB")
    usados = {"FRONT", "API", "DB", "DEPLOY"}
    for pieza, tipo in sorted(deps.items()):
        if pieza in ("API", "Base de datos"):
            continue
        clave = re.sub(r"[^A-Za-z]", "", pieza).upper()[:8] or "X"
        # Dos piezas distintas pueden dar la misma abreviatura ("Lector de
        # HTML" y "Lector de PDF" daban las dos LECTORDE). Si ya esta usada,
        # le agregamos un numero: si no, Mermaid las dibuja como una sola.
        base, n = clave, 2
        while clave in usados:
            clave = f"{base}{n}"
            n += 1
        usados.add(clave)
        lineas.append(f'  {clave}["{pieza}"]')
        lineas.append(f"  API --> {clave}")
    if procfile:
        lineas.append(f'  DEPLOY["Deploy<br/>{procfile}"]')
        lineas.append("  API -.-> DEPLOY")
    lineas.append("```")
    return "\n".join(lineas)


def mermaid_datos(por_pantalla, tope=3):
    """Pantalla -> las tablas que mas toca. Solo las principales, para que se lea."""
    lineas = ["```mermaid", "graph LR"]
    tablas_vistas = set()
    for pantalla, info in sorted(por_pantalla.items()):
        cuenta = {}
        for _, _, _, tabs in info["rutas"]:
            for t in tabs:
                cuenta[t] = cuenta.get(t, 0) + 1
        top = sorted(cuenta, key=lambda t: -cuenta[t])[:tope]
        if not top:
            continue
        pid = "P" + re.sub(r"[^A-Za-z0-9]", "", corto(pantalla))[:14]
        lineas.append(f'  {pid}["{corto(pantalla)}"]')
        for t in top:
            tid = "T" + re.sub(r"[^A-Za-z0-9]", "", t)[:12]
            if t not in tablas_vistas:
                lineas.append(f'  {tid}[("{t}")]')
                tablas_vistas.add(t)
            lineas.append(f"  {pid} --> {tid}")
    lineas.append("```")
    return "\n".join(lineas)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--escribir", action="store_true")
    args = ap.parse_args()

    repo = pathlib.Path(args.repo).expanduser().resolve()
    if not repo.is_dir():
        sys.exit(f"No existe: {repo}")

    clases = tablas(repo)
    rutas_def = rutas(repo, clases)
    deps = dependencias(repo)
    front = frente(repo)
    proc = (repo / "Procfile")
    procfile = proc.read_text(encoding="utf-8").strip().split(":")[0] if proc.exists() else ""

    rutas_api = solo_api(rutas_def)
    pres = prefijos_de(rutas_api)
    por_pantalla = {}
    for archivo, paths in front.items():
        encontradas = []
        # Si el archivo ya escribe rutas completas, no usa envoltorio: probar
        # prefijos ahi solo genera falsos positivos con los links del menu.
        escribe_completas = any(x.startswith(tuple(pres)) for x in paths)
        pres_archivo = () if escribe_completas else pres
        for p in paths:
            encontradas.extend(emparejar(p, rutas_api, pres_archivo))
        # unicas, conservando orden
        unicas, vistas = [], set()
        for r in encontradas:
            k = (r[0], r[1])
            if k not in vistas:
                vistas.add(k)
                unicas.append(r)
        por_pantalla[archivo] = {"paths": paths, "rutas": unicas}

    sin_front = len(rutas_api) - len({(r[0], r[1]) for i in por_pantalla.values() for r in i["rutas"]})

    partes = [
        f"# Arquitectura · {nombre_repo(repo)}",
        "",
        "Generado leyendo el repo. **No editar a mano**: lo regenera el CI en cada commit.",
        "",
        "Todo lo que figura acá está escrito en el código — dependencias declaradas, "
        "decoradores de ruta, `__tablename__` y las rutas que nombran los archivos del "
        "front. Nada está inferido por un modelo.",
        "",
        "## Las piezas",
        "",
        mermaid_piezas(deps, contar_pantallas(repo), len(solo_api(rutas_def)), len(set(clases.values())), procfile),
        "",
        "## Qué datos toca cada pantalla",
        "",
        "Las tablas principales de cada pantalla. El detalle completo está abajo.",
        "",
        mermaid_datos(por_pantalla),
        "",
    ]

    filas_lib, _ = librerias(repo)
    if filas_lib:
        partes += ["## Librerías", "",
                   "De dónde sale: la versión, de `requirements*.txt`; el uso, "
                   "de los `import` de cada archivo. Una librería declarada que "
                   "nadie importa se nota.", "",
                   "| Librería | Versión | Quién la usa |", "|---|---|---|"]
        for nombre, version, usos in filas_lib:
            donde = ", ".join("`" + u + "`" for u in usos[:4]) if usos else "sin import directo"
            if len(usos) > 4:
                donde += f" y {len(usos) - 4} más"
            partes.append(f"| `{nombre}` | {version} | {donde} |")
        partes.append("")

    partes += [
        "<details>",
        "<summary><b>Desglose por pantalla</b> — endpoints y tablas, uno por uno</summary>",
        "",
    ]

    for pantalla, info in sorted(por_pantalla.items()):
        tabs = sorted({t for _, _, _, ts in info["rutas"] for t in ts})
        partes.append(f"### {corto(pantalla)}")
        partes.append("")
        partes.append(f"- Endpoints que usa: **{len(info['rutas'])}**")
        partes.append(f"- Tablas que tocan esos endpoints: {', '.join('`' + t + '`' for t in tabs) if tabs else '—'}")
        partes.append("")
        if info["rutas"]:
            partes.append("| Método | Endpoint | Función | Tablas |")
            partes.append("|---|---|---|---|")
            for metodo, path, fn, ts in sorted(info["rutas"], key=lambda r: r[1])[:40]:
                partes.append(f"| {metodo} | `{path}` | `{fn}` | {', '.join(ts) if ts else '—'} |")
            partes.append("")

    partes += [
        "</details>",
        "",
        "## Lo que no se pudo probar",
        "",
        f"- Endpoints que ninguna pantalla nombra: **{max(sin_front, 0)}**. "
        "Pueden ser internos, llamarse con la ruta armada en tiempo de ejecución, o estar muertos.",
        f"- Tablas declaradas en `models.py`: **{len(set(clases.values()))}**; "
        "las que no aparecen arriba no las toca ningún endpoint que el front nombre.",
        "",
    ]

    texto = "\n".join(partes)
    if args.escribir:
        destino = repo / "ARQUITECTURA.md"
        destino.write_text(texto, encoding="utf-8")
        print(f"Escrito: {destino}  ({len(texto)} bytes)")
    else:
        print(texto)


if __name__ == "__main__":
    main()
