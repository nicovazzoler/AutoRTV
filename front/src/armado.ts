import { api } from "./api";

/** El último armado automático de reglas de una señal (lo hace el servidor, en segundo plano). */
export interface Armado {
  estado: "armando" | "aplicado" | "sin_mejora" | "error";
  mensaje: string | null;
  antes: number | null;
  despues: number | null;
}

const CADA_MS = 3000;

export async function esperarArmado(senalId: string): Promise<Armado | null> {
  for (;;) {
    const a = await api.get<Armado | null>(`/senales/${senalId}/reglas/armado`);
    if (!a || a.estado !== "armando") return a;
    await new Promise((listo) => setTimeout(listo, CADA_MS));
  }
}
