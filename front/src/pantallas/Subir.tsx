import { useState } from "react";
import { api, textoDeError } from "../api";
import { haceCuanto, rangoSemana } from "../fechas";
import { CopiarPagina } from "../piezas/CopiarPagina";
import { ZonaArchivo } from "../piezas/ZonaArchivo";
import { aSenal, navegar } from "../ruta";
import { recordarSemana } from "../semanaReciente";
import { useSesion } from "../sesion";
import type { SemanaAbierta } from "../tipos";

type Forma = "archivo" | "texto" | "web";

const FORMAS: { id: Forma; nombre: string }[] = [
  { id: "archivo", nombre: "Archivo" },
  { id: "texto", nombre: "Pegar texto" },
  { id: "web", nombre: "Web" },
];

export function Subir({ senalId }: { senalId: string }) {
  const { senales, actualizarSemana } = useSesion();
  const senal = senales?.find((s) => s.id === senalId);
  const abierta = senal?.semana ?? null;
  const [forma, setForma] = useState<Forma>("archivo");
  const [archivo, setArchivo] = useState<File | null>(null);
  const [texto, setTexto] = useState("");
  const [html, setHtml] = useState("");
  const [fecha, setFecha] = useState("");
  const [leyendo, setLeyendo] = useState(false);
  const [error, setError] = useState("");

  const listo = forma === "archivo" ? !!archivo : forma === "texto" ? !!texto.trim() : !!html.trim();

  const leer = async () => {
    setLeyendo(true);
    setError("");
    try {
      let datos: SemanaAbierta;
      if (forma === "archivo" && archivo) {
        const f = new FormData();
        f.append("archivo", archivo);
        datos = await api.subir<SemanaAbierta>(`/senales/${senalId}/abierta`, f);
      } else {
        datos = await api.post<SemanaAbierta>(`/senales/${senalId}/abierta/texto`,
          { texto: forma === "texto" ? texto : html, fecha_inicio: forma === "texto" ? fecha || null : null });
      }
      actualizarSemana(senalId, datos.semana);
      recordarSemana(senalId, datos);
      navegar(aSenal(senalId, "revisar"));
    } catch (e) {
      setError(textoDeError(e));
      setLeyendo(false);
    }
  };

  return (
    <main className="contenido" style={{ maxWidth: 900 }}>
      <header className="cabecera-textos">
        <span className="antetitulo">{senal?.nombre ?? senalId}</span>
        <h1 className="titulo">Subir la grilla de la semana</h1>
        <p className="bajada">Como venga: archivo, texto copiado o la página de la señal. Después te muestro qué salió de la base y qué hay que mirar.</p>
      </header>

      {abierta && (
        <p className="nota" role="status">
          Ya está abierta la semana <b>{rangoSemana(abierta.resumen?.desde ?? null, abierta.resumen?.hasta ?? null).toLowerCase()}</b>
          {abierta.version > 1 ? ` (v${abierta.version})` : ""}, subida por {abierta.subida_por} {haceCuanto(abierta.subida)}
          {abierta.confirmada_por ? ` y confirmada por ${abierta.confirmada_por}` : " y todavía sin confirmar"}.
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
          <ZonaArchivo archivo={archivo} alElegir={setArchivo} ayuda="Excel, PDF, XML, HTML guardado o .txt · tocá acá para elegirlo" />
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
          <label className="campo">Pegá acá el HTML de la página, directo, sin pasar por el bloc de notas
            <textarea className="entrada" rows={6} value={html} onChange={(e) => setHtml(e.target.value)} placeholder={'<div class="grilla">…'} />
          </label>
          <CopiarPagina titulo="¿Cómo copio el HTML de la página?" />
        </div>
      )}

      {error && <p className="error" role="alert">{error}</p>}

      <div className="botones" style={{ alignItems: "center", paddingTop: 16, borderTop: "1px solid var(--borde)" }}>
        <button type="button" className="boton principal" disabled={!listo || leyendo} onClick={leer} style={{ minHeight: 48, fontSize: 15 }}>
          {leyendo ? "Leyendo la grilla…" : "Leer la grilla"}
        </button>
      </div>
    </main>
  );
}
