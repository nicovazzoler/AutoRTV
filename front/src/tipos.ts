export interface Yo {
  id: number;
  usuario: string;
  admin: boolean;
}

export interface Resumen {
  filas: number;
  base: number;
  nueva_lista: number;
  revisar: number;
  pautas_revisar: number;
  desde: string | null;
  hasta: string | null;
  cambios?: number;
}

export interface MetaSemana {
  senal_id: string;
  tabla_id: string;
  nombre: string;
  subida_por: string;
  subida: string;
  resumen: Resumen | null;
  confirmada_por: string | null;
  confirmada: string | null;
  version: number;
  anterior_nombre: string | null;
}

export interface SenalLista {
  id: string;
  nombre: string;
  formato: string;
  semana: MetaSemana | null;
}

export interface Inicio {
  senales: SenalLista[];
  recientes: string[];
}

export type Celdas = Record<string, unknown>;

export interface Pauta {
  hash: string;
  filas: number[];
  motivos: string[];
  veces: number;
  crudo: Celdas;
  salida: Celdas;
}

export interface Aviso {
  nivel: "error" | "aviso" | "info";
  regla: string;
  mensaje: string;
  fila: number | null;
  columna: string | null;
}

export interface SemanaAbierta {
  semana: MetaSemana | null;
  resumen?: Resumen;
  contenido?: string[];
  programa?: string | null;
  revisar?: Pauta[];
  nuevas?: Pauta[];
  horarios?: Aviso[];
  cambios?: CambioVersion[] | null;
  lectura?: { filas: number; columnas: string[]; hojas?: number };
  campos_clave?: string[];
  armando_reglas?: boolean;
  lectura_agente?: LecturaAgente | null;
  aviso_fechas?: AvisoFechas | null;
}

/** Una grilla semanal sin fechas, o con fechas viejas: la persona elige desde qué lunes va. */
export interface AvisoFechas {
  tipo: "sin_fechas" | "viejas";
  desde: string | null;
  hasta: string | null;
  sugerido: string;
}

/** Qué hizo el agente cuando el código no encontró fecha y hora en la grilla. */
export interface LecturaAgente {
  logrado: boolean;
  modelo?: string;
  explicacion?: string;
  problemas: string[];
}

export interface CambioVersion {
  fecha: string;
  hora: string;
  tipo: "agregado" | "sacado" | "cambiado";
  campos?: string[];
  antes?: Record<string, string>;
  ahora?: Record<string, string>;
}

export interface Grupo {
  grupo: "base" | "nueva_lista" | "revisar";
  motivos: string[];
}

export interface GrillaAbierta {
  semana: MetaSemana;
  columnas: string[];
  filas: unknown[][];
  grupos: Grupo[];
  hashes: string[];
  contenido: string[];
  programa: string | null;
  validaciones: Aviso[];
  total_filas: number;
}

export interface PautaBase {
  hash: string;
  crudo: Celdas;
  salida: Celdas;
  estado: "revisada" | "editada";
  usuario: string;
  actualizado: string;
}

export interface ListaPautas {
  total: number;
  por_estado: Record<string, number>;
  pautas: PautaBase[];
}

export interface ColumnasBase {
  columnas: string[];
  programa: string | null;
}

export interface ValorColumna {
  valor: string | number;
  pautas: number;
}

export interface Condicion {
  columna: string;
  op: string;
  valor?: string;
}

export interface Tarjeta {
  id: string;
  tipo: string;
  activa?: boolean;
  nota?: string;
  si?: Condicion | null;
  [campo: string]: unknown;
}

export interface Receta {
  id: string;
  nombre: string;
  entrada: { tipo: string; partir?: { separador: string; solo_si?: string } | null; [campo: string]: unknown };
  tarjetas: Tarjeta[];
  salida: { columnas: string[] };
  idiomas?: string[];
  titulos_conocidos?: string[];
  [campo: string]: unknown;
}

export interface Metricas {
  errores_tarjetas: number;
  validaciones: Record<string, number>;
  ejemplos: Record<string, number>;
}

export interface Cambio {
  tipo: "agregada" | "modificada" | "borrada" | "salida" | "orden";
  id: string;
  tarjeta?: Tarjeta;
  campos?: string[];
  columnas?: string[];
}

export interface CorreccionBase {
  filtro: Record<string, string>;
  columna: string;
  valor: string | number | null;
  pautas: number;
  descripcion: string;
}

export interface AccionAdmin {
  tipo: string;
  descripcion: string;
  [campo: string]: unknown;
}

export interface Propuesta {
  logrado: boolean;
  explicacion: string;
  receta: Receta | null;
  cambios: Cambio[];
  correcciones_base: CorreccionBase[];
  acciones_admin: AccionAdmin[];
  antes: Metricas | null;
  despues: Metricas | null;
  problemas: string[];
  vueltas: number;
  aviso?: string;
  efecto?: {
    celdas: number;
    ejemplos: { fila: number; columna: string; antes: unknown; despues: unknown }[];
    revisar_antes: number;
    revisar_despues: number;
  };
}

export interface AccionUi {
  tipo: "ir_a" | "nueva_senal" | "armar_reglas";
  pantalla: string;
  senal: string;
  nombre: string;
  descripcion: string;
}

export interface Charla {
  respuesta: string;
  proponer_cambios: boolean;
  acciones: AccionUi[];
  recordar: string;
}

export interface ChatGuardado {
  id: number;
  titulo: string;
  actualizada: string;
}

export interface Limites {
  limite_diario: number;
  usados_hoy: number;
  quedan: number;
}

export interface Evaluacion {
  nombre: string;
  porcentaje?: number;
  error?: string;
  total_diferencias?: number;
}

export interface Version {
  id: number;
  usuario: string;
  fecha: string;
  cambios: Cambio[];
}
