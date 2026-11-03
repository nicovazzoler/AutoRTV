import { useEffect, useMemo, useState } from "react";
import { normalizar } from "../estado";
import { hoyLargo, saludo } from "../fechas";
import { Enlace } from "../piezas/Enlace";
import { aSenal, navegar } from "../ruta";
import { useSesion } from "../sesion";
import { Nueva } from "./Nueva";
import { persona } from "../nombre";

/** La lista de señales para elegir con cuál trabajar; arriba las que tienen algo para revisar. */
export function Inicio({ nueva }: { nueva: boolean }) {
  const { yo, senales, refrescarSenales, setContexto } = useSesion();
  const [q, setQ] = useState("");

  useEffect(() => {
    refrescarSenales().catch(() => {});
    setContexto("Inicio · lista de señales");
  }, [refrescarSenales, setContexto]);

  const lista = useMemo(() => {
    const pendientes = (s: { semana: { resumen?: { revisar?: number } | null } | null }) => s.semana?.resumen?.revisar ?? 0;
    return [...(senales ?? [])].sort((a, b) => Number(pendientes(b) > 0) - Number(pendientes(a) > 0) || a.nombre.localeCompare(b.nombre, "es"));
  }, [senales]);
  const buscado = normalizar(q.trim());
  const filtradas = lista.filter((s) => !buscado || normalizar(s.nombre).includes(buscado));

  return (
    <div className="pantalla-con-panel">
      <main className="contenido" style={{ maxWidth: 960 }}>
        <header className="cabecera-textos">
          <span className="antetitulo">{hoyLargo()} · {saludo().toLowerCase()}, {persona(yo.usuario)}</span>
          <h1 className="titulo">Señales</h1>
        </header>
        <div className="botones" style={{ alignItems: "center", paddingBottom: 14, borderBottom: "2px solid var(--texto)" }}>
          <input className="entrada buscador" type="search" aria-label="Filtrar señales" placeholder="Filtrar señales…" value={q}
            onChange={(e) => setQ(e.target.value)} style={{ flex: "1 1 320px" }} />
          <Enlace a="/nueva" className="boton principal">+ Agregar señal</Enlace>
        </div>
        <ul className="lista-senales">
          {filtradas.map((s) => {
            const revisar = s.semana?.resumen?.revisar ?? 0;
            return (
              <li key={s.id}>
                <Enlace a={aSenal(s.id)} className="fila-senal">
                  <span className={`punto${revisar ? " revisar" : ""}`} aria-hidden="true" />
                  <span className="nombre">{s.nombre}</span>
                  {revisar > 0 && <span className="pendiente">{revisar} para revisar</span>}
                  <span className="tenue" aria-hidden="true">›</span>
                </Enlace>
              </li>
            );
          })}
        </ul>
        {senales && filtradas.length === 0 && (
          <p className="tenue">{q ? <>Ninguna señal se llama así. <Enlace a="/nueva" style={{ color: "var(--acento)" }}>Agregarla</Enlace></> : "Todavía no hay señales."}</p>
        )}
      </main>
      {nueva && (
        <aside className="panel-lateral ancho" aria-label="Agregar señal">
          <Nueva enPanel alCerrar={() => navegar("/")} />
        </aside>
      )}
    </div>
  );
}
