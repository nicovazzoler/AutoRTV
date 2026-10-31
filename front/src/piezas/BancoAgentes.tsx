import { useEffect, useState } from "react";
import { api, textoDeError } from "../api";
import { haceCuanto } from "../fechas";

interface SenalBanco {
  id: string;
  nombre: string;
  ejemplos: number;
  ultimo: string;
}

interface Lectura {
  modelo: string;
  logrado: boolean;
  medida: { con_horario: number; empareja: number | null } | null;
  costo: number;
  segundos: number;
}

interface Reglas {
  modelo: string;
  antes: number;
  despues: number;
  vueltas: number;
  tarjetas: number;
  peores: [string, number][];
  costo: number;
  segundos: number;
}

interface Trio<T> {
  haiku: T;
  sonnet: T;
  escalera: T | null;
}

interface ResultadoSenal {
  nombre: string;
  error?: string;
  lectura?: Trio<Lectura>;
  reglas?: Trio<Reglas> | { error: string };
}

interface Cuenta {
  senales: number;
  haiku: number;
  sonnet: number;
  escalera: number;
}

interface Corrida {
  id: number;
  usuario: string;
  inicio: string;
  fin: string | null;
  estado: "corriendo" | "terminada" | "cortada" | "error";
  parametros: { senales: string[]; tope: number; pasos: string[] };
  progreso: string | null;
  gastado: number;
  resultado: { senales: ResultadoSenal[]; resumen: { lectura: Cuenta; reglas: Cuenta } } | null;
}

const POR_DEFECTO = 8;
const CADA_MS = 5000;

function usd(n: number): string {
  return `US$ ${n.toLocaleString("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 3 })}`;
}

function celdaLectura(x: Lectura | null | undefined) {
  if (!x) return <span className="tenue">—</span>;
  const emp = x.medida?.empareja;
  return <span className={x.logrado ? undefined : "c-revisar"}>{x.logrado ? "✔" : "✗"} {emp === null || emp === undefined ? "" : `${Math.round(emp * 100)} %`}
    <span className="chico tenue"> · {usd(x.costo)} · {x.segundos} s</span></span>;
}

function celdaReglas(x: Reglas | null | undefined) {
  if (!x) return <span className="tenue">—</span>;
  return (
    <span>
      <b className={x.despues >= 90 ? "c-nueva" : x.despues >= 70 ? undefined : "c-revisar"}>{Math.round(x.antes)} → {Math.round(x.despues)} %</b>
      <span className="chico tenue"> · {x.vueltas} {x.vueltas === 1 ? "vuelta" : "vueltas"} · {usd(x.costo)}</span>
      <br /><span className="chico tenue">{x.peores.some(([, p]) => p < 100)
        ? `falla en: ${x.peores.filter(([, p]) => p < 100).map(([c, p]) => `${c} ${Math.round(p)} %`).join(", ")}`
        : "todas las columnas al 100 %"}</span>
    </span>
  );
}

function frase(nombre: string, c: Cuenta): string {
  if (!c.senales) return "";
  return `${nombre}: Haiku alcanzó en ${c.haiku} de ${c.senales}, Sonnet en ${c.sonnet}${c.escalera ? ` y la escalera recuperó ${c.escalera}` : ""}.`;
}

