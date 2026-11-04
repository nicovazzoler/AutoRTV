"""En el build de la imagen: si un intento hostil sale de la caja, el build falla y no se deploya.

Si la caja no llega a correr código en el build, solo avisa: al arrancar se prueba de nuevo y, si tampoco anda, el
código de las señales queda apagado.
"""
import sys

from app.caja import autoprueba

resultado = autoprueba.probar()
for caso in resultado["casos"]:
    print(f"{'bloqueado' if caso['bloqueado'] else 'SE ESCAPÓ'} · {caso['nombre']} · {caso['motivo']}")
print(resultado["motivo"], f"({resultado.get('segundos', 0)} s, usuario {resultado.get('usuario')})")
sys.exit(1 if resultado["anda"] and not resultado["ok"] else 0)
