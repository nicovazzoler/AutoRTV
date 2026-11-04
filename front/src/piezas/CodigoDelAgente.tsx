import { useState } from "react";
import { api, textoDeError } from "../api";
import { useSesion } from "../sesion";

export interface Codigo {
  codigo: string;
  explicacion: string;
  activo: boolean;
  comprobado: boolean;
  resultado: string;
  autor: string;
}

const TITULOS = { lector: "Lector en código", final: "Paso final en código" };

/** El código que escribió el agente para la señal: qué hace, cómo dio contra el ejemplo y, para el admin, apagarlo. */
export function CodigoDelAgente({ senalId, donde, codigo, alCambiar }: {
  senalId: string;
  donde: "lector" | "final";
  codigo: Codigo;
  alCambiar: () => void;
}) {
  const { yo } = useSesion();
  const [error, setError] = useState("");
  const estado = !codigo.activo ? "apagado" : codigo.comprobado ? "prendido" : "prendido, sin comprobar con un ejemplo";

  async function cambiar(activo: boolean) {
    setError("");
    try {
      await api.post(`/senales/${senalId}/codigo`, { donde, activo });
      alCambiar();
    } catch (e) {
      setError(textoDeError(e));
    }
  }

  return (
    <div className="codigo-agente" aria-label={TITULOS[donde]}>
      <span className="etiqueta-propuesta">{TITULOS[donde].toUpperCase()} · LO ESCRIBIÓ EL AGENTE</span>
      <span><b className={codigo.activo ? undefined : "c-revisar"}>{estado[0].toUpperCase() + estado.slice(1)}</b>{codigo.resultado && <span className="tenue"> · {codigo.resultado}</span>}</span>
      <p style={{ margin: 0 }}>{codigo.explicacion || "Sin explicación."}</p>
      <details>
        <summary className="chico">Ver el código</summary>
        <pre className="codigo">{codigo.codigo}</pre>
      </details>
      {error && <p className="error" role="alert">{error}</p>}
      {yo.admin && (
        <div><button type="button" className={codigo.activo ? "boton chico peligro" : "boton chico"} onClick={() => cambiar(!codigo.activo)}>
          {codigo.activo ? "Apagarlo" : "Prenderlo"}
        </button></div>
      )}
    </div>
  );
}
