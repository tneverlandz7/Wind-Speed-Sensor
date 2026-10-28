# COMP0219 Stage 1: HX711 I2C + MCP9808 / 200 Hz output

**Goal:** contact-based airspeed, 2–10 m/s; Nucleo-F411RE computes airspeed and streams **one ASCII floating-point airspeed (m/s) per line at 200 Hz, 115200 baud** in final assessment mode. Arduino IDE is acceptable *per the lecturer's verbal confirmation*. A buildable optional PlatformIO target is also supplied.

**Status:** firmware source passes a C++ syntax check with mock Arduino/Wire interfaces. **It has not been tested on this exact user's board or wind tunnel. Do not claim a 200 Hz pass before running the hardware sequence diagnostic.** Python analysis passed with explicitly synthetic demo data.

## Files

- `firmware_Arduino/COMP0219_Stage1/COMP0219_Stage1.ino` (+ `calibration_config.h`): Arduino IDE version.
- `firmware/` (`platformio.ini`, `src/main.cpp`, `src/calibration_config.h`): optional VS Code/PlatformIO build.
- `python/logger_200hz.py`: timestamps and logs real UART data and manual pressure labels; `p`/`v` arguments are in **Pa**, not m/s.
- `python/check_200hz.py`: 200 Hz **line transfer** and sequence continuity test (`j` diagnostic mode, even before calibration).
- `python/analyze.py`: stationary wind tunnel fit / calibration plots / validation metrics (for real runs, needs POINT records).
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
