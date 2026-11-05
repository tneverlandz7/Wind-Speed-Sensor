# COMP0219 Stage 1: HX711 I2C + MCP9808 / 200 Hz output

**Goal:** contact-based airspeed, 2–10 m/s; Nucleo-F411RE computes airspeed and streams **one ASCII floating-point airspeed (m/s) per line at 200 Hz, 115200 baud** in final assessment mode. Arduino IDE is acceptable *per the lecturer's verbal confirmation*. A buildable optional PlatformIO target is also supplied.

**Status:** firmware source passes a C++ syntax check with mock Arduino/Wire interfaces. **It has not been tested on this exact user's board or wind tunnel. Do not claim a 200 Hz pass before running the hardware sequence diagnostic.** Python analysis passed with explicitly synthetic demo data.

## Files

- `firmware_Arduino/COMP0219_Stage1/COMP0219_Stage1.ino` (+ `calibration_config.h`): Arduino IDE version.
- `firmware_Arduino/COMP0219_SpeedOnly_Lab03/COMP0219_SpeedOnly_Lab03.ino`: standalone numeric-output test sketch with the lab_run03 calibration embedded. Its validation error is approximately 1.75 m/s; investigate accuracy before assessment use.
- `firmware/` (`platformio.ini`, `src/main.cpp`, `src/calibration_config.h`): optional VS Code/PlatformIO build.
- `python/logger_200hz.py`: timestamps and logs real UART data and manual pressure labels; `p`/`v` arguments are in **Pa**, not m/s.
- `python/check_200hz.py`: 200 Hz **line transfer** and sequence continuity test (`j` diagnostic mode, even before calibration).
- `python/analyze.py`: stationary wind tunnel fit / calibration plots / validation metrics (for real runs, needs POINT records).
- `python/calibrate_from_tunnel.py`: recommended offline calibration from tutorial reference CSV + raw sensor log + marked steady windows.
- `python/calibration_model.py`: shared firmware-equivalent fitting and prediction, including the baseline noise deadband.
- `python/plot_stream_200hz.py`: manual-reference-labeled time plots (cannot claim synchronized rise times).
- `python/demo.py`: synthetic demonstration. **Never submit synthetic metrics.**
- `python/make_embedded_config.py`: writes real calibration into firmware header for automatic 200 Hz, no-host-compute assessment output.

## IMPORTANT two separate speed limits

1. **200 Hz UART output** = one float every 5 ms; this is what the brief explicitly specifies.
2. **New HX711 conversions** = 10 or 80 samples/second in hardware, and the M5Stack I2C internal controller's update behavior has NOT been measured. A 200 Hz output is a multispeed estimate, **not 200 independent measurements**. Keep this distinction in the report.

## On-board setup tonight

Your working wiring remains unchanged, after verifying **3.3 V SDA/SCL logic safety** for 5 V I2C module:

| MCU | Weight-I2C U180 | MCP9808 |
| --- | --- | --- |
| PB9 SDA | SDA (0x26) | SDA (0x18) |
| PB8 SCL | SCL | SCL |
| GND | GND | GND |
| 5V | supply per label | — |
| 3V3 | — | supply per board label |

1. Keep a copy of your existing **tested 5 Hz project**. Do NOT overwrite it.
2. Compile/upload `firmware_Arduino/COMP0219_Stage1/COMP0219_Stage1.ino`. Select Nucleo-F411RE, 115200 baud, `Newline`.
3. With Serial Monitor closed, from package root:

   ```bash
   pip install -r python/requirements.txt
   python python/check_200hz.py --port COM7 --seconds 12 --output data/bedroom_200hz.csv
   ```

   This sends `j` and receives `sequence,speed` at 200 Hz; no calibration needed. It verifies **host throughput and missing sequence numbers**, not ADC freshness and not exact internal timer jitter. For a pass, observed rate should be around 200 lines/s with zero missing sequences; check the `STREAM_EXIT` `missed_slots` statistic as well. If it fails, use your working 5 Hz version for diagnosis, do not mask the failure.
4. Optionally test the logger on current firmware:

   ```bash
   python python/logger_200hz.py --port COM7 --output data/bedroom.csv
   ```

   Type `z`, then `r`, then `j` (several seconds), then `x`, `stop`. Never type `p`/`v` at home without a reference wind tunnel. Avoid `g` until calibration is valid.
5. You can verify Python plotting separately with `python python/demo.py --output data/demo_SYNTHETIC_DO_NOT_SUBMIT.csv` and `python python/analyze.py --input data/demo_SYNTHETIC_DO_NOT_SUBMIT.csv --out outputs/demo`.