/** Prueba los agentes contra los ejemplos guardados: qué logra Haiku, qué logra Sonnet y qué recupera la escalera. */
export function BancoAgentes() {
  const [senales, setSenales] = useState<SenalBanco[] | null>(null);
  const [elegidas, setElegidas] = useState<Set<string>>(new Set());
  const [tope, setTope] = useState("5");
  const [pasos, setPasos] = useState<Set<string>>(new Set(["lectura", "reglas"]));
  const [corridas, setCorridas] = useState<Corrida[]>([]);
  const [abierta, setAbierta] = useState<Corrida | null>(null);
  const [error, setError] = useState("");

  const cargarCorridas = async () => {
    const lista = await api.get<Corrida[]>("/admin/banco");
    setCorridas(lista);
    return lista;
  };

  const abrir = async (id: number) => setAbierta(await api.get<Corrida>(`/admin/banco/${id}`));

  useEffect(() => {
    api.get<SenalBanco[]>("/admin/banco/senales").then((s) => {
      setSenales(s);
      setElegidas(new Set(s.slice(0, POR_DEFECTO).map((x) => x.id)));
    }).catch((e) => setError(textoDeError(e)));
    cargarCorridas().then((l) => l[0] && abrir(l[0].id)).catch((e) => setError(textoDeError(e)));
  }, []);

  // Mientras corre, se refresca sola para ver el progreso.
  useEffect(() => {
    if (abierta?.estado !== "corriendo") return;
    const t = setTimeout(() => { abrir(abierta.id).then(cargarCorridas).catch(() => {}); }, CADA_MS);
    return () => clearTimeout(t);
  }, [abierta]);

  const alternar = (conjunto: Set<string>, valor: string, poner: (s: Set<string>) => void) => {
    const nuevo = new Set(conjunto);
    if (nuevo.has(valor)) nuevo.delete(valor);
    else nuevo.add(valor);
    poner(nuevo);
  };

  const correr = async () => {
    setError("");
    try {
      const { id } = await api.post<{ id: number }>("/admin/banco", { senales: [...elegidas], tope: Number(tope), pasos: [...pasos] });
      await cargarCorridas();
      await abrir(id);
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  const corriendo = corridas.some((c) => c.estado === "corriendo");
  const resumen = abierta?.resultado?.resumen;

  return (
    <section aria-label="Banco de agentes" className="seccion" style={{ gap: 16 }}>
      <div className="seccion-cabeza">
        <h2>Banco de agentes</h2>
        <span className="chico tenue">prueba Haiku y Sonnet contra el ejemplo más reciente de cada señal · gasta API de verdad</span>
      </div>
      {error && <p className="error" role="alert">{error}</p>}

      <div className="dos-columnas" style={{ alignItems: "flex-start" }}>
        <div>
          <span className="chico tenue">Señales con ejemplos ({senales?.length ?? "…"}) · {elegidas.size} elegidas</span>
          <ul className="lista-simple" style={{ maxHeight: 260, overflowY: "auto", marginTop: 6 }}>
            {senales?.length === 0 && <li className="chico tenue">Ninguna señal tiene ejemplos todavía.</li>}
            {senales?.map((s) => (
              <li key={s.id}>
                <label style={{ display: "flex", gap: 8, alignItems: "center", flex: "1 1 auto" }}>
                  <input type="checkbox" checked={elegidas.has(s.id)} onChange={() => alternar(elegidas, s.id, setElegidas)}
                    style={{ width: 18, height: 18, accentColor: "var(--acento)" }} />
                  <span className="serif" style={{ fontSize: 16 }}>{s.nombre}</span>
                </label>
                <span className="chico tenue">{s.ejemplos} {s.ejemplos === 1 ? "ejemplo" : "ejemplos"}</span>
              </li>
            ))}
          </ul>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <label className="campo" style={{ maxWidth: 200 }}>Tope de gasto (US$)
            <input className="entrada" type="number" min={0.5} max={50} step={0.5} value={tope} onChange={(e) => setTope(e.target.value)} />
          </label>
          <div className="botones" style={{ gap: 14 }}>
            {[["lectura", "Leer la grilla"], ["reglas", "Armar las reglas"]].map(([id, nombre]) => (
              <label key={id} style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <input type="checkbox" checked={pasos.has(id)} onChange={() => alternar(pasos, id, setPasos)}
                  style={{ width: 18, height: 18, accentColor: "var(--acento)" }} />{nombre}
              </label>
            ))}
          </div>
          <button type="button" className="boton principal" disabled={corriendo || !elegidas.size || !pasos.size} onClick={correr}
            style={{ alignSelf: "flex-start" }}>
            {corriendo ? "Hay una corrida en marcha…" : "Correr banco"}
          </button>
          <span className="chico tenue">Por señal: Haiku, Sonnet y, si Haiku no alcanza, Sonnet arrancando de lo de Haiku. Cada pedido queda en Uso del agente.</span>
        </div>
      </div>

      {abierta && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div className="seccion-cabeza">
            <h3 className="serif" style={{ margin: 0, fontSize: 20 }}>Corrida {abierta.id}</h3>
            <span className="chico tenue">{abierta.usuario} · {haceCuanto(abierta.inicio)} · {abierta.estado} · {usd(abierta.gastado)} de {usd(abierta.parametros.tope)}</span>
          </div>
          {abierta.estado === "corriendo" && (
            <p className="tenue" role="status" style={{ margin: 0, display: "flex", alignItems: "center", gap: 8 }}>
              <span className="punto-vivo" aria-hidden="true" />{abierta.progreso}
            </p>
          )}
          {abierta.estado !== "corriendo" && abierta.progreso !== "Listo" && <p className="nota" style={{ margin: 0 }}>{abierta.progreso}</p>}
          {resumen && (resumen.lectura.senales > 0 || resumen.reglas.senales > 0) && (
            <p style={{ margin: 0 }}>{frase("Lectura", resumen.lectura)} {frase("Reglas", resumen.reglas)}</p>
          )}
          {!!abierta.resultado?.senales.length && (
            <div className="desplazable">
              <table className="tabla-datos">
                <thead><tr><th>Señal</th><th>Paso</th><th>Haiku</th><th>Sonnet</th><th>Escalera</th></tr></thead>
                <tbody>
                  {abierta.resultado.senales.flatMap((r) => {
                    if (r.error) return [<tr key={r.nombre}><td>{r.nombre}</td><td colSpan={4} className="c-revisar">{r.error}</td></tr>];
                    const filas = [];
                    if (r.lectura) filas.push(
                      <tr key={`${r.nombre}-l`}><td>{r.nombre}</td><td className="tenue">lectura</td>
                        <td>{celdaLectura(r.lectura.haiku)}</td><td>{celdaLectura(r.lectura.sonnet)}</td><td>{celdaLectura(r.lectura.escalera)}</td></tr>);
                    if (r.reglas && "error" in r.reglas) filas.push(
                      <tr key={`${r.nombre}-r`}><td>{r.nombre}</td><td className="tenue">reglas</td><td colSpan={3} className="c-revisar">{r.reglas.error}</td></tr>);
                    else if (r.reglas) filas.push(
                      <tr key={`${r.nombre}-r`}><td>{r.nombre}</td><td className="tenue">reglas</td>
                        <td>{celdaReglas(r.reglas.haiku)}</td><td>{celdaReglas(r.reglas.sonnet)}</td><td>{celdaReglas(r.reglas.escalera)}</td></tr>);
                    return filas;
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {corridas.length > 1 && (
        <div>
          <span className="chico tenue">Corridas anteriores</span>
          <ul className="lista-simple" style={{ marginTop: 6 }}>
            {corridas.map((c) => (
              <li key={c.id}>
                <button type="button" className="enlace-chico" onClick={() => abrir(c.id)}>Corrida {c.id}</button>
                <span className="chico tenue" style={{ flex: "1 1 auto" }}>{haceCuanto(c.inicio)} · {c.parametros.senales.length} señales · {c.estado}</span>
                <span className="chico tenue">{usd(c.gastado)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
