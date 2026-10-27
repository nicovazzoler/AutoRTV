# Rediseño: ubicación de las cajas

## Contexto
- La web actual es confusa y quedó parcheada: arrancó centrada en las tarjetas, y después se le sumaron la base de pautas y el asistente encima.
- La idea nueva:
  - el usuario ve **contenido**, no reglas;
  - lo que sale mal se le pide al **agente**;
  - la **base** se filtra por programa o capítulo y se corrige ahí, y la semana se reprocesa sola;
  - lo que una grilla nueva trae y no resuelven ni la base ni las reglas tiene que **saltar a la vista**.
- Este paso es solo **dónde va cada caja**. El diseño visual viene después, con Vite (stack a definir).
- Ya decidido:
  - etapas chicas que revisás;
  - mismo repo con historia nueva;
  - se conservan los datos de Railway;
  - cualquier usuario puede aprobar y editar la base.

## Respuesta a "si la regla ya separa bien el capítulo, ¿hace falta revisar?"
No. Cada fila de una grilla nueva cae en uno de tres grupos:

| Grupo | Cuándo | ¿Hay que hacer algo? |
|---|---|---|
| ✔ **De la base** | la pauta ya está en la base | no |
| ✚ **Nueva, lista** | capítulo nuevo de un **programa que ya está en la base**, y la fila pasa todas las validaciones | no: entra sola al confirmar la semana; se puede mirar |
| ⚠ **Para revisar** | **programa que no está en la base**, celda que no cumple el catálogo, horario con error, o una regla que falló | sí: alguien la mira, corrige si hace falta y la da por buena |

- "Para revisar" se agrupa **por pauta**: un programa nuevo que sale 5 veces se revisa una sola vez.
- Al **confirmar la semana**, las ✚ y las ⚠ ya vistas pasan a la base. La semana siguiente salen ✔.

## Mapa de pantallas
```
Barra fija ─ señal · nueva señal · subir grilla · confirmar y exportar · usuario
├── Revisar (pestaña por defecto al subir una grilla)
├── Grilla completa
├── Base
├── Señal (ejemplos · reglas · configuración)
└── Admin (solo admin)
Panel del agente: siempre a la derecha, se puede plegar
```

## 1. Layout general
```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ AutoRTV  [Concert Channel ▾] [+ Nueva señal]   [⬆ Subir grilla]  [Confirmar y exportar ▾] nico ▾│
├──────────────────────────────────────────────────────────────────┬───────────────────────┤
│ [Revisar ⚠8] [Grilla completa] [Base] [Señal] [Admin]            │ AGENTE            [‹] │
│                                                                  │                       │
│                                                                  │  (conversación)       │
│                     CONTENIDO DE LA PESTAÑA                      │                       │
│                         (~70 % del ancho)                        │                       │
│                                                                  │                       │
│                                                                  │ [escribile…    ][➤]   │
└──────────────────────────────────────────────────────────────────┴───────────────────────┘
```
- "Confirmar y exportar ▾" abre xlsx/csv. Si quedan ⚠ sin ver, avisa antes.
- El número en la pestaña Revisar es lo pendiente. Es lo primero que se ve.

## 2. Revisar (lo principal)
```
┌ Semana 02/11 → 08/11 · grilla_noviembre.xlsx ─────────────────────────────────────────┐
│  573 filas    ✔ 540 de la base    ✚ 25 nuevas listas    ⚠ 8 para revisar (3 programas)  │
└────────────────────────────────────────────────────────────────────────────────────────┘
┌ ⚠ Para revisar ───────────────────────────────────────────── [Pedirle al agente que arregle] ┐
│ Motivo            │ Cómo vino (cruda)             │ Cómo queda (editable)          │ Veces │    │
│ Programa nuevo    │ Foo Fighters - Live at Wem…   │ TIT ING · TIT CAP ING · …      │  5    │ [✓] │
│ Año inválido      │ Memory Lane - Prince · 20255  │ … Año: 20255 ✕                 │  1    │ [✓] │
│ Regla con error   │ …                             │ …                              │  2    │ [✓] │
└──────────────────────────────────────────────────────────────────────────────────────────┘
┌ ✚ Nuevas listas: capítulos nuevos de programas conocidos (25) ──────────────── [ver ▸] ┐
└──────────────────────────────────────────────────────────────────────────────────────────┘
┌ Horarios: ✓ 24 h todos los días · sin huecos · sin superposiciones ────────── [ver ▸] ┐
└──────────────────────────────────────────────────────────────────────────────────────────┘
```
- [✓] = "está bien así".
- Corregir una celda: doble clic. Eso corrige todas las veces que aparece la pauta.
- Al tocar una fila, el agente queda "hablando de esa fila".

