import { useEffect, useMemo, useState } from "react";
import { api, textoDeError } from "../api";
import { normalizar } from "../estado";
import { CeldaEditable } from "./CeldaEditable";
import { Recorrido, type Parecida } from "./Recorrido";
import { cumple, FilaFiltros, type Filtros } from "./FiltrosColumna";
import { useSesion } from "../sesion";
import type { GrillaAbierta, Grupo } from "../tipos";

export type Filtro = "todas" | Grupo["grupo"];

const MARCA: Record<Grupo["grupo"], string> = { base: "Base", nueva_lista: "Nueva", revisar: "Revisar" };
const DE_A = 300;

/** La semana emisión por emisión, filtrada por estado (lo eligen los botones de la Semana) y por columna. */
export function TablaGrilla({ senalId, filtro }: { senalId: string; filtro: Filtro }) {
  const { actualizarSemana } = useSesion();
  const [datos, setDatos] = useState<GrillaAbierta | null>(null);
  const [error, setError] = useState("");
  const [programa, setPrograma] = useState("");
  const [q, setQ] = useState("");
  const [filtros, setFiltros] = useState<Filtros>({});
  const [mostrar, setMostrar] = useState(DE_A);
  const [parecidas, setParecidas] = useState<Parecida[] | null>(null);

  const recibir = (d: GrillaAbierta) => {
    setDatos(d);
    actualizarSemana(senalId, d.semana);
  };

  useEffect(() => {
    api.get<GrillaAbierta>(`/senales/${senalId}/abierta/grilla`).then(recibir).catch((e) => setError(textoDeError(e)));
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

  if (!datos) {
    return error ? <p className="error" role="alert">{error}</p> : <p className="tenue">Armando la grilla…</p>;
  }

  const buscado = normalizar(q.trim());
  const visibles = datos.filas
    .map((fila, i) => ({ fila, i, grupo: datos.grupos[i] }))
    .filter(({ grupo }) => filtro === "todas" || grupo.grupo === filtro)
    .filter(({ fila }) => !programa || String(fila[indicePrograma] ?? "") === programa)
    .filter(({ fila }) => !buscado || fila.some((v) => v !== null && normalizar(String(v)).includes(buscado)))
    .filter(({ fila }) => cumple((c) => fila[datos.columnas.indexOf(c)], filtros));

  const guardar = async (fila: number, columna: string, valor: string) => {
    setError("");
    try {
      const antes = datos.filas[fila][datos.columnas.indexOf(columna)];
      recibir(await api.post<GrillaAbierta>(`/senales/${senalId}/abierta/celda`, { fila, columna, valor }));
      const r = await api.post<Parecida[]>(`/senales/${senalId}/abierta/parecidas`, { fila, columna, antes, despues: valor });
      if (r.length) setParecidas(r);
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  const arreglarParecidas = async (elegidas: Parecida[]) => {
    await api.post(`/senales/${senalId}/abierta/aplicar`,
      elegidas.map((x) => ({ fila: Number(x.clave), columna: x.columna, valor: x.despues === null ? null : String(x.despues) })));
    recibir(await api.get<GrillaAbierta>(`/senales/${senalId}/abierta/grilla`));
  };

  return (
    <section aria-label="Grilla" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="filtros" role="group" aria-label="Filtros">
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
            <FilaFiltros columnas={datos.columnas} filtros={filtros} alCambiar={setFiltros} antes={1}
              valores={(c) => datos.filas.map((f) => f[datos.columnas.indexOf(c)])} />
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
      {parecidas && <Recorrido candidatas={parecidas} alAplicar={arreglarParecidas} alCerrar={() => setParecidas(null)} />}
    </section>
  );
}
