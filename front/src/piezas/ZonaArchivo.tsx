import { useState, type DragEvent } from "react";

interface Props {
  archivo: File | null;
  alElegir: (f: File | null) => void;
  ayuda?: string;
  accept?: string;
  chica?: boolean;
  deshabilitada?: boolean;
  etiqueta?: string;
}

export function ZonaArchivo({ archivo, alElegir, ayuda, accept, chica, deshabilitada, etiqueta }: Props) {
  const [encima, setEncima] = useState(false);

  const soltar = (e: DragEvent) => {
    e.preventDefault();
    setEncima(false);
    const f = e.dataTransfer.files[0];
    if (f && !deshabilitada) alElegir(f);
  };

  return (
    <label className={`zona-archivo${encima ? " encima" : ""}${chica ? " chica" : ""}${archivo ? " elegido" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setEncima(true); }} onDragLeave={() => setEncima(false)} onDrop={soltar}>
      <svg width={chica ? 24 : 32} height={chica ? 24 : 32} viewBox="0 0 24 24" fill="none" stroke="var(--tenue)" strokeWidth="1.5"
        strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M12 16V4" /><path d="M7 9l5-5 5 5" /><path d="M4 20h16" />
      </svg>
      <span className="grande">{archivo ? archivo.name : "Arrastrá el archivo o elegilo"}</span>
      {ayuda && <span className="tenue">{ayuda}</span>}
      <input type="file" accept={accept} disabled={deshabilitada} aria-label={etiqueta}
        onChange={(e) => alElegir(e.target.files?.[0] ?? null)} className="solo-lector" />
    </label>
  );
}
