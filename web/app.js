"use strict";
// Editor de recetas: las tarjetas se editan con formularios armados desde el JSON Schema
// que devuelve /api/tipos-tarjeta, así una tarjeta nueva en el backend aparece sola acá.

const NOMBRES = {
  limpiar_espacios: "Limpiar espacios", reemplazar: "Reemplazar", quitar: "Quitar", separar: "Separar",
  extraer: "Extraer", mayus_minus: "Mayúsculas / minúsculas", asignar: "Asignar valor", a_numero: "Pasar a número",
  correcciones: "Correcciones fijas", renombrar: "Renombrar columnas", numerar: "Numerar filas",
  redondear_hora: "Redondear hora", dia_semana: "Día de la semana", duracion: "Duración",
  clasificar_sinopsis: "Sinopsis: programa o capítulo",
};
const ETIQUETAS = {
  columna: "Columna", columnas: "Columnas", buscar: "Buscar", por: "Reemplazar por", modo: "Modo", texto: "Texto",
  donde: "Dónde", regex: "Es regex", valor: "Valor", destinos: "Destinos (programa, capítulo)", titulos: "Títulos conocidos (uno por línea)",
  respaldo: "Si no encuentra título conocido", preset: "Qué extraer", patron: "Patrón (regex)", destino: "Columna destino",
  quitar_del_origen: "Quitar del texto original", mapa: "Pares", inicio: "Empieza en", paso: "Paso",
  a_minutos: "Redondear a (minutos)", idioma: "Idioma", mayusculas: "En mayúsculas", fecha: "Columna fecha",
  hora: "Columna hora", ultimo_hasta: "Último programa termina a las (HH:MM)", programa: "Columna programa",
  capitulo: "Columna capítulo", sinopsis: "Columna sinopsis", destino_programa: "Destino si es de programa",
  destino_capitulo: "Destino si es de capítulo", umbral: "Umbral (0-1)", nota: "Nota",
};
const OPERADORES = { igual: "es igual a", distinto: "es distinto de", contiene: "contiene", empieza: "empieza con",
  termina: "termina con", vacio: "está vacía", no_vacio: "no está vacía", regex: "cumple regex" };
const CAMPOS_DE_COLUMNA = new Set(["columna", "destino", "fecha", "hora", "programa", "capitulo", "sinopsis",
  "destino_programa", "destino_capitulo"]);

const VALIDACIONES_DEFAULT = { fecha: null, hora: null, duracion: null, dia_minutos: 1440, max_duracion_min: 720,
  tolerancia_min: 0, huecos: true, superposiciones: true, filas_esperadas: null, obligatorias: [],
  avisar_titulos_nuevos: false, programa: null };

// Completa los campos opcionales para que "receta abierta" y "receta guardada" se comparen igual.
function normalizar(receta) {
  receta.validaciones = { ...VALIDACIONES_DEFAULT, ...(receta.validaciones || {}) };
  receta.titulos_conocidos = receta.titulos_conocidos || [];
  receta.idiomas = receta.idiomas || [];
  return receta;
}
const ICONOS = { error: "✕", aviso: "⚠", info: "ℹ" };

const estado = {
  schema: null, sinCondicion: new Set(), yo: null, receta: null, guardada: null,
  tablaId: null, informes: [], hilo: [], recienCambiadas: new Set(), columnas: new Set(), abierta: null, ultimoPreview: 0,
};

const $ = (s) => document.querySelector(s);
const el = (tag, props = {}, ...hijos) => {
  const e = Object.assign(document.createElement(tag), props);
  e.append(...hijos.filter((h) => h !== null && h !== undefined));
  return e;
};

async function api(ruta, opciones = {}) {
  const r = await fetch(ruta, opciones);
  if (r.status === 401) { location.href = "/login"; throw new Error("sin sesión"); }
  if (!r.ok) {
    let detalle = r.statusText;
    try { const j = await r.json(); detalle = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch {}
    throw new Error(detalle);
  }
  return r;
}
const json = (ruta, metodo, cuerpo) => api(ruta, {
  method: metodo, headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo),
}).then((r) => r.json());

function avisar(texto, esError = false) {
  const e = $("#estado");
  e.textContent = texto;
  e.className = esError ? "error" : "tenue";
}

// --- Defaults de una tarjeta nueva, a partir del schema ---

function definicion(tipo) {
  const ref = estado.schema.discriminator.mapping[tipo].split("/").pop();
  return estado.schema.$defs[ref];
}

function tarjetaNueva(tipo) {
  const def = definicion(tipo);
  const t = { id: "t" + Date.now().toString(36) + Math.random().toString(36).slice(2, 5), tipo };
  for (const [campo, p] of Object.entries(def.properties)) {
    if (campo in t || campo === "si") continue;
    if ("default" in p) t[campo] = structuredClone(p.default);
    else if ("const" in p) t[campo] = p.const;
    else if (p.enum) t[campo] = p.enum[0];
    else if (p.anyOf?.some((o) => o.const === "*")) t[campo] = "*";
    else if (p.prefixItems) t[campo] = p.prefixItems.map(() => "");
    else if (p.type === "array") t[campo] = [];
    else if (p.type === "object") t[campo] = {};
    else if (p.type === "integer" || p.type === "number") t[campo] = 0;
    else t[campo] = "";
  }
  return t;
}

// --- Formularios ---

function campoFormulario(tarjeta, campo, p) {
  const etiqueta = ETIQUETAS[campo] || p.title || campo;
  const cambiar = (v) => { tarjeta[campo] = v; cambioReceta(); };
  const opcionesNulas = p.anyOf?.find((o) => o.enum);

  if (p.anyOf?.some((o) => o.const === "*")) return selectorColumnas(etiqueta, tarjeta[campo], cambiar, true);
  if (campo === "columnas") return selectorColumnas(etiqueta, tarjeta[campo], cambiar, false);
  if (p.enum || opcionesNulas) {
    const valores = p.enum || opcionesNulas.enum;
    const sel = el("select", { onchange: () => cambiar(sel.value === "" ? null : sel.value) });
    if (opcionesNulas) sel.append(el("option", { value: "", textContent: "(ninguno)" }));
    for (const v of valores) sel.append(el("option", { value: v, textContent: v, selected: tarjeta[campo] === v }));
    return el("label", {}, etiqueta, sel);
  }
  if (p.type === "boolean") {
    const c = el("input", { type: "checkbox", checked: !!tarjeta[campo], onchange: () => cambiar(c.checked) });
    return el("label", { className: "check" }, c, etiqueta);
  }
  if (p.type === "integer" || p.type === "number") {
    const i = el("input", { type: "number", step: p.type === "number" ? "0.05" : "1", value: tarjeta[campo] ?? "" });
    i.oninput = () => cambiar(i.value === "" ? null : Number(i.value));
    return el("label", {}, etiqueta, i);
  }
  if (p.prefixItems) {
    const valores = tarjeta[campo];
    const inputs = valores.map((v, k) => {
      const i = el("input", { value: v, placeholder: k ? "capítulo" : "programa" });
      i.setAttribute("list", "columnas-conocidas");
      i.oninput = () => { valores[k] = i.value; cambiar(valores); };
      return i;
    });
    return el("label", {}, etiqueta, el("div", { className: "par" }, ...inputs));
  }
  if (p.type === "array") {
    const ta = el("textarea", { rows: 4, value: (tarjeta[campo] || []).join("\n") });
    ta.oninput = () => cambiar(ta.value.split("\n").map((s) => s.trim()).filter(Boolean));
    return el("label", {}, etiqueta, ta);
  }
  if (p.type === "object") return editorMapa(etiqueta, tarjeta[campo], cambiar, tarjeta.tipo === "renombrar");

  const i = el("input", { value: tarjeta[campo] ?? "" });
  if (CAMPOS_DE_COLUMNA.has(campo)) i.setAttribute("list", "columnas-conocidas");
  const anulable = p.anyOf?.some((o) => o.type === "null");
  i.oninput = () => cambiar(anulable && i.value === "" ? null : i.value);
  return el("label", {}, etiqueta, i);
}

function selectorColumnas(etiqueta, valor, cambiar, admiteTodas) {
  const caja = el("div", { className: "opciones-columnas" });
  const elegidas = new Set(Array.isArray(valor) ? valor : []);
  const dibujar = () => {
    caja.replaceChildren();
    if (admiteTodas) {
      const c = el("input", { type: "checkbox", checked: valor === "*" });
      c.onchange = () => { valor = c.checked ? "*" : [...elegidas]; cambiar(valor); dibujar(); };
      caja.append(el("label", { className: "check" }, c, el("b", { textContent: "todas" })));
    }
    if (valor === "*") return;
    const nombres = [...new Set([...estado.columnas, ...elegidas])];
    for (const nombre of nombres) {
      const c = el("input", { type: "checkbox", checked: elegidas.has(nombre) });
      c.onchange = () => {
        c.checked ? elegidas.add(nombre) : elegidas.delete(nombre);
        valor = [...elegidas];
        cambiar(valor);
      };
      caja.append(el("label", { className: "check" }, c, nombre));
    }
    if (!nombres.length) caja.append(el("span", { className: "tenue", textContent: "Subí una grilla para elegir columnas" }));
  };
  dibujar();
  return el("label", {}, etiqueta, caja);
}

