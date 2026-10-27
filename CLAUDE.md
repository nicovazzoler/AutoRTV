# AutoRTV

## Comentarios en el código

Regla: el código se explica solo. Un comentario existe solo si dice algo que el código no dice.

Permitido:
- Una línea arriba de una función que no es obvia, diciendo qué hace.
- El porqué de algo que parece un error o una decisión rara.
- Un caso borde que no se ve leyendo.

Prohibido:
- Historia: "antes pasaba X", "se arregló porque", "ahora usamos Y en vez de Z". Eso va en el commit.
- Repetir lo que dice el nombre de la función o la línea de abajo.
- Comentarios de más de 3 líneas. Si hace falta más, la función hace dos cosas: partila.
- Comentar cada paso de una función.

Mal:
```python
# Antes el csv salía en utf-8 común y en el laburo se veían mal las tildes,
# así que lo pasamos a utf-8-sig.
# Pasamos la tabla a csv
return pd.DataFrame(filas, columns=df.columns).to_csv(index=False).encode("utf-8-sig")
```

Bien:
```python
# utf-8 con BOM para que Excel en Windows abra bien los acentos.
return pd.DataFrame(filas, columns=df.columns).to_csv(index=False).encode("utf-8-sig")
```

Mal:
```python
# Redondeamos los segundos al paso
seg = min(round(seg / paso) * paso, 86400 - paso)
```

Bien:
```python
# 23:59:30 redondearía a 24:00, que no existe sin cambiar la fecha: se topea en el último paso del día.
seg = min(round(seg / paso) * paso, 86400 - paso)
```

## Trabajo con git y reportes

- Mensajes de commit de una sola línea.
- Reportes al usuario de máximo 5 líneas.
- Nunca hacer push directo a la rama principal (`main` / `claude/new-session-psu3ud`).
- Todo cambio va en una rama aparte y entra por pull request.
