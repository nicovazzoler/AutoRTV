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
}
