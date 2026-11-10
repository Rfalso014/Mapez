# Bot Web — descarga automática de reportes (versión 3.6)

El bot **abre una página web, repite los pasos que tú le enseñes y descarga el reporte**, sin
que tengas que estar delante. Puedes verlo trabajar o dejarlo **oculto**, y programarlo para que
se ejecute solo a una hora. Puedes tener **varios reportes** guardados y ejecutarlos juntos.

**Novedades de la 3.6** (detalles en §24)

* **Outlook**: el bot **pega** el asunto **completo** en el buscador (antes lo tecleaba letra a letra y solo las 4 primeras
  palabras, y Outlook podía comerse letras). Si así no encuentra nada, prueba una vez con una parte.
* **Fechas con calendario**: en todos los sitios donde se pone una fecha hay un botón que abre un **calendario** (fecha
  fija) o deja elegir una **fecha que cambia sola** (Hoy, Ayer, Hace 7 días, Lunes de esta semana, Inicio del mes…), con
  el **formato** elegido por ejemplos («28/10/2026», «2026-10-28»…). Ya no hace falta escribir `{ayer:%d/%m/%Y}`.

**Novedades de la 3.5** (detalles en §23)

* Los archivos descargados se llaman **como el reporte (nombre completo) y la fecha**, y no «report_xls (6).xlsx».
* Botón **📁 Elegir…** junto a cada carpeta o archivo: abre el explorador de Windows para elegirla.
* Correo: **Correos relacionados** (todos los correos de una búsqueda, con su estado) y **procesar cualquiera**, aunque ya
  se hubiera procesado.

**Novedades de la 3.4** (detalles en §21 y §22)

* **Correo** (detalles en §22): una sección nueva que **busca correos** (Outlook de la empresa, Gmail u otra cuenta por
  IMAP), los reconoce por **asunto, remitente, fecha, parte del cuerpo y adjuntos**, y con **cada** correo que llega
  **descarga sus adjuntos** (con el nombre que quieras), **copia un texto** («Total ventas: 1.234»), copia una **tabla** a
  Excel/CSV o guarda el cuerpo. Procesa **todos** los que coinciden (no solo uno), cada uno una sola vez, y se programa
  con el mismo editor **Cuándo**.
* **Programación completa**: vigilancias, reportes y Páginas se programan con el mismo editor **Cuándo**: los días que
  quieras, **varias horas** por día, **horas distintas según el día** (＋ Añadir otro horario), **cada N horas en un
  horario** (de 08:00 a 18:00 cada 2 h), **mensual** (el 1 y el 15, el último día del mes, el primer lunes…) y fechas de
  inicio y fin. Debajo se ve en palabras y con las 5 próximas ejecuciones.
* **Queda claro qué hace que se ejecute solo**: la tarea de Windows. Al guardar una vigilancia con horario el bot te
  ofrece **Activar: crear la tarea en Windows**, y cada vigilancia dice si la tiene.

**Correcciones de la 3.3.1** (detalles en §20)

* **Páginas y reportes que empiezan en una dirección profunda** (Portal `…/#/reportes/corte`): tras iniciar sesión Portal
  va siempre a «Inicio»; ahora el bot **vuelve a la página a la que iba** y sigue. Por eso la Página creada mapeando toda
  la página «no hacía nada».
* **ERP**: «El campo LICENCIA esta vacio (es un dato obligatorio)» ya **no** marca la contraseña como rechazada: el bot
  rellena la Licencia con tus Accesos (o te pide **solo** la Licencia) y reintenta. La ventana «La contraseña falló» rellena
  bien la contraseña de DevExpress. En **Accesos** se ve lo que dijo la página y hay **Quitar marca de rechazada**.
* **Vigilancia**: **＋ Añadir vigilancia** arriba, con **cualquier** reporte o Página; las listas grabadas como clics se
  ofrecen directamente y se convierten solas (con copia en Versiones).

**Novedades de la 3.3** (detalles en §19)

* **Mapear página funciona en otras webs** (Informes, el ERP…): mira también dentro de los **marcos (iframes)**, la
  pestaña que estás viendo (o la que elijas), etiquetas en tablas, listas y fechas de DevExpress, campos con **lupa de
  búsqueda**, botones «Ver Reporte» de imagen y menús de exportar. Si no encuentra nada o algo falla, **te dice por qué** y
  guarda un **diagnóstico** en `registros/mapas/`.
* **Varias vigilancias**: la misma lista con otros valores (p. ej. «Elegir corte» de «Detalles Ventas Mayorista» y,
  aparte, de «Cartera General»), o varias listas; cada una con sus avisos y su descarga automática. Tu base de datos
  se convierte sola al abrir el bot (antes se copia a `datos/bot.db.antes-v3.3`).

**Novedades de la 3.2** (detalles en §18)

* **Páginas**: la página de filtros de una web (p. ej. los reportes de Portal) queda guardada **dentro del bot**, como si
  fuera la propia página. En **Páginas** abres «Portal – Reportes», eliges Pestaña, Filtro por sistema, Seleccione
  reporte, Elegir corte y Formato, y pulsas **Generar y descargar**: el bot, por detrás, abre la web, inicia sesión,
  llega a la página, pone esos filtros, genera y descarga. Otro día, otros valores (o varios cortes a la vez), sin volver
  a mapear ni grabar. Favoritos («Mayorista + corte más reciente + Excel») para ejecutar con un clic o programar, y
  vigilancia de un filtro (el corte nuevo sale en la lista como **nueva**).
* **Sin abrir navegador (en segundo plano)**: un interruptor en cada Página (encendido por defecto), en Reportes y en
  «Usar filtros». El bot trabaja sin ninguna ventana; las preguntas de inicio de sesión siguen saliendo en el bot.
* El mapa del «Reporte mapeado» de Portal se convierte solo en la Página **«Portal – Reportes»** (el reporte no cambia).

**Novedades de la 3.1** (detalles en §17)

* **Usar filtros** (§17.1): cada reporte tiene un panel con sus filtros («Elegir corte», «Formato a Exportar»…) y
  **todas sus opciones**, sin tener que ir a la página: eliges el corte 43, el 42 o varios a la vez y pulsas **Descargar
  con estos filtros** (el reporte guardado no cambia). Las opciones se actualizan solas con cada ejecución y con la
  vigilancia. También por línea de comandos: `--filtro "Elegir corte=43 - 2026 (…)"`.
* **Vigilancia: solo lo más reciente es nuevo** (§17.2): un corte antiguo que aparece por primera vez (p. ej. «45 - 2023»)
  ya no se muestra ni se descarga como si fuera el corte nuevo; la lista de Vigilancia va de la más reciente a la más
  antigua y marca la **más reciente**.
* Los filtros mapeados ya no se llaman «Open»: se usa la etiqueta de verdad («Filtro por sistema», «Elegir corte»…).

**Novedades de la 3.0** (detalles en §16)

* **Portal ya no espera 30 s en cada lista** (§16.1): el menú abierto de una lista de Vuetify
  (`v-overlay--active`) se confundía con una rueda de «cargando…». Ahora los menús, listas, diálogos y
  popovers no cuentan como carga; la rueda de verdad (los ~80 s de «Generar») se sigue esperando.
* **Accesos más claros** (§16.2): lo que escribes al grabar se guarda solo en **Accesos** («Se guardaron
  los datos de acceso de «…»»). Si una página **rechaza la contraseña**, aparece la ventana **«La contraseña
  de «…» falló»** para escribir la nueva (con «Mostrar»); sin nadie delante, el bot **no reintenta la misma**
  contraseña, la marca como rechazada y te avisa (aviso en la aplicación y **notificación de Windows**).
* **Paso «Elegir opción»** (§16.3) para listas desplegables: la opción fija, **la más reciente** (p. ej. el
  corte «45 - 2026 (…)» en vez del «44»), la primera, la última o la que contiene un texto.
* **Vigilancia** (§16.4): el bot revisa un filtro (p. ej. «Elegir corte») cada N horas o cada día, **te
  avisa cuando llega un corte nuevo** y, si quieres, **lo descarga** (una sola vez).
* **Repetir por días** (§16.5): un reporte se descarga una vez por cada día de un rango (`{fecha}`).
* **Mapear página / Sacar filtros** (§16.6): el bot recorre la página, encuentra sus filtros (pestañas,
  listas, fechas, botón «Generar»…) y crea los pasos con los que tú elijas.
* **Interfaz nueva** (§16.7): `python bot.py` abre una ventana moderna (con los colores de la marca); la
  ventana de siempre sigue disponible con `python bot.py --clasica`.

**Novedades de la 2.3**

* **Inicio de sesión inteligente** (§7): el inicio de sesión es un único paso **«Iniciar sesión en
  «página» (si hace falta)»**. Si la sesión ya estaba abierta, se omite; si la página pide entrar a
  mitad del reporte (la sesión caducó), el bot entra solo y sigue; si **falta la contraseña o la
  página la rechaza, el bot analiza el formulario y te la pide** en una ventanita, y la guarda.
* **🔑 Accesos**: usuarios, licencias y contraseñas guardados por página, para cambiarlos o borrarlos.
* **Espera a que la página termine de cargar** (§4): después de cada paso el bot espera mientras se
  vea una rueda o barra de «cargando…», haya peticiones pendientes o la página se esté actualizando
  (ASP.NET, jQuery). Las esperas «hasta que aparezca» ya no se dan por buenas antes de tiempo, y los
  textos con fechas u horas sirven también otro día.
* Tus reportes guardados se **actualizan solos** al abrir la ventana (con una copia de la versión
  anterior que puedes restaurar en **Más ▾ → Versiones anteriores del reporte**).

**Novedades de la 2.2**

* Los reportes se **guardan dentro de la aplicación** (ya no como archivos): «Guardar» solo pide un
  nombre. Lista con Abrir, Renombrar, Duplicar, Eliminar y **Papelera** (§9).
* **Menús que se abren al pasar el ratón** (p. ej. ERP con menús DevExpress): el grabador anota
  pasos **«Pasar el ratón sobre …»** y la barra tiene el botón **🖱 Pasar el ratón** (§5).
* **Recuperación automática**: si al ejecutar una opción de un menú no se ve, el bot intenta abrir
  ese menú él solo (también en flujos antiguos) (§4).
* **Listas con autocompletar** (Vue/Vuetify…): ya no se graba un «Escribir» de más que se quedaba
  esperando, y «Escribir» en estas listas elige la opción (§3).

A diferencia de la versión 1 (clics por coordenadas de pantalla), esta versión controla el
navegador directamente (con *Playwright*): graba **sobre qué elemento actúas** (un botón, un
campo, un enlace), no en qué píxel. Por eso puede trabajar oculto, **espera a que el reporte se
genere** y no se rompe si cambias el tamaño de la ventana.

> La versión 1 sigue disponible, sin cambios, en la carpeta `version_escritorio/`.

---

## 1. Instalación

Necesitas Windows con **Python 3.10 o superior** y **Google Chrome o Microsoft Edge** instalados
(no se descarga ningún navegador).

Haz doble clic en **`iniciar.bat`**: instala lo necesario (`playwright`, `keyring` y `openpyxl`) y abre el bot.

A mano:

```
python -m pip install -r requirements.txt
python bot.py
```

### Compartir e instalar en otra PC

En la carpeta **`instalador/`** está **`Instalar Bot Web.cmd`**: un solo archivo que la otra persona abre con doble
clic. No necesita permisos de administrador ni saber nada de Python. El otro PC empieza **vacío**: no se copia
ningún dato tuyo (ni `datos/`, ni `perfiles/`, ni `registros/`, ni `descargas/`, ni los flujos de `flujos/`, ni
las contraseñas, que están en el Administrador de credenciales de *tu* Windows).

**Cómo compartirlo**

* **Una copia de la carpeta** del bot (en un .zip o un pendrive): el instalador copia el bot desde ella, dejando fuera
  tus datos. Pero lo que va **dentro del .zip** lo recibe la otra persona igualmente: borra de la **copia** las
  carpetas `datos`, `perfiles` (la sesión abierta de tu navegador), `registros` y `descargas` antes de comprimirla.
* **Solo el archivo** `Instalar Bot Web.cmd`: entonces descarga el bot de GitHub
  (`https://github.com/Rfalso014/Mapez`, rama **main**). Para eso el repositorio tiene que ser **público** y
  tener subida la última versión (`git push`); si no, el instalador avisa («GitHub dice que el bot no existe (404)»).

**Lo que ve la otra persona** (ventana negra, en español):

```
[1/7] Comprobando Windows y la conexión a Internet...
[2/7] Buscando Python...                 (si no hay, instala Python 3.13 de python.org solo para su usuario)
[3/7] Copiando el bot...                 (o «Descargando el bot de Internet...»)
[4/7] Preparando las piezas del bot...   (entorno .venv + playwright, keyring y openpyxl)
[5/7] Buscando Chrome o Edge...          (sin Chrome, el bot usa Edge)
[6/7] Creando los accesos directos...    («Bot Web» en el Escritorio y en el menú Inicio)
[7/7] Comprobando que todo funciona...   (python bot.py --smoke-web)
¡Listo! ... ¿Abrir Bot Web ahora? (S/N)
```

* El bot se instala en **`%USERPROFILE%\BotWeb\app`** (por ejemplo `C:\Users\Ana\BotWeb\app`), con su propio Python
  en `app\.venv`. No va en `AppData` a propósito: si el Python del equipo es el de la Microsoft Store, todo lo que ese
  Python escribe en `AppData` se desvía a una carpeta oculta y las descargas no se verían en el Explorador.
* El registro de la instalación queda en `%USERPROFILE%\BotWeb\instalacion.log`.
* **Actualizar**: volver a abrir el instalador. Cambia el programa y **conserva** `datos`, `perfiles`, `registros`,
  `descargas` y `flujos`.
