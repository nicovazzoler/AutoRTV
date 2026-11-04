import { useEffect, useState } from "react";
import { esperarArmado, type Armado } from "../armado";
import { api, ErrorApi, textoDeError } from "../api";
import { frase, fraseCambio, fraseEntrada, fraseIdiomas } from "../frases";
import { haceCuanto } from "../fechas";
import { ConfigSenal, RecetaArchivo } from "../piezas/ConfigSenal";
import { EpgCrudo } from "../piezas/EpgCrudo";
import { CodigoDelAgente, type Codigo } from "../piezas/CodigoDelAgente";
import { ParesEjemplos } from "../piezas/ParesEjemplos";
import { CabeceraBase } from "./Base";
import { pedirAgente } from "../piezas/Agente";
import { useSesion } from "../sesion";
import type { Evaluacion, Receta, Version } from "../tipos";
import { persona } from "../nombre";
import { confirmar } from "../piezas/Dialogos";

interface Informe {
  id: string;
  celdas_cambiadas: number;
  error: string | null;
}

// "ejemplo-20261027-153000" es como los guarda el servidor; a la persona le sirve la fecha.
function nombreEjemplo(nombre: string): string {
  const m = nombre.match(/^ejemplo-(\d{4})(\d{2})(\d{2})/);
  if (!m) return nombre;
  const meses = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  return `Subido el ${Number(m[3])} ${meses[Number(m[2]) - 1]} ${m[1]}`;
}

type Seccion = "ejemplos" | "reglas" | "lectura" | "columnas";

const SECCIONES: { id: Seccion; nombre: string }[] = [
  { id: "ejemplos", nombre: "Ejemplos" },
  { id: "reglas", nombre: "Reglas" },
  { id: "lectura", nombre: "Lectura" },
  { id: "columnas", nombre: "Columnas e idiomas" },
];

/** Base › Configuración: cómo se arma la señal (ejemplos, reglas, cómo se lee la grilla y qué columnas salen). */
interface PropuestaRegla {
  tipo: "crear" | "revisar";
  clave: string;
  columna?: string;
  antes?: unknown;
  despues?: unknown;
  tarjeta?: string;
  veces: number;
  semanas?: number;
  pedido: string;
}

