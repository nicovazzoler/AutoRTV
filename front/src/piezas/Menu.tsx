import { useState } from "react";
import { aSenal, navegar, type Destino, type Pantalla } from "../ruta";
import { useSesion } from "../sesion";
import { useTema } from "../tema";
import type { SenalLista } from "../tipos";
import { CambiarClave } from "./CambiarClave";
import { Enlace } from "./Enlace";

const SECCIONES: { id: Pantalla | "inicio" | "todas" | "admin"; nombre: string }[] = [
  { id: "inicio", nombre: "Inicio" },
  { id: "todas", nombre: "Todas las señales" },
  { id: "revisar", nombre: "Revisar" },
  { id: "grilla", nombre: "Grilla" },
  { id: "base", nombre: "Base" },
  { id: "senal", nombre: "Señal" },
  { id: "admin", nombre: "Admin" },
];

interface Props {
  destino: Destino;
  senalId: string | null;
  senal: SenalLista | undefined;
  alSalir: () => void;
}

export function Menu({ destino, senalId, senal, alSalir }: Props) {
  const { yo, senales } = useSesion();
  const [eligiendo, setEligiendo] = useState(false);
  const [buscar, setBuscar] = useState("");
  const [tema, alternarTema] = useTema();
  const [abierto, setAbierto] = useState(false);
  const [clave, setClave] = useState(false);
  const actual = destino.pantalla === "subir" ? "revisar" : destino.pantalla === "nueva" ? "inicio" : destino.pantalla;
  const pendientes = senal?.semana?.resumen?.revisar;
  const secciones = SECCIONES.filter((s) => s.id !== "admin" || yo.admin);
  const sinTildes = (t: string) => t.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  const elegibles = (senales ?? []).filter((s) => sinTildes(s.nombre).includes(sinTildes(buscar.trim()))).slice(0, 8);
  const elegir = (id: string) => {
    setEligiendo(false);
    setBuscar("");
    const quedarse = ["revisar", "grilla", "base", "senal"].includes(actual) ? actual as Pantalla : "revisar";
    navegar(aSenal(id, quedarse));
  };

  return (
    <nav className="menu" aria-label="Secciones">
      <Enlace a="/" className="menu-logo">Auto<span className="marca-texto">RTV</span></Enlace>
      <div className="selector-senal">
        <button type="button" className="menu-senal" aria-haspopup="dialog" aria-expanded={eligiendo} onClick={() => setEligiendo(!eligiendo)}>
          <span className="menu-senal-textos">
            <small>{senal ? "Señal · tocá para cambiar" : "Elegí una señal"}</small>
            <span>{senal?.nombre ?? "Ninguna abierta"}</span>
          </span>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M7 4l-4 4 4 4" /><path d="M3 8h14" /><path d="M17 20l4-4-4-4" /><path d="M21 16H7" />
          </svg>
        </button>
        {eligiendo && (
          <div className="selector-lista" role="dialog" aria-label="Cambiar de señal" onKeyDown={(e) => e.key === "Escape" && setEligiendo(false)}>
            <input className="entrada" autoFocus placeholder="Buscar señal" aria-label="Buscar señal" value={buscar} onChange={(e) => setBuscar(e.target.value)} />
            <ul>
              {elegibles.map((s) => (
                <li key={s.id}><button type="button" aria-current={s.id === senalId ? "true" : undefined} onClick={() => elegir(s.id)}>{s.nombre}</button></li>
              ))}
              {elegibles.length === 0 && <li className="chico tenue" style={{ padding: "6px 10px" }}>Ninguna con ese nombre</li>}
            </ul>
          </div>
        )}
      </div>
      <Enlace a="/nueva" className="menu-nueva">+ Nueva señal</Enlace>
      <ol>
        {secciones.map((s, i) => {
          const deSenal = !["inicio", "todas", "admin"].includes(s.id);
          const a = s.id === "inicio" ? "/" : !deSenal ? `/${s.id}` : senalId ? aSenal(senalId, s.id as Pantalla) : "/";
          return (
            <li key={s.id}>
              <Enlace a={a} className="menu-item" aria-current={actual === s.id ? "page" : undefined}
                aria-disabled={deSenal && !senalId ? "true" : undefined}>
                <span className="numero">{String(i + 1).padStart(2, "0")}</span>
                {s.nombre}
                {s.id === "revisar" && pendientes ? <span className="cuenta">{pendientes}</span> : null}
              </Enlace>
            </li>
          );
        })}
      </ol>
      <span className="menu-espacio" />
      <div className="cuenta-usuario">
        {abierto && (
          <div className="menu-cuenta" role="menu" aria-label="Tu cuenta">
            <button type="button" role="menuitem" onClick={() => { setClave(true); setAbierto(false); }}>Cambiar mi clave</button>
            <button type="button" role="menuitem" onClick={alternarTema}>{tema === "oscuro" ? "Pasar a tema claro" : "Pasar a tema oscuro"}</button>
            <button type="button" role="menuitem" onClick={alSalir}>Salir</button>
          </div>
        )}
        <div className="cuenta-fila">
          <button type="button" className="cuenta-boton" aria-haspopup="menu" aria-expanded={abierto} onClick={() => setAbierto(!abierto)}>
            <span className="inicial" aria-hidden="true">{yo.usuario[0]?.toUpperCase()}</span>
            <span className="cuenta-nombre"><b>{yo.usuario}</b><small>{yo.admin ? "admin" : "usuario"}</small></span>
          </button>
          <button type="button" className="boton-redondo" aria-label="Salir" title="Salir" onClick={alSalir}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><path d="M16 17l5-5-5-5" /><path d="M21 12H9" />
            </svg>
          </button>
        </div>
      </div>
      {clave && <CambiarClave alCerrar={() => setClave(false)} />}
    </nav>
  );
}