function editorMapa(etiqueta, mapa, cambiar, sonColumnas) {
  let filas = Object.entries(mapa || {});
  const caja = el("div");
  const volcar = () => cambiar(Object.fromEntries(filas.filter(([k]) => k !== "")));
  const dibujar = () => {
    caja.replaceChildren();
    filas.forEach((fila, k) => {
      const a = el("input", { value: fila[0], placeholder: sonColumnas ? "columna actual" : "como queda" });
      const b = el("input", { value: fila[1], placeholder: sonColumnas ? "nombre nuevo" : "cómo tiene que quedar" });
      if (sonColumnas) a.setAttribute("list", "columnas-conocidas");
      a.oninput = () => { fila[0] = a.value; volcar(); };
      b.oninput = () => { fila[1] = b.value; volcar(); };
      const x = el("button", { type: "button", className: "chico", textContent: "✕",
        onclick: () => { filas.splice(k, 1); volcar(); dibujar(); } });
      caja.append(el("div", { className: "par" }, a, b, x));
    });
    caja.append(el("button", { type: "button", className: "chico", textContent: "+ par",
      onclick: () => { filas.push(["", ""]); dibujar(); } }));
  };
  dibujar();
  return el("label", {}, etiqueta, caja);
}

function editorCondicion(tarjeta) {
  const activa = !!tarjeta.si;
  const c = el("input", { type: "checkbox", checked: activa });
  const caja = el("div", { className: "par" });
  c.onchange = () => {
    tarjeta.si = c.checked ? { columna: "", op: "contiene", valor: "" } : null;
    cambioReceta();
    dibujarTarjetas();
  };
  if (activa) {
    const col = el("input", { value: tarjeta.si.columna, placeholder: "columna" });
    col.setAttribute("list", "columnas-conocidas");
    col.oninput = () => { tarjeta.si.columna = col.value; cambioReceta(); };
    const op = el("select", { onchange: () => { tarjeta.si.op = op.value; cambioReceta(); } });
    for (const [v, t] of Object.entries(OPERADORES)) op.append(el("option", { value: v, textContent: t, selected: tarjeta.si.op === v }));
    const val = el("input", { value: tarjeta.si.valor, placeholder: "valor o {Otra columna}" });
    val.oninput = () => { tarjeta.si.valor = val.value; cambioReceta(); };
    caja.append(col, op, val);
  }
  return el("div", {}, el("label", { className: "check" }, c, "Solo en las filas donde…"), activa ? caja : null);
}

// --- Lista de tarjetas ---

// Tema de cada tipo de tarjeta: solo para mostrarlas agrupadas, no cambia la receta.
const TEMAS = {
  limpiar_espacios: "Limpieza de texto", reemplazar: "Limpieza de texto", quitar: "Limpieza de texto",
  mayus_minus: "Limpieza de texto", separar: "Separar y extraer", extraer: "Separar y extraer",
  redondear_hora: "Horarios", duracion: "Horarios", dia_semana: "Horarios",
  renombrar: "Columnas y datos", numerar: "Columnas y datos", a_numero: "Columnas y datos",
  asignar: "Columnas y datos", clasificar_sinopsis: "Columnas y datos", correcciones: "Correcciones",
};

// Junta solo tarjetas seguidas del mismo tema: el orden de ejecución no se toca.
function agruparConsecutivas(tarjetas) {
  const grupos = [];
  tarjetas.forEach((t, k) => {
    const tema = TEMAS[t.tipo] || "Otras";
    const ultimo = grupos[grupos.length - 1];
    if (ultimo && ultimo.tema === tema) ultimo.indices.push(k);
    else grupos.push({ tema, indices: [k], clave: `${tema}:${t.id}` });
  });
  return grupos;
}

function claveGruposAbiertos() { return "grupos-abiertos:" + estado.receta.id; }

function leerGruposAbiertos() {
  try { return new Set(JSON.parse(localStorage.getItem(claveGruposAbiertos()) || "[]")); } catch { return new Set(); }
}

function guardarGruposAbiertos(abiertos) {
  try { localStorage.setItem(claveGruposAbiertos(), JSON.stringify([...abiertos])); } catch {}
}

function dibujarTarjetas() {
  const lista = $("#lista-tarjetas");
  lista.replaceChildren();
  const tarjetas = estado.receta.tarjetas;
  const grupos = agruparConsecutivas(tarjetas);
  const abiertos = leerGruposAbiertos();
  $("#res-tarjetas").textContent = tarjetas.length ? `(${tarjetas.length} en ${grupos.length} grupos)` : "";
  for (const g of grupos) {
    const ids = g.indices.map((k) => tarjetas[k].id);
    const conError = ids.some((id) => estado.informes.find((i) => i.id === id)?.error);
    // Se abre solo si tiene un error, la tarjeta en edición o una que acaba de cambiar el asistente.
    if (conError || ids.includes(estado.abierta) || ids.some((id) => estado.recienCambiadas.has(id))) abiertos.add(g.clave);
    const abierto = abiertos.has(g.clave);
    const cabeza = el("div", { className: "cabeza-grupo", onclick: () => {
      const actuales = leerGruposAbiertos();
      actuales.has(g.clave) ? actuales.delete(g.clave) : actuales.add(g.clave);
      guardarGruposAbiertos(actuales);
      dibujarTarjetas();
    } }, el("b", { className: "titulo" }, g.tema, el("span", { className: "detalle" },
      ` · ${g.indices.length} ${g.indices.length === 1 ? "tarjeta" : "tarjetas"}`)), el("span", { className: "insignias" }));
    const grupo = el("li", { className: "grupo" + (abierto ? " abierto" : "") }, cabeza);
    grupo.dataset.ids = ids.join(" ");
    if (abierto) {
      const ol = el("ol", { className: "tarjetas" });
      for (const k of g.indices) ol.append(itemTarjeta(tarjetas[k], k));
      grupo.append(ol);
    }
    lista.append(grupo);
  }
  guardarGruposAbiertos(abiertos);
  estado.recienCambiadas = new Set();
  pintarInformes();
}

function itemTarjeta(t, k) {
  const activa = el("input", { type: "checkbox", checked: t.activa !== false, title: "Activa" });
  activa.onclick = (e) => e.stopPropagation();
  activa.onchange = () => { t.activa = activa.checked; cambioReceta(); dibujarTarjetas(); };
  const borrar = el("button", { className: "chico", textContent: "✕", title: "Borrar" });
  borrar.onclick = (e) => {
    e.stopPropagation();
    if (!confirm(`¿Borrar la tarjeta "${NOMBRES[t.tipo]}"?`)) return;
    estado.receta.tarjetas.splice(k, 1);
    cambioReceta();
    dibujarTarjetas();
  };
  const cabeza = el("div", { className: "cabeza", onclick: () => { estado.abierta = estado.abierta === t.id ? null : t.id; dibujarTarjetas(); } },
    activa,
    el("span", { className: "titulo" }, `${k + 1}. ${NOMBRES[t.tipo] || t.tipo}`, el("span", { className: "nota", textContent: t.nota || resumen(t) })),
    el("span", { className: "insignias" }), borrar);

  const item = el("li", { className: "tarjeta" + (t.activa === false ? " inactiva" : ""), draggable: true },
    cabeza, el("div", { className: "mensajes" }));
  item.dataset.id = t.id;
  if (estado.abierta === t.id) item.append(formularioTarjeta(t));
  habilitarArrastre(item, k);
  return item;
}

// --- Reglas en frases ---

const MODOS_MAYUS = { MAYUS: "MAYÚSCULAS", minus: "minúsculas", Titulo: "Tipo Título", Oracion: "Tipo oración",
  titulo_en: "título en inglés (palabras chicas en minúscula)" };
const PRESETS = { entre_parentesis: "lo que está entre paréntesis", numero: "el número", anio: "el año" };

function columnasEnFrase(c) {
  if (c === "*" || c === undefined) return "todas las columnas";
  return (Array.isArray(c) ? c : [c]).join(", ");
}

function frase(t) {
  const c = (x) => `«${x}»`;
  const texto = {
    limpiar_espacios: () => `Limpia espacios de más y saltos de línea en ${columnasEnFrase(t.columnas)}`,
    reemplazar: () => t.modo === "celda" ? `Si la celda dice exactamente ${c(t.buscar)}, la cambia por ${c(t.por)} (${columnasEnFrase(t.columnas)})`
      : `${t.por ? "Cambia" : "Borra"} ${t.modo === "regex" ? "el patrón " : ""}${c(t.buscar)}${t.por ? ` por ${c(t.por)}` : ""} en ${columnasEnFrase(t.columnas)}`,
    quitar: () => `Saca ${t.regex ? "el patrón " : ""}${c(t.texto)}${{ inicio: " del principio", fin: " del final", todo: "" }[t.donde || "todo"]} de ${columnasEnFrase(t.columnas)}`,
    separar: () => `Parte ${t.columna} en ${t.destinos[0]} y ${t.destinos[1]} ` + ({
      separador: `donde aparece ${c(t.valor)}`, min_mayus: "donde termina una minúscula y empieza una Mayúscula",
      titulos_conocidos: "usando los títulos conocidos de la señal", regex: `con el patrón ${c(t.valor)}` }[t.modo]),
    extraer: () => `Copia ${PRESETS[t.preset] || `el patrón ${c(t.patron)}`} de ${t.columna} a ${t.destino}${t.quitar_del_origen ? " y lo saca del original" : ""}`,
    mayus_minus: () => `Pasa ${columnasEnFrase(t.columnas)} a ${MODOS_MAYUS[t.modo]}`,
    asignar: () => `Pone ${c(t.valor)} en ${t.columna}`,
    a_numero: () => `Pasa ${columnasEnFrase(t.columnas)} a número ("01" → 1)`,
    correcciones: () => `Corrige a mano ${Object.keys(t.mapa || {}).length} textos en ${columnasEnFrase(t.columnas)}`,
    renombrar: () => `Renombra columnas: ${Object.entries(t.mapa || {}).map(([a, b]) => `${a} → ${b}`).join(", ")}`,
    numerar: () => `Numera las filas en ${t.columna || "N"}`,
    redondear_hora: () => `Redondea la hora de ${t.columna} ${(t.a_minutos || 1) > 1 ? `a ${t.a_minutos} minutos` : "al minuto"}`,
    dia_semana: () => `Escribe en ${t.destino || "Dia"} el día de la semana de ${t.columna}`,
    duracion: () => `${t.destino || "Duracion"} = minutos hasta el programa siguiente${t.ultimo_hasta ? ` (el último termina a las ${t.ultimo_hasta})` : ""}`,
    clasificar_sinopsis: () => `Si la sinopsis de ${t.sinopsis} se repite en todos los capítulos va a ${t.destino_programa}; si cambia, a ${t.destino_capitulo}`,
  }[t.tipo];
  let resultado = texto ? texto() : (NOMBRES[t.tipo] || t.tipo);
  if (t.si) resultado += `, solo si ${t.si.columna} ${OPERADORES[t.si.op]}${["vacio", "no_vacio"].includes(t.si.op) ? "" : " " + c(t.si.valor)}`;
  return resultado;
}

