import { useEffect, useState } from "react";
import { api, textoDeError } from "../api";
import { confirmar } from "./Dialogos";

interface Datos {
  fijas: string[];
  origen: { columna: string; ejemplo: string }[];
  mapa: Record<string, string>;
  activo: boolean;
}

interface Resultado {
  pautas: { antes: number | null; despues: number | null };
  reglas_con_error: string[];
  aviso: string;
}

const OBLIGATORIAS = ["Fecha", "Hora", "Título"];

/** De qué columna de la página sale cada columna fija del EPG crudo. Solo para señales web, solo admin. */
export function EpgCrudo({ senalId, alGuardar }: { senalId: string; alGuardar: () => void }) {
  const [datos, setDatos] = useState<Datos | null>(null);
  const [mapa, setMapa] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [resultado, setResultado] = useState<Resultado | null>(null);
  const [guardando, setGuardando] = useState(false);

  useEffect(() => {
    api.get<Datos>(`/senales/${senalId}/epg-crudo`).then((d) => { setDatos(d); setMapa(d.mapa); })
      .catch((e) => setError(textoDeError(e)));
  }, [senalId]);

  if (error && !datos) return <p className="chico tenue">{error}</p>;
  if (!datos) return <p className="chico tenue">Leyendo las columnas de la página…</p>;

  const ejemplo = (c: string) => datos.origen.find((o) => o.columna === c)?.ejemplo ?? "";
  const faltan = OBLIGATORIAS.filter((f) => !mapa[f]);

  const guardar = async () => {
    if (!datos.activo && !await confirmar({ titulo: "Pasar a EPG crudo",
      texto: "La base de esta señal se recalcula con el EPG crudo y las reglas pasan a ver estas columnas fijas. Las reglas que nombraban columnas de la página van a dar error hasta que el agente las ajuste.",
      boton: "Pasar a EPG crudo" })) return;
    setGuardando(true);
    setError("");
    try {
      setResultado(await api.post<Resultado>(`/senales/${senalId}/epg-crudo`, { mapa }));
      alGuardar();
    } catch (e) {
      setError(textoDeError(e));
    }
    setGuardando(false);
  };

  return (
    <details className="caja" open={!datos.activo}>
      <summary>EPG crudo {datos.activo ? "· activo" : "· sin activar"}</summary>
      <p className="chico tenue" style={{ lineHeight: 1.5 }}>
        La página se pasa primero a estas columnas fijas; el hash y las reglas trabajan sobre ellas. Así, si la página cambia su HTML
        pero dice lo mismo, la base sigue sirviendo. Lo que no tiene columna fija va a Extras, que no cuenta para el hash.
      </p>
      <table className="tabla-datos" style={{ marginTop: 8 }}>
        <thead><tr><th>Columna fija</th><th>Sale de</th><th>Ejemplo</th></tr></thead>
        <tbody>
          {datos.fijas.map((f) => (
            <tr key={f}>
              <td>{f}{OBLIGATORIAS.includes(f) ? " *" : ""}</td>
              <td>
                <select className="entrada" aria-label={`${f} sale de`} value={mapa[f] ?? ""} onChange={(e) => setMapa({ ...mapa, [f]: e.target.value })}
                  style={{ minHeight: 32 }}>
                  <option value="">(ninguna)</option>
                  {datos.origen.map((o) => <option key={o.columna} value={o.columna}>{o.columna}</option>)}
                </select>
              </td>
              <td className="tenue chico"><span className="dos-renglones">{mapa[f] ? ejemplo(mapa[f]) : ""}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="botones" style={{ alignItems: "center", marginTop: 12 }}>
        <button type="button" className="boton principal chico" onClick={guardar} disabled={guardando || faltan.length > 0}>
          {guardando ? "Guardando…" : datos.activo ? "Guardar" : "Pasar a EPG crudo"}
        </button>
        {faltan.length > 0 && <span className="chico c-revisar">Falta de dónde sale {faltan.join(", ")}.</span>}
      </div>
      {error && <p className="error chico" role="alert">{error}</p>}
      {resultado && (
        <div className="nota chico" role="status" style={{ marginTop: 10 }}>
          {resultado.pautas.antes !== null && <p style={{ margin: 0 }}>Base recalculada: {resultado.pautas.despues} pautas (había {resultado.pautas.antes}).</p>}
          {resultado.aviso && <p style={{ margin: 0 }}>{resultado.aviso}</p>}
          {resultado.reglas_con_error.length > 0 && (
            <>
              <p style={{ margin: "6px 0 0" }}>Estas reglas hay que ajustarlas (pedíselo al agente):</p>
              <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{resultado.reglas_con_error.map((r) => <li key={r}>{r}</li>)}</ul>
            </>
          )}
        </div>
      )}
    </details>
  );
}