export function Configuracion({ senalId }: { senalId: string }) {
  const { yo, senales, tocar, setContexto } = useSesion();
  const [seccion, setSeccion] = useState<Seccion>("reglas");
  const tablaId = senales?.find((s) => s.id === senalId)?.semana?.tabla_id ?? null;
  const [receta, setReceta] = useState<Receta | null>(null);
  const [version, setVersion] = useState("");
  const [evaluaciones, setEvaluaciones] = useState<Evaluacion[] | null>(null);
  const [historial, setHistorial] = useState<Version[]>([]);
  const [informes, setInformes] = useState<Record<string, Informe>>({});
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [editando, setEditando] = useState(false);
  const [armando, setArmando] = useState(false);
  const [confianza, setConfianza] = useState<{ semanas: Record<string, number>; hacen_falta: number } | null>(null);
  const [propuestas, setPropuestas] = useState<PropuestaRegla[]>([]);

  const cargar = async () => {
    const { datos, version: v } = await api.conVersion<Receta>(`/senales/${senalId}`);
    setReceta(datos);
    setVersion(v);
    setHistorial(await api.get<Version[]>(`/senales/${senalId}/historial`));
    setConfianza(await api.get(`/senales/${senalId}/reglas/confianza`));
    setPropuestas(await api.get<PropuestaRegla[]>(`/senales/${senalId}/reglas/propuestas`));
    setEvaluaciones(await api.post<Evaluacion[]>(`/senales/${senalId}/ejemplos/evaluar`, datos));
    if (tablaId) {
      const vista = await api.post<{ tarjetas: Informe[] }>("/preview", { tabla_id: tablaId, senal: datos, filas: 1 }).catch(() => null);
      if (vista) setInformes(Object.fromEntries(vista.tarjetas.map((i) => [i.id, i])));
    }
  };

  useEffect(() => {
    cargar().catch((e) => setError(textoDeError(e)));
  }, [senalId]);

  const dejar = async (p: PropuestaRegla) => {
    await api.post(`/senales/${senalId}/reglas/propuestas/descartar`, { clave: p.clave }).catch((e) => setError(textoDeError(e)));
    setPropuestas((lista) => lista.filter((x) => x.clave !== p.clave));
  };

  const sacarRegla = async (p: PropuestaRegla) => {
    if (!receta || !await confirmar({ texto: "Se puede deshacer desde el historial de abajo.", boton: "Sacar la regla", peligro: true })) return;
    setError("");
    try {
      await api.put(`/senales/${senalId}`, { ...receta, tarjetas: receta.tarjetas.filter((t) => t.id !== p.tarjeta) }, { "If-Match": version });
      await dejar(p);
      tocar();
      await cargar();
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  const restaurar = async (v: Version, cual: string) => {
    if (!await confirmar({ titulo: `Volver a las reglas de ${cual}`, texto: "Queda como un cambio más, así también se puede deshacer.",
      boton: "Volver a esas reglas" })) return;
    setError("");
    try {
      await api.conVersion(`/senales/${senalId}/historial/${v.id}/restaurar`, "POST", { "If-Match": version });
      setAviso("Listo: las reglas volvieron a esa versión.");
      tocar();
    } catch (e) {
      setError(e instanceof ErrorApi && e.estado === 409 ? `${e.message}. Recargá la página y probá de nuevo.` : textoDeError(e));
    }
  };

  const borrarEjemplo = async (nombre: string) => {
    if (!await confirmar({ texto: `Se borra el ejemplo «${nombreEjemplo(nombre)}». La base de pautas no cambia.`, boton: "Borrar el ejemplo",
      peligro: true })) return;
    try {
      await api.borrar(`/senales/${senalId}/ejemplos/${encodeURIComponent(nombre)}`);
      await cargar();
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  useEffect(() => {
    setContexto(`Base · Configuración · ${SECCIONES.find((x) => x.id === seccion)?.nombre}`);
  }, [seccion, setContexto]);

  const esperarYContar = async () => {
    setArmando(true);
    const a = await esperarArmado(senalId);
    setArmando(false);
    if (!a) return;
    if (a.estado === "aplicado") {
      setAviso(a.mensaje ?? "Reglas armadas por el agente.");
      tocar();
    } else if (a.estado !== "armando") {
      setError(a.mensaje ?? "El agente no pudo armar las reglas.");
    }
  };

  // Si el agente está armando las reglas (porque se creó la señal o llegó un ejemplo), se espera y se avisa.
  useEffect(() => {
    api.get<Armado | null>(`/senales/${senalId}/reglas/armado`)
      .then((a) => { if (a?.estado === "armando") esperarYContar().catch(() => setArmando(false)); })
      .catch(() => {});
  }, [senalId]);

  const armarReglas = async () => {
    setError("");
    setAviso("");
    try {
      await api.post(`/senales/${senalId}/reglas/armar`);
      await esperarYContar();
    } catch (e) {
      setArmando(false);
      setError(textoDeError(e));
    }
  };

  const sumarCriterios = async () => {
    setError("");
    setAviso("");
    try {
      const r = await api.post<{ aplicado: boolean; antes: Record<string, number>; despues: Record<string, number> }>(`/senales/${senalId}/reglas/criterios`);
      const resumen = Object.keys(r.antes).map((n) => `${nombreEjemplo(n)}: ${r.antes[n]} % → ${r.despues[n]} %`).join(" · ");
      if (r.aplicado) {
        setAviso(`Criterios generales sumados al principio de las reglas. ${resumen}`);
        tocar();
      } else {
        setError(`No los sumé porque algún ejemplo empeora con las reglas de ahora: ${resumen}. Pedile al agente que los combine.`);
      }
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  const limpiarBase = async () => {
    if (!await confirmar({ titulo: "Limpiar la base",
      texto: "Salen de la base las columnas que en realidad son horario (por ejemplo una hora con AM/PM). Las pautas que solo se diferenciaban por eso se juntan en una.",
      boton: "Sacar las columnas de horario", peligro: true })) return;
    try {
      const r = await api.post<{ antes: number; despues: number; columnas: string[] }>(`/senales/${senalId}/pautas/limpiar`, {});
      setAviso(r.columnas.length
        ? `Base limpia: se sacaron ${r.columnas.join(", ")} y quedaron ${r.despues} pautas (había ${r.antes}).`
        : "La base ya estaba limpia: no había columnas de horario guardadas.");
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  if (!receta) {
    return <main className="contenido">{error ? <p className="error" role="alert">{error}</p> : <p className="tenue">Cargando la señal…</p>}</main>;
  }

  const conPct = (evaluaciones ?? []).filter((x) => typeof x.porcentaje === "number");
  const promedio = conPct.length ? Math.round(conPct.reduce((a, x) => a + (x.porcentaje ?? 0), 0) / conPct.length) : null;
  const anterior = historial[1];

  return (
    <main className="contenido">
      <CabeceraBase senalId={senalId} config />
      <p className="bajada" style={{ margin: 0 }}>
        {fraseEntrada(receta)} · {fraseIdiomas(receta).toLowerCase()} · {promedio === null ? "todavía sin ejemplos para medir las reglas" : <>las reglas aciertan el <b>{promedio} %</b> de los ejemplos</>}
      </p>
      {error && <p className="error" role="alert">{error}</p>}
      {aviso && <p className="nota" role="status">{aviso}</p>}

      <div className="con-secciones">
        <nav aria-label="Secciones" className="secciones">
          {SECCIONES.map((x) => (
            <button key={x.id} type="button" aria-current={seccion === x.id ? "page" : undefined} onClick={() => setSeccion(x.id)}>
              {x.nombre}{x.id === "ejemplos" && evaluaciones ? <span className="tenue chico"> · {evaluaciones.length}</span> : null}
            </button>
          ))}
        </nav>

        <div style={{ flex: "1 1 auto", minWidth: 0, display: "flex", flexDirection: "column", gap: 18 }}>
          {seccion === "ejemplos" && (
            <section aria-label="Ejemplos" className="seccion" style={{ gap: 16 }}>
              <p className="chico tenue" style={{ margin: 0 }}>Semanas que ya salieron: cómo vinieron y cómo quedaron. Con ellas se carga la base y se miden las reglas.</p>
              <ul className="lista-simple">
                {evaluaciones === null && <li className="tenue chico">Probando las reglas contra los ejemplos…</li>}
                {evaluaciones?.length === 0 && <li className="tenue chico">Sin ejemplos todavía.</li>}
                {evaluaciones?.map((x) => (
                  <li key={x.nombre}>
                    <span className="serif" style={{ fontSize: 16 }}>{nombreEjemplo(x.nombre)}</span>
                    <span style={{ flexGrow: 1 }} />
                    <b title={x.error}>{x.error ? "error" : `${x.porcentaje} %`}</b>
                    <button type="button" className="boton chico" style={{ minHeight: 32, padding: "0 10px" }} onClick={() => borrarEjemplo(x.nombre)}>Borrar</button>
                  </li>
                ))}
              </ul>
              <ParesEjemplos senalId={senalId} alAgregar={async (m) => { setAviso(m); await cargar(); }} />
            </section>
          )}

          {seccion === "reglas" && (
            <section aria-label="Reglas" className="seccion">
              <span className="chico tenue">Las arma el agente desde los ejemplos y tus pedidos; se cambian hablándole o con «Deshacer».</span>
              {Boolean(receta.final) && <CodigoDelAgente senalId={senalId} donde="final" codigo={receta.final as Codigo} alCambiar={tocar} />}
              {propuestas.length > 0 && (
                <div className="propuestas-reglas" aria-label="El agente propone">
                  <span className="etiqueta-propuesta">EL AGENTE PROPONE, POR LO QUE SE CORRIGIÓ</span>
                  {propuestas.map((p) => (
                    <div key={p.clave} className="propuesta-regla">
                      <span>
                        {p.tipo === "crear"
                          ? <>Corrigieron {p.veces} veces <b>«{String(p.antes)}» → «{String(p.despues)}»</b> en {p.columna}: ¿creo una regla?</>
                          : <>La regla {(receta.tarjetas.findIndex((t) => t.id === p.tarjeta) + 1) || p.tarjeta} se corrigió {p.veces} veces en {p.semanas} semanas: ¿la saco o la cambio?</>}
                      </span>
                      <div className="botones" style={{ gap: 6 }}>
                        <button type="button" className="boton principal chico" onClick={() => pedirAgente(p.pedido)}>{p.tipo === "crear" ? "Crear la regla" : "Cambiarla"}</button>
                        {p.tipo === "revisar" && <button type="button" className="boton chico" onClick={() => sacarRegla(p)}>Sacarla</button>}
                        <button type="button" className="boton chico" onClick={() => dejar(p)}>Dejarla así</button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              <ol className="lista-simple">
                {receta.tarjetas.length === 0 && (
                  <li className="tenue chico" style={{ flexWrap: "wrap" }}>Sin reglas: todo sale de la base o como vino.
                    {!!evaluaciones?.length && <button type="button" className="boton chico" onClick={armarReglas} disabled={armando}>
                      {armando ? "Armando… (puede tardar un minuto)" : "Armar reglas desde los ejemplos"}</button>}
                  </li>
                )}
                {receta.tarjetas.length > 0 && !receta.tarjetas.some((t) => t.tipo === "criterios") && !!evaluaciones?.length && (
                  <li className="tenue chico" style={{ flexWrap: "wrap" }}>Estas reglas no usan los criterios generales.
                    <button type="button" className="boton chico" onClick={sumarCriterios}>Sumar los criterios generales</button>
                  </li>
                )}
                {receta.tarjetas.map((t, i) => {
                  const inf = informes[t.id];
                  return (
                    <li key={t.id} className={`regla${t.activa === false ? " apagada" : ""}`}>
                      <span className="numero">{i + 1}</span>
                      <span style={{ lineHeight: 1.5 }}>{frase(t)}{t.activa === false ? " (apagada)" : ""}
                        {t.tipo === "criterios" && confianza && (
                          <span className={`chico ${(confianza.semanas[t.id] ?? 0) >= confianza.hacen_falta ? "c-nueva" : "c-revisar"}`}>
                            {" · "}{(confianza.semanas[t.id] ?? 0) >= confianza.hacen_falta
                              ? `confiable: ${confianza.semanas[t.id]} semanas sin correcciones`
                              : `en prueba: ${confianza.semanas[t.id] ?? 0} de ${confianza.hacen_falta} semanas sin correcciones`}
                          </span>
                        )}
                      </span>
                      <span className={`chico ${inf?.error ? "c-revisar" : "tenue"}`} style={{ whiteSpace: "nowrap" }} title={inf?.error ?? undefined}>
                        {inf?.error ? "con error" : inf ? `${inf.celdas_cambiadas} celdas` : ""}
                      </span>
                    </li>
                  );
                })}
              </ol>
              {historial.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 14 }}>
                  <div className="botones" style={{ alignItems: "center" }}>
                    <span className="chico tenue">Último cambio: <b style={{ color: "var(--texto)" }}>{persona(historial[0].usuario)} · {haceCuanto(historial[0].fecha)}</b></span>
                    <span style={{ flexGrow: 1 }} />
                    {anterior && <button type="button" className="boton chico" onClick={() => restaurar(anterior, "antes del último cambio")}>Deshacer el último cambio</button>}
                  </div>
                  <details className="chico tenue">
                    <summary style={{ cursor: "pointer" }}>Historial ({historial.length})</summary>
                    <ul className="lista-simple" style={{ marginTop: 8 }}>
                      {historial.slice(0, 15).map((v, i) => (
                        <li key={v.id} style={{ flexWrap: "wrap" }}>
                          <span style={{ color: "var(--texto)" }}>{persona(v.usuario)} · {haceCuanto(v.fecha)}</span>
                          <span style={{ flex: "1 1 200px" }}>{v.cambios.length ? v.cambios.map(fraseCambio).join(" · ") : "primera versión"}</span>
                          {i > 0 && <button type="button" className="boton chico" style={{ minHeight: 32 }} onClick={() => restaurar(v, "en esta versión")}>Volver a esta</button>}
                        </li>
                      ))}
                    </ul>
                  </details>
                </div>
              )}
            </section>
          )}

          {(seccion === "lectura" || seccion === "columnas") && (
            <section aria-label={seccion === "lectura" ? "Lectura" : "Columnas e idiomas"} className="seccion">
              {editando ? (
                <ConfigSenal receta={receta} version={version} alCancelar={() => setEditando(false)} alGuardar={() => { setEditando(false); tocar(); }} />
              ) : (
                <dl className="datos-config">
                  {seccion === "lectura" ? (
                    <>
                      <div><dt>Cómo se lee la grilla</dt><dd>{fraseEntrada(receta)}</dd></div>
                      <div><dt>Celdas con varios programas</dt><dd>{receta.entrada.partir ? `Se parten en «${receta.entrada.partir.separador}»` : "No se parten"}</dd></div>
                      {receta.entrada.tipo === "codigo" && (
                        <div style={{ gridColumn: "1 / -1" }}>
                          <CodigoDelAgente senalId={senalId} donde="lector" codigo={receta.entrada.lector as Codigo} alCambiar={tocar} />
                        </div>
                      )}
                    </>
                  ) : (
                    <>
                      <div><dt>Idiomas</dt><dd>{fraseIdiomas(receta)}</dd></div>
                      <div><dt>Columnas de salida</dt><dd>{receta.salida.columnas.length ? receta.salida.columnas.join(", ") : "Las del catálogo, en su orden"}</dd></div>
                    </>
                  )}
                </dl>
              )}
              {yo.admin && !editando && (
                <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 12 }}>
                  <div><button type="button" className="boton chico" onClick={() => setEditando(true)}>Editar</button></div>
                  {seccion === "lectura" && receta.entrada.tipo === "html" && <EpgCrudo senalId={senalId} alGuardar={tocar} />}
                  {seccion === "columnas" && (
                    <>
                      <RecetaArchivo receta={receta} version={version} alGuardar={tocar} />
                      <div className="botones" style={{ alignItems: "center" }}>
                        <button type="button" className="boton chico" onClick={limpiarBase}>Limpiar la base</button>
                        <span className="chico tenue">Saca columnas de horario que hayan quedado guardadas como contenido.</span>
                      </div>
                    </>
                  )}
                </div>
              )}
              {!yo.admin && <p className="chico tenue">Esto lo cambia el admin.</p>}
            </section>
          )}
        </div>
      </div>
    </main>
  );
}
