import { useEffect, useRef } from "react";

// Corre dentro de la página de la señal: copia su HTML tal como se ve, con lo que cargó por JavaScript.
const FAVORITO = `javascript:(()=>{const h=document.documentElement.outerHTML;const ok=()=>alert('Listo: la página quedó copiada. Pegala en AutoRTV.');navigator.clipboard.writeText(h).then(ok,()=>{const t=document.createElement('textarea');t.value=h;document.body.appendChild(t);t.select();document.execCommand('copy');t.remove();ok();});})()`;

export function CopiarPagina({ titulo }: { titulo: string }) {
  const enlace = useRef<HTMLAnchorElement>(null);

  // React bloquea los href "javascript:", así que se pone a mano.
  useEffect(() => {
    enlace.current?.setAttribute("href", FAVORITO);
  }, []);

  return (
    <details className="caja">
      <summary>{titulo}</summary>
      <div style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 14, lineHeight: 1.5 }}>
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 12 }}>
          <a ref={enlace} className="boton marca chico" onClick={(e) => e.preventDefault()} draggable>Copiar grilla para AutoRTV</a>
          <span className="tenue">Arrastralo una vez a la barra de favoritos. En la página de la señal, un clic copia el HTML y lo pegás acá.</span>
        </div>
        <span className="tenue">A mano: clic derecho sobre la grilla › Inspeccionar › clic derecho en el bloque marcado › Copiar › Copiar outerHTML.</span>
        <span className="tenue">Si la página carga la grilla de a un día o después de hacer clics, la va a configurar el agente desde Señal › Fuente web.</span>
      </div>
    </details>
  );
}
