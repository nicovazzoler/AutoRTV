import { useEffect, useMemo, useState } from "react";
import { estadoDe, FORMATOS, normalizar, ordenarPorPendiente, type TipoEstado } from "../estado";
import { haceCuanto, hoyLargo, rangoCorto, saludo } from "../fechas";
import { Enlace } from "../piezas/Enlace";
import { aSenal } from "../ruta";
import { useSesion } from "../sesion";
import type { SenalLista } from "../tipos";

const PILDORA: Record<TipoEstado, string> = { revisar: "revisar", lista: "nueva", confirmada: "nueva", espera: "tenue" };

function destinoDe(s: SenalLista) {
  return aSenal(s.id, s.semana ? "revisar" : "subir");
}

// Lo último que hizo esta persona en la señal, en palabras.
function loQueHiciste(s: SenalLista, usuario: string): string {
  const semana = s.semana;
  if (!semana) return "";
  const confirmo = semana.confirmada_por === usuario && semana.confirmada && semana.confirmada >= semana.subida;
  if (confirmo) return `Confirmaste la semana ${haceCuanto(semana.confirmada!)}`;
  if (semana.subida_por === usuario) return `Subiste la grilla${semana.version > 1 ? ` (v${semana.version})` : ""} ${haceCuanto(semana.subida)}`;
  return `${semana.subida_por} subió la grilla ${haceCuanto(semana.subida)}`;
}

function ultimoCambio(s: SenalLista): string {
  const semana = s.semana;
  if (!semana) return "—";
  if (semana.confirmada && semana.confirmada >= semana.subida) return `${semana.confirmada_por} · ${haceCuanto(semana.confirmada)}`;
  return `${semana.subida_por} · ${haceCuanto(semana.subida)}`;
}

export function Inicio() {
  const { yo, senales, recientes, refrescarSenales } = useSesion();
  const [q, setQ] = useState("");

  useEffect(() => {
    refrescarSenales().catch(() => {});
  }, [refrescarSenales]);

  const lista = useMemo(() => ordenarPorPendiente(senales ?? []), [senales]);
  const filtradas = lista.filter((s) => normalizar(s.nombre).includes(normalizar(q.trim())));
  const cuenta = (tipo: TipoEstado) => lista.filter((s) => estadoDe(s).tipo === tipo).length;
  const seguis = recientes.map((id) => lista.find((s) => s.id === id)).filter((s): s is SenalLista => !!s);

  return (
    <main className="contenido angosto">
      <header className="cabecera">
        <div className="cabecera-textos">
          <span className="antetitulo">{hoyLargo()}</span>
          <h1 className="titulo">{saludo()}, {yo.usuario}.</h1>
          {senales && (
            <p className="bajada">
              <b className="c-revisar">{cuenta("revisar")}</b> señales tienen filas para revisar, <b className="c-nueva">{cuenta("confirmada")}</b> ya
              confirmaron la semana y {cuenta("espera")} esperan su grilla.
            </p>
          )}
        </div>
        <Enlace a="/nueva" className="boton principal">Nueva señal</Enlace>
      </header>

      <label className="campo">Buscar una señal
        <input className="entrada buscador" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Nombre de la señal" />
      </label>

      {seguis.length > 0 && !q && (
        <section aria-label="Lo último que tocaste" className="seccion" style={{ gap: 14 }}>
          <h2 className="etiqueta-seccion">LO ÚLTIMO QUE TOCASTE</h2>
          <div className="tres-columnas">
            {seguis.map((s, i) => {
              const estado = estadoDe(s);
              return (
                <Enlace key={s.id} a={destinoDe(s)} style={{ display: "flex", flexDirection: "column", gap: 6, paddingTop: 14, textDecoration: "none",
                  borderTop: i === 0 ? "2px solid var(--texto)" : "1px solid var(--borde)" }}>
                  <span className="serif" style={{ fontSize: 22 }}>{s.nombre}</span>
                  <span className={`chico ${estado.tipo === "revisar" ? "c-revisar" : "c-nueva"}`} style={{ fontWeight: 600 }}>{estado.texto}</span>
                  <span className="chico tenue">{loQueHiciste(s, yo.usuario)}</span>
                </Enlace>
              );
            })}
          </div>
        </section>
      )}

      <section aria-label="Todas las señales" className="seccion">
        <div className="seccion-cabeza">
          <h2>Todas las señales</h2>
          <span className="chico tenue">{lista.length} · ordenadas por lo pendiente</span>
        </div>
        <div className="desplazable">
          <table className="tabla">
            <thead>
              <tr><th>Señal</th><th>Formato</th><th>Última semana</th><th>Estado</th><th>Último cambio</th></tr>
            </thead>
            <tbody>
              {filtradas.map((s) => {
                const estado = estadoDe(s);
                const r = s.semana?.resumen;
                return (
                  <tr key={s.id}>
                    <td><Enlace a={destinoDe(s)} className="nombre">{s.nombre}</Enlace></td>
                    <td className="tenue">{FORMATOS[s.formato] ?? s.formato}</td>
                    <td className="tenue" style={{ whiteSpace: "nowrap" }}>{r ? rangoCorto(r.desde, r.hasta) : "—"}{s.semana && s.semana.version > 1 ? ` · v${s.semana.version}` : ""}</td>
                    <td><span className={`pildora ${PILDORA[estado.tipo]}`}>{estado.texto}</span></td>
                    <td className="tenue" style={{ whiteSpace: "nowrap" }}>{ultimoCambio(s)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {senales && filtradas.length === 0 && (
          <p className="tenue" style={{ marginTop: 16 }}>
            {q ? <>Ninguna señal se llama así. <Enlace a="/nueva" style={{ color: "var(--acento)" }}>Crear una nueva</Enlace></> : "Todavía no hay señales."}
          </p>
        )}
        {filtradas.length > 0 && <Enlace a="/nueva" className="menu-nueva" style={{ alignSelf: "flex-start", marginTop: 14 }}>+ Nueva señal</Enlace>}
      </section>
    </main>
  );
}
