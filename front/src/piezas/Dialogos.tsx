import { useEffect, useRef, useState } from "react";

interface Pedido {
  titulo?: string;
  texto: string;
  boton: string;
  peligro?: boolean;
  /** Con esto, el botón se habilita recién cuando la persona escribe este texto. */
  esperado?: string;
}

let abrir: ((p: Pedido) => Promise<boolean>) | null = null;

/** Pregunta con un modal propio. Esc o «Cancelar» devuelven false. */
export function confirmar(p: { titulo?: string; texto: string; boton: string; peligro?: boolean }): Promise<boolean> {
  return abrir ? abrir(p) : Promise.resolve(false);
}

/** Como confirmar, pero hay que escribir `esperado` (sin importar mayúsculas) para que se habilite el botón. */
export function pedirTexto(p: { titulo?: string; texto: string; esperado: string; boton?: string }): Promise<boolean> {
  return abrir ? abrir({ boton: "Borrar", peligro: true, ...p }) : Promise.resolve(false);
}

const igual = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase();

/** El modal de confirmar y pedirTexto. Va montado una sola vez en la app. */
export function Dialogos() {
  const dialogo = useRef<HTMLDialogElement>(null);
  const [pedido, setPedido] = useState<Pedido | null>(null);
  const [escrito, setEscrito] = useState("");
  const responder = useRef<(si: boolean) => void>(() => {});
  const origen = useRef<HTMLElement | null>(null);

  useEffect(() => {
    abrir = (p) => new Promise<boolean>((resolver) => {
      responder.current(false);  // si había otro abierto, ese queda como cancelado
      origen.current = document.activeElement as HTMLElement | null;
      responder.current = resolver;
      setEscrito("");
      setPedido(p);
    });
    return () => { abrir = null; };
  }, []);

  useEffect(() => {
    const d = dialogo.current;
    if (pedido && d && !d.open) {
      d.returnValue = "";
      d.showModal();
      // React no pone el atributo autofocus: sin esto showModal enfoca el primer botón, que es el de la acción.
      d.querySelector<HTMLElement>("[data-foco]")?.focus();
    }
  }, [pedido]);

  const alCerrar = () => {
    const si = dialogo.current?.returnValue === "si";
    responder.current(si);
    responder.current = () => {};
    setPedido(null);
    origen.current?.focus();
  };

  const bloqueado = pedido?.esperado !== undefined && !igual(escrito, pedido.esperado);

  return (
    <dialog ref={dialogo} className="dialogo" onClose={alCerrar} aria-labelledby="dialogo-titulo">
      {pedido && (
        <form method="dialog">
          <h2 id="dialogo-titulo">{pedido.titulo ?? "¿Seguro?"}</h2>
          <p style={{ margin: 0, whiteSpace: "pre-line" }}>{pedido.texto}</p>
          {pedido.esperado !== undefined && (
            <label className="campo">
              Escribí «{pedido.esperado}» para confirmar
              <input className="entrada" value={escrito} onChange={(e) => setEscrito(e.target.value)} data-foco autoComplete="off" />
            </label>
          )}
          <div className="botones">
            {/* Lo destructivo arranca con el foco en Cancelar: un Enter de más no borra nada. */}
            <button className={`boton ${pedido.peligro ? "peligro" : "principal"}`} type="submit" value="si" disabled={bloqueado}
              data-foco={!pedido.peligro && pedido.esperado === undefined ? "" : undefined}>
              {pedido.boton}
            </button>
            <button className="boton" type="submit" value="no" data-foco={pedido.peligro && pedido.esperado === undefined ? "" : undefined}>
              Cancelar
            </button>
          </div>
        </form>
      )}
    </dialog>
  );
}
