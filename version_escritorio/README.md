# Bot Copión — grabador y reproductor de acciones

Aplicación de escritorio para Windows que **graba** lo que haces con el ratón y el
teclado, te muestra cada acción como una **lista de pasos legibles** (a los que
puedes añadir tus propias notas) y la **reproduce al pie de la letra**, con los
mismos tiempos, cuando pulsas **Ejecutar**.

## Instalación y arranque

Requisitos: Windows 10/11 y Python 3.10 o superior (probado con 3.13).

- **Forma fácil:** doble clic en `iniciar.bat`. Instala las dependencias
  (`pynput`) la primera vez y abre el bot.
- **A mano:**
  ```
  python -m pip install -r requirements.txt
  python bot.py
  ```

### Recibir una URL desde la línea de comandos
```
python bot.py --url https://example.com
python bot.py --url example.com --ejecutar
```
- `--url`: rellena el campo **URL** de la ventana (si no lleva `http://` o `https://`,
  se antepone `https://`).
- `--ejecutar` (opcional): al abrir, ejecuta automáticamente la grabación cargada
  (`grabaciones/ultima.json`), con la cuenta regresiva normal. Si no hay ninguna
  grabación, solo avisa en la barra de estado.

## Cómo se usa

### 1. Grabar
1. *(Opcional)* Escribe una dirección en el campo **URL**.
2. Pulsa **⏺ Grabar** (o la tecla **F9**). La ventana del bot se **minimiza** sola
   y empieza la grabación (verás que tarda una fracción de segundo; el clic sobre
   el botón no se graba). Si hay una URL, el bot la **abre en tu navegador
   predeterminado**, la anota como primer paso (**Abrir URL …**) y empieza a grabar
   solo tras la **Espera de carga** (5 s por defecto). Pulsando F9 durante esa
   espera se cancela.
3. Haz lo que quieras automatizar: clics, arrastres, rueda del ratón, escribir,
   atajos como Ctrl+C...
4. Pulsa **F9** otra vez para terminar. La ventana vuelve a aparecer con la lista
   de pasos.

> Mientras grabas, la ventana está minimizada, así que se detiene con **F9**.
> Las teclas **F9**, **F10** y **Esc** están reservadas para el bot y **no se graban**.

### 2. Revisar y anotar los pasos
La tabla muestra: **Nº · Acción · Tiempo · Nota**. Ejemplos de lo que verás:

| Paso | Qué significa |
|------|---------------|
| `Clic izquierdo en (540, 320)` | Pulsar y soltar en el mismo sitio |
| `Doble clic izquierdo en (540, 320)` | Dos clics rápidos en el mismo sitio |
| `Arrastrar de (10, 10) a (200, 120)` | Pulsar, mover y soltar en otro punto |
| `Escribir 'hola'` | Teclas de caracteres seguidas |
| `Tecla Enter`, `Tecla Retroceso ×3` | Teclas especiales (las repetidas se fusionan) |
| `Atajo Ctrl+C` | Combinaciones con Ctrl, Alt, Mayús o Win |
| `Mover ratón de (…) a (…) (n movimientos)` | Movimientos sueltos, resumidos |
| `Rueda del ratón: abajo 3 en (…)` | Desplazamiento con la rueda |
| `Esperar 2.4 s` | Pausa de más de 1 segundo entre acciones |
| `Abrir URL https://example.com` | Abre la página en el navegador predeterminado |

- **Doble clic sobre un paso** (o **Editar nota**, o Intro) para escribir una
  **nota** o indicación personal. Las notas se guardan con la grabación.
- **Eliminar paso(s)** (o tecla Supr): borra los pasos seleccionados **y los
  eventos que hay detrás**, así que ya no se reproducen. El tiempo que ocupaban
  se descuenta para no dejar huecos.
