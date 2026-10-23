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
  return receta;
}
const ICONOS = { error: "✕", aviso: "⚠", info: "ℹ" };

const estado = {
  schema: null, sinCondicion: new Set(), yo: null, receta: null, guardada: null,
  tablaId: null, informes: [], columnas: new Set(), abierta: null, ultimoPreview: 0,
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

function dibujarTarjetas() {
  const lista = $("#lista-tarjetas");
  lista.replaceChildren();
  estado.receta.tarjetas.forEach((t, k) => {

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
    lista.append(item);
  });
  pintarInformes();
}

// Actualiza insignias y mensajes sin redibujar los formularios (no se pierde el foco al tipear).
function pintarInformes() {
  for (const item of document.querySelectorAll("#lista-tarjetas > li")) {
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
  estado.guardada = guardada ? JSON.stringify(normalizar(structuredClone(guardada))) : null;
  estado.version = version;
  estado.informes = [];
  estado.abierta = null;
  $("#principal").hidden = false;
  $("#in-hoja").value = receta.entrada.hoja;
  $("#in-fila").value = receta.entrada.fila_encabezado;
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
  dibujarTarjetas();
  cambioReceta();
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
  const tr = document.querySelector(`#tabla tbody tr:nth-child(${fila})`);
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
  try {
    const r = await json("/api/preview", "POST", { tabla_id: estado.tablaId, senal: estado.receta });
    if (turno !== estado.ultimoPreview) return;  // llegó una respuesta vieja
    estado.informes = r.tarjetas;
    for (const i of r.tarjetas) i.columnas.forEach((c) => estado.columnas.add(c));
    r.columnas.forEach((c) => estado.columnas.add(c));
    actualizarColumnasConocidas();
    dibujarTabla(r.columnas, r.filas, r.validaciones);
    pintarValidaciones(r);
    $("#resumen").textContent = `${r.total_filas} filas` + (r.total_filas > r.filas.length ? ` (se muestran ${r.filas.length})` : "");
    pintarInformes();
    avisar("");
  } catch (e) {
    if (turno === estado.ultimoPreview) avisar(e.message, true);
  }
}

function actualizarColumnasConocidas() {
  $("#columnas-conocidas").replaceChildren(...[...estado.columnas].map((c) => el("option", { value: c })));
}

function dibujarTabla(columnas, filas, avisos = []) {
  const nivelPorFila = {};
  for (const a of avisos) {
    if (!a.fila || a.nivel === "info") continue;
    if (a.nivel === "error" || !nivelPorFila[a.fila]) nivelPorFila[a.fila] = a.nivel;
  }
  const tabla = $("#tabla");
  const cabeza = el("tr", {}, el("th", { textContent: "#" }), ...columnas.map((c) => el("th", { textContent: c })));
  const cuerpo = filas.map((f, k) => el("tr", { className: nivelPorFila[k + 1] ? `fila-${nivelPorFila[k + 1]}` : "" }, el("td", { className: "num", textContent: k + 1 }),
    ...f.map((v) => el("td", v === null || v === "" ? { className: "vacia", textContent: "—" } : { textContent: v, title: v }))));
  tabla.replaceChildren(el("thead", {}, cabeza), el("tbody", {}, ...cuerpo));
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
    previsualizar();
  } catch (e) { avisar(e.message, true); }
}

async function exportar(formato) {
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
    el("span", { className: "espacio" }), borrar);
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
    await api(`/api/senales/${estado.receta.id}/ejemplos`, { method: "POST", body: new FormData(e.target) });
    e.target.reset();
    evaluarEjemplos();
  } catch (err) { avisar(err.message, true); }
}

// --- Usuarios ---

async function listarUsuarios() {
  const usuarios = await api("/api/usuarios").then((r) => r.json());
  $("#lista-usuarios").replaceChildren(...usuarios.map((u) => el("li", {},
    el("span", { textContent: u.usuario }), u.admin ? el("span", { className: "insignia", textContent: "admin" }) : null,
    el("span", { className: "espacio" }),
    u.id === estado.yo.id ? null : el("button", { className: "chico", textContent: "Borrar", onclick: async () => {
      if (!confirm(`¿Borrar a ${u.usuario}?`)) return;
      await api(`/api/usuarios/${u.id}`, { method: "DELETE" });
      listarUsuarios();
    } }))));
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
  for (const v of ["tabla", "ejemplos", "usuarios"]) $(`#vista-${v}`).hidden = v !== nombre;
  if (nombre === "usuarios") listarUsuarios();
  if (nombre === "ejemplos" && estado.receta) evaluarEjemplos();
}

async function iniciar() {
  estado.yo = await api("/api/yo").then((r) => r.json());
  const tipos = await api("/api/tipos-tarjeta").then((r) => r.json());
  estado.schema = tipos.schema;
  estado.sinCondicion = new Set(tipos.sin_condicion);
  $("#usuario").textContent = estado.yo.usuario;
  $("#pestana-usuarios").hidden = !estado.yo.admin;
  for (const tipo of Object.keys(estado.schema.discriminator.mapping).sort((a, b) => (NOMBRES[a] || a).localeCompare(NOMBRES[b] || b))) {
    $("#sel-tipo").append(el("option", { value: tipo, textContent: NOMBRES[tipo] || tipo }));
  }

  $("#sel-senal").onchange = (e) => e.target.value && abrirSenal(e.target.value);
  $("#btn-nueva").onclick = () => {
    const nombre = prompt("Nombre de la señal (ej. Concert Channel)");
    if (!nombre) return;
    const id = nombre.trim().toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    if (!id) { avisar("El nombre tiene que tener letras o números", true); return; }
    cargarReceta({ schema_version: 1, id, nombre, entrada: { tipo: "excel", hoja: 0, fila_encabezado: 1 },
      tarjetas: [], salida: { columnas: [] } }, null);
  };
  $("#in-archivo").onchange = (e) => e.target.files[0] && subirGrilla(e.target.files[0]);
  $("#btn-guardar").onclick = () => guardar();
  enlazarTitulos();
  $("#btn-xlsx").onclick = () => exportar("xlsx");
  $("#btn-csv").onclick = () => exportar("csv");
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
    cambioReceta();
  };
  $("#in-fila").oninput = (e) => { estado.receta.entrada.fila_encabezado = Number(e.target.value) || 1; cambioReceta(); };
  $("#in-salida").oninput = (e) => {
    estado.receta.salida.columnas = e.target.value.split("\n").map((s) => s.trim()).filter(Boolean);
    cambioReceta();
  };
  for (const b of document.querySelectorAll(".pestanas button")) b.onclick = () => mostrarPestana(b.dataset.pestana);
  $("#btn-evaluar").onclick = evaluarEjemplos;
  $("#form-ejemplo").onsubmit = subirEjemplo;
  $("#form-usuario").onsubmit = crearUsuario;
  enlazarValidaciones();

  let ultima = null;
  try { ultima = localStorage.getItem("ultima-senal"); } catch {}
  await listarSenales(ultima);
  if (ultima && [...$("#sel-senal").options].some((o) => o.value === ultima)) await abrirSenal(ultima);
}

iniciar().catch((e) => avisar(e.message, true));
