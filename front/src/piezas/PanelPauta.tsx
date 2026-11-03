import { useState } from "react";
import { api, textoDeError } from "../api";
import type { Celdas, PautaBase } from "../tipos";
import { Recorrido, type Parecida } from "./Recorrido";
import { confirmar } from "./Dialogos";

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

/**
 * Una pauta de la base para editar entera (todas sus columnas), con "Guardado · deshacer". Al guardar busca otras
 * pautas donde vale el mismo arreglo y abre el recorrido.
 */
export function PanelPauta({ senalId, pauta, columnas: delCatalogo, programa, alCambiar, alCerrar }: Props) {
  const columnas = [...new Set([...delCatalogo, ...Object.keys(pauta.salida)])];
  const [parecidas, setParecidas] = useState<Parecida[] | null>(null);
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
      const encontradas = (await Promise.all(cambiadas.map((c) => api.post<Parecida[]>(
        `/senales/${senalId}/pautas/${pauta.hash}/parecidas`, { columna: c, antes: pauta.salida[c] ?? null, despues: valores[c] || null })))).flat();
      if (encontradas.length) setParecidas(encontradas);
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

  const arreglarParecidas = async (elegidas: Parecida[]) => {
    await api.post(`/senales/${senalId}/pautas/aplicar`, elegidas.map((x) => ({ hash: x.clave, columna: x.columna, valor: x.despues })));
    setAviso(`Guardado en la base, y en ${elegidas.length} ${elegidas.length === 1 ? "pauta parecida" : "pautas parecidas"}`);
    await alCambiar();
  };

  const olvidar = async () => {
    if (!await confirmar({ texto: "La próxima vez que venga la arman las reglas y pide revisión.", boton: "Olvidar la pauta",
      peligro: true })) return;
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
            <h2 className="serif" style={{ margin: "2px 0 0", fontSize: 24, fontWeight: 500 }}>{nombrePrograma || "Pauta"}</h2>
          </div>
          <button type="button" className="boton-redondo" aria-label="Cerrar" onClick={alCerrar}>✕</button>
        </div>
        <p className="nota chico" style={{ margin: 0 }}>Cómo vino: {Object.values(pauta.crudo).filter((v) => v !== null && v !== "").map(String).join(" · ")}</p>
        {columnas.map((c) => (
          <label key={c} className="campo">
            <span style={{ display: "flex", gap: 8 }}>{c}<span style={{ flexGrow: 1 }} />
              {programa && c !== programa && !DEL_CAPITULO.test(c) && nombrePrograma && (
                <button type="button" className="enlace-chico" title={`En todas las pautas de ${nombrePrograma}`}
                  onClick={() => aTodoElPrograma(c)}>Aplicar a todas las pautas idénticas</button>
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
          <p className="nota chico" role="status" style={{ margin: 0 }}>✓ {aviso}{anterior && <> · <button type="button" className="enlace-chico" onClick={deshacer}>Deshacer</button></>}</p>
        )}
        {error && <p className="error chico" role="alert">{error}</p>}
      </div>
      {parecidas && <Recorrido candidatas={parecidas} alAplicar={arreglarParecidas} alCerrar={() => setParecidas(null)} />}
    </aside>
  );
}