- **Insertar Abrir URL…**: añade a mano un paso «Abrir URL» tras el paso
  seleccionado (o al final), junto con la *Espera de carga* configurada. Funciona
  como cualquier otro paso: admite notas y se puede eliminar.
- **Insertar espera…**: añade una pausa de *N* segundos justo después del paso
  seleccionado (o al final si no hay selección).

La lista es solo una *vista*: la grabación conserva todos los eventos originales
(cada movimiento, cada pulsación) para que la reproducción sea exacta.

### 3. Ejecutar
Pulsa **▶ Ejecutar** (o **F10**). El paso **Abrir URL** vuelve a abrir la página
y la grabación espera lo mismo que esperó al grabar antes de seguir.

- Si el campo **URL** contiene **otra dirección distinta** de la grabada, se usa esa
  en lugar de la grabada (solo en el primer paso «Abrir URL»): así los mismos pasos
  se pueden repetir sobre URLs distintas.
- Si la grabación **no tiene** ningún paso «Abrir URL» pero el campo URL está
  relleno, el bot abre esa URL al principio y espera la **Espera de carga** antes
  de empezar con lo grabado (en cada repetición).

Tras la **cuenta regresiva** (aparece un
cartel arriba de la pantalla) el bot repite todo exactamente como lo grabaste.
Si la opción *Minimizar esta ventana al ejecutar* está activa, la ventana se
esconde y reaparece al terminar; si la desactivas, verás **resaltado en amarillo**
el paso que se está ejecutando.

Para **abortar** en cualquier momento:
- pulsa **Esc**, o
- pulsa **⏹ Detener** (si la ventana está visible), o
- lleva el ratón a la **esquina superior izquierda** de la pantalla (parada de seguridad).

Al terminar o abortar, el bot **suelta todas las teclas y botones** que
hubieran quedado pulsados.

### Opciones
| Opción | Qué hace |
|--------|----------|
| **Velocidad** | Multiplicador de tiempo: 0.25× (muy lento) a 4× (rápido). Puedes escribir otro valor, p. ej. `1.25`. |
| **Repeticiones** | Cuántas veces se repite la grabación seguida (pausa de 0.5 s entre repeticiones). |
| **Cuenta regresiva** | Segundos de espera antes de empezar a ejecutar (0 = inmediato). |
| **Espera de carga** | Segundos que se esperan tras abrir una URL (al grabar, al insertar un paso o al ejecutar sin paso grabado). 5 por defecto. Dentro de una grabación esa espera forma parte de la línea de tiempo, así que también la afecta el multiplicador de **Velocidad**. |
| **Grabar movimientos del ratón** | Si lo desmarcas, solo se graban clics, rueda y teclado (el ratón "salta" de clic en clic). Debe estar marcado para arrastres fieles. |
| **Minimizar esta ventana al ejecutar** | Evita que el bot tape lo que vas a automatizar. |

### Archivos
- **💾 Guardar**: guarda la grabación en un `.json` (carpeta `grabaciones/` por defecto).
- **📂 Cargar**: abre una grabación guardada.
- **🗑 Limpiar**: vacía la lista.
- **Autoguardado:** después de cada cambio se guarda `grabaciones/ultima.json`, y
  se **carga automáticamente al abrir el bot**. Al grabar de nuevo, cargar otro
  archivo o limpiar, la anterior se conserva en `grabaciones/anterior.json`.

## Atajos globales
| Tecla | Acción |
|-------|--------|
| **F9** | Empezar / detener la grabación |
| **F10** | Ejecutar la grabación |
| **Esc** | Abortar la ejecución (o cancelar la cuenta regresiva) |

Funcionan aunque otra ventana tenga el foco.

## Limitaciones conocidas
- **Reproduce por coordenadas de pantalla.** Si las ventanas cambian de sitio o
  de tamaño, los clics caerán en otro lugar. Empieza siempre desde el mismo estado
  de pantalla que cuando grabaste (mismas ventanas abiertas y en la misma posición).