* **Desinstalar**: menú Inicio → Bot Web → **Desinstalar Bot Web** (`Desinstalar Bot Web.cmd`). Quita los accesos
  directos, las tareas programadas de la carpeta `\BotWeb\` del Programador de tareas y el programa; pregunta aparte
  si borrar también los datos y las contraseñas guardadas (por defecto **no**). Python no se desinstala.
* Las tareas programadas creadas en el otro PC usan el `pythonw.exe` de `app\.venv`.
* Si el otro PC no tiene Chrome, el bot abre Edge (y al revés) y lo anota en el registro con una línea.
* Avisos posibles: Windows SmartScreen o el antivirus pueden avisar al abrir un `.cmd` descargado («Más información →
  Ejecutar de todas formas»). Detrás de un proxy de empresa, `pip` puede necesitar que el proxy esté configurado.

Instrucciones cortas para la otra persona: `instalador/LEEME.txt`.

## 2. Inicio rápido

Con la **interfaz nueva** (`python bot.py`, ver §16.7):

1. En el menú de la izquierda pulsa **Grabar**, escribe la **dirección (URL)** y pulsa **● Empezar a grabar**.
   Se abre el navegador en esa página.
2. Haz tus pasos como siempre: inicia sesión, elige los filtros, pulsa «Generar», descarga el archivo…
3. Pulsa **Terminar** en la barra flotante del navegador (o **■ Terminar** en la ventana).
4. Escribe un **nombre** y pulsa **Guardar reporte**: se abre el **editor de pasos**. Ajusta lo que quieras
   (botón **Editar** de cada paso) y pulsa **Guardar**.
5. Pulsa **▶ Ejecutar** para probarlo. En **Reportes**, la casilla **Ver mientras trabaja** decide si se ve el
   navegador o trabaja oculto.

En la **ventana clásica** (`python bot.py --clasica`) es igual que en la 2.3: URL, **● Grabar**, **Terminar**,
nombre, **▶ Ejecutar**.

## 3. Cómo grabar

Mientras grabas, cada acción se anota como un **paso** con un nombre en español que aparece en
vivo en la lista: *«Clic en botón «Entrar»»*, *«Escribir «demo» en campo «usuario»»*,
*«Seleccionar «Globex» en …»*, etc.

* **Escribir**: se anota el texto **final** del campo cuando sales de él (no cada tecla).
* **Listas desplegables y casillas**: se anota la opción elegida o si quedó marcada.
* **Enter / Escape**: se anotan cuando los pulsas dentro de un campo (para enviar un buscador,
  por ejemplo). *Tab* no se anota.
* **Doble clic**: se anota como un solo paso de doble clic.
* **Pestañas nuevas y ventanas emergentes**: cada una recibe un número (pestaña 1 = la
  principal, 2 = la primera que se abre…) y los pasos que hagas en ella lo recuerdan.
* **Marcos (iframes)**: se anotan con la ruta del marco (mejor esfuerzo; funciona bien con los
  marcos habituales).
* Si escribes **una fecha relativa** (hoy, ayer, el primer o último día del mes o del mes
  anterior) en un campo, el bot te propone convertirla en una **fecha dinámica**
  (`{hoy}`, `{inicio_mes:%Y-%m-%d}`…) para que siempre use la fecha del día de la ejecución. Se
  respeta el formato que usaste (`23/10/2026`, `2026-10-23`…).
* **Esperas aprendidas**: de cada paso se anota cuántos segundos pasaron desde el anterior
  (`espera_grabada`). Al ejecutar, un paso que tuvo que esperar mucho al grabar (p. ej. un
  reporte que tardó 40 s) espera también mucho (ver «Puntos de espera»).
* **Menús que se abren al pasar el ratón**: si pasas el ratón por una opción de menú (al menos
  0,15 s) y eso abre un submenú donde luego haces clic, antes del clic se anotan pasos
  **«Pasar el ratón sobre «Inventario»»** (como mucho 3, en orden; en azul y marcados como
  *automático* en la lista). Ver §5.
* **Listas con autocompletar** (`v-autocomplete`, *combobox*, select2…): cuando eliges una opción,
  la web escribe su texto en el campo; ese texto **ya no se graba** como «Escribir» (lo hace el
  clic en la opción). Si habías tecleado para filtrar, el «Escribir» se conserva **desactivado** con
  una nota. Y si haces clic en la **etiqueta** del campo y enseguida (< 1 s) en su cuadro, se
  queda un solo clic (dos clics seguidos abrían y cerraban la lista al reproducir).

El bot guarda varios selectores alternativos por elemento (id estable, `data-testid`, `name`,
rol + nombre, texto visible, `aria-label`, `placeholder`, clases, ruta CSS) y al ejecutar prueba
uno tras otro, así que aguanta pequeños cambios de la página. Para textos cortos sin identificador
(años, meses, días, opciones de un menú…) el selector se acota al contenedor que tiene su propia
clase, p. ej. `.datepicker-years span:text-is("2020")`, en lugar de una ruta frágil desde `<body>`.
Cuando hay varias coincidencias visibles, al ejecutar se prefiere la de la ventanita emergente
(calendario, menú…) y solo se usan elementos **visibles y habilitados**.

### Calendarios y selectores de fecha

Muchas webs piden la fecha con un calendario (clic en el icono, elegir el año, el mes, el día…).
Repetir esos clics es lento y frágil, así que el grabador lo detecta: si tras clics dentro de un
calendario cambia el valor de un campo (sin que tú teclees), anota **un solo paso «Escribir»
con la fecha final** (marcado como *fecha directa*) y **desactiva** los clics del calendario que
llevaron a ella (no se borran: siguen en la lista, en gris, y los puedes reactivar). Al ejecutar,
el bot escribe la fecha directamente (con `fill`; si el campo es de solo lectura, con JavaScript
disparando `input`, `change` y `blur`, y pulsa Esc para cerrar el calendario) y comprueba que el
valor quedó puesto. Te propone además convertir la fecha en dinámica (`{inicio_mes:%Y-%m-%d}`…).

### Pasos desactivados

Cualquier paso puede **desactivarse** (botón **Activar/Desactivar** o casilla en el diálogo de
edición): se conserva en la lista (en gris) pero no se ejecuta; el registro anota «desactivado».

### La barra flotante

Durante la grabación verás una barra oscura arriba a la derecha de la página (puedes arrastrarla
por «● Grabando»). El bot **ignora todo lo que hagas sobre ella**.

| Botón | Qué hace |
|---|---|
| **Esperar a un elemento** | El *siguiente clic* no se ejecuta en la página: solo marca qué elemento hay que esperar. Se anota un paso «Esperar hasta que aparezca …». (Esc cancela.) |
| **🖱 Pasar el ratón** | El *siguiente clic* no se ejecuta en la página: marca el elemento sobre el que hay que **pasar el ratón** (p. ej. la opción «Inventario» de un menú que se abre al pasar por encima). Se anota «Pasar el ratón sobre …». (Esc cancela.) |
| **Esperar texto…** | Escribes un texto y se anota «Esperar hasta que aparezca «texto»». |
| **💾 Guardar esta página** | Eliges el formato (PDF, HTML o CSV) y se anota un paso «Guardar página» de la pestaña en la que estás (ver §6). |
| **Terminar** | Termina la grabación. |

## 4. Puntos de espera (reportes que tardan en generarse)

* **Espera automática**: antes de cada acción el bot espera hasta que el elemento exista, se vea
  y esté **habilitado** (un botón «Descargar» gris/deshabilitado mientras el reporte se genera no
  se pulsa hasta que se active). Por defecto hasta **60 s** por paso (opción «Tiempo máximo de
  espera»).
* **Espera aprendida**: el tiempo máximo real de un paso es el que pongas en el propio paso; si no
  pusiste ninguno, es el mayor entre «Tiempo máximo de espera» y **espera grabada × 3 + 30 s**,
  con tope en «Espera máxima de descargas/reportes». En el diálogo de edición de cada paso ves la
  espera aprendida y el tiempo que se usará.
* **Descargas**: el paso de descarga espera hasta **10 minutos** (600 s; opción «Espera máxima de
  descargas/reportes») *primero* a que el botón esté visible y habilitado y *después* a que
  empiece la descarga. Se cambia en la ventana o en el tiempo máximo del propio paso.
* **Avisos mientras espera**: cada ~15 s el registro y la barra de estado de la ventana dicen, por
  ejemplo, «esperando a que «Descargar» esté disponible… 45 s», para que sepas que sigue
  esperando y no está colgado.
* **Pausa entre pasos**: opción «Pausa entre pasos (s)» (0,3 s por defecto, no se aplica antes del
  primer paso) para dar tiempo a animaciones y calendarios que se redibujan.
* **Esperar a que la página termine de cargar** (casilla en «Opciones», activada por defecto; se
  guarda con cada reporte; cada paso puede forzarlo a «sí» o «no» en su diálogo de edición). Después
  de cada acción (clic, escribir, tecla, lista, abrir la página, iniciar sesión, descargar) y antes de
  buscar el elemento del paso siguiente, el bot espera a que:
  * la página haya terminado de abrirse y no queden **peticiones pendientes** durante medio segundo
    (no cuentan los websockets, las consultas que la página repite cada poco ni la analítica). Esta
    espera es **corta**: como mucho 30 s; si la página sigue «hablando», el bot continúa y lo anota;
  * no se vea ningún **indicador de carga**: ruedas y barras (`spinner`, `loading`, `v-progress`,
    `v-overlay--active`, `mat-progress`, `blockUI`, `role=progressbar`…), paneles de carga de
    DevExpress, `aria-busy`, textos «Cargando…», «Procesando…», «Espere…», «Generando…», o que
    **ASP.NET** no esté actualizando la página (postback asíncrono). Esta espera es **larga** (hasta
    la «Espera máxima de descargas/reportes», 600 s) y avisa cada ~15 s («esperando a que termine
    de cargar… 45 s (indicador …)»). Un indicador que ya se veía antes de la acción solo se espera
    mientras haya actividad, y uno que no se va aunque la página no haga nada durante 30 s se da por
    atascado;
  * si al hacer clic **algo tapa el elemento** (una capa de «cargando…»), el bot espera a que termine
    y vuelve a intentarlo dentro del tiempo del paso.
* **Esperas «hasta que aparezca» más fiables** (2.3): el grabador ya no usa textos que cambian
  (fechas, horas, números largos o textos de más de 40 caracteres) para reconocer lo que hay que
  esperar: usa un trozo fijo del texto o la estructura de la página, y el nombre del paso es corto
  («ACME Detalles De Ventas Mayorista» en vez de «… 24/10/2026 11:32 …»). Al ejecutar, una espera
  ya no se da por buena al instante con un selector alternativo que **ya coincidía antes** del paso
  anterior (p. ej. el informe de la vez anterior): vale el selector principal o algo nuevo o que
  cambió (y, si solo está lo de antes, se acepta cuando la página lleva un rato sin cargar nada).
  Un «Esperar texto» grabado con fechas u horas busca sus **partes fijas** en orden.
* **Esperar a que aparezca algo**: si tu reporte tarda en generarse, mientras grabas pulsa
  **Esperar a un elemento** y haz clic en el resultado (cuando ya haya salido), o usa
  **Esperar texto…** con un mensaje como «Reporte listo». También puedes añadirlo después con
  **Insertar paso ▾**.
* **Esperar unos segundos**: pausa fija, como último recurso.
* **Recuperación automática** (casilla en «Opciones», activada por defecto; se guarda con cada
  reporte): si en un paso de clic (o descarga, casilla, pasar el ratón) el elemento **existe pero no
  se ve** —o no aparece— durante unos **2 s**, el bot intenta **una vez** abrir el menú o la lista
  que lo contiene, y lo anota en el registro («intentando abrir el menú pasando el ratón por
  «Inventario»…»):
  1. pasa el ratón por la opción de la que cuelga (menús CSS con `:hover`, menús con
     `aria-controls`, menús DevExpress por sus ids `…_DXI1i0_` → `…_DXI1_`);
  2. repite los pasos «Pasar el ratón» que hay justo antes;
  3. si el paso anterior fue un clic que abre una lista o menú y ahora está cerrada, repite ese clic
     (p. ej. «etiqueta + cuadro» que dejaron cerrada una lista de Vuetify);
  4. si el elemento existe pero sigue oculto, pasa el ratón por las opciones de los menús de la página,
     una a una.
  Si no lo consigue, sigue esperando como siempre. Así también funcionan los flujos grabados antes de
  la 2.2, que no tienen pasos «Pasar el ratón».
* **«Escribir» que no se queda esperando**: si el campo **ya tiene el valor** (p. ej. lo puso la web al
  elegir una opción), el paso termina enseguida («el campo ya tenía el valor»). Si el campo se ve pero
  no parece disponible (solo lectura, sin eventos de ratón…) durante más de 3 s, se escribe igualmente;
  en las listas con autocompletar el bot escribe el texto y **elige la opción** con ese texto.
* **Pasos opcionales**: marca «Opcional» en un paso (p. ej. un aviso o ventana emergente que a
  veces sale). Si no aparece, se anota *OMITIDO* y el bot sigue. Un paso opcional espera como
  máximo **5 s** salvo que le pongas un tiempo propio. Un paso **obligatorio** que falla detiene
  la ejecución, guarda una **captura de pantalla** y lo anota en el registro (código de salida 1).

> Los flujos guardados con versiones anteriores conservan los tiempos que tenían (p. ej. 30 s);
> súbelos en las opciones si hace falta. Los flujos antiguos se abren sin problema.

## 5. Clic derecho y menús

El clic derecho se graba como el paso **«Clic derecho en …»**. Si la página muestra su propio
menú (como un «Exportar CSV» al hacer clic derecho en una tabla), el clic siguiente sobre una
opción del menú se graba como un paso normal. Al ejecutar, el bot espera a que el menú aparezca.

### Menús que necesitan el ratón encima

En muchas webs (sobre todo ERP hechos con ASP.NET/DevExpress) el submenú solo se ve **mientras el
ratón está encima** de su opción: al ejecutar, el bot no encontraba «Registro De Asistencia»
porque nadie había pasado el ratón por «Inventario». Ahora hay tres ayudas:

1. **Al grabar**, el bot nota que pasaste el ratón por «Inventario» y que eso abrió el submenú
   donde hiciste clic, y añade solo el paso **«Pasar el ratón sobre «Inventario»»** (automático).
2. Si no lo detecta, pulsa **🖱 Pasar el ratón** en la barra flotante y haz clic en la opción del
   menú (no se hace clic de verdad); o después, en la ventana, **Insertar paso ▾ → Pasar el ratón por
   encima de un elemento…**.
3. **Al ejecutar**, la *recuperación automática* (§4) intenta abrir el menú aunque falte el paso.

El paso `pasar_raton` pone el ratón encima del elemento (sin hacer clic) y espera 0,3 s a que el menú
termine de abrirse.

> El **menú nativo del navegador** (Guardar como…, Copiar enlace…, Inspeccionar) no es parte de
> la página y no se puede automatizar. Para «Guardar enlace como…» usa un paso de **descarga**
> (clic en el enlace); para guardar una página que se abrió como HTML usa **Guardar página** (§6).

## 6. Cambiar el nombre de lo descargado (plantillas) y guardar páginas

Cada descarga es un paso **«Descargar → guardar como `<plantilla>`»** en la carpeta elegida.
Al grabar, el nombre propuesto es el original más `{ext}` (si el nombre original contenía la fecha
de hoy o de ayer, se convierte solo en plantilla). Edita el paso (doble clic) para cambiarlo:

```
Ventas_{hoy:%Y-%m-%d}{ext}      ->  Ventas_2026-10-23.csv
{cliente}_{inicio_mes:%Y%m}{ext}
```

Si ya existe un archivo con ese nombre, se guarda como `nombre (2).ext` (en las opciones del
flujo se puede cambiar a sobrescribir con `"si_existe": "sobrescribir"`).

**Varias descargas en un mismo flujo**: durante la grabación las descargas **no se cancelan**: se
completan y se copian a `descargas/grabacion/` con su nombre original, para que la web se comporte
con normalidad y puedas seguir bajando más reportes en la misma grabación. Cada una queda como su
propio paso «Descargar». Al ejecutar se guardan todas, cada una con su nombre.

### Guardar página (PDF, HTML o CSV)

Algunos reportes no se descargan: se **abren como una página HTML** (a veces en otra pestaña) y
el único modo de guardarlos es «clic derecho → Guardar como», que es el menú del navegador y no se
puede automatizar. Para eso está el paso **Guardar página** (`guardar_pagina`):

| Formato | Qué se guarda |
|---|---|
| `pdf` | La página impresa. En modo oculto se usa la impresión del navegador; en modo visible Chrome no permite imprimir la página en pantalla, así que el bot imprime una copia en un navegador oculto auxiliar con la misma sesión (mejor esfuerzo). Si no se puede, lo explica en el registro y guarda un `.html`. |
| `html` | El HTML de la página tal como está ahora (con `<base href>` para que la copia encuentre imágenes y estilos). |
| `csv` | La **tabla más grande** de la página (en `utf-8` con BOM, para que Excel lea bien los acentos). Espera a que haya alguna tabla. |

Se añade mientras grabas con el botón **💾 Guardar esta página** de la barra flotante, o después con
**Insertar paso ▾ → Guardar página…**. El nombre admite plantillas (`Informe_{hoy:%Y-%m-%d}`); la
extensión se añade sola. Si el informe está en otra pestaña, el paso lleva su número de pestaña.

### Plantillas disponibles

Valen en **cualquier texto** de un paso (dirección, texto a escribir, opción a elegir, texto a
esperar, nombre y carpeta de descarga):

| Plantilla | Resultado (si hoy es 23/10/2026) |
|---|---|
| `{hoy}` | 23/10/2026 (formato por defecto `%d/%m/%Y`) |
| `{ayer}` | 22/10/2026 |
| `{hoy:%Y-%m-%d}` | 2026-10-23 (cualquier formato `strftime`) |
| `{dias:-7}` · `{dias:-7:%d/%m/%Y}` | hace 7 días (`{dias:3}` = dentro de 3 días) |
| `{inicio_mes}` · `{fin_mes}` | 01/10/2026 · 31/10/2026 |
| `{inicio_mes_anterior}` · `{fin_mes_anterior}` | 01/09/2026 · 30/09/2026 |
| `{lunes_semana}` · `{lunes_semana_anterior}` · `{domingo_semana_anterior}` | (3.6) 19/10/2026 · 12/10/2026 · 18/10/2026 (la semana empieza el lunes) |
| `{inicio_anio}` | (3.6) 01/01/2026 |
| `{ext}` | extensión del archivo descargado, con punto (`.csv`) — solo en nombres de descarga |
| `{nombre}` | nombre original del archivo, sin extensión — solo en nombres de descarga |
| `{secreto:nombre}` | una contraseña guardada (ver más abajo) |
| `{cliente}` | variable propia (ver abajo) |
| `{fecha}` · `{fecha:%Y-%m-%d}` | (3.0) el día que se está descargando con «Repetir por días» (§16.5); sin repetir, hoy |
| `{opcion}` | (3.0) el texto de la opción que eligió el último paso «Elegir opción» (p. ej. `Corte_{opcion}{ext}`) |
| `{{` y `}}` | llaves literales `{` y `}` |

Al editar un paso, el botón **Plantilla…** inserta estas opciones y debajo ves una **vista
previa** del resultado.  Desde la 3.6 las fechas se eligen con un **calendario** (§24.2): no hace falta
escribir estas plantillas a mano (el calendario las escribe por ti).

### Variables propias

Escríbelas en el campo **Variables** de la ventana (`cliente=Acme; mes=octubre`), en el flujo
(`"variables": {"cliente": "Acme"}`) o en la línea de comandos (`--var cliente=Acme`).
La línea de comandos tiene prioridad sobre el flujo.

## 7. Contraseñas e inicio de sesión

### Inicio de sesión inteligente (2.3)

* Al grabar, lo que haces en el formulario de inicio de sesión (usuario, contraseña, licencia… el
  «ojito», los clics en el recuadro de cada campo y el clic en «Entrar» o la tecla Enter) se guarda
  como **un solo paso**: **«Iniciar sesión en «página» (si hace falta)»**. Los usuarios y demás datos
  quedan en el paso; la contraseña, como siempre, en el Administrador de credenciales.
* Al ejecutar ese paso, el bot espera a que la página cargue y mira si hay un formulario de inicio
  de sesión (un campo de contraseña visible):
  * **no lo hay** → «ya había una sesión abierta: se omite» y sigue;
  * **lo hay** → rellena los campos (también los de DevExpress con «clon», los de solo lectura o los
    que ya tienen el valor), pulsa «Entrar», espera a que cargue y **comprueba** que la página lo
    aceptó (el campo de contraseña desaparece o se pasa a otra página). Si sigue el formulario, anota
    el mensaje de error que muestre la página.
* **Sesión que caduca a mitad** (o reporte grabado con la sesión ya abierta): si el elemento de un
  paso no aparece en ~3 s y la página muestra un formulario de inicio de sesión, el bot entra con los
  datos del paso «Iniciar sesión» del reporte (o con los **Accesos** guardados de esa página, o
  preguntándote) y **repite el paso**.
* **Si falta algo o la contraseña es rechazada, te lo pide**: aparece la ventanita **«La página
  «…» pide iniciar sesión»** con los campos que detectó el bot en la página (etiquetas de los
  campos; las contraseñas con `*`), los valores que ya conoce y la casilla **Recordar** (marcada).
  Al aceptar, entra con esos datos y, si funcionan, los guarda: las contraseñas en el Administrador
  de credenciales y el resto (usuario, licencia…) en **🔑 Accesos**. **Cancelar** detiene el paso.
  Mientras espera tu respuesta, el botón **Detener** sigue funcionando.
* **Contraseña rechazada**: se pregunta **una sola vez** («La contraseña fue rechazada…»). El bot
  **nunca vuelve a enviar los mismos datos** que la página rechazó y como mucho intenta entrar **2
  veces por página** en cada ejecución, para no bloquear tu cuenta.
* **Sin ventana** (tareas programadas, `--sin-ventana`): nadie puede contestar, así que si falta la
  contraseña o la rechazan, el reporte falla con el mensaje *«Falta la contraseña de «página» (o fue
  rechazada). Abre el bot y ejecútalo una vez con la ventana para guardarla.»* y el código de salida
  es 1. Si lo ejecutas desde la ventana en modo oculto, la pregunta **sí** aparece.
* **Tus reportes de la 2.2** se convierten solos al abrir la ventana: los pasos de inicio de sesión
  del principio (escribir usuario, «ojito», escribir contraseña guardada, clic en «Iniciar Sesión» /
  «Aceptar»…) se juntan en un paso «Iniciar sesión». Antes de cambiar cada reporte se guarda una
  **copia** de cómo estaba: **Más ▾ → Versiones anteriores del reporte → Restaurar** la recupera.
  Las contraseñas guardadas no cambian de nombre.

### 🔑 Accesos

El botón **🔑 Accesos** lista, por página, los datos con los que el bot inicia sesión (usuario,
licencia… y el *nombre* de la contraseña, nunca su valor). Puedes **cambiar un valor**, **cambiar
una contraseña**, **borrar** un campo o **borrar la página entera** (también sus contraseñas
guardadas). Los valores de Accesos tienen preferencia sobre los grabados en el paso. **Contraseñas
sueltas…** abre la lista de todas las contraseñas guardadas (también en **Más ▾**).

### Contraseñas

* Cuando escribes en un campo de contraseña **mientras grabas**, el valor va directo al
  **Administrador de credenciales de Windows** (mediante `keyring`) con el nombre
  `dominio:campo` y el paso guarda solo `{secreto:dominio:campo}`.
  **Nunca** se escribe la contraseña en el archivo del flujo, ni en los registros, ni en
  la lista de pasos, ni en pantalla.
* **El «ojito» de «mostrar contraseña»**: un campo cuenta como contraseña si **alguna vez** fue
  `type=password` (aunque el ojito lo convierta en texto antes de escribir), si su `autocomplete`
  es `current-password`/`new-password` o si su id, nombre, etiqueta, *placeholder* o `aria-label`
  contiene «pass», «contraseña», «clave» o «pwd».
* **Convertir en contraseña**: si un flujo grabado con una versión anterior tiene la contraseña
  escrita en claro, selecciona el paso «Escribir» y pulsa **Convertir en contraseña**: el texto
  pasa al Administrador de credenciales y el paso queda como `{secreto:nombre}`. Después pulsa
  **Guardar**. Revisa también el archivo `.json` antiguo y la carpeta `registros/` por si la
  conservaban, y cambia la contraseña en la web si estuvo expuesta.
* Al ejecutar, aunque un campo de contraseña lleve el texto en claro, **su valor se enmascara**
  (`********`) en el registro y en la lista de pasos.
* **Contraseñas sueltas…** (en 🔑 Accesos o en **Más ▾**) lista los nombres guardados (jamás los
  valores), permite añadir o cambiar una y borrarla. Si cambias de contraseña en la web, el bot te
  la pedirá la próxima vez que la página la rechace (o cámbiala en 🔑 Accesos).
* Si un paso «Escribir» (fuera de un «Iniciar sesión») usa una contraseña que no existe en este
  equipo, el bot lo avisa antes de abrir el navegador. Las de los pasos «Iniciar sesión» se piden.
* **Sesión persistente**: cada reporte usa su propio perfil del navegador
  (`perfiles/reporte_<número>`), así que las *cookies* se conservan entre ejecuciones y **renombrar
  el reporte no pierde la sesión**. El perfil que se usó al grabar un reporte nuevo pasa a ser el
  suyo al guardarlo. Si la página recuerda tu sesión, el paso «Iniciar sesión» se omite solo. (Un
  reporte duplicado empieza con un perfil nuevo: sin la sesión iniciada.)
* No escribas contraseñas como texto normal en un paso: usa siempre `{secreto:nombre}`.

## 8. Visible u oculto

* **Ver mientras trabaja** marcado: el navegador se ve y la lista resalta el paso en curso
  (amarillo = en curso, verde = bien, gris = omitido o desactivado, rojo = error). **Modo lento**
  añade una pausa entre acciones para poder seguirlo.
* Sin marcar: el navegador trabaja **oculto** (*headless*): no ves nada, pero la lista de
  pasos, el registro y las capturas de error siguen funcionando.
* Grabar siempre se hace con el navegador visible.
* Puedes elegir **Chrome** o **Edge**.
* **Detener** para la ejecución en cuanto termina el paso actual (en un lote, también cancela los
  reportes que faltan).

Cada ejecución crea un registro en `registros/AAAA-MM-DD_HHMMSS.log` (cada paso con su duración;
sin contraseñas) y, si falla, una captura `…_error_pasoN.png` al lado.

## 9. Guardar en la aplicación y el panel «Reportes»

Los reportes se guardan **dentro de la aplicación**, en una pequeña base de datos
(`datos/bot.db`), no como archivos sueltos:

* **Guardar**: si el reporte es nuevo, pide solo el **nombre** (propone el del campo «Nombre del
  reporte»); si ya estaba guardado, lo actualiza sin preguntar (si cambiaste el nombre, lo renombra).
* **Guardar como…**: pide un nombre nuevo y crea **otro** reporte (el original no cambia).
* Al **terminar una grabación** se pide el nombre para guardarla (Cancelar = no guardar ahora).
* Los nombres no se pueden repetir (sin distinguir mayúsculas) ni llevar comillas dobles.
* **Cambios sin guardar**: el título de la ventana muestra `Nombre*`; antes de abrir otro reporte,
  empezar uno nuevo, importar o salir, el bot pregunta si quieres guardarlos (Sí / No / Cancelar).

A la izquierda de la ventana está el panel **Reportes**: lista **todos los reportes guardados**
con una casilla ☐, el nombre, la página, la **última vez** que se ejecutaron y su **último
resultado** (Bien / Falló / Detenido). El historial de ejecuciones también se guarda en la base de
datos y lo actualizan las ejecuciones programadas o por línea de comandos.

| Botón | Qué hace |
|---|---|
| **Nuevo** | Empieza un reporte nuevo en el editor. |
| **Abrir** (o doble clic) | Carga el reporte en el editor de la derecha (te avisa si había cambios sin guardar). |
| **Renombrar** | Cambia el nombre. Conserva su historial, sus tareas programadas y la sesión del navegador. |
| **Duplicar** | Crea «Nombre (copia)» (empieza con un perfil de navegador nuevo, sin sesión). |
| **Eliminar** | Pide confirmación y lo manda a la **Papelera**. |
| **Papelera…** | Lista los eliminados: **Recuperar** (si ya hay otro con su nombre, vuelve como «Nombre (recuperado)») o **Borrar definitivamente** (con confirmación). |
| **Ejecutar seleccionados** | Ejecuta, uno detrás de otro, los reportes con la casilla marcada. |
| **Ejecutar todos** | Ejecuta todos los reportes de la lista. |
| **Programar…** | Programa el reporte elegido, los marcados o todos (ver §10). |

Los lotes se ejecutan **de uno en uno** en segundo plano (visibles u ocultos según «Ver mientras
trabaja»); **si un reporte falla, se sigue con el siguiente** y al final se muestra un resumen
(bien / falló, archivos descargados). Cada reporte usa sus **propias opciones guardadas**
(navegador, tiempos, carpeta de descargas); de la ventana solo valen «Ver mientras trabaja»,
«Modo lento» y «Variables». El lote usa lo guardado, no los cambios sin guardar del editor.

### Exportar e importar (copias de seguridad y compartir)

En **Más ▾** de la barra de botones:

* **Exportar a un archivo (.json)…**: guarda el reporte del editor como archivo (copia de seguridad o
  para pasárselo a otra persona). Las contraseñas no van en el archivo (solo `{secreto:nombre}`).
* **Importar desde un archivo (.json)…**: añade un archivo como reporte nuevo (si el nombre ya existe,
  se llama «Nombre (2)») y lo abre. Lee también los archivos de versiones anteriores.

### Paso desde la versión 2.1 (archivos en `flujos/`)

La primera vez que se abre la 2.2 (o que se ejecuta por línea de comandos), los `.json` que haya en
`flujos/` y su historial `_historial.json` **se importan solos** a la aplicación y los archivos se
mueven a `flujos/_importados/` (no se borra nada). El perfil del navegador de cada uno pasa a
`perfiles/reporte_<número>`, así que no hay que volver a iniciar sesión. Las tareas programadas
antiguas (`--flujo "…\flujos\ventas.json"`) siguen funcionando: el bot busca el reporte importado de
ese archivo. Si un archivo no se puede leer, se queda en `flujos/` y se avisa en el registro.

## 10. Programar ejecuciones

El botón **Programar** crea una tarea del **Programador de tareas de Windows** (carpeta
`BotWeb`), diaria o semanal a la hora que elijas. (Desde la 3.4, en la interfaz nueva puedes elegir días, varias horas,
horas distintas según el día, «cada N horas» en un horario y fechas del mes: ver §21.) Puedes programar **un reporte**, **los reportes
marcados** (un lote) o **todos** (`--todos`). Muestra el comando exacto y **pide confirmación**
antes de crear nada. También puede eliminar la tarea.

* La tarea se ejecuta **oculta**, con tu usuario y **solo si tienes la sesión de Windows
  iniciada** (necesita tus contraseñas guardadas y el perfil del navegador).
* El reporte se guarda antes de programarlo. La tarea lo llama por su **número** (`--id 3`), así
  que puedes **renombrarlo** sin volver a programar. Si lo eliminas, la tarea fallará (código 2).
* Las rutas largas pueden superar el límite del Programador (261 caracteres); si pasa, mueve la
  carpeta del bot a una ruta más corta o programa «Todos los reportes».

## 11. Línea de comandos

```
python bot.py                                        # abre la interfaz nueva (3.0)
python bot.py --clasica                              # abre la ventana clásica (tkinter)
python bot.py --vigilar --id 3                       # revisa las vigilancias activas del reporte 3 y sale
python bot.py --vigilar                              # revisa TODAS las vigilancias activas (reportes y Páginas)
python bot.py --vigilancia-id 7                      # (3.3) revisa solo la vigilancia número 7
python bot.py --reporte "Ventas"                     # abre la ventana con ese reporte
python bot.py --reporte "Ventas" --ejecutar          # y lo ejecuta al abrir
python bot.py --reporte "Ventas" --sin-ventana --oculto --var cliente=Acme
python bot.py --id 3 --url https://otra-web.com/ --sin-ventana --visible --lento
python bot.py --reporte "Ventas" --reporte "Clientes" --sin-ventana   # varios seguidos (lote)
python bot.py --id 3 --id 5 --sin-ventana                             # por número
python bot.py --todos --sin-ventana                                   # todos los reportes guardados
python bot.py --flujo copia.json --sin-ventana                        # un archivo exportado (.json)
python bot.py --id 10 --sin-ventana --filtro "Elegir corte=43 - 2026 (02/10/2026 - 08/10/2026)"   # (3.1) otra opción
python bot.py --id 10 --sin-ventana --filtro "6=43 - 2026 (…)" --filtro "6=42 - 2026 (…)"             # dos descargas
```

`--reporte`/`--id` con `--ejecutar` también valen con la interfaz nueva (abre la ventana y lo ejecuta).

| Opción | Significado |
|---|---|
| `--reporte NOMBRE` | reporte guardado en la aplicación, por su nombre (sin distinguir mayúsculas). **Se puede repetir** |
| `--id N` | reporte guardado, por su número (el que usan las tareas programadas). **Se puede repetir** |
| `--todos` | ejecuta todos los reportes guardados |
| `--flujo ARCHIVO` | un archivo `.json` (compatibilidad; se busca tal cual, en el proyecto y en `flujos/`). Si ya no existe porque se importó a la aplicación, se usa el reporte importado. Se puede repetir |
| `--db ARCHIVO` | base de datos de reportes (por defecto `datos/bot.db`) |
| `--carpeta-flujos CARPETA` | carpeta de flujos antiguos (`.json`) que se importan a la aplicación (por defecto `flujos/`) |
| `--url URL` | sustituye la dirección del reporte (solo con un único reporte) |
| `--oculto` / `--visible` | navegador oculto o visible (con `--sin-ventana` el defecto es oculto) |
| `--var clave=valor` | variable para las plantillas (repetible) |
| `--sin-ventana` | ejecuta y sale, sin interfaz; código de salida **0** = todo bien, **1** = algo falló (en un lote, si falla **algún** reporte), **2** = no se pudo abrir el reporte (no existe, archivo dañado…) |
| `--ejecutar` | en la ventana, ejecuta nada más abrir (si hay varios marcados, los ejecuta como lote) |
| `--lento` | modo lento |
| `--navegador chrome\|msedge` | navegador |
| `--descargas`, `--perfil`, `--registros` | carpetas de descargas, perfil del navegador y registros (en un lote, `--perfil` es la carpeta que contiene un perfil por reporte) |
| `--smoke` | construye la ventana clásica con una base de datos temporal y sale (comprobación rápida; no toca tus reportes) |
| `--clasica` | (3.0) abre la ventana clásica (tkinter) en lugar de la interfaz nueva |
| `--vigilar` | (3.0) revisa las vigilancias activas de `--id`/`--reporte` (o de `--pagina`/`--pagina-id`; sin nada, TODAS las activas), avisa de lo nuevo y lo descarga si está configurado; sin ventana. Código 0 = bien, 1 = alguna revisión o descarga falló, 2 = nada que vigilar |
| `--vigilancia-id N` | (3.3) revisa solo la vigilancia número N (aunque esté pausada); es lo que ejecutan las tareas de «Programar en Windows…» de cada vigilancia. Código 2 si no existe |
| `--smoke-web` | (3.0) arranca la interfaz nueva con una base de datos temporal, la carga en un navegador oculto, recorre todas sus páginas comprobando que no hay errores y sale |
| `--puerto N`, `--sin-navegador` | (3.0) interfaz nueva: puerto fijo / no abrir la ventana (solo imprime la dirección) |
| `--filtro FILTRO=VALOR` | (3.1) solo con un reporte: elige otra opción en un filtro **solo para esta ejecución** (el reporte guardado no cambia). FILTRO = el nombre del filtro como en «Usar filtros» (sin distinguir mayúsculas) o el número de paso (`6` o `paso 6`); VALOR = el texto de la opción, `más reciente`, `primera` o `última` (en las fechas, el texto o plantilla, p. ej. `{ayer:%d/%m/%Y}`). Repetible; el mismo filtro varias veces = una ejecución por valor (el nombre del archivo lleva « - <opción>»). Código 2 si el filtro no existe |

Sin ventana no se puede preguntar nada: si una página pide una contraseña que falta o que rechaza,
ese reporte falla con un mensaje claro («…Abre el bot y ejecútalo una vez con la ventana para
guardarla.») y el código de salida es 1. Al empezar, los reportes guardados con la 2.2 se actualizan
igual que al abrir la ventana (con copia de seguridad).

En un lote, el resumen final se imprime en la consola. Cada ejecución de un reporte guardado se anota
en su historial (el que ves en el panel Reportes); las de un archivo `--flujo` que no está en la
aplicación no se anotan.

## 12. Estructura de carpetas

```
bot.py            ventana clásica + línea de comandos (y arranque de la interfaz nueva)
ui/               interfaz nueva: index.html, app.js, app.css y tema.css (colores; sin Internet);
                  3.5: ui/fuentes/ (Chakra Petch, IBM Plex Sans y Mono, licencia OFL; sin CDN)