function dibujarReglas() {
  if (!estado.receta) return;
  const items = estado.receta.tarjetas.map((t) => {
    const informe = estado.informes.find((i) => i.id === t.id);
    const detalle = informe?.error ? el("span", { className: "insignia error", textContent: informe.error })
      : informe && t.activa !== false ? el("span", { className: "tenue", textContent: ` · ${informe.celdas_cambiadas} celdas` }) : null;
    const activa = el("input", { type: "checkbox", checked: t.activa !== false, title: "Activar o desactivar esta regla",
      onchange: (e) => { t.activa = e.target.checked; cambioReceta(); dibujarTarjetas(); } });
    return el("li", { className: t.activa === false ? "inactiva" : "" },
      el("label", { className: "check" }, activa, el("span", { textContent: frase(t) })), detalle,
      t.nota ? el("div", { className: "tenue nota", textContent: t.nota }) : null,
      estado.yo.admin ? el("button", { className: "enlace", textContent: "editar", onclick: () => {
        estado.abierta = t.id; dibujarTarjetas();
        document.querySelector(`#lista-tarjetas li.tarjeta[data-id="${t.id}"]`)?.scrollIntoView({ block: "center" });
      } }) : null);
  });
  $("#lista-reglas").replaceChildren(...(items.length ? items
    : [el("li", { className: "tenue", textContent: "Esta señal todavía no tiene reglas. Pedile al asistente que las arme." })]));
}

// Actualiza insignias y mensajes sin redibujar los formularios (no se pierde el foco al tipear).
function pintarInformes() {
  for (const grupo of document.querySelectorAll("#lista-tarjetas > li.grupo")) {
    const informes = grupo.dataset.ids.split(" ").map((id) => estado.informes.find((i) => i.id === id)).filter(Boolean);
    const errores = informes.filter((i) => i.error).length;
    const avisos = informes.reduce((n, i) => n + (i.avisos?.length || 0), 0);
    const celdas = informes.reduce((n, i) => n + (i.error ? 0 : i.celdas_cambiadas), 0);
    const insignias = [];
    if (errores) insignias.push(el("span", { className: "insignia error", textContent: `${errores} con error` }));
    if (informes.length) insignias.push(el("span", { className: "insignia", textContent: `${celdas} celdas` }));
    if (avisos) insignias.push(el("span", { className: "insignia aviso", textContent: `${avisos} avisos` }));
    grupo.querySelector(":scope > .cabeza-grupo .insignias").replaceChildren(...insignias);
    grupo.classList.toggle("con-error", errores > 0);
  }
  for (const item of document.querySelectorAll("#lista-tarjetas li.tarjeta")) {
    const t = estado.receta.tarjetas.find((x) => x.id === item.dataset.id);
    const informe = estado.informes.find((i) => i.id === item.dataset.id);
    const insignias = [];
    if (informe?.error) insignias.push(el("span", { className: "insignia error", textContent: "error" }));
    else if (informe && t?.activa !== false) insignias.push(el("span", { className: "insignia", textContent: `${informe.celdas_cambiadas} celdas` }));
    if (informe?.avisos?.length) insignias.push(el("span", { className: "insignia aviso", textContent: `${informe.avisos.length} avisos` }));
    item.querySelector(".insignias").replaceChildren(...insignias);
    item.classList.toggle("con-error", !!informe?.error);
    item.querySelector(".mensajes").replaceChildren(
      ...(informe?.error ? [el("div", { className: "error", textContent: informe.error })] : []),
      ...(informe?.avisos || []).map((a) => el("div", { className: "aviso", textContent: a })));
  }
  dibujarReglas();
}

function resumen(t) {
  const cols = t.columnas === "*" ? "todas las columnas" : (t.columnas || [t.columna]).filter(Boolean).join(", ");
  if (t.tipo === "reemplazar") return `"${t.buscar}" → "${t.por}" en ${cols}`;
  if (t.tipo === "quitar") return `"${t.texto}" en ${cols}`;
  if (t.tipo === "renombrar") return Object.entries(t.mapa).map(([a, b]) => `${a} → ${b}`).join(", ");
  if (t.tipo === "correcciones") return `${Object.keys(t.mapa).length} correcciones en ${cols}`;
  return cols;
}

function formularioTarjeta(t) {
  const def = definicion(t.tipo);
  const form = el("div", { className: "formulario", onclick: (e) => e.stopPropagation() });
  form.draggable = false;
  for (const [campo, p] of Object.entries(def.properties)) {
    if (["id", "tipo", "activa", "si", "nota"].includes(campo) || "const" in p) continue;
    form.append(campoFormulario(t, campo, p));
  }
  if (!estado.sinCondicion.has(t.tipo)) form.append(editorCondicion(t));
  form.append(campoFormulario(t, "nota", def.properties.nota));
  return form;
}

function habilitarArrastre(item, k) {
  item.addEventListener("dragstart", (e) => {
    if (e.target.closest(".formulario")) { e.preventDefault(); return; }
    e.dataTransfer.setData("text/plain", String(k));
    item.classList.add("arrastrando");
  });
  item.addEventListener("dragend", () => item.classList.remove("arrastrando"));
  item.addEventListener("dragover", (e) => e.preventDefault());
  item.addEventListener("drop", (e) => {
    e.preventDefault();
    const desde = Number(e.dataTransfer.getData("text/plain"));
    if (Number.isNaN(desde) || desde === k) return;
    const [t] = estado.receta.tarjetas.splice(desde, 1);
    estado.receta.tarjetas.splice(k, 0, t);
    cambioReceta();
    dibujarTarjetas();
  });
}

// --- Receta: cambios, borrador y guardado ---

let temporizador = null;
function cambioReceta() {
  $("#btn-guardar").disabled = JSON.stringify(estado.receta) === estado.guardada;
  try { localStorage.setItem("borrador:" + estado.receta.id, JSON.stringify(estado.receta)); } catch {}
  clearTimeout(temporizador);
  temporizador = setTimeout(previsualizar, 300);
}

function cargarReceta(receta, guardada, version = null) {
  estado.receta = normalizar(receta);
  $("#btn-exportar-receta").disabled = false;
  estado.guardada = guardada ? JSON.stringify(normalizar(structuredClone(guardada))) : null;
  estado.version = version;
  estado.informes = [];
  estado.abierta = null;
  estado.propuesta = null;
  estado.verPropuesta = false;
  $("#propuesta").hidden = true;
  estado.hilo = [];
  dibujarHilo();
  $("#principal").hidden = false;
  $("#in-hoja").value = receta.entrada.hoja ?? "";
  $("#in-fila").value = receta.entrada.fila_encabezado ?? "";
  $("#in-idioma-ing").checked = receta.idiomas.includes("ing");
  $("#in-idioma-port").checked = receta.idiomas.includes("port");
  $("#in-salida").value = receta.salida.columnas.join("\n");
  const v = receta.validaciones;
  $("#val-fecha").value = v.fecha || "";
  $("#val-hora").value = v.hora || "";
  $("#val-duracion").value = v.duracion || "";
  $("#val-dia").value = v.dia_minutos ?? "";
  $("#val-max").value = v.max_duracion_min ?? "";
  $("#val-tol").value = v.tolerancia_min;
  $("#val-filas").value = v.filas_esperadas ?? "";
  $("#val-huecos").checked = v.huecos;
  $("#val-super").checked = v.superposiciones;
  $("#val-obligatorias").value = v.obligatorias.join("\n");
  $("#val-titulos").checked = v.avisar_titulos_nuevos;
  $("#val-programa").value = v.programa || "";
  $("#tit-resultado").hidden = true;
  $("#tit-buscar").value = "";
  dibujarTitulos();
  $("#panel-validaciones").hidden = true;
  // Señal nueva: entrada y salida abiertas porque hay que configurarlas; si no, plegadas.
  $("#bloque-entrada").open = $("#bloque-salida").open = !guardada;
  resumirEntradaYSalida();
  dibujarTarjetas();
  cambioReceta();
}

