import type { SemanaAbierta } from "./tipos";

// Subir grilla ya trae la semana armada: Revisar la usa en vez de pedirla de nuevo (correrla tarda).
let guardada: { senal: string; datos: SemanaAbierta; cuando: number } | null = null;

export function recordarSemana(senal: string, datos: SemanaAbierta) {
  guardada = { senal, datos, cuando: Date.now() };
}

/** No la borra al leerla: en desarrollo React arma cada pantalla dos veces. Vence sola a los 30 segundos. */
export function tomarSemana(senal: string): SemanaAbierta | null {
  const g = guardada;
  return g && g.senal === senal && Date.now() - g.cuando < 30_000 ? g.datos : null;
}
