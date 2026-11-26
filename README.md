# Nexa Notes 0.13.5

Notas personales y etiquetas de colores para los jugadores de las mesas de Nexa Poker.
Programa portable para Windows 10/11: un solo archivo `NexaNotes.exe`, sin instalar nada.

---

## 1. Cómo obtener NexaNotes.exe (paso a paso)

1. En GitHub, abre tu repositorio **NexaNotesv2**.
2. **Borra el workflow antiguo**: entra en `.github/workflows/`, abre `crear-exe.yml`,
   pulsa el icono de la papelera y confirma con **Commit changes**.
   (Si no lo borras, se ejecutarán dos compilaciones y la antigua genera un `.exe` sin OCR.)
3. Descomprime en tu ordenador el ZIP que te he entregado.
4. En la página principal del repositorio pulsa **Add file → Upload files**.
5. Arrastra **todo el contenido** de la carpeta descomprimida (no la carpeta en sí):
   `nexanotes`, `tests`, `assets`, `tools`, `.github`, `nexa_notes.py`, `NexaNotes.spec`,
   `requirements.txt`, `requirements-dev.txt`, `README.md`, `.gitignore`.
   Acepta reemplazar `nexa_notes.py` y `requirements.txt`.
   > La carpeta `.github` empieza por punto y en Windows puede estar oculta. Si no la ves,
   > en el Explorador activa **Vista → Mostrar → Elementos ocultos**.
6. Pulsa **Commit changes**. La compilación empieza sola.
7. Ve a la pestaña **Actions**, abre la ejecución **Compilar NexaNotes.exe** y espera a que
   tenga el círculo verde (unos 10–15 minutos).
8. Abajo, en **Artifacts**, descarga **NexaNotes-Windows** (es un ZIP). Dentro está `NexaNotes.exe`.

Si algún paso sale en rojo, abre ese paso, copia el texto del error y envíamelo.
La compilación **se detiene a propósito** si el OCR no funciona, si falla una prueba o si
falta algún recurso dentro del ejecutable: nunca se publica un `.exe` defectuoso.

### Qué comprueba la compilación
| Paso | Comprobación |
|---|---|
| 1 | Las dependencias se instalan e importan |
| 2 | El OCR lee los 7 nombres de una captura real **antes** de compilar |
| 3 | Pruebas automáticas (detección, OCR, timebank, asientos vacíos, base de datos, filtro de ventanas) |
| 4 | Compilación con PyInstaller |
| 5 | El `.exe` contiene `config.yaml`, los 3 modelos ONNX, onnxruntime y los gráficos |
| 6 | El OCR funciona **dentro** del `.exe` (código de salida e informe `selftest_exe.json`) |
| 7 | Publicación del `.exe` |

---

## 2. Uso

1. Abre `NexaNotes.exe` (no arranca con Windows). La primera vez pide tu nick.
2. Abre tus mesas de Nexa Poker. En la ventana principal verás **Mesas detectadas: N**.
3. Junto a cada jugador reconocido aparece un **botón pequeño redondo con un lápiz**, a la
   derecha de su etiqueta. Púlsalo para abrir el editor: elige color, escribe notas y **Guardar**.
   El rectángulo de color aparece al instante alrededor del nickname y las fichas.
4. **Quitar color** elimina el borde pero conserva las notas.
5. En la ventana principal puedes buscar jugadores, editarlos, añadirlos a mano o eliminarlos.

Tus datos están en `%LOCALAPPDATA%\NexaNotes\jugadores.db` (la misma base de datos de
siempre). Al abrir esta versión por primera vez se crea una copia de seguridad
`jugadores.backup-v0-FECHA.db` y se añaden columnas nuevas sin borrar nada.

**¿Por qué un botón y no un clic sobre el avatar?** La superposición deja pasar todos los
clics a Nexa Poker, para no interferir nunca con el cliente. El botón es la única zona
interactiva, está fuera del nickname, de las fichas y de los botones de juego, y solo abre
el editor: nunca hace clics en la mesa. Se puede ocultar en **Ajustes**.