## Firmware modes and commands

For a standalone test of the current lab_run03 prediction, open
`firmware_Arduino/COMP0219_SpeedOnly_Lab03/COMP0219_SpeedOnly_Lab03.ino` in Arduino
IDE, select Nucleo-F411RE and upload. Its folder name matches its sketch name;
keep it separate from the Stage1 sketch. It needs no `calibration_config.h` or
serial commands: after initialization it prints one speed in m/s per line at a
scheduled 200 Hz, 115200 baud. Close Serial Monitor before connecting the board
in Wind Tunnel Logger. Calibration parameters are constants near the top of the
new sketch; regenerating Stage1's headers does not update this standalone copy.
This is the current experimental fit (reference 2.926 m/s predicted 4.674 m/s),
not evidence of acceptable accuracy. Like Stage1, missing initial sensor reads
produce numeric zero, and failed later reads hold the last successful reading.
Check actual sensor operation and hardware output rate separately.

| Firmware command | Function | Output |
| --- | --- | --- |
| `z` | 5-second no-wind zero; **wipes calibration** | ZERO + diagnostics |
| `p 4.082` | 5-second stationary calibration capture for **reference speed in m/s** | POINT, MODEL |
| `v 5.000` | independent validation capture in **m/s** | POINT, error |
| `r` | status + error metrics + `RESTORE_CMD` | text |
| `d` | calibration/validation CSV + `RESTORE_CMD` | text |
| `q` | zero-drift check (does **not** wipe model) | ZERO_CHECK |
| `k 8836559 27.17 -1 0.218484` | restore already measured model from file | RESTORE_OK |
| `j` | 200 Hz diagnostic, `seq,speed` | only sequence+speed until `x` |
| `g` | **200 Hz float-only** after calibration | only speed line until `x` |
| `x` | exit stream, print missed-slot/I2C stats | one STREAM_EXIT summary |

**Important discrepancy:** in `python/logger_200hz.py`, the convenient `p 3` and `v 8` mean **pressure in Pa**. The logger *assumes* `v=10 sqrt(Pa/60)` and forwards a reference speed to the STM32. This model is supported by the *one* provided 60Pa=10m/s anchor only at that point; verify full wind-tunnel manual and obtain **synchronized 200 Hz Dwyer/Pitot ground truth** from TA before reporting official errors or precise dynamic response.

## Save & restore a calibration across reset

1. During calibration, run `r` or `d` from the Python logger. It sees the firmware's `RESTORE_CMD,k ...` line and automatically creates `data/<runname>_calibration_restore.txt`.
2. After reboot, start the logger **before** entering `g` and type `load`. Logger forwards the stored `k ...` command to STM32. `r` verifies. This is a parameter transfer only; MCU computes all estimates.
3. For autonomous final demo, **after lab measurements**, run:

   ```bash
   python python/make_embedded_config.py --model-file data/lab_run01_calibration_restore.txt
   ```

   It updates both copies of `calibration_config.h` to set `COMP0219_AUTOSTART=1` with measured parameters. Recompile/reupload. On power-up, firmware emits **only 200 Hz numeric floats** (after its short initialization delay). Re-test while wind is off and at a known tunnel setting. For new calibration, restore the headers to `AUTOSTART 0` and upload again.

## Lab logging

### Recommended: calibrate from the tutorial's measured reference speeds

Use the installed **Wind Tunnel Logger** for the tunnel reference and this project's
logger for raw Nucleo readings, **on the same laptop**. Keep the tutorial's student
connection disconnected during calibration: only our logger opens the Nucleo port.
The tutorial can save reference-only runs. Verify that reference data is arriving
and saving before starting the full experiment. Do not use simulated ground truth.

1. Warm up the system. Keep the plate, mounting and wind direction fixed. Start
   `wind-tunnel-logger`, select the real ground-truth source and enter the actual
   ambient pressure (Pa) and air temperature (C). With the fan OFF, let the tunnel
   reference finish zeroing.
2. In a separate terminal, start raw logging with a **new** output filename:

   ```bash
   python3 python/logger_200hz.py --port YOUR_PORT --output data/lab_run01.csv
   ```

   `YOUR_PORT` is the Nucleo's serial port (e.g. `COM7` on Windows or
   `/dev/cu.usbmodem...` on macOS). Close Serial Monitor first. Keep the firmware
   headers at `COMP0219_AUTOSTART 0` for this session. If it is streaming, send `x`
   and wait for `STREAM_EXIT` so `LIVE` raw ADC and temperature readings resume.
