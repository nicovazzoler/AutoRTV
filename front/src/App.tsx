import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { leerRuta, navegar, rutaNueva, useRuta } from "./ruta";
import { ContextoSesion, type Sesion } from "./sesion";
import type { Inicio as DatosInicio, MetaSemana, Yo } from "./tipos";
import { Barra } from "./piezas/Barra";
import { Agente } from "./piezas/Agente";
import { Historial } from "./pantallas/Historial";
import { Login } from "./pantallas/Login";
import { Inicio } from "./pantallas/Inicio";
import { Semana } from "./pantallas/Semana";
import { Base } from "./pantallas/Base";
import { Configuracion } from "./pantallas/Configuracion";
import { Administrar } from "./pantallas/Administrar";
import { olvidarSemana } from "./semanaReciente";

const ULTIMA_SENAL = "autortv.senal";

function ultimaSenalGuardada(): string | null {
  try {
    return localStorage.getItem(ULTIMA_SENAL);
  } catch {
    return null;
  }
}

export function App() {
  const ruta = useRuta();
  const destino = leerRuta(ruta);
  const [yo, setYo] = useState<Yo | null>(null);
  const [inicio, setInicio] = useState<DatosInicio | null>(null);
  const [contexto, setContexto] = useState("");
  const senalDeRuta = "senal" in destino ? destino.senal : null;
  const [ultimaSenal, setUltimaSenal] = useState<string | null>(ultimaSenalGuardada);

  // Los favoritos y links de las pantallas viejas siguen andando.
  useEffect(() => {
    const nueva = rutaNueva(ruta);
    if (nueva) navegar(nueva, true);
  }, [ruta]);

  useEffect(() => {
    if (destino.pantalla !== "login" && !yo) api.get<Yo>("/yo").then(setYo).catch(() => {});
  }, [destino.pantalla, yo]);

  const refrescarSenales = useCallback(async () => setInicio(await api.get<DatosInicio>("/inicio")), []);

  useEffect(() => {
    if (yo) refrescarSenales().catch(() => {});
  }, [yo, refrescarSenales]);

  useEffect(() => {
    if (!senalDeRuta) return;
    setUltimaSenal(senalDeRuta);
    try {
      localStorage.setItem(ULTIMA_SENAL, senalDeRuta);
    } catch {
      // Sin almacenamiento, Base arranca en la señal solo mientras dure la pestaña.
    }
  }, [senalDeRuta]);

  const actualizarSemana = useCallback((senal: string, semana: MetaSemana | null) => {
    setInicio((i) => i && { ...i, senales: i.senales.map((s) => (s.id === senal ? { ...s, semana } : s)) });
  }, []);

  const [revision, setRevision] = useState(0);
  const tocar = useCallback(() => {
    olvidarSemana();
    setRevision((r) => r + 1);
  }, []);

  const sesion = useMemo<Sesion | null>(
    () => yo && { yo, senales: inicio?.senales ?? null, recientes: inicio?.recientes ?? [], refrescarSenales, actualizarSemana,
      revision, tocar, contexto, setContexto },
    [yo, inicio, refrescarSenales, actualizarSemana, revision, tocar, contexto],
  );

  if (destino.pantalla === "login") return <Login />;
  if (!sesion) return null;

  const salir = async () => {
    await api.post("/logout").catch(() => {});
    setYo(null);
    setInicio(null);
    navegar("/login");
  };
  // Cuando el agente cambia reglas o la base, la pantalla se vuelve a armar con lo nuevo.
  const clave = `${senalDeRuta}-${revision}`;
  const senalBase = destino.pantalla === "base" ? destino.senal ?? ultimaSenal : null;
  const senalAgente = senalDeRuta ?? (destino.pantalla === "base" ? senalBase : null);

  return (
    <ContextoSesion.Provider value={sesion}>
      <div className="marco">
        <Barra destino={destino} ultimaSenal={ultimaSenal} alSalir={salir} />
        {destino.pantalla === "inicio" && <Inicio nueva={!!destino.nueva} />}
        {destino.pantalla === "semana" && <Semana key={clave} senalId={destino.senal} />}
        {destino.pantalla === "base" && !destino.config && <Base key={`${senalBase}-${revision}`} senalId={senalBase} />}
        {destino.pantalla === "base" && destino.config && senalBase && <Configuracion key={clave} senalId={senalBase} />}
        {destino.pantalla === "admin" && <Administrar key={revision} />}
        {destino.pantalla === "historial" && <Historial />}
        <Agente senalId={senalAgente} />
      </div>
    </ContextoSesion.Provider>
  );
}