function resumirEntradaYSalida() {
  const e = estado.receta.entrada;
  const formatos = { pdf: "PDF", xml: "XML", html: "HTML", texto: "texto" };
  $("#res-entrada").textContent = e.tipo === "excel" ? `hoja ${e.hoja}, encabezado en la fila ${e.fila_encabezado}`
    : `${formatos[e.tipo] || e.tipo}, se lee solo`;
  $("#in-hoja").closest(".fila").hidden = e.tipo !== "excel";
  const n = estado.receta.salida.columnas.length;
  $("#res-salida").textContent = n ? `${n} columnas` : "todas";
}

function enlazarValidaciones() {
  const v = () => estado.receta.validaciones;
  const texto = (id, campo) => { $(id).oninput = (e) => { v()[campo] = e.target.value.trim() || null; cambioReceta(); }; };
  const numero = (id, campo, vacio) => {
    $(id).oninput = (e) => { v()[campo] = e.target.value === "" ? vacio : Number(e.target.value); cambioReceta(); };
  };
  const tilde = (id, campo) => { $(id).onchange = (e) => { v()[campo] = e.target.checked; cambioReceta(); }; };
  texto("#val-fecha", "fecha");
  texto("#val-hora", "hora");
  texto("#val-duracion", "duracion");
  numero("#val-dia", "dia_minutos", null);
  numero("#val-max", "max_duracion_min", null);
  numero("#val-tol", "tolerancia_min", 0);
  numero("#val-filas", "filas_esperadas", null);
  tilde("#val-huecos", "huecos");
  tilde("#val-super", "superposiciones");
  tilde("#val-titulos", "avisar_titulos_nuevos");
  texto("#val-programa", "programa");
  $("#val-obligatorias").oninput = (e) => {
    v().obligatorias = e.target.value.split("\n").map((x) => x.trim()).filter(Boolean);
    cambioReceta();
  };
}

// --- Asistente ---

// `camino` muestra qué modelo está trabajando: "rapido" (charla) o "propuesta" (cambios).
function estadoAsistente(texto, esError = false, camino = "") {
  const e = $("#estado-asistente");
  e.textContent = texto;
  e.className = esError ? "error-asistente" : `tenue ${camino ? "trabajando " + camino : ""}`;
}

// Cada mensaje pasa primero por la charla (modelo rápido); si pide cambios, sigue a la propuesta.
async function enviarMensaje(forzarPropuesta = false) {
  const texto = $("#in-pedido").value.trim();
  if (!texto) { estadoAsistente("Escribí qué querés que haga el asistente", true); return; }
  const previo = estado.hilo.slice();
  agregarAlHilo("persona", texto);
  $("#in-pedido").value = "";
  if (!forzarPropuesta) {
    ocupado(true);
    estadoAsistente("Respondiendo rápido…", false, "rapido");
    try {
      const c = await json("/api/asistente/charla", "POST", { senal: estado.receta, pedido: texto,
        tabla_id: estado.tablaId, historial: previo });
      if (c.respuesta) agregarAlHilo("asistente", c.respuesta);
      estadoAsistente("");
      if (!c.proponer_cambios) return;
    } catch (e) { estadoAsistente(e.message, true); return; } finally { ocupado(false); }
  }
  await pedirAsistente(texto, null, previo);
}

function ocupado(si) { $("#btn-pedir").disabled = $("#btn-proponer").disabled = si; }

function agregarAlHilo(rol, texto) {
  estado.hilo.push({ rol, texto });
  dibujarHilo();
}

function dibujarHilo() {
  const lista = $("#hilo");
  lista.hidden = $("#btn-hilo-nuevo").hidden = !estado.hilo.length;
  lista.replaceChildren(...estado.hilo.map((m) => el("li", { className: m.rol + (m.texto.startsWith("(") ? " nota" : ""),
    textContent: m.texto })));
  lista.scrollTop = lista.scrollHeight;
}

async function pedirAsistente(pedido, ejemplo = null, historial = []) {
  if (!pedido.trim()) { estadoAsistente("Escribí qué querés que haga el asistente", true); return; }
  if (!ejemplo && !estado.tablaId) { estadoAsistente("Subí una grilla para que el asistente pueda armar una propuesta", true); return; }
  ocupado(true);
  estadoAsistente("Armando una propuesta y probándola contra la grilla… (puede tardar un minuto)", false, "propuesta");
  avisar("El asistente está trabajando…");
  try {
    const p = await json("/api/asistente", "POST", { senal: estado.receta, pedido, tabla_id: estado.tablaId, ejemplo, historial });
    estado.propuesta = p;
    estado.verPropuesta = false;
    dibujarPropuesta();
    if (ejemplo) agregarAlHilo("persona", pedido);
    agregarAlHilo("asistente", p.explicacion || (p.receta ? "Te dejo una propuesta abajo." : "No llegué a una propuesta válida."));
    estadoAsistente("");
    avisar("");
    if (ejemplo) mostrarPestana("tabla");
  } catch (e) {
    estadoAsistente(e.message, true);
    avisar("");
    if (ejemplo) avisar(e.message, true);  // pedido desde la pestaña Ejemplos: el cuadro del asistente no se ve
  } finally { ocupado(false); }
}

function dibujarPropuesta() {
  const p = estado.propuesta;
  const caja = $("#propuesta");
  caja.hidden = !p;
  if (!p) return;
  caja.className = "propuesta" + (p.logrado ? "" : " fallida");
  const hijos = [];
  if (!p.logrado) {
    hijos.push(el("p", {}, el("b", { textContent: `No lo logró del todo (${p.vueltas} intentos). ` }),
      p.receta ? "Te muestro el último intento; revisalo antes de aplicarlo." : "No llegó a una propuesta válida."));
  }
  if (p.explicacion) hijos.push(el("p", { textContent: p.explicacion }));
  if (p.cambios.length) hijos.push(el("ul", {}, ...p.cambios.map(lineaCambio)));
  else if (p.receta) hijos.push(el("p", { className: "tenue", textContent: "No cambia ninguna tarjeta." }));
  if (p.despues) hijos.push(dibujarMetricas(p.antes, p.despues));
  if (p.problemas.length) {
    hijos.push(el("details", {}, el("summary", { textContent: `Problemas que quedaron (${p.problemas.length})` }),
      el("ul", {}, ...p.problemas.map((x) => el("li", { textContent: x })))));
  }
  const botones = el("div", { className: "fila" });
  if (p.receta) {
    botones.append(
      el("button", { textContent: estado.verPropuesta ? "Ver la receta actual" : "Ver en la tabla", onclick: () => {
        estado.verPropuesta = !estado.verPropuesta; dibujarPropuesta(); previsualizar(); } }),
      el("button", { className: "primario", textContent: "Aplicar", onclick: aplicarPropuesta }));
  }
  botones.append(el("button", { textContent: "Descartar", onclick: () => {
    estado.propuesta = null; estado.verPropuesta = false; dibujarPropuesta(); previsualizar();
    agregarAlHilo("asistente", "(Propuesta descartada)"); } }));
  hijos.push(botones);
  caja.replaceChildren(...hijos);
}

function lineaCambio(c) {
  if (c.tipo === "salida") return el("li", { textContent: `Columnas de salida: ${c.columnas.join(", ") || "todas"}` });
  if (c.tipo === "orden") return el("li", { textContent: "Cambia el orden de las tarjetas" });
  const signo = { agregada: "+", modificada: "~", borrada: "−" }[c.tipo];
  const detalle = c.tipo === "modificada" ? ` (cambia ${c.campos.join(", ")})` : "";
  return el("li", { className: c.tipo },
    `${signo} ${NOMBRES[c.tarjeta.tipo] || c.tarjeta.tipo}: ${c.tarjeta.nota || resumen(c.tarjeta)}${detalle}`);
}

function dibujarMetricas(antes, despues) {
  const comparar = (a, b, menosEsMejor) => {
    const clase = a === b ? "" : (b < a) === menosEsMejor ? "mejor" : "peor";
    return el("b", { className: clase, textContent: a === b ? `${b}` : `${a} → ${b}` });
  };
  const lineas = [el("div", {}, "Errores de tarjetas: ", comparar(antes.errores_tarjetas, despues.errores_tarjetas, true),
    " · Validaciones con error: ", comparar(antes.validaciones.error, despues.validaciones.error, true))];
  for (const [nombre, pct] of Object.entries(despues.ejemplos)) {
    lineas.push(el("div", {}, `Ejemplo ${nombre}: `, comparar(antes.ejemplos[nombre], pct, false), " %"));
  }
  return el("div", { className: "metricas" }, ...lineas);
}

function aplicarPropuesta() {
  const r = estado.propuesta.receta;
  estado.recienCambiadas = new Set(estado.propuesta.cambios.filter((c) => c.id).map((c) => c.id));
  estado.receta.tarjetas = r.tarjetas;
  estado.receta.salida = r.salida;
  $("#in-salida").value = r.salida.columnas.join("\n");
  resumirEntradaYSalida();
  estado.propuesta = null;
  estado.verPropuesta = false;
  dibujarPropuesta();
  dibujarTarjetas();
  cambioReceta();
  agregarAlHilo("asistente", "(Propuesta aplicada)");
  avisar("Propuesta aplicada. Tocá Guardar para que quede para todos.");
}

