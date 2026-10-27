import type { SenalLista } from "./tipos";

export type TipoEstado = "revisar" | "lista" | "confirmada" | "espera";

export interface Estado {
  tipo: TipoEstado;
  texto: string;
}

const ORDEN: Record<TipoEstado, number> = { revisar: 0, lista: 1, confirmada: 2, espera: 3 };

export function estadoDe(s: SenalLista): Estado {
  const semana = s.semana;
  if (!semana) return { tipo: "espera", texto: "Sin grilla" };
  // Fechas ISO: compararlas como texto alcanza.
  if (semana.confirmada && semana.confirmada >= semana.subida) return { tipo: "confirmada", texto: "Semana confirmada" };
  const revisar = semana.resumen?.revisar ?? 0;
  if (revisar > 0) return { tipo: "revisar", texto: `${revisar} para revisar` };
  return { tipo: "lista", texto: "Lista para confirmar" };
}

export function ordenarPorPendiente(senales: SenalLista[]): SenalLista[] {
  return [...senales].sort((a, b) => ORDEN[estadoDe(a).tipo] - ORDEN[estadoDe(b).tipo] || a.nombre.localeCompare(b.nombre, "es"));
}

export const FORMATOS: Record<string, string> = { excel: "Excel", pdf: "PDF", xml: "XML", html: "HTML", texto: "Texto" };

export function normalizar(texto: string): string {
  return texto.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}
