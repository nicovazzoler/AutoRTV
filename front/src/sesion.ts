import { createContext, useContext } from "react";
import type { MetaSemana, SenalLista, Yo } from "./tipos";

export interface Sesion {
  yo: Yo;
  senales: SenalLista[] | null;
  recientes: string[];
  refrescarSenales: () => Promise<void>;
  /** Lo que una pantalla sabe de la semana abierta, para que el menú y el Inicio lo muestren sin volver a pedirlo. */
  actualizarSemana: (senal: string, semana: MetaSemana | null) => void;
  /** Sube cada vez que cambian las reglas o la base desde el agente: las pantallas se vuelven a armar. */
  revision: number;
  tocar: () => void;
}

export const ContextoSesion = createContext<Sesion | null>(null);

export function useSesion(): Sesion {
  const s = useContext(ContextoSesion);
  if (!s) throw new Error("useSesion fuera de la sesión");
  return s;
}
