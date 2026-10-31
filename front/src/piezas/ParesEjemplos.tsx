import { useState, type DragEvent } from "react";
import { api, textoDeError } from "../api";
import { ZonaArchivo } from "./ZonaArchivo";

interface Par {
  vino: File | null;
  pegado: string;
  quedo: File | null;
}

const VACIO: Par = { vino: null, pegado: "", quedo: null };

// "grilla 27-10.html" y "EPG 27.10.xlsx" van juntos: se empareja por el primer dd-mm del nombre.
function fechaDelNombre(nombre: string): string | null {
  const m = nombre.match(/(\d{1,2})[-_.](\d{1,2})/);
  return m ? `${Number(m[1])}-${Number(m[2])}` : null;
}

// La macro hecha siempre es un Excel; si hay dos Excel con la misma fecha, el que dice EPG o ejemplo es la macro.
function esMacro(f: File, otros: File[]): boolean {
  if (!/\.xlsx?$/i.test(f.name)) return false;
  const mismaFecha = otros.filter((o) => o !== f && fechaDelNombre(o.name) === fechaDelNombre(f.name));
  return mismaFecha.length === 0 || /epg|ejemplo|macro|final/i.test(f.name) || mismaFecha.every((o) => !/\.xlsx?$/i.test(o.name));
}

export function emparejar(archivos: File[]): Par[] {
  const macros = archivos.filter((f) => esMacro(f, archivos));
  const grillas = archivos.filter((f) => !macros.includes(f));
  const usadas = new Set<File>();
  const pares = grillas.map((g) => {
    const quedo = macros.find((m) => !usadas.has(m) && fechaDelNombre(m.name) && fechaDelNombre(m.name) === fechaDelNombre(g.name))
      ?? macros.find((m) => !usadas.has(m) && !fechaDelNombre(m.name)) ?? null;
    if (quedo) usadas.add(quedo);
    return { vino: g, pegado: "", quedo };
  });
  return [...pares, ...macros.filter((m) => !usadas.has(m)).map((m) => ({ vino: null, pegado: "", quedo: m }))];
}

/** Agregar una o varias semanas terminadas: cómo vino (archivo o pegado) y cómo quedó (la macro hecha). */
export function ParesEjemplos({ senalId, alAgregar }: { senalId: string; alAgregar: (mensaje: string) => Promise<void> }) {
  const [pares, setPares] = useState<Par[]>([{ ...VACIO }]);
  const [subiendo, setSubiendo] = useState(false);
  const [error, setError] = useState("");
  const [encima, setEncima] = useState(false);
  const listos = pares.filter((p) => (p.vino || p.pegado.trim()) && p.quedo);

  const cambiar = (i: number, cambio: Partial<Par>) => setPares(pares.map((p, j) => (j === i ? { ...p, ...cambio } : p)));

  const soltarVarios = (e: DragEvent) => {
    e.preventDefault();
    setEncima(false);
    const archivos = [...e.dataTransfer.files];
    if (archivos.length) setPares([...pares.filter((p) => p.vino || p.pegado || p.quedo), ...emparejar(archivos)]);
  };

  const agregar = async () => {
    setSubiendo(true);
    setError("");
    const ahora = new Date();
    const dos = (n: number) => String(n).padStart(2, "0");
    const sello = `ejemplo-${ahora.getFullYear()}${dos(ahora.getMonth() + 1)}${dos(ahora.getDate())}-${dos(ahora.getHours())}${dos(ahora.getMinutes())}${dos(ahora.getSeconds())}`;
    let pautas = 0;
    try {
      for (const [i, p] of listos.entries()) {
        const datos = new FormData();
        datos.set("nombre", listos.length > 1 ? `${sello}-${i + 1}` : sello);
        datos.set("entrada", p.vino ?? new File([p.pegado], p.pegado.trimStart().startsWith("<") ? "grilla.html" : "grilla.txt"));
        datos.set("esperado", p.quedo!);
        const r = await api.subir<{ pautas: { agregadas?: number } | null }>(`/senales/${senalId}/ejemplos`, datos);
        pautas += r.pautas?.agregadas ?? 0;
      }
      setPares([{ ...VACIO }]);
      await alAgregar(`${listos.length === 1 ? "Ejemplo agregado" : `${listos.length} ejemplos agregados`}. La base sumó ${pautas} pautas.`);
    } catch (err) {
      setError(textoDeError(err));
    }
    setSubiendo(false);
  };

  return (
    <div className="caja" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <h3 className="serif" style={{ margin: 0, fontSize: 20, fontWeight: 600 }}>Agregar ejemplos</h3>
      <div className={`zona-archivo chica${encima ? " encima" : ""}`} onDragOver={(e) => { e.preventDefault(); setEncima(true); }}
        onDragLeave={() => setEncima(false)} onDrop={soltarVarios}>
        <span>Soltá acá varios archivos juntos (grillas y macros hechas): <b>los emparejo por la fecha del nombre</b> y abajo corregís si hace falta.</span>
      </div>
      {pares.map((p, i) => (
        <div key={i} className="par-ejemplo">
          <div className="campo">Cómo vino
            {p.vino || !p.pegado ? <ZonaArchivo chica archivo={p.vino} alElegir={(f) => cambiar(i, { vino: f })} etiqueta={`Cómo vino ${i + 1}`} /> : null}
            {!p.vino && (
              <textarea className="entrada" rows={2} value={p.pegado} placeholder="…o pegá el texto o el HTML de la página" aria-label={`Texto de cómo vino ${i + 1}`}
                onChange={(e) => cambiar(i, { pegado: e.target.value })} style={{ fontSize: 12, minHeight: 64 }} />
            )}
          </div>
          <div className="campo">Cómo quedó (macro hecha)
            <ZonaArchivo chica archivo={p.quedo} alElegir={(f) => cambiar(i, { quedo: f })} accept=".xlsx,.xls" etiqueta={`Cómo quedó ${i + 1}`} />
          </div>
          {pares.length > 1 && <button type="button" className="boton-redondo" aria-label={`Quitar el par ${i + 1}`} onClick={() => setPares(pares.filter((_, j) => j !== i))}>✕</button>}
        </div>
      ))}
      <div className="botones">
        <button type="button" className="boton chico" onClick={() => setPares([...pares, { ...VACIO }])}>+ otro par</button>
        <button type="button" className="boton principal chico" onClick={agregar} disabled={subiendo || listos.length === 0}>
          {subiendo ? "Subiendo…" : listos.length > 1 ? `Agregar los ${listos.length} ejemplos` : "Agregar"}
        </button>
      </div>
      {error && <p className="error chico" role="alert">{error}</p>}
    </div>
  );
}
