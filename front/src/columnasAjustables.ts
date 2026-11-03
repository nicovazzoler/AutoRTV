/**
 * Columnas que se agrandan y achican arrastrando el borde derecho del encabezado, en toda tabla `.tabla-datos`.
 *
 * No agrega nada al DOM que maneja React: escucha el puntero en el documento y pone anchos en línea, que React no
 * pisa porque esas tablas no tienen `style`. El ancho se recuerda por pantalla y tabla, en este navegador.
 */
const BORDE = 6;
const MINIMO = 40;
const PREFIJO = "anchos:";

type Anchos = Record<string, number>;

function encabezados(tabla: HTMLTableElement): HTMLTableCellElement[] {
  const fila = tabla.tHead?.rows[0];
  return fila ? Array.from(fila.cells) : [];
}

function nombre(th: HTMLTableCellElement, i: number): string {
  return th.textContent?.trim() || `#${i}`;
}

// La ruta sin la señal ("/s/xt" y "/s/otra" comparten anchos) y el nombre de la tabla o su orden en la página.
function clave(tabla: HTMLTableElement): string {
  const ruta = location.pathname.split("/").slice(0, 2).join("/");
  const orden = Array.from(document.querySelectorAll("table.tabla-datos")).indexOf(tabla);
  return `${PREFIJO}${ruta}:${tabla.dataset.tabla ?? orden}`;
}

function leer(k: string): Anchos {
  try {
    return JSON.parse(localStorage.getItem(k) ?? "{}") as Anchos;
  } catch {
    return {};
  }
}

function guardar(k: string, anchos: Anchos) {
  try {
    localStorage.setItem(k, JSON.stringify(anchos));
  } catch {
    // sin almacenamiento (modo privado): el ancho dura hasta recargar
  }
}

function fijar(tabla: HTMLTableElement, anchos: Anchos) {
  const ths = encabezados(tabla);
  let total = 0;
  ths.forEach((th, i) => {
    const ancho = Math.max(MINIMO, anchos[nombre(th, i)] ?? th.getBoundingClientRect().width);
    th.style.width = `${ancho}px`;
    total += ancho;
  });
  tabla.style.tableLayout = "fixed";
  tabla.style.width = `${total}px`;
  tabla.classList.add("ajustada");
  tabla.dataset.anchos = JSON.stringify(anchos);
}

function sobreElBorde(e: PointerEvent): HTMLTableCellElement | null {
  const th = (e.target as Element | null)?.closest?.("table.tabla-datos thead tr:first-child th") as HTMLTableCellElement | null;
  if (!th) return null;
  return th.getBoundingClientRect().right - e.clientX <= BORDE ? th : null;
}

function aplicarGuardados() {
  document.querySelectorAll<HTMLTableElement>("table.tabla-datos").forEach((tabla) => {
    const anchos = leer(clave(tabla));
    if (Object.keys(anchos).length && tabla.dataset.anchos !== JSON.stringify(anchos)) fijar(tabla, anchos);
  });
}

export function activarColumnasAjustables() {
  let arrastre: { tabla: HTMLTableElement; th: HTMLTableCellElement; desde: number; ancho: number } | null = null;

  document.addEventListener("pointermove", (e) => {
    if (arrastre) {
      const { tabla, th, desde, ancho } = arrastre;
      const anchos: Anchos = JSON.parse(tabla.dataset.anchos ?? "{}");
      anchos[nombre(th, th.cellIndex)] = Math.max(MINIMO, ancho + e.clientX - desde);
      fijar(tabla, anchos);
      return;
    }
    document.body.classList.toggle("ajustando-columna", sobreElBorde(e) !== null);
  });

  document.addEventListener("pointerdown", (e) => {
    const th = sobreElBorde(e);
    if (!th) return;
    const tabla = th.closest("table") as HTMLTableElement;
    // Antes del primer arrastre se toman los anchos que tiene la tabla, para que el resto no salte.
    const actuales: Anchos = {};
    encabezados(tabla).forEach((x, i) => { actuales[nombre(x, i)] = x.getBoundingClientRect().width; });
    fijar(tabla, { ...actuales, ...JSON.parse(tabla.dataset.anchos ?? "{}") });
    arrastre = { tabla, th, desde: e.clientX, ancho: th.getBoundingClientRect().width };
    e.preventDefault();
  });

  document.addEventListener("pointerup", () => {
    if (!arrastre) return;
    guardar(clave(arrastre.tabla), JSON.parse(arrastre.tabla.dataset.anchos ?? "{}"));
    arrastre = null;
  });

  // Las tablas se arman de nuevo al cambiar de pantalla o de filtro: se les vuelve a poner el ancho guardado.
  new MutationObserver(aplicarGuardados).observe(document.body, { childList: true, subtree: true });
}