webbot/           flujo.py, plantillas.py, secretos.py, grabador.js, grabador_web.py,
                  ejecutor.py, programador.py, navegador.py, lote.py, almacen.py (base de datos),
                  accesos.py (datos de acceso por página); 3.0: servidor_ui.py (servidor de la interfaz),
                  mapeador.py + mapeador.js (Mapear página), vigilancia.py, avisos.py (notificaciones);
                  3.1: filtros.py (panel «Usar filtros»); 3.4: horario.py (programación), correo.py +
                  correo_web.py, correo_outlook.py, correo_gmail.py, correo_imap.py (sección «Correo»)
datos/bot.db      reportes guardados, papelera, historial de ejecuciones, copias de versiones
                  anteriores (tabla versiones) y accesos por página (sin contraseñas) (SQLite); 3.0:
                  notificaciones, estado de las contraseñas (rechazada / funcionó, sin la contraseña),
                  vigilancias, opciones vistas, mapas de páginas y ajustes; 3.1: opciones de los filtros
                  (opciones_filtro); 3.4: cuentas de correo, búsquedas de correo y correos ya procesados
flujos/           solo para importar flujos .json antiguos; _importados/ con los ya importados
descargas/        archivos descargados (y descargas/grabacion/ con lo bajado al grabar)
registros/        registros y capturas de error
perfiles/         perfil del navegador (sesiones) de cada reporte: reporte_<número>; 3.4: correo_<número>
                  (la sesión de cada cuenta de Outlook/Gmail)
