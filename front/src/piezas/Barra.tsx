import { useState } from "react";
import { type Destino } from "../ruta";
import { useSesion } from "../sesion";
import { useTema } from "../tema";
import { CambiarClave } from "./CambiarClave";
import { Enlace } from "./Enlace";
import { persona } from "../nombre";

interface Props {
  destino: Destino;
  ultimaSenal: string | null;
  alSalir: () => void;
}

export function Barra({ destino, ultimaSenal, alSalir }: Props) {
  const { yo, senales } = useSesion();
  const [tema, alternarTema] = useTema();
  const [abierto, setAbierto] = useState(false);
  const [clave, setClave] = useState(false);
  const pendientes = (senales ?? []).reduce((n, s) => n + (s.semana?.resumen?.revisar ? 1 : 0), 0);
  const pestanas = [
    { id: "inicio", nombre: "Inicio", a: "/", cuenta: pendientes || "" },
    { id: "base", nombre: "Base", a: ultimaSenal ? `/base/${ultimaSenal}` : "/base", cuenta: "" },
  ];
  const actual = destino.pantalla === "semana" ? "inicio" : destino.pantalla;

  return (
    <header className="barra">
      <Enlace a="/" className="barra-logo">Auto<span className="marca-texto">RTV</span></Enlace>
      <nav aria-label="Pantallas" className="barra-pestanas">
        {pestanas.map((p) => (
          <Enlace key={p.id} a={p.a} className="barra-pestana" aria-current={actual === p.id ? "page" : undefined}>
            {p.nombre}{p.cuenta ? <span className="cuenta">{p.cuenta}</span> : null}
          </Enlace>
        ))}
      </nav>
      <span className="barra-espacio" />
      <div className="barra-cuenta">
        <button type="button" className="cuenta-boton" aria-haspopup="menu" aria-expanded={abierto} onClick={() => setAbierto(!abierto)}>
          <span className="inicial" aria-hidden="true">{yo.usuario[0]?.toUpperCase()}</span>
          <span className="cuenta-nombre"><b>{persona(yo.usuario)}</b></span>
        </button>
        {abierto && (
          <div className="menu-cuenta flotante" role="menu" aria-label="Tu cuenta">
            <button type="button" role="menuitem" onClick={() => { setClave(true); setAbierto(false); }}>Cambiar mi clave</button>
            <button type="button" role="menuitem" onClick={alternarTema}>{tema === "oscuro" ? "Pasar a tema claro" : "Pasar a tema oscuro"}</button>
            {yo.admin && <Enlace a="/admin" role="menuitem" onClick={() => setAbierto(false)}>Administrar</Enlace>}
            <button type="button" role="menuitem" onClick={alSalir}>Salir</button>
          </div>
        )}
      </div>
      {clave && <CambiarClave alCerrar={() => setClave(false)} />}
    </header>
  );
}