3. At our logger's `cmd>` prompt send `z`, with the fan OFF, and wait for the
   `ZERO,ADC=...,SIGMA=...` response. Press **Start Logging** in the tutorial.
   Run `z` only once in this recording; a new zero requires a new run.
4. Set approximately 2 m/s, wait for airflow/plate readings to settle, then send:

   ```text
   begin cal speed_2
   ```

   Wait 10 seconds with steady airflow, then send `end`. Repeat at approximately
   3, 4, 6, 8 and 10 m/s with unique labels such as `speed_3` and `speed_10`.
   The label is a name, not a reference measurement: the importer reads the
   actual measured speed from the tutorial CSV. No `p`/`v` commands are needed.
5. Record separate held-out validation windows at approximately 2.5, 5, 7 and
   9 m/s using `begin val check_2_5`, wait 10 seconds, then `end`, etc. Include
   repeated settings and a decreasing-speed pass to check hysteresis. Validation
   windows never contribute to the fitted coefficient. The importer requires at
   least two usable calibration windows and one validation window.
6. Press **Stop & Save** in the tutorial and send `stop` in our logger. Our logger
   saves `data/lab_run01.csv` and `data/lab_run01_windows.csv`. Always send `end`
   before stopping: unfinished windows are saved but rejected by the importer.
7. Fit offline, supplying the **same ambient settings entered in the tutorial**:

   ```bash
   python3 python/calibrate_from_tunnel.py \
     --sensor data/lab_run01.csv \
     --reference "/path/to/team_date_time_vdas.csv" \
     --windows data/lab_run01_windows.csv \
     --ambient-pressure-pa 101325 \
     --reference-temperature-c 20 \
     --mounting-notes "Plate and load-cell mounting description" \
     --firmware-version "Identifier of the firmware you uploaded" \
     --out outputs/lab_run01
   ```

   Replace the pressure/temperature examples with your measured settings. Use a
   **new** output directory. GIGA reference runs also use the reference `_vdas.csv`
   export in the installed v1.0.0 implementation; inspect the files saved by your
   version. The required columns are `timestamp_epoch` and `value_raw_mps`.
8. Review `fig_plateaus.pdf` for settling, drift and unstable flow; review
   `fig_calibration.pdf`, `fig_validation_error.pdf`, `windows_summary.csv` and
   the held-out metrics in `model.json`. No automatic accuracy pass is assumed.
   Baseline-noise calibration points are marked as excluded. Fix poor windows
   or repeat the run before deployment.

   Reference window means are accepted within 2..10 m/s by default. A measured
   edge setting may sit slightly outside that range: for example, explicitly add
   `--min-reference-mps 1.9` to accept a 1.97 m/s window. The fitter keeps 1.97 as
   measured; it does not round or clamp it to 2. The optional
   `--max-reference-mps` sets the upper limit. Both bounds are stored in
   `model.json`; broadening them does not demonstrate accuracy across 2..10 m/s.
9. With the fan OFF, open a new logger session and restore:

   ```bash
   python3 python/logger_200hz.py --port YOUR_PORT \
     --output data/post_calibration.csv \
     --model-file outputs/lab_run01/calibration_restore.txt
   ```

   Send `load`, then `r`, then `q`, waiting for each response. `q` checks zero
   drift without clearing the model. **Do not send `z` after loading**: it erases
   the model. For autonomous assessment, generate the embedded headers:

   ```bash
   python3 python/make_embedded_config.py \
     --model-file outputs/lab_run01/calibration_restore.txt
   ```

   Recompile/upload, close our logger, connect the Nucleo in the tutorial, and
   record a fresh independent test. Embedded firmware automatically starts the
   numeric 200 Hz output. Use the embedded model for this handoff: our logger's
   `stop` exits streaming, and reconnecting may reset a RAM-only model. Run the
   sequence diagnostic separately.

The fitter averages raw ADC, sensor temperature and **unclipped reference speed**
over the same marked steady intervals. It fits the firmware's square-root model
and exports `k ZERO SIGMA SIGN BETA`. It uses the same sign selection and
three-sigma noise deadband as firmware; the final calculations still run entirely
on the Nucleo. No firmware algorithm changes are needed.

Quality checks reject missing/nonfinite data, overlapping/unfinished windows,
multiple zero baselines, backward clocks and simulated reference runs. Each window
needs at least 10 raw sensor and 2 reference samples. Both streams must cover the
window edges to within 1 second, with no internal gap greater than 1 second;
`--max-gap-s` changes that limit if justified by the actual instrument cadence.
Host clocks are shared, but transport delays are unmeasured: use this for steady
calibration, not precise dynamic latency. Inspect the plateau plots even when all
automated checks pass.