async function mostrarUsoAsistente() {
  try {
    const u = await api("/api/asistente/uso").then((r) => r.json());
    const caja = $("#uso-asistente");
    if (!u.configurado) { caja.textContent = "El asistente no está configurado (falta ANTHROPIC_API_KEY en el servidor)."; return; }
    caja.replaceChildren(el("p", { textContent: `Tope: ${u.limite_diario} pedidos por persona por día.` }),
      ...(u.usuarios.length ? u.usuarios.map((x) => el("div", { textContent:
        `${x.usuario}: ${x.pedidos} pedidos (${x.logrados} logrados) · ${x.tokens_entrada.toLocaleString("es-AR")} tokens de entrada, ${x.tokens_salida.toLocaleString("es-AR")} de salida` }))
        : [el("p", { textContent: "Todavía nadie lo usó este mes." })]));
  } catch (e) { avisar(e.message, true); }
}

// --- Títulos conocidos ---

let titulosAprendidos = [];

function dibujarTitulos() {
  const lista = estado.receta.titulos_conocidos;
  $("#cant-titulos").textContent = `(${lista.length})`;
  const filtro = $("#tit-buscar").value.trim().toLowerCase();
  const ta = $("#tit-texto");
  ta.value = (filtro ? lista.filter((t) => t.toLowerCase().includes(filtro)) : lista).join("\n");
  ta.readOnly = !!filtro;  // con filtro se ve una parte: editar ahí borraría lo que no se ve
  ta.title = filtro ? "Borrá la búsqueda para editar la lista" : "";
}

async function aprenderTitulos(archivos) {
  const datos = new FormData();
  datos.append("columna", $("#tit-columna").value.trim());
  datos.append("usar_ejemplos", archivos ? "false" : "true");
  datos.append("conocidos", JSON.stringify(estado.receta.titulos_conocidos));
  for (const a of archivos || []) datos.append("archivos", a);
  avisar("Leyendo títulos…");
  try {
    const r = await api(`/api/senales/${estado.receta.id}/titulos/aprender`, { method: "POST", body: datos }).then((x) => x.json());
    titulosAprendidos = r.titulos.map((t) => ({ ...t, elegido: t.nuevo }));
    const nuevos = r.titulos.filter((t) => t.nuevo).length;
    $("#tit-resumen").textContent = `${r.titulos.length} títulos en la columna ${r.columna_usada}, ${nuevos} nuevos.`;
    $("#tit-resultado").hidden = false;
    dibujarAprendidos();
    avisar("");
  } catch (e) { avisar(e.message, true); }
}

function dibujarAprendidos() {
  $("#tit-lista").replaceChildren(...titulosAprendidos.map((t) => {
    const c = el("input", { type: "checkbox", checked: t.elegido, onchange: () => { t.elegido = c.checked; } });
    return el("li", {}, el("label", { className: "check" }, c, t.nuevo ? el("b", { textContent: t.titulo }) : t.titulo,
      el("span", { className: "veces", textContent: ` ×${t.apariciones}` + (t.nuevo ? " · nuevo" : "") })));
  }));
}

function enlazarTitulos() {
  $("#btn-tit-ejemplos").onclick = () => aprenderTitulos(null);
  $("#tit-archivos").onchange = (e) => { if (e.target.files.length) aprenderTitulos([...e.target.files]); e.target.value = ""; };
  $("#btn-tit-nuevos").onclick = () => { titulosAprendidos.forEach((t) => { t.elegido = t.nuevo; }); dibujarAprendidos(); };
  $("#btn-tit-ninguno").onclick = () => { titulosAprendidos.forEach((t) => { t.elegido = false; }); dibujarAprendidos(); };
  $("#btn-tit-agregar").onclick = () => {
    const lista = estado.receta.titulos_conocidos;
    const ya = new Set(lista);
    const agregar = titulosAprendidos.filter((t) => t.elegido && !ya.has(t.titulo)).map((t) => t.titulo);
    lista.push(...agregar);
    lista.sort((a, b) => a.localeCompare(b));
    $("#tit-resultado").hidden = true;
    avisar(`${agregar.length} títulos agregados. Tocá Guardar para que queden en la señal.`);
    dibujarTitulos();
    cambioReceta();
  };
  $("#tit-buscar").oninput = dibujarTitulos;
  $("#tit-texto").oninput = (e) => {
    estado.receta.titulos_conocidos = [...new Set(e.target.value.split("\n").map((t) => t.trim()).filter(Boolean))];
    $("#cant-titulos").textContent = `(${estado.receta.titulos_conocidos.length})`;
    cambioReceta();
  };
}

function pintarValidaciones(r) {
  const avisos = r.validaciones;
  const n = r.resumen_validaciones;
  const cols = r.columnas_validadas;
  $("#cols-validadas").textContent = cols.fecha && cols.hora && cols.duracion
    ? `usa ${cols.fecha} · ${cols.hora} · ${cols.duracion}` : "faltan columnas";
  const panel = $("#panel-validaciones");
  panel.hidden = false;
  const contadores = [];
  if (n.error) contadores.push(el("span", { className: "contador error", textContent: `✕ ${n.error} errores` }));
  if (n.aviso) contadores.push(el("span", { className: "contador aviso", textContent: `⚠ ${n.aviso} avisos` }));
  if (!n.error && !n.aviso) contadores.push(el("span", { className: "contador ok", textContent: "✓ Sin errores ni avisos" }));
  if (n.info) contadores.push(el("span", { className: "tenue", textContent: `${n.info} notas` }));
  $("#resumen-validaciones").replaceChildren(el("b", { textContent: "Validaciones" }), ...contadores);
  if (n.error) panel.open = true;
  $("#lista-validaciones").replaceChildren(...avisos.map((a) => {
    const li = el("li", { className: a.nivel },
      el("span", { className: "icono", textContent: ICONOS[a.nivel] + " " }),
      a.fila ? el("b", { textContent: `Fila ${a.fila}: ` }) : null, a.mensaje);
    if (a.fila) {
      li.dataset.fila = a.fila;
      li.onclick = () => irAFila(a.fila);
    }
    return li;
  }));
}

function irAFila(fila) {
  const tr = document.querySelector(`#tabla tbody tr[data-fila="${fila}"]`);
  if (!tr) { avisar(`La fila ${fila} está fuera de las filas visibles`); return; }
  document.querySelectorAll("#tabla tr.resaltada").forEach((x) => x.classList.remove("resaltada"));
  tr.classList.add("resaltada");
  tr.scrollIntoView({ block: "center" });
}

async function abrirSenal(id) {
  const r = await api(`/api/senales/${id}`);
  const version = r.headers.get("ETag");
  const guardada = await r.json();
  let receta = structuredClone(guardada);
  try {
    const borrador = localStorage.getItem("borrador:" + id);
    const textoGuardado = JSON.stringify(normalizar(structuredClone(guardada)));
    if (borrador && borrador !== textoGuardado && confirm("Hay cambios sin guardar de la última vez. ¿Recuperarlos?")) {
      receta = JSON.parse(borrador);
    }
  } catch {}
  cargarReceta(receta, guardada, version);
  try { localStorage.setItem("ultima-senal", id); } catch {}
  $("#resultados-ejemplos").replaceChildren();
  if (!$("#vista-base").hidden) listarBase();
}

// --- Importar / exportar receta ---

function exportarReceta() {
  const texto = JSON.stringify(estado.receta, null, 2);
  const url = URL.createObjectURL(new Blob([texto], { type: "application/json" }));
  el("a", { href: url, download: `receta_${estado.receta.id}.json` }).click();
  URL.revokeObjectURL(url);
}

async function importarReceta(archivo) {
  let datos;
  try { datos = JSON.parse(await archivo.text()); } catch { avisar("El archivo no es un JSON válido", true); return; }
  const r = await json("/api/senales/validar", "POST", datos);
  if (!r.ok) { avisar("La receta tiene errores: " + r.errores.join("; "), true); return; }
  const receta = r.receta;
  const existe = [...$("#sel-senal").options].some((o) => o.value === receta.id);
  if (existe) {
    if (!confirm(`Ya existe la señal "${receta.nombre}". ¿Reemplazar su receta? Queda como borrador hasta que toques Guardar.`)) return;
    await abrirSenal(receta.id);
    const version = estado.version;
    const guardada = JSON.parse(estado.guardada);
    cargarReceta(receta, guardada, version);
  } else {
    cargarReceta(receta, null);
  }
  avisar(`Receta "${receta.nombre}" importada. Tocá Guardar para que quede para todos.`);
}

async function listarSenales(elegir) {
  const senales = await api("/api/senales").then((r) => r.json());
  const sel = $("#sel-senal");
  sel.replaceChildren(el("option", { value: "", textContent: senales.length ? "Elegí una señal…" : "Sin señales: creá una" }));
  for (const s of senales) sel.append(el("option", { value: s.id, textContent: s.nombre, selected: s.id === elegir }));
}

async function guardar(forzar = false) {
  try {
    const cabeceras = { "Content-Type": "application/json" };
    if (estado.version && !forzar) cabeceras["If-Match"] = estado.version;
    const r = await fetch(`/api/senales/${estado.receta.id}`, {
      method: "PUT", headers: cabeceras, body: JSON.stringify(estado.receta) });
    if (r.status === 409) {
      const { detail } = await r.json();
      if (confirm(`${detail}.\n\nAceptar: guardar igual y pisar esos cambios.\nCancelar: recargar la señal (lo tuyo queda como borrador).`)) {
        return guardar(true);
      }
      return abrirSenal(estado.receta.id);
    }
    if (r.status === 401) { location.href = "/login"; return; }
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    estado.version = r.headers.get("ETag");
    estado.guardada = JSON.stringify(estado.receta);
    try { localStorage.removeItem("borrador:" + estado.receta.id); } catch {}
    $("#btn-guardar").disabled = true;
    avisar("Guardado");
    await listarSenales(estado.receta.id);
  } catch (e) { avisar("No se pudo guardar: " + e.message, true); }
}