## 3. Grilla completa
```
┌ Filtros: estado [todas ▾]  programa [todos ▾]  buscar [__________] ──────────────────────┐
├──────────────────────────────────────────────────────────────────────────────────────────┤
│ # │ ● │ N │ DIA │ FECHA │ HORA │ DUR │ TIT ING │ NRO TEMP │ NRO CAP │ TIT CAP ING │ …      │
│   │ ✔ ✚ ⚠ por fila, celdas inválidas marcadas, doble clic para editar el contenido        │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```
Es la tabla de hoy, sin el panel de validaciones encima: los horarios están en Revisar.

## 4. Base
```
┌ Filtros ──────────────────────────────────────────────────────────────────────────────┐
│ Programa [Memory Lane ▾]  Capítulo [todos ▾]  [Columna ▾] = [_____]  buscar [_______]   │
│ 16 pautas · estado [todas ▾]                                                           │
├──────────────────────────────────────────────────────────────────────────────────────────┤
│ ☐ │ Cómo vino (cruda)        │ TIT ING     │ NRO TEMP │ NRO CAP │ TIT CAP ING │ … │ por  │
│ ☐ │ Memory Lane · OutKast …  │ Memory Lane │ 5        │ 1       │ Outkast     │   │ ana  │
├──────────────────────────────────────────────────────────────────────────────────────────┤
│ Con las 16 marcadas:  [Cambiar ▾ columna] a [__________] [Aplicar]   [Olvidar]          │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```
- Después de editar, la semana abierta se reprocesa sola y los números de Revisar se actualizan.

## 5. Señal
```
┌ Ejemplos ─────────────────────┐ ┌ Reglas (lo arma el agente) ──────────────────────────┐
│ 3 semanas cargadas            │ │ 1. Saca «_x000D_» de todas las columnas · 74 celdas │
│ · octubre  100 %  [borrar]    │ │ 2. Parte TIT ING en programa y capítulo en « - »     │
│ · septiembre 96 % [borrar]    │ │ …                                                   │
│ [+ Agregar semana terminada]  │ │ Historial: hoy 15:02 ana · ayer nico  [Deshacer]    │
│ Las reglas aciertan el 98 %   │ └──────────────────────────────────────────────────────┘
└───────────────────────────────┘ ┌ Configuración ───────────────────────────────────────┐
                                  │ Hoja · fila de encabezado (detectada) · idiomas      │
                                  │ (admin) validaciones · exportar/importar receta      │
                                  └──────────────────────────────────────────────────────┘
```
- Las reglas se ven como frases, de solo lectura. Se cambian hablando con el agente o con "Deshacer".

## 6. Nueva señal (cuadro de 3 pasos)
```
┌ Nueva señal ──────────────────────────────────────────────────────────────┐
│ ① Nombre  [Concert Channel______]   → cartel si hay una parecida          │
│ ② ┌ Grilla cruda ──────┐  ┌ Macro hecha ───────┐                          │
│   │ arrastrá el xlsx   │  │ arrastrá el xlsx   │                          │
│   └────────────────────┘  └────────────────────┘                          │
│ ③ ✓ Base: 145 pautas    ⟳ El agente arma las reglas desde el ejemplo… 92 %  │
│                                                    [Abrir la señal]       │
└───────────────────────────────────────────────────────────────────────────┘
```
- El paso ③ corre solo, porque las reglas hacen falta para los programas nuevos de las semanas siguientes.
- Sin API key, la señal arranca solo con la base.

## 7. Panel del agente
```
┌ Agente ─────────────── [nueva] [‹] ┐
│        ¿por qué este capítulo  ◯   │
│        quedó cortado?              │
│ ◯ La regla 2 corta en « - »…       │
│ ┌ Propuesta ─────────────────────┐ │
│ │ "Corto solo en el último « - »" │ │
│ │ Cambia 12 filas:                │ │
│ │  Live - Paris - 2024 → …        │ │
│ │  (3 ejemplos de antes → después)│ │
│ │ ⚠ para revisar: 8 → 2           │ │
│ │ [Ver en la grilla] [Aplicar]    │ │
│ │ [Descartar]   ▸ ver la regla    │ │
│ └─────────────────────────────────┘ │
│ ● respondiendo rápido               │
│ [escribile…              ] [➤]      │
│ [Proponer cambios]                  │
└─────────────────────────────────────┘
```
- La propuesta muestra **contenido** (filas antes → después y cuántas ⚠ resuelve). La regla queda plegada.

