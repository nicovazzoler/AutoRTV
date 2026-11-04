import { useEffect, useState } from "react";
import { api, textoDeError } from "../api";
import { haceCuanto } from "../fechas";

interface Caso {
  nombre: string;
  bloqueado: boolean;
  motivo: string;
}

interface EstadoCaja {
  ok: boolean;
  anda: boolean;
  probando: boolean;
  motivo: string;
  casos: Caso[];
  fecha?: string;
  segundos?: number;
  usuario?: number | null;
  limites?: { segundos: number; memoria_mb: number; del_sistema?: boolean };
}

/** La autoprueba de la caja en este servidor: si el código que escribe el agente puede correr, y la prueba. */
export function CajaCodigo() {
  const [estado, setEstado] = useState<EstadoCaja | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<EstadoCaja>("/admin/caja").then(setEstado).catch((e) => setError(textoDeError(e)));
  }, []);

  // Mientras prueba (tarda un minuto), se pregunta cada 3 s.
  useEffect(() => {
    if (!estado?.probando) return;
    const reloj = setTimeout(() => api.get<EstadoCaja>("/admin/caja").then(setEstado).catch((e) => setError(textoDeError(e))), 3000);
    return () => clearTimeout(reloj);
  }, [estado]);

  async function probar() {
    setError("");
    try {
      setEstado(await api.post<EstadoCaja>("/admin/caja/probar"));
    } catch (e) {
      setError(textoDeError(e));
    }
  }

  const limites = estado?.limites ?? { segundos: 20, memoria_mb: 768 };
  return (
    <section aria-label="Caja de código" className="seccion" style={{ gap: 16 }}>
      <div className="seccion-cabeza">
        <h2>Caja de código</h2>
        <button type="button" className="boton chico" onClick={probar} disabled={!estado || estado.probando}>
          {estado?.probando ? "Probando…" : "Probar de nuevo"}
        </button>
      </div>
      <p className="chico tenue" style={{ margin: 0 }}>
        El código que el agente escribe para una señal corre acá: sin variables de entorno, sin red, sin los archivos
        del servidor, sin lanzar programas, con {limites.segundos} s y {limites.memoria_mb} MB como máximo. Al arrancar,
        el servidor prueba código que intenta salir: si alguno lo logra, el código de las señales queda apagado.
      </p>
      {error && <p className="error" role="alert">{error}</p>}
      {estado && (
        <p role="status" className={estado.ok ? "c-nueva" : "c-revisar"} style={{ margin: 0 }}>
          {estado.ok ? "✔" : "✗"} {estado.probando ? "Probando en este servidor…" : estado.motivo}
          {!estado.probando && estado.fecha && (
            <span className="chico tenue"> · {haceCuanto(estado.fecha)} en este servidor
              {estado.usuario === 65534 ? ", con un usuario sin permisos" : ""}
              {estado.limites?.del_sistema ? " y con los topes puestos por el sistema operativo" : ""}</span>
          )}
        </p>
      )}
      {estado && estado.casos.length > 0 && (
        <div className="desplazable">
          <table className="tabla-datos">
            <thead><tr><th>Intento</th><th>Resultado</th><th>Qué le contestó la caja</th></tr></thead>
            <tbody>
              {estado.casos.map((c) => (
                <tr key={c.nombre}>
                  <td>{c.nombre}</td>
                  <td className={c.bloqueado ? "c-nueva" : "c-revisar"}>{c.bloqueado ? "Bloqueado" : "Se escapó"}</td>
                  <td className="chico">{c.motivo}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