// --- Vista previa ---

async function previsualizar() {
  if (!estado.tablaId || !estado.receta) return;
  const turno = ++estado.ultimoPreview;
  const receta = estado.verPropuesta && estado.propuesta?.receta ? estado.propuesta.receta : estado.receta;
  try {
    const r = await json("/api/preview", "POST", { tabla_id: estado.tablaId, senal: receta,
      solo_nuevas: $("#sel-filtro-pautas").value === "nuevas" });
    if (turno !== estado.ultimoPreview) return;  // llegó una respuesta vieja
    estado.vista = r;
    estado.informes = r.tarjetas;
    for (const i of r.tarjetas) i.columnas.forEach((c) => estado.columnas.add(c));
    r.columnas.forEach((c) => estado.columnas.add(c));
    actualizarColumnasConocidas();
    dibujarTabla(r);
    pintarValidaciones(r);
    pintarResumenPautas(r);
    $("#resumen").replaceChildren(`${r.total_filas} filas` + (r.total_filas > r.filas.length ? ` (se muestran ${r.filas.length})` : ""),
      estado.verPropuesta ? el("span", { className: "vista-propuesta", textContent: " · mostrando la propuesta del asistente" }) : "");
    pintarInformes();
    const grupoConErrorCerrado = [...document.querySelectorAll("#lista-tarjetas > li.grupo.con-error:not(.abierto)")].length;
    if (grupoConErrorCerrado && !document.activeElement?.closest(".formulario")) dibujarTarjetas();
    if ($("#estado").classList.contains("error")) avisar("");  // los mensajes informativos quedan
  } catch (e) {
    if (turno === estado.ultimoPreview) avisar(e.message, true);
  }
}

function actualizarColumnasConocidas() {
  $("#columnas-conocidas").replaceChildren(...[...estado.columnas].map((c) => el("option", { value: c })));
}

const ESTADOS_PAUTA = {
  conocida: { icono: "✔", texto: "Conocida: sale de la base" },
  editada: { icono: "✎", texto: "Editada a mano: sale de la base" },
  nueva: { icono: "●", texto: "Nueva: la arman las reglas, falta revisarla" },
};

function dibujarTabla(r) {
  const { columnas, filas, indices } = r;
  const avisos = r.validaciones || [];
  const editables = new Set(r.contenido);
  const nivelPorFila = {};
  for (const a of avisos) {
    if (!a.fila || a.nivel === "info") continue;
    if (a.nivel === "error" || !nivelPorFila[a.fila]) nivelPorFila[a.fila] = a.nivel;
  }
  // Celdas que no cumplen el catálogo: se marcan y el motivo aparece al pasar el mouse.
  const porCelda = {};
  for (const a of avisos) if (a.fila && a.columna) porCelda[`${a.fila}|${a.columna}`] = a.mensaje;
  const cabeza = el("tr", {}, el("th", { textContent: "#" }), el("th", { title: "Estado de la pauta", textContent: "" }),
    ...columnas.map((c) => el("th", { textContent: c })));
  const cuerpo = filas.map((f, k) => {
    const n = indices[k] + 1;  // número de fila en la grilla completa
    const est = ESTADOS_PAUTA[r.estados[k]];
    const tr = el("tr", { className: nivelPorFila[n] ? `fila-${nivelPorFila[n]}` : "" },
      el("td", { className: "num", textContent: n }),
      el("td", { className: `estado-pauta ${r.estados[k]}`, textContent: est.icono, title: est.texto }),
      ...f.map((v, j) => {
        const td = celda(v, porCelda[`${n}|${columnas[j]}`]);
        if (editables.has(columnas[j])) {
          td.classList.add("editable");
          td.ondblclick = () => editarCelda(td, v, (valor) => json(`/api/senales/${estado.receta.id}/pautas/editar-celda`, "POST", {
            tabla_id: estado.tablaId, senal: estado.receta, fila: indices[k], columna: columnas[j], valor }));
        }
        return td;
      }));
    tr.dataset.fila = n;
    return tr;
  });
  $("#tabla").replaceChildren(el("thead", {}, cabeza), el("tbody", {}, ...cuerpo));
}

function celda(v, motivo) {
  const props = v === null || v === "" ? { className: "vacia", textContent: "—" } : { textContent: v, title: v };
  if (motivo) Object.assign(props, { className: "celda-error", title: motivo });
  return el("td", props);
}

// Edición en el lugar: Enter guarda, Escape (o salir de la celda) cancela.
function editarCelda(td, valor, guardarValor) {
  if (td.querySelector("input")) return;
  const entrada = el("input", { className: "edicion", value: valor ?? "" });
  td.replaceChildren(entrada);
  entrada.focus();
  entrada.select();
  let terminado = false;
  const cancelar = () => { if (!terminado) { terminado = true; td.replaceChildren(valor ?? "—"); } };
  entrada.onblur = cancelar;
  entrada.onkeydown = async (e) => {
    if (e.key === "Escape") cancelar();
    if (e.key !== "Enter") return;
    terminado = true;
    entrada.disabled = true;
    try {
      await guardarValor(entrada.value);
      avisar("Guardado en la base de pautas");
      previsualizar();
      if (!$("#vista-base").hidden) listarBase();
    } catch (err) { avisar(err.message, true); td.replaceChildren(valor ?? "—"); }
  };
}

function pintarResumenPautas(r) {
  const n = r.resumen_pautas;
  estado.pautasNuevas = n.nueva;
  $("#barra-pautas").hidden = false;
  $("#resumen-pautas").replaceChildren(
    el("span", { className: "contador ok", textContent: `✔ ${n.conocida} conocidas` }), " · ",
    el("span", { className: "contador", textContent: `✎ ${n.editada} editadas` }), " · ",
    el("span", { className: "contador" + (n.nueva ? " aviso" : ""), textContent: `● ${n.nueva} nuevas` }));
  $("#btn-revisar").disabled = !n.nueva;
}

async function revisarNuevas() {
  if (!confirm(`Se guardan en la base las ${estado.pautasNuevas} filas nuevas tal como las armaron las reglas. ¿Seguir?`)) return;
  try {
    const r = await json(`/api/senales/${estado.receta.id}/pautas/revisar`, "POST", { tabla_id: estado.tablaId, senal: estado.receta });
    avisar(`${r.revisadas} pautas guardadas como revisadas`);
    previsualizar();
  } catch (e) { avisar(e.message, true); }
}

async function subirGrilla(archivo) {
  const datos = new FormData();
  datos.append("archivo", archivo);
  avisar("Subiendo…");
  try {
    const r = await api("/api/tablas", { method: "POST", body: datos }).then((x) => x.json());
    estado.tablaId = r.tabla_id;
    $("#nombre-archivo").textContent = r.nombre;
    $("#btn-xlsx").disabled = $("#btn-csv").disabled = false;
    // Una señal que venía en Excel y ahora llega en PDF (o al revés) pasa a leerse en el formato nuevo.
    if (r.entrada.tipo !== estado.receta.entrada.tipo) {
      estado.receta.entrada = r.entrada;
      resumirEntradaYSalida();
      cambioReceta();
    }
    avisar("");
    previsualizar();
  } catch (e) { avisar(e.message, true); }
}

async function exportar(formato) {
  if (estado.pautasNuevas && !confirm(`Hay ${estado.pautasNuevas} pautas nuevas sin revisar. ¿Exportar igual?`)) return;
  try {
    const r = await api("/api/export", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tabla_id: estado.tablaId, senal: estado.receta, formato }) });
    const nombre = /filename="([^"]+)"/.exec(r.headers.get("Content-Disposition") || "")?.[1] || `epg.${formato}`;
    const url = URL.createObjectURL(await r.blob());
    el("a", { href: url, download: nombre }).click();
    URL.revokeObjectURL(url);
  } catch (e) { avisar(e.message, true); }
}

// --- Ejemplos ---

async function evaluarEjemplos() {
  const caja = $("#resultados-ejemplos");
  caja.replaceChildren(el("p", { className: "tenue", textContent: "Probando…" }));
  try {
    const resultados = await json(`/api/senales/${estado.receta.id}/ejemplos/evaluar`, "POST", estado.receta);
    caja.replaceChildren();
    if (!resultados.length) caja.append(el("p", { className: "tenue", textContent: "Esta señal todavía no tiene ejemplos." }));
    for (const r of resultados) caja.append(dibujarEjemplo(r));
  } catch (e) { caja.replaceChildren(el("p", { className: "error", textContent: e.message })); }
}

