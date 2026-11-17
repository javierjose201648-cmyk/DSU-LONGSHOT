# DSU Pad

1. Windows desktop app (Python 3.11 + PySide6) that receives a DSU / cemuhook controller over UDP (port 26760),
   calibrates it and outputs a virtual DualShock 4 with gyro (ViGEmBus + vgamepad) that SDL games read.
2. Layouts: Left Joy-Con, Wii Classic, Wii Remote (`app/core/controles.py`). Optional outputs: Xbox 360, DSU server.
3. Code: `app/core` (logic, no UI), `app/ui` (Qt), `app/tests` (simulator + tests), `app/i18n.py` (EN default, ES).
4. Tests: `python -m pytest app/tests`. Build: `python build.py` (PyInstaller onedir).
5. Honesty rule: "tested with the simulator" is not "tested with a real device"; say so explicitly
   (status table in `docs/TESTING.md`).
6. Read `docs/ARCHITECTURE.md` before working. If a local `privado/` folder exists (not in git), read it too.
7. Privacy: the repository is public. Never commit names, IP addresses, local paths, emails or device details.
8. Don't touch game saves or emulator configuration without a backup.
