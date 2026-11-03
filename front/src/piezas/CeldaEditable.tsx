import { useState, type KeyboardEvent } from "react";

interface Props {
  valor: unknown;
  editable: boolean;
  columna: string;
  clase?: string;
  aviso?: string;
  alGuardar: (valor: string) => Promise<void>;
}

// Más largo que esto, la celda muestra 2 renglones con "…" y el texto entero se lee tocándola.
const LARGO = 40;

/** Celda que se corrige con doble clic (o Enter desde el teclado). Enter guarda, Escape cancela. */
export function CeldaEditable({ valor, editable, columna, clase = "", aviso, alGuardar }: Props) {
  const [editando, setEditando] = useState(false);
  const [guardando, setGuardando] = useState(false);
  const [leyendo, setLeyendo] = useState(false);
  const texto = valor === null || valor === undefined ? "" : String(valor);

  const tecla = async (e: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    if (e.key === "Escape") setEditando(false);
    if (e.key !== "Enter") return;
    e.preventDefault();
    const nuevo = e.currentTarget.value;
    setGuardando(true);
    try {
      await alGuardar(nuevo);
    } finally {
      setGuardando(false);
      setEditando(false);
    }
  };

  if (editando) {
    return (
      <td className={clase}>
        {texto.length > LARGO ? (
          <textarea className="celda-entrada larga" defaultValue={texto} autoFocus disabled={guardando} aria-label={`Corregir ${columna}`}
            rows={5} onKeyDown={tecla} onBlur={() => !guardando && setEditando(false)} />
        ) : (
          <input className="celda-entrada" defaultValue={texto} autoFocus disabled={guardando} aria-label={`Corregir ${columna}`}
            onKeyDown={tecla} onBlur={() => !guardando && setEditando(false)} />
        )}
      </td>
    );
  }
  const clases = [clase, editable ? "editable" : "", aviso ? "invalida" : ""].filter(Boolean).join(" ");
  const largo = texto.length > LARGO;
  const titulo = [aviso, editable ? "Doble clic para corregir" : null].filter(Boolean).join("\n\n") || undefined;
  return (
    <td className={`${clases}${largo ? " celda-larga" : ""}`} title={titulo} tabIndex={editable || largo ? 0 : undefined}
      onClick={largo ? () => setLeyendo(!leyendo) : undefined} onBlur={() => setLeyendo(false)}
      onDoubleClick={editable ? () => { setLeyendo(false); setEditando(true); } : undefined}
      onKeyDown={(e) => {
        if (e.key === "Escape") setLeyendo(false);
        if (editable && e.key === "Enter") setEditando(true);
      }}>
      {largo ? <span className="dos-renglones">{texto}</span> : texto}
      {leyendo && <div className="globito" role="note">{texto}</div>}
    </td>
  );
}
