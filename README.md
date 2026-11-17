# DSU Longshot

**Turn any DSU (cemuhook) motion controller into a virtual DualShock 4 with gyro on Windows.**

[Español](README.es.md)

DSU Longshot receives buttons, sticks and motion from any device that speaks the
[DSU / cemuhook protocol](https://v1993.github.io/cemuhook-protocol/), for example a phone running a DSU controller
app. It calibrates the input and outputs a **virtual DualShock 4 with gyroscope**, so any game that reads controllers
through SDL or Steam Input sees a real motion controller. It was built for **Longshot** (the native PC port of
*Ocarina of Time*), but it works with any SDL-based game or emulator.

```
DSU device ──Wi-Fi / UDP 26760──▶ DSU Longshot ──▶ virtual DualShock 4 (ViGEmBus) ──▶ SDL / Steam Input ──▶ game
                                               ├─▶ virtual Xbox 360 (optional, gyro → right stick)
                                               └─▶ DSU server (optional, for Dolphin, Cemu, …)
```

## Features

- **Virtual DualShock 4 with real gyro and accelerometer**, re-sent at a fixed 250 Hz so motion stays smooth even
  when the source sends fewer samples.
- **Three controller layouts**: Left Joy-Con, Wii Classic (full controller: two sticks, a/b/x/y, L/R/ZL/ZR,
  d-pad, L3/R3) and Wii Remote.
- **Guided calibration** (about 2 minutes): learns which button sends what, the stick rotation and center, and the
  gyro axes and signs from three simple gestures. Any group of steps can be repeated on its own.
- **Profiles**: save, duplicate, import and export calibrations; no recalibration on the next launch.
- **Button remapping** with "click and press", stick dead zone and range, gyro sensitivity and inversion,
  optional gyro → right stick.
- **Optional outputs**: virtual Xbox 360 and a DSU server for emulators such as Dolphin.
- **English and Spanish interface** (Settings → Language).
- **Built-in simulator** to try everything without a device.

## Supported layouts

| Layout | Sticks | Buttons | Typical use | Status |
|---|---|---|---|---|
| Left Joy-Con | 1 | ZL, SL, SR, −, +, Home, 4 arrows | Held sideways: Longshot and most games | Verified with a real device |
| Wii Classic | 2 | a b x y, L R ZL ZR, AL/AR (L3/R3), d-pad, − + Home | Games that need a full controller | Simulator only |
| Wii Remote | 0 | A, B, 1, 2, d-pad, − + Home | Dolphin and d-pad + motion games | Simulator only |

The button bits for Wii Classic and Wii Remote come from the official Dolphin profiles published by the
DSU Controller app developer. The calibration wizard measures every button anyway, so layouts that send different
bits are learned automatically. Reports with real devices are welcome.

## Requirements

- Windows 10 or 11 (64-bit).
- [ViGEmBus](https://github.com/nefarius/ViGEmBus/releases) driver. The app detects it and can install it for you.
- A DSU source on the same local network, for example a phone running a DSU controller app.

## Installation

1. Download `DSU-Longshot-<version>-windows.zip` from **Releases** and unzip it. Python is not needed.
2. Run `DSU-Longshot.exe`. The executable is not signed, so Windows SmartScreen may warn you:
   choose **More info → Run anyway**.
3. If the **Connection** page reports that ViGEmBus is missing, click **Install ViGEmBus** and restart Windows.
4. If Windows Firewall asks, allow the app on **private networks** (it receives UDP packets).

## Quick start

1. In your DSU app, select the controller layout (Left Joy-Con, Wii Classic or Wii Remote) and note the **IP address
   and port** it shows (the port is usually `26760`).
2. **Connection**: type the IP address and click **Connect**. Packets and motion samples per second appear live.
3. **Controller**: choose the same layout you picked in the DSU app.
4. **Calibration**: click **Start calibration** and follow the highlighted drawing. Then **Save profile**.
5. **Play**: click **Enable controller**, then start your game.

Next time: open the app → **Play → Enable controller**. You can also tick *Connect automatically on startup*, or run
`DSU-Longshot.exe --jugar` to connect and enable the controller right away.

## Using it with games

**SDL / Steam Input games (Longshot and others).** Start the game *after* enabling the controller. It shows up as a
*PS4 Controller* with a gyroscope. In Longshot, open the menu (F1, or − and + together) → *Controls* → *Motion*
to adjust sensitivity and inversion, and enable *Background input* so you don't lose control when switching
windows. Longshot's options menu is navigated with the d-pad; with the Left Joy-Con layout use the mouse there.

**Dolphin and other DSU clients.** Enable *DSU server* under **Settings → Outputs** (default port `26761`) and add
`127.0.0.1:26761` as an alternate input source in the emulator. The Wii Remote and Wii Classic layouts send the same
buttons as the DSU Controller app's Dolphin profiles.

**XInput-only games.** Enable *Virtual Xbox 360* and *Gyro → right stick*. Keep only one of DS4 / Xbox enabled, or
the game will see two controllers.

## Troubleshooting

| Problem | What to check |
|---|---|
| Nothing arrives | Same Wi-Fi network (no guest network or mobile data), correct IP and port, DSU app in the foreground with the screen on, firewall allowed. Try `ping <device IP>`. |
| The game doesn't see the controller | Enable the controller *before* starting the game. Check that ViGEmBus is installed (Connection page). |
| Aiming is inverted | Invert the axis in **Settings → Motion**, in the game, or repeat **Calibration → Rotations**. |
| Two controllers appear | Keep only one of *DualShock 4* / *Xbox 360* enabled. |
| Stuck buttons after signal loss | If no data arrives for 2 s the controller returns to neutral by itself. |
| The app closes unexpectedly | See `%APPDATA%\DSU-Longshot\errores.log`. |

## Known limitations

- Phone-based DSU apps usually send motion at around 30–60 Hz (a real Joy-Con sends 60–200 Hz). It is playable but
  slightly less smooth.
- In the Left Joy-Con layout of DSU Controller, SL and L arrive identical and clicking the stick sends nothing.
- ViGEmBus is no longer developed, but it still works on Windows 10 and 11.

## Development

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt pyinstaller pytest pysdl2 pysdl2-dll
.venv\Scripts\python -m app.main --simulador                         # app + simulated DSU device
.venv\Scripts\python -m app.main --simulador --control wii-classic   # simulate another layout
.venv\Scripts\python -m pytest app/tests                             # test suite
.venv\Scripts\python build.py                                        # dist\DSU-Longshot\ and the .zip
```

Project layout:

```
app/
  core/        protocol, controller layouts, calibration, transforms, outputs, profiles, engine (no UI)
  ui/          Qt (PySide6) windows and drawings
  tests/       DSU device simulator, scripted "robot user", tests
  i18n.py      English / Spanish strings
herramientas/  diagnostic tools (read the virtual DS4 through SDL, drive a game without a device)
referencia/    original command-line bridge, packet capture and layout screenshot
docs/          architecture, test status, CI workflow
```

More detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/TESTING.md](docs/TESTING.md) ·
[CHANGELOG.md](CHANGELOG.md).

The GitHub Actions workflow lives in `docs/ci/windows.yml`. Copy it to `.github/workflows/` to enable it; pushing
it requires a token with the `workflow` scope.

## Acknowledgements

- [cemuhook DSU protocol](https://v1993.github.io/cemuhook-protocol/) documentation.
- [ViGEmBus](https://github.com/nefarius/ViGEmBus) and [vgamepad](https://github.com/yannbouteiller/vgamepad) for
  virtual controllers.
- [Dolphin](https://github.com/dolphin-emu/dolphin)'s DSU client, used as a reference for conventions.
- [DSU Controller guides](https://github.com/breeze2/dsu-controller-guides) for the layout button profiles.

This project is not affiliated with Nintendo, Sony, Microsoft or the authors of the apps mentioned.
