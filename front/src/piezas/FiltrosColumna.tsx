import { normalizar } from "../estado";

export type Filtros = Record<string, string>;

interface Props {
  columnas: string[];
  filtros: Filtros;
  alCambiar: (f: Filtros) => void;
  antes?: number;
  despues?: number;
}

/** Fila de encabezado con un campo por columna: lo que se escribe filtra esa columna sin importar tildes ni mayúsculas. */
export function FilaFiltros({ columnas, filtros, alCambiar, antes = 0, despues = 0 }: Props) {
  return (
    <tr className="fila-filtros">
      {Array.from({ length: antes }, (_, i) => <th key={`a${i}`} />)}
      {columnas.map((c) => (
        <th key={c}>
          <input className="filtro-columna" type="search" aria-label={`Filtrar ${c}`} placeholder="filtrar"
            value={filtros[c] ?? ""} onChange={(e) => alCambiar({ ...filtros, [c]: e.target.value })} />
        </th>
      ))}
      {Array.from({ length: despues }, (_, i) => <th key={`d${i}`} />)}
    </tr>
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