- **Programas como Administrador:** una aplicación ejecutada como Administrador
  solo acepta las acciones del bot si el bot también se ejecuta como Administrador
  (clic derecho sobre `iniciar.bat` → *Ejecutar como administrador*).
- El bot activa la *DPI awareness* de Windows para que las coordenadas coincidan
  con el escalado de pantalla (125 %, 150 %...). Graba y reproduce con la misma
  configuración de pantallas/escala.
- Las teclas F9, F10 y Esc no se pueden grabar (están reservadas).
- Mantener Ctrl/Mayús pulsado mientras haces un clic grabará `Presionar tecla Ctrl`,
  el clic y `Soltar tecla Ctrl` como pasos separados (se reproducen igual).
- Algunos programas (juegos con protección anti-trampas, pantalla de bloqueo,
  UAC) ignoran las entradas simuladas.

## Estructura del proyecto
```
Bot de pruba/
├── bot.py            # Ventana (tkinter) y atajos globales
├── acciones.py       # Modelo: eventos crudos, pasos legibles, notas, JSON (sin pynput)
├── grabador.py       # Captura de ratón y teclado (pynput)
├── reproductor.py    # Reproducción fiel en un hilo, con abortar
├── requirements.txt  # pynput
├── iniciar.bat       # Instala dependencias y abre el bot
├── grabaciones/      # Grabaciones (.json); ultima.json es el autoguardado
└── tests/            # Pruebas unitarias
```

### Formato de los archivos `.json`
```json
{
  "version": 1,
  "creado": "2026-10-23T12:00:00",
  "eventos": [
    {"tipo": "abrir_url", "t": 0.0, "url": "https://example.com", "nota": "Abrir la web"},
    {"tipo": "mover",  "t": 5.0,   "x": 540, "y": 320},
    {"tipo": "clic",   "t": 0.52,  "x": 540, "y": 320, "boton": "left", "presionado": true, "nota": "Abrir el menú"},
    {"tipo": "scroll", "t": 1.10,  "x": 540, "y": 320, "dx": 0, "dy": -1},
    {"tipo": "tecla",  "t": 1.80,  "tecla": "a", "presionada": true, "vk": 65},
    {"tipo": "esperar","t": 2.50,  "segundos": 3.0}
  ]
}
```
`t` son los segundos desde el inicio. Las teclas especiales se guardan como
`"Key.enter"`; las letras como el propio carácter; si solo se conoce el código
de tecla virtual, como `"vk:67"` (así se recuperan los atajos tipo Ctrl+C).
El evento `abrir_url` guarda la URL; la espera de carga queda reflejada en las
marcas `t` de los eventos siguientes (en el ejemplo, la primera acción ocurre a los 5 s).
La clave `nota` va en el primer evento de cada paso (`nota_espera` en el evento
que sigue a una pausa automática).

## Pruebas
```
python -m unittest discover -s tests -v
```
Las pruebas de `acciones.py` no necesitan `pynput`. Las del reproductor usan
controladores falsos, así que no mueven el ratón ni pulsan teclas.

Para comprobar que la ventana arranca sin errores (se cierra sola):
```
python bot.py --smoke
python bot.py --smoke --url example.com   # comprueba además que el campo URL se rellena
```
Ninguna de las dos abre el navegador ni mueve el ratón.

## Solución de problemas
- **"No se encontró Python"** al abrir `iniciar.bat`: instala Python y marca
  *Add python.exe to PATH*.
- **Los clics caen en sitios distintos:** cambió la posición/tamaño de las
  ventanas o el escalado de pantalla desde la grabación.
- **No se graba nada en una aplicación concreta:** puede estar ejecutándose como
  Administrador; ejecuta también el bot como Administrador.
- **La ejecución se detuvo sola:** probablemente el ratón tocó la esquina
  superior izquierda (parada de seguridad). Cuando empieza a ejecutarse, el
  ratón no debe estar en esa esquina.