function dibujarEjemplo(r) {
  const borrar = el("button", { className: "chico", textContent: "Borrar ejemplo", onclick: async () => {
    if (!confirm(`¿Borrar el ejemplo ${r.nombre}?`)) return;
    await api(`/api/senales/${estado.receta.id}/ejemplos/${r.nombre}`, { method: "DELETE" });
    evaluarEjemplos();
  } });
  if (r.error) return el("div", { className: "ejemplo" }, el("h3", {}, r.nombre, borrar), el("p", { className: "error", textContent: r.error }));

  const titulo = el("h3", {},
    el("span", { className: "porcentaje" + (r.total_diferencias === 0 ? " completo" : ""), textContent: `${r.porcentaje} %` }),
    r.nombre, el("span", { className: "tenue", textContent: `${r.filas[0]} filas (esperadas ${r.filas[1]}) · ${r.total_diferencias} diferencias`
      + ` · validaciones: ${r.resumen_validaciones.error} errores, ${r.resumen_validaciones.aviso} avisos` }),
    el("span", { className: "espacio" }),
    r.total_diferencias ? el("button", { className: "chico", textContent: "Armar desde este ejemplo",
      title: "El asistente ajusta las tarjetas para que esta grilla quede igual al EPG terminado",
      onclick: () => pedirAsistente("Ajustá las tarjetas para que la grilla de entrada de este ejemplo quede igual al EPG esperado.", r.nombre) }) : null,
    borrar);
  const bloque = el("div", { className: "ejemplo" }, titulo);

  const cantidad = Object.values(r.correcciones).reduce((n, m) => n + Object.keys(m).length, 0);
  if (cantidad) {
    bloque.append(el("div", { className: "fila" },
      el("span", { textContent: `${cantidad} correcciones sugeridas a partir de este ejemplo.` }),
      el("button", { textContent: "Agregar a la tarjeta de correcciones", onclick: () => agregarCorrecciones(r.correcciones) })));
  }
  if (r.diferencias.length) {
    const filas = r.diferencias.map((d) => el("tr", {}, el("td", { className: "num", textContent: d.fila + 1 }),
      el("td", { textContent: d.columna }), el("td", {}, el("span", { className: "quedo", textContent: d.obtenido ?? "—" })),
      el("td", {}, el("span", { className: "esperado", textContent: d.esperado ?? "—" }))));
    bloque.append(el("div", { className: "contenedor-tabla" }, el("table", {},
      el("thead", {}, el("tr", {}, ...["Fila", "Columna", "Quedó", "Tenía que quedar"].map((t) => el("th", { textContent: t })))),
      el("tbody", {}, ...filas))));
    if (r.total_diferencias > r.diferencias.length) bloque.append(el("p", { className: "tenue", textContent: `Se muestran las primeras ${r.diferencias.length}.` }));
  }
  return bloque;
}

function agregarCorrecciones(porColumna) {
  for (const [columna, mapa] of Object.entries(porColumna)) {
    let t = estado.receta.tarjetas.find((x) => x.tipo === "correcciones" && Array.isArray(x.columnas)
      && x.columnas.length === 1 && x.columnas[0] === columna);
    if (!t) {
      t = { ...tarjetaNueva("correcciones"), columnas: [columna], mapa: {}, nota: `Correcciones de ${columna}` };
      estado.receta.tarjetas.push(t);
    }
    Object.assign(t.mapa, mapa);
  }
  cambioReceta();
  dibujarTarjetas();
  evaluarEjemplos();
}

async function subirEjemplo(e) {
  e.preventDefault();
  try {
    const r = await api(`/api/senales/${estado.receta.id}/ejemplos`, { method: "POST", body: new FormData(e.target) })
      .then((x) => x.json());
    e.target.reset();
    if (r.pautas?.error) avisar(r.pautas.error, true);
    else if (r.pautas) avisar(`Ejemplo agregado: ${r.pautas.agregadas} pautas nuevas en la base`);
    evaluarEjemplos();
    previsualizar();
  } catch (err) { avisar(err.message, true); }
}

// --- Nueva señal ---

function enlazarNuevaSenal() {
  const dialogo = $("#dialogo-senal");
  const error = $("#error-senal");
  $("#btn-nueva").onclick = () => { $("#form-senal").reset(); error.hidden = true; dialogo.showModal(); };
  $("#btn-senal-cancelar").onclick = () => dialogo.close();
  $("#form-senal").onsubmit = async (e) => {
    e.preventDefault();
    const datos = new FormData(e.target);
    error.hidden = true;
    let r = await fetch("/api/senales/crear", { method: "POST", body: datos });
    if (r.status === 409) {
      const { detail } = await r.json();
      const eleccion = await elegirParecida(detail);
      if (!eleccion) return;
      datos.append(...(eleccion === "crear" ? ["confirmar", "true"] : ["agregar_a", eleccion]));
      r = await fetch("/api/senales/crear", { method: "POST", body: datos });
    }
    if (r.status === 401) { location.href = "/login"; return; }
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      error.textContent = typeof j.detail === "string" ? j.detail : "No se pudo crear la señal";
      error.hidden = false;
      return;
    }
    const creada = await r.json();
    dialogo.close();
    await listarSenales(creada.id);
    await abrirSenal(creada.id);
    estado.tablaId = creada.tabla_id;
    $("#nombre-archivo").textContent = datos.get("grilla_cruda").name;
    $("#btn-xlsx").disabled = $("#btn-csv").disabled = false;
    previsualizar();
    const base = creada.pautas?.agregadas ? ` La base arrancó con ${creada.pautas.agregadas} pautas.` : "";
    avisar(`Señal "${creada.nombre}" lista, con su ejemplo cargado.${base}`);
  };
}

// Cartel de verificación cuando ya hay señales con ese nombre o uno parecido.
// Devuelve "crear", el id de la señal a la que se suma el ejemplo, o null si se cancela.
function elegirParecida(detalle) {
  const dialogo = $("#dialogo-parecidas");
  $("#parecidas-titulo").textContent = detalle.mensaje;
  $("#btn-parecidas-crear").hidden = detalle.identica;
  return new Promise((resolver) => {
    const terminar = (valor) => { dialogo.onclose = null; dialogo.close(); resolver(valor); };
    $("#parecidas-lista").replaceChildren(...detalle.parecidas.map((s) => el("li", {},
      el("b", { textContent: s.nombre }), el("span", { className: "espacio" }),
      el("button", { type: "button", textContent: "Agregar como ejemplo de esta", onclick: () => terminar(s.id) }))));
    $("#btn-parecidas-crear").onclick = () => terminar("crear");
    $("#btn-parecidas-cancelar").onclick = () => terminar(null);
    dialogo.onclose = () => resolver(null);  // Escape
    dialogo.showModal();
  });
}

// --- Base de pautas ---

async function listarBase(mas = false) {
  if (!estado.receta) return;
  const desde = mas ? estado.base.pautas.length : 0;
  const params = new URLSearchParams({ q: $("#base-buscar").value, estado: $("#base-estado").value, desde });
  try {
    const r = await api(`/api/senales/${estado.receta.id}/pautas?${params}`).then((x) => x.json());
    estado.base = mas ? { ...r, pautas: [...estado.base.pautas, ...r.pautas] } : r;
    dibujarBase();
  } catch (e) { avisar(e.message, true); }
}

function dibujarBase() {
  const { pautas, total, por_estado: n } = estado.base;
  $("#base-resumen").textContent = `${total} pautas · ${n.revisada || 0} revisadas · ${n.editada || 0} editadas`;
  $("#btn-base-mas").hidden = pautas.length >= total;
  const columnas = [...new Set(pautas.flatMap((p) => Object.keys(p.salida)))];
  const cabeza = el("tr", {}, el("th", { textContent: "" }), el("th", { textContent: "Como viene en la grilla" }),
    ...columnas.map((c) => el("th", { textContent: c })), el("th", { textContent: "Por" }), el("th", { textContent: "" }));
  const filas = pautas.map((p) => {
    const est = ESTADOS_PAUTA[p.estado === "editada" ? "editada" : "conocida"];
    const crudo = Object.values(p.crudo).filter((v) => v !== null && v !== "").join(" · ");
    return el("tr", {},
      el("td", { className: `estado-pauta ${p.estado === "editada" ? "editada" : "conocida"}`, textContent: est.icono, title: est.texto }),
      el("td", { className: "crudo", textContent: crudo, title: crudo }),
      ...columnas.map((c) => {
        const td = celda(p.salida[c] ?? null);
        td.classList.add("editable");
        td.ondblclick = () => editarCelda(td, p.salida[c], (valor) => json(
          `/api/senales/${estado.receta.id}/pautas/${p.hash}`, "PUT", { salida: { ...p.salida, [c]: valor.trim() || null } }));
        return td;
      }),
      el("td", { className: "tenue", textContent: p.usuario, title: p.actualizado }),
      el("td", {}, el("button", { className: "chico", textContent: "Olvidar", title: "La próxima vez esta fila vuelve a salir como nueva",
        onclick: async () => {
          await api(`/api/senales/${estado.receta.id}/pautas/${p.hash}`, { method: "DELETE" });
          listarBase();
          previsualizar();
        } })));
  });
  if (!pautas.length) filas.push(el("tr", {}, el("td", { colSpan: 3, className: "tenue",
    textContent: "No hay pautas. Se cargan solas con los ejemplos o con «Marcar nuevas como revisadas»." })));
  $("#tabla-base").replaceChildren(el("thead", {}, cabeza), el("tbody", {}, ...filas));
}

async function cargarBaseDeEjemplos() {
  try {
    const r = await json(`/api/senales/${estado.receta.id}/pautas/desde-ejemplos`, "POST", {});
    const extra = r.conflictos ? ` (${r.conflictos} filas iguales con salidas distintas: quedó la primera)` : "";
    avisar(`${r.agregadas} pautas nuevas desde los ejemplos${extra}` + (r.errores.length ? `. Errores: ${r.errores.join("; ")}` : ""),
      r.errores.length > 0);
    listarBase();
    previsualizar();
  } catch (e) { avisar(e.message, true); }
}

// --- Catálogo (admin) ---

const TIPOS_CATALOGO = { texto: "texto", entero: "número entero", anio: "año", valores: "valores fijos", fecha: "fecha", hora: "hora" };

