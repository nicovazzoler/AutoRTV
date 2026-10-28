import { useEffect, useState } from "react";
import { api, ErrorApi, textoDeError } from "../api";
import { frase, fraseCambio, fraseEntrada, fraseIdiomas } from "../frases";
import { haceCuanto } from "../fechas";
import { ConfigSenal, RecetaArchivo } from "../piezas/ConfigSenal";
import { ZonaArchivo } from "../piezas/ZonaArchivo";
import { useSesion } from "../sesion";
import type { Evaluacion, Propuesta, Receta, Version } from "../tipos";

interface Informe {
  id: string;
  celdas_cambiadas: number;
  error: string | null;
}

// "ejemplo-20261027-153000" es como los guarda el servidor; a la persona le sirve la fecha.
function nombreEjemplo(nombre: string): string {
  const m = nombre.match(/^ejemplo-(\d{4})(\d{2})(\d{2})/);
  if (!m) return nombre;
  const meses = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  return `Subido el ${Number(m[3])} ${meses[Number(m[2]) - 1]} ${m[1]}`;
}

export function Senal({ senalId }: { senalId: string }) {
  const { yo, senales, tocar } = useSesion();
  const tablaId = senales?.find((s) => s.id === senalId)?.semana?.tabla_id ?? null;
  const [receta, setReceta] = useState<Receta | null>(null);
  const [version, setVersion] = useState("");
  const [evaluaciones, setEvaluaciones] = useState<Evaluacion[] | null>(null);
  const [historial, setHistorial] = useState<Version[]>([]);
  const [informes, setInformes] = useState<Record<string, Informe>>({});
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [subiendo, setSubiendo] = useState(false);
  const [editando, setEditando] = useState(false);
  const [forma, setForma] = useState<"archivo" | "pegar">("archivo");
  const [entrada, setEntrada] = useState<File | null>(null);
  const [pegada, setPegada] = useState("");
  const [esperado, setEsperado] = useState<File | null>(null);
  const [armando, setArmando] = useState(false);

  const cargar = async () => {
    const { datos, version: v } = await api.conVersion<Receta>(`/senales/${senalId}`);
    setReceta(datos);
    setVersion(v);
    setHistorial(await api.get<Version[]>(`/senales/${senalId}/historial`));
    setEvaluaciones(await api.post<Evaluacion[]>(`/senales/${senalId}/ejemplos/evaluar`, datos));
    if (tablaId) {
      const vista = await api.post<{ tarjetas: Informe[] }>("/preview", { tabla_id: tablaId, senal: datos, filas: 1 }).catch(() => null);
      if (vista) setInformes(Object.fromEntries(vista.tarjetas.map((i) => [i.id, i])));
    }
  };

  useEffect(() => {
    cargar().catch((e) => setError(textoDeError(e)));
  }, [senalId]);

  const restaurar = async (v: Version, cual: string) => {
    if (!confirm(`¿Volver las reglas a como estaban ${cual}? Queda como un cambio más, así también se puede deshacer.`)) return;
    setError("");
    try {
      await api.conVersion(`/senales/${senalId}/historial/${v.id}/restaurar`, "POST", { "If-Match": version });
      setAviso("Listo: las reglas volvieron a esa versión.");
      tocar();
    } catch (e) {
      setError(e instanceof ErrorApi && e.estado === 409 ? `${e.message}. Recargá la página y probá de nuevo.` : textoDeError(e));
    }
  };

  const borrarEjemplo = async (nombre: string) => {
    if (!confirm(`¿Borrar el ejemplo «${nombreEjemplo(nombre)}»? La base de pautas no cambia.`)) return;
    try {
      await api.borrar(`/senales/${senalId}/ejemplos/${encodeURIComponent(nombre)}`);
      await cargar();
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  const agregarEjemplo = async () => {
    const cruda = forma === "archivo" ? entrada : pegada.trim() ? new File([pegada], pegada.trimStart().startsWith("<") ? "grilla.html" : "grilla.txt") : null;
    if (!cruda || !esperado) return;
    const datos = new FormData();
    const ahora = new Date();
    const dos = (n: number) => String(n).padStart(2, "0");
    datos.set("nombre", `ejemplo-${ahora.getFullYear()}${dos(ahora.getMonth() + 1)}${dos(ahora.getDate())}-${dos(ahora.getHours())}${dos(ahora.getMinutes())}${dos(ahora.getSeconds())}`);
    datos.set("entrada", cruda);
    datos.set("esperado", esperado);
    setSubiendo(true);
    setError("");
    try {
      const r = await api.subir<{ pautas: { agregadas?: number; error?: string } | null }>(`/senales/${senalId}/ejemplos`, datos);
      setAviso(r.pautas?.error ?? `Ejemplo agregado. La base sumó ${r.pautas?.agregadas ?? 0} pautas.`);
      setEntrada(null);
      setPegada("");
      setEsperado(null);
      await cargar();
    } catch (err) {
      setError(textoDeError(err));
    }
    setSubiendo(false);
  };

  const armarReglas = async () => {
    if (!receta || !evaluaciones?.length) return;
    setArmando(true);
    setError("");
    setAviso("");
    try {
      const p = await api.post<Propuesta>("/asistente", { senal: receta, ejemplo: evaluaciones[0].nombre, fuerte: true,
        pedido: "Ajustá las tarjetas para que la grilla de entrada de este ejemplo quede igual al EPG esperado." });
      const antes = p.antes?.ejemplos[evaluaciones[0].nombre] ?? null;
      const despues = p.despues?.ejemplos[evaluaciones[0].nombre] ?? null;
      if (p.receta && despues !== null && (antes === null || despues > antes)) {
        await api.put(`/senales/${senalId}`, p.receta, { "If-Match": version });
        setAviso(`Reglas armadas: aciertan el ${despues} % del ejemplo.${p.aviso ? ` ${p.aviso}` : ""}`);
        tocar();
      } else {
        setError(`El agente no encontró reglas que mejoren el ejemplo. ${p.problemas.join(" ")}`);
      }
    } catch (e) {
      setError(textoDeError(e));
    }
    setArmando(false);
  };

  const limpiarBase = async () => {
    if (!confirm("¿Sacar de la base las columnas que en realidad son horario (por ejemplo una hora con AM/PM)? Las pautas que solo se diferenciaban por eso se juntan en una.")) return;
    try {
      const r = await api.post<{ antes: number; despues: number; columnas: string[] }>(`/senales/${senalId}/pautas/limpiar`, {});
      setAviso(r.columnas.length
        ? `Base limpia: se sacaron ${r.columnas.join(", ")} y quedaron ${r.despues} pautas (había ${r.antes}).`
        : "La base ya estaba limpia: no había columnas de horario guardadas.");
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  if (!receta) {
    return <main className="contenido">{error ? <p className="error" role="alert">{error}</p> : <p className="tenue">Cargando la señal…</p>}</main>;
  }

  const conPct = (evaluaciones ?? []).filter((x) => typeof x.porcentaje === "number");
  const promedio = conPct.length ? Math.round(conPct.reduce((a, x) => a + (x.porcentaje ?? 0), 0) / conPct.length) : null;
  const anterior = historial[1];

  return (
    <main className="contenido">
      <header className="cabecera-textos">
        <span className="antetitulo">Señal · {fraseEntrada(receta)} · {fraseIdiomas(receta).toLowerCase()}</span>
        <h1 className="titulo">{receta.nombre}</h1>
        <p className="bajada">
          {promedio === null ? "Todavía no tiene ejemplos para medir las reglas." : <>Las reglas aciertan el <b>{promedio} %</b> de las celdas de los ejemplos. Lo que falta lo cubre la base.</>}
        </p>
      </header>

      {error && <p className="error" role="alert">{error}</p>}
      {aviso && <p className="nota" role="status">{aviso}</p>}

      <div className="tres-columnas" style={{ gap: 40 }}>
        <section aria-label="Ejemplos" className="seccion">
          <div className="seccion-cabeza"><h2 style={{ fontSize: 22 }}>Ejemplos</h2></div>
          <p className="chico tenue" style={{ margin: "8px 0" }}>Semanas que ya salieron: cómo vinieron y cómo quedaron.</p>
          <ul className="lista-simple">
            {evaluaciones === null && <li className="tenue chico">Probando las reglas contra los ejemplos…</li>}
            {evaluaciones?.length === 0 && <li className="tenue chico">Sin ejemplos todavía.</li>}
            {evaluaciones?.map((x) => (
              <li key={x.nombre}>
                <span className="serif" style={{ fontSize: 16 }}>{nombreEjemplo(x.nombre)}</span>
                <span style={{ flexGrow: 1 }} />
                <b title={x.error}>{x.error ? "error" : `${x.porcentaje} %`}</b>
                <button type="button" className="boton chico" style={{ minHeight: 32, padding: "0 10px" }} onClick={() => borrarEjemplo(x.nombre)}>Borrar</button>
              </li>
            ))}
          </ul>
          <details className="caja" style={{ marginTop: 14 }}>
            <summary>Agregar semana terminada</summary>
            <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 12 }}>
              <span className="campo">Cómo vino</span>
              <div className="botones" role="group" aria-label="Cómo la traés" style={{ gap: 6 }}>
                <button type="button" className="boton chico" aria-pressed={forma === "archivo"} onClick={() => setForma("archivo")}>Archivo</button>
                <button type="button" className="boton chico" aria-pressed={forma === "pegar"} onClick={() => setForma("pegar")}>Pegar texto o HTML</button>
              </div>
              {forma === "archivo"
                ? <ZonaArchivo chica archivo={entrada} alElegir={setEntrada} etiqueta="Cómo vino" />
                : <textarea className="entrada" rows={4} value={pegada} onChange={(e) => setPegada(e.target.value)} aria-label="Texto o HTML de cómo vino"
                    placeholder="Pegá el texto o el HTML de la página" style={{ minHeight: 90, fontSize: 12 }} />}
              <span className="campo">Cómo quedó (EPG terminado, Excel)</span>
              <ZonaArchivo chica archivo={esperado} alElegir={setEsperado} accept=".xlsx,.xls" etiqueta="Cómo quedó" />
              <button type="button" className="boton principal chico" style={{ alignSelf: "flex-start" }} onClick={agregarEjemplo}
                disabled={subiendo || !esperado || (forma === "archivo" ? !entrada : !pegada.trim())}>{subiendo ? "Subiendo…" : "Agregar"}</button>
            </div>
          </details>
        </section>

        <section aria-label="Reglas" className="seccion" style={{ gridColumn: "span 2" }}>
          <div className="seccion-cabeza">
            <h2 style={{ fontSize: 22 }}>Reglas</h2>
            <span className="chico tenue">las arma el agente · se cambian hablándole</span>
          </div>
          <ol className="lista-simple">
            {receta.tarjetas.length === 0 && (
              <li className="tenue chico" style={{ flexWrap: "wrap" }}>Sin reglas: todo sale de la base o como vino.
                {!!evaluaciones?.length && <button type="button" className="boton chico" onClick={armarReglas} disabled={armando}>
                  {armando ? "Armando… (puede tardar un minuto)" : "Armar reglas desde los ejemplos"}</button>}
              </li>
            )}
            {receta.tarjetas.map((t, i) => {
              const inf = informes[t.id];
              return (
                <li key={t.id} className={`regla${t.activa === false ? " apagada" : ""}`}>
                  <span className="numero">{i + 1}</span>
                  <span style={{ lineHeight: 1.5 }}>{frase(t)}{t.activa === false ? " (apagada)" : ""}</span>
                  <span className={`chico ${inf?.error ? "c-revisar" : "tenue"}`} style={{ whiteSpace: "nowrap" }} title={inf?.error ?? undefined}>
                    {inf?.error ? "con error" : inf ? `${inf.celdas_cambiadas} celdas` : ""}
                  </span>
                </li>
              );
            })}
          </ol>
          {historial.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 14 }}>
              <div className="botones" style={{ alignItems: "center" }}>
                <span className="chico tenue">Último cambio: <b style={{ color: "var(--texto)" }}>{historial[0].usuario} · {haceCuanto(historial[0].fecha)}</b></span>
                <span style={{ flexGrow: 1 }} />
                {anterior && <button type="button" className="boton chico" onClick={() => restaurar(anterior, "antes del último cambio")}>Deshacer el último cambio</button>}
              </div>
              <details className="chico tenue">
                <summary style={{ cursor: "pointer" }}>Historial ({historial.length})</summary>
                <ul className="lista-simple" style={{ marginTop: 8 }}>
                  {historial.slice(0, 15).map((v, i) => (
                    <li key={v.id} style={{ flexWrap: "wrap" }}>
                      <span style={{ color: "var(--texto)" }}>{v.usuario} · {haceCuanto(v.fecha)}</span>
                      <span style={{ flex: "1 1 200px" }}>{v.cambios.length ? v.cambios.map(fraseCambio).join(" · ") : "primera versión"}</span>
                      {i > 0 && <button type="button" className="boton chico" style={{ minHeight: 32 }} onClick={() => restaurar(v, "en esta versión")}>Volver a esta</button>}
                    </li>
                  ))}
                </ul>
              </details>
            </div>
          )}
        </section>
      </div>

      <div className="dos-columnas" style={{ gap: 40 }}>
        <section aria-label="Configuración" className="seccion" style={editando ? { gridColumn: "1 / -1" } : undefined}>
          <div className="seccion-cabeza">
            <h2 style={{ fontSize: 22 }}>Configuración</h2>
            <span style={{ flexGrow: 1 }} />
            {yo.admin && !editando && <button type="button" className="boton chico" onClick={() => setEditando(true)}>Editar</button>}
          </div>
          {editando ? (
            <ConfigSenal receta={receta} version={version} alCancelar={() => setEditando(false)} alGuardar={() => { setEditando(false); tocar(); }} />
          ) : (
          <dl className="datos-config" style={{ marginTop: 12 }}>
            <div><dt>Cómo se lee la grilla</dt><dd>{fraseEntrada(receta)}</dd></div>
            <div><dt>Idiomas</dt><dd>{fraseIdiomas(receta)}</dd></div>
            <div><dt>Celdas con varios programas</dt><dd>{receta.entrada.partir ? `Se parten en «${receta.entrada.partir.separador}»` : "No se parten"}</dd></div>
            <div><dt>Columnas de salida</dt><dd>{receta.salida.columnas.length ? receta.salida.columnas.join(", ") : "Las del catálogo, en su orden"}</dd></div>
          </dl>
          )}
          {yo.admin && !editando && (
            <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 12 }}>
              <RecetaArchivo receta={receta} version={version} alGuardar={tocar} />
              <div className="botones" style={{ alignItems: "center" }}>
                <button type="button" className="boton chico" onClick={limpiarBase}>Limpiar la base</button>
                <span className="chico tenue">Saca columnas de horario que hayan quedado guardadas como contenido.</span>
              </div>
            </div>
          )}
        </section>
        <section aria-label="Fuente web" className="seccion">
          <div className="seccion-cabeza"><h2 style={{ fontSize: 22 }}>Fuente web</h2></div>
          <p className="chico tenue" style={{ marginTop: 12, lineHeight: 1.5 }}>
            Bajar la grilla directo de la página de la señal llega más adelante. Mientras tanto, se pega el HTML desde Subir grilla › Web.
          </p>
        </section>
      </div>
    </main>
  );
}
