import { useState } from "react";

export type Tema = "oscuro" | "claro";

export function useTema(): [Tema, () => void] {
  const [tema, setTema] = useState<Tema>(() => (document.documentElement.dataset.tema === "claro" ? "claro" : "oscuro"));
  const alternar = () => {
    const nuevo: Tema = tema === "oscuro" ? "claro" : "oscuro";
    document.documentElement.dataset.tema = nuevo;
    try {
      localStorage.setItem("autortv.tema", nuevo);
    } catch {
      // Sin almacenamiento (ventana privada) el tema vale solo hasta recargar.
    }
    setTema(nuevo);
  };
  return [tema, alternar];
}
