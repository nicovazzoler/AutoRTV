import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, textoDeError } from "../api";

export function CambiarClave({ alCerrar }: { alCerrar: () => void }) {
  const dialogo = useRef<HTMLDialogElement>(null);
  const [error, setError] = useState("");
  const [listo, setListo] = useState(false);

  useEffect(() => {
    dialogo.current?.showModal();
  }, []);

  const enviar = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const datos = new FormData(e.currentTarget);
    if (datos.get("nueva") !== datos.get("repetida")) {
      setError("Las claves nuevas no coinciden");
      return;
    }
    try {
      await api.post("/yo/clave", { actual: datos.get("actual"), nueva: datos.get("nueva") });
      setListo(true);
      setError("");
    } catch (err) {
      setError(textoDeError(err));
    }
  };

  return (
    <dialog ref={dialogo} className="dialogo" onClose={alCerrar}>
      <form onSubmit={enviar}>
        <h2>Cambiar mi clave</h2>
        {listo ? (
          <p className="nota">Listo: la clave nueva ya vale. Las otras sesiones abiertas se cerraron.</p>
        ) : (
          <>
            <label className="campo">Clave actual<input className="entrada" name="actual" type="password" autoComplete="current-password" required /></label>
            <label className="campo">Clave nueva (8 caracteres o más)<input className="entrada" name="nueva" type="password" autoComplete="new-password" minLength={8} required /></label>
            <label className="campo">Repetí la clave nueva<input className="entrada" name="repetida" type="password" autoComplete="new-password" minLength={8} required /></label>
          </>
        )}
        {error && <p className="error" role="alert">{error}</p>}
        <div className="botones">
          {!listo && <button className="boton principal" type="submit">Cambiar</button>}
          <button className="boton" type="button" onClick={() => dialogo.current?.close()}>{listo ? "Cerrar" : "Cancelar"}</button>
        </div>
      </form>
    </dialog>
  );
}
