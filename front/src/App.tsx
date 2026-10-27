import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { leerRuta, navegar, useRuta } from "./ruta";
import { ContextoSesion, type Sesion } from "./sesion";
import type { Inicio as DatosInicio, MetaSemana, Yo } from "./tipos";
import { Menu } from "./piezas/Menu";
import { Login } from "./pantallas/Login";
import { Inicio } from "./pantallas/Inicio";
import { Revisar } from "./pantallas/Revisar";
import { Subir } from "./pantallas/Subir";
import { Pronto } from "./pantallas/Pronto";
import { Grilla } from "./pantallas/Grilla";
import { Base } from "./pantallas/Base";
import { Senal } from "./pantallas/Senal";
import { Agente } from "./piezas/Agente";
import { olvidarSemana } from "./semanaReciente";

const ULTIMA_SENAL = "autortv.senal";

function ultimaSenal(): string | null {
  try {
    return localStorage.getItem(ULTIMA_SENAL);
  } catch {
    return null;
  }
}

export function App() {
  const destino = leerRuta(useRuta());
  const [yo, setYo] = useState<Yo | null>(null);
  const [inicio, setInicio] = useState<DatosInicio | null>(null);
  const senalDeRuta = "senal" in destino ? destino.senal : null;
  const senalId = senalDeRuta ?? ultimaSenal();

  useEffect(() => {
    if (destino.pantalla !== "login" && !yo) api.get<Yo>("/yo").then(setYo).catch(() => {});
  }, [destino.pantalla, yo]);

  const refrescarSenales = useCallback(async () => setInicio(await api.get<DatosInicio>("/inicio")), []);

  useEffect(() => {
    if (yo) refrescarSenales().catch(() => {});
  }, [yo, refrescarSenales]);

  useEffect(() => {
    if (!senalDeRuta) return;
    try {
      localStorage.setItem(ULTIMA_SENAL, senalDeRuta);
    } catch {
      // Sin almacenamiento, el menú solo recuerda la señal mientras la URL la tenga.
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
      revision, tocar },
    [yo, inicio, refrescarSenales, actualizarSemana, revision, tocar],
  );

  if (destino.pantalla === "login") return <Login />;
  if (!sesion) return null;

  const salir = async () => {
    await api.post("/logout").catch(() => {});
    setYo(null);
    setInicio(null);
    navegar("/login");
  };
  const senal = sesion.senales?.find((s) => s.id === senalId);
  // Cuando el agente cambia reglas o la base, la pantalla se vuelve a armar con lo nuevo.
  const clave = `${senalDeRuta}-${revision}`;
  const conAgente = "senal" in destino && destino.pantalla !== "subir";

  return (
    <ContextoSesion.Provider value={sesion}>
      <div className="marco">
        <Menu destino={destino} senalId={senal ? senalId : null} senal={senal} alSalir={salir} />
        {destino.pantalla === "inicio" && <Inicio />}
        {destino.pantalla === "revisar" && <Revisar key={clave} senalId={destino.senal} />}
        {destino.pantalla === "subir" && <Subir key={clave} senalId={destino.senal} />}
        {destino.pantalla === "grilla" && <Grilla key={clave} senalId={destino.senal} />}
        {destino.pantalla === "base" && <Base key={clave} senalId={destino.senal} />}
        {destino.pantalla === "senal" && <Senal key={clave} senalId={destino.senal} />}
        {["nueva", "admin"].includes(destino.pantalla) && <Pronto />}
        {conAgente && <Agente key={destino.senal} senalId={destino.senal} />}
      </div>
    </ContextoSesion.Provider>
  );
}