tests/            pruebas (con un sitio de prueba local en tests/sitio_prueba/)
version_escritorio/   versión 1 (coordenadas de pantalla), conservada
```

Haz copia de `datos/bot.db` (con el bot cerrado) o usa **Exportar** para guardar tus reportes.

Los reportes exportados son JSON legibles; puedes editarlos a mano e importarlos. Tipos de paso:
`abrir_url`, `clic`, `escribir`, `tecla`, `seleccionar`, `marcar`, `esperar_elemento`,
`esperar_texto`, `esperar_segundos`, `descargar`, `guardar_pagina` (`formato`: `pdf`, `html` o
`csv`, más `nombre` y `carpeta`), desde la 2.2, `pasar_raton` (`selectores`, `objetivo`; `auto`
si lo añadió el grabador) y, desde la 2.3, `iniciar_sesion` (`sitio`, `campos`: lista de
`{selectores, etiqueta, tipo: texto|clave, clave, valor | secreto}`, `enviar`: `{selectores}` o
`{tecla: "Enter"}`) y, desde la 3.0, `elegir_opcion` (`selectores` de la lista, `objetivo`, `estrategia`:
`fija`|`mas_reciente`|`primera`|`ultima`|`contiene`, `valor`). Los reportes de la 2.3 y 3.0 llevan `"version": 3`. Campos comunes de un paso: `nota`, `opcional`, `timeout`, `pagina`,
`marco`, y desde la 2.1 `desactivado`, `espera_grabada` y (en «escribir») `fecha_directa`. Opciones
del flujo: `navegador`, `timeout_paso` (60), `timeout_descarga` (600), `pausa_entre_pasos` (0,3),
`carpeta_descargas`, `si_existe`, (2.2) `recuperacion_automatica` (`true`) y (2.3) `esperar_carga`
(`true`); cada paso puede llevar `esperar_carga: true|false` para forzarlo. Desde la 3.0, `repetir_dias`:
`null` o `{"modo": "fijo"|"ultimos"|"mes_hasta_ayer"|"ayer", "desde": "AAAA-MM-DD", "hasta": "AAAA-MM-DD", "n": 7}`.

## 13. Limitaciones

* El **menú contextual nativo** del navegador no se puede automatizar (sí los menús de clic
  derecho que ofrece la propia web). Para guardar un informe HTML usa **Guardar página**.
* **PDF en modo visible**: es de mejor esfuerzo (se imprime una copia de la página en un navegador
  oculto auxiliar); si la página depende de datos que solo existen en la pestaña original puede
  salir distinta. No se ha podido verificar con todos los sitios.
* **CAPTCHA** y **verificación en dos pasos (2FA)** no se pueden automatizar; el perfil
  persistente ayuda a no repetir el inicio de sesión.
* Si la web cambia mucho su diseño, puede haber que regrabar algún paso.
* Los selectores se calculan sobre el DOM normal de la página: elementos dentro de *shadow DOM*
  de la propia web o marcos de otro dominio se graban en mejor esfuerzo.
* La detección de calendarios se basa en que el calendario tenga una clase o id como
  `datepicker`, `calendar`, `picker`, `flatpickr`, `daterangepicker`, `mat-calendar`…; con otros
  nombres se graban los clics normales (que también funcionan).
* No se graban arrastres de ratón, subida de archivos ni teclas sueltas (solo Enter/Escape en
  campos). Para otras teclas, inserta un paso «Pulsar tecla» editando el JSON.
* No uses el mismo flujo (mismo perfil) en dos ejecuciones a la vez; los lotes ya van de uno en uno.
* La detección de **menús que se abren al pasar el ratón** al grabar es una heurística: se basa en
  que la opción parezca de menú (enlace, `li`, botón, `role=menuitem`, clases con «menu», «nav»,
  «dropdown», «dxm», «item»…), en que el ratón se quede encima al menos 0,15 s y en que aparezca algo
  (en menos de 0,6 s) que contenga lo que luego pulsas. Si no se detecta, usa **🖱 Pasar el ratón** o
  confía en la recuperación automática. Puede añadir algún «Pasar el ratón» de más (inofensivo).
* La recuperación automática se intenta **una vez por paso** y solo pasa el ratón o repite el clic
  anterior si abre una lista que está cerrada; nunca hace clic en opciones al azar.
* El bot necesita que Chrome o Edge estén instalados; no descarga navegadores.
* **Inicio de sesión**: el formulario se reconoce por un campo de contraseña visible (o el «clon»
  visible de DevExpress). Inicios de sesión en varias pantallas (primero el usuario y luego, en otra,
  la contraseña), CAPTCHA o códigos por SMS no se automatizan: el bot te pedirá lo que vea, pero no
  puede resolver un CAPTCHA. Si dos reportes usan la misma página con **usuarios distintos**, los
  Accesos de esa página (que tienen preferencia) valen para los dos: en ese caso no marques
  «Recordar» o borra el usuario en 🔑 Accesos.
* **Esperas de carga**: los indicadores se reconocen por sus clases, ids, roles y textos habituales;
  un indicador con otro nombre no se espera (las esperas de elemento siguen funcionando), y algo que
  se llame «progress»/«loading» y se quede visible puede retrasar un paso hasta 30 s (se da por
  atascado; las capas sin rueda, ~3 s). Si una página concreta da problemas, quita la casilla en ese
  paso o en el reporte.
* **Mapear página** (3.0): solo mira el documento principal (no dentro de iframes) y reconoce las listas
  habituales (nativas, Vuetify, Material, select2, `role=combobox`…); las listas que solo se rellenan al
  elegir otra se leen con «Actualizar opciones». Los selectores son los del grabador, así que, como los
  grabados, pueden necesitar un retoque si la web cambia mucho.
* **Vigilancia** (3.0): se vigila un paso «Elegir opción»; si el reporte tenía la lista grabada como dos clics,
  conviértela antes («Convertir listas…» en el editor). «Lo más reciente» se decide por la fecha más alta
  del texto, luego el año y luego el primer número (vale para «45 - 2026 (…)», «Octubre 2026»,
  «2026-10-25»…). Las notificaciones de Windows necesitan la sesión de Windows iniciada.
* **Interfaz nueva** (3.0): es una página local (solo en este equipo, `127.0.0.1`) para una persona; si la
  cierras se apaga sola al rato (si no hay nada ejecutándose). La ventana clásica sigue con `--clasica`.

## 14. Solución de problemas

* *«No se pudo abrir Chrome…»*: comprueba que Chrome/Edge están instalados y que no hay otra
  ejecución usando el mismo perfil. Prueba a cambiar de navegador en las opciones.
* *«No apareció ningún elemento…»* / *«…sigue deshabilitado…»*: la página cambió o tardó más de lo
  previsto. Mira la captura del error en `registros/`, sube el tiempo máximo del paso (o la
  espera máxima de descargas/reportes) o regraba ese paso.
* *Faltan contraseñas guardadas*: abre **🔑 Accesos → Contraseñas sueltas…** y guarda la que se indica.
* *«Falta la contraseña de «…» (o fue rechazada)…»* en una tarea programada: abre el bot, ejecuta ese
  reporte una vez con la ventana, escribe la contraseña cuando la pida (con «Recordar» marcado).
* *«Son los mismos datos que «…» ya rechazó»* / *«volvió a rechazar»*: el bot no insiste para no
  bloquear tu cuenta; comprueba usuario y contraseña en la web y cámbialos en **🔑 Accesos**.
* *Un reporte actualizado a la 2.3 no funciona como antes*: **Más ▾ → Versiones anteriores del
  reporte → Restaurar** devuelve la versión de antes (y avísanos).
* *Un paso espera mucho «a que termine de cargar»*: el registro dice qué indicador o petición espera;
  si no es un indicador real de la página, pon «Esperar a que la página cargue después: no» en ese
  paso (o quita la casilla en las opciones del reporte).
* *El paso de un calendario falla de vez en cuando*: regraba la fecha (se anotará como fecha
  directa) o sube la «Pausa entre pasos».
* *Se queda esperando una opción de un menú* («esperando a que «Administrar…» esté disponible»):
  comprueba que «Recuperación automática» está marcada; si aun así no la encuentra, inserta antes un
  paso **Pasar el ratón** sobre la opción del menú de la que cuelga (o regrábalo pasando el ratón
  despacio por el menú).
* *Se queda esperando un «Escribir» en una lista* («esperando a que «Open» esté disponible»): era el
  texto que la web pone al elegir la opción; en la 2.2 ese paso termina solo. En flujos antiguos
  puedes desactivarlo.
* *Mis reportes de antes no aparecen*: mira `flujos/_importados/` (ya están importados) y el
  registro de la ventana por si alguno no se pudo leer; también puedes usar **Más ▾ → Importar**.

## 15. Pruebas

```
python -m unittest discover -s tests -v
```

Desde la 3.0 hay además `tests/test_v30.py` (estrategias de «Elegir opción», conversión de listas con la forma
real de Portal, «Repetir por días», contraseñas rechazadas, base de datos v3, programar la vigilancia, `--vigilar`,
mapeador), `tests/test_integracion_v30.py` (página tipo Portal `portal.html`: los menús de Vuetify no hacen esperar
y la rueda sí; «Elegir opción» con lista virtual; repetir por días; Accesos al grabar; contraseña rechazada con y sin
ventana; mapear la página y ejecutar los pasos generados; vigilancia que detecta el corte nuevo y lo descarga una
vez) y `tests/test_servidor_ui.py` (API: token, origen, reportes, ejecutar con progreso y pregunta de acceso,
mapear; la ventana «La contraseña falló» en la página; `--smoke-web`).

Las pruebas unitarias (plantillas, flujo, secretos con almacén en memoria, programador, lotes,
historial, la base de datos de reportes en `tests/test_almacen.py` y, en `tests/test_v23.py`, la
conversión de los reportes de la 2.2 —con las formas reales de Portal y del ERP—, las copias de
versiones y los accesos) no usan navegador. Las de
integración (`tests/test_integracion.py`, `tests/test_integracion_v21.py`,
`tests/test_integracion_v22.py`, `tests/test_integracion_v23.py`) levantan un sitio local de prueba (`tests/sitio_prueba/`: login,
reporte lento con botón deshabilitado, calendario propio con dos instancias, «ojito» de
contraseña, varias descargas, informe en otra pestaña, menú CSS `:hover` anidado, menú tipo
DevExpress con submenús aparte, lista con autocompletar tipo Vuetify, inicio de sesión con sesión en
`localStorage`, licencia, campos tipo DevExpress y sesión que caduca, página con rueda de carga,
postback de ASP.NET, `jQuery.active`, petición lenta, capa que tapa los clics y consultas cada
200 ms…) y graban/ejecutan en modo
oculto con Chrome; usan un almacén de contraseñas en memoria y bases de datos temporales, y **no**
crean tareas programadas ni usan el ratón o teclado reales (el «ratón» es el del navegador oculto).
`tests/test_gui.py` y `tests/test_gui_v23.py` ejercitan el panel Reportes, guardar/renombrar/papelera,
la lista de pasos, la pregunta «la página pide iniciar sesión» (hilo de trabajo ↔ ventana), los
cuadros Accesos y Versiones y la actualización de reportes al abrir, sin interacción humana. En total
unas 294 pruebas; tardan unos 11 minutos. Ninguna muestra notificaciones de Windows (el notificador es
inyectable y no hace nada mientras se ejecuta `unittest`).
Las pruebas de la versión 1: `cd version_escritorio` y `python -m unittest discover -s tests`.

Desde la 3.1, `tests/test_v31.py` (regla de novedad con la forma real del reporte 10: «45 - 2023» y «45 - 2025» no son
novedad y «45 - 2026» sí, una sola descarga; opciones sin fecha; orden de la API de Vigilancia; nombres de los filtros sin
«Open»; panel, combinaciones, nombres de archivo, «Guardar como predeterminado», `--filtro`) y
`tests/test_integracion_v31.py` (página tipo Portal con `aria-label="Open"`: mapa con nombres de verdad, panel por la API,
descargar una vez / varias / confirmar, predeterminado con copia, «Actualizar opciones» y listas dependientes, vigilancia
que marca «nueva», `--filtro`, y la página: el panel se abre sin errores y la Vigilancia muestra primero lo más reciente).

## 16. Novedades de la 3.0 en detalle

### 16.1 Por qué Portal iba lento (y el arreglo)

En los registros del 26/10 (`registros/2026-10-26_083056.log` y `_081817.log`), después de cada clic que abría una
lista de Portal («Clic en «div»») el bot se quedaba **unos 30 s** con *«esperando a que termine de cargar… (indicador
#v-menu-v-32.v-overlay.v-overlay--absolute)»* y luego *«un indicador de carga sigue visible pero la página no hace
nada desde hace 30 s: se continúa»*. Eran **4 pasos × 30 s ≈ 2 minutos perdidos** por ejecución.

La causa: Portal está hecho con Vue/Vuetify, y en Vuetify **el menú abierto de una lista también es un
`v-overlay--active`**, la misma clase que usa la capa de «cargando…». El bot de la 2.3 lo tomaba por una rueda de carga
(y además el menú se queda en la página con esa clase después de elegir). En la ejecución que se detuvo, ese menú abierto
también tapaba el paso «Pasar el ratón».

El arreglo (en la espera de carga del ejecutor):

* **No son carga** los menús, listas desplegables, popovers, diálogos y tooltips: `role=menu|listbox|dialog|tooltip|
  combobox`, clases `v-menu`, `v-select`, `v-autocomplete`, `dropdown`, `popover`, `menu`… y las capas que contienen
  opciones, elementos de lista, campos o botones.
* Una **capa** (`v-overlay--active`, «overlay») solo cuenta como carga si **dentro hay una rueda o barra de verdad**
  (`.v-progress-*`, `role=progressbar`, clases de spinner/loader, `aria-busy=true`) o un texto «Cargando…».
* Lo que no es claramente una rueda (capas sin nada dentro, clases «busy»/«wait») se deja de esperar en cuanto la página
  lleva **~3 s sin hacer nada** (antes 30 s).
* Las ruedas de verdad **se siguen esperando** lo que haga falta: los ~80 s que tarda Portal en generar el reporte tras
  «Generar» (`.loader-container`) son el sitio trabajando de verdad y el bot los respeta.
* Si un elemento sigue tapado tras varios intentos (otro menú abierto encima), el bot le envía el clic o el «pasar el
  ratón» directamente.

La prueba `tests/test_integracion_v30.py` reproduce la página (un `v-overlay v-menu` que se queda con `--active`, más una
rueda `v-progress-circular` real): con la 2.3 cada paso de lista tardaba 30 s; ahora menos de 3 s, y la rueda se espera.

### 16.2 Accesos: cómo funciona ahora

* **La primera vez se guardan solos.** Lo que escribes al **grabar** en el formulario de inicio de sesión (usuario,
  licencia… y la contraseña) queda guardado en **Accesos** para esa página, y la ventana lo confirma: *«Se guardaron los
  datos de acceso de «portal.ejemplo.com»»*. La contraseña va, como siempre, al **Administrador de credenciales de
  Windows**; en la base de datos solo queda su nombre. Lo mismo si el bot te pide los datos al ejecutar y aciertas.
* **Si la contraseña cambia en la web** y la página la rechaza:
  * **Con la ventana abierta**: aparece **«La contraseña de «…» falló»**, que explica qué pasó, muestra la página y el
    usuario (que puedes corregir), un campo para la **contraseña nueva** (con **Mostrar/Ocultar**) y los botones
    **Guardar y reintentar** / **Cancelar**. La nueva se guarda y el bot sigue.
  * **Sin nadie delante** (tarea programada, `--sin-ventana`, `--vigilar`): el bot **no espera** ni **vuelve a probar la
    misma contraseña** (ni en esa ejecución ni en las siguientes, para no bloquear la cuenta): la marca como
    *rechazada (fecha)*, crea un aviso en la aplicación (la campana 🔔) y una **notificación de Windows**: *«La contraseña
    de «…» cambió: actualízala en Accesos»*. Al **abrir el aviso** aparece la misma ventana para escribir la nueva
    (**Guardar y reintentar** vuelve a ejecutar el reporte).
  * Cuando la contraseña se cambia (en Accesos, en esa ventana o en «Contraseñas sueltas…»), la marca desaparece sola.
* **Página Accesos** (interfaz nueva): cada página con sus datos y el estado de la contraseña: **guardada ✓**,
  **rechazada ✗ el …** o **falta**; botones **Cambiar contraseña**, **Probar acceso** (ejecuta solo el inicio de sesión
  de un reporte que use esa página, con un perfil temporal sin sesión, para comprobar que entra) y **Borrar**.

### 16.3 Paso «Elegir opción»

Para listas desplegables, nativas (`<select>`) o propias de la web (Vuetify `v-select`/`v-autocomplete`, `combobox`,
select2…). El bot abre la lista, **lee todas sus opciones** (también en las listas «virtuales» que solo dibujan lo que se
ve: las va desplazando) y elige según la **estrategia**:

| Estrategia | Elige |
|---|---|
| `fija` | la opción con ese texto exacto (lo de siempre) |
| `mas_reciente` | la más reciente: fecha más alta del texto, luego el año, luego el número inicial — «45 - 2026 (16/10/2026 - 22/10/2026)» gana a «44 - 2026 (…)»; «Octubre 2026» a «Septiembre 2026» |
| `primera` / `ultima` | la primera / la última de la lista |
| `contiene` | la primera que contiene el texto (o casa con él como expresión regular); admite plantillas, p. ej. `{hoy:%d/%m/%Y}` |

El grabador sigue grabando los clics («clic en la lista» + «clic en la opción»). Para convertirlos: en el editor,
**Convertir listas…** (o en la ventana clásica, **Más ▾ → Convertir listas en «Elegir opción»…**) muestra los pares y te
deja elegir la estrategia de cada uno. No se hace solo: tus reportes no cambian hasta que lo pidas. «Mapear página» (§16.6)
crea directamente pasos «Elegir opción». Tras el paso, `{opcion}` vale el texto elegido (útil en el nombre del archivo).

### 16.4 Vigilancia: avisar cuando llega un corte nuevo (y descargarlo)

Ejemplo: en Portal, «Elegir corte» tiene esta semana «44 - 2026 (09/10/2026 - 15/10/2026)» y la que viene tendrá
«45 - 2026 (…)». En la página **Vigilancia** eliges, para un reporte, el paso «Elegir opción» que quieres vigilar y:

* **Revisar ahora**: el bot ejecuta el reporte **hasta ese filtro** (iniciando sesión si hace falta), lee sus opciones y
  las compara con las que ya había visto. La **primera revisión** solo apunta lo que hay (es la referencia).
* Si aparecen opciones nuevas: aviso en la aplicación y **notificación de Windows**: *«Llegó un corte nuevo en «Portal,
  metricas»: 45 - 2026 (…)»*, con el botón **Descargar** (ejecuta el reporte con esa opción elegida).
* **Descargar automáticamente lo nuevo**: ejecuta el reporte una vez por cada opción nueva. Lo descargado queda
  apuntado y **no se vuelve a descargar**.
* **Cada N horas** o **cada día a una hora**: **Programar en Windows…** crea (tras mostrarte el comando y confirmarlo) una
  tarea que ejecuta `python bot.py --vigilar --id N --oculto`.

### 16.5 Repetir por días (y «cada día descargar el día anterior»)

En las opciones del reporte (editor → *Opciones del reporte*), **Repetir por días** ejecuta el reporte **una vez por
cada día** de un rango: **entre dos fechas**, **los últimos N días** (hasta ayer), **desde el inicio del mes hasta ayer**
o **solo ayer**. En cada vuelta, `{fecha}` vale ese día: úsalo en los campos de fecha (`{fecha}` = 25/10/2026,
`{fecha:%Y-%m-%d}` = 2026-10-25) y en el nombre del archivo (`Ventas_{fecha:%Y%m%d}{ext}`), para que no se pisen.

**«Cada día descargar el día anterior»**: no hace falta vigilancia. Escribe `{ayer}` (o `{ayer:%Y-%m-%d}`) en el campo de
fecha del reporte y prográmalo **diario** (editor del reporte → **Programar…**, o **Programar** en la ventana clásica). Hoy 26 descarga
el 25; mañana 27, el 26. Para recuperar días atrasados, usa «Repetir por días» → «los últimos N días».

### 16.6 Mapear página / Sacar filtros

En **Mapear página** eliges un **reporte guardado** (o escribes una **dirección**) y pulsas **Abrir el navegador**. El
bot abre el navegador (visible), inicia sesión con el paso «Iniciar sesión»/Accesos y ejecuta el reporte **hasta justo
antes de su primer filtro** (o hasta el paso que elijas; también puedes navegar tú a mano). Después:

* **Mapear toda la página** o **Mapear una parte…** (en el navegador pasas el ratón sobre la zona de los filtros —se
  resalta— y haces clic).
* El bot encuentra **pestañas** («Corte», «Crédito y Cobros»), **listas** propias y nativas («Filtro por sistema» =
  Portal, «Seleccione reporte», «Elegir corte», «Formato a Exportar» = Excel) —abre cada una para leer sus opciones y
  la cierra con Esc—, **fechas**, **textos**, **casillas** y **botones** («Generar», «Buscar», «Consultar», «Ver
  reporte», «Exportar», «Descargar»), cada uno con su etiqueta (`<label>`, etiqueta flotante, texto de ayuda como
  «Filtro por sistema», placeholder…), su valor actual, sus opciones y sus selectores (los mismos que calcula el grabador).
* **Actualizar opciones**: si una lista depende de otra («reporte → corte»), elige el valor en la primera y el bot vuelve
  a leer las siguientes.
* Marcas qué filtros **traer** y cómo: la opción **fija**, la **más reciente**…; para fechas **hoy**, **ayer**, `{fecha}`,
  inicio/fin de mes o una fija; para botones, **clic** o **clic y descargar**.
* **Crear pasos**: un **reporte nuevo** (los pasos del reporte hasta ese punto + los nuevos) o **reemplazar / añadir** en
  el reporte elegido (se guarda antes una copia de la versión anterior). **Guardar el mapa** lo apunta; al volver a
  mapear más tarde se muestra **qué cambió** (filtros u opciones nuevos o quitados).

### 16.7 La interfaz nueva (y la clásica)

`python bot.py` (o `iniciar.bat`) arranca un pequeño servidor **solo en este equipo** (`127.0.0.1`, puerto libre) y
abre una ventana tipo aplicación (Edge o Chrome con `--app`; si no hay, el navegador predeterminado). Funciona **sin
Internet** (sin librerías externas). Cada vez se crea un **permiso (token) nuevo** que la página manda en cada petición,
y se rechazan las peticiones de cualquier otra página web. Si cierras la ventana, el bot se apaga solo al poco (si no
hay nada ejecutándose).

Menú de la izquierda: **Inicio** (reportes guardados, ejecutados hoy, fallidos, novedades de vigilancia; últimas
ejecuciones, próximas tareas programadas y notificaciones), **Reportes** (Ejecutar, *Ver mientras trabaja*, Editar
pasos, Grabar nuevo, Duplicar, Eliminar, Papelera, ejecutar varios), **Editor de pasos** (editar, activar/desactivar,
subir/bajar, insertar; opciones del reporte y «Repetir por días»), **Grabar**, **Mapear página**, **Vigilancia**,
**Historial** (cada ejecución con su registro y la captura del error), **Accesos** y **Ajustes** (tiempos, navegador,
carpeta de descargas, recuperación automática, esperas de carga). Las preguntas del bot («La página pide iniciar
sesión», «La contraseña falló») aparecen como ventanas en la página. La campana 🔔 muestra los avisos.

**Colores**: están en `ui/tema.css` como variables. La paleta es **provisional**
(barra lateral casi negra, rojo de marca, paneles blancos, fondo gris claro): sustituye los valores marcados con
«PROVISIONAL» por los códigos oficiales de la marca.

La **ventana clásica** (tkinter) sigue igual con `python bot.py --clasica` (y la línea de comandos no cambia).

## 17. Novedades de la 3.1 en detalle

### 17.1 Usar filtros

El mapa de la página ya sabía qué filtros tiene un reporte; ahora **te los trae para usarlos**. En **Reportes** cada
reporte tiene el botón **⚙ Usar filtros** (también en el editor de pasos y en Vigilancia). El panel muestra cada filtro
del reporte (los pasos «Elegir opción», las listas nativas «Seleccionar» y los campos de fecha) con:

* su **nombre** («Elegir corte», «Formato a Exportar»…): el que guardaste, la etiqueta del filtro en el último mapa,
  el nombre del paso, la etiqueta que se lee en la página o lo que se deduce de sus opciones («Corte», «Periodo»,
  «Formato»). Nunca «Open», «Abrir» ni nombres de iconos (era la etiqueta que Vuetify pone a sus listas). Si no hay
  ninguno bueno sale «Lista del paso N»: pulsa **Renombrar**. Si dos filtros se llaman igual, uno lleva «(paso N)».
* una lista con **todas las opciones conocidas**. Las listas de periodos (cortes, meses, fechas) van **de la más reciente
  a la más antigua** (por la fecha del texto, no por el orden de la página) y la más reciente lleva ★ y «más reciente»;
  las demás, en el orden de la página. La primera opción es **«La más reciente (hoy: 44 - 2026 …)»**, que es lo que hace
  el reporte si está guardado así.
* **Elegir varias**: marca 42, 43 y 44 y el reporte se ejecuta **una vez por opción** (si eliges varias en varios filtros,
  una vez por combinación; con más de 10 ejecuciones te pide confirmación, máximo 100). Para que los archivos no se pisen,
  si el nombre del archivo no lleva `{opcion}`, se le añade « - <opción>», p. ej. `Reporte - 43 - 2026 (02_10_2026 -
  08_10_2026).xlsx`. (Se añade el texto de las opciones que cambian, no `{opcion}`, porque `{opcion}` es la última lista
  elegida, que en Portal es «Formato a Exportar».)
* **actualizado el …** y de dónde salen las opciones: del **mapa** de la página, de la última **ejecución** (el bot lee
  la lista entera cada vez que elige una opción), de la **vigilancia** o de **Actualizar opciones**. Lo que llegó nuevo
  según la vigilancia lleva la marca **nueva** durante 7 días.

Botones:

* **Descargar con estos filtros**: ejecuta el reporte con lo elegido **sin cambiar el reporte guardado** (en el registro:
  «Filtros elegidos para esta ejecución (el reporte guardado no cambia): paso 6 «Elegir corte» = «43 - 2026 (…)»»).
* **Guardar como predeterminado**: escribe lo elegido (y los nombres de los filtros) en el reporte; antes guarda una copia
  en **Versiones**.
* **Actualizar opciones**: ejecuta el reporte (oculto) **hasta el último filtro**, leyendo la lista de cada filtro, y
  guarda las opciones. No genera ni descarga nada.

**Listas que dependen de otras** («Elegir corte» depende de «Seleccione reporte»): las opciones se guardan por
combinación de lo elegido en los filtros anteriores. Si cambias el «reporte» y no hay opciones guardadas para esa
combinación, se muestra la última lista conocida con una nota; pulsa **Actualizar opciones** para leer la de esa
combinación (si una opción elegida no está en la lista nueva, para seguir leyendo se toma la primera).

### 17.2 Vigilancia: qué cuenta como «nuevo»

El 26/10 la página Vigilancia mostraba arriba «45 - 2023 (20/10/2023 - 26/10/2023)», que parecía el corte nuevo 45, y al
pulsar Descargar se bajó el de 2023 (`registros/2026-10-26_112042.log`). La página mostraba las opciones en el orden de la
web **al revés** (el final de la lista, que son los cortes más antiguos). Ahora:

* La lista va **de la más reciente a la más antigua** según la fecha del texto (`clave_reciente`: fecha más alta, luego
  el año, luego el número), con la marca **más reciente** y el periodo legible («año 2026 · del 09/10/2026 al
  15/10/2026»).
* **Regla de novedad**: una opción que se ve por primera vez solo es **nueva** (aviso «Llegó un corte nuevo…», descarga
  automática) si es **más reciente que la más reciente que ya se conocía**. Si aparecen cortes antiguos por primera vez
  (la web añadió historial o el bot leyó entera una lista larga), se apuntan **en silencio** como históricos: sin aviso
  ni descarga.
* Si la opción nueva **no lleva fecha, año ni número** (no se puede saber si es más reciente), se avisa como «Opción
  nueva en «…» (sin fecha…)», sin decir que sea un corte nuevo, y **no se descarga sola** salvo que marques **Descargar
  también opciones nuevas sin fecha**.
* Cada revisión deja además la lista en las opciones del filtro («Usar filtros»).

## 18. Novedades de la 3.2 en detalle: Páginas

### 18.1 Qué es una Página

Hasta la 3.1, un mapa («Mapear página») servía una sola vez: creaba un reporte con pasos fijos. Una **Página** es una
**copia de la página de filtros de la web dentro del bot**, para usarla cuando quieras:

* **Lunes**: mapeas una vez la página de reportes de Portal y pulsas **Guardar como Página**. En el menú aparece la
  sección **Páginas** con la tarjeta «Portal – Reportes».
* **Martes**: la abres y ves un formulario como el de la web:

  ```
  Portal – Reportes                         (opciones actualizadas el 27/10 08:00)
  Pestaña:            [ Corte ▾ ]
  Filtro por sistema: [ Portal ▾ ]
  Seleccione reporte: [ Detalles Ventas Mayorista ▾ ]   (las 12 opciones)
  Elegir corte:   [ La más reciente (hoy: 44 - 2026 …) ▾ ]  (los 156 cortes, del más reciente al más antiguo)
  Formato a exportar: [ Excel ▾ ]
              [ ⤓ Generar y descargar ]      [x] Sin abrir navegador (en segundo plano)
  ```

  Eliges y pulsas **Generar y descargar**: el bot, por detrás, abre Portal, inicia sesión (con tus Accesos), llega a la
  página, pone esos filtros, pulsa «Generar», espera y pulsa «Descargar». El archivo sale en **Archivos descargados** con
  **Abrir archivo** y **Abrir carpeta**.
* **Miércoles**: la misma tarjeta, otro reporte y **Elegir varias** en el corte (40, 41 y 42) → 3 archivos, uno por
  corte (con más de 10 ejecuciones pide confirmación; máximo 100). Sin volver a mapear ni grabar.
* **Jueves**: la vigilancia detecta el corte 45 y aparece en la lista como «★ 45 - 2026 … · nueva».

Cada web es su propia Página (Portal, Informes «Historial Bancario» con fechas y listas, la consulta del ERP…). Los
reportes grabados siguen funcionando igual.

### 18.2 Crear una Página

1. **Mapear página** → elige un reporte (para llegar a la página con la sesión iniciada) o escribe la dirección →
   **Abrir el navegador** → **Mapear toda la página** (o una parte).
2. Pulsa **▦ Guardar como Página…** y revisa:
   * **Cómo llegar a la página**: los pasos que se ejecutaron antes de mapear (abrir la dirección, «Iniciar sesión», los
     clics de los menús). Si navegaste a mano hasta otra dirección, se añade «Abrir» esa dirección (revísalo: el bot no
     puede saber qué clics hiciste a mano).
   * **Filtros**: marca cuáles traer y ponles nombre (se proponen con las reglas de la 3.1: nunca «Open»).
   * **Detectar dependencias**: el bot elige otra opción en cada lista y vuelve a leer las siguientes; así sabe que
     «Elegir corte» depende de «Seleccione reporte». Si no lo pulsas, lo va viendo al usar la Página.
   * **El resultado**: se adivina con los botones del mapa: «Generar»/«Ver Reporte»/«Consultar» y
     «Descargar»/«Exportar». Tipos: *el botón descarga el archivo*; *Generar y después «Descargar»* (Portal: se habilita al
     terminar); *Generar y un menú de exportar* (ERP: ratón sobre «Vista Exportar» + «Exportar»); *Ver Reporte abre el
     informe en otra pestaña* → guardarlo como **PDF, CSV o HTML** (Informes); o *los pasos del reporte* tal cual.
3. **Guardar como Página** → se abre su formulario.

**El «Reporte mapeado» de Portal**: al abrir el bot 3.2 por primera vez, el mapa guardado (mapa 1 del reporte 10) se
convierte solo en la Página **«Portal – Reportes»** (una vez; el reporte y el mapa no se tocan). La llegada son los pasos
del reporte antes del primer filtro; los valores por defecto, los que elegía el reporte; la acción, **Generar +
Descargar**; y usa el perfil del navegador del reporte (la sesión ya iniciada). Como aquel mapa se hizo con la 3.0, tres
listas se llamaban «Open»: salen como «Lista 2», «Lista 3» y «Corte (2)» con la marca **nombre provisional**. Pulsa
**↻ Actualizar opciones**: el bot lee en la web sus nombres de verdad («Filtro por sistema», «Seleccione reporte»,
«Elegir corte») y los pone solo; o renómbralos en **Configurar esta página**. Revisa también que el botón
«Descargar» de la acción coincida con el de la web (si no, cambia sus selectores ahí). La lista «Corte» de la barra de
arriba de Portal también se trae (con «la más reciente»), pero no va en el nombre del archivo.

### 18.3 Usar una Página

* **Opciones**: cada lista muestra **todas las opciones conocidas**; las de periodos (cortes, meses, fechas) de la más
  reciente a la más antigua, con **«La más reciente (hoy: …)»** primero; ★ marca la más reciente y **nueva** lo que llegó
  según la vigilancia. Debajo, cuántas hay y de cuándo son («actualizado el …», del mapa / de una ejecución / de la
  vigilancia / de «Actualizar opciones»). **Cada ejecución lee y guarda las listas por las que pasa.**
* **Listas que dependen de otras**: las opciones se guardan por combinación («Elegir corte» con «Mayorista» no es igual
  que con «Resumen de Ventas»). Si cambias el reporte y esa lista no se conoce, el bot **la trae solo** («⏳ trayendo
  opciones…»: ejecuta la Página por detrás hasta esa lista, sin generar nada) y la guarda.
* **↻ Actualizar opciones**: lo mismo con todas las listas (y corrige los nombres provisionales).
* **★ Guardar como favorito…**: guarda lo elegido, p. ej. «Mayorista + corte más reciente + Excel»; «la más reciente» se
  recalcula cada vez. Cada favorito tiene **▶ Ejecutar**, **Programar…** (tarea de Windows, tras mostrarte el comando) y
  **Borrar**. **Guardar como valores por defecto** cambia lo que sale al abrir la Página.
* **Nombre de los archivos**: por defecto `{pagina} - {variantes}` = el nombre de la Página y lo elegido de verdad en los
  filtros marcados «en el nombre del archivo» (y en los que elijas varias), p. ej. `Portal – Reportes - Portal - Detalles
  Ventas Mayorista - 44 - 2026 (09_10_2026 - 15_10_2026).xlsx`. En **Configurar esta página** puedes poner otra
  plantilla con `{Elegir corte}`, `{Seleccione reporte}`, `{hoy:%Y-%m-%d}`…
* **Vigilancia**: elige la lista a vigilar, con qué valores (los de un favorito) y cada cuánto; la regla de la 3.1 se
  mantiene (solo lo MÁS RECIENTE que lo conocido es nuevo). Con **Descargar automáticamente lo nuevo** descarga la
  novedad con ese favorito (una sola vez). Las novedades aparecen en la campana con **Descargar** y **Abrir la página**.
* **Configurar esta página**: nombres de los filtros, «en el nombre del archivo», de qué filtros dependen sus opciones,
  la acción (tipo y selectores de los botones), los pasos de llegada (editar, quitar, añadir) y **Eliminar la página**.
* El historial de cada ejecución va al **Historial** de siempre (con la marca «página»).

### 18.4 «Sin abrir navegador (en segundo plano)»

En cada Página hay un interruptor **Sin abrir navegador (en segundo plano)**, **encendido por defecto**: el bot hace
todo por detrás, sin ninguna ventana, y puedes seguir trabajando. *Por dentro sigue usando un navegador (Chrome o Edge)
invisible*: es lo mismo que el modo «oculto» de siempre. Si la página pide iniciar sesión o la contraseña falla, **la
pregunta sale en el bot** igual que antes. Apágalo para ver lo que hace («Ver mientras trabaja»). El mismo interruptor está
en **Reportes** (cambia el ajuste general «Ver mientras trabaja») y en **Usar filtros**. Las tareas programadas van
siempre sin navegador.

### 18.5 Línea de comandos

```
python bot.py --pagina "Portal – Reportes"                                   valores por defecto
python bot.py --pagina "Portal – Reportes" --favorito "Mayorista"              un favorito
python bot.py --pagina "Portal – Reportes" --favorito "Mayorista" --filtro "Elegir corte=43 - 2026 (02/10/2026 - 08/10/2026)"
python bot.py --pagina "Portal – Reportes" --filtro "Elegir corte=40 - 2026 (…)" --filtro "Elegir corte=41 - 2026 (…)"
python bot.py --pagina-id 1 --favorito "Mayorista" --sin-ventana --oculto      (lo que ejecutan las tareas programadas)
python bot.py --vigilar --pagina-id 1                                       revisa su filtro vigilado
```

`--filtro` acepta el nombre del filtro (como en el formulario), el texto de la opción o «más reciente», «primera»,
«última»; en casillas «sí»/«no». Código 0 = bien, 1 = alguna ejecución falló, 2 = no existe la página, el favorito o el
filtro. `--vigilar` sin `--id`/`--pagina` revisa también las Páginas vigiladas.

### 18.6 Pruebas

`tests/test_v32.py` (sin navegador: conversión de la forma real del mapa 1 + reporte 10 —copiada en solo lectura a
`tests/fijos/portal_mapa.json`, sin usuarios ni contraseñas—, una sola vez y sin tocar el reporte; flujo, nombres de
archivo, combinaciones, formulario, dependencias, favoritos, `--filtro`; conversión de la tabla `ejecuciones` antigua;
novedades de una Página; el interruptor llega al ejecutor como «oculto»; comando de la tarea de un favorito; «Abrir
archivo» solo dentro de las descargas) y `tests/test_integracion_v32.py` (navegador oculto: crear la Página desde un mapa
por la API con dependencias y acción adivinada en `portal.html?boton=1`, valores elegidos y su archivo, varias
ejecuciones, opciones traídas bajo pedido, favorito con la más reciente, `--pagina/--favorito/--filtro`, vigilancia que
marca «nueva» y descarga una vez, inicio de sesión preguntado sin abrir navegador, `informes.html` con fechas y el
informe en otra pestaña → CSV, `erp_consulta.html` con el menú «Vista Exportar» → «Exportar», y la interfaz).
`--smoke-web` abre también la lista de Páginas y el formulario de una.


## 19. Novedades de la 3.3 en detalle

### 19.1 Mapear otras webs (Informes, ERP…)

**Por qué solo funcionaba en Portal** (registros del 26/10: `_144413`, `_144622`, `_145449`, `_144943` terminaron sin
mapa y sin ningún aviso):

* **El ERP tiene la consulta dentro de un iframe** (`#tab0_Frame`): el mapeador solo miraba el documento principal, así
  que no veía ningún filtro. Además «Consultar» y «Vista Exportar» son opciones de un menú de DevExpress, no botones, y sus
  listas y fechas (DevExpress) salían como simples textos.
