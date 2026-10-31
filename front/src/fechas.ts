const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
  "noviembre", "diciembre"];
const DIAS = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];

// "2026-11-02" se lee como medianoche local: con new Date("2026-11-02") sería UTC y en Argentina daría el día anterior.
function dia(iso: string): Date {
  const [a, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(a, m - 1, d);
}

export function nombreMes(iso: string, mesesDespues = 0): string {
  return MESES[(dia(iso).getMonth() + mesesDespues) % 12];
}

export function rangoSemana(desde: string | null, hasta: string | null): string {
  if (!desde || !hasta) return "Semana sin fechas";
  const a = dia(desde);
  const b = dia(hasta);
  if (a.getMonth() === b.getMonth()) return `Del ${a.getDate()} al ${b.getDate()} de ${MESES[b.getMonth()]}`;
  return `Del ${a.getDate()} de ${MESES[a.getMonth()]} al ${b.getDate()} de ${MESES[b.getMonth()]}`;
}

export function rangoCorto(desde: string | null, hasta: string | null): string {
  if (!desde || !hasta) return "—";
  const a = dia(desde);
  const b = dia(hasta);
  const mes = (d: Date) => MESES[d.getMonth()].slice(0, 3);
  return a.getMonth() === b.getMonth() ? `${a.getDate()} al ${b.getDate()} ${mes(b)}` : `${a.getDate()} ${mes(a)} al ${b.getDate()} ${mes(b)}`;
}

export function numeroSemana(iso: string): number {
  // Semana ISO: se cuenta por jueves, y la 1 es la que tiene el 4 de enero.
  const jueves = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + 3 - ((d.getDay() + 6) % 7));
  const este = jueves(dia(iso));
  const primero = jueves(new Date(este.getFullYear(), 0, 4));
  return 1 + Math.round((este.getTime() - primero.getTime()) / (7 * 86400000));
}

export function hoyLargo(): string {
  const d = new Date();
  const texto = `${DIAS[d.getDay()]} ${d.getDate()} de ${MESES[d.getMonth()]}`;
  return texto[0].toUpperCase() + texto.slice(1);
}

export function saludo(): string {
  const h = new Date().getHours();
  return h < 13 ? "Buen día" : h < 20 ? "Buenas tardes" : "Buenas noches";
}

export function haceCuanto(iso: string): string {
  const minutos = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutos < 1) return "recién";
  if (minutos < 60) return `hace ${minutos} min`;
  const horas = Math.round(minutos / 60);
  if (horas < 24) return `hace ${horas} h`;
  const d = new Date(iso);
  return horas < 48 ? "ayer" : `${d.getDate()} ${MESES[d.getMonth()].slice(0, 3)}`;
}
