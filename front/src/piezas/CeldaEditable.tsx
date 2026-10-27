import { useState, type KeyboardEvent } from "react";

interface Props {
  valor: unknown;
  editable: boolean;
  columna: string;
  clase?: string;
  aviso?: string;
  alGuardar: (valor: string) => Promise<void>;
}

/** Celda que se corrige con doble clic (o Enter desde el teclado). Enter guarda, Escape cancela. */
export function CeldaEditable({ valor, editable, columna, clase = "", aviso, alGuardar }: Props) {
  const [editando, setEditando] = useState(false);
  const [guardando, setGuardando] = useState(false);
  const texto = valor === null || valor === undefined ? "" : String(valor);

  const tecla = async (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") setEditando(false);
    if (e.key !== "Enter") return;
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
        <input className="celda-entrada" defaultValue={texto} autoFocus disabled={guardando} aria-label={`Corregir ${columna}`}
          onKeyDown={tecla} onBlur={() => !guardando && setEditando(false)} />
      </td>
    );
  }
  const clases = [clase, editable ? "editable" : "", aviso ? "invalida" : ""].filter(Boolean).join(" ");
  const titulo = aviso ?? (editable ? "Doble clic para corregir" : undefined);
  return (
    <td className={clases} title={titulo} tabIndex={editable ? 0 : undefined}
      onDoubleClick={editable ? () => setEditando(true) : undefined}
      onKeyDown={editable ? (e) => e.key === "Enter" && setEditando(true) : undefined}>
      {texto}
    </td>
  );
}