* **Un solo control raro estropeaba todo el mapa** (si al analizarlo la página daba un error, no salía nada).
* **Informes**: las etiquetas están en celdas de tabla (sin `<label>`), el desplegable del usuario de la barra se tomaba
  por una lista, el botón «Ver Reporte» de imagen no se reconocía y «Cuenta No.» (con lupa) no se distinguía.
* **Se mapeaba siempre la última pestaña abierta**, no la que estabas viendo.
* **Nada quedaba escrito**: un mapa vacío salía como una tabla vacía y un error como un aviso pasajero.

**Ahora:**

* Se mapean la página y **todos sus marcos**; los filtros de un marco llevan la marca «en un marco» y los pasos y las
  Páginas creados con ellos trabajan **dentro de ese marco**.
* Se mapea la pestaña que estás viendo; si hay varias, en **Pestaña** puedes elegir otra (↻ Pestañas la actualiza).
  Puedes iniciar sesión, navegar a mano (o abrir el reporte en otra pestaña) y después pulsar **Mapear**.
* Etiquetas: `<label>`, leyendas de DevExpress, la celda de al lado en una tabla, el texto de antes, `title`… y, si no hay
  nada, el nombre del campo hecho legible («txtFechaIni» → «Fecha Ini»). Ningún control se pierde por no tener etiqueta.
