"""Bajar la página de una señal desde su link."""
import ipaddress
import socket
from urllib.parse import urlparse

import httpx

MAX_BYTES = 15 * 1024 * 1024
TIMEOUT_S = 25
SALTOS = 5


class NoSePudo(Exception):
    """El link no se pudo bajar; el mensaje ya está en castellano."""


def _publica(host: str) -> bool:
    """Que el link no apunte a la red interna del servidor (localhost, 10.x, 192.168.x, metadatos de la nube)."""
    try:
        direcciones = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except socket.gaierror:
        raise NoSePudo(f"No encuentro el sitio {host}")
    return all(ipaddress.ip_address(d.split("%")[0]).is_global for d in direcciones)


def bajar(url: str) -> bytes:
    """El HTML de la página, siguiendo redirecciones y revisando cada salto."""
    url = url.strip()
    for _ in range(SALTOS):
        partes = urlparse(url)
        if partes.scheme not in ("http", "https") or not partes.hostname:
            raise NoSePudo("El link tiene que empezar con http:// o https://")
        if not _publica(partes.hostname):
            raise NoSePudo("Ese link apunta a una dirección interna: solo se bajan páginas públicas")
        try:
            with httpx.stream("GET", url, timeout=TIMEOUT_S, follow_redirects=False,
                              headers={"User-Agent": "Mozilla/5.0 (AutoRTV)", "Accept-Language": "es,en;q=0.8"}) as r:
                if r.is_redirect and r.headers.get("location"):
                    url = str(r.url.join(r.headers["location"]))
                    continue
                if r.status_code >= 400:
                    raise NoSePudo(f"La página respondió {r.status_code}")
                contenido = b""
                for parte in r.iter_bytes():
                    contenido += parte
                    if len(contenido) > MAX_BYTES:
                        raise NoSePudo("La página pasa los 15 MB")
                return contenido
        except httpx.HTTPError as e:
            raise NoSePudo(f"No se pudo bajar la página: {type(e).__name__}") from e
    raise NoSePudo("La página redirige demasiadas veces")
