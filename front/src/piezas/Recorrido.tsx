import { useEffect, useRef, useState } from "react";
import { textoDeError } from "../api";

export interface Parecida {
  clave: string;
  programa: string;
  columna: string;
  antes: unknown;
  despues: unknown;
  motivo: "mismo_valor" | "mismo_trozo" | "mayusculas";
  aplica: boolean;
  porque: string;
}

const MOTIVO: Record<Parecida["motivo"], string> = {
  mismo_valor: "Mismo valor",
  mismo_trozo: "Mismo pedazo de texto",
  mayusculas: "Mismas mayúsculas",
};

function texto(v: unknown): string {
  return v === null || v === undefined || v === "" ? "(vacío)" : String(v);
}

interface Props {
  candidatas: Parecida[];
  alAplicar: (elegidas: Parecida[]) => Promise<void>;
  alCerrar: () => void;
}

/**
 * Después de una corrección: las otras pautas donde vale el mismo arreglo, una por una.
 * Vienen marcadas las que el agente dice que aplican; la corrección original ya quedó guardada.
 */
export function Recorrido({ candidatas, alAplicar, alCerrar }: Props) {
  const [marcadas, setMarcadas] = useState(() => new Set(candidatas.filter((p) => p.aplica).map((p) => p.clave)));
  const [actual, setActual] = useState(0);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");
  const filas = useRef<(HTMLLIElement | null)[]>([]);

  useEffect(() => {
    filas.current[actual]?.scrollIntoView({ block: "nearest" });
  }, [actual]);

  const aplicar = async (elegidas: Parecida[]) => {
    if (!elegidas.length) return alCerrar();
    setGuardando(true);
    setError("");
    try {
      await alAplicar(elegidas);
      alCerrar();
    } catch (e) {
      setError(textoDeError(e));
      setGuardando(false);
    }
  };

  const alternar = (clave: string) => setMarcadas((m) => {
    const nuevas = new Set(m);
    if (nuevas.has(clave)) nuevas.delete(clave);
    else nuevas.add(clave);
    return nuevas;
  });

  return (
    <div className="recorrido" role="dialog" aria-label="Pautas parecidas"
      onKeyDown={(e) => {
        if (e.key === "ArrowDown") { e.preventDefault(); setActual((i) => Math.min(i + 1, candidatas.length - 1)); }
        if (e.key === "ArrowUp") { e.preventDefault(); setActual((i) => Math.max(i - 1, 0)); }
        if (e.key === " " && (e.target as HTMLElement).tagName !== "INPUT") { e.preventDefault(); alternar(candidatas[actual].clave); }
        if (e.key === "Escape") alCerrar();
      }}>
      <div className="recorrido-cabeza">
        <div>
          <h2>Encontré {candidatas.length} {candidatas.length === 1 ? "parecida" : "parecidas"} a lo que cambiaste</h2>
          <span className="chico tenue">Tu corrección ya quedó guardada. Marcá en cuáles hacer lo mismo (↑ ↓ para recorrerlas, espacio para marcar).</span>
        </div>
        <button type="button" className="boton-redondo" style={{ flexBasis: 32, height: 32 }} aria-label="Cerrar" onClick={alCerrar}>✕</button>
      </div>
      <ul className="recorrido-lista" tabIndex={0} autoFocus>
        {candidatas.map((p, i) => (
          <li key={p.clave} ref={(el) => { filas.current[i] = el; }} aria-current={i === actual} onClick={() => setActual(i)}>
            <input type="checkbox" checked={marcadas.has(p.clave)} onChange={() => alternar(p.clave)}
              aria-label={`Arreglar ${texto(p.antes)}`} />
            <div>
              <span className="chico tenue">{p.programa ? `${p.programa} · ` : ""}{p.columna} · {MOTIVO[p.motivo]}</span>
              <span><span className="tachado">{texto(p.antes)}</span> → <b>{texto(p.despues)}</b></span>
              {p.porque && <span className={`chico ${p.aplica ? "c-nueva" : "c-revisar"}`}>Agente: {p.porque}</span>}
            </div>
          </li>
        ))}
      </ul>
      {error && <p className="error chico" role="alert">{error}</p>}
      <div className="botones" style={{ gap: 8 }}>
        <button type="button" className="boton principal" disabled={guardando || marcadas.size === 0}
          onClick={() => aplicar(candidatas.filter((p) => marcadas.has(p.clave)))}>
          {guardando ? "Arreglando…" : `Arreglar las marcadas (${marcadas.size})`}
        </button>
        <button type="button" className="boton" disabled={guardando} onClick={() => aplicar(candidatas)}>Arreglar todas</button>
        <button type="button" className="boton" disabled={guardando} onClick={alCerrar}>Ninguna</button>
      </div>
    </div>
  );
}