* Reconoce listas y fechas de **DevExpress**, fechas con **calendario** (bootstrap-datepicker), **campos con lupa**
  («Texto con búsqueda»: pulsa **Leer opciones de la búsqueda** para traer las filas de la ventanita; en la Página eliges
  una fila y el bot pulsa la lupa y la fila), botones de imagen, enlaces con aspecto de botón y menús de exportar.
* «Ver Reporte» se propone como «abre el informe en otra pestaña → guardarlo»; «Consultar» + «Vista Exportar» como el
  menú de exportar del ERP.
* Si no encuentra nada o algo falla, lo dice: «parece la página de inicio de sesión», «la página todavía se está
  cargando», «no hay ningún control…», «no se pudieron leer N marcos…», «N controles no se pudieron analizar…». Y guarda un
  **diagnóstico** en `registros/mapas/<fecha>_<sitio>/` (captura, pestañas y marcos, controles encontrados —nunca el
  valor de una contraseña— y errores; `LEEME.txt` lo resume). Cada sesión de mapeo queda en `registros/` como una
  ejecución.

### 19.2 Varias vigilancias

En **Vigilancia** cada reporte y cada Página muestra **todas sus vigilancias** (una tarjeta por vigilancia, con su
número), con **Revisar ahora**, **Cambiar…**, **Pausar/Activar**, **Programar en Windows…** y **Borrar**, y arriba
**↻ Revisar todas**. **＋ Añadir vigilancia** pide: la lista (o el paso), un nombre opcional, **con qué valores** en los
filtros de antes (un favorito y/o, en cada lista anterior, una opción: p. ej. «Seleccione reporte» = «Cartera
General»), si se descarga sola y cada cuánto. Ejemplo: «Elegir corte» con «Detalles Ventas Mayorista» y, aparte,
con «Cartera General»: cada una sabe qué cortes ha visto, avisa con su nombre («Llegó un corte nuevo en «Portal –
Reportes» (Cartera General): 45 - 2026 …») y descarga lo suyo una sola vez. La marca **nueva** del formulario de la
Página junta las de todas. Cambiar lo que vigila (la lista o los valores) hace que la próxima revisión vuelva a ser la
referencia.

La primera vez que abres el bot 3.3 la base de datos se convierte sola: **antes** se copia a `datos/bot.db.antes-v3.3`;
las vigilancias que tuvieras pasan a la tabla nueva con lo que ya habían visto, y las tablas antiguas se conservan
renombradas (`*_v32`). Lo que una vigilancia de la 3.2 había visto (aunque la quitaras) sirve de referencia a la primera
vigilancia nueva de esa misma lista.

Tareas de Windows: cada vigilancia tiene la suya (`python bot.py --vigilancia-id N --vigilar --oculto`); `--vigilar` sin
más revisa todas las activas.

### 19.3 Pruebas

`tests/test_v33.py` (sin navegador) y `tests/test_integracion_v33.py` (navegador oculto con las páginas de prueba
`informes2_inicio.html`/`informes2_historial.html`, `erp2_inicio.html`/`erp2_consulta.html`, `nueva_pestana.html`,
`sin_filtros.html`, `control_roto.html`, y dos vigilancias reales de `portal.html`). `--smoke-web` abre también la página
Vigilancia con varias vigilancias y la ventana «Añadir vigilancia».

## 20. Correcciones 3.3.1

Lo que se vio en los registros del 28/10 y qué cambió.

### 20.1 «El mapeo no hace nada»: tras iniciar sesión, Portal va a «Inicio»

Las Páginas «Portal – Reportes» y «Portal – Reportes (2)» (creadas mapeando toda la página) y el «Reporte mapeado» empiezan
abriendo `https://portal.ejemplo.com/portal/#/reportes/corte`. Sin sesión, Portal enseña el inicio de sesión; el bot entraba
bien («sesión iniciada»), pero **Portal lleva siempre a «Inicio»**, no a la página pedida, y el bot se quedaba 60 s
esperando la pestaña «Corte», que allí no existe.

Ahora, después de iniciar sesión (a mitad de un paso o con el paso «Iniciar sesión»), si la web llevó a otra página, el bot
**vuelve a abrir la dirección a la que iba** (la del último «Abrir la página», también la de la Página) y espera a que
cargue. En el registro: «tras iniciar sesión la web fue a «…/#/inicio»: se vuelve a «…/#/reportes/corte»». Se compara la
dirección sin la parte `?…` pero **con** la ruta tras `#`. No se vuelve si la dirección era la propia página de inicio de
sesión (`login`, `inicio-sesion`…, o la página donde estaba el formulario cuando al entrar la web pasa a otra página, como
`index.html` → `reportes.html`) ni a la raíz del sitio. Sirve para las Páginas que ya tienes y para las nuevas, y para los
reportes que empiezan en una dirección profunda. Además, un clic en una **pestaña que ya está elegida** («Corte») se da por
hecho al momento.

### 20.2 ERP: la Licencia vacía no es una contraseña rechazada

En el reporte «Erp» la página contestó «El campo LICENCIA esta vacio (es un dato obligatorio)» y el bot **marcó la
contraseña como rechazada** (no lo era) y la siguiente vez ni la envió. Ahora:

* El bot distingue lo que dice la página: un **dato obligatorio vacío** («vacío», «obligatorio», «requerido», «debe
  ingresar»…) **no** es una contraseña mala. Cierra la ventanita del mensaje («Aceptar»), busca qué campo nombra el mensaje
  («LICENCIA» → el campo «Licencia» / `txtLicencia`), lo rellena con tus **Accesos** y reintenta; si no lo sabe, te pide
  **solo ese dato** (y lo guarda en Accesos). Solo marca la contraseña como rechazada si la página dice que los datos son
  incorrectos («Usuario o contraseña incorrectos», «credenciales inválidas»…) o si, con todo relleno, sigue en el inicio de
  sesión sin decir nada.
* Si el paso «Iniciar sesión» del reporte no lleva un campo que Accesos sí conoce para ese sitio (p. ej. la Licencia), se
  rellena también. El mismo campo escrito de varias formas (`ctl00$formContent$txtLicencia`, `ctl00_formContent_txtLicencia_I`,
  el «clon» `…_I_CLND` de DevExpress, la contraseña guardada como `erp.ejemplo.com:ctl00$formContent$txtContrasenia`) se
  reconoce como uno solo.
* Al terminar de rellenar, si un dato se borró solo (la web terminaba de cargar), se vuelve a escribir.
* La ventana del bot nunca muestra dos cajas para el mismo campo, no deja enviar la contraseña vacía y, si mientras te
  pregunta **entras a mano** en el navegador, el bot lo nota y sigue (antes: «Faltan datos para iniciar sesión…:
  Contrasenia»). La contraseña que escribes se teclea en el campo de DevExpress (se pulsa el «clon» para que aparezca el
  campo real).
* Al marcar una contraseña como rechazada se guarda **lo que dijo la página** (nunca la contraseña). Si la marca se puso por
  un dato obligatorio vacío, se quita sola la próxima vez. En **Accesos** ves «La página dijo: «…»» y el botón **Quitar marca
  de rechazada** (por si sabes que la contraseña es buena). Al funcionar, la marca se quita como siempre.

### 20.3 Vigilancia: añadir una a cualquier reporte

La página Vigilancia solo enseñaba «POrtal» con «Sus listas están grabadas como clics… Abrir en el editor», sin forma de
añadir nada. Ahora:

* Arriba, **＋ Añadir vigilancia**: eliges cualquier reporte guardado o Página (con buscador) y después la lista. Si el
  reporte tiene sus listas grabadas como clics («abrir la lista» + «clic en la opción»), salen directamente («Lista donde se
  eligió «45 - 2026 (…)»»); al añadir la vigilancia el bot convierte esos clics en un paso «Elegir opción» (**antes guarda
  una copia** en «Versiones anteriores») con «la opción más reciente» si parece un corte o periodo, o la opción grabada (lo
  puedes cambiar en la ventana). Lo mismo con las listas sencillas («Seleccionar»). Si el reporte no tiene ninguna lista,
  la ventana lo explica y te lleva a «Mapear página».
* La página muestra todos los reportes y Páginas que tienen listas (convertidas o no), cada uno con su **＋ Añadir
  vigilancia**. Si al convertir cambian los números de los pasos, las vigilancias que ya tenía el reporte se renumeran solas.

### 20.4 Pruebas

`tests/test_integracion_v331.py` (navegador oculto): `portal_spa.html` (web de una sola página con rutas `#/…`: sin sesión
cualquier ruta enseña el inicio de sesión y al entrar va siempre a `#/inicio`) — un reporte que empieza en `#/reportes/corte`
(también con el paso «Iniciar sesión» y con la web que cambia la dirección a `#/inicio-sesion`) y una Página creada mapeando
toda la página se ejecutan hasta la descarga; `erp_login.html` (Licencia + Usuario + contraseña de DevExpress con clon, nombres
`ctl00$formContent$…`, ventanita «El campo LICENCIA esta vacio» y «Usuario o contraseña incorrectos») — Licencia desde
Accesos, pedir solo la Licencia sin marcar la contraseña, Licencia que la web no recibió, contraseña mala marcada con el
motivo y la respuesta de la ventana que rellena DevExpress, marca por dato obligatorio que se quita sola, entrar a mano
mientras se pregunta, «Quitar marca» por la API; Vigilancia: listado con todos los candidatos, añadir con listas grabadas como
clics (conversión, copia, renumeración y una revisión real que detecta y descarga el corte nuevo), con «Elegir opción», con
una lista sencilla y con una Página, y la página en el navegador (buscador, «sin listas», conversión) sin errores en la
consola.

No verificado contra las webs reales (no hay acceso desde aquí): que Portal vuelva bien a `#/reportes/corte` con su sesión
real, el texto exacto de los mensajes del ERP en otros casos y que su ventanita se cierre con «Aceptar» como en la página de
prueba.

## 21. Novedades de la 3.4: programación completa

Antes una vigilancia solo podía revisarse «cada N horas» o «cada día a una hora», y un reporte «cada día» o «algunos días a
una hora». Ahora todo lo que se programa (vigilancias, reportes y Páginas) usa el mismo editor **Cuándo**.

### 21.1 Cómo elegir días y horas

En **Cuándo** eliges primero el tipo:

* **Solo cuando pulse «Revisar ahora»** (o «Sin programar»): no se ejecuta solo.
* **Días y horas**: pulsa los días (L M X J V S D; atajos **Todos**, **Lunes a viernes**, **Fines de semana**) y pon una o
  varias horas (**＋ hora**). Ejemplo: de lunes a viernes a las 08:00 y a las 14:00.
* **Cada N horas en un horario**: los días, cada cuántas horas (o minutos, como mínimo 15) y **de** qué hora **a** qué
  hora. Ejemplo: de lunes a viernes cada 2 h de 08:00 a 18:00 (08, 10, 12, 14, 16 y 18). **Todo el día** = de 00:00 a 23:59.
* **Mensual**: **días del mes** (por ejemplo el 1 y el 15, o **Último día del mes**) o **el primer / segundo / tercer /
  cuarto / último** lunes, viernes… del mes. En **Meses** puedes dejar solo algunos.

¿Horas distintas según el día? Pulsa **＋ Añadir otro horario**: por ejemplo «Horario 1: lunes a jueves a las 08:00 y
14:00» y «Horario 2: viernes a las 10:00». Puedes mezclar tipos (lunes a viernes a las 09:00 y además los viernes cada 2 h).
Si quieres que empiece o termine un día concreto, abre **Fecha de inicio y de fin**.

Mientras eliges, debajo se ve **en palabras** lo que has puesto («Se ejecutará de lunes a viernes a las 09:00 y 15:00; los
viernes cada 2 h de 08:00 a 18:00») y **las 5 próximas veces** («hoy 15:00 · mañana 08:00 · …»). Si algo no vale (un día
sin marcar, «hasta» antes de «desde»…) lo dice en rojo. Las horas son las del reloj del ordenador.

### 21.2 Lo que hace que se ejecute solo: la tarea de Windows

**El horario por sí solo no hace nada.** Lo que ejecuta el bot sin que estés delante es una **tarea del Programador de
tareas de Windows** (carpeta `BotWeb`). Por eso:

* En **Vigilancia**, al guardar una vigilancia con horario, el bot te avisa si todavía no tiene tarea y te ofrece
  **Activar: crear la tarea en Windows**. Si cambias el horario de una vigilancia que ya tenía tarea, te ofrece
  **Actualizar la tarea en Windows**; si la pasas a «Solo cuando pulse Revisar ahora», te ofrece **Quitar la tarea**.
* Cada tarjeta de vigilancia dice si tiene tarea («✓ Tarea de Windows creada», con la próxima revisión) o, en amarillo,
  «Tiene horario, pero NO tiene tarea en Windows: no se revisará sola» con el botón para crearla.
* En **Programar…** de un reporte o de un favorito de una Página verás si ya tiene tarea, y podrás sustituirla o quitarla.
* Antes de crear nada el bot te enseña **qué se creará**: el nombre de la tarea, el horario en palabras, las próximas
  ejecuciones, cada disparador, el programa que ejecuta, el comando (`schtasks /Create /XML … /TN "BotWeb\…" /F`) y, si
  quieres, el XML. Solo se crea si pulsas **Crear la tarea**.
* Como antes, la tarea se ejecuta **oculta**, con **tu usuario** y **solo si tienes la sesión de Windows iniciada**
  (necesita tus contraseñas guardadas y el perfil del navegador). Novedades: también funciona con el portátil **con
  batería**, nunca se lanza dos veces a la vez y Windows la para si pasara de 12 horas.
* En **Inicio → Próximas tareas** salen las vigilancias con su próxima revisión (calculada por el bot) y, si no tienen
  tarea, la marca **sin tarea de Windows**; las tareas de reportes y Páginas llevan su horario en palabras.

### 21.3 Lo que ya tenías

* Las vigilancias de antes («cada 4 h», «cada día a las 08:00») se ven en el editor nuevo tal cual («todos los días cada
  4 h») y siguen funcionando; la base de datos gana la columna `vigilancias.programacion` sola al abrir el bot (no se
  borra nada) y la tabla `programaciones` (el último horario con el que se creó la tarea de un reporte o una Página).
* Las tareas creadas con versiones anteriores siguen funcionando: ejecutan el mismo comando (`--id N`, `--pagina-id N`,
  `--vigilancia-id N --vigilar`…), que no ha cambiado. Al volver a programar se sustituyen (mismo nombre).
