# Architecture

## Data flow

```
UDP (DSU / cemuhook)  →  protocolo.ClienteDSU  →  motor.Motor (thread)
                                                     │  transformar(perfil)
                                                     ▼
                                        EstadoLogico (calibrated state)
                                                     │
                     ┌───────────────────────────────┼─────────────────────────┐
                     ▼                               ▼                         ▼
          salidas.SalidaDS4 (250 Hz)        salidas.SalidaXbox        salidas.ServidorDSU
          ViGEmBus → SDL / Steam Input      XInput                    DSU clients (Dolphin…)
```

| Module | Responsibility |
|---|---|
| `app/core/protocolo.py` | DSU packets (CRC32, version 1001), parser, client that re-subscribes every second and drops out-of-order packets. |
| `app/core/controles.py` | Controller layouts: physical buttons, the protocol bit each one sends, drawing geometry, default stick matrix and gyro axes per orientation. |
| `app/core/perfiles.py` | Versioned profile schema (`version: 2`), defaults, migration from older files, atomic save. |
| `app/core/calibracion.py` | Pure analysis functions and the calibration wizard (a state machine fed with packets). |
| `app/core/transformar.py` | Raw state → logical state: button mapping, stick matrix, dead zone, gyro axes, signs and units. |
| `app/core/salidas.py` | Virtual DS4 (re-sent at a fixed 250 Hz), Xbox 360, DSU server. |
| `app/core/motor.py` | Engine thread: connection, statistics, neutral state after 2 s without data. |
| `app/ui/` | PySide6 interface: Connection, Controller, Calibration, Settings, Profiles, Play. |
| `app/i18n.py` | English (default) and Spanish strings. |

## Conventions

- **Logical motion frame** (SDL / DS4): X right, Y up, Z toward the player. Gyro in °/s as (pitch, yaw, roll) with
  +pitch = point up, +yaw = point left, +roll = tilt left. Accelerometer in g, +1 on Y when flat.
- **Sticks**: logical = M · raw, where raw is centered and M is a 2×2 matrix measured by the wizard
  ("push toward *your* up / *your* right").
- **Output button names** follow the DS4 by position: A = bottom (✕), B = right (○), X = left (□), Y = top (△).
- **DSU server sign convention** (same as Dolphin's DSU client): accel Up = −Y, Left = +X, Forward = +Z;
  gyro Pitch Up = +pitch, Roll Left = −roll, Yaw Left = −yaw.

## Design decisions

1. **Virtual DS4 as the main output.** It is the only common path where SDL games receive real gyro data.
2. **Fixed 250 Hz DS4 reports.** A worker thread re-sends the latest state with its own clock. Phone DSU apps often send
   ~30 new motion samples per second, and some games read zero rotation between packets otherwise.
3. **Monotonic timestamps.** Some DSU apps repeat the same motion timestamp in several packets. The DS4 and the DSU server
   use a clock that always advances; the wizard treats a repeated timestamp as dt = 0.
4. **Calibration by gestures, not by time.** Each rotation step advances only after a real rotation (≥ 40°) followed by
   stillness, with live feedback. rad/s and m/s² sources are detected by magnitude.
5. **Button bits are measured, not assumed.** Each layout has expected bits (Left Joy-Con: measured with a real device;
   Wii Classic and Wii Remote: from the DSU Controller app's official Dolphin profiles). The wizard asks for every
   button and offers to remap when a different bit arrives.
6. **Left Joy-Con default mapping (sideways).** Half a Joy-Con has 10 usable buttons and a Switch-style game expects
   10 (A B X Y L R ZL ZR − +). Arrows become face buttons by position, SL/SR → L/R, ZL → ZL, the green icon → ZR,
   −/+ → −/+.
7. **Wii Classic / Wii Remote default mapping.** Each button is sent as the bit the DSU app uses for it, which is what
   the app's Dolphin profiles expect (Classic: a = ○, b = ✕, x = △, y = □, AL/AR = L3/R3).
8. **Profiles** are JSON files in `%APPDATA%\DSU-Pad\perfiles`; files from older versions are migrated on load.
9. **Interface language** is stored in `%APPDATA%\DSU-Pad\ajustes.json` (`"idioma": "en" | "es"`) and applies on
   restart.
