import { useCallback, useEffect, useState } from "react";
import { api, textoDeError } from "../api";
import { haceCuanto, numeroSemana, rangoSemana } from "../fechas";
import { Enlace } from "../piezas/Enlace";
import { aSenal } from "../ruta";
import { tomarSemana } from "../semanaReciente";
import { useSesion } from "../sesion";
import type { CambioVersion, Celdas, Pauta, SemanaAbierta } from "../tipos";

function valores(celdas: Celdas, sin: string | null | undefined, cuantos: number, yaVistos: Celdas = {}): string {
  const vistos = new Set(Object.values(yaVistos).map(String));
  return Object.entries(celdas)
    .filter(([c, v]) => c !== sin && v !== null && v !== undefined && String(v).trim() !== "" && !vistos.has(String(v)))
    .slice(0, cuantos)
    .map(([, v]) => String(v))
    .join(" · ");
}

function programaDe(p: Pauta, columna: string | null | undefined): string {
  const v = columna ? p.salida[columna] : null;
  return v ? String(v) : valores(p.salida, null, 1) || "(sin programa)";
}

// "Programa nuevo: Ruta Sonora" → "Programa nuevo"; el detalle ya se ve en la fila.
function etiquetaMotivo(motivo: string): string {
  return motivo.split(":")[0].trim();
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

// Los motivos que dicen algo más que la pastilla y el nombre del programa.
function detalleMotivos(p: Pauta, columna: string | null | undefined): string[] {
  const obvio = `Programa nuevo: ${programaDe(p, columna)}`;
  return p.motivos.filter((m) => m !== obvio && m.includes(":"));
}

export function Revisar({ senalId }: { senalId: string }) {
  const { senales, actualizarSemana } = useSesion();
  const senal = senales?.find((s) => s.id === senalId);
  const [datos, setDatos] = useState<SemanaAbierta | null>(() => tomarSemana(senalId));
  const [error, setError] = useState("");
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [menuExportar, setMenuExportar] = useState(false);
  const [desde, setDesde] = useState("");
  const [hasta, setHasta] = useState("");

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
      await api.descargar(`/senales/${senalId}/abierta/export?${recorte}`);
    } catch (e) {
      setError(textoDeError(e));
    }
    setOcupado(null);
  };

  if (!datos) {
    return (
      <main className="contenido">
        {error ? <p className="error" role="alert">{error}</p> : <p className="tenue">Armando la semana…</p>}
        {error && <div className="botones"><Enlace a={aSenal(senalId, "subir")} className="boton">Subir la grilla</Enlace></div>}
      </main>
    );
  }

  if (!datos.semana || !datos.resumen) {
    return (
      <main className="contenido angosto">
        <header className="cabecera-textos">
          <span className="antetitulo">{senal?.nombre ?? senalId}</span>
          <h1 className="titulo">Todavía no hay grilla de esta semana</h1>
          <p className="bajada">Subila como venga y te muestro qué sale de la base y qué hay que mirar.</p>
        </header>
        <div className="botones"><Enlace a={aSenal(senalId, "subir")} className="boton principal">Subir grilla</Enlace></div>
      </main>
    );
  }

  const { semana, resumen } = datos;
  const revisar = datos.revisar ?? [];
  const nuevas = datos.nuevas ?? [];
  const problemas = (datos.horarios ?? []).filter((a) => a.nivel !== "info");
  const notas = (datos.horarios ?? []).filter((a) => a.nivel === "info");
  const confirmada = semana.confirmada && semana.confirmada >= semana.subida;

  return (
    <main className="contenido">
      <header className="cabecera">
        <div className="cabecera-textos">
          <span className="antetitulo">
            {resumen.desde ? `Semana ${numeroSemana(resumen.desde)} · ` : ""}{semana.version > 1 ? `v${semana.version} · ` : ""}{semana.nombre} · subida por {semana.subida_por} {haceCuanto(semana.subida)}
          </span>
          <h1 className="titulo">{rangoSemana(resumen.desde, resumen.hasta)}</h1>
          <p className="bajada">
            <b>{resumen.base}</b> filas salen de la base, <b className="c-nueva">{resumen.nueva_lista}</b> capítulos nuevos entran solos
            {resumen.revisar > 0 ? <> y <b className="c-revisar">{resumen.revisar}</b> piden que las mires.</> : " y no hay nada para revisar."}
          </p>
        </div>
        <div className="botones" style={{ position: "relative" }}>
          <Enlace a={aSenal(senalId, "subir")} className="boton">Subir otra grilla</Enlace>
          <button type="button" className="boton principal" aria-haspopup="menu" aria-expanded={menuExportar}
            disabled={ocupado === "confirmar"} onClick={() => setMenuExportar(!menuExportar)}>
            {ocupado === "confirmar" ? "Confirmando…" : confirmada ? "Exportar de nuevo" : "Confirmar y exportar"}
          </button>
          {menuExportar && (
            <div className="menu-cuenta" role="dialog" aria-label="Exportar" style={{ position: "absolute", right: 0, top: "calc(100% + 6px)", zIndex: 2, minWidth: 260, gap: 8, padding: 10 }}>
              <span className="chico tenue">Vacío = toda la semana. La hora es opcional.</span>
              <label className="campo chico">Desde<input className="entrada" type="datetime-local" value={desde} onChange={(e) => setDesde(e.target.value)} /></label>
              <label className="campo chico">Hasta<input className="entrada" type="datetime-local" value={hasta} onChange={(e) => setHasta(e.target.value)} /></label>
              <button type="button" onClick={() => confirmar("xlsx")}>Excel (.xlsx)</button>
              <button type="button" onClick={() => confirmar("csv")}>CSV</button>
            </div>
          )}
        </div>
      </header>

      {semana.version > 1 && !confirmada && (
        <p className="nota">Es la versión {semana.version} de esta semana: reemplazó a «{semana.anterior_nombre}». Lo que cambió está abajo; hay que volver a confirmar y exportar.</p>
      )}
      {confirmada && semana.confirmada && (
        <p className="nota">Confirmada por {semana.confirmada_por} {haceCuanto(semana.confirmada)}. Lo nuevo ya está en la base: la semana que viene sale solo.</p>
      )}
      {error && <p className="error" role="alert">{error}</p>}

      <section aria-label="Para revisar" className="seccion">
        <div className="seccion-cabeza">
          <h2>Para revisar</h2>
          <span className="chico tenue">{resumen.pautas_revisar} pautas · {resumen.revisar} emisiones</span>
        </div>
        {revisar.length === 0 ? (
          <p className="tenue" style={{ marginTop: 12 }}>Nada para revisar: todo salió de la base o entra solo.</p>
        ) : (
          <div className="desplazable">
            <table className="tabla apilable" style={{ fontSize: 15 }}>
              <tbody>
                {revisar.map((p) => (
                  <tr key={p.hash}>
                    <td style={{ width: 170, paddingTop: 18 }}>
                      <span className="pildora revisar" style={{ whiteSpace: "normal" }}>{etiquetaMotivo(p.motivos[0] ?? "Revisar")}</span>
                    </td>
                    <td style={{ paddingTop: 18 }}>
                      <div className="serif" style={{ fontSize: 19 }}>{programaDe(p, datos.programa)}</div>
                      <div className="chico tenue">{valores(p.salida, datos.programa, 3, p.crudo) || "sin más datos"}</div>
                      {detalleMotivos(p, datos.programa).length > 0 && (
                        <ul className="chico c-revisar" style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                          {detalleMotivos(p, datos.programa).map((m) => <li key={m}>{m}</li>)}
                        </ul>
                      )}
                    </td>
                    <td className="chico tenue" style={{ paddingTop: 18 }}>vino como<br /><span style={{ color: "var(--texto)" }}>{valores(p.crudo, null, 3)}</span></td>
                    <td className="chico tenue" style={{ paddingTop: 18, whiteSpace: "nowrap" }}>{p.veces} {p.veces === 1 ? "vez" : "veces"}</td>
                    <td className="derecha" style={{ paddingTop: 18, paddingRight: 0 }}>
                      <button type="button" className="boton chico" disabled={ocupado === p.hash} onClick={() => aceptar(p.hash)}>
                        {ocupado === p.hash ? "Guardando…" : "Está bien"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

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
          <summary>Nuevas listas <span className="chico c-nueva" style={{ fontFamily: "Inter Variable, sans-serif" }}>{resumen.nueva_lista} · entran solas al confirmar</span></summary>
          <ul style={{ margin: "12px 0 0", padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 8, fontSize: 14 }}>
            {nuevas.slice(0, 20).map((p) => (
              <li key={p.hash}>{programaDe(p, datos.programa)} <span className="tenue">· {valores(p.salida, datos.programa, 2)}</span></li>
            ))}
            {nuevas.length > 20 && <li className="tenue">y {nuevas.length - 20} más</li>}
            {nuevas.length === 0 && <li className="tenue">Esta semana no hay capítulos nuevos.</li>}
          </ul>
        </details>
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
    </main>
  );
}
