import { useEffect, useState } from "react";
import { api, textoDeError } from "../api";
import { haceCuanto, rangoSemana } from "../fechas";
import { CopiarPagina } from "../piezas/CopiarPagina";
import { ZonaArchivo } from "../piezas/ZonaArchivo";
import { recordarSemana } from "../semanaReciente";
import { useSesion } from "../sesion";
import type { Receta, SemanaAbierta } from "../tipos";
import { persona } from "../nombre";

type Forma = "archivo" | "texto" | "web";

const FORMAS: { id: Forma; nombre: string }[] = [
  { id: "archivo", nombre: "Archivo" },
  { id: "texto", nombre: "Pegar texto" },
  { id: "web", nombre: "Web" },
];

/** Subir la grilla de la semana: archivo, texto pegado o HTML de la página. Va adentro de la Semana. */
export function Subir({ senalId, alLeer, alCancelar }: { senalId: string; alLeer: (d: SemanaAbierta) => void; alCancelar?: () => void }) {
  const { senales, actualizarSemana } = useSesion();
  const senal = senales?.find((s) => s.id === senalId);
  const abierta = senal?.semana ?? null;
  const [forma, setForma] = useState<Forma>("archivo");
  const [archivos, setArchivos] = useState<File[]>([]);
  const [texto, setTexto] = useState("");
  const [html, setHtml] = useState("");
  const [url, setUrl] = useState("");
  // Si la señal se baja de un link, la pestaña Web arranca con ese link.
  useEffect(() => {
    api.get<Receta>(`/senales/${senalId}`).then((r) => {
      const link = (r.entrada as { url?: string | null }).url;
      if (link) {
        setUrl(link);
        setForma("web");
      }
    }).catch(() => {});
  }, [senalId]);
  const [fecha, setFecha] = useState("");
  const [leyendo, setLeyendo] = useState(false);
  const [error, setError] = useState("");

  const listo = forma === "archivo" ? archivos.length > 0 : forma === "texto" ? !!texto.trim() : !!(html.trim() || url.trim());

  const leer = async () => {
    setLeyendo(true);
    setError("");
    try {
      let datos: SemanaAbierta;
      if (forma === "archivo" && archivos.length) {
        const f = new FormData();
        // Varios archivos van juntos y el servidor los lee como una sola semana.
        if (archivos.length === 1) f.append("archivo", archivos[0]);
        else archivos.forEach((a) => f.append("archivos", a));
        datos = await api.subir<SemanaAbierta>(`/senales/${senalId}/abierta`, f);
      } else if (forma === "web" && !html.trim()) {
        datos = await api.post<SemanaAbierta>(`/senales/${senalId}/abierta/url`, { url });
      } else {
        datos = await api.post<SemanaAbierta>(`/senales/${senalId}/abierta/texto`,
          { texto: forma === "texto" ? texto : html, fecha_inicio: forma === "texto" ? fecha || null : null });
      }
      actualizarSemana(senalId, datos.semana);
      recordarSemana(senalId, datos);
      alLeer(datos);
    } catch (e) {
      setError(textoDeError(e));
      setLeyendo(false);
    }
  };

  return (
    <section aria-label="Subir la grilla" style={{ display: "flex", flexDirection: "column", gap: 24, maxWidth: 900 }}>
      <header className="cabecera-textos">
        <span className="antetitulo">{senal?.nombre ?? senalId}</span>
        <h1 className="titulo">Soltá la grilla de la semana</h1>
        <p className="bajada">Como venga: archivo, texto copiado o la página de la señal. Después te muestro qué salió de la base y qué hay que mirar.</p>
      </header>

      {abierta && (
        <p className="nota" role="status">
          Ya está abierta la semana <b>{rangoSemana(abierta.resumen?.desde ?? null, abierta.resumen?.hasta ?? null).toLowerCase()}</b>
          {abierta.version > 1 ? ` (v${abierta.version})` : ""}, subida por {persona(abierta.subida_por)} {haceCuanto(abierta.subida)}
          {abierta.confirmada_por ? ` y confirmada por ${persona(abierta.confirmada_por)}` : " y todavía sin confirmar"}.
          Si la grilla nueva es de esas mismas fechas, queda como versión corregida y te muestro qué cambió; si es de otra semana, la reemplaza.
          Lo corregido en la base se conserva siempre.
        </p>
      )}

      <div role="tablist" aria-label="Cómo llega la grilla" className="botones" style={{ paddingBottom: 16, borderBottom: "2px solid var(--texto)" }}>
        {FORMAS.map((f) => (
          <button key={f.id} type="button" role="tab" className="boton" aria-selected={forma === f.id} onClick={() => setForma(f.id)}
            style={{ fontWeight: 600 }}>{f.nombre}</button>
        ))}
      </div>

      {forma === "archivo" && (
        <div role="tabpanel" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <ZonaArchivo archivo={null} alElegir={() => {}} varios={archivos} alElegirVarios={setArchivos}
            ayuda="Excel, PDF, Word, XML, HTML guardado, .txt o un .zip · si la semana viene en varios archivos, soltalos todos juntos" />
        </div>
      )}

      {forma === "texto" && (
        <div role="tabpanel" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <label className="campo">Pegá la grilla como la copiaste
            <textarea className="entrada" rows={10} value={texto} onChange={(e) => setTexto(e.target.value)}
              placeholder={"LUNES 9\n06:00 Agenda Musical\n07:00 Noches de Jazz - Trío Sur"} />
          </label>
          <label className="campo" style={{ maxWidth: 260 }}>La semana empieza el (si el texto no trae fechas)
            <input className="entrada" type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} />
          </label>
        </div>
      )}

      {forma === "web" && (
        <div role="tabpanel" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <label className="campo">El link de la página de la señal
            <input className="entrada" type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…/programacion" />
          </label>
          <span className="chico tenue">Si la página arma la grilla después de cargar (o pide iniciar sesión), el link puede no alcanzar: en ese caso pegá el HTML acá abajo.</span>
          <label className="campo">O pegá el HTML de la página, directo, sin pasar por el bloc de notas
            <textarea className="entrada" rows={6} value={html} onChange={(e) => setHtml(e.target.value)} placeholder={'<div class="grilla">…'} />
          </label>
          <CopiarPagina titulo="¿Cómo copio el HTML de la página?" />
        </div>
      )}

      {error && <p className="error" role="alert">{error}</p>}

      <div className="botones" style={{ alignItems: "center", paddingTop: 16, borderTop: "1px solid var(--borde)" }}>
        <button type="button" className="boton principal" disabled={!listo || leyendo} onClick={leer} style={{ minHeight: 48, fontSize: 15 }}>
          {leyendo ? "Leyendo la grilla… (si hace falta, el agente busca la fecha y la hora)" : "Leer la grilla"}
        </button>
        {alCancelar && <button type="button" className="boton" onClick={alCancelar} style={{ minHeight: 48 }}>Cancelar</button>}
      </div>
    </section>
  );
}
