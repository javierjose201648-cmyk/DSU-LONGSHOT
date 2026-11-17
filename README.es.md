# DSU Pad

**Convierte cualquier control DSU (cemuhook) con movimiento en un DualShock 4 virtual con giroscopio en Windows.**

[English](README.md)

DSU Pad recibe botones, sticks y movimiento de cualquier dispositivo que hable el
[protocolo DSU / cemuhook](https://v1993.github.io/cemuhook-protocol/). Por ejemplo, un teléfono con una app de control
DSU. La app calibra esa entrada y crea un **DualShock 4 virtual con giroscopio**. Así, cualquier juego que lea controles
por SDL o Steam Input ve un control de movimiento real.

Es un adaptador de control de uso general: Windows ve un DualShock 4 normal. Por eso funciona con:

- juegos de PC;
- Steam, incluido Steam Input, que puede convertir el giroscopio en mouse aunque el juego no lo soporte;
- emuladores como Dolphin, Cemu o Ryujinx;
- juegos que solo aceptan control de Xbox, con la salida Xbox 360 opcional.

Empezó como una forma de jugar **Longshot**, el port nativo para PC de *Ocarina of Time*, apuntando con movimiento.

```
dispositivo DSU ──Wi-Fi / UDP 26760──▶ DSU Pad ──▶ DualShock 4 virtual (ViGEmBus) ──▶ SDL / Steam Input ──▶ juego
                                               ├─▶ Xbox 360 virtual (opcional, giroscopio → stick derecho)
                                               └─▶ servidor DSU (opcional, para Dolphin, Cemu, …)
```

## Características

- **DualShock 4 virtual con giroscopio y acelerómetro reales.** Los reportes se reenvían a 250 Hz fijos, así que el
  movimiento se mantiene suave aunque el dispositivo mande menos muestras.
- **Tres tipos de control:**
  - Joy-Con izquierdo.
  - Wii Classic: control completo con 2 sticks, a/b/x/y, L/R/ZL/ZR, cruceta y L3/R3.
  - Wii Remote.
- **Calibración guiada** de unos 2 minutos. Aprende tres cosas:
  - qué manda cada botón;
  - la rotación y el centro de cada stick;
  - los ejes del giroscopio, con 3 gestos sencillos.

  Cada grupo de pasos se puede repetir por separado.
- **Perfiles:** guardar, duplicar, importar y exportar. Una vez guardado, no hace falta recalibrar.
- **Ajustes de control:**
  - remapeo de botones con «clic y presiona»;
  - zona muerta y rango del stick;
  - sensibilidad e inversión del giroscopio;
  - giroscopio → stick derecho (opcional).
- **Salidas opcionales:** Xbox 360 virtual y servidor DSU para emuladores como Dolphin.
- **Interfaz en inglés y español** (Ajustes → Idioma).
- **Simulador incluido** para probar todo sin dispositivo.

## Controles compatibles

| Control | Sticks | Botones | Uso típico | Estado |
|---|---|---|---|---|
| Joy-Con izquierdo | 1 | ZL, SL, SR, −, +, Home, 4 flechas | De lado: Longshot y la mayoría de juegos | Verificado con un dispositivo real |
| Wii Classic | 2 | a b x y, L R ZL ZR, AL/AR (L3/R3), cruceta, − + Home | Juegos que piden un control completo | Solo con simulador |
| Wii Remote | 0 | A, B, 1, 2, cruceta, − + Home | Dolphin y juegos con cruceta + movimiento | Solo con simulador |

Los botones de Wii Classic y Wii Remote salen de los perfiles oficiales de Dolphin que publica el desarrollador de la
app DSU Controller. De todos modos, el asistente mide cada botón, así que se adapta si un dispositivo los manda
distinto. Se agradecen reportes de pruebas con dispositivos reales.

## Requisitos

- Windows 10 u 11 de 64 bits.
- Driver [ViGEmBus](https://github.com/nefarius/ViGEmBus/releases). La app lo detecta y puede instalarlo.
- Un dispositivo DSU en la misma red local, por ejemplo un teléfono con una app de control DSU.

## Instalación

1. Descarga `DSU-Pad-<versión>-windows.zip` de **Releases** y descomprímelo. No hace falta Python.
2. Abre `DSU-Pad.exe`. El programa no está firmado, así que SmartScreen puede avisar: elige
   **Más información → Ejecutar de todas formas**.
3. Si la página **Conexión** dice que falta ViGEmBus, pulsa **Instalar ViGEmBus** y reinicia Windows.
4. Si el Firewall de Windows pregunta, permite la app en **redes privadas**. La app recibe paquetes UDP.

## Inicio rápido

1. En tu app DSU, elige el tipo de control (Joy-Con izquierdo, Wii Classic o Wii Remote). Anota la **IP y el puerto**
   que muestra; el puerto suele ser `26760`.
2. **Conexión:** escribe la IP y pulsa **Conectar**. Verás en vivo los paquetes y las muestras de movimiento por
   segundo.
3. **Control:** elige el mismo tipo de control que en la app DSU.
4. **Calibración:** pulsa **Empezar calibración** y sigue el dibujo iluminado. Al terminar, **Guardar perfil**.
5. **Jugar:** pulsa **Activar control** y luego abre el juego.

Las siguientes veces basta con abrir la app → **Jugar → Activar control**. También puedes marcar *Conectar sola al
abrir la app*, o abrir `DSU-Pad.exe --jugar`, que conecta y activa el control al abrir.

## Uso con juegos

### Juegos con SDL o Steam Input (Longshot y otros)

Abre el juego **después** de activar el control. Lo verá como *PS4 Controller* con giroscopio.

En Longshot:

- Abre el menú con F1, o con − y + a la vez.
- En *Controles → Movimiento* ajustas la sensibilidad y la inversión.
- Activa *Control en segundo plano* para no perder el control al cambiar de ventana.
- Su menú de opciones se mueve con la cruceta. Con el Joy-Con izquierdo, que no tiene cruceta, usa el mouse ahí.

### Dolphin y otros clientes DSU

1. Activa *Servidor DSU* en **Ajustes → Salidas**. El puerto por defecto es `26761`.
2. En el emulador, agrega `127.0.0.1:26761` como fuente de entrada alternativa.

Wii Remote y Wii Classic mandan los mismos botones que los perfiles de Dolphin de la app DSU Controller.

### Juegos que solo aceptan XInput

Activa *Xbox 360 virtual* y *Giroscopio → stick derecho*. Deja activo solo uno de los dos, DS4 o Xbox; si no, el
juego verá dos controles.

## Solución de problemas

| Problema | Qué revisar |
|---|---|
| No llega nada | Misma red Wi-Fi (no de invitados ni datos móviles), IP y puerto correctos, app DSU en primer plano y con la pantalla encendida, firewall permitido. Prueba `ping <IP del dispositivo>`. |
| El juego no ve el control | Activa el control **antes** de abrir el juego. Revisa que ViGEmBus esté instalado (página Conexión). |
| El apuntado va al revés | Invierte el eje en **Ajustes → Movimiento** o en el juego, o repite **Calibración → Giros**. |
| Aparecen dos controles | Deja activo solo uno: *DualShock 4* o *Xbox 360*. |
| Botones pegados al perder la señal | Si pasan 2 s sin datos, el control vuelve a neutro solo. |
| La app se cierra | Revisa `%APPDATA%\DSU-Pad\errores.log`. |

## Limitaciones conocidas

- Las apps DSU de teléfono suelen mandar el movimiento a unos 30–60 Hz; un Joy-Con real manda 60–200 Hz. Se puede
  jugar, pero se siente un poco menos fino.
- En el modo Joy-Con izquierdo de DSU Controller, SL y L llegan idénticos y presionar el stick no manda nada.
- ViGEmBus ya no recibe actualizaciones, pero sigue funcionando en Windows 10 y 11.

## Desarrollo

Comandos, estructura del proyecto y más detalles en la [versión en inglés](README.md#development).

Documentación técnica:

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/TESTING.md](docs/TESTING.md)
- [CHANGELOG.md](CHANGELOG.md)

Este proyecto no está afiliado a Nintendo, Sony, Microsoft ni a los autores de las apps mencionadas.
