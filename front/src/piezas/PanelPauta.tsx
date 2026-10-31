import { useState } from "react";
import { api, textoDeError } from "../api";
import { haceCuanto } from "../fechas";
import type { Celdas, PautaBase } from "../tipos";

interface Props {
  senalId: string;
  pauta: PautaBase;
  columnas: string[];
  programa: string | null;
  alCambiar: () => Promise<void>;
  alCerrar: () => void;
}

// Columnas del capítulo: no tiene sentido copiarlas a todos los capítulos del programa.
const DEL_CAPITULO = /cap|temp|sin|episod/i;

function texto(v: unknown): string {
  return v === null || v === undefined ? "" : String(v);
}

/** Una pauta de la base para editar entera, con "Guardado · deshacer" y lo del programa aplicable a todos sus capítulos. */
export function PanelPauta({ senalId, pauta, columnas, programa, alCambiar, alCerrar }: Props) {
  const [valores, setValores] = useState<Record<string, string>>(() => Object.fromEntries(columnas.map((c) => [c, texto(pauta.salida[c])])));
  const [anterior, setAnterior] = useState<Celdas | null>(null);
  const [aviso, setAviso] = useState("");
  const [error, setError] = useState("");
  const nombrePrograma = programa ? texto(pauta.salida[programa]) : "";
  const cambiadas = columnas.filter((c) => valores[c] !== texto(pauta.salida[c]));

  const guardar = async () => {
    setError("");
    try {
      const salida = { ...pauta.salida, ...Object.fromEntries(cambiadas.map((c) => [c, valores[c] || null])) };
      await api.put(`/senales/${senalId}/pautas/${pauta.hash}`, { salida });
      setAnterior(pauta.salida);
      setAviso("Guardado en la base");
      await alCambiar();
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  const deshacer = async () => {
    if (!anterior) return;
    try {
      await api.put(`/senales/${senalId}/pautas/${pauta.hash}`, { salida: anterior });
      setValores(Object.fromEntries(columnas.map((c) => [c, texto(anterior[c])])));
      setAnterior(null);
      setAviso("Deshecho");
      await alCambiar();
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  const aTodoElPrograma = async (columna: string) => {
    if (!programa || !nombrePrograma) return;
    setError("");
    try {
      const r = await api.post<{ editadas: number }>(`/senales/${senalId}/pautas/editar-varias`,
        { filtro: { [programa]: nombrePrograma }, columna, valor: valores[columna] || null });
      setAviso(`${columna} = «${valores[columna] || "(vacío)"}» en los ${r.editadas} capítulos de ${nombrePrograma}`);
      await alCambiar();
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  const olvidar = async () => {
    if (!confirm("¿Olvidar esta pauta? La próxima vez que venga la arman las reglas y pide revisión.")) return;
    try {
      await api.borrar(`/senales/${senalId}/pautas/${pauta.hash}`);
      await alCambiar();
      alCerrar();
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  return (
    <aside className="panel-lateral" aria-label="Pauta">
      <div className="panel-contenido">
        <div className="agente-cabeza">
          <div style={{ flex: "1 1 auto", minWidth: 0 }}>
            <span className="chico tenue">{pauta.estado === "editada" ? "corregida a mano" : "aprobada"} por {pauta.usuario} · {haceCuanto(pauta.actualizado)}</span>
            <h2 className="serif" style={{ margin: "2px 0 0", fontSize: 24, fontWeight: 500 }}>{nombrePrograma || "Pauta"}</h2>
          </div>
          <button type="button" className="boton-redondo" aria-label="Cerrar" onClick={alCerrar}>✕</button>
        </div>
        <p className="nota chico" style={{ margin: 0 }}>Cómo vino: {Object.values(pauta.crudo).filter((v) => v !== null && v !== "").map(String).join(" · ")}</p>
        {columnas.map((c) => (
          <label key={c} className="campo">
            <span style={{ display: "flex", gap: 8 }}>{c}<span style={{ flexGrow: 1 }} />
              {programa && c !== programa && !DEL_CAPITULO.test(c) && nombrePrograma && (
                <button type="button" className="enlace-chico" onClick={() => aTodoElPrograma(c)}>aplicar a todo {nombrePrograma}</button>
              )}
            </span>
            {valores[c].length > 60
              ? <textarea className="entrada" rows={4} value={valores[c]} onChange={(e) => setValores({ ...valores, [c]: e.target.value })} />
              : <input className="entrada" value={valores[c]} onChange={(e) => setValores({ ...valores, [c]: e.target.value })} />}
          </label>
        ))}
        <div className="botones">
          <button type="button" className="boton principal chico" onClick={guardar} disabled={cambiadas.length === 0}>Guardar</button>
          <button type="button" className="boton chico" onClick={olvidar}>Olvidar esta pauta</button>
        </div>
        {aviso && (
          <p className="nota chico" role="status" style={{ margin: 0 }}>✓ {aviso}{anterior && <> · <button type="button" className="enlace-chico" onClick={deshacer}>deshacer</button></>}</p>
        )}
        {error && <p className="error chico" role="alert">{error}</p>}
      </div>
    </aside>
  );
}
