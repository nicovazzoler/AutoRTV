import { useEffect, useRef, useState, type FormEvent, type PointerEvent as EventoPuntero } from "react";
import { api, ErrorApi, textoDeError } from "../api";
import { haceCuanto } from "../fechas";
import { fraseCambio } from "../frases";
import { useSesion } from "../sesion";
import { navegar } from "../ruta";
import type { AccionAdmin, AccionUi, Charla, ChatGuardado, CorreccionBase, Limites, PedidoDePropuesta, Propuesta, Receta } from "../tipos";

interface Mensaje {
  rol: "persona" | "asistente";
  texto: string;
}

interface PropuestaAbierta extends Propuesta {
  id: number;
  senal: string;
  nombreSenal: string;
  otraSenal: boolean;
  pedido: string;
  historial: Mensaje[];
  version: string; // de la receta sobre la que se armó, para no pisar un cambio de otro
  aplicadas: Set<number>;
}

const PLEGADO = "autortv.agente-plegado";
const ANCHO = "autortv.agente-ancho";
const CHAT = "autortv.agente-chat";

function leer(clave: string): string | null {
  try {
    return localStorage.getItem(clave);
  } catch {
    return null;
  }
}

function guardar(clave: string, valor: string | null) {
  try {
    if (valor === null) localStorage.removeItem(clave);
    else localStorage.setItem(clave, valor);
  } catch {
    // Sin almacenamiento: dura hasta recargar.
  }
}

const PREGUNTAR = "autortv.agente-preguntar";
const PEDIDO_SIN_EJEMPLO = "Es una señal nueva y no tiene ejemplo de cómo tiene que quedar. Mirá la grilla y preguntame lo que " +
  "necesites para armar las reglas: qué es programa y qué capítulo, si hay temporada o número, y qué columnas van al EPG.";

/** Deja pedido que el agente se abra en la semana de esa señal y pregunte lo que necesita (señal nueva sin ejemplo). */
export function pedirAlAgente(senalId: string) {
  try {
    sessionStorage.setItem(PREGUNTAR, senalId);
  } catch {
    // Sin almacenamiento, la persona le escribe al agente.
  }
}

const PEDIDO = "autortv:pedir-agente";

/** Abre el agente y le manda un pedido armado por la pantalla (por ejemplo, desde un grupo de motivos). */
export function pedirAgente(pedido: string) {
  window.dispatchEvent(new CustomEvent(PEDIDO, { detail: pedido }));
}

// Lo que se hace desde el agente queda marcado así en el historial.
const DEL_AGENTE = { "X-Origen": "agente" };

const anchoInicial = () => Number(leer(ANCHO)) || Math.round(window.innerWidth / 3);
const limitarAncho = (a: number) => Math.min(Math.max(a, 320), Math.round(window.innerWidth * 0.7));

const RUTAS: Record<string, (senal: string) => string> = {
  inicio: () => "/", semana: (s) => `/s/${s}`, base: (s) => `/base/${s}`, configuracion: (s) => `/base/${s}/config`,
  administrar: () => "/admin",
};

function texto(v: unknown): string {
  return v === null || v === undefined || v === "" ? "(vacío)" : String(v);
}

/**
 * El agente: un círculo flotante en todas las pantallas que se abre en un panel a la derecha (el ancho se arrastra).
 * Los chats quedan guardados por persona y siguen al cambiar de pantalla o de señal.
 */
