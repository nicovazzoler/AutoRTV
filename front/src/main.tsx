import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/fraunces";
import "@fontsource-variable/inter";
import "./estilos.css";
import { App } from "./App";
import { activarColumnasAjustables } from "./columnasAjustables";

activarColumnasAjustables();

createRoot(document.getElementById("raiz")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
