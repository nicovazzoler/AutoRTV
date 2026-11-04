import type { Cambio, Receta, Tarjeta } from "./tipos";

export const NOMBRES: Record<string, string> = {
  limpiar_espacios: "Limpiar espacios", reemplazar: "Reemplazar", quitar: "Quitar", separar: "Separar",
  extraer: "Extraer", mayus_minus: "Mayúsculas / minúsculas", asignar: "Asignar valor", a_numero: "Pasar a número",
  correcciones: "Correcciones fijas", renombrar: "Renombrar columnas", numerar: "Numerar filas",
  redondear_hora: "Redondear hora", dia_semana: "Día de la semana", duracion: "Duración",
  clasificar_sinopsis: "Sinopsis: programa o capítulo", convertir_zona: "Convertir zona horaria",
  criterios: "Criterios generales",
};

const OPERADORES: Record<string, string> = { igual: "es igual a", distinto: "es distinto de", contiene: "contiene",
  empieza: "empieza con", termina: "termina con", vacio: "está vacía", no_vacio: "no está vacía", regex: "cumple el patrón" };
const MODOS_MAYUS: Record<string, string> = { MAYUS: "MAYÚSCULAS", minus: "minúsculas", Titulo: "Tipo Título",
  Oracion: "Tipo oración", titulo_en: "título en inglés (palabras chicas en minúscula)" };
const PRESETS: Record<string, string> = { entre_parentesis: "lo que está entre paréntesis", numero: "el número", anio: "el año" };

const c = (x: unknown) => `«${x}»`;

function columnas(cols: unknown): string {
  if (cols === "*" || cols === undefined) return "todas las columnas";
  return (Array.isArray(cols) ? cols : [cols]).join(", ");
}

/** La tarjeta como una frase que entiende cualquiera, sin JSON. */
export function frase(t: Tarjeta): string {
  const x = t as Record<string, any>; // cada tipo trae sus campos; el motor ya los validó
  const textos: Record<string, () => string> = {
    limpiar_espacios: () => `Limpia espacios de más y saltos de línea en ${columnas(x.columnas)}`,
    reemplazar: () => x.modo === "celda"
      ? `Si la celda dice exactamente ${c(x.buscar)}, la cambia por ${c(x.por)} (${columnas(x.columnas)})`
      : `${x.por ? "Cambia" : "Borra"} ${x.modo === "regex" ? "el patrón " : ""}${c(x.buscar)}${x.por ? ` por ${c(x.por)}` : ""} en ${columnas(x.columnas)}`,
    quitar: () => `Saca ${x.regex ? "el patrón " : ""}${c(x.texto)}${({ inicio: " del principio", fin: " del final", todo: "" } as Record<string, string>)[x.donde || "todo"]} de ${columnas(x.columnas)}`,
    separar: () => `Parte ${x.columna} en ${x.destinos?.[0]} y ${x.destinos?.[1]} ` + (({
      separador: `donde aparece ${c(x.valor)}`, min_mayus: "donde termina una minúscula y empieza una Mayúscula",
      titulos_conocidos: "usando los programas que ya conoce", regex: `con el patrón ${c(x.valor)}` } as Record<string, string>)[x.modo] ?? ""),
    extraer: () => `Copia ${PRESETS[x.preset] || `el patrón ${c(x.patron)}`} de ${x.columna} a ${x.destino}${x.quitar_del_origen ? " y lo saca del original" : ""}`,
    mayus_minus: () => `Pasa ${columnas(x.columnas)} a ${MODOS_MAYUS[x.modo] ?? x.modo}`,
    asignar: () => `Pone ${c(x.valor)} en ${x.columna}`,
    a_numero: () => `Pasa ${columnas(x.columnas)} a número ("01" → 1)`,
    correcciones: () => `Corrige a mano ${Object.keys(x.mapa || {}).length} textos en ${columnas(x.columnas)}`,
    renombrar: () => `Renombra columnas: ${Object.entries(x.mapa || {}).map(([a, b]) => `${a} → ${b}`).join(", ")}`,
    numerar: () => `Numera las filas en ${x.columna || "N"}`,
    redondear_hora: () => `Redondea la hora de ${x.columna} ${(x.a_minutos || 1) > 1 ? `a ${x.a_minutos} minutos` : "al minuto"}`,
    dia_semana: () => `Escribe en ${x.destino || "Dia"} el día de la semana de ${x.columna}`,
    duracion: () => `${x.destino || "Duracion"} = minutos hasta el programa siguiente${x.ultimo_hasta ? ` (el último termina a las ${x.ultimo_hasta})` : ""}`,
    convertir_zona: () => `Pasa ${x.columna}${x.hora ? ` y ${x.hora}` : ""} de ${x.desde} a ${x.hacia} (en ${x.destino_fecha || "Fecha"} y ${x.destino_hora || "Hora"})`,
    criterios: () => {
      const destinos = [x.programa, x.capitulo, x.temporada, x.numero, x.anio, x.tt].filter(Boolean).join(", ");
      return `Lee ${x.columna}${x.detalle ? ` y ${x.detalle}` : ""} con los criterios generales (programa conocido, separadores, temporada y capítulo, año, repetición, vivo, mayúsculas) y lo pasa a ${destinos}`;
    },
    clasificar_sinopsis: () => `Si la sinopsis de ${x.sinopsis} se repite en todos los capítulos va a ${x.destino_programa}; si cambia, a ${x.destino_capitulo}`,
  };
  let texto = textos[t.tipo]?.() ?? NOMBRES[t.tipo] ?? t.tipo;
  if (t.si) texto += `, solo si ${t.si.columna} ${OPERADORES[t.si.op] ?? t.si.op}${["vacio", "no_vacio"].includes(t.si.op) ? "" : " " + c(t.si.valor)}`;
  return texto;
}

export function fraseCambio(cambio: Cambio): string {
  if (cambio.tipo === "salida") return `Columnas de salida: ${cambio.columnas?.join(", ") || "todas"}`;
  if (cambio.tipo === "orden") return "Cambia el orden de las reglas";
  const signo = { agregada: "Agrega", modificada: "Cambia", borrada: "Saca" }[cambio.tipo];
  return `${signo}: ${cambio.tarjeta ? frase(cambio.tarjeta) : cambio.id}`;
}

export function fraseEntrada(r: Receta): string {
  const e = r.entrada as Record<string, any>;
  const base: Record<string, string> = {
    excel: `Excel · encabezado en la fila ${e.fila_encabezado ?? 1}`,
    pdf: `PDF · ${e.paginas?.length ? `páginas ${e.paginas.join(", ")}` : "todas las páginas"}`,
    texto: `Texto · ${e.separador ? `separado por ${c(e.separador)}` : e.separador === "" ? "líneas «hora programa»" : "separador detectado solo"}`,
    xml: `XML · ${e.elemento ? `cada programa es <${e.elemento}>` : "XMLTV"}`,
    html: `HTML · ${e.bloque ? `bloque ${c(e.bloque)}` : "bloque detectado solo"}${e.epg && Object.keys(e.epg).length ? " · EPG crudo" : ""}`,
    codigo: "Lector en código que escribió el agente",
  };
  return base[e.tipo] ?? e.tipo;
}

export function fraseIdiomas(r: Receta): string {
  const i = r.idiomas ?? [];
  if (!i.length) return "Solo español";
  return i.map((x) => ({ ing: "lleva inglés", port: "lleva portugués" } as Record<string, string>)[x] ?? x).join(" y ");
}
