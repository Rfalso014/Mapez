# Plan v2: Bot web para descargar reportes ("Bot Copión Web")

## Por qué cambia el enfoque
La versión 1 repetía clics por **coordenadas de pantalla** (pynput). Eso no permite trabajar
**sin que se vea** (oculto), no sabe **esperar a que un reporte se genere** y se rompe si la
ventana cambia de tamaño. La versión 2 controla el **navegador directamente** con
**Playwright**: graba sobre qué *elemento* de la página actúas (botón, campo, enlace), no en qué
píxel, y al ejecutar espera a que cada elemento exista antes de usarlo.

La versión 1 se conserva en `version_escritorio/` (no se borra).

## Requisitos del usuario → cómo se cumplen
| Requisito | Solución |
|---|---|
| Recibir una URL y entrar a la página | Campo URL en la ventana + `--url`; primer paso `abrir_url`. |
| Seguir mis pasos, de forma organizada | Grabador que anota cada acción como un **paso** con nombre en español; lista editable (subir/bajar, editar, borrar, notas). |
| Si hay un punto de espera, esperar a que se genere y seguir | Espera automática por elemento (Playwright) + pasos **"Esperar hasta que aparezca…"** / **"Esperar texto…"** marcados al grabar con la barra flotante; descargas con espera larga (hasta 10 min configurable). |
| Que me deje ver cuando lo hace | Casilla **"Ver mientras trabaja"** (navegador visible) + **modo lento** opcional; resalta el paso en curso. |
| Que no necesite de mí | Ejecución desatendida por línea de comandos y botón **Programar** (Programador de tareas de Windows); registros y captura de pantalla si falla. |
| Que trabaje sin que lo vea | Modo **oculto** (headless). |
| Clic derecho y elegir opciones del menú | Graba `contextmenu` → paso "Clic derecho en …"; el clic siguiente en el menú de la página se graba como paso normal. (Ver limitación del menú nativo abajo.) |
| Cambiar nombre a los archivos | Cada descarga es un paso **"Descargar → guardar como `<plantilla>`"**, p. ej. `Ventas_{hoy:%Y-%m-%d}{ext}`, en la carpeta elegida. |
| Usar mi contraseña e iniciar sesión | Las contraseñas se guardan en el **Administrador de credenciales de Windows** (`keyring`), nunca en el JSON; el paso guarda `{secreto:nombre}`. Perfil de navegador persistente para mantener la sesión. |
| Escribir, poner fechas, pasos con lógica | **Plantillas** en cualquier texto: `{hoy}`, `{ayer}`, `{hoy:%d/%m/%Y}`, `{dias:-7}`, `{inicio_mes}`, `{fin_mes}`, `{inicio_mes_anterior}`, `{fin_mes_anterior}`, variables propias `{cliente}` (definidas en el flujo o con `--var`). Pasos **opcionales** (si no aparece, sigue; útil para avisos/popups). Al grabar, si escribes la fecha de hoy/ayer se propone convertirla en fecha dinámica. |

## Tecnología
- Python 3.13, **tkinter** (ventana), **Playwright 1.6x** (sync API), **keyring** (contraseñas).
- Navegador: Chrome o Edge ya instalados (`channel="chrome"` / `"msedge"`), sin descargar navegadores. Seleccionable en opciones.

## Estructura
```
Bot de pruba/
├── bot.py                  # Ventana (tkinter) + línea de comandos
├── webbot/
│   ├── __init__.py
│   ├── flujo.py            # Modelo de pasos, descripción en español, JSON (sin importar playwright)
│   ├── plantillas.py       # Fechas y variables {hoy:%d/%m/%Y}, {secreto:x}
│   ├── secretos.py         # Envoltura de keyring (inyectable para pruebas)
│   ├── grabador.js         # Script inyectado: captura eventos, genera selectores, barra flotante
│   ├── grabador_web.py     # Abre navegador, inyecta grabador.js, recibe eventos → pasos
│   ├── ejecutor.py         # Ejecuta pasos (visible/oculto), esperas, descargas, registros
│   └── programador.py      # Crear/borrar tarea en el Programador de tareas (schtasks)
├── flujos/                 # Flujos guardados (.json)
├── descargas/              # Carpeta de descargas por defecto
├── registros/              # Logs y capturas de error por ejecución
├── perfiles/               # Perfil persistente del navegador (sesiones/cookies)
├── tests/
│   ├── sitio_prueba/       # Web local de prueba: login, generar reporte con demora, menú de clic derecho, descarga
│   ├── test_flujo.py, test_plantillas.py   # Unitarias
│   └── test_integracion.py # Graba y ejecuta contra el sitio de prueba en modo oculto
├── version_escritorio/     # Versión 1 (coordenadas), conservada
├── requirements.txt, iniciar.bat, README.md
```

## Modelo de pasos (`flujo.py`)
Flujo = `{version, nombre, url, variables{}, opciones{navegador, timeout_paso, carpeta_descargas}, pasos[]}`.
Cada paso: `{tipo, ...datos, nota, opcional, timeout, pagina}`. Tipos:
- `abrir_url {url}`
- `clic {selectores[], boton: izquierdo|derecho|medio, doble}`
- `escribir {selectores[], valor}` — `valor` admite plantillas; contraseña → `{secreto:nombre}`
- `tecla {selectores[]?, tecla}` (Enter, Tab, Escape…)
- `seleccionar {selectores[], valor, etiqueta}` (listas desplegables)
- `marcar {selectores[], marcado}` (casillas/radios)
- `esperar_elemento {selectores[], estado: visible|oculto}`
- `esperar_texto {texto}`
- `esperar_segundos {segundos}`
- `descargar {selectores[], boton, nombre, carpeta}` — el clic que provoca la descarga + renombrado
- `pagina` = índice de pestaña (0 principal; las pestañas/popups nuevas se numeran al abrirse).
`selectores[]` = alternativas en orden de preferencia; el ejecutor prueba cada una.

## Grabador (`grabador.js` + `grabador_web.py`)
- `launch_persistent_context(perfiles/<flujo>, channel, headless=False)`; `add_init_script(grabador.js)` y `expose_binding` para enviar eventos a Python; funciona en todas las pestañas y marcos.
- Captura: `click`, `dblclick`, `contextmenu`, `change`/`input` (valor final al salir del campo), `keydown` de Enter/Tab/Escape, `select`, casillas. Se ignoran eventos sobre la barra flotante.
- Selectores (en orden): `#id` estable (no autogenerado), `[data-testid]`, `[name]`, rol + nombre accesible, texto visible para botones/enlaces, `[aria-label]`, `[placeholder]`, ruta CSS con `:nth-of-type` como último recurso.
- Descargas: `page.on("download")` convierte el último clic en paso `descargar` (nombre sugerido = nombre original + `{ext}`; el archivo grabado se descarta).
- Contraseñas: campo `type=password` → el valor va directo a `keyring` como `<dominio>:<campo>` y el paso guarda `{secreto:<dominio>:<campo>}`. Nunca se escribe en JSON, registros ni pantalla.
- **Barra flotante** en la página (Shadow DOM, esquina, arrastrable): "⏳ Esperar a un elemento" (el siguiente clic marca qué elemento esperar, no hace clic), "🔤 Esperar texto…", "⏹ Terminar".
- Pasos llegan en vivo a la lista de la ventana (cola + `root.after`).

## Ejecutor (`ejecutor.py`)
- Visible u oculto; `slow_mo` en modo lento; `accept_downloads=True`.
- Antes de cada acción espera al elemento (timeout por paso, defecto 30 s; descargas 10 min).
- Resuelve plantillas y secretos justo al ejecutar.
- Paso opcional que falla → se anota y continúa; obligatorio → captura de pantalla + log + se detiene (código de salida 1).
- Registro por ejecución en `registros/AAAA-MM-DD_HHMMSS.log` con cada paso y su duración (sin contraseñas).
- Callback de progreso para resaltar el paso en la ventana; botón **Detener**.

## Ventana (`bot.py`)
- URL, nombre del flujo, botones: **⏺ Grabar**, **⏹ Detener**, **▶ Ejecutar**, **💾 Guardar**, **📂 Abrir**, **🆕 Nuevo**.
- Opciones: Ver mientras trabaja (sí/no), modo lento, navegador (Chrome/Edge), carpeta de descargas, timeout.
- Lista de pasos: Nº · Acción · Detalle · Nota. Doble clic → diálogo de edición (valor con ayuda de plantillas de fecha, selectores, timeout, opcional, nota). Subir/bajar, borrar, insertar espera.
- **🔑 Contraseñas**: listar/guardar/borrar secretos (sin mostrar valores).
- **⏰ Programar**: tarea diaria/semanal a una hora → `schtasks` ejecutando en modo oculto (con confirmación).
- Línea de comandos: `python bot.py --flujo flujos/x.json [--url U] [--oculto|--visible] [--var clave=valor] [--ejecutar]`; sin ventana con `--sin-ventana`.

## Pruebas
- Unitarias: plantillas de fecha (fecha fija inyectada), modelo/JSON, descripciones, secretos con backend en memoria.
- Integración (oculto, sitio local con `http.server` en puerto libre): login con contraseña desde secreto → fecha → "Generar" (aparece tras 2 s) → clic derecho → menú propio → "Exportar" → descarga renombrada `Reporte_{hoy:%Y-%m-%d}.csv`. Se prueba con un flujo escrito a mano **y** grabando (acciones simuladas con Playwright sobre la página mientras graba) y re-ejecutando lo grabado.
- `python bot.py --smoke` construye la ventana y sale.

## Limitaciones
- El **menú contextual nativo del navegador** (Guardar como, Copiar enlace…) no es parte de la página y no se puede automatizar; sí los menús de clic derecho que ofrece la propia web. Para "Guardar enlace como" se usa el paso `descargar`.
- CAPTCHA y verificación en dos pasos (2FA) no se pueden automatizar; el perfil persistente ayuda a no repetir el login.
- Si la web cambia mucho su diseño, puede haber que regrabar algún paso.

---

## v2.1 (correcciones tras probar con webs reales + varios reportes)

Cambios y por qué (diagnóstico de los registros de portal.ejemplo.com e informesweb):

