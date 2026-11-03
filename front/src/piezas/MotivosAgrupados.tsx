import { useState } from "react";
import { api, textoDeError } from "../api";
import type { Pauta } from "../tipos";
import { pedirAgente } from "./Agente";
import { type Parecida } from "./Recorrido";

interface Props {
  senalId: string;
  revisar: Pauta[];
  campos: string[];
  ocupado: string | null;
  alAceptar: (hashes: string[]) => Promise<void>;
  /** El arreglo propuesto para un grupo: se confirma pauta por pauta en el recorrido. */
  alProponer: (candidatas: Parecida[]) => void;
}

interface Grupo {
  codigo: string;
  pautas: Pauta[];
  motivo: string;
}

function agrupar(revisar: Pauta[]): Grupo[] {
  const grupos = new Map<string, Grupo>();
  for (const p of revisar) {
    (p.codigos?.length ? p.codigos : ["otro"]).forEach((codigo, i) => {
      const g = grupos.get(codigo) ?? { codigo, pautas: [], motivo: p.motivos[i] ?? p.motivos[0] ?? "" };
      g.pautas.push(p);
      grupos.set(codigo, g);
    });
  }
  return [...grupos.values()].sort((a, b) => b.pautas.length - a.pautas.length);
}

function titulo(g: Grupo): string {
  const [tipo, columna] = g.codigo.split(":");
  if (tipo === "programa_nuevo") return "Programa nuevo";
  if (tipo === "vacia") return `${columna} vacía`;
  if (tipo === "catalogo") return `${columna} no cumple el catálogo`;
  if (tipo === "sinopsis_repetida") return "La misma sinopsis en capítulos distintos";
  if (tipo === "regla_con_error") return "Una regla falló";
  return g.motivo.split(":")[0] || "Otros";
}

function resumenPauta(p: Pauta, campos: string[]): string {
  return campos.map((c) => p.salida[c]).filter((v) => v !== null && v !== undefined && v !== "").map(String).slice(0, 4).join(" · ");
}

/** "Para revisar" por motivo: un bloque por cada uno, con el arreglo rápido que le corresponde. */
export function MotivosAgrupados({ senalId, revisar, campos, ocupado, alAceptar, alProponer }: Props) {
  const [valores, setValores] = useState<Record<string, string>>({});
  const [error, setError] = useState("");

  const proponer = async (g: Grupo) => {
    setError("");
    try {
      const r = await api.post<Parecida[]>(`/senales/${senalId}/abierta/arreglo`,
        { codigo: g.codigo, hashes: g.pautas.map((p) => p.hash), valor: valores[g.codigo] ?? null });
      if (r.length) alProponer(r);
      else setError("No encontré un arreglo seguro para ese grupo: corregilas a mano o pedile al agente.");
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  const agente = (g: Grupo) => pedirAgente(
    `En "Para revisar" hay ${g.pautas.length} pautas con este motivo: «${g.motivo}». Explicame por qué pasa y proponé cómo arreglarlo para todas.`);

  return (
    <div className="motivos-agrupados">
      {error && <p className="error chico" role="alert">{error}</p>}
      {agrupar(revisar).map((g, n) => {
        const [tipo, columna] = g.codigo.split(":");
        const hashes = g.pautas.map((p) => p.hash);
        return (
          <details key={g.codigo} className="grupo-motivo" open={n < 3}>
            <summary>
              <span className="serif" style={{ fontSize: 18 }}>{titulo(g)}</span>
              <span className="c-revisar chico">{g.pautas.length} {g.pautas.length === 1 ? "pauta" : "pautas"}</span>
            </summary>
            <div className="botones" style={{ gap: 8, alignItems: "center" }}>
              {(tipo === "programa_nuevo" || tipo === "otro" || tipo === "sinopsis_repetida") && (
                <button type="button" className="boton principal chico" disabled={!!ocupado} onClick={() => alAceptar(hashes)}>
                  {tipo === "sinopsis_repetida" ? "Son capítulos distintos: están bien" : `Están bien ${g.pautas.length === 1 ? "" : "todas"}`}
                </button>
              )}
              {tipo === "catalogo" && <button type="button" className="boton principal chico" onClick={() => proponer(g)}>Arreglo sugerido para todas</button>}
              {tipo === "sinopsis_repetida" && <button type="button" className="boton chico" onClick={() => proponer(g)}>Pasar a argumento de programa</button>}
              {tipo === "vacia" && (
                <>
                  <input className="entrada" style={{ minHeight: 34, maxWidth: 240 }} placeholder={`${columna} para todas`}
                    aria-label={`Completar ${columna}`} value={valores[g.codigo] ?? ""}
                    onChange={(e) => setValores({ ...valores, [g.codigo]: e.target.value })} />
                  <button type="button" className="boton principal chico" disabled={!valores[g.codigo]?.trim()} onClick={() => proponer(g)}>Completar</button>
                </>
              )}
              <button type="button" className="boton chico" onClick={() => agente(g)}>Pedirle al agente</button>
            </div>
            <ul className="pautas-motivo">
              {g.pautas.map((p) => (
                <li key={p.hash}>
                  <span>{resumenPauta(p, campos) || "(sin datos)"}</span>
                  <span className="chico tenue">{p.motivos.join(" · ")}{p.veces > 1 ? ` · ${p.veces} veces` : ""}</span>
                  <button type="button" className="boton chico" disabled={ocupado === p.hash} onClick={() => alAceptar([p.hash])}>Está bien</button>
                </li>
              ))}
            </ul>
          </details>
        );
      })}
    </div>
  );
}