### Si no detecta las mesas
El filtro exige que la ventana sea **del proceso de Nexa Poker** y que su título contenga
**Blinds**. Por defecto se acepta cualquier ejecutable cuyo nombre contenga «nexa».
Abre **Ventana de diagnóstico**: en «Ventanas descartadas» verás el nombre exacto del
proceso de cada ventana con «Blinds». Si el de Nexa no contiene «nexa», escríbelo en
**Ajustes → Proceso de Nexa contiene**.

---

## 3. Modo diagnóstico

- **Modo diagnóstico** (casilla): dibuja sobre cada mesa todas las etiquetas detectadas
  (blanco), la zona que lee el OCR (amarillo), el estado y texto leído de cada asiento,
  las zonas descartadas con su motivo (rojo) y los tiempos del análisis.
- **Ventana de diagnóstico**: mesas identificadas, proceso, método de captura, tiempos,
  estado de cada asiento, eventos (timebank, cambios de jugador...), ventanas descartadas
  y errores.
- Con el modo diagnóstico activado se guarda la última captura de cada mesa en
  `%LOCALAPPDATA%\NexaNotes\diagnostico\` (sirve para enviármela si algo falla).
- **Probar con captura…**: analiza una imagen guardada y genera `*_diagnostico.png` y
  `*_diagnostico.json` al lado. También por línea de comandos:
  `NexaNotes.exe --analizar captura1.png captura2.png`.

Para que una captura forme parte de las pruebas automáticas, guárdala en
`tests/capturas/extra/` con el número de jugadores al final: `mesa_6max_4.png`.

---

## 4. Cómo funciona

| Módulo | Función |
|---|---|
| `winapi.py` | Enumera ventanas, lee el ejecutable del proceso, posición/estado y captura del área cliente (PrintWindow). Solo lectura visual, sin inyectar ni leer memoria. |
| `detector.py` | Detecta las etiquetas sin coordenadas fijas: color gris pizarra de la etiqueta → rectángulos aislados (y, con su tamaño, búsqueda de etiquetas pegadas al borde de la mesa) → validación (proporción ~2:1, fondo oscuro, **dos líneas de texto centradas**, avatar encima). No depende del azul de las fichas. |
| `ocr.py` | RapidOCR + ONNX Runtime, una sola instancia, 1 hilo, **solo el reconocedor** sobre la mitad superior de la etiqueta (nickname). No puede leer avatares, fichas ni el fondo. |
| `textrules.py` | Clasifica lo leído: nombre, timebank (números cortos), acción (All in, Fold...), cantidad, nombre truncado «…». |
| `tracker.py` | Identidad de cada asiento (ver abajo). |
| `engine.py` | Planificación: un solo hilo de análisis, sin colas. |
| `overlay.py` | Ventanas transparentes que no reciben clics ni foco, «propiedad» de cada mesa. |
| `app.py`, `editor.py` | Ventana principal, editor rápido, ajustes y diagnóstico. |

### Timebank, asiento vacío y cambio de jugador
- **Timebank / All in / Fold / Check**: el texto no es un nombre → se mantiene la identidad y el color.
- **Asiento vacío**: la etiqueta desaparece en **2 análisis seguidos** → se retira la identidad.
  Una sola ausencia (animación) no la retira.
- **Cambio de jugador sin que la etiqueta desaparezca**: si se lee otro nombre, el asiento
  queda **«en duda» y sin color** hasta confirmarlo con una segunda lectura (o al momento si
  además cambió el avatar). Así un jugador nuevo nunca hereda el color del anterior.
- **Errores pequeños de OCR** (una letra) no se consideran cambio de jugador.
- **Nombre truncado «…»**: no se asocia a nadie automáticamente. El editor te pide el nombre
  completo (con sugerencias de tu base de datos) y lo mantiene mientras siga ese jugador.

### Superposición
- Cada rectángulo de color son **4 tiras finas de color sólido** por fuera de la etiqueta, y el
  botón del lápiz es otra ventana pequeña. Se colocan justo encima de su mesa en el orden de
  ventanas (sin activarse): quedan tapadas por las mismas ventanas que tapan la mesa, se ocultan
  al minimizarla y no aparecen encima de otras aplicaciones.
- Coordenadas en píxeles físicos (escalado DPI desactivado en Qt), por lo que coinciden con
  las de Windows en cualquier escala y monitor.
- La posición se sigue con llamadas Win32 muy ligeras cada 120 ms (sin capturas).

### Frecuencia de análisis y consumo
- Búsqueda de mesas: cada **5 s**.
- Un único hilo analiza **una mesa cada 2 s** en turno rotatorio (captura del área cliente
  + detección ≈ 20–70 ms). Nunca hay dos OCR a la vez ni trabajos acumulados.
- OCR (≈ 20 ms por nombre) solo cuando un asiento es nuevo, está en duda, cambia el avatar o
  pasan **30 s** desde su última lectura.
- Con **N** mesas visibles, cada mesa se re-analiza cada **2·N s** y cada nombre se relee
  cada **máx(30 s, 2·N s)**:

| Mesas | Etiquetas/asientos vacíos | Relectura OCR |
|---|---|---|
| 4 | cada 8 s | cada 30 s |
| 12 | cada 24 s | cada ~30 s |
| 20 | cada 40 s | cada ~40 s |

  El consumo de CPU no crece con el número de mesas (está limitado por el turno de 2 s);
  lo que crece es el tiempo entre análisis de una misma mesa. Las mesas minimizadas, en otro
  escritorio o cerradas no se analizan, y sus recursos se liberan. El cambio de color al
  guardar es inmediato (no espera al OCR).

---

## 5. Estado de las pruebas (honesto)

| Tipo | Estado |
|---|---|
| Sintaxis e importación de todos los módulos | ✔ hecho |
| Pruebas automáticas (73) en Linux con Python 3.12 | ✔ pasan |
| Detección con 5 capturas (3 reales de tu Windows, una con los botones Fold/Call): todas las etiquetas, 0 falsos positivos | ✔ hecho |
| OCR con las 3 capturas: 20/20 nombres (latinos y chinos) | ✔ hecho |
| Dibujo del overlay sobre tus capturas (posición de rectángulos) | ✔ hecho |
| Compilación con PyInstaller + recursos incluidos + OCR dentro del binario | ✔ hecho **en Linux**; en Windows lo comprueba el workflow |
| Interfaz (ventana principal, editor, ajustes, diagnóstico) | ✔ arranca sin errores en modo sin pantalla |
| Windows real: detección de ventanas de Nexa (proceso «Nexa Poker.exe» + «Blinds») | ✔ comprobado por ti (v0.13.0) |
| Windows real: captura de la mesa | ✔ funciona copiando de la pantalla (la mesa debe estar visible); PrintWindow devuelve negro con Nexa |
| Windows real: rectángulos de color con tiras sólidas (0.13.2) | ✘ pendiente de tu prueba |
| Asientos vacíos reales, timebank real, bounty, otros fondos, mesas de 2–6 | ✘ sin capturas reales (simulados en pruebas) |

## 6. Normas de Nexa Poker
No he podido consultar las normas oficiales de Nexa Poker (sin acceso a internet en esta
sesión). **Antes de usarlo en mesas reales, pide a la sala confirmación por escrito** de que
se permite un programa de notas personales con superposición visual que lee la pantalla.
Nexa Notes no recomienda jugadas, no calcula estadísticas ni estrategias, no automatiza
acciones, no lee la memoria del cliente, no intercepta comunicaciones y no comparte datos.