| Problema | Cambio |
|---|---|
| El reporte tardó más que el tiempo máximo del paso; el botón «Descargar» seguía deshabilitado | Los pasos de descarga esperan *visible + habilitado* con `timeout_descarga` (600 s). Cada paso graba `espera_grabada` (segundos desde el paso anterior); tiempo efectivo = `timeout` propio, o `max(timeout_paso, espera×3+30)` con tope `timeout_descarga`. `timeout_paso` por defecto 60 s. Avisos cada ~15 s en registro y barra de estado. Todos los pasos de acción esperan *habilitado*. |
| Calendario (bootstrap-datepicker, 2 instancias en `<body>`) fallaba a ratos | Selectores de texto acotados al ancestro con clase propia (`.datepicker-years span:text-is("2020")`, `tag.clase:text-is`, `:text-is`, y la ruta CSS ya no se ancla a `<body>` dentro de popups). El ejecutor solo acepta candidatos visibles+habilitados y entre varios prefiere el del último popup. Opción `pausa_entre_pasos` (0,3 s). Reintento si la página redibuja. |
| Calendarios = muchos clics frágiles | El grabador detecta calendarios (`datepicker|calendar|picker|flatpickr|daterangepicker|mat-calendar…`), compara el valor de los campos y anota un `escribir` con `fecha_directa` y **desactiva** los clics del calendario. Paso nuevo flag `desactivado`. `escribir` en campos readonly: `fill` o JS (`input`+`change`+`blur`) + Esc, y verifica. Fechas sugeridas: hoy, ayer, inicio/fin de mes y de mes anterior. |
| Contraseña grabada en claro (ojito de «mostrar contraseña») | Un campo es contraseña si alguna vez fue `type=password` (MutationObserver + `data-bot-pw`), por `autocomplete` o por id/name/etiqueta/placeholder (`pass|contrase|clave|pwd`). El ejecutor enmascara en el registro el valor literal de campos de contraseña y la lista no lo muestra. Acción **Convertir en contraseña**. |
| Varios reportes | Las descargas ya no se cancelan al grabar (se guardan en `descargas/grabacion/`), así que un flujo puede tener varios pasos `descargar`. Nuevo módulo `webbot/lote.py` (lista de flujos, `flujos/_historial.json`, `ejecutar_lote`). Panel **Reportes** en la ventana (casillas, última ejecución/resultado, Nuevo/Abrir/Duplicar/Eliminar→`_papelera`, ejecutar seleccionados/todos, programar). CLI: `--flujo` repetible, `--todos`, `--carpeta-flujos`; código 1 si falla alguno. `programador.py` puede programar un lote o `--todos` (solo `schtasks` tras confirmar en la GUI). |
| Informe que se abre como HTML (no se puede «Guardar como») | Paso `guardar_pagina {formato: pdf\|html\|csv, nombre, carpeta}`: CSV = tabla más grande; PDF con `page.pdf` en oculto o impresión en un navegador oculto auxiliar si es visible (si no, HTML y se explica en el registro). Botón «💾 Guardar esta página» en la barra del grabador e «Insertar paso → Guardar página» en la ventana. |

Modelo de pasos: `Paso` gana `espera_grabada`, `desactivado`, `fecha_directa`, `formato` y el tipo
`guardar_pagina`; los flujos antiguos (sin esos campos) se cargan igual. Reglas que se mantienen:
`flujo.py`/`plantillas.py`/`lote.py` no importan playwright; los objetos de Playwright solo viven en
el hilo de trabajo (los lotes corren en un único hilo, un flujo detrás de otro); Tk solo se toca
desde el hilo principal; las contraseñas nunca van a JSON/registros/consola.

Pruebas añadidas: `tests/test_nuevas.py` (modelo, esperas, contraseñas, fechas, lista/historial/lote,
programador por lotes, `--smoke`), `tests/test_integracion_v21.py` (reporte lento con botón
deshabilitado, calendario propio con grabación + reproducción de las dos variantes, contraseña con
ojito, dos descargas, lote CLI con un fallo, `guardar_pagina` csv/html/pdf) y `tests/test_gui.py`
(panel Reportes, lista de pasos, lote desde la ventana). Sitio de prueba ampliado: `lento.html`,
`fechas.html`, `clave.html`, `multiples.html`, `abrir_reporte.html`, `reporte_tabla.html`.

---

## v2.2 (menús con ratón encima, listas con autocompletar, reportes guardados en la aplicación)

Diagnóstico de los registros del 24/10 (erp.ejemplo.com con menús DevExpress; portal.ejemplo.com con
Vue/Vuetify) y petición del usuario de guardar los reportes «en la aplicación, no en un archivo».

| Problema | Cambio |
|---|---|
| «Clic en «Registro De Asistencia»» esperaba 12 s, 52 s o para siempre: el submenú solo se ve con el ratón encima de su opción | Paso nuevo `pasar_raton {selectores, objetivo, auto}` (hover + 0,3 s). El grabador guarda el rastro de `mouseover` reales sobre elementos de menú (≥ 150 ms desde el último paso) y, con un MutationObserver (≤ 600 ms tras pasar) más la comprobación de submenús CSS descendientes, sabe qué abrió cada uno; al hacer clic envía hasta 3 `pasar_raton` (`auto: true`) de la cadena que contiene lo pulsado. Botón de barra «🖱 Pasar el ratón». **Recuperación automática** en el ejecutor (opción `recuperacion_automatica`, por defecto sí): tras ~2 s sin ver el elemento de un clic, una vez por paso: (a) ratón sobre la opción padre (ancestro visible del contenedor oculto, `aria-controls/owns`, ids DevExpress `_DXI1i0_`→`_DXI1_`); (b) repetir los `pasar_raton` anteriores; (c) repetir el clic anterior si abre una lista cerrada (`aria-expanded=false`, combobox…); (d) si existe oculto, ratón por las opciones de los menús visibles. Antes de (a), (b) y (d) el ratón se aparta a (0,0) (si ya estaba encima, la web no recibiría el evento). |
| «Escribir «Detalles Ventas Mayorista» en «Open»» esperaba para siempre (era el texto que Vuetify pone al elegir la opción) | Grabador: no se envía `escribir` si el valor cambió ≤ 800 ms tras pulsar una opción de una lista/menú flotante, o si el campo es combobox/autocompletar y no se tecleó (salvo flechas del teclado); si se tecleó para filtrar, se envía `desactivado` con nota. Ejecutor: `escribir` con el valor ya puesto termina al momento; campo visible pero «no disponible» > 3 s → se escribe igualmente; en combobox se escribe (o se abre si es de solo lectura) y se elige la opción con ese texto. |
| «Clic en «Filtro por reporte»» + «Clic en «div»» abrían y cerraban la lista a velocidad de reproducción | El grabador junta dos clics (< 1 s) en elementos no interactivos del mismo campo (su ancestro común contiene un único control): se queda el último (`reemplaza`). En flujos antiguos lo arregla la recuperación (c). |
| Guardar creaba archivos; el usuario quiere guardarlos en la aplicación | `webbot/almacen.py`: SQLite `datos/bot.db` (`reportes` con nombre único entre los activos, papelera por `eliminado`, `origen` del .json importado; `ejecuciones` = historial). Una conexión por hilo + cerrojo para escribir. Ventana: Guardar pide solo el nombre; Guardar como…; al terminar de grabar se pide el nombre; panel con Abrir (doble clic), Renombrar, Duplicar, Eliminar → Papelera (recuperar / borrar definitivamente); título con «*» y pregunta antes de descartar cambios; Exportar/Importar .json en «Más ▾». Migración automática de `flujos/*.json` y `_historial.json` a la base de datos (una vez; los archivos pasan a `flujos/_importados/`). CLI `--reporte NOMBRE`, `--id N` (repetibles), `--todos` (los guardados), `--db`; `--flujo` sigue valiendo (si el archivo ya se importó, se usa el reporte importado). `programador.py` programa por `--id`. Perfiles del navegador por id: `perfiles/reporte_<id>` (renombrar no pierde la sesión; el perfil de la grabación y el antiguo por nombre se traspasan). |

Reglas que se mantienen: `flujo.py`/`plantillas.py`/`lote.py`/`almacen.py` no importan playwright ni
tkinter; Playwright solo en el hilo de trabajo; Tk solo en el principal; contraseñas nunca en la base
de datos, registros ni consola; las pruebas usan bases de datos temporales y nunca crean tareas.

Pruebas añadidas: `tests/test_almacen.py` (CRUD, nombres únicos, renombrar conserva id/perfil,
papelera, historial, exportar/importar, dos hilos a la vez, migración, lotes por id, CLI
`--reporte/--id/--todos/--flujo` con un ejecutor falso, programador por id),
`tests/test_integracion_v22.py` (menú CSS anidado y menú tipo DevExpress: grabación con `pasar_raton`
y reproducción, flujos solo con clics recuperados, exploración sin ids, repetir ratón previo, modo de la
barra; autocompletar: sin `escribir` bloqueante, etiqueta+cuadro en un clic, valor ya puesto, lista que
se cierra, elegir opción al escribir; CLI con base de datos). `tests/test_gui.py` adaptada (panel desde
la base de datos, guardar/guardar como, nombres repetidos, cambios sin guardar, grabación → nombre,
exportar/importar, migración al abrir). Sitio de prueba: `menu_css.html`, `menu_dx.html`
(`?sin_ids=1`, `?cerrar_ms=N`), `autocompletar.html` (`?modo=alternar`). `--smoke` usa una base de
datos temporal.

---

## v2.3 (inicio de sesión inteligente y esperas de carga)

Petición del usuario: «A veces cuando la contraseña no pasa se detiene, y muchas veces no espera que cosas
carguen… si una página necesita contraseña que la analice y me la pida… y si algo necesita cargar que lo
espere».  Diagnóstico de los registros del 24/10 (11:34–11:48): los pasos «Escribir usuario/contraseña»
fallan si el perfil ya tiene la sesión abierta (no hay formulario) o si la sesión caduca; Portal (Vue/Vuetify)
muestra una rueda 80 s tras «Generar» y la espera «hasta que aparezca «ACME … 24/10/2026 11:32 …»» pasó en
0,0 s con una ruta CSS alternativa que ya coincidía con el informe anterior; el ERP (ASP.NET + DevExpress) hace
postbacks asíncronos.

