import { useState, type FormEvent } from "react";
import { api, ErrorApi, textoDeError } from "../api";
import type { Receta } from "../tipos";

interface Props {
  receta: Receta;
  version: string;
  alGuardar: () => void;
  alCancelar: () => void;
}

type Valores = Record<string, any>; // la receta tal cual la guarda el servidor, que la valida al recibirla

function numero(v: FormDataEntryValue | null): number | null {
  const s = String(v ?? "").trim();
  return s === "" ? null : Number(s);
}

function texto(v: FormDataEntryValue | null): string | null {
  const s = String(v ?? "").trim();
  return s === "" ? null : s;
}

/** Lo que antes se tocaba en la web vieja: cómo se lee la grilla, idiomas, validaciones y columnas de salida. Solo admin. */
export function ConfigSenal({ receta, version, alGuardar, alCancelar }: Props) {
  const [error, setError] = useState("");
  const [guardando, setGuardando] = useState(false);
  const e = receta.entrada as Valores;
  const v = (receta.validaciones ?? {}) as Valores;

  const guardar = async (ev: FormEvent<HTMLFormElement>) => {
    ev.preventDefault();
    const d = new FormData(ev.currentTarget);
    const entrada: Valores = { ...e };
    if (e.tipo === "excel") Object.assign(entrada, { hoja: texto(d.get("hoja")) ?? 0, fila_encabezado: numero(d.get("fila_encabezado")) ?? 1 });
    if (e.tipo === "pdf") {
      const paginas = String(d.get("paginas") ?? "").split(/[,\s]+/).filter(Boolean).map(Number);
      Object.assign(entrada, { paginas, fecha_inicio: texto(d.get("fecha_inicio")) });
    }
    if (e.tipo === "texto") Object.assign(entrada, { separador: d.get("separador_auto") ? null : String(d.get("separador") ?? ""), fecha_inicio: texto(d.get("fecha_inicio")) });
    if (e.tipo === "xml") entrada.elemento = texto(d.get("elemento"));
    if (e.tipo === "html") entrada.bloque = texto(d.get("bloque"));
    const separador = texto(d.get("partir_separador"));
    entrada.partir = separador ? { ...(e.partir ?? {}), separador, solo_si: texto(d.get("partir_solo_si")) } : null;

    const nueva: Valores = {
      ...receta,
      entrada,
      idiomas: ["ing", "port"].filter((i) => d.get(`idioma_${i}`)),
      salida: { ...receta.salida, columnas: String(d.get("columnas") ?? "").split("\n").map((x) => x.trim()).filter(Boolean) },
      validaciones: {
        ...v,
        dia_minutos: numero(d.get("dia_minutos")),
        max_duracion_min: numero(d.get("max_duracion_min")),
        tolerancia_min: numero(d.get("tolerancia_min")) ?? 0,
        filas_esperadas: numero(d.get("filas_esperadas")),
        huecos: !!d.get("huecos"),
        superposiciones: !!d.get("superposiciones"),
        avisar_titulos_nuevos: !!d.get("avisar_titulos_nuevos"),
        obligatorias: String(d.get("obligatorias") ?? "").split(",").map((x) => x.trim()).filter(Boolean),
        fecha: texto(d.get("col_fecha")), hora: texto(d.get("col_hora")), duracion: texto(d.get("col_duracion")),
        programa: texto(d.get("col_programa")),
      },
    };
    setGuardando(true);
    setError("");
    try {
      await api.put(`/senales/${receta.id}`, nueva, { "If-Match": version });
      alGuardar();
    } catch (err) {
      setError(err instanceof ErrorApi && err.estado === 409 ? `${err.message}. Recargá la página y volvé a cambiarlo.` : textoDeError(err));
      setGuardando(false);
    }
  };

  return (
    <form className="form-config" onSubmit={guardar}>
      <fieldset>
        <legend>Cómo se lee la grilla ({e.tipo})</legend>
        {e.tipo === "excel" && <>
          <label className="campo">Hoja (número o nombre)<input className="entrada" name="hoja" defaultValue={e.hoja ?? 0} style={{ width: 140 }} /></label>
          <label className="campo">Fila del encabezado<input className="entrada" name="fila_encabezado" type="number" min={1} defaultValue={e.fila_encabezado ?? 1} style={{ width: 100 }} /></label>
        </>}
        {e.tipo === "pdf" && <>
          <label className="campo">Páginas (vacío = todas)<input className="entrada" name="paginas" defaultValue={(e.paginas ?? []).join(", ")} placeholder="1, 2" style={{ width: 140 }} /></label>
          <label className="campo">Primer día, si el PDF no lo trae<input className="entrada" name="fecha_inicio" type="date" defaultValue={e.fecha_inicio ?? ""} /></label>
        </>}
        {e.tipo === "texto" && <>
          <label className="tilde"><input type="checkbox" name="separador_auto" defaultChecked={e.separador == null} />Separador detectado solo</label>
          <label className="campo">Separador<input className="entrada" name="separador" defaultValue={e.separador ?? ""} style={{ width: 100 }} /></label>
          <label className="campo">Primer día, si el texto no lo trae<input className="entrada" name="fecha_inicio" type="date" defaultValue={e.fecha_inicio ?? ""} /></label>
        </>}
        {e.tipo === "xml" && <label className="campo">Elemento de cada programa (vacío = XMLTV)<input className="entrada" name="elemento" defaultValue={e.elemento ?? ""} /></label>}
        {e.tipo === "html" && <label className="campo">Bloque de cada programa (vacío = detectar)<input className="entrada" name="bloque" defaultValue={e.bloque ?? ""} placeholder="div.programa" /></label>}
        <label className="campo">Partir celdas con varios programas en (regex)<input className="entrada" name="partir_separador" defaultValue={e.partir?.separador ?? ""} placeholder="\s*/\s+" style={{ width: 160 }} /></label>
        <label className="campo">…solo si aparece (regex)<input className="entrada" name="partir_solo_si" defaultValue={e.partir?.solo_si ?? ""} style={{ width: 160 }} /></label>
      </fieldset>

      <fieldset>
        <legend>Idiomas</legend>
        <label className="tilde"><input type="checkbox" name="idioma_ing" defaultChecked={receta.idiomas?.includes("ing")} />Lleva inglés</label>
        <label className="tilde"><input type="checkbox" name="idioma_port" defaultChecked={receta.idiomas?.includes("port")} />Lleva portugués</label>
      </fieldset>

      <fieldset>
        <legend>Validaciones</legend>
        <label className="campo">Minutos por día<input className="entrada" name="dia_minutos" type="number" defaultValue={v.dia_minutos ?? ""} style={{ width: 100 }} /></label>
        <label className="campo">Duración máxima (min)<input className="entrada" name="max_duracion_min" type="number" defaultValue={v.max_duracion_min ?? ""} style={{ width: 100 }} /></label>
        <label className="campo">Tolerancia (min)<input className="entrada" name="tolerancia_min" type="number" defaultValue={v.tolerancia_min ?? 0} style={{ width: 100 }} /></label>
        <label className="campo">Filas esperadas<input className="entrada" name="filas_esperadas" type="number" defaultValue={v.filas_esperadas ?? ""} style={{ width: 100 }} /></label>
        <label className="tilde"><input type="checkbox" name="huecos" defaultChecked={v.huecos ?? true} />Avisar huecos</label>
        <label className="tilde"><input type="checkbox" name="superposiciones" defaultChecked={v.superposiciones ?? true} />Avisar superposiciones</label>
        <label className="tilde"><input type="checkbox" name="avisar_titulos_nuevos" defaultChecked={v.avisar_titulos_nuevos ?? false} />Avisar títulos nuevos</label>
        <label className="campo" style={{ flex: "1 1 100%" }}>Columnas obligatorias (separadas por coma)<input className="entrada" name="obligatorias" defaultValue={(v.obligatorias ?? []).join(", ")} /></label>
        <label className="campo">Columna fecha (vacío = detectar)<input className="entrada" name="col_fecha" defaultValue={v.fecha ?? ""} style={{ width: 140 }} /></label>
        <label className="campo">Columna hora<input className="entrada" name="col_hora" defaultValue={v.hora ?? ""} style={{ width: 140 }} /></label>
        <label className="campo">Columna duración<input className="entrada" name="col_duracion" defaultValue={v.duracion ?? ""} style={{ width: 140 }} /></label>
        <label className="campo">Columna programa<input className="entrada" name="col_programa" defaultValue={v.programa ?? ""} style={{ width: 140 }} /></label>
      </fieldset>

      <label className="campo">Columnas de salida, una por línea (vacío = las del catálogo, en su orden)
        <textarea className="entrada" name="columnas" rows={4} defaultValue={receta.salida.columnas.join("\n")} style={{ minHeight: 100 }} />
      </label>

      {error && <p className="error" role="alert">{error}</p>}
      <div className="botones">
        <button type="submit" className="boton principal chico" disabled={guardando}>{guardando ? "Guardando…" : "Guardar"}</button>
        <button type="button" className="boton chico" onClick={alCancelar}>Cancelar</button>
      </div>
    </form>
  );
}