## 8. Admin
Tres cajas en columna: **Usuarios** (crear, nueva clave, borrar) · **Catálogo de columnas** · **Uso del asistente**.

## Formatos de entrada
Todo formato termina en la misma **tabla cruda** (filas y columnas). Desde ahí, las reglas y la base funcionan igual. Lo único que cambia es el **lector**, que se configura por señal, igual que hoy se configuran la hoja y la fila de encabezado.

| Formato | Cómo se lee | Qué guarda la señal |
|---|---|---|
| Excel / CSV | como hoy | hoja y fila de encabezado (detectadas) |
| XML | si es XMLTV (estándar de EPG), solo. Si es otro XML, se elige qué elemento es un programa y qué campo va a cada columna | elemento y campos |
| PDF | si trae tablas, se leen las tablas; si es texto suelto, se trata como texto | páginas, tablas o texto |
| Texto pegado o .txt | cada línea es una fila. Se detecta el separador (tab al copiar de Excel, `;`, `\|`) o un patrón de línea ("06:00 Programa - Capítulo"). Las líneas de día ("Lunes 2/11") ponen la fecha de las que siguen | separador o patrón, y formato del día |

- **Lector de PDF y texto suelto:** lo propone el agente a partir del ejemplo, igual que con las reglas. El resultado se ve antes de aceptarlo.
- **Fecha de inicio:** si el texto no trae la fecha en cada fila, al subirlo se pide la fecha de inicio de la semana.

Cambios en las cajas:
- **"⬆ Subir grilla"** abre un cuadro con dos pestañas:
  - **Archivo:** se arrastra un xlsx, csv, xml, pdf, txt o html.
  - **Pegar texto:** un cuadro de texto más la fecha de inicio.
- **Revisar** suma una primera caja: "Cómo se leyó: grilla.pdf → 573 filas · 6 columnas [ver la tabla cruda ▸]". Si se leyó mal, ahí está el botón "Pedirle al agente que ajuste la lectura".
- **Nueva señal ②:** la grilla cruda puede venir en cualquier formato o pegada. La macro hecha sigue siendo Excel.
- **Nueva etapa:** los lectores van como etapa propia del backend, después de "Backend de la semana": XMLTV y XML genérico, texto y pegado, PDF.

## Qué se va de la web actual
- El editor de tarjetas y la lista de tarjetas.
- La sección "Títulos conocidos": se sacan solos de los programas que hay en la base.
- Los bloques Entrada / Validaciones / Columnas de salida de la izquierda: pasan a Señal → Configuración.

## Qué se conserva por dentro
- El motor de reglas: lo usa el agente.
- La base de pautas, Postgres, las validaciones, el catálogo, los usuarios y los ejemplos.
- Los datos de Railway siguen. Los tres grupos (✔ ✚ ⚠) se calculan al vuelo y no cambian la base.

## Después de acordar esto (cada uno es una etapa que revisás; ninguna arranca sin tu ok)
1. **Backend de la semana:**
   - los tres grupos, con su motivo;
   - "confirmar semana";
   - en la Base, filtros por columna y edición masiva;
   - historial de reglas con deshacer;
   - títulos conocidos sacados de la base.
2. **Web nueva con Vite**, con estas pantallas. Antes hay que definir el framework y chequear que el entorno llegue a npm (hoy el CDN está bloqueado).
3. **Agente centrado en contenido:**
   - recibe las filas ⚠;
   - la propuesta muestra filas antes → después;
   - arma las reglas solo en "Nueva señal";
   - puede proponer correcciones en la base.
4. **Limpieza + historia nueva en `main`.**
   - Ojo: GitHub deja visibles los PRs viejos (#1-#5) con sus commits aunque se reescriba `main`. Si el repo va a ser público y querés que no queden, hay que hacerlo en un repo nuevo. Se decide en esa etapa.
- El PR #5 (CLAUDE.md + README) sigue abierto: conviene mergearlo igual.

## Estado
- Propuesta de ubicación, a revisar. Todavía no hay código de la versión nueva.