| Problema | Cambio |
|---|---|
| Inicio de sesión frágil (sesión ya abierta, caducada, contraseña que falta o cambió) | Paso nuevo `iniciar_sesion {sitio, campos[{selectores, etiqueta, tipo texto\|clave, clave, valor \| secreto}], enviar{selectores \| tecla}}` — «Iniciar sesión en «host» (si hace falta)». El ejecutor espera a que cargue; sin campo de contraseña visible (ni «clon» `_CLND` de DevExpress) → «ya había una sesión abierta: se omite». Si lo hay: analiza el formulario (`JS_ANALIZAR_LOGIN`: campos visibles de la misma zona, etiquetas por `<label>`/aria/placeholder/celda anterior, obligatorios, botón de entrar, mensaje de error), rellena con la lógica de «Escribir» (solo lectura, ya relleno, clon de DevExpress), envía, espera y comprueba (desaparece la contraseña o se pasa a otra página con otros campos). |
| «Que me la pida» | `pedir_acceso(solicitud, esperar)` inyectado: la ventana usa `PeticionAcceso` (cola + `threading.Event`; el hilo de trabajo espera bombeando Playwright y atento a «Detener») y muestra «La página «host» pide iniciar sesión» con los campos detectados (contraseñas con `*`, valores conocidos, «Recordar» marcado). Al acertar, contraseñas a keyring (nombre del paso o «host:campo», como el grabador) y el resto a la tabla `accesos` (host + clave del campo). Rechazo: se pregunta una vez («La contraseña fue rechazada…»), nunca se reenvían los mismos datos (huella SHA-256 en memoria) y máximo 2 intentos por sitio y ejecución. Sin ventana (CLI/tareas) → error «Falta la contraseña de «host» (o fue rechazada). Abre el bot y ejecútalo una vez con la ventana para guardarla.» y código 1. Las contraseñas de los `iniciar_sesion` ya no se exigen al empezar. |
| Sesión caducada a mitad / reporte grabado con la sesión abierta | Guardia: si el elemento de un paso no aparece en ~3 s (1,5 s tras «Abrir la página») y la página muestra un formulario de inicio de sesión, se entra con el `iniciar_sesion` del reporte para ese host, con los Accesos guardados o preguntando, y se repite el paso (el tiempo del inicio de sesión no cuenta para el paso). |
| Grabación | `grabador.js` anota en cada evento si el elemento está en la zona de un campo de contraseña (`token` = página + campo) y su papel (`campo`, `enviar`, `incidental`: ojito, recuadro td/div de un campo). Al terminar, `flujo.agrupar_inicio_sesion` junta la secuencia (incluidos clics sueltos antes/entre campos y reintentos) en un `iniciar_sesion`; el clon `_CLND` sobra si está el campo real. |
| Reportes ya guardados | `Flujo` versión 3. Al abrir la ventana (y en la línea de comandos), `Almacen.migrar_formato()` convierte los de versión 2: la secuencia justo después del primer «Abrir la página» con al menos una contraseña `{secreto:}` y el clic de entrar (con el ojito o los clics del recuadro entre medias y los reintentos posteriores) → `iniciar_sesion`. Antes de cambiar cada reporte guarda su JSON en la tabla `versiones` (Más ▾ → Versiones anteriores → Restaurar; restaurar guarda también la actual). Un reporte dañado o cuya conversión no fuera válida se deja igual; se anuncia en el registro y la barra de estado. |
| 🔑 Accesos | Cuadro nuevo (sustituye al botón Contraseñas, que sigue en «Contraseñas sueltas…»): lista por sitio, cambiar valor / contraseña, borrar campo o sitio (con sus contraseñas). |
| No espera a que cargue | `Ejecutor._esperar_carga(pg)` tras cada acción (`TIPOS_CON_CARGA`) y antes de buscar el elemento del paso siguiente: (corto, ≤ 30 s) `readyState` completo, sin peticiones pendientes durante 0,5 s (eventos `request/response/requestfinished/requestfailed`; se ignoran websocket/eventsource/media, analítica, URLs tipo sondeo y las que se repiten ≥ 3 veces en 10 s, y las de más de 15 s), `jQuery.active`; (largo, hasta `timeout_descarga`) indicadores visibles (clases/ids/roles spinner, loading, v-progress, v-overlay--active, mat-progress, blockUI, DevExpress `dxlp`/LoadingPanel, `aria-busy`, `role=progressbar` sin completar, textos «Cargando…/Procesando…/Espere…/Generando…») y postback de ASP.NET. Los indicadores que ya se veían antes de la acción (marcados `data-bot-ind`) solo se esperan con actividad; uno sin cambios en el DOM ni peticiones durante 30 s se da por atascado. Avisos cada ~15 s. Opción `esperar_carga` (casilla en la ventana) y `Paso.esperar_carga` (sí/no/según el reporte en el diálogo). Clic tapado («intercepts pointer events») → esperar carga y reintentar. |
| Esperas que pasan antes de tiempo | Grabador: en modo «Esperar a un elemento» no usa textos con fechas/horas/números largos ni de más de 40 caracteres (usa `:has-text` con un trozo fijo y clases) y el nombre del paso es la parte fija. «Esperar texto» de la barra guarda la parte fija. Ejecutor: antes de una acción marca (`data-bot-pre-N` + huella del texto) lo que ya coincide con los selectores alternativos de las esperas siguientes; la espera solo vale con el principal o con algo nuevo/cambiado (si solo hay lo de antes, se acepta tras 5–30 s con la página tranquila). «Esperar texto» con fechas u horas busca sus partes fijas en orden. Tras una espera también se espera la carga. |

Reglas que se mantienen: `flujo.py`/`plantillas.py`/`accesos.py`/`almacen.py` sin playwright ni tkinter;
Playwright solo en el hilo de trabajo; Tk solo en el principal (la pregunta de acceso viaja por la cola);
contraseñas nunca en la base de datos (la tabla `accesos` solo guarda su nombre), registros ni consola.

Pruebas añadidas: `tests/test_v23.py` (paso, textos que cambian, agrupación con las formas reales de Portal
—métricas con ojito y Recaudos con reintento— y del ERP con clon DevExpress, migración en base de datos con
copia y restauración, accesos, `PeticionAcceso`), `tests/test_integracion_v23.py` (sesión abierta → se omite;
sin sesión → entra; falta la contraseña → se pide con los campos detectados, incluida «Licencia», y se guarda;
contraseña rechazada → se pregunta una vez y nunca se reenvían los mismos datos; sesión que caduca a mitad;
sin paso grabado → se analiza y se pide; cancelar; CLI sin ventana → mensaje y código 1; grabación tipo
DevExpress con ojito y recuadros → un paso; rueda, ASP.NET, jQuery, petición lenta, capa que tapa clics, página
con sondeo cada 200 ms, espera que no vale con lo que ya estaba), `tests/test_gui_v23.py` (pregunta hilo ↔
ventana, Detener la cancela, cuadros Iniciar sesión/Accesos/Versiones, opción de carga, editar el paso,
actualización de reportes al abrir). Sitio de prueba: `login.html` (`?licencia=1`, `?dx=1`, `?volver=`),
`app.html` (`?expira=N`, `?login=`), `carga.html` (`?modo=spinner|aspnet|jquery|xhr|capa`, `?sondeo=1`),
`espera_vieja.html`; el servidor de pruebas responde `/api/lento?ms=N` y `/api/ping`.
Cambios en pruebas anteriores: la grabación del login de `index.html` ahora da un paso `iniciar_sesion`
(`test_b_graba_y_reejecuta`), y `TestEsperasLargas` (que mide los tiempos máximos de cada paso) apaga
`esperar_carga`, porque ahora el bot espera solo a que desaparezca el «Generando…».

---

## v3.0 (rama New-tool)

Petición del usuario (26/10): Portal va lento; «no comprendo cómo funciona la parte de contraseñas» (que se tomen la primera
vez, que avise si cambia y que salga una ventana para poner la nueva); vigilar los cortes semanales de Portal («44 - 2026»
→ «45 - 2026») y descargarlos, y filtrar por días; una opción «Mapear página / Sacar filtros»; y un diseño nuevo más simple,
con los colores de la marca (boceto funcional).

