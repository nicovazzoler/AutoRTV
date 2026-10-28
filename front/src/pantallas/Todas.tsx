import { useEffect, useState } from "react";
import { api, textoDeError } from "../api";
import { Enlace } from "../piezas/Enlace";
import { FilaFiltros, type Filtros } from "../piezas/FiltrosColumna";
import { aSenal } from "../ruta";

interface Datos {
  columnas: string[];
  filas: string[][]; // [id de la señal, ...columnas]
  total: number;
  cuentas: Record<string, number>;
  sin_foto: number;
}

type Estado = "" | "revisar" | "nueva_lista" | "base";

const ESTADOS: { id: Estado; nombre: string }[] = [
  { id: "", nombre: "Todas" },
  { id: "revisar", nombre: "Para revisar" },
  { id: "nueva_lista", nombre: "Nuevas" },
  { id: "base", nombre: "De la base" },
];
const MARCA: Record<string, string> = { base: "base", nueva_lista: "nueva", revisar: "revisar" };

export function Todas() {
  const [datos, setDatos] = useState<Datos | null>(null);
  const [estado, setEstado] = useState<Estado>("");
  const [filtros, setFiltros] = useState<Filtros>({});
  const [error, setError] = useState("");
  const [trayendo, setTrayendo] = useState(false);

  const pedir = async (desde = 0) => {
    const q = new URLSearchParams({ estado, desde: String(desde) });
    for (const [c, v] of Object.entries(filtros)) if (v.trim()) q.append("filtro", `${c}=${v}`);
    return api.get<Datos>(`/todas?${q}`);
  };

  // Espera a que se deje de escribir: cada pedido recorre las semanas de todas las señales.
  useEffect(() => {
    const espera = setTimeout(() => pedir().then(setDatos).catch((e) => setError(textoDeError(e))), 300);
    return () => clearTimeout(espera);
  }, [estado, filtros]);

  const verMas = async () => {
    if (!datos) return;
    const mas = await pedir(datos.filas.length).catch((e) => { setError(textoDeError(e)); return null; });
    if (mas) setDatos({ ...mas, filas: [...datos.filas, ...mas.filas] });
  };

  const traer = async () => {
    setTrayendo(true);
    setError("");
    try {
      let quedan = 1;
      while (quedan > 0) quedan = (await api.post<{ quedan: number }>("/todas/actualizar", {})).quedan;
      setDatos(await pedir());
    } catch (e) {
      setError(textoDeError(e));
    }
    setTrayendo(false);
  };

  const columnas = datos?.columnas ?? [];
  const cuenta = (e: Estado) => (e ? datos?.cuentas[e] ?? 0 : Object.values(datos?.cuentas ?? {}).reduce((a, b) => a + b, 0));

  return (
    <main className="contenido">
      <header className="cabecera-textos">
        <span className="antetitulo">Todas las señales</span>
        <h1 className="titulo">Las semanas abiertas, juntas</h1>
        <p className="bajada">Cada fila es una emisión de la semana abierta de su señal. Filtrá por cualquier columna; tocá la señal para ir a su grilla.</p>
      </header>

      {datos && datos.sin_foto > 0 && (
        <div className="nota botones" role="status" style={{ alignItems: "center" }}>
          <span>{datos.sin_foto} {datos.sin_foto === 1 ? "señal tiene" : "señales tienen"} la semana abierta pero todavía no se ve acá.</span>
          <button type="button" className="boton chico" onClick={traer} disabled={trayendo}>{trayendo ? "Trayéndolas…" : "Traerlas"}</button>
        </div>
      )}

      <div className="botones" role="group" aria-label="Estado" style={{ gap: 6 }}>
        {ESTADOS.map((e) => (
          <button key={e.id} type="button" className="boton chico" aria-pressed={estado === e.id} onClick={() => setEstado(e.id)}>
            {e.nombre} · {cuenta(e.id)}
          </button>
        ))}
      </div>

      {error && <p className="error" role="alert">{error}</p>}

      <div className="desplazable con-alto">
        <table className="tabla-datos">
          <thead>
            <tr>{columnas.map((c) => <th key={c}>{c}</th>)}</tr>
            <FilaFiltros columnas={columnas} filtros={filtros} alCambiar={setFiltros} />
          </thead>
          <tbody>
            {datos?.filas.map(([id, senal, grupo, fecha, ...resto], i) => (
              <tr key={i}>
                <td style={{ whiteSpace: "nowrap" }}><Enlace a={aSenal(id, grupo === "revisar" ? "revisar" : "grilla")} className="nombre">{senal}</Enlace></td>
                <td><span className={`marca-estado ${grupo}`}>{MARCA[grupo] ?? grupo}</span></td>
                <td style={{ whiteSpace: "nowrap" }}>{fecha}</td>
                {resto.map((v, j) => (
                  <td key={j} className={j === resto.length - 1 ? "c-revisar chico" : j === 2 ? "programa" : undefined}>
                    {v.length > 60 ? <span className="dos-renglones" title={v}>{v}</span> : v}
                  </td>
                ))}
              </tr>
            ))}
            {datos && datos.filas.length === 0 && <tr><td colSpan={columnas.length} className="tenue">Ninguna fila cumple esos filtros.</td></tr>}
          </tbody>
        </table>
      </div>
      {datos && (
        <div className="botones" style={{ alignItems: "center" }}>
          <span className="chico tenue">Se ven {datos.filas.length} de {datos.total} filas.</span>
          {datos.total > datos.filas.length && <button type="button" className="boton chico" onClick={verMas}>Ver más</button>}
        </div>
      )}
    </main>
  );
}
