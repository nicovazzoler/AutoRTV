import { useCallback, useEffect, useState } from "react";
import { api, textoDeError } from "../api";
import { esperarArmado, type Armado } from "../armado";
import { haceCuanto, nombreMes, numeroSemana, rangoSemana } from "../fechas";
import { CeldaEditable } from "../piezas/CeldaEditable";
import { Enlace } from "../piezas/Enlace";
import { TablaGrilla, type Filtro } from "../piezas/TablaGrilla";
import { Subir } from "./Subir";
import { Recorrido, type Parecida } from "../piezas/Recorrido";
import { cumple, FilaFiltros, type Filtros } from "../piezas/FiltrosColumna";
import { tomarSemana } from "../semanaReciente";
import { useSesion } from "../sesion";
import type { CambioVersion, Celdas, LecturaAgente, SemanaAbierta } from "../tipos";
import { persona } from "../nombre";

function valores(celdas: Celdas, sin: string | null | undefined, cuantos: number, yaVistos: Celdas = {}): string {
  const vistos = new Set(Object.values(yaVistos).map(String));
  return Object.entries(celdas)
    .filter(([c, v]) => c !== sin && v !== null && v !== undefined && String(v).trim() !== "" && !vistos.has(String(v)))
    .slice(0, cuantos)
    .map(([, v]) => String(v))
    .join(" · ");
}

const DIAS_CORTOS = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"];

function cuandoCorto(c: CambioVersion): string {
  const [a, m, d] = c.fecha.split("-").map(Number);
  return `${DIAS_CORTOS[new Date(a, m - 1, d).getDay()]} ${d} · ${c.hora}`;
}

// `crudas`: columnas que vienen tal cual de la grilla; repiten lo que ya dicen las del EPG.
function fraseCambioVersion(c: CambioVersion, programa: string | null | undefined, crudas: string[]): string {
  const nombre = (x?: Record<string, string>) => (programa && x?.[programa]) || Object.values(x ?? {}).find((v) => v) || "(vacío)";
  if (c.tipo === "agregado") return `se agregó ${nombre(c.ahora)}`;
  if (c.tipo === "sacado") return `se sacó ${nombre(c.antes)}`;
  const campos = c.campos ?? [];
  const delEpg = campos.filter((k) => !crudas.includes(k));
  const mostrar = (delEpg.length ? delEpg : campos).sort((a, b) => Number(b === programa) - Number(a === programa));
  return mostrar.map((k) => `${k === programa ? "" : `${k}: `}${c.antes?.[k] || "(vacío)"} → ${c.ahora?.[k] || "(vacío)"}`).join(" · ");
}

const VISTAS: { id: Filtro; nombre: string }[] = [
  { id: "revisar", nombre: "Para revisar" },
  { id: "nueva_lista", nombre: "Nuevas" },
  { id: "base", nombre: "De la base" },
  { id: "todas", nombre: "Todas" },
];

