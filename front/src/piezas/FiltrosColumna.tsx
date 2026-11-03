import { useMemo, useState } from "react";
import { normalizar } from "../estado";

export type Filtros = Record<string, string>;

interface Props {
  columnas: string[];
  filtros: Filtros;
  alCambiar: (f: Filtros) => void;
  antes?: number;
  despues?: number;
  /** Los valores de cada columna, para la lista que aparece al escribir o con ▾. */
  valores?: (columna: string) => unknown[];
}

const MAXIMO_LISTA = 300;

/** Fila de encabezado con un campo por columna: lo que se escribe filtra esa columna sin importar tildes ni mayúsculas. */
export function FilaFiltros({ columnas, filtros, alCambiar, antes = 0, despues = 0, valores }: Props) {
  return (
    <tr className="fila-filtros">
      {Array.from({ length: antes }, (_, i) => <th key={`a${i}`} />)}
      {columnas.map((c) => (
        <th key={c}>
          <FiltroConLista columna={c} valor={filtros[c] ?? ""} valores={valores ? () => valores(c) : undefined}
            alCambiar={(v) => alCambiar({ ...filtros, [c]: v })} />
        </th>
      ))}
      {Array.from({ length: despues }, (_, i) => <th key={`d${i}`} />)}
    </tr>
  );
}

interface PropsFiltro {
  columna: string;
  valor: string;
  alCambiar: (v: string) => void;
  valores?: () => unknown[];
}

function FiltroConLista({ columna, valor, alCambiar, valores }: PropsFiltro) {
  const [abierta, setAbierta] = useState(false);
  const [todos, setTodos] = useState(false);
  const distintos = useMemo(() => {
    if (!abierta || !valores) return [];
    const vistos = new Map<string, string>();
    for (const v of valores()) {
      const t = v === null || v === undefined ? "" : String(v).trim();
      if (t && !vistos.has(normalizar(t))) vistos.set(normalizar(t), t);
    }
    return [...vistos.values()].sort((a, b) => a.localeCompare(b, "es", { numeric: true }));
  }, [abierta, valores]);
  const buscado = normalizar(valor.trim());
  const lista = (todos || !buscado ? distintos : distintos.filter((t) => normalizar(t).includes(buscado))).slice(0, MAXIMO_LISTA);

  return (
    <div className="filtro-con-lista" onBlur={(e) => !e.currentTarget.contains(e.relatedTarget) && setAbierta(false)}>
      <input className="filtro-columna" type="search" aria-label={`Filtrar ${columna}`} placeholder="Filtrar"
        value={valor} onChange={(e) => { alCambiar(e.target.value); setTodos(false); setAbierta(Boolean(valores) && e.target.value !== ""); }}
        onKeyDown={(e) => e.key === "Escape" && setAbierta(false)} />
      {valores && (
        <button type="button" className="filtro-abrir" aria-label={`Ver todos los valores de ${columna}`} aria-expanded={abierta && todos}
          onClick={() => { setTodos(true); setAbierta(!(abierta && todos)); }}>▾</button>
      )}
      {abierta && lista.length > 0 && (
        <ul className="filtro-lista" role="listbox" aria-label={`Valores de ${columna}`}>
          {lista.map((t) => (
            <li key={t}>
              <button type="button" role="option" aria-selected={normalizar(t) === buscado} title={t}
                onClick={() => { alCambiar(t); setAbierta(false); }}>{t}</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function cumple(valor: (columna: string) => unknown, filtros: Filtros): boolean {
  return Object.entries(filtros).every(([c, buscado]) => {
    const b = normalizar(buscado.trim());
    if (!b) return true;
    const v = valor(c);
    return v !== null && v !== undefined && normalizar(String(v)).includes(b);
  });
}
