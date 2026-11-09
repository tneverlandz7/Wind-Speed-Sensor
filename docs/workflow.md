# Hardware and operating workflow

Run commands from the repository root. Use a new output file/directory for every recording or calibration.

## Wiring

| Nucleo-F411RE | Weight-I2C U180 | MCP9808 |
| --- | --- | --- |
| PB9 SDA | SDA, address 0x26 | SDA, address 0x18 |
| PB8 SCL | SCL | SCL |
| GND | GND | GND |
| 5V | Supply according to module label | — |
| 3V3 | — | Supply according to board label |

Verify 3.3 V SDA/SCL logic compatibility when the I2C module is powered at 5 V. Keep plate, mounting, and wind direction fixed. See `system_diagram.mmd` for the measurement chain.

## Commands and units

| Direct firmware command | Action |
| --- | --- |
| `z` | Five-second no-wind baseline; clears calibration |
| `p 4.12` | Calibration capture at measured **4.12 m/s** |
| `v 5.00` | Independent validation capture at measured **5.00 m/s** |
| `r` / `d` | Status / calibration CSV, including restore command |
| `q` | Zero-drift check without clearing the model |
| `k ZERO SIGMA SIGN BETA` | Restore saved calibration |
| `j` | Diagnostic 200 Hz sequence,speed stream |
| `g` | Calibrated 200 Hz numeric-only stream |
| `x` | Exit streaming; print missed-slot/I2C statistics |

The Python logger accepts `speed-p 4.12` and `speed-v 5.00` in **m/s**. Its legacy `p` and `v` instead accept **Pa**, convert using `10*sqrt(Pa/60)`, and forward speeds to firmware. That approximate conversion has only the original 60 Pa = 10 m/s anchor; prefer measured reference speeds.

## Record calibration

1. Leave `COMP0219_AUTOSTART=0` in both main headers and upload. Close Serial Monitor.
2. Run the tunnel reference recorder and this project's logger on the same laptop. Only this logger should open the Nucleo port during raw calibration. Verify that actual reference data is saving, using measured ambient pressure and temperature.

   ```sh
   python python/log_serial.py --port COM7 --output data/new_session.csv
   ```

3. If streaming, send `x` to resume LIVE readings. With the fan off, send `z` once and wait for ZERO. A new baseline requires a new recording.
4. At a settled calibration setting, send `begin cal speed_2`, wait about 10 seconds, then `end`. Repeat across the target range with unique names. Names are labels; the reference CSV supplies actual speeds.
5. Record separate validation windows with `begin val check_5`, wait, then `end`. Include repeated settings and a decreasing-speed pass. At least two usable calibration windows and one validation window are required.
6. Save the reference recording. Close the final window, then send `stop` in this logger. It saves the sensor CSV and companion `_windows.csv`.
7. Fit with the actual ambient settings entered in the reference recorder. Replace the example 101325 Pa and 20 C below. The reference CSV needs `timestamp_epoch` and `value_raw_mps`.

   ```sh
   python python/calibrate_sensor.py --sensor data/new_session.csv --reference data/new_reference_vdas.csv --windows data/new_session_windows.csv --ambient-pressure-pa 101325 --reference-temperature-c 20 --mounting-notes "Describe the mounting" --firmware-version "Identify the uploaded revision" --out results/new_session
   ```

8. Review plateau stability, calibration/validation plots, `windows_summary.csv`, and `model.json`. Input checks do not imply an accuracy pass. Range limits default to 2–10 m/s; an explicit `--min-reference-mps 1.9` accepts a measured edge point below 2 without rounding it.

The fitter uses the firmware's square-root model, sign convention, three-sigma deadband, and 101325 Pa density convention. Recalibrate after mounting or material ambient-pressure changes. Temperature updates density, not load-cell thermal drift. Source hashes identify host files, not which firmware is flashed on the board.

## Restore and deploy

The logger saves a received RESTORE_CMD to a companion file. Offline calibration exports `calibration_restore.txt`.

```sh
python python/log_serial.py --port COM7 --output data/post_calibration.csv --model-file results/new_session/calibration_restore.txt
```

With the fan off, send `load`, `r`, then `q`, waiting for each response. Do not send `z` after loading: it clears the model. To enable autonomous output:

```sh
python python/generate_calibration_header.py --model-file results/new_session/calibration_restore.txt
```

This updates both main headers and enables autostart. Recompile/upload and verify no-wind behavior, known tunnel speeds, and actual rate. Restore AUTOSTART=0 before new calibration. Neither header affects the experimental stream sketch.

## Reproduce recorded fits

Run03's stored user-supplied reference settings are 101325 Pa and 20 C. These commands retain those historical settings; they do not independently verify them.

```sh
python python/calibrate_sensor.py --sensor data/lab_run03.csv --reference data/T4_20261104_155058_giga_vdas.csv --windows data/lab_run03_windows.csv --ambient-pressure-pa 101325 --reference-temperature-c 20 --min-reference-mps 1.9 --out results/lab_run03_reproduced
python python/calibrate_sensor.py --sensor data/lab_run06.csv --windows data/lab_run06_windows.csv --assumed-speeds data/lab_run06_assumed_speeds.csv --out results/lab_run06_assumed_reproduced
```

Run06 is provisional. The assumed-speed mapping must explicitly match window names; it cannot be combined with a measured reference. Keep `ASSUMED_REFERENCES.txt` with its outputs. The fixed diagnostic script below verifies input hashes and overwrites its existing derived CSV and PNG in `results/lab_run06_diagnostics/`:

```sh
python python/plot_run06_calibration.py
```

## Independent evaluation

`evaluate_reference.py` requires a measured clock shift from the reference time to the logger's `host_elapsed_s`, supplied via `--ref-time-offset-s`. Reference columns default to `time_s` and `speed_mps` and are configurable. Manual annotations do not provide synchronization.

`correct_zero_offset.py` requires original aligned, student, and reference exports, plus an explicit `--zero-speed`. It preserves original readings alongside corrected values and records assumptions. It does not change the MCU model.
