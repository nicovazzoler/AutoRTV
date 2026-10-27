import { useEffect, useState, type FormEvent } from "react";
import { api, textoDeError } from "../api";
import { useSesion } from "../sesion";

interface Usuario {
  id: number;
  usuario: string;
  admin: boolean;
}

interface UsoUsuario {
  usuario: string;
  pedidos: number;
  logrados: number;
  pedidos_hoy: number;
  usd_mes: number;
  usd_hoy: number;
}

interface Uso {
  configurado: boolean;
  limite_diario: number;
  usuarios: UsoUsuario[];
}

interface Columna {
  nombre: string;
  tipo: string;
  regla: string;
  obligatoria: string;
}

interface Resultado {
  descripcion: string;
  ok: boolean;
  clave?: string;
  error?: string;
}

const OBLIGATORIA: Record<string, string> = { si: "obligatoria", ing: "obligatoria si lleva inglés", port: "obligatoria si lleva portugués", no: "opcional" };

function usd(n: number): string {
  return n < 0.01 && n > 0 ? "menos de 0,01 USD" : `${n.toLocaleString("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USD`;
}

export function Admin() {
  const { yo } = useSesion();
  const [usuarios, setUsuarios] = useState<Usuario[]>([]);
  const [uso, setUso] = useState<Uso | null>(null);
  const [catalogo, setCatalogo] = useState<Columna[]>([]);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [tope, setTope] = useState("");

  const cargar = async () => {
    const [u, s, c] = await Promise.all([api.get<Usuario[]>("/usuarios"), api.get<Uso>("/asistente/uso"), api.get<Columna[]>("/catalogo")]);
    setUsuarios(u);
    setUso(s);
    setTope(String(s.limite_diario));
    setCatalogo(c);
  };

  useEffect(() => {
    if (yo.admin) cargar().catch((e) => setError(textoDeError(e)));
  }, [yo.admin]);

  if (!yo.admin) {
    return <main className="contenido angosto"><h1 className="titulo">Solo para admin</h1></main>;
  }

  const accion = async (a: Record<string, unknown>) => {
    setError("");
    setAviso("");
    try {
      const [r] = await api.post<Resultado[]>("/admin/acciones", { acciones: [a] });
      if (!r.ok) setError(`${r.descripcion}: ${r.error}`);
      else setAviso(r.clave ? `${r.descripcion}. La clave es ${r.clave} — anotala y pasásela: no se vuelve a mostrar.` : `Listo: ${r.descripcion.toLowerCase()}.`);
      await cargar();
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  const crear = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const datos = new FormData(e.currentTarget);
    const usuario = String(datos.get("usuario") ?? "").trim();
    if (!usuario) return;
    accion({ tipo: "crear_usuario", usuario, admin: datos.get("admin") === "on" });
    e.currentTarget.reset();
  };

  const borrar = async (u: Usuario) => {
    if (!confirm(`¿Borrar el usuario ${u.usuario}? Se le cierran las sesiones.`)) return;
    try {
      await api.borrar(`/usuarios/${u.id}`);
      await cargar();
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  const subirCatalogo = async (archivo: File | undefined) => {
    if (!archivo) return;
    const datos = new FormData();
    datos.append("archivo", archivo);
    try {
      const c = await api.subir<Columna[]>("/catalogo", datos);
      setCatalogo(c);
      setAviso(`Catálogo cargado: ${c.length} columnas.`);
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  const usoDe = (nombre: string) => uso?.usuarios.find((x) => x.usuario === nombre);
  const totalMes = (uso?.usuarios ?? []).reduce((a, x) => a + x.usd_mes, 0);
  const totalHoy = (uso?.usuarios ?? []).reduce((a, x) => a + x.usd_hoy, 0);
  const pedidosMes = (uso?.usuarios ?? []).reduce((a, x) => a + x.pedidos, 0);

  return (
    <main className="contenido" style={{ maxWidth: 1120 }}>
      <header className="cabecera-textos">
        <span className="antetitulo">Solo admin</span>
        <h1 className="titulo">Admin</h1>
        <p className="bajada">Usuarios, columnas del EPG y cuánto se gasta en el agente. Lo mismo se le puede pedir al agente desde tu usuario.</p>
      </header>

      {error && <p className="error" role="alert">{error}</p>}
      {aviso && <p className="nota" role="status">{aviso}</p>}

      <section aria-label="Usuarios" className="seccion">
        <div className="seccion-cabeza"><h2>Usuarios</h2><span className="chico tenue">{usuarios.length} {usuarios.length === 1 ? "persona" : "personas"}</span></div>
        <div className="desplazable">
          <table className="tabla">
            <thead><tr><th>Usuario</th><th>Rol</th><th className="derecha">Pedidos hoy</th><th className="derecha">Gasto del mes</th><th><span className="solo-lector">Acciones</span></th></tr></thead>
            <tbody>
              {usuarios.map((u) => (
                <tr key={u.id}>
                  <td className="serif" style={{ fontSize: 18 }}>{u.usuario}</td>
                  <td className="tenue">{u.admin ? "Admin" : "Usuario"}</td>
                  <td className="derecha" style={{ fontVariantNumeric: "tabular-nums" }}>{usoDe(u.usuario)?.pedidos_hoy ?? 0}</td>
                  <td className="derecha tenue" style={{ fontVariantNumeric: "tabular-nums" }}>{usd(usoDe(u.usuario)?.usd_mes ?? 0)}</td>
                  <td className="derecha" style={{ whiteSpace: "nowrap", paddingRight: 0 }}>
                    <button type="button" className="boton chico" onClick={() => accion({ tipo: "resetear_clave", usuario: u.usuario })}>Nueva clave</button>{" "}
                    {u.id !== yo.id && <button type="button" className="boton chico tenue" onClick={() => borrar(u)}>Borrar</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <form onSubmit={crear} className="botones" style={{ alignItems: "flex-end", marginTop: 16 }}>
          <label className="campo">Usuario nuevo<input className="entrada" name="usuario" placeholder="nombre" required style={{ minHeight: 40, borderRadius: 999 }} /></label>
          <label className="campo" style={{ flexDirection: "row", alignItems: "center", gap: 8, minHeight: 40, color: "var(--texto)" }}>
            <input type="checkbox" name="admin" style={{ width: 18, height: 18, accentColor: "var(--acento)" }} />Admin
          </label>
          <button type="submit" className="boton fuerte chico" style={{ minHeight: 40 }}>Crear</button>
          <span className="chico tenue">La clave la genera el servidor y se muestra una vez.</span>
        </form>
      </section>

      <section aria-label="Catálogo de columnas" className="seccion">
        <div className="seccion-cabeza">
          <h2>Catálogo de columnas</h2>
          <span className="chico tenue">{catalogo.length} columnas · se valida cada celda</span>
          <span style={{ flexGrow: 1 }} />
          <label className="boton chico" style={{ cursor: "pointer" }}>Subir Columnas.xlsx
            <input type="file" accept=".xlsx,.xls" className="solo-lector" onChange={(e) => subirCatalogo(e.target.files?.[0])} />
          </label>
        </div>
        {catalogo.length === 0 ? <p className="tenue chico" style={{ marginTop: 12 }}>Sin catálogo cargado.</p> : (
          <ul className="lista-simple dos-columnas" style={{ columnGap: 40, gap: 0 }}>
            {catalogo.map((c) => (
              <li key={c.nombre}>
                <b style={{ minWidth: 110 }}>{c.nombre}</b>
                <span className="chico tenue" style={{ flex: "1 1 auto" }}>{c.regla || c.tipo}</span>
                <span className="chico tenue">{OBLIGATORIA[c.obligatoria] ?? c.obligatoria}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Uso del agente" className="seccion" style={{ gap: 16 }}>
        <div className="seccion-cabeza"><h2>Uso del agente</h2><span className="chico tenue">este mes · estimado con el precio de cada modelo</span></div>
        {uso && !uso.configurado && <p className="error">El agente no está configurado: falta ANTHROPIC_API_KEY en Railway.</p>}
        <div className="tres-columnas">
          <div><div className="serif" style={{ fontSize: 36 }}>{usd(totalMes)}</div><span className="chico tenue">en el mes · {pedidosMes} pedidos</span></div>
          <div><div className="serif" style={{ fontSize: 36 }}>{usd(totalHoy)}</div><span className="chico tenue">hoy</span></div>
          <form onSubmit={(e) => { e.preventDefault(); accion({ tipo: "cambiar_limite_diario", valor: Number(tope) }); }}>
            <div className="serif" style={{ fontSize: 36 }}>{uso?.limite_diario ?? "—"}</div>
            <label className="campo" style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>pedidos por persona y día
              <input className="entrada" type="number" min={1} max={1000} value={tope} onChange={(e) => setTope(e.target.value)} style={{ width: 80, minHeight: 32 }} />
              <button type="submit" className="boton chico" style={{ minHeight: 32 }}>Cambiar</button>
            </label>
          </form>
        </div>
        <p className="chico tenue">El número real está en la Console de Anthropic. Este es un tope: no descuenta lo que se cobra menos por la caché.</p>
      </section>
    </main>
  );
}