| Problema / petición | Cambio |
|---|---|
| Portal: ~30 s de espera en cada paso de lista («indicador #v-menu-v-32.v-overlay.v-overlay--absolute»), ~2 min por ejecución; el «Pasar el ratón» siguiente fallaba tapado | `JS_ESTADO_CARGA`: los menús/listas/diálogos/popovers/tooltips no son indicadores (`role=menu\|listbox\|dialog\|tooltip\|combobox`, clases `v-menu\|v-select\|v-autocomplete\|dropdown\|popover\|menu…`, capas con opciones/campos/botones). Cada indicador lleva `fuerte`: una capa solo es «fuerte» si contiene `.v-progress-*`, `role=progressbar`, spinner/loader, `aria-busy` o «Cargando…». Los débiles salen a los ~3 s sin actividad (`ESPERA_ESTANCADA_DEBIL`, máx. 10 s con solo animaciones) y van con el tope corto; los fuertes como antes (los ~80 s de «Generar» se respetan). Elemento tapado ≥3 veces → `dispatch_event`. Página de regresión `tests/sitio_prueba/portal.html`. |
| Accesos: «que las tome la primera vez» | `GrabadorWeb(accesos=…)`: al agrupar el inicio de sesión guarda los campos en `accesos` (contraseña: solo su nombre) y emite `accesos` («Se guardaron los datos de acceso de «host»»); el ejecutor hace lo mismo al recordar lo que escribe el usuario (`notificar("accesos_guardados")`). |
| «Si cambia que me avise» y «que salga una ventana para poner la nueva» | Rechazo: `secretos.marcar_rechazada` guarda en el almacén de contraseñas (nunca en la base de datos) una huella SHA-256 del valor rechazado; `estado_claves` (base de datos) guarda la fecha. Mientras la contraseña guardada sea la misma no se vuelve a enviar (ni en otras ejecuciones). Sin ventana: error claro + `avisos.avisar` (notificación de la aplicación, sin repetir, y «toast» de Windows inyectable; nunca en pruebas) «La contraseña de «host» cambió: actualízala en Accesos». Con ventana: la solicitud lleva `tipo: clave_fallida` y la ventana «La contraseña de «host» falló» (sitio, usuario, nueva contraseña con Mostrar, Guardar y reintentar). Al funcionar o cambiarse, la marca se borra y el aviso se da por leído. Página Accesos con estado (guardada/rechazada/falta), Cambiar contraseña, Probar acceso (solo el inicio de sesión, perfil temporal) y Borrar. |
| Cortes semanales: elegir el más reciente | Paso `elegir_opcion {selectores, objetivo, estrategia: fija\|mas_reciente\|primera\|ultima\|contiene, valor}`. `flujo.clave_reciente` (fecha más alta, año, primer número) y `elegir_indice`. Ejecutor: listas nativas (`select_option(index)`) y propias (`JS_OPCIONES`: la lista que controla el campo por `aria-controls/owns` o la visible más cercana; desplaza las listas virtuales; marca la opción y hace clic). `{opcion}` = texto elegido. Conversión bajo pedido (`pares_lista_opcion`, `convertir_listas`), con la forma real de Portal (clic en «div» + `role=option[name=…]`). |
| «Que revise la página y me avise si llegó algo nuevo, y lo descargue» | `webbot/vigilancia.py`: `revisar()` ejecuta el reporte con `Ejecutor(hasta=k, al_final=…)`, lee las opciones del paso k y las compara con `opciones_vistas` (la primera vez es la referencia); avisa de las nuevas y, con `auto_descargar`, ejecuta el reporte una vez por opción (la marca `descargada`, no se repite). Tablas `vigilancias` y `opciones_vistas`. CLI `--vigilar`; `programador` admite `vigilar=True` y `HORAS` (`/SC HOURLY /MO N`). |
| Filtros por días | Opción del reporte `repetir_dias {modo: fijo\|ultimos\|mes_hasta_ayer\|ayer, desde, hasta, n}`: el ejecutor repite los pasos una vez por día en el mismo navegador, con `{fecha}` / `{fecha:%Y-%m-%d}`. «Cada día descargar el día anterior» = `{ayer}` + programación diaria (documentado). |
| «Mapear página / Sacar filtros» | `webbot/mapeador.py` + `mapeador.js` (que reutiliza los bloques `<<selectores-1/2` de `grabador.js`): pestañas, listas propias (se abren y se leen), nativas, fechas, textos, casillas y botones de acción, con etiqueta (label, etiqueta flotante, ayuda anterior, placeholder…), valor, opciones, selectores y orden. `actualizar_opciones` (listas dependientes), `elegir_parte` (resaltado + clic), `generar_pasos`, `aplicar_pasos` (nuevo / reemplazar / añadir), `comparar` (cambios desde el mapa anterior), `punto_de_mapeo` (antes del primer filtro). `SesionMapeo` atiende órdenes en el hilo del navegador. Tabla `mapas`. |
| Diseño nuevo, simple, con colores de la marca | `webbot/servidor_ui.py` (`ThreadingMixIn` + `HTTPServer` de la biblioteca estándar, 127.0.0.1, puerto libre, token por sesión en `X-Bot-Token`, rechazo de Origin/Host/Sec-Fetch-Site ajenos, CSP) + `ui/` (HTML/CSS/JS sin dependencias). Trabajos con navegador de uno en uno en su hilo; eventos por sondeo largo; preguntas del hilo como ventanas. Páginas: Inicio, Reportes, Editor, Grabar, Mapear, Vigilancia, Accesos, Historial, Ajustes. `python bot.py` abre `msedge/chrome --app`; `--clasica` = Tk; `--smoke-web`. Colores en `ui/tema.css` (paleta PROVISIONAL). `ejecuciones` guarda `registro` y `captura`. |

Reglas que se mantienen: `flujo.py`/`plantillas.py`/`accesos.py`/`almacen.py`/`vigilancia.py`/`avisos.py` sin playwright
ni tkinter; Playwright solo en el hilo de trabajo (también el del servidor y el del mapeo); contraseñas nunca en la base
de datos, registros, eventos ni consola (la API solo las recibe cuando el usuario las escribe y van directas a keyring);
las pruebas usan bases de datos temporales, almacén de contraseñas en memoria, notificador falso, nunca crean tareas.

Pruebas añadidas: `tests/test_v30.py`, `tests/test_integracion_v30.py`, `tests/test_servidor_ui.py` (ver README §15).

## v3.1 (rama New-tool)

Petición del usuario (26/10): «El sistema de mapeo funciona, pero lo que quiero es que me traiga esos filtros para yo
utilizarlos y que se actualicen si vigilancia detecta algo nuevo… en vez de 44 quiero el 43, 42, etc.»; y un fallo: la
Vigilancia mostró «45 - 2023» arriba como si fuera el corte nuevo y se descargó ese.

| Problema / petición | Cambio |
|---|---|
| Vigilancia mostraba «45 - 2023» arriba (`ui/app.js` invertía el orden de la página) | `servidor_ui._opciones_recientes`: de la más reciente a la más antigua con `clave_reciente` (empates: orden de la página), `mas_reciente` y `periodo` (`flujo.describir_opcion`); la página no invierte y marca «más reciente». |
| Lo antiguo que aparece por primera vez contaba como «nuevo» | `Almacen.registrar_opciones(detalle=True)`: nueva solo si `clave_reciente` > la más reciente conocida antes de la revisión; las antiguas = históricas (en silencio); sin fecha/año/número (o sin referencia) = `sin_orden`: aviso «Opción nueva… (sin fecha)», sin descarga automática salvo `vigilancias.descargar_sin_fecha`. `opciones_vistas.novedad` (fecha de la novedad). «Llegó un corte nuevo…» solo para las recientes (y se arregló «Llegó una opción nuevo»: `nombre_de_la_novedad` deduce «corte» de las opciones si el paso se llama «Open»). |
| «Que me traiga esos filtros para usarlos» | `webbot/filtros.py` (sin playwright): `pasos_filtro` (elegir_opcion, seleccionar, escribir fecha), `nombres`/`nombre_filtro`, `datos_panel`, `combinaciones` (producto cartesiano), `aplicar` (copia + « - <opción>» en el nombre del archivo si no lleva `{opcion}`), `guardar_predeterminado`, `resolver_cli`. API `reportes/<id>/filtros` (GET/POST datos, `descargar` con confirmación > 10, `predeterminado` con `guardar_version`, `nombre`, `actualizar`). Panel «⚙ Usar filtros» en Reportes, Editor y Vigilancia. |
| Opciones guardadas y al día | Tabla `opciones_filtro (reporte_id, paso, padres, firma, opciones, actualizado, fuente)`; `ResultadoEjecucion.opciones_leidas` (el ejecutor anota cada lista que lee, con lo elegido antes = `padres`, y la `firma` del campo); se guardan en `registrar_resultado` (ejecución), en la vigilancia, al crear pasos desde el mapa (`mapeador.opciones_para_cache`) y con «Actualizar opciones» (`Ejecutor(hasta=último filtro + 1, solo_leer=True)`). Listas dependientes: búsqueda exacta → compatible → la última conocida con nota. |
| Filtros llamados «Open» | `flujo.etiqueta_generica` (Open/Close/Abrir/iconos/flechas/etiquetas HTML); `mapeador.js`: etiqueta flotante antes que aria-label, se descartan las genéricas, se mira el «hint» del campo; `paso_de_filtro` guarda `Paso.filtro` (campo nuevo). Para reportes ya creados el panel enlaza los pasos con el mapa por selectores o por valor y corrige el nombre al mostrarlo (se guarda con «Guardar como predeterminado» o «Renombrar»). |
| Ejecutar con otros filtros | `Ejecutor(filtros={paso: {estrategia, valor}})` (registra los cambios); `seleccionar` cambiado → «Elegir opción» por texto. CLI `--filtro "NOMBRE=VALOR"` (repetible; nombre o número de paso). |

`portal.html` lleva ahora `aria-label="Open"` en los campos de las listas (como Vuetify 3). Pruebas: `tests/test_v31.py`,
`tests/test_integracion_v31.py`; `--smoke-web` abre también el panel «Usar filtros».

## v3.2 (rama New-tool) — «Páginas»

Petición del usuario (26/10): que el mapa no sea de un solo uso sino «como si fuera la propia página, para cuando quiera
utilizarla»: una sección **Páginas** con una tarjeta «Portal – Reportes» cuyo formulario (Pestaña, Filtro por sistema,
Seleccione reporte, Elegir corte, Formato) se rellena y descarga por detrás; varias opciones = varios archivos;
favoritos («Mayorista + corte más reciente + Excel») ejecutables y programables; la vigilancia marca el corte nuevo en la
lista; listas dependientes recordadas por combinación y traídas bajo pedido; y «crea un botón para que el bot no tenga
que abrir un navegador para hacerlo».

| Petición | Cambio |
|---|---|
| Página reutilizable | `webbot/paginas.py` (sin playwright): `data` = `llegada` (pasos para llegar: abrir_url, iniciar_sesion, clics/ratón de menús), `filtros` [{id, nombre, tipo pestana\|lista\|lista_nativa\|fecha\|texto\|casilla, selectores, depende_de, en_nombre, defecto, pestanas, formato, nombre_origen}], `accion` {tipo descargar\|boton_descarga\|menu_exportar\|guardar_pagina\|pasos, generar, descargar, menu, exportar, formato, pestana, pasos}, `nombre_archivo` (`{pagina} - {variantes}`, `{Nombre del filtro}`, `{hoy:…}`), `favoritos`, `opciones`, `sin_navegador`, `perfil`. Tablas `paginas`, `opciones_pagina` (página + filtro + combinación de los filtros anteriores), `vigilancias_paginas`, `opciones_vistas_paginas`. `ejecuciones` gana `pagina_id` y `reporte_id` pasa a admitir NULL (la tabla se copia entera al abrir una base de datos anterior: mismos ids). |
| Ejecutar | `construir_flujo` = llegada + un paso por filtro (pestaña → clic en su selector; lista → «Elegir opción» fija/estrategia; fecha/texto → «Escribir»; casilla → «Marcar») + pasos de la acción; lo ejecuta el `Ejecutor` de siempre (esperas, guardia de inicio de sesión, recuperación). El ejecutor guarda lo elegido en cada filtro con nombre como variable `{Nombre del filtro}` (con «la más reciente», el texto elegido de verdad) y escribe `lineas_inicio` en el registro. `ejecutar()` = una ejecución por combinación (confirmación > 10, máx. 100), historial y caché de las listas leídas. |
| Crear desde el mapa | «Mapear página» → **Guardar como Página…** (`mapa/propuesta`: llegada = pasos ejecutados antes de mapear —o «abrir» la dirección a la que se navegó a mano—, filtros con nombre, botones, acción adivinada con `RX_GENERAR`/`RX_DESCARGAR` y los pasos del reporte; **Detectar dependencias** = orden `dependencias` de `SesionMapeo` → `mapeador.detectar_dependencias`, que elige otra opción en cada lista y vuelve a leer las siguientes). `POST /api/paginas`. |
| Mapa real de Portal | `paginas.convertir_mapas` (una vez, `meta.paginas_convertidas`, desde `bot.migrar_reportes`): cada reporte con mapa → Página («Portal – Reportes» por `nombre_sugerido`), con la llegada del reporte (antes de `punto_de_mapeo`), los valores de sus pasos (enlazados por selectores), la acción (el reporte solo pulsaba «Generar» → Generar + «Descargar») y el perfil `reporte_<id>`. No cambia el reporte ni el mapa. Las etiquetas «Open» del mapa 3.0 → «Lista N»/«Corte (2)» (provisionales): «Actualizar opciones» mapea la página al final (`al_final` sin abrir listas) y `corregir_nombres` pone la etiqueta de la web. |
| Formulario | `#/paginas/<id>`: `paginas.formulario` (periodos de la más reciente a la más antigua, «La más reciente (hoy: …)», «nueva», actualizado/fuente, `desconocida` si depende de otro filtro y no se conoce → la página pide `traer` = ejecución oculta hasta esa lista con `solo_leer`), Elegir varias, Generar y descargar, Actualizar opciones, favoritos (ejecutar, programar, borrar), valores por defecto, vigilancia, archivos con «Abrir archivo»/«Abrir carpeta» (`/api/archivos`, solo dentro de las carpetas de descargas y con extensiones de documento), historial, «Configurar esta página». Dependencias aprendidas solas (`detectar_dependencias`: listas distintas con otro valor en un filtro anterior; no cuenta que lleguen ≤ 3 opciones nuevas) salvo las puestas a mano. |
| Vigilancia | `vigilancia.revisar_pagina` / `descargar_opcion_pagina` (misma regla de novedad de la 3.1 con `_registrar_vistas` generalizado), con los valores de un favorito; las opciones van a la caché de la Página; aviso con «Descargar»/«Abrir la página». CLI `--vigilar --pagina-id N`; `--vigilar` solo revisa también las Páginas vigiladas. |
| CLI y tareas | `--pagina NOMBRE` / `--pagina-id N` [`--favorito X`] [`--filtro "Nombre=Valor"`…] (sin ventana; código 0/1/2). `programador.comando_bot(pagina_id, favorito)` → `--pagina-id N --favorito "X" --sin-ventana --oculto`. |
| «Sin abrir navegador» | Interruptor «Sin abrir navegador (en segundo plano)» con ayuda (usa un navegador invisible; las preguntas de acceso siguen saliendo en el bot): en cada Página (por defecto encendido, `data.sin_navegador`; los favoritos guardan el suyo), en Reportes (= lo contrario del ajuste «Ver mientras trabaja») y en «Usar filtros». |

Reglas que se mantienen: `paginas.py` sin playwright ni tkinter; Playwright solo en el hilo de trabajo; contraseñas nunca
en la base de datos, registros ni eventos; las pruebas usan bases de datos temporales, contraseñas en memoria, ningún
archivo se abre de verdad (`Aplicacion.abrir_en_sistema` inyectable) y no se crean tareas.

Pruebas: `tests/test_v32.py`, `tests/test_integracion_v32.py` (README §18.6); sitio de prueba `portal.html?boton=1`,
`informes.html` + `informes_reporte.html`, `erp_consulta.html` (+ `/api/erp/descarga`); `tests/fijos/portal_mapa.json`
(forma real del mapa 1 y el reporte 10, copiada en solo lectura). `--smoke-web` abre la lista de Páginas y una Página.

No verificado contra las webs reales: los selectores del botón «Descargar» de Portal (adivinados por su texto), los
nombres «de verdad» de las listas de Portal al «Actualizar opciones», Informes y el ERP reales.


## v3.3 (rama New-tool) — mapear otras webs y varias vigilancias

Petición del usuario (26/10): «El mapeo solo funciona en Portal» (los mapas guardados son solo de Portal; las sesiones de
Informes, del ERP y de otra web terminaron sin mapa y sin ningún diagnóstico) y «el estado de vigilancia solo me deja
colocar a uno, tiene que permitirme colocar a más de uno».

| Problema | Causa encontrada | Cambio |
|---|---|---|
| ERP: el mapa salía vacío | El mapeador solo analizaba el documento principal (`pg.evaluate`), y en el ERP la consulta está DENTRO del iframe `#tab0_Frame` (todos los pasos grabados del ERP llevan `marco: ["#tab0_Frame"]`). Además «Consultar»/«Vista Exportar» son opciones de menú de DevExpress (`li.dxm-item`), no botones, y las listas/fechas de DevExpress (`…_I` + `…_DDD_L`) salían como textos | `mapeador.marcos()` recorre todos los marcos (también de otra web, hasta 4 niveles) con su cadena de selectores; cada filtro lleva `marco` y `pagina`, que pasan a los pasos («Crear pasos»), a la Página (filtros y botones de la acción, `_boton(d, lugar)`) y a «Guardar el mapa». `mapeador.js`: ASPxComboBox (opciones leídas de la lista oculta `…_DDD_L`), ASPxDateEdit, leyendas `dxflCaption/dxeCaption`, opciones de menú DevExpress como botones y «Vista Exportar» como submenú (`adivinar_accion` → `menu_exportar` en el mismo marco). El ejecutor abre las listas de DevExpress por su botón `…_B-1` |
| Una web con un control raro: no salía nada | `window.__botMapear` era todo o nada: una excepción en un control (p. ej. un `value` que lanza error) hacía fallar el `evaluate` y la orden «mapear» devolvía solo un aviso pasajero | Cada control se analiza en su `try` (`errores`); los marcos que no se pueden leer, también |
| Informes: mapa pobre | Etiquetas en celdas de tabla y nombres ASP.NET; el desplegable del usuario de la barra (Bootstrap `dropdown-toggle`) se tomaba por una lista (y al «leerla» se pulsaba su enlace `#`); `<input type=image>` («Ver Reporte» como ImageButton) no se reconocía; «Cuenta No.» (campo con lupa) salía como texto sin más | Etiqueta por celda anterior/cabecera de columna, texto anterior, `aria-labelledby`, `title` y, si no hay nada, el name/id legible («ctl00$formContent$txtFechaIni» → «Fecha Ini»): nunca se descarta un control por no tener etiqueta. Los desplegables de la barra/menú lateral no son filtros. Fechas de bootstrap-datepicker (clase `date`/`datepicker`, icono de calendario, valor `2026-10-01`). Botones `input[type=image]`, enlaces con aspecto de botón (`a[class*=btn]`, `javascript:`). «Texto con búsqueda»: el botón lupa queda en `busqueda`; «Leer opciones de la búsqueda» (orden `busqueda`) pulsa la lupa, lee las filas de la ventanita y la cierra; en la Página, elegir una fila = clic en la lupa + clic en la fila (`paginas.pasos_de_filtro`). «Ver Reporte» se adivina como «guardar la página que se abre en otra pestaña» (pestaña = la del formulario + 1) |
| Pestaña equivocada | `SesionMapeo._pagina` mapeaba siempre la ÚLTIMA pestaña abierta, no la que el usuario estaba viendo (si volvía a otra pestaña o la web abría una ventana auxiliar) | `pestanas()`: la que tiene el foco o se ve (`visibilityState`), si no la que se abrió/navegó la última; la interfaz muestra «Pestaña» para elegirla cuando hay varias (orden `pestanas`, `mapear {pestana}`). Si el formulario estaba en otra pestaña y la Página abre su dirección, sus filtros pasan a la pestaña 1 (`con_pestana`) |
| Sin explicación ni registro | Mapa vacío = tabla vacía; un error = un aviso que desaparece; el mapeador no escribía nada en `registros/` | `avisos_del_mapa`: inicio de sesión detectado, página cargando, sin controles, controles no reconocidos, marcos ilegibles, controles con error. `guardar_diagnostico` → `registros/mapas/<fecha>_<sitio>/` (captura, pestañas y marcos, resumen de controles por documento SIN valores de contraseña, errores, LEEME.txt) cuando sale vacío o algo falla; la ruta sale en la interfaz. Cada orden queda en el registro de la sesión («Mapear toda la página: pestaña 1 de 2 — …», nº de elementos, avisos, errores) |
| Una sola vigilancia | `vigilancias.reporte_id` y `vigilancias_paginas.pagina_id` eran la clave primaria; `opciones_vistas*` iban por reporte+paso / página+filtro | Tabla `vigilancias` nueva (id propio; reporte_id+paso o pagina_id+filtro; `favorito`, `valores` JSON con los otros filtros, `nombre`) y `opciones_vigiladas` por vigilancia: la misma lista con otros valores no se mezcla. Conversión automática al abrir: ANTES se copia el archivo a `bot.db.antes-v3.3` (API de copia de SQLite); las filas (y sus opciones vistas) se copian y las tablas antiguas quedan como `*_v32`; lo visto de la 3.2 sirve de referencia a la primera vigilancia nueva de esa lista. API `/api/vigilancias` (crear, cambiar, borrar, opciones, revisar, descargar, programar, «revisar todas»); las rutas de la 3.2 siguen (vigilancia principal). Avisos con la etiqueta de la vigilancia y su `vigilancia_id`; la marca «nueva» del formulario junta todas. Tareas por vigilancia (`--vigilancia-id N --vigilar`); `--vigilar` revisa todas las activas (reportes y Páginas) |

Pruebas: `tests/test_v33.py` (sin navegador: varias vigilancias de Página y de reporte con otros valores, novedad y
descarga independientes, avisos, conversión desde la tabla antigua con copia, API, programar, CLI, acción adivinada,
pasos en un marco y con búsqueda, avisos del mapa) y `tests/test_integracion_v33.py` (navegador oculto, por la API como
el usuario: `informes2_*` —menú → formulario en la misma pestaña, celdas, datepicker, lupa con tabla, «Ver Reporte» en
otra pestaña→CSV—, `erp2_*` —formulario en un iframe con DevExpress y menú de exportar→descarga—, `nueva_pestana.html`,
`sin_filtros.html`, `login.html` y `control_roto.html`; dos vigilancias reales de la misma lista de `portal.html` con otro
reporte, cada una descarga lo suyo; `--vigilancia-id`; la página Vigilancia).

No verificado contra las webs reales (no hay acceso desde aquí): Informes (si «Ver Reporte» es `input type=image` o
submit, la ventanita real de «Cuenta No.»), el ERP (que el iframe se llame siempre `#tab0_Frame` y que las listas
DevExpress del ERP lleven `…_DDD_L`) ni el sitio de terceros (play.pokemonshowdown.com: un mapa en oculto de su portada
sí encuentra controles, así que allí la sesión acabó probablemente sin pulsar «Guardar» por el resultado pobre).


## v3.3.1 (rama New-tool) — correcciones con las webs reales

Petición del usuario (28/10): «Sigo teniendo los mismos errores. El estado de vigilancia no puedo agregar a uno que ya
existe; en el ERP tampoco me está dejando colocar la contraseña bien; y el mapeo no tiene sentido: en parte mapea pero la
página toda no hace nada.»  Diagnóstico con `registros/2026-10-28_*.log` y sus capturas.

| Problema | Causa | Cambio |
|---|---|---|
| La Página de «mapear toda la página» (y el «Reporte mapeado») no llegan a la página | Empiezan en `…/portal/#/reportes/corte`; sin sesión la guardia inicia sesión bien, pero Portal lleva SIEMPRE a `#/inicio` y el bot esperaba 60 s la pestaña «Corte» | `Ejecutor._destinos` (página → URL del último `abrir_url`); `_volver_tras_login` tras la guardia y tras el paso `iniciar_sesion`: si `hay_que_volver(actual, destino)` (distinta sin contar `?…` pero con la ruta tras `#`; no si el destino es de inicio de sesión —`RX_URL_LOGIN`, o la dirección donde estaba el formulario si al entrar se pasa a otra ruta (no solo otro «#/…»)— o la raíz) → `goto(destino)` + esperar carga, con registro «tras iniciar sesión la web fue a «…»: se vuelve a «…»». Clic en una pestaña ya elegida (`JS_PESTANA_ELEGIDA`: `aria-selected`, `--selected`, `.active`) = hecho |
| ERP: «El campo LICENCIA esta vacio (es un dato obligatorio)» marcó la contraseña como rechazada; luego «Faltan datos…: Contrasenia» | Todo fallo con el formulario a la vista se trataba como contraseña rechazada; la respuesta vacía (el usuario ya había entrado a mano: la captura muestra la sesión abierta a las 12:41:59) acababa en error | `accesos.tipo_de_fallo` (`RX_CAMPO_OBLIGATORIO` / `RX_CREDENCIAL`), `nombra_campo` («LICENCIA» → `txtLicencia`/«Licencia»); dato obligatorio → `_cerrar_mensaje` (`JS_MARCAR_CIERRE_MENSAJE`: botón «Aceptar/OK/Cerrar» de una capa sin contraseña, o Escape), se rellena desde Accesos y se reintenta (no cuenta como intento ni se recuerda la huella; máx. 2) o se pide SOLO ese dato (`solicitud.obligatorio`); con todo relleno y sin mensaje → rechazo como antes. `accesos.identidad_campo` (`X`, `X_I`, `X_I_CLND`, `$`/`_`, «host:…») en `_plan_login`: sin duplicados, Accesos por identidad, campos de Accesos que se ven en la página. `forzar` = teclear de nuevo; comprobación de campos que se vaciaron solos. `_activar_clon` con cualquier selector. Tras preguntar: si el formulario ya no está, «se inició a mano» y se sigue; respuesta incompleta → se vuelve a preguntar (máx. 3). La ventana: una caja por clave y no envía la contraseña vacía |
| No se podía deshacer la marca | — | `estado_claves.motivo` (lo que dijo la página; columna nueva); la marca con motivo de dato obligatorio se quita sola; API `POST accesos/<host>/quitar_rechazo` y botón «Quitar marca de rechazada» + «La página dijo…» en Accesos |
| Vigilancia: no se podía añadir a un reporte existente | Solo se ofrecían pasos `elegir_opcion`; «POrtal» tiene sus listas como clics y solo salía «Abrir en el editor» | `GET vigilancia` devuelve todos los reportes con `listas_clic` (pares de `pares_lista_opcion` con descripción «Lista donde se eligió «…»») y `selects`, y todas las Páginas; `POST vigilancias` con `par` o `seleccionar` → `_convertir_para_vigilar` (copia en `versiones`, «más reciente» si la opción lleva fecha o año, si no «fija»; `Almacen.renumerar_pasos` corrige las vigilancias y las opciones guardadas de los pasos siguientes). Interfaz: «＋ Añadir vigilancia» arriba (buscador, explicación si no hay listas → «Mapear página»), la estrategia en la ventana, todos los candidatos en la página |

Pruebas: `tests/test_integracion_v331.py` (README §20.4); sitio de prueba `portal_spa.html` (`?redir=1`, `?auto=1`) y
`erp_login.html` (`?borra_licencia=1`). `--smoke-web` abre también «＋ Añadir vigilancia» y elige un reporte.

No verificado contra las webs reales: la vuelta a `#/reportes/corte` con la sesión real de Portal, otros mensajes del ERP y
que su ventanita se cierre igual que en la página de prueba.


## v3.4 (rama New-tool) — programación completa y correo

Petición del usuario (29/10): «No lo busca cada cierto día de la semana, ni a cierta hora de cierto día de la semana. Tiene
que ser mucho más completo.»  (Parte 1: programación.  La parte 2, la sección «Correo», reutiliza este modelo.)

| Problema | Cambio |
|---|---|
| Una vigilancia solo admitía `frecuencia` '' / 'horas' (cada N h) / 'diaria' (una hora); los reportes y Páginas, DIARIA/SEMANAL a UNA hora (`schtasks /Create` por línea de comandos solo admite un disparador por tarea) | `webbot/horario.py` (sin playwright): programación = `{"reglas": [...], "inicio": "AAAA-MM-DD"\|"", "fin": ...}` con reglas `semanal` {dias, horas[]}, `intervalo` {dias, cada_min ≥ 15, desde, hasta (incluida)}, `mensual` {dias_mes [1–31, "ultimo"], horas, meses}, `mensual_semana` {semanas [1–4, "ultima"], dias, horas, meses}; días `lun mar mie jue vie sab dom`; varias reglas = horas distintas según el día. `normalizar` (forma canónica, errores en español, máx. 48 disparadores), `describir` («de lunes a viernes a las 09:00 y 15:00; los viernes cada 2 h de 08:00 a 18:00»), `proximas(prog, n, ahora)` (hora local sin zona, último día del mes, bisiestos, días 29–31), `texto_fecha`, `vista`, `avisos`, `desde_antiguo`, `de_vigilancia` |
| Tareas con varios disparadores | `programador.disparadores` / `construir_xml_tarea` (CalendarTrigger: `ScheduleByWeek`, `ScheduleByMonth` con `Day` = `Last`, `ScheduleByMonthDayOfWeek` con `Week` 1–4/`Last`, `Months`; «cada N horas» = `Repetition` Interval + Duration = hasta − desde + 1 min; `StartBoundary` = inicio u hoy, `EndBoundary` = fin 23:59:59; `Principal` = usuario de la sesión con `InteractiveToken` + `LeastPrivilege`; `IgnoreNew`, también con batería, límite 12 h; `Exec` = `separar_comando(comando_bot(...))`) y `crear_con_xml` (UTF-16 en un archivo temporal que se borra; `schtasks /Create /XML … /TN BotWeb\… /F`; exige `confirmado`, `ejecutor` inyectable). Comprobado con el propio Programador (`Schedule.Service` → `NewTask(0).XmlText`, que no registra nada). La línea de comandos de las tareas no cambia (las tareas antiguas siguen valiendo) |
| Guardar la programación | `vigilancias.programacion` (JSON; columna nueva al abrir, sin copia: solo se añade); con programación `frecuencia` = 'programa' (o '' sin reglas) y se vacían `hora`/`cada_horas`; la API antigua (solo `frecuencia`) borra la programación y vale la frecuencia. `Almacen._fila_vigilancia` devuelve `programacion` = la que vale (la guardada o la convertida). Tabla `programaciones` (clave «reporte:N», «pagina:N[:favorito]», después «correo:N»; programacion, tarea, actualizado): `guardar_programacion`, `programacion`, `lista_programaciones`, `borrar_programacion` |
| «La frecuencia sola no hace nada» (el usuario no lo sabía) | API: `POST /api/horario` (vista previa), `vigilancias/<id>/programar` sin `frecuencia` = XML con su programación (o la que se pase), sustituye la tarea de la misma vigilancia con otro nombre (`… #N`); `vigilancias/<id>/quitar_tarea`; `GET`/`POST reportes/<id>/programar` (`programacion`; GET = lo guardado y si existe la tarea) y `reportes/<id>/quitar_tarea`; `paginas/<id>/programar` con `programacion` / `consultar` / `quitar`. `_vig_dict`: `cuando`, `proxima` y `tarea {existe, nombres, proxima}` (con `listar_tareas`, solo lectura). `Aplicacion(ejecutar_tareas=…)` inyectable. Inicio: vigilancias con su próxima revisión calculada y `sin_tarea`; las tareas de reportes/Páginas con su horario en palabras |
| Interfaz | `editorCuando(prog, {textoNunca})` (`ui/app.js`): modo (solo a mano / días y horas / cada N horas / mensual / varios), por horario: tipo, días (chips + Todos / Lunes a viernes / Fines de semana), lista de horas (＋ hora, ✕), cada N horas o minutos de–a, días del mes + «Último día del mes», primer…último + día, meses; «＋ Añadir otro horario»; fechas de inicio/fin; descripción y próximas 5 desde `/api/horario`. `confirmarTarea` (nombre, horario, próximas, disparadores, programa, comando schtasks, XML) antes de crear. Vigilancia: «Cuándo revisar» en la ventana; al guardar con horario, si no hay tarea → «Activar: crear la tarea en Windows» (o «Actualizar…» si cambió, «Quitar la tarea» si pasa a manual); la tarjeta dice si tiene tarea. «Programar…» de reportes y de Páginas/favoritos con el editor, estado de la tarea y «Quitar la tarea de Windows» |

Reglas que se mantienen: `horario.py`/`almacen.py` sin playwright ni tkinter; la tarea se crea solo tras la confirmación
del usuario (la interfaz muestra lo que se creará), oculta, con su usuario y solo con la sesión iniciada; las pruebas
nunca ejecutan schtasks (`ejecutar_tareas` falso y `programador._ejecutar` parcheado para fallar), usan bases de datos
temporales y ningún aviso de Windows.

Pruebas: `tests/test_v34.py` (README §21.4); `--smoke-web` abre el editor «Cuándo» de una vigilancia (añade un horario
mensual con «último día») y la confirmación de «Programar…» de un reporte (con un schtasks falso).

No hecho / pendiente: la ventana clásica (Tk, `--clasica`) sigue con su «Programar» antiguo (diaria/semanal/cada N h, una
hora); no verificado creando una tarea real en este equipo (por norma, las pruebas no crean tareas; el XML sí lo acepta
el Programador).

### Parte 2: «Correo»

Petición del usuario (29/10): «Me gustaría que hubiera una parte llamada gmail. Que esta pueda buscar un gmail, descargar
los archivos, documentos o copiar cierto texto… identificar al gmail: primero, tomar su asunto, fecha, persona, parte del
cuerpo… Tener los mismos filtros que ya tenemos pero funcional… Hay un programa que hicimos… modificarlo para que no
solamente busque uno sino varios.»  El correo de la empresa es Outlook/Microsoft 365 y el programa existente (Octopus,
`data_correo/motor/descargar_reporte.py` + `reglas.py` + `email/imap_client.py`, solo lectura) usa Outlook en la web: se
admiten **Outlook, Gmail e IMAP**.

| Petición | Cambio |
|---|---|
| Cuentas | `cuentas_correo` (proveedor `outlook_web` \| `gmail_web` \| `imap`, dirección, url opcional, host/puerto/usuario/ssl/carpeta, estado de la sesión). Navegador: perfil persistente `perfiles/correo_<id>` (`navegador.abrir_contexto`); «Iniciar sesión en el correo» = ventana visible en la que entra el usuario (el bot espera hasta 10 min a la bandeja y NUNCA escribe la contraseña). IMAP: contraseña en keyring (`correo_imap:<id>`). Sesión caducada (`ErrorSesion`: campos de inicio de sesión visibles ~20 s seguidos, como Octopus; IMAP: login rechazado o sin contraseña) → cuenta «caducada», aviso `correo_sesion` (sin repetir) y toast; al volver a funcionar el aviso se da por leído |
| Identificar el correo (varios) | `correo.normalizar_criterios`: asunto contiene, remitente contiene/exacto, fecha (cualquiera/hoy/ayer/últimos N días/desde–hasta con plantillas), trozos del cuerpo, «tiene adjunto», nombre/extensión del adjunto; `normalizar` de Octopus (sin mayúsculas, acentos ni puntuación). `coincide(fase="resumen")` con la lista (lo desconocido no descarta) y `fase="detalle"` con el correo abierto. Se procesan TODOS los nuevos, del más reciente al más antiguo, `max_por_vez` (10). `correos_procesados` (clave = id del proveedor + fecha —en Outlook/Gmail el id es el de la conversación— o huella remitente+asunto+fecha; estado ok/error/descartado, archivos, valores, acciones hechas, intentos ≤ 3); «Volver a procesar» |
| Acciones | `aplicar_acciones`: adjuntos (todos o por nombre/extensión, .zip descomprimido, carpeta y nombre con plantillas + `{fecha_correo:…}`, `{asunto}`, `{remitente}`, `{adjunto}`, `{ext}`, `{n}`; `ruta_libre` y `nombre_archivo_seguro` del ejecutor); texto («después de», «entre», regex) → aviso/historial y opcionalmente fila en .csv (;) / .xlsx / .txt; tabla del cuerpo (n-ésima, de `reglas.py`) → .xlsx (agregar / reemplazar / hoja por mes) o .csv; cuerpo → .html/.txt. Una acción que falla no para las demás; los reintentos solo hacen las que faltaron (nunca se duplican filas). openpyxl ya estaba instalado (si no, CSV) |
| Proveedores | `correo_web.AdaptadorWeb` (abrir perfil, esperar bandeja cada 0,4 s, sesión, descargas capturadas en el contexto + recuperación de la carpeta «Descargas» —GUID.tmp estable o el nombre esperado—, `ctx.request` para enlaces). `correo_outlook`: buscador tecleado pulsación a pulsación + Enter, resultados = URL «search» o filas cambiadas, filas `[data-convid]` (texto + title/aria-label; fecha M/D o D/M desempatada por el día de la semana), panel de lectura («Cuerpo del mensaje»…), tarjetas `[role=option]` → «Más acciones» → «Descargar», si no «Descargar todo» (.zip). `correo_gmail`: `#search/<operadores>` (`consulta_gmail`), `tr.zA`, `h2.hP`/`span.gD`/`div.a3s`, `span.aZo`. `correo_imap`: SEARCH con SINCE/BEFORE/FROM/SUBJECT (solo ASCII), `BODY.PEEK` y carpeta en solo lectura |
| Programar y ejecutar | Programación de la parte 1 (`horario`); `_programar_con_horario` con tarea «Correo <nombre> #N» (`programador.comando_bot(correo_id=…)` → `--correo-id N --oculto`; `--correos` = todas) y clave «correo:N». CLI `bot.py --correo-id N [--oculto\|--visible]`, `--correos` (0/1/2). `revisar_varias` comparte el navegador entre las búsquedas de una misma cuenta. Avisos `correo` («Llegó «…»: 2 archivos guardados, Total ventas: 1.234», con los archivos), `ejecuciones.correo_id` (historial con rutas completas y registro en `registros/…_correo_…log`), «Próximas» del Inicio con la próxima revisión y «sin tarea de Windows» |
| Interfaz | Menú «Correo» (✉). Cuentas (estado de la sesión, Iniciar sesión en el correo / Probar conexión, Comprobar sesión, Cambiar, Borrar) y búsquedas como tarjetas (cuándo, última revisión, tarea de Windows, Revisar ahora, Editar, Programar, Pausar, Borrar, últimos procesados con Abrir archivo y Volver a procesar). Editor: Cuenta, ¿Qué correo? (con «Probar búsqueda»: trabajo oculto → evento `correo_prueba` con los correos que coinciden, sus adjuntos y por qué no vale cada uno, sin procesar nada), ¿Qué hago con él? (lista de acciones), Cuándo (`editorCuando`) y, al guardar con horario, «Activar: crear la tarea en Windows». API `/api/correo` (cuentas, búsquedas, probar, revisar, procesados, reprocesar, programar, quitar_tarea); «Abrir archivo» admite las carpetas absolutas de las acciones |

Reglas que se mantienen: `correo.py`/`almacen.py` sin playwright ni tkinter; Playwright solo en el hilo de trabajo; la
contraseña IMAP solo en keyring; nunca se escribe la contraseña de Microsoft/Google; las pruebas usan bases de datos
temporales, contraseñas en memoria, avisos falsos, schtasks falso, buzones de prueba locales e imaplib simulado.

Pruebas: `tests/test_v34_correo.py`, `tests/test_integracion_v34_correo.py` (README §22.5); sitio de prueba
`correo_outlook.html` (`?auto_login=MS`, `?sin_menu=1`) y `correo_gmail.html` (`?auto_login=MS`) con el buzón de
`servidor_prueba.py` (`/api/correo/…`, `estado["correo_login"]`, `estado["correos_extra"]`). `--smoke-web` abre la página
Correo, su editor y la ventana de una cuenta IMAP.

No verificado contra el Outlook ni el Gmail reales (sin acceso desde aquí): los selectores (los de Outlook vienen de
Octopus, que sí funcionaba con un correo; los de Gmail, de su estructura conocida), la recuperación de descargas nativas
y el comportamiento con conversaciones agrupadas.  No hecho: la ventana clásica (Tk) no tiene «Correo».

## v3.5 (rama New-tool) — diseño «Centro de control» y arreglos

### Parte 1: tres arreglos

Petición del usuario (29/10): «El bot no suele colocar el nombre completo del reporte»; «en vez de escribir la dirección,
que la pueda seleccionar desde la carpeta: que abra la carpeta para que seleccionen»; y en Correo, poder procesar
cualquier correo aunque no sea nuevo y ver todos los relacionados, «como en Portal con los cortes».

| Problema | Causa encontrada | Cambio |
|---|---|---|
| Archivos «report_xls (6).xlsx», «DetallesVentasMayorista (3).xlsx» en vez del nombre del reporte | Al grabar, `grabador_web._procesar_descarga` ponía en el paso «Descargar» el nombre que sugiere la web convertido en plantilla (`fechas_a_plantilla(base) + "{ext}"`): un nombre FIJO, igual en cada ejecución, que `ruta_libre` numeraba. Comprobado (solo lectura) en la base de datos del usuario: `report_xls{ext}` (ERP) y `DetallesVentasMayorista{ext}` (Portal). Además `os.path.splitext` cortaba los nombres con puntos sin extensión («S.A.S. 2026-10-29» → «.  2026-10-29») | Plantilla nueva `{reporte}` (`plantillas.renderizar(reporte=…)`, reservada; una variable propia «reporte» manda): el nombre COMPLETO del reporte (`Ejecutor._r` pasa `flujo.nombre`; en una Página = el de la Página; en el correo = el de la búsqueda, sin quitar el punto final). Nombre por defecto `flujo.NOMBRE_DESCARGA_DEFECTO` = «{reporte} {hoy:%Y-%m-%d}{ext}» (grabación, «Crear pasos» del mapa, «Insertar paso»); con varias descargas en el mismo reporte, «{reporte} - {nombre} {hoy:%Y-%m-%d}{ext}» (la grabación cambia también la primera). El nombre de la web sigue como `{nombre}`. `ejecutor.separar_extension` / `ruta_libre(ruta, ext)`: la extensión conocida de la descarga (o, sin pista, solo `.abc` de 1–5 letras/números) |
| Reportes ya guardados con el nombre de la web | — | `flujo.es_nombre_de_la_web` (texto fijo + «{ext}», sin otras plantillas: lo que dejaba la grabación; los nombres con fechas, `{opcion}`, `{nombre}`… se consideran elegidos y no se tocan), `usar_nombre_del_reporte` (con «Repetir por días» usa `{fecha:…}`). `Almacen.migrar_nombres_descarga()`: UNA vez (`meta.nombres_descarga_v35`), con copia de cada reporte en `versiones` («antes de poner el nombre del reporte a las descargas (v3.5)»); desde `bot.migrar_reportes` (interfaz, ventana clásica y línea de comandos), con mensaje en consola por reporte y una notificación `nombres_descarga` |
| Editor | — | Diálogo del paso «Descargar»: explicación de `{reporte}`/`{nombre}`/`{ext}`, vista previa con el nombre real del reporte (`POST /api/plantilla {reporte}`) y botones «Nombre del reporte + fecha» / «Nombre que da la web». Aviso en el editor si algún paso guarda con el nombre de la web + botón «Usar el nombre del reporte» (`POST /api/flujo/usar_nombre_reporte`; `flujo/describir` devuelve `nombres_web`) |
| Nombres cortados con «…» | `.lista .sub` y `.tabla .detalle` con `overflow: hidden; text-overflow: ellipsis` (las rutas y nombres largos sin espacios se cortaban); la barra del trabajo en curso corta su línea | Esas listas y tablas ahora parten la línea (`overflow-wrap: anywhere`) y la barra del trabajo lleva el texto completo en `title` |
| Escribir la carpeta a mano | El navegador no deja conocer la ruta de una carpeta del disco | `webbot/dialogos.py`: `elegir(tipo carpeta\|archivo\|guardar, inicial, filtros, titulo)` abre el explorador de Windows con tkinter (`askdirectory` / `askopenfilename` / `asksaveasfilename` sin «¿reemplazar?») en un hilo PROPIO con su raíz de Tk oculta y «siempre encima», creada y destruida en ese hilo; un cerrojo = un diálogo a la vez; cancelar → None; sin escritorio → `ErrorDialogo` («Escribe la ruta a mano»). `POST /api/elegir` (mismo token y comprobación de Origin/Host/Sec-Fetch-Site que el resto; la carpeta inicial: la parte fija antes de una plantilla, relativa = dentro de la carpeta de descargas). `Aplicacion(abrir_dialogo=…)` inyectable. Interfaz: `campoRuta(inp, {tipo, filtros, titulo})` (`ui/app.js`) = el campo (sigue editable) + «📁 Elegir…», en: carpeta de descargas del reporte, carpeta de los pasos «Descargar»/«Guardar página», carpeta de los archivos de una Página (nuevo campo, `data.opciones.carpeta_descargas`), carpeta de adjuntos y del cuerpo del correo, archivo donde se anota un texto y Excel/CSV de una tabla (`guardar` con filtros), y Ajustes |
| Correo: solo procesaba lo nuevo y no se veía lo demás | Cada correo se procesaba una vez; «Volver a procesar» solo olvidaba la marca para la próxima revisión, y solo con los últimos procesados | «✉ Correos relacionados» en cada búsqueda: `correo.correos_relacionados` (los criterios de la búsqueda con `criterios_con_rango`: sus fechas / 30 / 90 / 365 días / todas, del más reciente al más antiguo, «el más reciente» marcado, de 10 en 10 con «Cargar más», abriendo cada correo para ver sus adjuntos —se puede desmarcar—, y el estado de `correos_procesados`: nuevo / ya procesado + cuándo / con error / descartado) como trabajo oculto → evento `correo_relacionados` (`POST /api/correo/busquedas/<id>/relacionados`). «Procesar este» / «Procesar seleccionados» (`POST …/procesar {claves, rango, buscar_hasta}`): `revisar_busqueda(solo=…, rango=…)` busca esos correos y rehace TODAS sus acciones aunque ya se hubieran hecho; el registro se ACTUALIZA (INSERT OR REPLACE por búsqueda+clave, `intentos` = 1, «Procesado otra vez a mano»); aviso «Procesado otra vez «…»», historial y registro como siempre; no cambia la «última revisión». Si la búsqueda AGREGA filas (tabla «agregar»/«hoja por mes» o texto anotado en un archivo) y algún correo ya se procesó, la API devuelve `confirmar` con el aviso de filas repetidas y la interfaz pregunta |

Reglas que se mantienen: `flujo.py`/`plantillas.py`/`almacen.py`/`correo.py`/`dialogos.py` sin playwright (tkinter solo
dentro del diálogo, en su hilo); las pruebas usan bases de datos temporales, contraseñas en memoria, avisos falsos,
schtasks falso, un elegidor de carpetas falso (el de Tk queda parcheado para fallar) y buzones de prueba. La conversión de
nombres no se ha ejecutado contra la base de datos real (se hará sola la primera vez que se abra el bot 3.5).

Pruebas: `tests/test_v35.py` (README §23.4). Cambiadas: `test_integracion.py` y `test_integracion_v21.py` (el nombre que
deja la grabación) y las comprobaciones de versión. `--smoke-web` además: «📁 Elegir…» en Ajustes (diálogo falso), el aviso
y «Usar el nombre del reporte» del editor con los botones del paso «Descargar», y «Correos relacionados» con un buzón en
memoria.

No hecho / pendiente: la ventana clásica (Tk) graba y ejecuta con `{reporte}` (sale en su lista de plantillas) pero no
tiene los botones «Nombre del reporte + fecha» ni «Usar el nombre del reporte» (ya tenía sus propios diálogos de carpeta); no verificado con el explorador de Windows real desde la interfaz (por norma, las pruebas no abren
diálogos) ni con el Outlook/Gmail reales.

### Parte 2: diseño «A · Centro de control» y rapidez

Petición del usuario (29/10), tras ver dos bocetos: «Me gusta el boceto A. Impleméntalo.»  Y antes: «Hay partes del
programa que se sienten muy lentas. La página se recarga cada ciertos minutos o en cada acción… El diseño se siente muy
feo… Quiero que se vea más futurista pero a la vez mucho más optimizada.»

| Problema | Causa encontrada | Cambio |
|---|---|---|
| Inicio, Vigilancia y Correo tardaban ~1 s en cada carga | Las tres llamaban a `schtasks /Query` (≈ 0,9–1 s en este equipo) en CADA petición (`_tareas`) | Caché de `TTL_TAREAS` = 60 s; se vacía al crear/borrar una tarea desde el bot (todo pasa por `_ejecutor_tareas`, también con el ejecutor de las pruebas); con la interfaz abierta (`abrir_aplicacion`: `tareas_en_segundo_plano` + `precargar_tareas`) pasado el plazo se devuelve la lista anterior y se relee en otro hilo. Medido (HTTP, schtasks de verdad, solo lectura) con una base de datos temporal realista (7 reportes, 2 Páginas, 3 vigilancias, correo, 8 días de historial): `inicio` 900–1150 ms → 11–32 ms; `vigilancia` 920–1220 → 9–36; `correo` 890–1160 → 5–19 (la primera lectura tras arrancar, ~1 s, se hace en segundo plano al abrir la interfaz). Las demás rutas ya iban en 3–30 ms (el ruido de ~15 ms es el reloj de Windows) |
| Conexiones de SQLite que nunca se cerraban | `ThreadingMixIn` atiende cada petición en un hilo NUEVO y `Almacen._con` abría una conexión por hilo (se guardaban en `_conexiones`: miles al día con el sondeo de eventos) | `liberar_hilo()` al terminar cada petición |
| «La página se recarga en cada acción y cada pocos minutos» | `despachar` llamaba a `setTimeout(navegar, 300)` al terminar CUALQUIER trabajo en Inicio/Reportes/Historial/Vigilancia/Accesos/Correo/Páginas, y casi todos los botones llamaban a `navegar()`: se vaciaba `#contenido`, se volvía a pedir todo, se perdía el desplazamiento, el foco y lo abierto, y parpadeaba | Ningún `navegar()` tras una acción ni tras un evento. `claveLista` (cada fila/tarjeta con su clave; solo se repinta si cambian sus datos, conservando `<details>` abiertos y el foco), `actualizador` (de una en una, nunca datos viejos encima), vistas VIVAS (Inicio, Reportes, Páginas, Vigilancia, Correo, Accesos, Historial, Grabar, Mapear: al cambiar de sección se guardan tal cual con su desplazamiento, vuelven al instante y se ponen al día por detrás; reciben los eventos aunque no se vean), `E.curso` (al pulsar «Ejecutar» la fila pasa a «en curso» al instante; los eventos «trabajo»/«lote» llevan ahora `reporte_id` y «progreso» mueve su barrita sin repintar la fila), esqueleto solo si algo tarda > 120 ms. Inicio = una sola llamada (`/api/inicio` con todo) |
| Diseño | — | Boceto A llevado a JavaScript sin dependencias: `tema.css` (tinta azul, cian = vivo, rojo de marca PROVISIONAL solo en la acción principal, ok/aviso/error), fuentes en `ui/fuentes/` (Chakra Petch 500–700, IBM Plex Sans variable, IBM Plex Mono 400–500; woff2 latinos de Google Fonts, OFL, sin CDN; `font/woff2` y caché de un día), `app.css` reescrito (riel de iconos con nombres al pasar el ratón y punto rojo de novedades, barra abajo con «Más» por debajo de 720 px; cabecera con título Chakra + subtítulo mono + «Buscar o ejecutar… Ctrl K»; tablas que en el móvil pasan a tarjetas; foco cian, cifras tabulares, «reducir movimiento»; sin scroll horizontal a 400 px). Iconos de trazo (`ico()`): los botones con símbolo («▶», «⚙», «📁»…) se convierten solos. Centro de control: cifras con chispa de 7 días (`Almacen.serie_dias`), filas densas (`ultimas_por_reporte`, sitio, archivo y duración, próxima ejecución, «Completar Licencia» → Accesos), filtros, «En vivo» (aria-live), Vigilancia («Descargar este corte»), Correo y Próximas. Paleta Ctrl K (`GET /api/buscador`, sin nada lento): secciones, «Ejecutar «X»», Páginas, «Revisar…» vigilancias y correo, Grabar, Mapear, revisar todo; difusa y sin acentos; ↑↓ Enter Esc. Reportes e Historial como filas (con buscador / filtros). Arreglado de paso: el formulario de una Página y «Usar filtros» pintaban «nullnullnull» bajo las listas sin chips; y al abrir una ventana el foco iba al primer campo con un temporizador de 30 ms, que con el equipo cargado podía robar el foco mientras ya se escribía en otro campo (lo escrito acababa en «Nombre»: así fallaba a veces `test_integracion_v34_correo` en la batería completa): ahora el foco se pone al instante |

Reglas que se mantienen: sin React ni compilación; todos los textos con `h()`; mismos ids/clases/atributos `data-*` que
usan las pruebas y `--smoke-web`; ninguna función ni ruta de la API quitada.

Pruebas: `tests/test_v35_diseno.py` (sin navegador: series de 7 días y filas del Inicio, buscador, caché de tareas —una
lectura para Inicio+Vigilancia+Correo, se vacía al crear/quitar, caduca, en segundo plano no espera—, `reporte_id` en
los eventos, una conexión por petición que se cierra, fuentes locales; con navegador oculto: al empezar/progresar/terminar
un trabajo cambia SOLO su fila —un elemento marcado, la misma vista, otra fila y el desplazamiento siguen—, Reportes no se
rehace con un evento, volver a Inicio devuelve la misma vista con su desplazamiento, y la paleta Ctrl K).

No hecho / pendiente: los colores de la marca siguen PROVISIONALES; el editor de pasos, el formulario de una Página,
Ajustes y las ventanas se repintan como antes al abrirse (no son vistas vivas: tienen cambios sin guardar); la ventana
clásica (Tk) no cambia.


## v3.6 (rama New-tool) — pegar en Outlook y calendario de fechas

Petición del usuario (29/10): «El bot no pega el nombre completo cuando busca en Outlook; es mucho mejor que lo pegue en
vez de escribirlo.»  Y: «Cuando detecta que hay una fecha o para colocar una fecha, en muchas partes no es funcional. Que
aparezca un calendario o colocar la fecha de forma más simple.»

| Problema | Causa encontrada | Cambio |
|---|---|---|
| Outlook no encontraba el correo / buscaba otro texto | `correo.texto_a_teclear` usaba solo las **4 primeras palabras** del asunto (heredado de Octopus, que temía que una coma rompiera la búsqueda) y `correo_outlook._lanzar_busqueda` las **tecleaba** (`campo.type(texto, delay=40)`): el combobox de sugerencias de Outlook puede comerse o robarse pulsaciones | `texto_a_teclear` = el texto COMPLETO (asunto entero / «buscar» / remitente / cuerpo); `textos_a_buscar` = [completo, `texto_corto`] (hasta la primera coma si quedan ≥ 2 palabras; si no, 4 palabras sin signos). `AdaptadorOutlook.buscar` prueba el completo y, SOLO si ninguna fila cumple `coincide(fase="resumen")`, una vez el corto (registro: «Buscando en Outlook: «…» (completo)» → «sin resultados que cumplan la búsqueda con «…»; se prueba con «…» (más corto)»). `_escribir_busqueda`: clic + Ctrl+A + Supr, `keyboard.insert_text` (un solo evento, como pegar), comprobación con `input_value`; si no quedó, portapapeles (`grant_permissions` clipboard-read/write, `navigator.clipboard.readText` → `writeText` → Ctrl+V → se devuelve lo anterior) y comprobación; último recurso, teclear. Si con el texto pegado Outlook no lanza la búsqueda (ni la dirección ni las filas cambian), otra vez con Ctrl+V. Gmail no escribe nada (busca por la dirección); los pasos «Escribir» del ejecutor ya usan `fill` (un solo evento): no hace falta la opción «pegar» |
| Fechas: escribir `{ayer:%d/%m/%Y}` a mano en muchos sitios | Cada sitio tenía su campo de texto (+ a veces «Fechas habituales» o un `type=date`) | `campoFecha(inp, opc)` en `ui/app.js` (como `campoRuta`: el campo sigue siendo el texto que se guarda, escondido detrás de un botón «Ayer · 28/10/2026»; al cambiar lanza «input» y «change»). Calendario en `<body>` (`position: fixed`, junto al botón, `z-index` sobre las ventanas, se cierra con Esc / al pulsar fuera / al cerrar la ventana / al cambiar de sección; a 400 px cabe en la pantalla): **Fecha fija** (rejilla del mes, ‹ ›, hoy marcado, ← → ↑ ↓, Re Pág / Av Pág, Inicio / Fin, Enter) y **Cambia sola** (Hoy, Ayer, Hace N días, Lunes de esta semana, Lunes / Domingo de la semana pasada, Inicio / Fin de este mes y del anterior, 1 de enero, y {fecha} en los reportes); **Formato** con ejemplos de verdad (`FORMATOS_FECHA`, «Otro…» con códigos), «Se escribirá: …», «Quitar la fecha», «Escribir a mano». Plantillas nuevas en `plantillas.py`: `lunes_semana`, `lunes_semana_anterior`, `domingo_semana_anterior`, `inicio_anio`; `analizar_fecha` / `plantilla_fecha` (ida y vuelta exacta: `{ayer}` sigue siendo `{ayer}` si no se toca), `formato_de_fecha`, `describir_fecha`; la interfaz tiene `analizarFecha` / `componerFecha` / `describirFecha` iguales (comprobado en las pruebas con `window.__botFechas`) |
| Dónde | — | **Usar filtros** (fechas: `filtros.datos_panel` da `formato`), **formulario de una Página** (`paginas.formulario` da `formato`), **editor de pasos** (paso «Escribir» con `fecha_directa`, una plantilla de fecha o una fecha; si no, botón «Es una fecha: elegirla en el calendario»; marcar «Fecha escrita directamente» lo cambia), **Mapear** (fechas: `{fecha: "plantilla", valor}` en `mapeador._paso_de_filtro`, validado; lo de antes sigue valiendo), **Repetir por días** desde/hasta y **inicio/fin** del editor «Cuándo» (solo fecha fija AAAA-MM-DD, como antes) y **Correo** «entre dos fechas» (desde/hasta, sin formato). `filtros._RX_FECHA_PLANTILLA` reconoce también `{dias:…}` y las nuevas |

Reglas que se mantienen: lo guardado no cambia de forma (las mismas plantillas y fechas de texto); `plantillas.py` sin
playwright; las pruebas no tocan el portapapeles de Windows (Chrome oculto usa uno propio: se comprueba con
`GetClipboardSequenceNumber`, que no lee el contenido), usan bases de datos temporales y ningún aviso ni tarea.

Pruebas: `tests/test_v36.py` (README §24.3).  Página de prueba `correo_outlook.html`: el buscador pierde las letras
tecleadas a menos de 120 ms de la anterior (como el combobox de Outlook) y acepta lo pegado; `?teclado_ok=1`,
`?sin_insertar=1` (solo un pegado con Ctrl+V), `?coma_falla=1` (una búsqueda con coma no encuentra nada).  Cambiada:
`test_v34_correo` (el texto completo).  `--smoke-web` abre el calendario de la Página de prueba.

No hecho / pendiente: no verificado contra el Outlook real (sin acceso desde aquí); con el navegador VISIBLE el pegado con
Ctrl+V usa el portapapeles de Windows (se devuelve el texto que había; si había una imagen, se pierde — solo pasa si el
buscador no acepta el texto pegado con `insert_text`); la ventana clásica (Tk) no tiene el calendario; los formatos con
nombres de mes (`%b`) salen en inglés (como siempre en Python).