/** La semana de una señal: subir la grilla, revisar lo que frena, ver la grilla entera y confirmar. */
export function Semana({ senalId }: { senalId: string }) {
  const { senales, actualizarSemana, setContexto } = useSesion();
  const senal = senales?.find((s) => s.id === senalId);
  const [datos, setDatos] = useState<SemanaAbierta | null>(() => tomarSemana(senalId));
  const [error, setError] = useState("");
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [menuExportar, setMenuExportar] = useState(false);
  const [filtros, setFiltros] = useState<Filtros>({});
  const [desde, setDesde] = useState("");
  const [hasta, setHasta] = useState("");
  const [repetir, setRepetir] = useState<"" | "mes" | "dos_meses">("");
  const [vista, setVista] = useState<Filtro | null>(null);
  const [subiendo, setSubiendo] = useState(false);
  const [armado, setArmado] = useState<Armado | "armando" | null>(null);
  const [lecturaAgente, setLecturaAgente] = useState<LecturaAgente | null>(null);
  const [parecidas, setParecidas] = useState<Parecida[] | null>(null);

  const esperarReglas = async () => {
    setArmado("armando");
    try {
      const a = await esperarArmado(senalId);
      setArmado(a);
      recibir(await api.get<SemanaAbierta>(`/senales/${senalId}/abierta`));
    } catch (e) {
      setArmado(null);
      setError(textoDeError(e));
    }
  };

  const recibirSubida = (d: SemanaAbierta) => {
    setSubiendo(false);
    setVista(null);
    recibir(d);
    setLecturaAgente(d.lectura_agente ?? null);
    if (d.armando_reglas) void esperarReglas();
  };

  const rearmarReglas = async () => {
    setError("");
    try {
      await api.post(`/senales/${senalId}/reglas/armar`);
      await esperarReglas();
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  useEffect(() => {
    const nombre = senal?.nombre ?? senalId;
    const pendientes = datos?.resumen?.revisar ?? 0;
    const v = datos?.semana ? VISTAS.find((x) => x.id === (vista ?? (pendientes > 0 ? "revisar" : "todas")))?.nombre : "sin grilla";
    setContexto(`${nombre} · Semana${v ? ` · ${v}` : ""}`);
  }, [senal?.nombre, senalId, vista, datos, setContexto]);

  const recibir = useCallback((d: SemanaAbierta) => {
    setDatos(d);
    actualizarSemana(senalId, d.semana);
  }, [senalId, actualizarSemana]);

  // Solo al entrar: después cada acción ya devuelve la semana actualizada.
  useEffect(() => {
    if (datos) return;
    api.get<SemanaAbierta>(`/senales/${senalId}/abierta`).then(recibir).catch((e) => setError(textoDeError(e)));
  }, [senalId]);

  const aceptar = async (hash: string) => {
    setOcupado(hash);
    setError("");
    try {
      recibir(await api.post<SemanaAbierta>(`/senales/${senalId}/abierta/aceptar`, { hashes: [hash] }));
    } catch (e) {
      setError(textoDeError(e));
    }
    setOcupado(null);
  };

  const corregir = async (fila: number, columna: string, valor: string, antes: unknown) => {
    setError("");
    try {
      await api.post(`/senales/${senalId}/abierta/celda`, { fila, columna, valor });
      recibir(await api.get<SemanaAbierta>(`/senales/${senalId}/abierta`));
      const r = await api.post<Parecida[]>(`/senales/${senalId}/abierta/parecidas`, { fila, columna, antes, despues: valor });
      if (r.length) setParecidas(r);
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  const arreglarParecidas = async (elegidas: Parecida[]) => {
    await api.post(`/senales/${senalId}/abierta/aplicar`,
      elegidas.map((x) => ({ fila: Number(x.clave), columna: x.columna, valor: x.despues === null ? null : String(x.despues) })));
    recibir(await api.get<SemanaAbierta>(`/senales/${senalId}/abierta`));
  };

  const borrarGrilla = async () => {
    if (!window.confirm("¿Borrar esta grilla? Si era una versión corregida, vuelve la anterior; si no, la señal queda sin grilla. Lo que ya está en la base no se toca.")) return;
    setError("");
    try {
      const d = await api.borrar<SemanaAbierta>(`/senales/${senalId}/abierta`);
      setVista(null);
      setLecturaAgente(null);
      recibir(d);
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  const confirmar = async (formato: "xlsx" | "csv") => {
    setMenuExportar(false);
    const quedan = datos?.resumen?.revisar ?? 0;
    if (quedan > 0 && !confirm(`Quedan ${quedan} filas para revisar. Si confirmás, entran a la base como están. ¿Confirmar igual?`)) return;
    setOcupado("confirmar");
    setError("");
    try {
      recibir(await api.post<SemanaAbierta>(`/senales/${senalId}/abierta/confirmar`));
      const recorte = new URLSearchParams({ formato });
      if (desde) recorte.set("desde", desde);
      if (hasta) recorte.set("hasta", hasta);
      if (repetir) recorte.set("repetir", repetir);
      await api.descargar(`/senales/${senalId}/abierta/export?${recorte}`);
    } catch (e) {
      setError(textoDeError(e));
    }
    setOcupado(null);
  };

  const volver = <Enlace a="/" className="volver">‹ Señales</Enlace>;
  if (!datos) {
    return (
      <main className="contenido">
        {volver}
        {error ? <p className="error" role="alert">{error}</p> : <p className="tenue">Armando la semana…</p>}
      </main>
    );
  }

  if (!datos.semana || !datos.resumen) {
    return <main className="contenido">{volver}<Subir senalId={senalId} alLeer={recibirSubida} /></main>;
  }

  const { semana, resumen } = datos;
  const elegida: Filtro = vista ?? (resumen.revisar > 0 ? "revisar" : "todas");
  const cuenta: Record<Filtro, number> = { revisar: resumen.revisar, nueva_lista: resumen.nueva_lista, base: resumen.base, todas: resumen.filas };
  const revisar = datos.revisar ?? [];
  const problemas = (datos.horarios ?? []).filter((a) => a.nivel !== "info");
  const notas = (datos.horarios ?? []).filter((a) => a.nivel === "info");
  const confirmada = semana.confirmada && semana.confirmada >= semana.subida;
  const casiTodaNueva = resumen.filas >= 10 && resumen.revisar >= resumen.filas / 2;
  const contenido = datos.contenido ?? [];
  const columnas = contenido;
  const filtradas = revisar.filter((p) => cumple((c) => (c === "Motivo" ? p.motivos.join(" ") : p.salida[c]), filtros));

  return (
    <main className="contenido">
      {volver}
      <header className="cabecera">
        <div className="cabecera-textos">
          <span className="antetitulo">
            {senal?.nombre ?? senalId} · {resumen.desde ? `Semana ${numeroSemana(resumen.desde)} · ` : ""}{semana.version > 1 ? `v${semana.version} · ` : ""}{semana.nombre}{(datos.lectura?.hojas ?? 1) > 1 ? ` (leí ${datos.lectura?.hojas} hojas)` : ""} · subida por {persona(semana.subida_por)} {haceCuanto(semana.subida)}
          </span>
          <h1 className="titulo">{rangoSemana(resumen.desde, resumen.hasta)}</h1>
          <p className="bajada">
            <b>{resumen.base}</b> filas salen de la base, <b className="c-nueva">{resumen.nueva_lista}</b> capítulos nuevos entran solos
            {resumen.revisar > 0 ? <> y <b className="c-revisar">{resumen.revisar}</b> piden que las mires.</> : " y no hay nada para revisar."}
          </p>
        </div>
        <div className="botones" style={{ position: "relative" }}>
          <button type="button" className="boton" onClick={() => setSubiendo(true)}>Subir otra</button>
          <button type="button" className="boton" onClick={borrarGrilla}>Borrar esta grilla</button>
          <button type="button" className="boton principal" aria-haspopup="menu" aria-expanded={menuExportar}
            disabled={ocupado === "confirmar"} onClick={() => setMenuExportar(!menuExportar)}>
            {ocupado === "confirmar" ? "Confirmando…" : confirmada ? "Exportar de nuevo" : "Confirmar y exportar"}
          </button>
          {menuExportar && (
            <div className="menu-cuenta" role="dialog" aria-label="Exportar" style={{ position: "absolute", right: 0, top: "calc(100% + 6px)", zIndex: 2, minWidth: 260, gap: 8, padding: 10 }}>
              <span className="chico tenue">Desde y hasta vacíos = todo. La hora es opcional.</span>
              <label className="campo chico">Desde<input className="entrada" type="datetime-local" value={desde} onChange={(e) => setDesde(e.target.value)} /></label>
              <label className="campo chico">Hasta<input className="entrada" type="datetime-local" value={hasta} onChange={(e) => setHasta(e.target.value)} /></label>
              {resumen.hasta && (
                <label className="campo chico">Repetir la última semana
                  <select className="entrada" value={repetir} onChange={(e) => setRepetir(e.target.value as typeof repetir)}>
                    <option value="">No, como vino</option>
                    <option value="mes">Hasta fin de {nombreMes(resumen.hasta)}</option>
                    <option value="dos_meses">Hasta fin de {nombreMes(resumen.hasta, 1)}</option>
                  </select>
                </label>
              )}
              <button type="button" onClick={() => confirmar("xlsx")}>Excel (.xlsx)</button>
              <button type="button" onClick={() => confirmar("csv")}>CSV</button>
            </div>
          )}
        </div>
      </header>

      {!resumen.desde && (
        <p className="error" role="alert">
          No encontré la fecha y la hora en la grilla{lecturaAgente ? `, y el agente tampoco: ${lecturaAgente.problemas.join(" ")}` : ""}. Así no sale la base ni se puede exportar bien. Pasame el archivo para sumar cómo se lee.
        </p>
      )}
      {resumen.desde && lecturaAgente?.logrado && (
        <p className="nota">El código no encontraba la fecha y la hora; el agente encontró cómo leer la grilla y quedó guardado para las próximas semanas. {lecturaAgente.explicacion}</p>
      )}
      {armado === "armando" && <p className="nota" role="status">El agente está armando las reglas desde los ejemplos: cuando termine, la semana se vuelve a armar sola.</p>}
      {armado && armado !== "armando" && armado.mensaje && (
        <p className={armado.estado === "error" ? "error" : "nota"}>{armado.mensaje}</p>
      )}
      {casiTodaNueva && armado !== "armando" && (
        <p className="nota">
          {resumen.revisar} de {resumen.filas} filas quedaron para revisar: no están en la base y las reglas no alcanzan. Si casi nada sale bien, puede que la grilla cambió de forma o que las reglas quedaron pegadas al ejemplo.{" "}
          <button type="button" className="boton" onClick={rearmarReglas}>Rearmar las reglas con el agente</button>
        </p>
      )}
      {semana.version > 1 && !confirmada && (
        <p className="nota">Es la versión {semana.version} de esta semana: reemplazó a «{semana.anterior_nombre}». Lo que cambió está abajo; hay que volver a confirmar y exportar.</p>
      )}
      {confirmada && semana.confirmada && (
        <p className="nota">Confirmada por {persona(semana.confirmada_por)} {haceCuanto(semana.confirmada)}. Lo nuevo ya está en la base: la semana que viene sale solo.</p>
      )}
      {error && <p className="error" role="alert">{error}</p>}

      {subiendo ? <Subir senalId={senalId} alLeer={recibirSubida} alCancelar={() => setSubiendo(false)} /> : (
        <>
          {datos.cambios && (
            <details className="plegable" open={datos.cambios.length > 0 && datos.cambios.length <= 20}>
              <summary>Cambios contra la v{semana.version - 1} <span className="chico tenue" style={{ fontFamily: "Inter Variable, sans-serif" }}>
                {datos.cambios.length === 0 ? "ninguno: vino igual" : `${datos.cambios.length}${datos.cambios.length >= 300 ? " o más" : ""}`}</span></summary>
              <ul style={{ margin: "12px 0 0", padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 8, fontSize: 14 }}>
                {datos.cambios.map((c) => (
                  <li key={`${c.fecha}-${c.hora}`}>
                    <span className="tenue" style={{ display: "inline-block", minWidth: 110 }}>{cuandoCorto(c)}</span>{" "}
                    <span className={c.tipo === "sacado" ? "c-revisar" : c.tipo === "agregado" ? "c-nueva" : undefined}>{fraseCambioVersion(c, datos.programa, datos.lectura?.columnas ?? [])}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}

          <div className="dos-columnas">
            <details className="plegable">
              <summary>Horarios <span className={`chico ${problemas.length ? "c-revisar" : "tenue"}`} style={{ fontFamily: "Inter Variable, sans-serif" }}>
                {problemas.length ? `${problemas.length} ${problemas.length === 1 ? "aviso" : "avisos"}` : "24 h todos los días, sin huecos"}</span></summary>
              <ul style={{ margin: "12px 0 0", paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6, fontSize: 14 }}>
                {problemas.map((a, i) => <li key={i}>{a.fila ? `Fila ${a.fila}: ` : ""}{a.mensaje}</li>)}
                {notas.map((a, i) => <li key={`n${i}`} className="tenue">{a.mensaje}</li>)}
                {problemas.length === 0 && notas.length === 0 && <li className="tenue">Sin huecos ni superposiciones.</li>}
              </ul>
            </details>
          </div>

          <div className="botones" role="group" aria-label="Qué ver" style={{ gap: 6, paddingBottom: 12, borderBottom: "2px solid var(--texto)" }}>
            {VISTAS.map((v) => (
              <button key={v.id} type="button" className="boton chico" aria-pressed={elegida === v.id} onClick={() => setVista(v.id)}>
                {v.nombre} · {cuenta[v.id]}
              </button>
            ))}
          </div>

          {elegida === "revisar" ? (
            <section aria-label="Para revisar" className="seccion">
              <div className="seccion-cabeza">
                <h2>Para revisar</h2>
                <span className="chico tenue">{resumen.pautas_revisar} {resumen.pautas_revisar === 1 ? "pauta" : "pautas"} · {resumen.revisar} {resumen.revisar === 1 ? "emisión" : "emisiones"} · doble clic en una celda para corregirla</span>
              </div>
              {revisar.length === 0 ? (
                <p className="tenue" style={{ marginTop: 12 }}>Nada para revisar: todo salió de la base o entra solo.</p>
              ) : (
                <div className="desplazable con-alto">
                  <table className="tabla-datos">
                    <thead>
                      <tr>
                        <th><span className="solo-lector">Acción</span></th>
                        <th>Motivo</th>
                        {columnas.map((c) => <th key={c}>{c}</th>)}
                        <th>Veces</th><th>Cómo vino</th>
                      </tr>
                      <FilaFiltros columnas={["Motivo", ...columnas]} filtros={filtros} alCambiar={setFiltros} antes={1}
                        valores={(c) => revisar.flatMap((p) => (c === "Motivo" ? p.motivos : [p.salida[c]]))} />
                    </thead>
                    <tbody>
                      {filtradas.map((p) => (
                        <tr key={p.hash}>
                          <td>
                            <button type="button" className="boton chico" disabled={ocupado === p.hash} onClick={() => aceptar(p.hash)}>
                              {ocupado === p.hash ? "Guardando…" : "Está bien"}
                            </button>
                          </td>
                          <td className="motivos"><ul>{p.motivos.map((m) => <li key={m}>{m}</li>)}</ul></td>
                          {columnas.map((c) => (
                            <CeldaEditable key={c} columna={c} valor={p.salida[c]} editable clase={c === datos.programa ? "programa" : ""}
                              aviso={p.motivos.find((m) => m.startsWith(`${c}:`))} alGuardar={(v) => corregir(p.filas[0], c, v, p.salida[c])} />
                          ))}
                          <td className="tenue">{p.veces}</td>
                          <td className="tenue"><span className="dos-renglones">{valores(p.crudo, null, 4)}</span></td>
                        </tr>
                      ))}
                      {filtradas.length === 0 && <tr><td colSpan={columnas.length + 4} className="tenue">Ninguna pauta cumple esos filtros.</td></tr>}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          ) : <TablaGrilla key={elegida} senalId={senalId} filtro={elegida} />}
          {parecidas && <Recorrido candidatas={parecidas} alAplicar={arreglarParecidas} alCerrar={() => setParecidas(null)} />}
        </>
      )}
    </main>
  );
}