export function Agente({ senalId }: { senalId: string | null }) {
  const { yo, senales, tocar, contexto } = useSesion();
  const tablaId = senales?.find((s) => s.id === senalId)?.semana?.tabla_id ?? null;
  const [hilo, setHilo] = useState<Mensaje[]>([]);
  const [chatId, setChatId] = useState<number | null>(() => Number(leer(CHAT)) || null);
  const [chats, setChats] = useState<ChatGuardado[] | null>(null);
  const [acciones, setAcciones] = useState<AccionUi[]>([]);
  // Una charla puede pedir propuestas para varias señales: se muestran todas, cada una con su «Aplicar».
  const [propuestas, setPropuestas] = useState<PropuestaAbierta[]>([]);
  const ultimaPropuesta = useRef(0);
  const [escrito, setEscrito] = useState("");
  const [trabajando, setTrabajando] = useState<"" | "rapido" | "propuesta">("");
  const [error, setError] = useState("");
  const [limites, setLimites] = useState<Limites | null>(null);
  const [plegado, setPlegado] = useState(() => leer(PLEGADO) !== "0");
  const [ancho, setAncho] = useState(() => limitarAncho(anchoInicial()));
  const [claves, setClaves] = useState<string[]>([]);
  const fondo = useRef<HTMLDivElement>(null);
  // Los mensajes se guardan en orden: el primero abre el chat y los demás necesitan su id.
  const cola = useRef<Promise<number | null>>(Promise.resolve(chatId));

  const refrescarLimites = () => api.get<Limites>("/asistente/limites").then(setLimites).catch(() => {});
  useEffect(() => {
    refrescarLimites();
    if (chatId) api.get<Mensaje[]>(`/agente/conversaciones/${chatId}`).then(setHilo).catch(() => elegirChat(null));
  }, []);
  useEffect(() => {
    fondo.current?.scrollIntoView({ block: "nearest" });
  }, [hilo, acciones]);
  useEffect(() => {
    setPropuestas([]);  // eran de la señal anterior
    let pendiente: string | null = null;
    try {
      pendiente = sessionStorage.getItem(PREGUNTAR);
    } catch {
      return;
    }
    if (!senalId || pendiente !== senalId) return;
    sessionStorage.removeItem(PREGUNTAR);
    plegar(false);
    elegirChat(null);
    void enviar(PEDIDO_SIN_EJEMPLO);
  }, [senalId]);

  // El listener se registra una vez y llama siempre al enviar de este render.
  const enviarActual = useRef<(fijo?: string) => Promise<void>>(async () => {});
  useEffect(() => {
    const escuchar = (e: Event) => {
      plegar(false);
      void enviarActual.current((e as CustomEvent<string>).detail);
    };
    window.addEventListener(PEDIDO, escuchar);
    return () => window.removeEventListener(PEDIDO, escuchar);
  }, []);

  const plegar = (si: boolean) => {
    setPlegado(si);
    guardar(PLEGADO, si ? "1" : "0");
  };

  const elegirChat = (id: number | null) => {
    setChatId(id);
    guardar(CHAT, id === null ? null : String(id));
    cola.current = Promise.resolve(id);
    setPropuestas([]);
    setAcciones([]);
    setChats(null);
    if (id === null) setHilo([]);
    else api.get<Mensaje[]>(`/agente/conversaciones/${id}`).then(setHilo).catch((e) => setError(textoDeError(e)));
  };

  const verChats = () => {
    if (chats) return setChats(null);
    api.get<ChatGuardado[]>("/agente/conversaciones").then(setChats).catch((e) => setError(textoDeError(e)));
  };

  const decir = (m: Mensaje) => {
    setHilo((h) => [...h, m]);
    cola.current = cola.current.then(async (id) => {
      try {
        const r = await api.post<{ conversacion_id: number }>("/agente/mensajes", { conversacion_id: id, ...m, senal_id: senalId });
        if (r.conversacion_id !== id) {
          setChatId(r.conversacion_id);
          guardar(CHAT, String(r.conversacion_id));
        }
        return r.conversacion_id;
      } catch {
        return id;  // si no se guardó, el chat sigue en pantalla igual
      }
    });
  };

  const arrastrarBorde = (e: EventoPuntero<HTMLDivElement>) => {
    e.preventDefault();
    const mover = (ev: PointerEvent) => setAncho(limitarAncho(window.innerWidth - ev.clientX - 16));
    const soltar = () => {
      window.removeEventListener("pointermove", mover);
      window.removeEventListener("pointerup", soltar);
      setAncho((a) => {
        guardar(ANCHO, String(a));
        return a;
      });
    };
    window.addEventListener("pointermove", mover);
    window.addEventListener("pointerup", soltar);
  };

  const moverPagina = (a: AccionUi) => {
    if (a.tipo === "ir_a") navegar(RUTAS[a.pantalla]?.(a.senal) ?? "/");
    if (a.tipo === "nueva_senal") navegar(`/nueva?nombre=${encodeURIComponent(a.nombre)}`);
    decir({ rol: "asistente", texto: `(${a.descripcion})` });
  };

  const hacer = async (a: AccionUi) => {
    setAcciones((lista) => lista.filter((x) => x !== a));
    setError("");
    try {
      if (a.tipo === "armar_reglas") {
        await api.post(`/senales/${a.senal}/reglas/armar`, {}, DEL_AGENTE);
        decir({ rol: "asistente", texto: "(Armando las reglas desde los ejemplos: el resultado aparece en Configuración › Reglas.)" });
      }
      if (a.tipo === "corregir_pautas") {
        // Las pautas que contó el agente al proponerlo: una que llegó después no se toca.
        const r = await api.post<{ editadas: number }>(`/senales/${a.senal}/pautas/editar-varias`,
          { hashes: a.hashes, columna: a.columna, valor: a.valor ?? null }, DEL_AGENTE);
        decir({ rol: "asistente", texto: `(Corregidas ${r.editadas} pautas de ${a.nombre_senal}.)` });
      }
      if (a.tipo === "confirmar_semana") {
        await api.post(`/senales/${a.senal}/abierta/confirmar`, {}, DEL_AGENTE);
        decir({ rol: "asistente", texto: `(Semana de ${a.nombre_senal} confirmada.)` });
      }
      tocar();
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  const proponer = async (pedido: string, historial: Mensaje[], fuerte = false, destino?: PedidoDePropuesta) => {
    const senal = destino?.senal ?? senalId;
    if (!senal) return;
    setTrabajando("propuesta");
    try {
      const { datos: receta, version } = await api.conVersion<Receta>(`/senales/${senal}`);
      const tabla = senales?.find((x) => x.id === senal)?.semana?.tabla_id ?? null;
      const p = await api.post<Propuesta>("/asistente", { senal: receta, pedido, tabla_id: tabla, historial, fuerte, contexto });
      const nueva = { ...p, id: ++ultimaPropuesta.current, senal, nombreSenal: receta.nombre, otraSenal: senal !== senalId,
        pedido, historial, version, aplicadas: new Set<number>() };
      // Pedirla de nuevo con el modelo fuerte reemplaza la anterior del mismo pedido.
      setPropuestas((ps) => [...ps.filter((x) => !(x.senal === senal && x.pedido === pedido)), nueva]);
      decir({ rol: "asistente", texto: p.explicacion || (p.receta ? "Te dejo una propuesta abajo." : "No llegué a una propuesta que sirva.") });
    } catch (e) {
      setError(textoDeError(e));
    }
    setTrabajando("");
    refrescarLimites();
  };

  const enviar = async (fijo?: string) => {
    const pedido = (fijo ?? escrito).trim();
    if (!pedido) {
      setError("Escribí qué querés que haga el agente");
      return;
    }
    const previo = fijo === PEDIDO_SIN_EJEMPLO ? [] : hilo;  // la señal sin ejemplo arranca un chat nuevo
    setError("");
    setEscrito("");
    decir({ rol: "persona", texto: pedido });
    setTrabajando("rapido");
    try {
      const receta = senalId ? (await api.conVersion<Receta>(`/senales/${senalId}`)).datos : null;
      const c = await api.post<Charla>("/asistente/charla", { senal: receta, pedido, tabla_id: tablaId, historial: previo, contexto });
      if (c.respuesta) decir({ rol: "asistente", texto: c.respuesta });
      const acciones = c.acciones ?? [];
      acciones.filter((a) => a.nivel === "pagina").forEach(moverPagina);
      setAcciones(acciones.filter((a) => a.nivel !== "pagina"));
      setTrabajando("");
      refrescarLimites();
      for (const destino of c.propuestas ?? []) await proponer(destino.pedido, previo, false, destino);
    } catch (e) {
      setError(textoDeError(e));
      setTrabajando("");
    }
  };

  enviarActual.current = enviar;

  const enviarFormulario = (e: FormEvent) => {
    e.preventDefault();
    enviar();
  };

  const marcarAplicada = (id: number, i: number) =>
    setPropuestas((ps) => ps.map((x) => (x.id === id ? { ...x, aplicadas: new Set([...x.aplicadas, i]) } : x)));

  const descartar = (p: PropuestaAbierta) => {
    setPropuestas((ps) => ps.filter((x) => x.id !== p.id));
    decir({ rol: "asistente", texto: `(Propuesta para ${p.nombreSenal} descartada)` });
  };

  const aplicarReglas = async (p: PropuestaAbierta) => {
    if (!p.receta) return;
    setError("");
    try {
      await api.put(`/senales/${p.senal}`, p.receta, { "If-Match": p.version, ...DEL_AGENTE });
      decir({ rol: "asistente", texto: `(Reglas de ${p.nombreSenal} aplicadas. Se pueden deshacer desde Base › Configuración › Reglas.)` });
      marcarAplicada(p.id, -1);
      tocar();
    } catch (e) {
      setError(e instanceof ErrorApi && e.estado === 409
        ? `${e.message}. Pedile la propuesta de nuevo para armarla sobre las reglas de ahora.` : textoDeError(e));
    }
  };

  const aplicarCorreccion = async (p: PropuestaAbierta, c: CorreccionBase, i: number) => {
    setError("");
    try {
      const r = await api.post<{ editadas: number }>(`/senales/${p.senal}/pautas/editar-varias`,
        { filtro: c.filtro, columna: c.columna, valor: c.valor === null ? null : String(c.valor) }, DEL_AGENTE);
      decir({ rol: "asistente", texto: `(Corregidas ${r.editadas} pautas de ${p.nombreSenal} en la base.)` });
      marcarAplicada(p.id, i);
      tocar();
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  const aplicarAdmin = async (p: PropuestaAbierta, acciones: AccionAdmin[]) => {
    setError("");
    try {
      const r = await api.post<{ descripcion: string; ok: boolean; clave?: string; error?: string }[]>("/admin/acciones", { acciones });
      setClaves(r.filter((x) => x.clave).map((x) => `${x.descripcion}: la clave es ${x.clave}`));
      decir({ rol: "asistente", texto: r.map((x) => `(${x.ok ? "Hecho" : "No se pudo"}: ${x.descripcion}${x.error ? ` — ${x.error}` : ""})`).join("\n") });
      marcarAplicada(p.id, -2);
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  if (plegado) {
    return <button type="button" className="agente-circulo" aria-label="Abrir el agente" title="Agente" onClick={() => plegar(false)}>✦</button>;
  }

  return (
    <aside className="agente flotante" aria-label="Agente" style={{ width: ancho }}>
      <div className="agente-borde" role="separator" aria-orientation="vertical" aria-label="Cambiar el ancho del agente" onPointerDown={arrastrarBorde} />
      <div className="agente-cabeza">
        <h2>Agente</h2>
        <span style={{ flexGrow: 1 }} />
        <button type="button" className="boton chico" aria-expanded={!!chats} onClick={verChats}>Chats</button>
        {hilo.length > 0 && <button type="button" className="boton chico" onClick={() => elegirChat(null)}>Nuevo chat</button>}
        <button type="button" className="boton-redondo" style={{ flexBasis: 36, height: 36 }} aria-label="Cerrar el agente" title="Cerrar" onClick={() => plegar(true)}>✕</button>
      </div>
      {chats && (
        <ul className="lista-chats" aria-label="Chats anteriores">
          {chats.length === 0 && <li className="tenue chico">Todavía no hay chats guardados.</li>}
          {chats.map((c) => (
            <li key={c.id}>
              <button type="button" aria-current={c.id === chatId} onClick={() => elegirChat(c.id)}>
                <span>{c.titulo}</span><span className="tenue chico">{haceCuanto(c.actualizada)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {contexto && <span className="etiqueta-contexto">Viendo: {contexto}</span>}
      {limites && <span className="chico tenue">Te quedan {limites.quedan} de {limites.limite_diario} pedidos hoy</span>}

      <div className="hilo" aria-live="polite">
        {hilo.length === 0 && (
          <p className="tenue chico">
            {senalId ? "Preguntale por qué una fila quedó así, o pedile un cambio: «el año viene pegado al título», «todos los Noches de Jazz van con género Música»."
              : "Pedile lo que necesites: «llevame a la semana de XT», «¿qué le falta revisar a TBN?», «creá la señal Canal XX»."}
          </p>
        )}
        {hilo.map((m, i) => (
          <p key={i} className={`mensaje ${m.rol}${m.texto.startsWith("(") ? " nota-hilo" : ""}`}>{m.rol === "persona" ? "—" : ""}{m.texto}</p>
        ))}

        {acciones.length > 0 && (
          <section className="bloque-propuesta" aria-label="Lo que puedo hacer">
            {acciones.map((a, i) => (
              <div key={i} className={`accion-agente${a.otra_senal ? " otra-senal" : ""}`}>
                <span>
                  {a.descripcion}
                  {a.otra_senal && <><br /><b className="c-revisar chico">Ojo: es en {a.nombre_senal}, no en la señal que estás mirando.</b></>}
                </span>
                <button type="button" className="boton principal chico" onClick={() => hacer(a)}>
                  {a.otra_senal ? `Hacerlo en ${a.nombre_senal}` : "Hacerlo"}
                </button>
              </div>
            ))}
          </section>
        )}

        {propuestas.map((p) => {
          const efecto = p.efecto;
          const ejemplos = p.despues ? Object.entries(p.despues.ejemplos) : [];
          const accionesAdmin = yo.admin ? p.acciones_admin ?? [] : [];
          return (
          <div key={p.id} role="group" className={`propuesta-agente${p.otraSenal ? " otra-senal" : ""}`} aria-label={`Propuesta para ${p.nombreSenal}`}>
            {p.otraSenal && (
              <p className="chico c-revisar" style={{ margin: 0 }}><b>Propuesta para {p.nombreSenal}</b>, no para la señal que estás mirando.</p>
            )}
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
                    <button type="button" className="boton principal chico" onClick={() => aplicarReglas(p)}>Aplicar</button>
                    <button type="button" className="boton chico" onClick={() => descartar(p)}>Descartar</button>
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
                  <button type="button" className="boton principal chico" style={{ alignSelf: "flex-start" }} onClick={() => aplicarCorreccion(p, c, i)}>Aplicar a las {c.pautas}</button>
                )}
              </section>
            ))}

            {accionesAdmin.length > 0 && (
              <section className="bloque-propuesta">
                <span className="etiqueta-propuesta">PROPUESTA · ADMIN</span>
                <ol style={{ margin: 0, paddingLeft: 20, fontSize: 15 }}>{accionesAdmin.map((a, i) => <li key={i}>{a.descripcion}</li>)}</ol>
                {p.aplicadas.has(-2) ? <span className="chico c-nueva">Aplicadas.</span> : (
                  <button type="button" className="boton principal chico" style={{ alignSelf: "flex-start" }} onClick={() => aplicarAdmin(p, accionesAdmin)}>
                    {accionesAdmin.length === 1 ? "Aplicar" : `Aplicar las ${accionesAdmin.length}`}
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
                onClick={() => proponer(p.pedido, p.historial, true, { senal: p.senal, nombre_senal: p.nombreSenal, pedido: p.pedido, otra_senal: p.otraSenal })}>
                Probar con el modelo fuerte (más caro)</button>
            )}
          </div>
          );
        })}
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
        <div className="caja-chat">
          <textarea rows={3} value={escrito} onChange={(e) => setEscrito(e.target.value)} disabled={!!trabajando}
            aria-label="Escribile al agente" placeholder="Ej.: el año viene pegado al título"
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); enviar(); } }} />
          <button type="submit" className="enviar-chat" aria-label="Enviar" disabled={!!trabajando || !escrito.trim()}>↑</button>
        </div>
      </form>
    </aside>
  );
}
