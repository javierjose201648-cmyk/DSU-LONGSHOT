# Testing and verification status

"Tested with the simulator" is not the same as "tested with a real device". This page says which is which.

## Automated tests

```
.venv\Scripts\python -m pytest app/tests
```

| Test file | What it covers |
|---|---|
| `test_nucleo.py` | Packet parsing (including a real captured packet), CRC, axis and stick deduction, mappings, profiles and migration. |
| `test_red.py` | Simulator vs. real capture, client re-subscription, out-of-order packets, DSU server, engine, full wizard with a scripted user in several orientations and units. |
| `test_controles.py` | Wii Classic and Wii Remote: default profiles, right stick, wizard end to end, learning an unexpected bit. |
| `test_ds4_real.py` | Simulator → engine → virtual DS4 → SDL (all buttons, both sticks, gyro per axis, neutral after signal loss). Skipped without ViGEmBus or SDL. |
| `test_ui.py` | The whole interface against the simulator for all three layouts, saving and reopening a profile. |
| `test_i18n.py` | English by default, Spanish strings, language switch saved in the settings. |

`app/tests/simulador.py` reproduces a phone DSU app: slot 1, ~54 packets/s with ~33 new motion samples/s, repeated
timestamps, and the button bits of each layout.

## Verification status

| Item | Simulator | Real device |
|---|---|---|
| Left Joy-Con: connection, calibration, buttons, stick, gyro | ✓ | ✓ |
| Longshot recognizes the virtual DS4 with gyro and integrates rotation | ✓ | ✓ |
| Wii Classic: 17 buttons and both sticks through the virtual DS4 into SDL | ✓ | not yet |
| Wii Remote: buttons and motion | ✓ | not yet |
| DSU server against a real Dolphin | — | not yet (tested with a test client) |
| Installing ViGEmBus from the app | — | not yet |

If you test a layout with a real device, please open an issue with the result and, if something differs, the bit the
wizard reported for each button.
