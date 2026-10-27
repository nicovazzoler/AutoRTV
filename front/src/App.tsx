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

  const sesion = useMemo<Sesion | null>(
    () => yo && { yo, senales: inicio?.senales ?? null, recientes: inicio?.recientes ?? [], refrescarSenales, actualizarSemana },
    [yo, inicio, refrescarSenales, actualizarSemana],
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

  return (
    <ContextoSesion.Provider value={sesion}>
      <div className="marco">
        <Menu destino={destino} senalId={senal ? senalId : null} senal={senal} alSalir={salir} />
        {destino.pantalla === "inicio" && <Inicio />}
        {destino.pantalla === "revisar" && <Revisar key={destino.senal} senalId={destino.senal} />}
        {destino.pantalla === "subir" && <Subir key={destino.senal} senalId={destino.senal} />}
        {["grilla", "base", "senal", "nueva", "admin"].includes(destino.pantalla) && <Pronto />}
      </div>
    </ContextoSesion.Provider>
  );
}
