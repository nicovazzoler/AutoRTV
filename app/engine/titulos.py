"""La columna de programa de un EPG terminado, por su nombre."""
NOMBRES_PROGRAMA = ["TIT ING", "Programa", "PROGRAMA", "Program Title", "Titulo", "Título", "Title"]


def detectar_columna(columnas: list[str]) -> str | None:
    return next((c for c in NOMBRES_PROGRAMA if c in columnas), None)

