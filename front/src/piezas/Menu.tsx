import { useState } from "react";
import { aSenal, type Destino, type Pantalla } from "../ruta";
import { useSesion } from "../sesion";
import { useTema } from "../tema";
import type { SenalLista } from "../tipos";
import { CambiarClave } from "./CambiarClave";
import { Enlace } from "./Enlace";

const SECCIONES: { id: Pantalla | "inicio" | "admin"; nombre: string }[] = [
  { id: "inicio", nombre: "Inicio" },
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
  const { yo } = useSesion();
  const [tema, alternarTema] = useTema();
  const [abierto, setAbierto] = useState(false);
  const [clave, setClave] = useState(false);
  const actual = destino.pantalla === "subir" ? "revisar" : destino.pantalla === "nueva" ? "inicio" : destino.pantalla;
  const pendientes = senal?.semana?.resumen?.revisar;
  const secciones = SECCIONES.filter((s) => s.id !== "admin" || yo.admin);

  return (
    <nav className="menu" aria-label="Secciones">
      <Enlace a="/" className="menu-logo">Auto<span className="marca-texto">RTV</span></Enlace>
      <Enlace a="/" className="menu-senal">
        <small>{senal ? "Señal · cambiar" : "Elegí una señal"}</small>
        <span>{senal?.nombre ?? "Ninguna abierta"}</span>
      </Enlace>
      <ol>
        {secciones.map((s, i) => {
          const deSenal = s.id !== "inicio" && s.id !== "admin";
          const a = s.id === "inicio" ? "/" : s.id === "admin" ? "/admin" : senalId ? aSenal(senalId, s.id as Pantalla) : "/";
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
