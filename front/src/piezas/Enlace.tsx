import type { AnchorHTMLAttributes, MouseEvent } from "react";
import { navegar } from "../ruta";

/** Un <a> que cambia de pantalla sin recargar; con Ctrl o el botón del medio abre otra pestaña como siempre. */
export function Enlace({ a, onClick, ...props }: AnchorHTMLAttributes<HTMLAnchorElement> & { a: string }) {
  const ir = (e: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(e);
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    navegar(a);
  };
  return <a href={a} onClick={ir} {...props} />;
}
