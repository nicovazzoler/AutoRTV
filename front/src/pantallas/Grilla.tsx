import { useEffect, useMemo, useState } from "react";
import { api, textoDeError } from "../api";
import { normalizar } from "../estado";
import { numeroSemana } from "../fechas";
import { CeldaEditable } from "../piezas/CeldaEditable";
import { Enlace } from "../piezas/Enlace";
import { aSenal } from "../ruta";
import { useSesion } from "../sesion";
import type { GrillaAbierta, Grupo } from "../tipos";

type Filtro = "todas" | Grupo["grupo"];

const FILTROS: { id: Filtro; nombre: string }[] = [
  { id: "todas", nombre: "Todas" },
  { id: "revisar", nombre: "Para revisar" },
  { id: "nueva_lista", nombre: "Nuevas" },
  { id: "base", nombre: "De la base" },
];
const MARCA: Record<Grupo["grupo"], string> = { base: "base", nueva_lista: "nueva", revisar: "revisar" };
const DE_A = 300;

export function Grilla({ senalId }: { senalId: string }) {
  const { senales, actualizarSemana } = useSesion();
  const senal = senales?.find((s) => s.id === senalId);
  const [datos, setDatos] = useState<GrillaAbierta | null>(null);
  const [sinSemana, setSinSemana] = useState(false);
  const [error, setError] = useState("");
  const [filtro, setFiltro] = useState<Filtro>("todas");
  const [programa, setPrograma] = useState("");
  const [q, setQ] = useState("");
  const [mostrar, setMostrar] = useState(DE_A);

  const recibir = (d: GrillaAbierta) => {
    setDatos(d);
    actualizarSemana(senalId, d.semana);
  };

  useEffect(() => {
    api.get<GrillaAbierta>(`/senales/${senalId}/abierta/grilla`).then(recibir).catch((e) => {
      if (e?.estado === 404) setSinSemana(true);
      else setError(textoDeError(e));
    });
  }, [senalId]);

  const indicePrograma = datos?.programa ? datos.columnas.indexOf(datos.programa) : -1;
  const programas = useMemo(() => {
    if (!datos || indicePrograma < 0) return [];
    return [...new Set(datos.filas.map((f) => String(f[indicePrograma] ?? "")).filter(Boolean))].sort((a, b) => a.localeCompare(b, "es"));
  }, [datos, indicePrograma]);

  // Avisos por celda ("fila|columna") y por fila, para marcarlos en la tabla.
  const avisos = useMemo(() => {
    const porCelda = new Map<string, string>();
    for (const a of datos?.validaciones ?? []) {
      if (a.nivel === "info" || !a.fila) continue;
      const clave = `${a.fila - 1}|${a.columna ?? ""}`;
      porCelda.set(clave, porCelda.has(clave) ? `${porCelda.get(clave)}\n${a.mensaje}` : a.mensaje);
    }
    return porCelda;
  }, [datos]);

  if (sinSemana) {
    return (
      <main className="contenido angosto">
        <header className="cabecera-textos">
          <span className="antetitulo">{senal?.nombre ?? senalId}</span>
          <h1 className="titulo">Todavía no hay grilla de esta semana</h1>
          <p className="bajada">Subila y acá vas a ver el EPG completo, fila por fila.</p>
        </header>
        <div className="botones"><Enlace a={aSenal(senalId, "subir")} className="boton principal">Subir grilla</Enlace></div>
      </main>
    );
  }
  if (!datos) {
    return <main className="contenido">{error ? <p className="error" role="alert">{error}</p> : <p className="tenue">Armando la grilla…</p>}</main>;
  }

  const cuenta = (g: Filtro) => (g === "todas" ? datos.grupos.length : datos.grupos.filter((x) => x.grupo === g).length);
  const buscado = normalizar(q.trim());
  const visibles = datos.filas
    .map((fila, i) => ({ fila, i, grupo: datos.grupos[i] }))
    .filter(({ grupo }) => filtro === "todas" || grupo.grupo === filtro)
    .filter(({ fila }) => !programa || String(fila[indicePrograma] ?? "") === programa)
    .filter(({ fila }) => !buscado || fila.some((v) => v !== null && normalizar(String(v)).includes(buscado)));

  const guardar = async (fila: number, columna: string, valor: string) => {
    setError("");
    try {
      recibir(await api.post<GrillaAbierta>(`/senales/${senalId}/abierta/celda`, { fila, columna, valor }));
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  const resumen = datos.semana.resumen;
  return (
    <main className="contenido">
      <header className="cabecera-textos">
        <span className="antetitulo">
          {resumen?.desde ? `Semana ${numeroSemana(resumen.desde)} · ` : ""}{datos.total_filas} filas · {datos.semana.nombre}
        </span>
        <h1 className="titulo">La grilla, fila por fila</h1>
        <p className="bajada">Así sale el EPG. Doble clic en una celda de contenido para corregirla: el cambio va a la base y vale para todas las veces que aparece esa pauta.</p>
      </header>

      <div className="filtros" role="group" aria-label="Filtros">
        <div className="campo">
          <span id="filtro-estado">Estado</span>
          <div className="botones" role="group" aria-labelledby="filtro-estado" style={{ gap: 6 }}>
            {FILTROS.map((f) => (
              <button key={f.id} type="button" className="boton chico" aria-pressed={filtro === f.id} onClick={() => setFiltro(f.id)}>
                {f.nombre} · {cuenta(f.id)}
              </button>
            ))}
          </div>
        </div>
        {programas.length > 0 && (
          <label className="campo">Programa
            <select className="entrada" value={programa} onChange={(e) => setPrograma(e.target.value)}>
              <option value="">Todos</option>
              {programas.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </label>
        )}
        <label className="campo" style={{ flex: "1 1 200px" }}>Buscar
          <input className="entrada" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Programa, capítulo…" />
        </label>
      </div>

      {error && <p className="error" role="alert">{error}</p>}

      <div className="desplazable con-alto">
        <table className="tabla-datos">
          <thead>
            <tr><th>Estado</th>{datos.columnas.map((c) => <th key={c}>{c}</th>)}</tr>
          </thead>
          <tbody>
            {visibles.slice(0, mostrar).map(({ fila, i, grupo }) => (
              <tr key={i}>
                <td title={[...grupo.motivos, avisos.get(`${i}|`)].filter(Boolean).join("\n") || undefined}>
                  <span className={`marca-estado ${grupo.grupo}`}>{MARCA[grupo.grupo]}</span>
                </td>
                {datos.columnas.map((col, j) => (
                  <CeldaEditable key={col} columna={col} valor={fila[j]} editable={datos.contenido.includes(col)}
                    clase={j === indicePrograma ? "programa" : ""} aviso={avisos.get(`${i}|${col}`)}
                    alGuardar={(v) => guardar(i, col, v)} />
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="botones" style={{ alignItems: "center" }}>
        <span className="chico tenue">Se ven {Math.min(mostrar, visibles.length)} de {visibles.length} filas.</span>
        {visibles.length > mostrar && <button type="button" className="boton chico" onClick={() => setMostrar(mostrar + DE_A)}>Ver más</button>}
        {datos.total_filas > datos.filas.length && <span className="chico tenue">La grilla tiene {datos.total_filas} filas; acá se muestran las primeras {datos.filas.length}.</span>}
      </div>
    </main>
  );
}
