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

export type Pantalla = "revisar" | "subir" | "grilla" | "base" | "senal";

export type Destino =
  | { pantalla: "login" }
  | { pantalla: "inicio" }
  | { pantalla: "nueva" }
  | { pantalla: "admin" }
  | { pantalla: Pantalla; senal: string };

export function leerRuta(ruta: string): Destino {
  if (ruta === "/login") return { pantalla: "login" };
  if (ruta === "/nueva") return { pantalla: "nueva" };
  if (ruta === "/admin") return { pantalla: "admin" };
  const m = ruta.match(/^\/s\/([a-z0-9_-]+)(?:\/(revisar|subir|grilla|base|senal))?\/?$/);
  if (m) return { pantalla: (m[2] as Pantalla) ?? "revisar", senal: m[1] };
  return { pantalla: "inicio" };
}

export function aSenal(senal: string, pantalla: Pantalla = "revisar") {
  return `/s/${senal}/${pantalla}`;
}
