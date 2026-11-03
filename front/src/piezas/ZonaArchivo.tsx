import { useState, type DragEvent } from "react";

interface Props {
  archivo: File | null;
  alElegir: (f: File | null) => void;
  /** Con esto se pueden soltar o elegir varios archivos de una vez (la semana en varios archivos). */
  alElegirVarios?: (fs: File[]) => void;
  varios?: File[];
  ayuda?: string;
  accept?: string;
  chica?: boolean;
  deshabilitada?: boolean;
  etiqueta?: string;
}

export function ZonaArchivo({ archivo, alElegir, alElegirVarios, varios = [], ayuda, accept, chica, deshabilitada, etiqueta }: Props) {
  const elegir = (lista: FileList | null) => {
    const fs = Array.from(lista ?? []);
    if (alElegirVarios) alElegirVarios(fs);
    else alElegir(fs[0] ?? null);
  };
  const nombre = varios.length > 1 ? `${varios.length} archivos: ${varios.map((f) => f.name).join(", ")}` : (varios[0] ?? archivo)?.name;
  const [encima, setEncima] = useState(false);

  const soltar = (e: DragEvent) => {
    e.preventDefault();
    setEncima(false);
    if (e.dataTransfer.files.length && !deshabilitada) elegir(e.dataTransfer.files);
  };

  return (
    <label className={`zona-archivo${encima ? " encima" : ""}${chica ? " chica" : ""}${nombre ? " elegido" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setEncima(true); }} onDragLeave={() => setEncima(false)} onDrop={soltar}>
      <svg width={chica ? 24 : 32} height={chica ? 24 : 32} viewBox="0 0 24 24" fill="none" stroke="var(--tenue)" strokeWidth="1.5"
        strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M12 16V4" /><path d="M7 9l5-5 5 5" /><path d="M4 20h16" />
      </svg>
      <span className="grande">{nombre ?? (alElegirVarios ? "Arrastrá el archivo (o varios) o elegilo" : "Arrastrá el archivo o elegilo")}</span>
      {ayuda && <span className="tenue">{ayuda}</span>}
      <input type="file" accept={accept} disabled={deshabilitada} aria-label={etiqueta} multiple={!!alElegirVarios}
        onChange={(e) => elegir(e.target.files)} className="solo-lector" />
    </label>
  );
}