async function listarCatalogo() {
  const columnas = await api("/api/catalogo").then((r) => r.json());
  $("#res-catalogo").textContent = columnas.length ? `${columnas.length} columnas cargadas` : "Todavía no hay catálogo cargado.";
  const obligatoria = { si: "sí", ing: "si lleva inglés", port: "si lleva portugués", no: "" };
  const regla = (c) => c.tipo === "valores" ? c.valores.join(" · ")
    : c.maximo ? `${TIPOS_CATALOGO[c.tipo]} (máx. ${c.maximo})` : TIPOS_CATALOGO[c.tipo];
  $("#tabla-catalogo").replaceChildren(
    el("thead", {}, el("tr", {}, ...["#", "Columna", "Regla", "Obligatoria", "Significado"].map((t) => el("th", { textContent: t })))),
    el("tbody", {}, ...columnas.map((c, i) => el("tr", {}, el("td", { className: "num", textContent: i + 1 }),
      el("td", { textContent: c.nombre }), el("td", { textContent: regla(c) }),
      el("td", { textContent: obligatoria[c.obligatoria] }), el("td", { textContent: c.significado })))));
}

async function subirCatalogo(archivo) {
  const datos = new FormData();
  datos.append("archivo", archivo);
  try {
    await api("/api/catalogo", { method: "POST", body: datos });
    await listarCatalogo();
    avisar("Catálogo cargado. Las validaciones y el orden de columnas ya lo usan.");
    previsualizar();
  } catch (e) { avisar(e.message, true); }
}

// --- Usuarios ---

async function listarUsuarios() {
  const usuarios = await api("/api/usuarios").then((r) => r.json());
  $("#lista-usuarios").replaceChildren(...usuarios.map((u) => el("li", {},
    el("span", { textContent: u.usuario }), u.admin ? el("span", { className: "insignia", textContent: "admin" }) : null,
    el("span", { className: "espacio" }),
    el("button", { className: "chico", textContent: "Nueva clave", onclick: async () => {
      const nueva = prompt(`Clave nueva para ${u.usuario} (mínimo 8 caracteres). Se le cierran las sesiones abiertas.`);
      if (!nueva) return;
      try {
        await json(`/api/usuarios/${u.id}/clave`, "POST", { nueva });
        avisar(`Clave de ${u.usuario} cambiada. Pasásela por un medio seguro.`);
      } catch (e) { avisar(e.message, true); }
    } }),
    u.id === estado.yo.id ? null : el("button", { className: "chico", textContent: "Borrar", onclick: async () => {
      if (!confirm(`¿Borrar a ${u.usuario}?`)) return;
      await api(`/api/usuarios/${u.id}`, { method: "DELETE" });
      listarUsuarios();
    } }))));
}

function enlazarCambioDeClave() {
  const dialogo = $("#dialogo-clave");
  const error = $("#error-clave");
  $("#usuario").onclick = () => { $("#form-clave").reset(); error.hidden = true; dialogo.showModal(); };
  $("#btn-clave-cancelar").onclick = () => dialogo.close();
  $("#form-clave").onsubmit = async (e) => {
    e.preventDefault();
    const datos = Object.fromEntries(new FormData(e.target));
    if (datos.nueva !== datos.repetida) { error.textContent = "Las claves nuevas no coinciden"; error.hidden = false; return; }
    try {
      await json("/api/yo/clave", "POST", { actual: datos.actual, nueva: datos.nueva });
      dialogo.close();
      avisar("Clave cambiada. Las otras sesiones abiertas con tu usuario se cerraron.");
    } catch (err) { error.textContent = err.message; error.hidden = false; }
  };
}

async function crearUsuario(e) {
  e.preventDefault();
  const datos = Object.fromEntries(new FormData(e.target));
  try {
    await json("/api/usuarios", "POST", { usuario: datos.usuario, clave: datos.clave, admin: !!datos.admin });
    e.target.reset();
    listarUsuarios();
  } catch (err) { avisar(err.message, true); }
}

// --- Arranque ---

function mostrarPestana(nombre) {
  for (const b of document.querySelectorAll(".pestanas button")) b.classList.toggle("activa", b.dataset.pestana === nombre);
  for (const v of ["tabla", "reglas", "base", "ejemplos", "usuarios"]) $(`#vista-${v}`).hidden = v !== nombre;
  if (nombre === "base") listarBase();
  if (nombre === "usuarios") { listarUsuarios(); mostrarUsoAsistente(); listarCatalogo(); }
  if (nombre === "ejemplos" && estado.receta) evaluarEjemplos();
}

async function iniciar() {
  estado.yo = await api("/api/yo").then((r) => r.json());
  const tipos = await api("/api/tipos-tarjeta").then((r) => r.json());
  estado.schema = tipos.schema;
  estado.sinCondicion = new Set(tipos.sin_condicion);
  $("#usuario").textContent = estado.yo.usuario;
  enlazarCambioDeClave();
  $("#pestana-usuarios").hidden = !estado.yo.admin;
  for (const e of document.querySelectorAll(".solo-admin")) e.hidden = !estado.yo.admin;
  for (const tipo of Object.keys(estado.schema.discriminator.mapping).sort((a, b) => (NOMBRES[a] || a).localeCompare(NOMBRES[b] || b))) {
    $("#sel-tipo").append(el("option", { value: tipo, textContent: NOMBRES[tipo] || tipo }));
  }

  $("#sel-senal").onchange = (e) => e.target.value && abrirSenal(e.target.value);
  enlazarNuevaSenal();
  $("#in-catalogo").onchange = (e) => { if (e.target.files[0]) subirCatalogo(e.target.files[0]); e.target.value = ""; };
  const idioma = (codigo) => (e) => {
    const lista = new Set(estado.receta.idiomas);
    e.target.checked ? lista.add(codigo) : lista.delete(codigo);
    estado.receta.idiomas = ["ing", "port"].filter((x) => lista.has(x));
    cambioReceta();
  };
  $("#in-idioma-ing").onchange = idioma("ing");
  $("#in-idioma-port").onchange = idioma("port");
  $("#in-archivo").onchange = (e) => e.target.files[0] && subirGrilla(e.target.files[0]);
  $("#btn-guardar").onclick = () => guardar();
  $("#btn-pedir").onclick = () => enviarMensaje();
  $("#btn-proponer").onclick = () => enviarMensaje(true);
  $("#in-pedido").onkeydown = (e) => {
    if (e.key === "Enter" && !e.shiftKey && !$("#btn-pedir").disabled) { e.preventDefault(); enviarMensaje(); }
  };
  $("#btn-hilo-nuevo").onclick = () => { estado.hilo = []; dibujarHilo(); };
  enlazarTitulos();
  $("#btn-xlsx").onclick = () => exportar("xlsx");
  $("#btn-csv").onclick = () => exportar("csv");
  $("#btn-exportar-receta").onclick = exportarReceta;
  $("#in-receta").onchange = (e) => { if (e.target.files[0]) importarReceta(e.target.files[0]); e.target.value = ""; };
  $("#btn-salir").onclick = async () => { await fetch("/api/logout", { method: "POST" }); location.href = "/login"; };
  $("#btn-agregar").onclick = () => {
    const t = tarjetaNueva($("#sel-tipo").value);
    estado.receta.tarjetas.push(t);
    estado.abierta = t.id;
    cambioReceta();
    dibujarTarjetas();
  };
  $("#in-hoja").oninput = (e) => {
    const v = e.target.value.trim();
    estado.receta.entrada.hoja = /^\d+$/.test(v) ? Number(v) : v;
    resumirEntradaYSalida();
    cambioReceta();
  };
  $("#in-fila").oninput = (e) => {
    estado.receta.entrada.fila_encabezado = Number(e.target.value) || 1;
    resumirEntradaYSalida();
    cambioReceta();
  };
  $("#btn-abrir-todo").onclick = () => {
    guardarGruposAbiertos(new Set(agruparConsecutivas(estado.receta.tarjetas).map((g) => g.clave)));
    dibujarTarjetas();
  };
  $("#btn-cerrar-todo").onclick = () => { estado.abierta = null; guardarGruposAbiertos(new Set()); dibujarTarjetas(); };
  $("#in-salida").oninput = (e) => {
    estado.receta.salida.columnas = e.target.value.split("\n").map((s) => s.trim()).filter(Boolean);
    resumirEntradaYSalida();
    cambioReceta();
  };
  for (const b of document.querySelectorAll(".pestanas button")) b.onclick = () => mostrarPestana(b.dataset.pestana);
  $("#btn-evaluar").onclick = evaluarEjemplos;
  $("#sel-filtro-pautas").onchange = previsualizar;
  $("#btn-revisar").onclick = revisarNuevas;
  let demora;
  $("#base-buscar").oninput = () => { clearTimeout(demora); demora = setTimeout(listarBase, 300); };
  $("#base-estado").onchange = () => listarBase();
  $("#btn-base-ejemplos").onclick = cargarBaseDeEjemplos;
  $("#btn-base-mas").onclick = () => listarBase(true);
  $("#form-ejemplo").onsubmit = subirEjemplo;
  $("#form-usuario").onsubmit = crearUsuario;
  enlazarValidaciones();

  let ultima = null;
  try { ultima = localStorage.getItem("ultima-senal"); } catch {}
  await listarSenales(ultima);
  if (ultima && [...$("#sel-senal").options].some((o) => o.value === ultima)) await abrirSenal(ultima);
}

iniciar().catch((e) => avisar(e.message, true));
