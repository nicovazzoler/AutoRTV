import { useCallback, useEffect, useState } from "react";
import { api, textoDeError } from "../api";
import { haceCuanto } from "../fechas";
import { CeldaEditable } from "../piezas/CeldaEditable";
import { useSesion } from "../sesion";
import type { Celdas, ColumnasBase, ListaPautas, PautaBase, ValorColumna } from "../tipos";

function vinoComo(crudo: Celdas): string {
  return Object.values(crudo).filter((v) => v !== null && v !== undefined && String(v).trim() !== "").map(String).join(" · ");
}

interface Filtros {
  programa: string;
  columna: string;
  valor: string;
  q: string;
  estado: string;
}

const SIN_FILTROS: Filtros = { programa: "", columna: "", valor: "", q: "", estado: "" };

export function Base({ senalId }: { senalId: string }) {
  const { senales } = useSesion();
  const senal = senales?.find((s) => s.id === senalId);
  const [columnas, setColumnas] = useState<ColumnasBase | null>(null);
  const [programas, setProgramas] = useState<ValorColumna[]>([]);
  const [filtros, setFiltros] = useState<Filtros>(SIN_FILTROS);
  const [q, setQ] = useState("");
  const [lista, setLista] = useState<ListaPautas | null>(null);
  const [marcadas, setMarcadas] = useState<Set<string>>(new Set());
  const [todasDelFiltro, setTodasDelFiltro] = useState(false);
  const [cambiarColumna, setCambiarColumna] = useState("");
  const [cambiarValor, setCambiarValor] = useState("");
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");

  useEffect(() => {
    api.get<ColumnasBase>(`/senales/${senalId}/pautas/columnas`).then((c) => {
      setColumnas(c);
      setCambiarColumna(c.columnas.find((x) => x !== c.programa) ?? c.columnas[0] ?? "");
      if (c.programa) api.get<ValorColumna[]>(`/senales/${senalId}/pautas/valores?columna=${encodeURIComponent(c.programa)}`).then(setProgramas);
    }).catch((e) => setError(textoDeError(e)));
  }, [senalId]);

  // El buscador espera a que se deje de escribir para no pedir la base en cada tecla.
  useEffect(() => {
    const t = setTimeout(() => setFiltros((f) => ({ ...f, q })), 300);
    return () => clearTimeout(t);
  }, [q]);

  const filtroColumnas = useCallback((): Record<string, string> => {
    const r: Record<string, string> = {};
    if (filtros.programa && columnas?.programa) r[columnas.programa] = filtros.programa;
    if (filtros.columna && filtros.valor.trim()) r[filtros.columna] = filtros.valor.trim();
    return r;
  }, [filtros, columnas]);

  const cargar = useCallback(async (desde = 0) => {
    const params = new URLSearchParams({ desde: String(desde) });
    if (filtros.estado) params.set("estado", filtros.estado);
    if (filtros.q.trim()) params.set("q", filtros.q.trim());
    for (const [c, v] of Object.entries(filtroColumnas())) params.append("filtro", `${c}=${v}`);
    const r = await api.get<ListaPautas>(`/senales/${senalId}/pautas?${params}`);
    setLista((l) => (desde && l ? { ...r, pautas: [...l.pautas, ...r.pautas] } : r));
  }, [senalId, filtros, filtroColumnas]);

  useEffect(() => {
    setMarcadas(new Set());
    setTodasDelFiltro(false);
    cargar().catch((e) => setError(textoDeError(e)));
  }, [cargar]);

  const hayFiltro = !!(filtros.estado || filtros.q.trim() || Object.keys(filtroColumnas()).length);
  const seleccion = () => (todasDelFiltro ? { estado: filtros.estado || null, q: filtros.q, filtro: filtroColumnas() } : { hashes: [...marcadas] });
  const cuantas = todasDelFiltro ? lista?.total ?? 0 : marcadas.size;
  const pautas = lista?.pautas ?? [];
  const todasVisibles = pautas.length > 0 && pautas.every((p) => marcadas.has(p.hash));

  const alternar = (h: string) => {
    setTodasDelFiltro(false);
    setMarcadas((m) => {
      const n = new Set(m);
      if (n.has(h)) n.delete(h);
      else n.add(h);
      return n;
    });
  };
  const alternarVisibles = () => {
    setTodasDelFiltro(false);
    setMarcadas(todasVisibles ? new Set() : new Set(pautas.map((p) => p.hash)));
  };

  const hacer = async (accion: () => Promise<string>) => {
    setError("");
    setAviso("");
    try {
      setAviso(await accion());
      setMarcadas(new Set());
      setTodasDelFiltro(false);
      await cargar();
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  const aplicar = () => hacer(async () => {
    const r = await api.post<{ editadas: number }>(`/senales/${senalId}/pautas/editar-varias`,
      { ...seleccion(), columna: cambiarColumna, valor: cambiarValor });
    return `Listo: ${r.editadas} pautas con ${cambiarColumna} = ${cambiarValor || "(vacío)"}. La semana abierta ya sale así.`;
  });

  const olvidar = () => {
    if (!confirm(`¿Olvidar ${cuantas} pautas? La próxima vez que vengan las arman las reglas y piden revisión.`)) return;
    hacer(async () => {
      const r = await api.post<{ olvidadas: number }>(`/senales/${senalId}/pautas/olvidar-varias`, seleccion());
      return `Se olvidaron ${r.olvidadas} pautas.`;
    });
  };

  const editarCelda = async (p: PautaBase, columna: string, valor: string) => {
    setError("");
    try {
      await api.put(`/senales/${senalId}/pautas/${p.hash}`, { salida: { ...p.salida, [columna]: valor } });
      await cargar();
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  const total = Object.values(lista?.por_estado ?? {}).reduce((a, b) => a + b, 0);
  const cols = columnas?.columnas ?? [];

  return (
    <main className="contenido">
      <header className="cabecera-textos">
        <span className="antetitulo">{senal?.nombre ?? senalId} · {total} pautas guardadas</span>
        <h1 className="titulo">La base</h1>
        <p className="bajada">Cada programa que ya pasó, tal como quedó en el EPG. Lo que corrijas acá sale así todas las semanas, y la semana abierta se vuelve a armar sola.</p>
      </header>

      <div className="filtros" role="group" aria-label="Filtros">
        {columnas?.programa && (
          <label className="campo">Programa
            <select className="entrada" value={filtros.programa} onChange={(e) => setFiltros({ ...filtros, programa: e.target.value })}>
              <option value="">Todos</option>
              {programas.map((p) => <option key={String(p.valor)} value={String(p.valor)}>{String(p.valor)} ({p.pautas})</option>)}
            </select>
          </label>
        )}
        <div style={{ display: "flex", alignItems: "flex-end", gap: 6 }}>
          <label className="campo">Columna
            <select className="entrada" value={filtros.columna} onChange={(e) => setFiltros({ ...filtros, columna: e.target.value })}>
              <option value="">—</option>
              {cols.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <span className="tenue" style={{ minHeight: 36, display: "flex", alignItems: "center" }}>=</span>
          <label className="campo">Valor
            <input className="entrada" style={{ width: 140 }} value={filtros.valor} disabled={!filtros.columna}
              onChange={(e) => setFiltros({ ...filtros, valor: e.target.value })} />
          </label>
        </div>
        <label className="campo">Estado
          <select className="entrada" value={filtros.estado} onChange={(e) => setFiltros({ ...filtros, estado: e.target.value })}>
            <option value="">Todas</option>
            <option value="revisada">Revisadas</option>
            <option value="editada">Corregidas a mano</option>
          </select>
        </label>
        <label className="campo" style={{ flex: "1 1 180px" }}>Buscar
          <input className="entrada" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="En cómo vino o cómo quedó" />
        </label>
        {hayFiltro && <button type="button" className="boton chico" onClick={() => { setFiltros(SIN_FILTROS); setQ(""); }}>Limpiar filtros</button>}
      </div>

      {error && <p className="error" role="alert">{error}</p>}
      {aviso && <p className="nota" role="status">{aviso}</p>}

      <div className="desplazable con-alto">
        <table className="tabla-datos">
          <thead>
            <tr>
              <th><input type="checkbox" checked={todasVisibles} onChange={alternarVisibles} aria-label="Marcar todas las que se ven" style={{ width: 18, height: 18, accentColor: "var(--acento)" }} /></th>
              <th>Cómo vino</th>
              {cols.map((c) => <th key={c}>{c}</th>)}
              <th>Último cambio</th>
            </tr>
          </thead>
          <tbody>
            {pautas.map((p) => (
              <tr key={p.hash}>
                <td><input type="checkbox" checked={todasDelFiltro || marcadas.has(p.hash)} onChange={() => alternar(p.hash)}
                  aria-label={`Marcar ${vinoComo(p.crudo)}`} style={{ width: 18, height: 18, accentColor: "var(--acento)" }} /></td>
                <td className="chico tenue" style={{ minWidth: 220 }}>{vinoComo(p.crudo)}</td>
                {cols.map((c) => (
                  <CeldaEditable key={c} columna={c} valor={p.salida[c]} editable clase={c === columnas?.programa ? "programa" : ""}
                    alGuardar={(v) => editarCelda(p, c, v)} />
                ))}
                <td className="chico tenue" style={{ whiteSpace: "nowrap" }}>
                  {p.usuario} · {haceCuanto(p.actualizado)}{p.estado === "editada" ? " · a mano" : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="botones" style={{ alignItems: "center" }}>
        <span className="chico tenue">{lista ? `Se ven ${pautas.length} de ${lista.total} pautas.` : "Cargando la base…"}</span>
        {lista && pautas.length < lista.total && (
          <button type="button" className="boton chico" onClick={() => cargar(pautas.length).catch((e) => setError(textoDeError(e)))}>Ver más</button>
        )}
        {todasVisibles && hayFiltro && lista && lista.total > pautas.length && !todasDelFiltro && (
          <button type="button" className="boton chico" onClick={() => setTodasDelFiltro(true)}>Marcar las {lista.total} del filtro</button>
        )}
      </div>

      {cuantas > 0 && (
        <div className="barra-acciones" role="group" aria-label="Cambiar las marcadas">
          <b>Con las {cuantas} marcadas:</b>
          <label className="campo" style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>cambiar
            <select className="entrada" value={cambiarColumna} onChange={(e) => setCambiarColumna(e.target.value)}>
              {cols.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <label className="campo" style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>a
            <input className="entrada" style={{ width: 160 }} value={cambiarValor} onChange={(e) => setCambiarValor(e.target.value)} placeholder="vacío" />
          </label>
          <button type="button" className="boton principal chico" onClick={aplicar} disabled={!cambiarColumna}>Aplicar</button>
          <span style={{ flexGrow: 1 }} />
          <button type="button" className="boton chico" onClick={olvidar}>Olvidar</button>
        </div>
      )}
    </main>
  );
}