The reference uses the tutorial's actual ambient settings. Our model deliberately
keeps the firmware's **101325 Pa density convention** in both offline fitting and
deployment. Beta absorbs a constant pressure difference during calibration;
material atmospheric-pressure changes or mounting changes require recalibration.
Temperature updates density, not load-cell thermal drift. Verify the MCP9808
against a trusted thermometer separately. `model.json` records input and local
firmware source hashes, ambient settings, mounting notes and the host repository
revision. Supply `--firmware-version` to identify what you actually uploaded:
the current serial protocol cannot verify which firmware is running on the board.

For an optional direct on-board fit using a measured speed, our logger now accepts
`speed-p 4.12` and `speed-v 5.00` in **m/s**. Legacy `p`/`v` commands below still
take **Pa** and use the approximate conversion; prefer the measured-reference
workflow above.

### Provisional calibration when the tunnel reference recording is missing

An explicit assumed-speed mapping can replace the recorded reference for a
provisional fit. It contains exactly one `name,assumed_mps` row for every window.
For lab_run06, `data/lab_run06_assumed_speeds.csv` maps speed_10/8/6/4 to
10/8/6/4 m/s. The original window file controls which points are `cal` and `val`.

```bash
python3 python/calibrate_from_tunnel.py \
  --sensor data/lab_run06.csv \
  --windows data/lab_run06_windows.csv \
  --assumed-speeds data/lab_run06_assumed_speeds.csv \
  --out outputs/lab_run06_assumed
```

Use a new output folder on reruns. `--assumed-speeds` and `--reference` cannot be
combined. No reference ambient settings are needed in assumed mode: density
still uses the measured sensor temperature and the same 101325 Pa firmware
convention. Sensor baseline, window coverage, sample count and noise checks
still apply. The script does not infer speeds from names or invent timestamped
reference samples. Missing/extra/duplicate mapping names fail explicitly.

Plots, summaries and `model.json` identify the assumed source. In particular,
reference counts are zero and unknown reference variability/coverage are blank.
`ASSUMED_REFERENCES.txt` records the limitation. The held-out result measures
agreement with the assumed speed, not independently measured tunnel accuracy.
`calibration_constants.txt` contains the four constants for the standalone
speed-only sketch; `calibration_restore.txt` supports the existing load/header
workflow. Review results before updating firmware. Keep the assumption label
with any model or plots used in the report.

### Legacy manual-pressure commands

```bash
python python/logger_200hz.py --port COM7 --output data/lab_run01.csv
```

Close Arduino Serial Monitor. `z` at fan OFF; then set actual measured differential pressures and use `p 3`, `p 5`, `p 10`, `p 22`, `p 38`, `p 60`. Keep `v 8`, `v 15`, `v 30`, `v 49` as independent validation after calibration. `r` and `d` then `q` at fan OFF, save model file. For 200 Hz stage use `j`, `x`, `g` and optionally `phase step`, `pressure 22` annotations. **Manual pressure labels are not timestamp-synchronized truth**.

## Report and grading

- 6-page IEEE paper, stage 1, core 2–10 m/s, dynamic steps and ramps. Record MSE, bias, uncertainty and sensor limitations; at least system diagram + step and ramp plots.
- The project brief says `CubeIDE/PlatformIO` for buildability while the lecturer allowed any IDE in person; attach Arduino sketch and this optional PlatformIO project.
- **Performance is 70%**: official Dwyer/Pitot reference, 200 Hz no drops and actual MSE decide practical performance. The preflight tools are not a substitute for the official grader.
- Keep raw logs, calibration restore text, screenshots, schematics/STL and code version in `supplementary_[TeamName].zip`.

## After TA provides synchronized Pitot ground truth

An **optional** separate script calculates accurate sample-level MSE/Bias/σ only **after** aligning the clocks with a measured common trigger (or official synchronization):

```bash
python python/evaluate_reference.py \
  --sensor data/lab_run01.csv \
  --reference data/TA_pitot.csv \
  --ref-time-col time_s --ref-speed-col speed_mps \
  --ref-time-offset-s 0.000 \
  --out outputs/official
```

The `0.000` offset above is a **placeholder**, not automatically correct. Obtain/reference the true time offset before making latency or MSE claims. Optionally use `--ref-sigma-col sigma_mps` to estimate adjusted RMSE under the IEEE template's stated assumptions.