* La ventana clásica (`--clasica`) sigue con su «Programar» de siempre (diaria / semanal / cada N horas).

### 21.4 Para los que programan

`webbot/horario.py` (sin playwright): la programación es un JSON
`{"reglas": [{"tipo": "semanal", "dias": ["lun",…], "horas": ["09:00",…]}, {"tipo": "intervalo", "dias": […], "cada_min":
120, "desde": "08:00", "hasta": "18:00"}, {"tipo": "mensual", "dias_mes": [1, 15, "ultimo"], "horas": […], "meses": [1…12]},
{"tipo": "mensual_semana", "semanas": [1, "ultima"], "dias": ["lun"], "horas": […], "meses": […]}], "inicio": "AAAA-MM-DD"|"",
"fin": "AAAA-MM-DD"|""}`; `normalizar`, `describir`, `proximas`, `vista`, `desde_antiguo`. `programador.construir_xml_tarea`
(un disparador por hora; «cada N horas» = un disparador con repetición) y `crear_con_xml` (UTF-16, archivo temporal).
API: `POST /api/horario`, `POST /api/vigilancias/<id>/programar` (sin `frecuencia` = con su programación; `confirmar`),
`POST /api/vigilancias/<id>/quitar_tarea`, `GET|POST /api/reportes/<id>/programar` (`programacion`), `POST
/api/reportes/<id>/quitar_tarea`, `POST /api/paginas/<id>/programar` (`programacion`, `consultar`, `quitar`). En la
interfaz, el componente es `editorCuando(prog, {textoNunca})` en `ui/app.js`.

Pruebas: `tests/test_v34.py` (modelo, textos, próximas ejecuciones con último día del mes, bisiestos y cambios de hora, XML
leído de nuevo con xml.etree y —en Windows— por el propio Programador de tareas sin registrar nada, conversión de la base
de datos de la 3.3 y la API con un schtasks falso: nunca se crea una tarea de verdad). `--smoke-web` abre también el
editor «Cuándo» de una vigilancia y la confirmación de «Programar…» de un reporte.

## 22. Correo (3.4)

La sección **Correo** (menú de la izquierda, ✉) hace con el correo lo que el bot ya hacía con las webs: **encuentra los
correos que te interesan y hace algo con cada uno**, sin que estés delante. Está basada en el programa de Outlook que ya
teníamos (el que descargaba el «RESUMEN DE VENTAS»), pero ahora sirve para **muchos** correos y **muchas** búsquedas.

### 22.1 Conectar la cuenta (la primera vez)

1. **Correo → ＋ Añadir cuenta**. Elige el tipo:
   * **Outlook / Microsoft 365 (en el navegador)**: el correo de la empresa (usuario@…). No hace falta poner nada más.
   * **Gmail (en el navegador)**.
   * **Otro buzón por IMAP**: servidor (p. ej. `imap.gmail.com`), usuario y contraseña. La contraseña se guarda en el
     Administrador de credenciales de Windows (nunca en un archivo).
2. Con Outlook o Gmail pulsa **Iniciar sesión en el correo**: se abre una ventana del navegador (Chrome o Edge) **solo
   para esta cuenta**. **Entras tú**, como siempre (contraseña y, si te lo pide, el código del móvil). El bot espera hasta
   10 minutos a que aparezca la bandeja de entrada, la detecta y cierra la ventana. **El bot nunca escribe tu contraseña de
   Microsoft ni de Google.**
3. A partir de ahí revisa el correo **sin abrir ninguna ventana** (con la sesión guardada en `perfiles/correo_<n>`).
   **Comprobar sesión** lo verifica sin abrir nada.

**Si la sesión caduca** (Microsoft o Google vuelven a pedir la contraseña), el bot **no se queda colgado ni falla en
silencio**: la cuenta sale como «sesión caducada», aparece el aviso **«La sesión del correo «…» caducó»** en la campana (y
en Windows) y la tarjeta de la búsqueda lo dice. Pulsa otra vez **Iniciar sesión en el correo** y listo.

**Gmail por IMAP**: Google no deja usar tu contraseña normal. Hace falta una **contraseña de aplicación**: Cuenta de
Google → Seguridad → Verificación en dos pasos (activada) → **Contraseñas de aplicaciones**; copia las 16 letras en
«Contraseña». En Gmail → Configuración → «Reenvío y correo POP/IMAP» tiene que estar **IMAP activado**. Con Outlook /
Microsoft 365 muchas empresas no permiten IMAP con contraseña: usa el tipo «Outlook (en el navegador)».

### 22.2 Crear una búsqueda

**＋ Nueva búsqueda** abre una ventana con cuatro partes:

* **Cuenta**: el nombre de la búsqueda («Ventas diarias») y con qué cuenta.
* **¿Qué correo?**: rellena **solo lo que sirva para reconocerlo**:
  * *El asunto contiene* (p. ej. `RESUMEN DE VENTAS MI EMPRESA`): no hace falta el asunto entero; lo que va detrás («AL 31 DE
    AGOSTO 2026») da igual.
  * *Remitente*: **contiene** (un trozo del nombre o de la dirección) o **es exactamente** (la dirección completa).
  * *Fecha*: cualquier fecha, de hoy, de ayer, **de los últimos N días** (lo normal: 7) o **entre dos fechas** (puedes
    escribir `01/10/2026` o plantillas como `{dias:-7}`, `{inicio_mes}`, `{hoy}`).
  * *El cuerpo dice*: uno o varios trozos de texto (uno por línea); tienen que estar todos.
  * *Adjuntos*: «tiene algún adjunto», un trozo del **nombre del adjunto** (`SUPERVISION VENTAS`) y/o la **extensión**
    (`xlsx`).
  * No importan las **mayúsculas, los acentos ni los signos**: «S.A.S.», «S. A. S.» y «SAS» valen igual.
  * En «Más opciones»: el texto que se escribe en el buscador de Outlook (por defecto, las primeras palabras del
    asunto), la carpeta (IMAP) y **cuántos correos como mucho** en cada revisión (10).
  * **🔎 Probar búsqueda** busca **ahora** y te enseña qué correos coinciden (asunto, remitente, fecha y adjuntos) y por
    qué no vale cada uno de los que no, **sin procesar ninguno**. También dice cuáles ya se procesaron.
* **¿Qué hago con él?**: una o varias acciones (＋ Añadir acción):
  * **Descargar los adjuntos**: todos o solo los que contienen un texto / tienen una extensión; en qué **carpeta** (vacío
    = la carpeta de descargas del bot; una carpeta suelta como `migracion` va dentro de ella; también
    `%USERPROFILE%\Downloads\migracion` o `Correo\{fecha_correo:%Y-%m}`) y con qué **nombre**. En el nombre puedes usar
    `{fecha_correo:%Y-%m-%d}` (la fecha del correo), `{asunto}`, `{remitente}`, `{adjunto}` (el nombre original sin la
    extensión), `{ext}`, `{n}` (1, 2, 3… dentro del correo) y las fechas de siempre (`{hoy:%Y-%m-%d}`…). Si no pones la
    extensión, se añade la del adjunto. Si el archivo ya existe, no se pisa: se guarda como «… (2)». Si el adjunto es un
    **.zip** puedes **descomprimirlo** (y quedarte solo con lo que coincide).
  * **Copiar un texto del cuerpo**: «lo que va **después de** `Total ventas:`» (hasta el final de la línea), «lo que va
    **entre** A y B» o una **expresión regular**. El valor sale en el aviso, en el historial y en la tarjeta
    («Total ventas: 1.234») y, si quieres, se **anota** en un `.csv`, un Excel `.xlsx` o un `.txt` (una fila por correo:
    Fecha, Asunto, Campo, Valor).
  * **Copiar una tabla del cuerpo** a Excel (`.xlsx`) o CSV: la tabla número N, **agregando** filas al final (sin repetir
    los títulos), **reemplazando** la hoja o en **una hoja por mes** («OCTUBRE 2026», solo Excel).
  * **Guardar el cuerpo** como página web (`.html`) o texto (`.txt`).
* **Cuándo**: el mismo editor que las vigilancias (§21). Al guardar con horario, el bot te ofrece **Activar: crear la
  tarea en Windows** (sin la tarea no se revisa solo).

**Ejemplo** (el correo de ventas):

```
Nombre:           Ventas diarias              Cuenta: Correo de la empresa (Outlook)
¿Qué correo?      El asunto contiene «RESUMEN DE VENTAS MI EMPRESA» · de los últimos 7 días
¿Qué hago?        1. Descargar los adjuntos que contienen «SUPERVISION VENTAS»
                     carpeta: %USERPROFILE%\Downloads\migracion     nombre: Ventas {fecha_correo:%Y-%m-%d}.xlsx
                  2. Copiar un texto: lo que va después de «Total ventas:»
Cuándo            De lunes a viernes a las 09:00 y 15:00
```

### 22.3 Cómo trabaja

* En cada revisión busca los correos que coinciden y procesa **todos los que todavía no se procesaron**, del más
  reciente al más antiguo (como mucho 10 por vez; los demás, en la siguiente). **Cada correo se procesa una sola vez**:
  el bot apunta cuáles ya hizo. Si llegan dos el mismo día, se procesan los dos.
* Primero mira la lista de resultados (asunto, remitente, fecha) y después **abre** cada correo para comprobar el cuerpo
  y los adjuntos; si al abrirlo no coincide, lo apunta como «no coincide» y no lo vuelve a abrir (salvo que cambies la
  búsqueda).
* Si una acción falla (p. ej. el Excel destino está abierto), las demás se hacen igual; en las siguientes revisiones se
  **reintenta solo lo que faltó** (hasta 3 veces), así «agregar filas» nunca duplica.
* Al procesar un correo verás un aviso en la campana: **«Llegó «RESUMEN DE VENTAS…»: 1 archivo guardado, Total ventas:
  1.234»** (con **Abrir archivo**), una notificación de Windows y la ejecución en el **Historial** (marca «correo», con su
  registro). En **Inicio → Próximas tareas** sale la próxima revisión de cada búsqueda.
* Cada tarjeta tiene **Revisar ahora**, **Editar**, **Programar…**, **Pausar** y **Borrar**, y abajo **Últimos correos
  procesados** con sus archivos (Abrir archivo / Abrir carpeta), los textos copiados y **Volver a procesar** (la próxima
  revisión lo vuelve a hacer).
* **Outlook y las conversaciones**: si Outlook agrupa los correos en conversaciones, en la lista solo se ve el último de
  cada una. Si los reportes llegan como respuestas del mismo hilo, en Outlook → Configuración → Correo → Diseño elige
  «Mostrar el correo como mensajes individuales».

### 22.4 Línea de comandos

```
python bot.py --correo-id 2                 revisa esa búsqueda (sin ventana) — es lo que ejecuta su tarea de Windows
python bot.py --correo-id 2 --visible       igual, viendo el navegador
python bot.py --correos                     todas las búsquedas activas
```

Código 0 = bien (aunque no hubiera correos nuevos), 1 = alguna revisión falló (o la sesión caducó: el aviso queda en el
bot), 2 = no existe la búsqueda / no hay ninguna activa.

### 22.5 Para los que programan

`webbot/correo.py` (sin playwright): criterios (`normalizar_criterios`, `coincide` en la lista y con el correo abierto,
`rango_fechas`, `leer_fecha` para Outlook/Gmail/IMAP), la clave de cada correo (`clave_mensaje`), extraer textos y
tablas (`extraer_despues/entre/regex`, `tablas_html`, `html_a_texto`), nombres (`renderizar`, `nombre_final`,
`resolver_carpeta`), .zip, CSV/Excel (`anotar_fila`, `pegar_tabla`, de Octopus), `aplicar_acciones` y la revisión
(`revisar_busqueda`, `revisar_varias`, `probar_busqueda`). Proveedores con la misma interfaz (`buscar`, `abrir`,
`descargar`): `correo_outlook.py` y `correo_gmail.py` (base común `correo_web.py`: perfil persistente, espera de la
bandeja, sesión caducada, descargas en el contexto y recuperación de la carpeta «Descargas») y `correo_imap.py`. Tablas
`cuentas_correo`, `busquedas_correo`, `correos_procesados` y `ejecuciones.correo_id`; API `/api/correo/…`; tareas
`Correo <nombre> #<n>` (`--correo-id N`), con la programación guardada en `programaciones` («correo:N»).

Pruebas: `tests/test_v34_correo.py` (sin navegador: lógica, almacén, un proveedor falso, IMAP simulado, API y línea de
comandos) y `tests/test_integracion_v34_correo.py` (navegador oculto con los buzones de prueba
`tests/sitio_prueba/correo_outlook.html` y `correo_gmail.html`, servidos por `tests/servidor_prueba.py`). `--smoke-web`
abre también la página Correo, su editor y la ventana de una cuenta IMAP.

**No verificado con el Outlook ni el Gmail de verdad** (no hay acceso desde aquí): los selectores salen del programa de
Outlook que ya funcionaba (Octopus) y de la estructura conocida de Gmail, y se han probado con páginas de prueba que los
imitan. Si Microsoft o Google cambian su página puede haber que ajustarlos; la cuenta IMAP es la opción más estable.

## 23. Novedades de la 3.5: tres arreglos

### 23.1 Los archivos se llaman como el reporte (nombre completo)

**Lo que pasaba**: al grabar un reporte, el bot apuntaba en el paso «Descargar» el nombre que le pone **la web** al
archivo (`report_xls` en el ERP, `DetallesVentasMayorista` en Portal). Como ese nombre es siempre el mismo, los archivos
salían como «report_xls (6).xlsx» y no se sabía de qué reporte eran.

**Ahora**: por defecto cada archivo se llama **como el reporte, con su nombre completo, y la fecha**:
«Ventas, Cobros y Comisiones S.A.S. 2026-10-29.xlsx» (se respetan los espacios, las comas, los acentos y los puntos).

* En el nombre del archivo puedes usar:
  * `{reporte}` = el nombre completo del reporte (en una Página, el de la Página; en Correo, el de la búsqueda).
  * `{nombre}` = el nombre que le da la web al archivo («report_xls»).
  * `{ext}` = su extensión (.xlsx, .csv…) y las fechas de siempre (`{hoy:%Y-%m-%d}`, `{ayer}`…).
* Al editar un paso «Descargar» hay dos botones: **Nombre del reporte + fecha** (`{reporte} {hoy:%Y-%m-%d}{ext}`) y
  **Nombre que da la web** (`{nombre}{ext}`, como antes). Debajo se ve cómo quedará.
* Si un reporte descarga **varios archivos**, cada uno lleva también el nombre de la web para que no se pisen:
  «Ventas - clientes 2026-10-29.csv»… (`{reporte} - {nombre} {hoy:%Y-%m-%d}{ext}`).
* **Tus reportes ya guardados**: la primera vez que abras el bot 3.5, los pasos «Descargar» que tenían el nombre fijo de
  la web pasan solos a «nombre del reporte + fecha». Antes se guarda una **copia de cada reporte** (Más ▾ → Versiones
  anteriores del reporte → Restaurar, si prefieres el de antes) y verás un aviso en la campana. Se hace **una sola vez**;
  los nombres que tú habías cambiado (con fechas, `{opcion}`…) no se tocan.
* En el editor, si algún paso todavía guarda con el nombre de la web, sale un aviso con el botón **Usar el nombre del
  reporte**.
* Las listas ya no cortan los nombres largos con «…»: se ven enteros (en varias líneas si hace falta).

### 23.2 Elegir la carpeta con el explorador de Windows

Junto a cada carpeta o archivo hay un botón **📁 Elegir…**: abre el explorador de Windows (el de siempre) para que
elijas la carpeta o el archivo, y pone la dirección completa en el campo. El campo se puede seguir escribiendo a mano
(por ejemplo con plantillas como `Correo\{fecha_correo:%Y-%m}`).

Está en: la carpeta de descargas del reporte (Opciones del reporte), la carpeta de los pasos «Descargar» y «Guardar
página», la carpeta de los archivos de una **Página** (en «Configurar esta página»), las carpetas y archivos de las
acciones de **Correo** (adjuntos, el Excel/CSV donde se copia una tabla, el archivo donde se anota un texto, el cuerpo) y
**Ajustes**. Para los Excel puedes elegir uno que ya existe (el bot le añade filas; no pregunta «¿reemplazar?»).

La ventana se abre en **este PC** (el bot y la interfaz están en el mismo equipo). Si no aparece, mira si quedó detrás de
otra ventana. Cancelar no cambia nada.

### 23.3 Correo: «Correos relacionados» y procesar cualquiera

En cada búsqueda de Correo hay un botón **✉ Correos relacionados**: como la lista de cortes de una Página, enseña
**todos** los correos que cumplen la búsqueda, del más reciente al más antiguo, con su fecha, quién lo envía, el asunto,
los adjuntos y su estado:

* **nuevo** (todavía no se ha procesado), **ya procesado el …**, **procesado con error el …** o **descartado** (al
  abrirlo no coincidía). El más reciente lleva la marca **el más reciente**.
* **Fechas**: «las de la búsqueda», «últimos 30 días» (por defecto), «90 días», «último año» o «todas las fechas»; esto
  solo cambia la lista, **no** la búsqueda. **Cargar más** trae los 10 siguientes. Si desmarcas «Abrir cada correo» va
  más rápido, pero no se ven los adjuntos.
* **Procesar este** (o **Procesar otra vez**) hace ahora las acciones de la búsqueda con ese correo, **aunque ya se
  hubiera procesado**. Marca varios y pulsa **Procesar seleccionados** para hacerlo con todos.
* Si la búsqueda **agrega filas a un Excel o CSV** (copiar una tabla «agregando», o anotar un texto en un archivo) y el
  correo ya se procesó, el bot te avisa de que **pueden quedar filas repetidas** y te pregunta antes.
* El resultado sale como siempre: aviso en la campana («Procesado otra vez «…»: 1 archivo guardado…»), notificación e
  **Historial**. El correo no se apunta dos veces: se actualiza su registro.

### 23.4 Para los que programan

