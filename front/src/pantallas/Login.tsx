import { useState, type FormEvent } from "react";
import { api, textoDeError } from "../api";
import { navegar } from "../ruta";

export function Login() {
  const [error, setError] = useState("");
  const [entrando, setEntrando] = useState(false);

  const entrar = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const datos = new FormData(e.currentTarget);
    setEntrando(true);
    try {
      await api.post("/login", { usuario: datos.get("usuario"), clave: datos.get("clave") });
      navegar("/");
    } catch (err) {
      setError(textoDeError(err));
      setEntrando(false);
    }
  };

  return (
    <main className="login">
      <div className="brillo uno" aria-hidden="true" />
      <div className="brillo dos" aria-hidden="true" />
      <div className="puntos" aria-hidden="true" />
      <form className="tarjeta-login" onSubmit={entrar}>
        <div className="logo-placa"><img src="/logo-rtv.png" alt="rtv" width={124} height={34} /></div>
        <h1 className="titulo" style={{ fontSize: 40, fontWeight: 600, textAlign: "center" }}>AutoRTV</h1>
        <label className="campo">Usuario<input className="entrada" name="usuario" autoComplete="username" required autoFocus /></label>
        <label className="campo">Clave<input className="entrada" name="clave" type="password" autoComplete="current-password" required /></label>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="boton principal" type="submit" disabled={entrando} style={{ minHeight: 48, fontSize: 15 }}>
          {entrando ? "Entrando…" : "Entrar"}
        </button>
      </form>
    </main>
  );
}
