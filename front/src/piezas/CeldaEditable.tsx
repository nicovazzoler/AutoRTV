import { useState, type KeyboardEvent } from "react";

interface Props {
  valor: unknown;
  editable: boolean;
  columna: string;
  clase?: string;
  aviso?: string;
  alGuardar: (valor: string) => Promise<void>;
}

const LARGO = 60;

/** Celda que se corrige con doble clic (o Enter desde el teclado). Enter guarda, Escape cancela. */
export function CeldaEditable({ valor, editable, columna, clase = "", aviso, alGuardar }: Props) {
  const [editando, setEditando] = useState(false);
  const [guardando, setGuardando] = useState(false);
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
  const titulo = [aviso, largo ? texto : null, editable ? "Doble clic para corregir" : null].filter(Boolean).join("\n\n") || undefined;
  return (
    <td className={clases} title={titulo} tabIndex={editable ? 0 : undefined}
      onDoubleClick={editable ? () => setEditando(true) : undefined}
      onKeyDown={editable ? (e) => e.key === "Enter" && setEditando(true) : undefined}>
      {largo ? <span className="dos-renglones">{texto}</span> : texto}
    </td>
  );
}