* Nombres: `plantillas.renderizar(reporte=…)` y `RESERVADAS` con «reporte»; `Ejecutor._r` pasa `flujo.nombre`;
  `flujo.NOMBRE_DESCARGA_DEFECTO`, `NOMBRE_DESCARGA_VARIAS`, `es_nombre_de_la_web`, `usar_nombre_del_reporte`,
  `pasos_con_nombre_de_la_web`; `ejecutor.separar_extension` y `ruta_libre(ruta, ext)`; `Almacen.migrar_nombres_descarga`
  (marca `meta.nombres_descarga_v35`) desde `bot.migrar_reportes`; API `flujo/usar_nombre_reporte`, `flujo/describir`
  → `nombres_web`, `plantilla {reporte}`; correo: `{reporte}` en `correo.renderizar`.
* Elegir: `webbot/dialogos.py` (`elegir`, Tk en un hilo propio, un diálogo a la vez) y `POST /api/elegir {tipo, inicial,
  filtros, titulo}` → `{ruta}`; `Aplicacion(abrir_dialogo=…)`; en la interfaz `campoRuta(inp, opc)`.
* Correo: `correo.correos_relacionados`, `criterios_con_rango`, `acciones_que_agregan`, `estado_de`,
  `revisar_busqueda(solo=, rango=, buscar_hasta=)`; API `correo/busquedas/<id>/relacionados` (evento
  `correo_relacionados`) y `correo/busquedas/<id>/procesar` (`confirmar` si puede duplicar filas).

Pruebas: `tests/test_v35.py` — `{reporte}` y nombres con comas, acentos y puntos (también «(2)» sin extensión), la
grabación con una y dos descargas, la conversión de reportes (una vez, con copia y aviso), la API del editor, el
elegidor de carpetas con uno FALSO (en su propio hilo, uno a la vez, cancelar, sin escritorio, por HTTP con token y
Origin), la lista de correos relacionados (estados, rangos, «Cargar más», sin procesar nada), procesar a mano (rehace las
acciones, actualiza sin duplicar, avisos e historial, correos que ya no están), la API con confirmación, y con navegador
oculto una descarga real con el nombre completo y el buzón de prueba tipo Outlook. Ninguna prueba abre un diálogo de
Windows de verdad.

### 23.5 El nuevo aspecto: «Centro de control» (3.5, parte 2)

La interfaz tiene un diseño nuevo, oscuro y más compacto, pensado para tenerla abierta todo el día:

* **Barra de iconos** a la izquierda (al pasar el ratón sale el nombre de cada sección; un punto rojo en Vigilancia
  cuando hay cortes nuevos). En pantallas estrechas pasa a ser una barra abajo, con «Más» para Grabar, Mapear, Accesos y
  Ajustes.
* **Inicio = Centro de control**: arriba cuatro cifras (descargas de hoy, en curso, con error, novedades) con la línea
  de los últimos 7 días; debajo los reportes como filas (punto de estado, archivo y duración, cuándo fue y cuándo toca,
  «Ejecutar» y, si la web pidió un dato, «Completar Licencia» → Accesos), con filtros «Todos / Con error / Programados»;
  a la derecha **En vivo**: lo que va haciendo el bot, al momento; y abajo la novedad de Vigilancia («Descargar este
  corte»), lo último del correo y las próximas ejecuciones.
* **Buscar o ejecutar (Ctrl K)**: escribe parte de un nombre (sin preocuparte de acentos ni mayúsculas: «charg»,
  «pagina», «sas ventas») y pulsa Enter: ejecutar un reporte, abrir una Página, revisar una vigilancia o una búsqueda de
  correo, grabar, mapear o ir a cualquier sección. ↑ ↓ para moverte, Esc para cerrar.
* **Sin recargas**: la página ya no se vuelve a cargar entera cada vez que termina algo o pulsas un botón. Solo cambia
  la fila, la cifra o la línea afectada (al pulsar «Ejecutar» la fila pasa a «en curso» al instante, con su barrita de
  progreso). Al cambiar de sección y volver, todo sigue como lo dejaste (dónde estabas, lo que tenías abierto), y se
  pone al día por detrás.
* **Más rápido**: la lista de tareas de Windows (que tardaba ~1 s en cada carga del Inicio, de Vigilancia y de Correo)
  se guarda un minuto (ahora esas páginas responden en unos milisegundos).

Para los que programan: `ui/app.js` — `claveLista(cont, items, clave, pintar, {firma, vacio, destello})` (lista por clave:
solo se repinta lo que cambió, conservando foco y `<details>` abiertos), `actualizador` (peticiones de una en una, sin
pintar datos viejos), vistas vivas (`VIVAS`: cada ruta devuelve `{actualizar, evento}`; reciben los eventos aunque no
se vean), `E.curso` (reportes en curso por los eventos «trabajo» / «lote» / «progreso», que ahora llevan `reporte_id`) y
la paleta (`opcionesPaleta`, `buscarEnPaleta`). Servidor: `Aplicacion._tareas` con caché (`TTL_TAREAS`, se vacía al
crear/borrar con `_ejecutor_tareas`; con la interfaz abierta se relee en segundo plano), `GET /api/inicio` con `serie`
(`Almacen.serie_dias`), `reportes` (`ultimas_por_reporte`), `vigilancia_novedad`, `correo_ultimo`, `tareas_activas`;
`GET /api/buscador`; cada petición cierra su conexión de SQLite (antes quedaba una abierta por petición).
Pruebas: `tests/test_v35_diseno.py` (series de 7 días, filas, buscador, caché de tareas, `reporte_id` en los eventos,
conexiones, fuentes sin CDN y, con navegador oculto, que al terminar un trabajo NO se reconstruye la página —un elemento
marcado, la misma fila y el desplazamiento siguen— y la paleta Ctrl K).

## 24. Novedades de la 3.6: pegar en Outlook y calendario de fechas

### 24.1 Outlook: el bot pega el asunto entero

**Lo que pasaba**: para buscar el correo, el bot escribía en el buscador de Outlook **solo las 4 primeras palabras** del
asunto, y las **tecleaba letra a letra**. El buscador de Outlook va abriendo sugerencias mientras escribes y a veces **se
come o se queda letras**: el bot acababa buscando un texto distinto y no encontraba el correo.

**Ahora**:

* Busca con el **asunto completo** (o con lo que pongas en «Más opciones → Texto del buscador (Outlook)»).
* Lo **pega** de una vez, como harías tú con Ctrl+V, en lugar de teclearlo. Antes de pulsar Enter **comprueba** que el
  buscador tiene el texto entero (en el registro verás «buscador: «…» (pegado y comprobado)»).
* Si el buscador no acepta el texto pegado, lo pega con el **portapapeles y Ctrl+V** (y deja el portapapeles como
  estaba); solo si nada de eso funciona lo teclea como antes.
* Si con el texto completo **no sale ningún correo que cumpla la búsqueda**, prueba **una vez** con una parte: hasta la
  primera coma (o las 4 primeras palabras). En el registro: «Buscando en Outlook: «…» (completo)» y, si hace falta, «sin
  resultados que cumplan la búsqueda con «…»; se prueba con «…» (más corto)».
* Gmail no cambia (busca con la dirección de la página, no escribe nada) y los pasos «Escribir» de los reportes ya ponían
  el texto de una vez.

### 24.2 Fechas: calendario o «cambia sola»

Donde antes había que escribir una fecha (o una plantilla como `{ayer:%d/%m/%Y}`), ahora hay un **botón con la fecha en
palabras**, por ejemplo **«Ayer · 28/10/2026»** o **«Fecha fija · 15/10/2026»**. Al pulsarlo se abre un calendario con dos
modos:

* **Fecha fija**: eliges un día en el calendario (‹ › para cambiar de mes, «Ir a hoy»). Siempre se escribe ese día.
* **Cambia sola**: la fecha se **calcula cada vez** que se ejecuta: **Hoy**, **Ayer**, **Hace N días** (pones el número),
  **Lunes de esta semana**, **Lunes / Domingo de la semana pasada**, **Inicio / Fin de este mes**, **Inicio / Fin del mes
  anterior**, **1 de enero** y, en los reportes, **El día que se descarga** («Repetir por días»).
* **Formato**: eliges cómo lo escribe la web **viendo un ejemplo** («28/10/2026», «2026-10-28», «28-10-2026»,
  «10/28/2026»…, u «Otro…» si es raro). El bot propone el que tenía la fecha grabada.
* Debajo ves **«Se escribirá: 28/10/2026»**.
* **Escribir a mano** enseña el texto de siempre, para plantillas avanzadas. Lo que no entiende el calendario se queda
  tal cual (escrito a mano).
* Con el teclado: flechas para moverte por los días, Re Pág / Av Pág para cambiar de mes, Enter para elegir y Esc para
  cerrar. Funciona también en pantallas estrechas (móvil).

Está en: **Usar filtros** de un reporte (las fechas), el **formulario de una Página** (sus fechas), el **editor de pasos**
(un paso «Escribir» que escribe una fecha —también las que detectó la grabación desde un calendario—; en los demás, el
botón «Es una fecha: elegirla en el calendario»), **Mapear página** (las fechas que se traen), **Repetir por días**
(desde / hasta), las **fechas de inicio y fin** del editor «Cuándo» (programar reportes, Páginas, vigilancias y correo) y
el **Correo** («entre dos fechas»: desde / hasta).

**Tus reportes no cambian**: lo que se guarda es el mismo texto de antes (`15/10/2026`, `{ayer:%d/%m/%Y}`, `{dias:-7}`…),
así que todo sigue funcionando igual; el calendario solo es otra forma de elegirlo.

### 24.3 Para los que programan

* Outlook (`webbot/correo_outlook.py`): `_escribir_busqueda` (insert_text → portapapeles + Ctrl+V con
  `grant_permissions(["clipboard-read", "clipboard-write"])`, guardando y devolviendo el texto anterior → `type`, y
  comprobación con `input_value`), `_lanzar_busqueda(texto, que)` (si con el texto pegado no se lanza la búsqueda, otra
  vez con Ctrl+V) y `buscar` (intentos de `correo.textos_a_buscar`: el completo y `texto_corto`; el segundo solo si
  ninguna fila cumple `coincide(fase="resumen")`). `correo.texto_a_teclear` devuelve ya el texto completo.
* Fechas (`webbot/plantillas.py`): `lunes_semana`, `lunes_semana_anterior`, `domingo_semana_anterior`, `inicio_anio`;
  `analizar_fecha` (vacía / fija / relativa / a mano), `plantilla_fecha` (lo contrario), `formato_de_fecha`,
  `describir_fecha`, `FORMATOS_FECHA`, `RELATIVAS`. `filtros.datos_panel` y `paginas.formulario` devuelven `formato`;
  `mapeador` acepta `{fecha: "plantilla", valor}`. En la interfaz: `campoFecha(inp, {iso, sinFormato, formato, conFecha,
  vacio, prefijo, titulo})` (`ui/app.js`, como `campoRuta`: el campo sigue siendo el que se guarda y se lanzan «input» y
  «change»), con `analizarFecha` / `componerFecha` iguales a los de Python (`window.__botFechas` para las pruebas).

Pruebas: `tests/test_v36.py` — plantillas nuevas, `analizar_fecha` ↔ `plantilla_fecha` (ida y vuelta) y que la interfaz
entiende lo mismo que Python, mapear con el calendario, el texto de búsqueda completo y el corto; con navegador oculto,
la página de prueba tipo Outlook con un buscador que **pierde letras tecleadas** (se ve el fallo de antes), el asunto
pegado entero, Ctrl+V cuando no acepta el texto insertado (sin tocar el portapapeles de Windows: se comprueba), el
segundo intento más corto; y el calendario en una Página (día, teclado, Esc, «Ayer» + formato, «Hace N días», guardar),
en el editor de pasos y en «Programar…». `--smoke-web` abre además el calendario de la Página de prueba.

## 25. Novedades de la 3.7: avisos y vista de lo programado

Para todo lo que se ejecuta solo (reportes y Páginas programados, vigilancias y búsquedas de correo), el editor **Cuándo**
tiene un bloque nuevo, **Avisos y vista**:

* **Avisarme antes**: No / 1 / 5 / 10 / 15 / 30 minutos (en una programación nueva, 5). Te llega un aviso de Windows
  («"PORTAL" se ejecutará en 5 min, a las 12:50») y el bot espera hasta la hora de verdad.
* **Avisar cuando empieza** y **Avisar cuando termina (con el resultado)**: «terminó bien: 1 archivo», «falló en el
  paso 5: …», «nada nuevo», «novedad: «45 - 2026»»…
* **En segundo plano (oculto)** o **Ver la ejecución en vivo (navegador visible)**.
* **Mostrar una ventanita con la barra de progreso**: una ventana pequeña, siempre encima, abajo a la derecha, con el
  nombre, «Paso 3 de 8: Clic en …», la barra, el tiempo que lleva y **Detener**. Mientras espera para empezar tiene
  **Ver en vivo**, **Empezar ya** y **Cancelar esta ejecución**. Al terminar enseña el resultado y se cierra sola. (Una
  vez abierto el navegador oculto ya no se puede pasar a verlo: por eso «Ver en vivo» solo está antes de empezar.)

En **Inicio (Centro de control)**:

* **En curso**: lo que está haciendo el bot ahora, lo hayas lanzado tú o una tarea de Windows, con su barra de
  progreso, el paso, el tiempo y **Detener** (o, si está esperando para empezar, Ver en vivo / Empezar ya / Cancelar).
* **Lo programado**: cada cosa con horario, sus avisos y un interruptor **En vivo / En segundo plano**. Al cambiarlo se
  guarda y, si tiene tarea de Windows, la tarea se actualiza al momento.

**Lo que ya tenías sigue igual**: las tareas creadas antes no llevan estas opciones y funcionan como siempre (ocultas,
sin avisos). Toman las nuevas cuando vuelves a guardar su horario (o cuando usas el interruptor, que solo cambia «en
vivo / en segundo plano»). No hace falta ninguna conversión: la base de datos gana sola la tabla `en_curso`.

### 25.1 Cómo se avisa «antes» (y sus límites)

Windows no le dice al bot qué hora de la tarea lo lanzó. Por eso, con «Avisarme antes» de N minutos, **la tarea se
crea con todas sus horas N minutos antes** y ejecuta el bot con `--aviso-antes N`: el bot avisa, busca en el horario la
ejecución que toca en los próximos N minutos y espera hasta esa hora. Al confirmar la tarea verás cada disparador así:
«de lunes a viernes a las 09:00 (empieza a las 08:55 para avisarte 5 min antes)».

* Si la hora es justo después de medianoche (p. ej. 00:03), en «Días y horas» y «Cada N horas» la tarea empieza **el
  día anterior** a las 23:58 (los días se mueven uno atrás).
* En los horarios **mensuales** eso no siempre se puede decir («el último día − 1», «el primer lunes − 1»…), así que
  empieza a las **00:00 del mismo día**: el aviso llega algo más tarde (p. ej. 2 min antes en vez de 5).
* «Avisarme antes» tiene que ser **menos** que «cada N minutos/horas» (si no, el aviso de la siguiente se cruzaría con
  la anterior), y si dos horas están más juntas que el aviso el editor lo advierte: Windows no lanza la tarea dos veces
  a la vez.

### 25.2 Para los que programan

* `webbot/horario.py`: la programación puede llevar `"ejecucion": {"avisar_antes", "avisar_inicio", "avisar_fin",
  "en_vivo", "ventanita"}` (`EJECUCION_DEFECTO`; sin ella = como antes, `ejecucion(prog)` → None); `con_en_vivo`,
  `describir_ejecucion`, `siguiente_en`; `vista` devuelve `ejecucion` y `ejecucion_texto`.
* `webbot/programador.py`: `comando_bot(…, aviso_antes, avisar_inicio, avisar_fin, ventanita)`, `opciones_comando(prog)`,
  `disparadores(prog, ahora, adelanto)` / `construir_xml_tarea(…, adelanto=None)` (por defecto el «Avisarme antes» de
  la programación; `_adelantar` mueve hora, días, StartBoundary y EndBoundary).
* `webbot/seguimiento.py` (sin playwright ni tkinter): `Seguimiento` (espera previa, avisos, progreso en `en_curso`,
  «Detener» por `en_curso.pedido`), `resumen_corto`, `describir_objetivo`. En `bot.py`, `_con_seguimiento` envuelve las
  ejecuciones sin ventana de lo guardado (`--id`, `--pagina-id`, `--vigilancia-id`, `--correo-id`…); el progreso sale
  del `progreso(indice, estado, texto)` del ejecutor (el mismo que usa la interfaz), no del registro.
* `webbot/ventanita.py`: la ventanita (tkinter) en su propio proceso (`bot.py --db … --ventanita-de N`); `vista(fila)`
  decide qué se enseña. Si tkinter falla o no hay escritorio, la ejecución sigue.
* `webbot/almacen.py`: tabla `en_curso` (`crear_en_curso`, `actualizar_en_curso`, `en_curso_id`, `pedir_en_curso`,
  `lista_en_curso`, que borra las filas de procesos muertos con `pid_vivo`).
* `webbot/servidor_ui.py`: `/api/eventos` mira la tabla cada segundo mientras espera y emite «externo»; `GET /api/en_curso`,
  `POST /api/en_curso/<id>/<detener|cancelar|ya|en_vivo>`, `POST /api/en_vivo {clave, en_vivo}`; `/api/inicio` trae
  `externos` y `programados`. En `ui/app.js`: el bloque en `editorCuando`, `pintarEnCurso`, `filaProgramado`.

Pruebas: `tests/test_v37_avisos.py` (bloque guardado y comprobado, XML adelantado —también cruzando la medianoche y el
mensual a las 00:00— y leído por el Programador de Windows sin registrar nada, la tabla `en_curso`, la espera previa con
un reloj falso, cancelar / empezar ya / ver en vivo, los avisos con el notificador falso, Detener desde la ventanita, la
línea de comandos con un ejecutor falso, la API, la ventanita y, con navegador oculto, «Programar…», «En curso» y el
interruptor de «Lo programado»).
