import { useEffect, useState, type FormEvent } from "react";
import { api, textoDeError } from "../api";
import { BancoAgentes } from "../piezas/BancoAgentes";
import { ZonaArchivo } from "../piezas/ZonaArchivo";
import { useSesion } from "../sesion";
import { persona } from "../nombre";
import { haceCuanto } from "../fechas";
import { Enlace } from "../piezas/Enlace";

interface Usuario {
  id: number;
  usuario: string;
  admin: boolean;
  nombre?: string;
  descripcion?: string;
}

interface Aviso {
  id: number;
  usuario: string;
  senal_id: string;
  tipo: string;
  detalle: string;
  fecha: string;
  visto: boolean;
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

type Pestana = "avisos" | "usuarios" | "senales" | "catalogo" | "uso" | "banco";

const PESTANAS: { id: Pestana; nombre: string }[] = [
  { id: "avisos", nombre: "Avisos" },
  { id: "usuarios", nombre: "Usuarios" },
  { id: "senales", nombre: "Señales" },
  { id: "catalogo", nombre: "Catálogo de columnas" },
  { id: "uso", nombre: "Uso del agente" },
  { id: "banco", nombre: "Banco de agentes" },
];

/** Solo admin, desde el menú de la cuenta: usuarios, señales, catálogo, gasto del agente y banco de agentes. */
export function Administrar() {
  const { yo, senales, refrescarSenales, setContexto } = useSesion();
  const [pestana, setPestana] = useState<Pestana>("avisos");
  const [avisos, setAvisos] = useState<Aviso[]>([]);
  const [buscarSenal, setBuscarSenal] = useState("");
  const [usuarios, setUsuarios] = useState<Usuario[]>([]);
  const [uso, setUso] = useState<Uso | null>(null);
  const [catalogo, setCatalogo] = useState<Columna[]>([]);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");
  const [tope, setTope] = useState("");

  const cargar = async () => {
    const [u, s, c, a] = await Promise.all([api.get<Usuario[]>("/usuarios"), api.get<Uso>("/asistente/uso"),
      api.get<Columna[]>("/catalogo"), api.get<Aviso[]>("/admin/avisos")]);
    setUsuarios(u);
    setAvisos(a);
    setUso(s);
    setTope(String(s.limite_diario));
    setCatalogo(c);
  };

  useEffect(() => {
    if (yo.admin) cargar().catch((e) => setError(textoDeError(e)));
  }, [yo.admin]);

  const marcarVisto = async (a: Aviso) => {
    await api.post(`/admin/avisos/${a.id}/visto`).catch((e) => setError(textoDeError(e)));
    setAvisos((lista) => lista.map((x) => (x.id === a.id ? { ...x, visto: true } : x)));
  };

  const guardarFicha = async (u: Usuario, nombre: string, descripcion: string) => {
    setError("");
    try {
      await api.put(`/usuarios/${u.id}/perfil`, { nombre, descripcion });
      setUsuarios((lista) => lista.map((x) => (x.id === u.id ? { ...x, nombre, descripcion } : x)));
      setAviso(`Ficha de ${persona(u.usuario)} guardada: el agente ya la usa.`);
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  useEffect(() => {
    setContexto(`Administrar · ${PESTANAS.find((x) => x.id === pestana)?.nombre}`);
  }, [pestana, setContexto]);

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

  const borrarSenal = async (id: string, nombre: string) => {
    const escrito = prompt(`Se borra «${nombre}» con sus reglas, ejemplos, base de pautas y semana abierta. No se puede deshacer.\n\nEscribí el nombre de la señal para confirmar:`);
    if (escrito === null) return;
    if (escrito.trim().toLowerCase() !== nombre.trim().toLowerCase()) {
      setError("El nombre no coincide: no se borró nada.");
      return;
    }
    setError("");
    try {
      await api.borrar(`/senales/${id}`);
      setAviso(`Listo: se borró la señal ${nombre}.`);
      await refrescarSenales();
    } catch (e) {
      setError(textoDeError(e));
    }
  };

  const sinTildes = (t: string) => t.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  const senalesFiltradas = (senales ?? []).filter((s) => sinTildes(s.nombre).includes(sinTildes(buscarSenal.trim())));

  const usoDe = (nombre: string) => uso?.usuarios.find((x) => x.usuario === nombre);
  const totalMes = (uso?.usuarios ?? []).reduce((a, x) => a + x.usd_mes, 0);
  const totalHoy = (uso?.usuarios ?? []).reduce((a, x) => a + x.usd_hoy, 0);
  const pedidosMes = (uso?.usuarios ?? []).reduce((a, x) => a + x.pedidos, 0);

  return (
    <main className="contenido" style={{ maxWidth: 1120 }}>
      <header className="cabecera-textos">
        <span className="antetitulo">Solo admin</span>
        <h1 className="titulo">Administrar</h1>
      </header>
      <nav aria-label="Administrar" className="pestanas-linea">
        {PESTANAS.map((x) => (
          <button key={x.id} type="button" aria-current={pestana === x.id ? "page" : undefined} onClick={() => setPestana(x.id)}>{x.nombre}</button>
        ))}
      </nav>

      {error && <p className="error" role="alert">{error}</p>}
      {aviso && <p className="nota" role="status">{aviso}</p>}

      {pestana === "avisos" && (
        <section aria-label="Avisos" className="seccion">
          <div className="seccion-cabeza">
            <h2>Avisos</h2>
            <span className="chico tenue">Cambios de reglas que hizo alguien que no es admin, para dejarlos definitivos o deshacerlos</span>
          </div>
          {avisos.length === 0 ? <p className="tenue">No hay avisos.</p> : (
            <ul className="lista-avisos">
              {avisos.map((a) => (
                <li key={a.id} className={a.visto ? "tenue" : undefined}>
                  <span><b>{persona(a.usuario)}</b> cambió las reglas de <Enlace a={`/base/${a.senal_id}/config`}>{senales?.find((x) => x.id === a.senal_id)?.nombre ?? a.senal_id}</Enlace> · {haceCuanto(a.fecha)}</span>
                  <span className="chico">{a.detalle}</span>
                  {!a.visto && <button type="button" className="boton chico" onClick={() => marcarVisto(a)}>Visto</button>}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {pestana === "usuarios" && (
      <section aria-label="Usuarios" className="seccion">
        <div className="seccion-cabeza"><h2>Usuarios</h2><span className="chico tenue">{usuarios.length} {usuarios.length === 1 ? "persona" : "personas"}</span></div>
        <div className="desplazable">
          <table className="tabla">
            <thead><tr><th>Usuario</th><th>Rol</th><th>Para el agente: nombre y qué hace</th><th className="derecha">Pedidos hoy</th><th className="derecha">Gasto del mes</th><th><span className="solo-lector">Acciones</span></th></tr></thead>
            <tbody>
              {usuarios.map((u) => (
                <tr key={u.id}>
                  <td className="serif" style={{ fontSize: 18 }}>{persona(u.usuario)}</td>
                  <td className="tenue">{u.admin ? "Admin" : "Usuario"}</td>
                  <td><FichaUsuario usuario={u} alGuardar={(nombre, descripcion) => guardarFicha(u, nombre, descripcion)} /></td>
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
          <label className="campo">Usuario nuevo<input className="entrada" name="usuario" placeholder="Nombre" required style={{ minHeight: 40, borderRadius: 999 }} /></label>
          <label className="campo" style={{ flexDirection: "row", alignItems: "center", gap: 8, minHeight: 40, color: "var(--texto)" }}>
            <input type="checkbox" name="admin" style={{ width: 18, height: 18, accentColor: "var(--acento)" }} />Admin
          </label>
          <button type="submit" className="boton fuerte chico" style={{ minHeight: 40 }}>Crear</button>
          <span className="chico tenue">La clave la genera el servidor y se muestra una vez.</span>
        </form>
      </section>
      )}

      {pestana === "senales" && (
      <section aria-label="Señales" className="seccion">
        <div className="seccion-cabeza">
          <h2>Señales</h2><span className="chico tenue">{senales?.length ?? 0} señales</span>
          <span style={{ flexGrow: 1 }} />
          <input className="entrada" aria-label="Buscar señal" placeholder="Buscar señal" value={buscarSenal} onChange={(e) => setBuscarSenal(e.target.value)}
            style={{ minHeight: 36, borderRadius: 999, maxWidth: 240 }} />
        </div>
        <ul className="lista-simple" style={{ maxHeight: 320, overflowY: "auto" }}>
          {senalesFiltradas.slice(0, 100).map((s) => (
            <li key={s.id}>
              <span className="serif" style={{ fontSize: 16, flex: "1 1 auto" }}>{s.nombre}</span>
              <span className="chico tenue">{s.semana ? "con semana abierta" : "sin semana"}</span>
              <button type="button" className="boton chico tenue" onClick={() => borrarSenal(s.id, s.nombre)}>Borrar</button>
            </li>
          ))}
          {senalesFiltradas.length > 100 && <li className="chico tenue">y {senalesFiltradas.length - 100} más: buscá para encontrarla.</li>}
        </ul>
      </section>
      )}

      {pestana === "catalogo" && (
      <section aria-label="Catálogo de columnas" className="seccion">
        <div className="seccion-cabeza">
          <h2>Catálogo de columnas</h2>
          <span className="chico tenue">{catalogo.length} columnas · se valida cada celda</span>
        </div>
        <div style={{ maxWidth: 420, marginTop: 12 }}>
          <ZonaArchivo chica archivo={null} alElegir={(f) => subirCatalogo(f ?? undefined)} accept=".xlsx,.xls" etiqueta="Subir Columnas.xlsx"
            ayuda="Subí un Columnas.xlsx nuevo para reemplazar el catálogo" />
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
      )}

      {pestana === "uso" && (
      <section aria-label="Uso del agente" className="seccion" style={{ gap: 16 }}>
        <div className="seccion-cabeza"><h2>Uso del agente</h2><span className="chico tenue">Este mes · estimado con el precio de cada modelo</span></div>
        {uso && !uso.configurado && <p className="error">El agente no está configurado: falta ANTHROPIC_API_KEY en Railway.</p>}
        <div className="tres-columnas">
          <div><div className="serif" style={{ fontSize: 36 }}>{usd(totalMes)}</div><span className="chico tenue">En el mes · {pedidosMes} pedidos</span></div>
          <div><div className="serif" style={{ fontSize: 36 }}>{usd(totalHoy)}</div><span className="chico tenue">hoy</span></div>
          <form onSubmit={(e) => { e.preventDefault(); accion({ tipo: "cambiar_limite_diario", valor: Number(tope) }); }}>
            <div className="serif" style={{ fontSize: 36 }}>{uso?.limite_diario ?? "—"}</div>
            <label className="campo" style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>Pedidos por persona y día
              <input className="entrada" type="number" min={1} max={1000} value={tope} onChange={(e) => setTope(e.target.value)} style={{ width: 80, minHeight: 32 }} />
              <button type="submit" className="boton chico" style={{ minHeight: 32 }}>Cambiar</button>
            </label>
          </form>
        </div>
        <p className="chico tenue">El número real está en la Console de Anthropic. Este es un tope: no descuenta lo que se cobra menos por la caché.</p>
      </section>
      )}

      {pestana === "banco" && <BancoAgentes />}
    </main>
  );
}


/** Nombre real y qué hace la persona, para que el agente sepa con quién habla. Se guarda al salir del campo. */
function FichaUsuario({ usuario, alGuardar }: { usuario: Usuario; alGuardar: (nombre: string, descripcion: string) => void }) {
  const [nombre, setNombre] = useState(usuario.nombre ?? "");
  const [descripcion, setDescripcion] = useState(usuario.descripcion ?? "");
  const cambio = nombre !== (usuario.nombre ?? "") || descripcion !== (usuario.descripcion ?? "");
  return (
    <div style={{ display: "flex", gap: 6, alignItems: "center", minWidth: 320 }}>
      <input className="entrada" style={{ minHeight: 34, width: 120 }} placeholder="Nombre" aria-label={`Nombre de ${usuario.usuario}`}
        value={nombre} onChange={(e) => setNombre(e.target.value)} />
      <input className="entrada" style={{ minHeight: 34, flex: 1 }} placeholder="Qué hace (ej.: lleva las señales de cine)"
        aria-label={`Qué hace ${usuario.usuario}`} value={descripcion} onChange={(e) => setDescripcion(e.target.value)} />
      {cambio && <button type="button" className="boton chico" onClick={() => alGuardar(nombre, descripcion)}>Guardar</button>}
    </div>
  );
}
