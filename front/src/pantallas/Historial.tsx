import { useEffect, useState } from "react";
import { api, textoDeError } from "../api";
import { haceCuanto, rangoSemana } from "../fechas";
import { persona } from "../nombre";
import { useSesion } from "../sesion";

interface Carga {
  senal_id: string;
  carga: string;
  desde: string | null;
  hasta: string | null;
  ultima: string;
  usuarios: string[];
  cuenta: Record<string, number>;
  confirmada: boolean;
}

interface Cambio {
  usuario: string;
  fecha: string;
  tipo: "corregida" | "aceptada" | "confirmada" | "base" | "reglas";
  programa: string | null;
  columna: string | null;
  antes: unknown;
  despues: unknown;
}

const PLURAL: Record<string, [string, string]> = {
  corregida: ["corregida", "corregidas"], aceptada: ["aceptada", "aceptadas"], confirmada: ["confirmada", "confirmadas"],
  base: ["cambio en la base", "cambios en la base"], reglas: ["cambio de reglas", "cambios de reglas"],
};
const TIPO: Record<Cambio["tipo"], string> = {
  corregida: "Corrigió", aceptada: "Aceptó", confirmada: "Confirmó", base: "Cambió en la base", reglas: "Reglas",
};

function texto(v: unknown): string {
  return v === null || v === undefined || v === "" ? "(vacío)" : String(v);
}

function resumen(cuenta: Record<string, number>): string {
  return Object.entries(cuenta).map(([t, n]) => `${n} ${PLURAL[t]?.[n === 1 ? 0 : 1] ?? t}`).join(" · ");
}

/** Qué se cambió, carga por carga de la semana. Cada uno ve lo suyo; el admin ve lo de todos y filtra por persona. */
export function Historial() {
  const { yo, senales, setContexto } = useSesion();
  const [cargas, setCargas] = useState<Carga[] | null>(null);
  const [usuarios, setUsuarios] = useState<string[]>([]);
  const [quien, setQuien] = useState("");
  const [abierta, setAbierta] = useState<string | null>(null);
  const [detalle, setDetalle] = useState<Cambio[]>([]);
  const [error, setError] = useState("");

  useEffect(() => setContexto("Historial"), [setContexto]);
  useEffect(() => {
    if (yo.admin) api.get<{ usuario: string }[]>("/usuarios").then((u) => setUsuarios(u.map((x) => x.usuario))).catch(() => {});
  }, [yo.admin]);
  useEffect(() => {
    setAbierta(null);
    api.get<Carga[]>(`/historial${quien ? `?usuario=${encodeURIComponent(quien)}` : ""}`).then(setCargas).catch((e) => setError(textoDeError(e)));
  }, [quien]);

  const abrir = async (c: Carga) => {
    const clave = `${c.senal_id}|${c.carga}`;
    if (abierta === clave) return setAbierta(null);
    setAbierta(clave);
    setDetalle([]);
    const params = new URLSearchParams({ carga: c.carga, ...(quien ? { usuario: quien } : {}) });
    api.get<Cambio[]>(`/historial/${c.senal_id}?${params}`).then(setDetalle).catch((e) => setError(textoDeError(e)));
  };

  return (
    <main className="contenido" style={{ maxWidth: 1120 }}>
      <header className="cabecera-textos">
        <span className="antetitulo">{yo.admin ? "De todos" : "Lo tuyo"}</span>
        <h1 className="titulo">Historial</h1>
        <p className="bajada">Cada carga de la semana con lo que se corrigió, se aceptó, se confirmó y los cambios de reglas.</p>
      </header>
      {yo.admin && (
        <label className="campo" style={{ maxWidth: 260 }}>Persona
          <select className="entrada" value={quien} onChange={(e) => setQuien(e.target.value)}>
            <option value="">Todas</option>
            {usuarios.map((u) => <option key={u} value={u}>{persona(u)}</option>)}
          </select>
        </label>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      {cargas === null ? <p className="tenue">Cargando…</p> : cargas.length === 0 ? <p className="tenue">Todavía no hay cambios.</p> : (
        <ul className="lista-historial">
          {cargas.map((c) => {
            const clave = `${c.senal_id}|${c.carga}`;
            return (
              <li key={clave}>
                <button type="button" className="fila-historial" aria-expanded={abierta === clave} onClick={() => abrir(c)}>
                  <span className="serif" style={{ fontSize: 18 }}>{senales?.find((s) => s.id === c.senal_id)?.nombre ?? c.senal_id}</span>
                  <span>{c.desde ? rangoSemana(c.desde, c.hasta) : "Sin semana abierta"}</span>
                  <span className="tenue">{c.usuarios.map(persona).join(", ")} · {haceCuanto(c.ultima)}</span>
                  <span className={c.confirmada ? "c-nueva" : "tenue"}>{c.confirmada ? "Confirmada" : "Sin confirmar"}</span>
                  <span className="chico">{resumen(c.cuenta)}</span>
                </button>
                {abierta === clave && (
                  <ul className="detalle-historial">
                    {detalle.map((d, i) => (
                      <li key={i}>
                        <span className="chico tenue">{persona(d.usuario)} · {haceCuanto(d.fecha)} · {TIPO[d.tipo]}</span>
                        <span>
                          {d.programa && <b>{d.programa}</b>}
                          {d.columna && <> · {d.columna}: <span className="tachado">{texto(d.antes)}</span> → {texto(d.despues)}</>}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </main>
  );
}
