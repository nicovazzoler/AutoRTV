import { useEffect, useState, type FormEvent } from "react";
import { api, ErrorApi, textoDeError } from "../api";
import { Enlace } from "../piezas/Enlace";
import { CopiarPagina } from "../piezas/CopiarPagina";
import { ZonaArchivo } from "../piezas/ZonaArchivo";
import { aSenal } from "../ruta";
import { useSesion } from "../sesion";
import type { Propuesta, Receta } from "../tipos";

interface Creada {
  id: string;
  nombre: string;
  ejemplo: string;
  pautas: { agregadas?: number; conflictos?: number; error?: string } | null;
  semana_abierta?: boolean;
  aviso?: string | null;
}

interface SenalCorta {
  id: string;
  nombre: string;
}

interface Parecidas {
  mensaje: string;
  parecidas: SenalCorta[];
  identica: boolean;
}

type Reglas =
  | { estado: "trabajando" }
  | { estado: "listo"; porcentaje: number | null; aplicadas: boolean; problemas: string[]; aviso?: string }
  | { estado: "sin-agente" | "error"; mensaje: string };

const PEDIDO = "Ajustá las tarjetas para que la grilla de entrada de este ejemplo quede igual al EPG esperado.";

/** Alta de una señal con la grilla como vino y la macro hecha. Se abre como panel al costado del Inicio. */
export function Nueva({ enPanel = false, alCerrar }: { enPanel?: boolean; alCerrar?: () => void }) {
  const { refrescarSenales } = useSesion();
  const [nombre, setNombre] = useState("");
  const [forma, setForma] = useState<"archivo" | "pegar">("archivo");
  const [cruda, setCruda] = useState<File | null>(null);
  const [pegada, setPegada] = useState("");
  const [ejemplo, setEjemplo] = useState<File | null>(null);
  const [creando, setCreando] = useState(false);
  const [error, setError] = useState("");
  const [parecidas, setParecidas] = useState<Parecidas | null>(null);
  const [creada, setCreada] = useState<Creada | null>(null);
  const [agregadaA, setAgregadaA] = useState<string | null>(null);
  const [reglas, setReglas] = useState<Reglas | null>(null);
  const [enVivo, setEnVivo] = useState<SenalCorta[]>([]);

  useEffect(() => {
    if (creada || nombre.trim().length < 3) {
      setEnVivo([]);
      return;
    }
    const espera = setTimeout(() => {
      api.get<SenalCorta[]>(`/senales-parecidas?nombre=${encodeURIComponent(nombre.trim())}`).then(setEnVivo).catch(() => setEnVivo([]));
    }, 400);
    return () => clearTimeout(espera);
  }, [nombre, creada]);

  const grillaCruda = () => cruda ?? new File([pegada], pegada.trimStart().startsWith("<") ? "grilla.html" : "grilla.txt");
  const listo = nombre.trim() && (forma === "archivo" ? !!cruda : !!pegada.trim()) && !!ejemplo;

  const armarReglas = async (c: Creada) => {
    setReglas({ estado: "trabajando" });
    try {
      const { datos: receta, version } = await api.conVersion<Receta>(`/senales/${c.id}`);
      // Armar todas las reglas desde cero le queda grande al modelo barato; pasa una vez por señal.
      const p = await api.post<Propuesta>("/asistente", { senal: receta, pedido: PEDIDO, ejemplo: c.ejemplo, fuerte: true });
      const antes = p.antes?.ejemplos[c.ejemplo] ?? null;
      const despues = p.despues?.ejemplos[c.ejemplo] ?? null;
      // Solo se aplican si mejoran: una propuesta peor que no tener reglas no sirve de punto de partida.
      if (p.receta && despues !== null && (antes === null || despues > antes)) {
        await api.put(`/senales/${c.id}`, p.receta, { "If-Match": version });
        setReglas({ estado: "listo", porcentaje: despues, aplicadas: true, problemas: [], aviso: p.aviso });
      } else {
        setReglas({ estado: "listo", porcentaje: antes, aplicadas: false, problemas: p.problemas, aviso: p.aviso });
      }
    } catch (e) {
      setReglas(e instanceof ErrorApi && e.estado === 503
        ? { estado: "sin-agente", mensaje: "El agente no está configurado: la señal arranca solo con la base." }
        : { estado: "error", mensaje: textoDeError(e) });
    }
  };

  const crear = async (extra: Record<string, string> = {}) => {
    if (!ejemplo) return;
    setCreando(true);
    setError("");
    const datos = new FormData();
    datos.append("nombre", nombre.trim());
    datos.append("grilla_cruda", grillaCruda());
    datos.append("ejemplo", ejemplo);
    for (const [k, v] of Object.entries(extra)) datos.append(k, v);
    try {
      const c = await api.subir<Creada>("/senales/crear", datos);
      setParecidas(null);
      setCreada(c);
      await refrescarSenales();
      if (extra.agregar_a) setAgregadaA(c.nombre);
      else await armarReglas(c);
    } catch (e) {
      if (e instanceof ErrorApi && e.estado === 409 && e.detalle && typeof e.detalle === "object") setParecidas(e.detalle as Parecidas);
      else setError(textoDeError(e));
    }
    setCreando(false);
  };

  const enviar = (e: FormEvent) => {
    e.preventDefault();
    crear();
  };

  const pautas = creada?.pautas;
  return (
    <div className={enPanel ? "panel-contenido" : "contenido"} style={{ maxWidth: 960 }}>
      <header className="cabecera-textos" style={{ flexDirection: "row", alignItems: "flex-start", gap: 12 }}>
        <div style={{ flex: "1 1 auto", display: "flex", flexDirection: "column", gap: 8 }}>
          <span className="antetitulo">Tres pasos</span>
          <h1 className="titulo" style={enPanel ? { fontSize: 32 } : undefined}>Agregar señal</h1>
          <p className="bajada">Con una semana como vino y cómo quedó después de la macro, armo la base y las reglas solo.</p>
        </div>
        {alCerrar && <button type="button" className="boton-redondo" aria-label="Cerrar" onClick={alCerrar}>✕</button>}
      </header>

      <form onSubmit={enviar} style={{ display: "flex", flexDirection: "column", gap: 32 }}>
        <section aria-label="Paso 1" className="paso-nueva" style={{ borderTop: "2px solid var(--texto)" }}>
          <span className="numero-paso">1</span>
          <div style={{ flex: "1 1 auto", display: "flex", flexDirection: "column", gap: 12 }}>
            <label className="campo">Nombre de la señal
              <input className="entrada serif" value={nombre} onChange={(e) => { setNombre(e.target.value); setParecidas(null); }} required
                disabled={!!creada} style={{ maxWidth: 420, minHeight: 48, fontSize: 20 }} />
            </label>
            {!parecidas && enVivo.length > 0 && (
              <div role="status" className="botones" style={{ alignItems: "center", padding: "14px 18px", borderRadius: 14, border: "1px solid var(--revisar)" }}>
                <span style={{ fontSize: 14 }}>Ya hay {enVivo.length === 1 ? "una señal" : "señales"} con un nombre parecido: {enVivo.map((p) => <b key={p.id} className="serif" style={{ fontSize: 16 }}>{p.nombre} </b>)}.
                  Si es la misma, cargá los archivos abajo y sumalos como ejemplo de esa.</span>
                <span style={{ flexGrow: 1 }} />
                {enVivo.map((p) => (
                  <button key={p.id} type="button" className="boton chico" onClick={() => crear({ agregar_a: p.id })} disabled={!listo || creando}>
                    Agregar como ejemplo de {p.nombre}
                  </button>
                ))}
              </div>
            )}
            {parecidas && (
              <div role="status" className="botones" style={{ alignItems: "center", padding: "14px 18px", borderRadius: 14, border: "1px solid var(--revisar)" }}>
                <span style={{ fontSize: 14 }}>{parecidas.mensaje}: {parecidas.parecidas.map((p) => <b key={p.id} className="serif" style={{ fontSize: 16 }}>{p.nombre} </b>)}. ¿Es la misma?</span>
                <span style={{ flexGrow: 1 }} />
                {parecidas.parecidas.map((p) => (
                  <button key={p.id} type="button" className="boton chico" onClick={() => crear({ agregar_a: p.id })} disabled={creando}>
                    Agregar como ejemplo de {p.nombre}
                  </button>
                ))}
                {!parecidas.identica && <button type="button" className="boton chico" onClick={() => crear({ confirmar: "true" })} disabled={creando}>Crear igual</button>}
              </div>
            )}
          </div>
        </section>

        <section aria-label="Paso 2" className="paso-nueva">
          <span className="numero-paso">2</span>
          <div style={{ flex: "1 1 auto", display: "flex", flexDirection: "column", gap: 16 }}>
            <div className="dos-columnas" style={{ gap: 20 }}>
              <div className="caja-archivo">
                <span className="serif" style={{ fontSize: 20 }}>Grilla como vino</span>
                <div className="botones" role="group" aria-label="Cómo la traés" style={{ gap: 6 }}>
                  <button type="button" className="boton chico" aria-pressed={forma === "archivo"} onClick={() => setForma("archivo")}>Archivo</button>
                  <button type="button" className="boton chico" aria-pressed={forma === "pegar"} onClick={() => setForma("pegar")}>Pegar texto o HTML</button>
                </div>
                {forma === "archivo" ? (
                  <ZonaArchivo chica archivo={cruda} alElegir={setCruda} deshabilitada={!!creada} etiqueta="Grilla como vino"
                    ayuda="Excel, PDF, XML, HTML guardado o .txt" />
                ) : (
                  <textarea className="entrada" rows={4} value={pegada} onChange={(e) => setPegada(e.target.value)} disabled={!!creada}
                    aria-label="Texto o HTML de la grilla" placeholder="Pegá el texto o el HTML de la página, directo" style={{ minHeight: 100, fontSize: 12 }} />
                )}
              </div>
              <div className="caja-archivo">
                <span className="serif" style={{ fontSize: 20 }}>Cómo quedó (macro hecha)</span>
                <span className="chico tenue">El EPG terminado de esa misma semana, en Excel</span>
                <ZonaArchivo chica archivo={ejemplo} alElegir={setEjemplo} accept=".xlsx,.xls" deshabilitada={!!creada} etiqueta="Cómo quedó" />
              </div>
            </div>
            <CopiarPagina titulo="¿La grilla viene de una página web?" />
            {!creada && (
              <button type="submit" className="boton principal" disabled={!listo || creando} style={{ alignSelf: "flex-start", minHeight: 48 }}>
                {creando ? "Creando…" : "Crear la señal"}
              </button>
            )}
            {error && <p className="error" role="alert">{error}</p>}
          </div>
        </section>
      </form>

      {creada && (
        <section aria-label="Paso 3" className="paso-nueva">
          <span className="numero-paso">3</span>
          <div style={{ flex: "1 1 auto", display: "flex", flexDirection: "column", gap: 14, fontSize: 15 }}>
            {agregadaA ? (
              <p style={{ margin: 0 }}>El par quedó como ejemplo de <b>{agregadaA}</b>{pautas?.agregadas !== undefined ? ` y la base sumó ${pautas.agregadas} pautas` : ""}.</p>
            ) : (
              <>
                <p style={{ margin: 0 }}>
                  {pautas?.error ? <span className="c-revisar">{pautas.error}</span>
                    : <><b>Base cargada:</b> {pautas?.agregadas ?? 0} pautas a partir del ejemplo.</>}
                  {creada.semana_abierta && " Como la grilla es de esta semana, también quedó abierta para revisar."}
                </p>
                {creada.aviso && <p className="error" role="alert" style={{ margin: 0 }}>{creada.aviso}</p>}
                {reglas?.estado === "trabajando" && (
                  <p className="tenue" role="status" style={{ margin: 0, display: "flex", alignItems: "center", gap: 8 }}>
                    <span className="punto-vivo" aria-hidden="true" />El agente arma las reglas desde el ejemplo… (puede tardar un minuto)
                  </p>
                )}
                {reglas?.estado === "listo" && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    <span>{reglas.aplicadas ? <b>Reglas armadas.</b> : "El agente no encontró reglas que mejoren el ejemplo."}
                      {reglas.porcentaje !== null && ` Aciertan el ${reglas.porcentaje} % de las celdas.`}</span>
                    {!reglas.aplicadas && reglas.problemas.length > 0 && (
                      <details className="chico tenue"><summary style={{ cursor: "pointer" }}>Qué le faltó</summary>
                        <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>{reglas.problemas.map((x) => <li key={x}>{x}</li>)}</ul>
                      </details>
                    )}
                    {!reglas.aplicadas && <button type="button" className="boton chico" style={{ alignSelf: "flex-start" }} onClick={() => armarReglas(creada)}>Probar de nuevo</button>}
                    {reglas.porcentaje !== null && (
                      <div role="progressbar" aria-label="Las reglas aciertan" aria-valuenow={reglas.porcentaje} aria-valuemin={0} aria-valuemax={100} className="barra-progreso">
                        <div style={{ width: `${reglas.porcentaje}%` }} />
                      </div>
                    )}
                    {reglas.aviso && <span className="chico c-revisar">{reglas.aviso}</span>}
                    <span className="chico tenue">Lo que falta lo cubre la base, y se sigue ajustando hablando con el agente.</span>
                  </div>
                )}
                {(reglas?.estado === "sin-agente" || reglas?.estado === "error") && <p className="chico c-revisar" style={{ margin: 0 }}>{reglas.mensaje}</p>}
              </>
            )}
            {reglas?.estado !== "trabajando" && (
              <div className="botones">
                {creada.semana_abierta
                  ? <Enlace a={aSenal(creada.id, "revisar")} className="boton principal">Revisar la semana</Enlace>
                  : <Enlace a={aSenal(creada.id, "subir")} className="boton principal">Subir la grilla de esta semana</Enlace>}
                <Enlace a={aSenal(creada.id, "senal")} className="boton">Ver la señal</Enlace>
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
