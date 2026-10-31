import { useSyncExternalStore } from "react";

// Router mínimo sobre la History API: la web tiene pocas pantallas y no necesita más.
const avisar = new Set<() => void>();

export function navegar(a: string, reemplazar = false) {
  if (a === location.pathname) return;
  if (reemplazar) history.replaceState(null, "", a);
  else history.pushState(null, "", a);
  avisar.forEach((f) => f());
}

window.addEventListener("popstate", () => avisar.forEach((f) => f()));

function suscribir(f: () => void) {
  avisar.add(f);
  return () => avisar.delete(f);
}

export function useRuta(): string {
  return useSyncExternalStore(suscribir, () => location.pathname);
}

/** Las pantallas de antes; se siguen usando en los links y van a la pantalla nueva que corresponde. */
export type Pantalla = "revisar" | "subir" | "grilla" | "base" | "senal";

export type Destino =
  | { pantalla: "login" }
  | { pantalla: "inicio"; nueva?: boolean }
  | { pantalla: "admin" }
  | { pantalla: "semana"; senal: string }
  | { pantalla: "base"; senal: string | null; config: boolean };

const ID = "([a-z0-9_-]+)";

/** La ruta de una dirección vieja que tiene otra nueva, o null si ya está bien. */
export function rutaNueva(ruta: string): string | null {
  if (ruta === "/todas") return "/";
  const vieja = ruta.match(new RegExp(`^/s/${ID}/(revisar|subir|grilla|base|senal)/?$`));
  return vieja ? aSenal(vieja[1], vieja[2] as Pantalla) : null;
}

export function leerRuta(ruta: string): Destino {
  if (ruta === "/login") return { pantalla: "login" };
  if (ruta === "/admin") return { pantalla: "admin" };
  if (ruta === "/nueva") return { pantalla: "inicio", nueva: true };
  const semana = ruta.match(new RegExp(`^/s/${ID}/?$`));
  if (semana) return { pantalla: "semana", senal: semana[1] };
  const base = ruta.match(new RegExp(`^/base(?:/${ID}(/config)?)?/?$`));
  if (base) return { pantalla: "base", senal: base[1] ?? null, config: !!base[2] };
  return { pantalla: "inicio" };
}

export function aSenal(senal: string, pantalla: Pantalla = "revisar") {
  if (pantalla === "base") return `/base/${senal}`;
  if (pantalla === "senal") return `/base/${senal}/config`;
  return `/s/${senal}`;
}

export function aBase(senal: string, config = false) {
  return `/base/${senal}${config ? "/config" : ""}`;
}
