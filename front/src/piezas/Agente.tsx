import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, ErrorApi, textoDeError } from "../api";
import { fraseCambio } from "../frases";
import { useSesion } from "../sesion";
import type { AccionAdmin, Charla, CorreccionBase, Limites, Propuesta, Receta } from "../tipos";

interface Mensaje {
  rol: "persona" | "asistente";
  texto: string;
}

interface PropuestaAbierta extends Propuesta {
  pedido: string;
  historial: Mensaje[];
  version: string; // de la receta sobre la que se armó, para no pisar un cambio de otro
  aplicadas: Set<number>;
}

// La conversación es por señal y sigue al cambiar de pantalla; se pierde al recargar.
const hilos = new Map<string, Mensaje[]>();

const PLEGADO = "autortv.agente-plegado";

function leerPlegado(): boolean {
  try {
    // Plegado de entrada: Revisar y Grilla necesitan el ancho. Queda abierto solo si la persona lo abrió.
    return localStorage.getItem(PLEGADO) !== "0";
  } catch {
    return false;
  }
}

function texto(v: unknown): string {
  return v === null || v === undefined || v === "" ? "(vacío)" : String(v);
}

export function Agente({ senalId }: { senalId: string }) {
  const { yo, senales, tocar } = useSesion();
  const tablaId = senales?.find((s) => s.id === senalId)?.semana?.tabla_id ?? null;
  const [hilo, setHilo] = useState<Mensaje[]>(() => hilos.get(senalId) ?? []);
  const [propuesta, setPropuesta] = useState<PropuestaAbierta | null>(null);
  const [escrito, setEscrito] = useState("");
  const [trabajando, setTrabajando] = useState<"" | "rapido" | "propuesta">("");
  const [error, setError] = useState("");
  const [limites, setLimites] = useState<Limites | null>(null);
  const [plegado, setPlegado] = useState(leerPlegado);
  const [claves, setClaves] = useState<string[]>([]);
  const fondo = useRef<HTMLDivElement>(null);

  const refrescarLimites = () => api.get<Limites>("/asistente/limites").then(setLimites).catch(() => {});
  useEffect(() => {
    refrescarLimites();
  }, []);
  useEffect(() => {
    hilos.set(senalId, hilo);
    fondo.current?.scrollIntoView({ block: "nearest" });
  }, [hilo, senalId]);

  const plegar = (si: boolean) => {
    setPlegado(si);
    try {
      localStorage.setItem(PLEGADO, si ? "1" : "0");
    } catch {
      // Sin almacenamiento, vuelve a abrirse al recargar.
    }
  };

  const decir = (m: Mensaje) => setHilo((h) => [...h, m]);

  const proponer = async (pedido: string, historial: Mensaje[], fuerte = false) => {
    setTrabajando("propuesta");
    try {
      const { datos: receta, version } = await api.conVersion<Receta>(`/senales/${senalId}`);
      const p = await api.post<Propuesta>("/asistente", { senal: receta, pedido, tabla_id: tablaId, historial, fuerte });
      setPropuesta({ ...p, pedido, historial, version, aplicadas: new Set() });
      decir({ rol: "asistente", texto: p.explicacion || (p.receta ? "Te dejo una propuesta abajo." : "No llegué a una propuesta que sirva.") });
    } catch (e) {
      setError(textoDeError(e));
    }
    setTrabajando("");
    refrescarLimites();
  };

  const enviar = async (forzar: boolean) => {
    const pedido = escrito.trim();
    if (!pedido) {
      setError("Escribí qué querés que haga el agente");
      return;
    }
    const previo = hilo;
    setError("");
    setEscrito("");
    decir({ rol: "persona", texto: pedido });
    if (!forzar) {
      setTrabajando("rapido");
      try {
        const { datos: receta } = await api.conVersion<Receta>(`/senales/${senalId}`);
        const c = await api.post<Charla>("/asistente/charla", { senal: receta, pedido, tabla_id: tablaId, historial: previo });
        if (c.respuesta) decir({ rol: "asistente", texto: c.respuesta });
        setTrabajando("");
        refrescarLimites();
        if (!c.proponer_cambios) return;
      } catch (e) {
        setError(textoDeError(e));
        setTrabajando("");
        return;
      }
    }
    await proponer(pedido, previo);
  };

  const enviarFormulario = (e: FormEvent) => {
    e.preventDefault();
    enviar(false);
  };

  const marcarAplicada = (i: number) => setPropuesta((p) => p && { ...p, aplicadas: new Set([...p.aplicadas, i]) });

  const aplicarReglas = async () => {
    if (!propuesta?.receta) return;
    setError("");
    try {
      await api.put(`/senales/${senalId}`, propuesta.receta, { "If-Match": propuesta.version });
      decir({ rol: "asistente", texto: "(Reglas aplicadas. Se pueden deshacer desde Señal.)" });
      marcarAplicada(-1);
      tocar();
    } catch (e) {
      setError(e instanceof ErrorApi && e.estado === 409
        ? `${e.message}. Pedile la propuesta de nuevo para armarla sobre las reglas de ahora.` : textoDeError(e));
    }
  };

  const aplicarCorreccion = async (c: CorreccionBase, i: number) => {
    setError("");
    try {
      const r = await api.post<{ editadas: number }>(`/senales/${senalId}/pautas/editar-varias`,
        { filtro: c.filtro, columna: c.columna, valor: c.valor === null ? null : String(c.valor) });
      decir({ rol: "asistente", texto: `(Corregidas ${r.editadas} pautas en la base.)` });
      marcarAplicada(i);
      tocar();
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  const aplicarAdmin = async (acciones: AccionAdmin[]) => {
    setError("");
    try {
      const r = await api.post<{ descripcion: string; ok: boolean; clave?: string; error?: string }[]>("/admin/acciones", { acciones });
      setClaves(r.filter((x) => x.clave).map((x) => `${x.descripcion}: la clave es ${x.clave}`));
      decir({ rol: "asistente", texto: r.map((x) => `(${x.ok ? "Hecho" : "No se pudo"}: ${x.descripcion}${x.error ? ` — ${x.error}` : ""})`).join("\n") });
      marcarAplicada(-2);
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  if (plegado) {
    return (
      <aside className="agente plegado" aria-label="Agente">
        <button type="button" className="boton chico" onClick={() => plegar(false)}>Abrir el agente</button>
      </aside>
    );
  }

  const p = propuesta;
  const efecto = p?.efecto;
  const ejemplos = p?.despues ? Object.entries(p.despues.ejemplos) : [];
  const acciones = yo.admin ? p?.acciones_admin ?? [] : [];

  return (
    <aside className="agente" aria-label="Agente">
      <div className="agente-cabeza">
        <h2>Notas del agente</h2>
        <span style={{ flexGrow: 1 }} />
        {hilo.length > 0 && <button type="button" className="boton chico" onClick={() => { setHilo([]); setPropuesta(null); }}>Nueva charla</button>}
        <button type="button" className="boton-redondo" style={{ flexBasis: 36, height: 36 }} aria-label="Plegar el agente" title="Plegar" onClick={() => plegar(true)}>›</button>
      </div>
      {limites && <span className="chico tenue">Te quedan {limites.quedan} de {limites.limite_diario} pedidos hoy · ve solo esta señal</span>}

      <div className="hilo" aria-live="polite">
        {hilo.length === 0 && (
          <p className="tenue chico">Preguntale por qué una fila quedó así, o pedile un cambio: «el año viene pegado al título», «todos los Noches de Jazz van con género Música».</p>
        )}
        {hilo.map((m, i) => (
          <p key={i} className={`mensaje ${m.rol}${m.texto.startsWith("(") ? " nota-hilo" : ""}`}>{m.rol === "persona" ? "—" : ""}{m.texto}</p>
        ))}

        {p && (
          <div className="propuesta-agente">
            {!p.logrado && (
              <p className="chico c-revisar" style={{ margin: 0 }}>
                No lo logró del todo ({p.vueltas} {p.vueltas === 1 ? "intento" : "intentos"}). {p.receta ? "Revisá el efecto antes de aplicarlo." : ""}
              </p>
            )}

            {p.receta && (p.cambios.length > 0 || efecto) && (
              <section className="bloque-propuesta">
                <span className="etiqueta-propuesta">PROPUESTA · REGLAS</span>
                {efecto && efecto.ejemplos.length > 0 && (
                  <table className="antes-despues">
                    <thead><tr><th>Antes</th><th>Después</th></tr></thead>
                    <tbody>
                      {efecto.ejemplos.map((x, i) => (
                        <tr key={i}><td className="tenue">{texto(x.antes)}</td><td>{texto(x.despues)}</td></tr>
                      ))}
                    </tbody>
                  </table>
                )}
                <p className="chico tenue" style={{ margin: 0 }}>
                  {efecto ? <>Cambian {efecto.celdas} celdas · para revisar <b className="c-revisar">{efecto.revisar_antes} → {efecto.revisar_despues}</b></> : null}
                  {ejemplos.map(([n, pct]) => <span key={n}><br />Ejemplo {n.replace(/^ejemplo-/, "")}: {p.antes?.ejemplos[n]} → {pct} %</span>)}
                </p>
                {p.cambios.length > 0 && (
                  <details className="chico tenue">
                    <summary style={{ cursor: "pointer" }}>Ver la regla</summary>
                    <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>{p.cambios.map((c, i) => <li key={i}>{fraseCambio(c)}</li>)}</ul>
                  </details>
                )}
                {p.aplicadas.has(-1) ? <span className="chico c-nueva">Aplicada.</span> : (
                  <div className="botones" style={{ gap: 8 }}>
                    <button type="button" className="boton principal chico" onClick={aplicarReglas}>Aplicar</button>
                    <button type="button" className="boton chico" onClick={() => { setPropuesta(null); decir({ rol: "asistente", texto: "(Propuesta descartada)" }); }}>Descartar</button>
                  </div>
                )}
              </section>
            )}

            {p.correcciones_base.map((c, i) => (
              <section key={i} className="bloque-propuesta">
                <span className="etiqueta-propuesta">PROPUESTA · CORREGIR EN LA BASE</span>
                <p style={{ margin: 0, fontSize: 15 }}>{c.descripcion}</p>
                <p className="chico tenue" style={{ margin: 0 }}>
                  {c.pautas ? `Afecta ${c.pautas} pautas · la semana abierta se vuelve a armar sola` : "Todavía no hay pautas así en la base: no cambia nada."}
                </p>
                {p.aplicadas.has(i) ? <span className="chico c-nueva">Aplicada.</span> : c.pautas > 0 && (
                  <button type="button" className="boton principal chico" style={{ alignSelf: "flex-start" }} onClick={() => aplicarCorreccion(c, i)}>Aplicar a las {c.pautas}</button>
                )}
              </section>
            ))}

            {acciones.length > 0 && (
              <section className="bloque-propuesta">
                <span className="etiqueta-propuesta">PROPUESTA · ADMIN</span>
                <ol style={{ margin: 0, paddingLeft: 20, fontSize: 15 }}>{acciones.map((a, i) => <li key={i}>{a.descripcion}</li>)}</ol>
                {p.aplicadas.has(-2) ? <span className="chico c-nueva">Aplicadas.</span> : (
                  <button type="button" className="boton principal chico" style={{ alignSelf: "flex-start" }} onClick={() => aplicarAdmin(acciones)}>
                    {acciones.length === 1 ? "Aplicar" : `Aplicar las ${acciones.length}`}
                  </button>
                )}
                {claves.map((c) => <p key={c} className="nota chico" style={{ margin: 0 }}>{c}. Anotala: no se vuelve a mostrar.</p>)}
              </section>
            )}

            {p.problemas.length > 0 && (
              <details className="chico tenue">
                <summary style={{ cursor: "pointer" }}>Lo que quedó sin resolver ({p.problemas.length})</summary>
                <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>{p.problemas.map((x, i) => <li key={i}>{x}</li>)}</ul>
              </details>
            )}
            {!p.logrado && (
              <button type="button" className="boton chico" style={{ alignSelf: "flex-start" }} disabled={!!trabajando}
                onClick={() => proponer(p.pedido, p.historial, true)}>Probar con el modelo fuerte (más caro)</button>
            )}
          </div>
        )}
        <div ref={fondo} />
      </div>

      {trabajando && (
        <span className="chico tenue" role="status" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span className="punto-vivo" aria-hidden="true" />
          {trabajando === "rapido" ? "Respondiendo rápido…" : "Armando una propuesta y probándola contra la grilla…"}
        </span>
      )}
      {error && <p className="error chico" role="alert">{error}</p>}
      <form onSubmit={enviarFormulario} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <label className="campo">Escribile
          <textarea className="entrada" rows={3} value={escrito} onChange={(e) => setEscrito(e.target.value)} disabled={!!trabajando}
            placeholder="Ej.: el año viene pegado al título" style={{ minHeight: 0, fontFamily: "inherit", fontSize: 14 }}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); enviar(false); } }} />
        </label>
        <div className="botones" style={{ gap: 8 }}>
          <button type="submit" className="boton fuerte" style={{ flex: "1 1 auto" }} disabled={!!trabajando}>Enviar</button>
          <button type="button" className="boton chico" style={{ minHeight: 44 }} disabled={!!trabajando} onClick={() => enviar(true)}>Proponer cambios</button>
        </div>
      </form>
    </aside>
  );
}
