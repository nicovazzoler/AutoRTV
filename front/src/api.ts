import { navegar } from "./ruta";

export class ErrorApi extends Error {
  constructor(public estado: number, mensaje: string, public detalle?: unknown) {
    super(mensaje);
  }
}

function mensajeDe(cuerpo: unknown, estado: number): string {
  const detalle = (cuerpo as { detail?: unknown } | null)?.detail;
  if (typeof detalle === "string") return detalle;
  if (detalle && typeof detalle === "object" && "mensaje" in detalle) return String((detalle as { mensaje: unknown }).mensaje);
  if (Array.isArray(detalle)) return "Hay datos inválidos en el pedido";
  return `El servidor respondió ${estado}`;
}

async function pedir(ruta: string, opciones: RequestInit = {}): Promise<Response> {
  const r = await fetch("/api" + ruta, { credentials: "same-origin", ...opciones });
  if (r.status === 401 && ruta !== "/login") {
    navegar("/login");
    throw new ErrorApi(401, "La sesión venció: volvé a entrar");
  }
  if (!r.ok) {
    const cuerpo = await r.json().catch(() => null);
    throw new ErrorApi(r.status, mensajeDe(cuerpo, r.status), (cuerpo as { detail?: unknown } | null)?.detail);
  }
  return r;
}

export const api = {
  async get<T>(ruta: string): Promise<T> {
    return (await pedir(ruta)).json();
  },
  async post<T>(ruta: string, datos: unknown = {}): Promise<T> {
    const r = await pedir(ruta, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(datos) });
    return r.json();
  },
  async subir<T>(ruta: string, formulario: FormData): Promise<T> {
    return (await pedir(ruta, { method: "POST", body: formulario })).json();
  },
  /** Baja un archivo que arma el servidor, con el nombre que manda en Content-Disposition. */
  async descargar(ruta: string) {
    const r = await pedir(ruta);
    const nombre = r.headers.get("Content-Disposition")?.match(/filename="([^"]+)"/)?.[1] ?? "grilla";
    const url = URL.createObjectURL(await r.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: nombre });
    a.click();
    URL.revokeObjectURL(url);
  },
};

export function textoDeError(e: unknown): string {
  return e instanceof Error ? e.message : "Algo salió mal";
}
