# COMP0219 wind-speed sensor

A contact-based airspeed sensor built around a Nucleo-F411RE, a load cell with a
Weight-I2C interface, and an MCP9808 temperature sensor. Airflow acts on a plate;
the board converts the measured load into an estimated airspeed using a calibrated
square-root model. The intended operating range is **2–10 m/s**.

The board performs the real-time estimation and sends **one numeric airspeed in
m/s per line at a scheduled 200 Hz**, using **115200 baud**. Calibration fitting
and analysis of recorded tests run offline in Python.

## Which Arduino sketch to use

| Purpose | Sketch | Behaviour |
| --- | --- | --- |
| Record raw calibration data, zero the sensor, or inspect diagnostics | [COMP0219_Stage1.ino](firmware_Arduino/COMP0219_Stage1/COMP0219_Stage1.ino) | Accepts serial commands. Its checked-in header has `COMP0219_AUTOSTART=0` and placeholder coefficients. |
| Send numeric wind speed to Wind Tunnel Logger | [COMP0219_SpeedOnly_Lab03.ino](firmware_Arduino/COMP0219_SpeedOnly_Lab03/COMP0219_SpeedOnly_Lab03.ino) | Starts streaming automatically after initialization; accepts no commands and needs no calibration header. |

Despite its **Lab03 filename and older header comments**, the speed-only sketch's
active constants use the **run06 fit with a later zero-offset adjustment**:

```cpp
const float ZERO_ADC = 8837482.0f;
const float ZERO_SIGMA_ADC = 29.83f;
const int WIND_SIGN = -1;
const float BETA = 0.03077113727f;
```

The original run06 fit used `ZERO_ADC=8840126`; the saved calibration model still
contains that original baseline. Updating a saved model or Stage1's header does
**not** automatically update the standalone speed-only sketch.

This checkout contains the Arduino sketches. The optional PlatformIO `firmware/`
project mentioned in older documentation is not present.

## Hardware and real-time processing

| Connection or setting | Value in the firmware |
| --- | --- |
| Board | Nucleo-F411RE |
| I2C SDA / SCL | PB9 / PB8 |
| I2C clock | 100 kHz |
| Weight-I2C address / raw register | `0x26` / `0x00` |
| MCP9808 address / temperature register | `0x18` / `0x05` |
| Serial output | 115200 baud, three decimal places, newline terminated |

Connect both modules to the shared I2C bus and common ground, with power supplied
according to the module's requirements.

The following timings apply to Stage1's streaming modes and the speed-only sketch:

| Operation | Scheduled interval | Rate |
| --- | --- | --- |
| Poll the load interface | 12.5 ms | Up to 80 polls/s |
| Poll temperature | 500 ms | Approximately 2 polls/s |
| Output the latest airspeed estimate | 5 ms | 200 lines/s |

**200 Hz output does not mean 200 independent load measurements per second.**
The board reuses the latest filtered load and temperature between sensor polls.
Polling at 80 Hz also does not prove that the interface supplies 80 distinct ADC
conversions per second. Outside streaming mode, Stage1 prints raw `LIVE` readings
at approximately **5 Hz**.

```text
Load ADC → EMA → subtract zero and apply wind sign → noise deadband ┐
                                                                 ├→ airspeed → serial output
Temperature → air-density estimate ───────────────────────────────┘
```

The exponential moving average (EMA) is applied to the load reading:

```text
y[n] = 0.25 × x[n] + 0.75 × y[n−1]
```

It starts at the first valid ADC reading. It smooths noise and adds delay. Its
physical response depends on the successful update rate; the same coefficient
in the slower `LIVE` mode does not produce the same time response as streaming.

The prediction uses:

```text
rho = 101325 / (287.05 × (temperature_C + 273.15))
q   = WIND_SIGN × (filtered_ADC − ZERO_ADC)

if q <= 3 × ZERO_SIGMA_ADC:
    speed = 0
else:
    speed = BETA × sqrt(q / rho)
```

`ZERO_ADC` is the no-wind baseline, `ZERO_SIGMA_ADC` its noise standard deviation,
`WIND_SIGN` defines the load direction, and `BETA` is the fitted scale coefficient.
The coefficient incorporates the plate, mounting and load sensitivity; changes to
that assembly require a new calibration. Temperature adjusts air density; it does
not provide separate load-cell thermal-drift compensation. Firmware density uses
101325 Pa, so a material pressure change also warrants recalibration.

Serial output takes priority over I2C polling. The scheduler skips missed output
slots instead of replaying them in a burst. Before a valid load and temperature
are available, the numeric-output modes report zero; subsequent failed reads hold
the last successful measurement. CPU utilisation and worst-case execution time
have not been established by these logs.

## Recorded calibration runs

| Dataset | Test setup | Reference used in the saved fit | Saved results |
| --- | --- | --- | --- |
| `lab_run03` | Wooden wind tunnel used for the earlier calibration | Recorded tunnel speeds from `data/T4_20261104_155058_giga_vdas.csv` | [outputs/lab_run03](outputs/lab_run03) |
| `lab_run06` | Wind tunnel used for the final demonstration | Assumed window speeds; the tunnel reference recording was missing | [outputs/lab_run06_assumed](outputs/lab_run06_assumed) |


For run06, the assumed means are **10, 8 and 6 m/s** for calibration, with **4 m/s**
held out. The original saved model predicts about **3.513 m/s** for that validation
window, an error of **−0.487 m/s relative to the assumed speed**. This is not an
independent measurement of accuracy against the tunnel reference. The mapping is
stored in [lab_run06_assumed_speeds.csv](data/lab_run06_assumed_speeds.csv).

The saved model files preserve the original fits. In particular, run06 plots made
from that model use the original zero, not the later adjustment in the current
speed-only sketch.

## Software setup

Run commands from the repository root. The examples below use macOS/Linux shell
syntax; on Windows use the Python launcher and serial port appropriate to that
installation.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r python/requirements.txt
```

Use Arduino IDE with STM32 board support and select **Nucleo-F411RE**. Open the
chosen `.ino` in its matching folder. Keep Stage1's `calibration_config.h` beside
its sketch.

Only one application can use the Nucleo serial port at a time. Close Arduino
Serial Monitor before connecting either Python or Wind Tunnel Logger.

## Run the numeric-output sketch

1. Upload `firmware_Arduino/COMP0219_SpeedOnly_Lab03/COMP0219_SpeedOnly_Lab03.ino`.
2. Allow its initialization delay of approximately 1.2 s. It streams automatically;
   do not send `g`, `begin`, or other commands to this sketch.
3. Connect the board as the student sensor in Wind Tunnel Logger at 115200 baud.
   Every line is a numeric speed, for example `4.327`, with no units or header.
4. Check the output with no wind and at known tunnel settings before relying on
   the embedded coefficients for a new setup.

## Record a new calibration

Use **Stage1**, with `COMP0219_AUTOSTART=0`, for this workflow. Use Wind Tunnel
Logger for the measured reference and `python/logger_200hz.py` for raw board data,
on the **same computer**. During calibration, leave the Nucleo disconnected from
Wind Tunnel Logger's student connection; our Python logger owns that port.

1. Keep the plate and mounting fixed. With the fan off, allow the tunnel reference
   to zero and verify that its real measurements are arriving.
2. Start our logger in a terminal, using a new filename:

   ```bash
   python3 python/logger_200hz.py \
     --port /dev/cu.usbmodem103 \
     --output data/lab_run07.csv
   ```

   Replace `/dev/cu.usbmodem103` with the board's current port, such as `COM7` on
   Windows. The example filename is also replaceable; existing logs are not
   overwritten.
3. At the Python logger's **`cmd>` prompt**, send `z`. Wait for the approximately
   five-second no-wind capture and its `ZERO,ADC=...,SIGMA=...` response. Start
   saving the reference recording in Wind Tunnel Logger before the speed windows.
4. Set a tunnel speed and wait for it to stabilise. At `cmd>`, send:

   ```text
   begin cal speed_2
   ```

   Hold the setting steady for about 10 s, then send:

   ```text
   end
   ```

   Repeat at several speeds across the intended range, using unique names such
   as `speed_4`, `speed_6`, `speed_8` and `speed_10`. The name is a label: in measured
   reference mode, the actual reference mean comes from the tunnel CSV.
5. Record separate stable validation windows using `begin val check_5`, followed
   by `end`. At least **two usable calibration windows and one independent
   validation window** are required. Use additional speeds and repeat settings
   where possible; validation windows are excluded from fitting.
6. Finish the last window with `end`, stop and save the tunnel recording, then
   send `stop` at `cmd>` to close our logger.

`begin`, `end` and `stop` are **Python logger commands**. Enter them at `cmd>`, not
in Arduino Serial Monitor or directly in the shell. If the board replies
`Unknown command. Send h.`, the window command has reached the firmware instead
of the Python logger.

`end` only closes a marked window: raw recording continues. `stop` ends the logger.
To record again, restart the logger with a new output filename. A fresh offline
calibration recording needs its own no-wind `z` capture.

### What the two CSV files contain

- `data/lab_run07.csv`: continuous sensor records, including raw ADC, temperature,
  host timestamps and the `ZERO` message.
- `data/lab_run07_windows.csv`: only the names, roles and start/end epoch times:

  ```csv
  name,role,start_epoch,end_epoch
  speed_2,cal,1793270304.308664,1793270310.54037
  ```

The windows file contains **markers**, not sensor values. The fitter selects raw
sensor samples and measured reference samples within each interval
`start_epoch <= timestamp < end_epoch`, then averages each stream separately.
Different sample rates are supported; it does not need a one-to-one row match.

## Fit the calibration offline

With both recordings saved, run:

```bash
python3 python/calibrate_from_tunnel.py \
  --sensor data/lab_run07.csv \
  --reference "/path/to/tunnel_run_vdas.csv" \
  --windows data/lab_run07_windows.csv \
  --ambient-pressure-pa 101325 \
  --reference-temperature-c 20 \
  --mounting-notes "Describe the plate and mounting used" \
  --firmware-version "Identify the uploaded sketch" \
  --out outputs/lab_run07
```

Replace the paths and ambient settings with those actually used in Wind Tunnel
Logger. The reference CSV must contain **`timestamp_epoch` and `value_raw_mps`**;
the recorded `_vdas.csv` exports used here have that format. Use a **new output
directory** on every fit.

The fitter uses the `ZERO` baseline, window-mean raw ADC and sensor temperature,
and reference window means. It selects the wind sign and fits a positive scale
coefficient with no additional intercept. Validation points do not influence the
fit. Each window needs at least 10 sensor samples and, in measured mode, two
reference samples. Default checks allow at most a one-second internal gap or
uncovered edge. Inspect the plots even if these checks pass.

Reference window means must be within 2–10 m/s by default. For a genuinely
measured boundary value just below 2 m/s, an explicit `--min-reference-mps 1.9`
can be appropriate. This retains the measured value rather than rounding or
clamping it. Run03 was fitted with that lower bound.

Review these exports before updating firmware:

| Export | Purpose |
| --- | --- |
| `model.json` | Coefficients, validation errors and input provenance |
| `windows_summary.csv` | Window means, sample counts, predictions and errors |
| `fig_plateaus.pdf` | Check stability within each window |
| `fig_calibration.pdf` / `fig_validation_error.pdf` | Inspect the fit and held-out errors |
| `calibration_restore.txt` | Stage1 command: `k ZERO_ADC SIGMA SIGN BETA` |
| `calibration_constants.txt` | Four constants for a standalone speed-only sketch |

### Reproduce the original run06 assumed-speed fit

Because the run06 reference recording is missing, its provisional calibration
uses an explicit mapping rather than fabricated reference samples:

```bash
python3 python/calibrate_from_tunnel.py \
  --sensor data/lab_run06.csv \
  --windows data/lab_run06_windows.csv \
  --assumed-speeds data/lab_run06_assumed_speeds.csv \
  --out outputs/lab_run06_refit
```

The mapping must have exactly one `name,assumed_mps` entry for every window.
`--assumed-speeds` and `--reference` are mutually exclusive. These exports include
`ASSUMED_REFERENCES.txt`; their errors measure agreement with the assumptions,
not independently measured tunnel accuracy.

## Apply a new calibration

For the **speed-only sketch**, replace its active `ZERO_ADC`, `ZERO_SIGMA_ADC`,
`WIND_SIGN` and `BETA` definitions with those in the new fit's
`calibration_constants.txt`, then recompile and upload. Do not edit only the
commented-out wooden-tunnel values. Recheck the no-wind zero and known speeds.
Changing the baseline changes estimates throughout the range, especially at low
speeds; it is not just a display adjustment.

For **Stage1**, restore coefficients in a logger session:

```bash
python3 python/logger_200hz.py \
  --port /dev/cu.usbmodem103 \
  --output data/post_calibration.csv \
  --model-file outputs/lab_run07/calibration_restore.txt
```

At `cmd>`, send `load`, then `r` to inspect the model and `q` for a no-wind drift
check. Wait for each response. **Do not send `z` after restoring:** it clears the
model. Send `g` to stream numeric speed and `x` to return to diagnostics.
A restored model is in RAM and is lost on reset.

Stage1 can also start automatically if its `calibration_config.h` has
`COMP0219_AUTOSTART=1` and the four `COMP0219_SAVED_*` macros populated from the
chosen model. Recompile and upload after editing the header; use
`COMP0219_AUTOSTART=0` again for raw calibration sessions.

**Current helper limitation:** `python/make_embedded_config.py` expects both
`firmware/src/` and the Arduino Stage1 folder. Since `firmware/src/` is absent in
this checkout, the helper fails here; edit Stage1's header directly instead.
It never updates the standalone speed-only sketch.

## Commands and units

| Where | Command | Meaning |
| --- | --- | --- |
| Python `cmd>` | `begin cal NAME` / `begin val NAME` | Start a steady measurement window |
| Python `cmd>` | `end` / `stop` | Close the window / stop recording |
| Python `cmd>` | `load` | Send the selected restore file to Stage1 |
| Python `cmd>` | `speed-p 4.12` / `speed-v 5.00` | Direct on-board calibration / validation using measured **m/s** |
| Python `cmd>` | `p 3` / `v 8` | Legacy inputs in **Pa**, converted using `10 × sqrt(Pa/60)` |
| Stage1, directly or through our logger | `z` | Capture the no-wind baseline and clear the model |
| Stage1, directly or through our logger | `r` / `d` / `q` | Report / export captures / check zero drift |
| Stage1, directly or through our logger | `g` / `j` / `x` | Numeric 200 Hz stream / sequence diagnostic stream / exit stream |
| Stage1, direct serial only | `p 4.12` / `v 5.00` | Direct calibration / validation using **m/s**, not Pa |

Prefer the measured-reference window workflow. The legacy pressure conversion
is an assumption, not a substitute for recorded tunnel speeds. The standalone
speed-only sketch does not process any of these commands.

## Recorded test results and figures

The later `Team_4_log1_20261105_102850` and `Team_4_log2_20261105_103115` tests are
separate from the run03/run06 raw calibration recordings. Their existing aligned
CSV pairs give:

| Test | Aligned pairs | RMSE (m/s) | Mean signed error, board − reference (m/s) |
| --- | --- | --- | --- |
| Run 1 | 514 | 0.447 | +0.330 |
| Run 2 | 474 | 0.731 | +0.406 |

These comparisons use the supplied alignment, without an additional baseline,
gain or timing correction. The reference rate is approximately 4 Hz, whereas the
student numeric output is approximately 200 Hz.

The current report figures are:

- [Step responses, both runs](outputs/team4_dynamic_analysis/step_response_both_runs.png)
  ([SVG](outputs/team4_dynamic_analysis/step_response_both_runs.svg)): selected
  rising transitions in the 20–80 s portions. Annotated rise times span
  **1.48–5.05 s**; normalised 50% crossing differences span **−0.19 to +0.07 s**.
- [Ramp responses, both runs](outputs/team4_dynamic_analysis/ramp_response_both_runs.png)
  ([SVG](outputs/team4_dynamic_analysis/ramp_response_both_runs.svg)): annotations
  now measure the **falling half**, with 90–10% fall times of **7.49 s** and
  **3.88 s**, and 50% crossing differences of **+0.20 s** and **−0.11 s**.

Each trace uses its own endpoints for normalisation. Positive crossing difference
means the board crosses later; negative means an apparent lead. Reference samples
are about 0.25 s apart, so the smaller interpolated offsets do not establish a
resolved physical latency. The measured transition times include the tunnel's
changing airflow, rather than measuring intrinsic sensor response time. Persistent
steady differences are consistent with calibration bias; the Run 2 end-of-recording
zero-versus-approximately-2 m/s disagreement has no established cause from these
logs alone.

Detailed values are in `transition_metrics.csv` and `final_pulse_fall_metrics.csv`
under [outputs/team4_dynamic_analysis](outputs/team4_dynamic_analysis). The older
`final_pulse_metrics.csv` contains the original **rising-half** measurements;
`summary_metrics.csv` covers a broader set of transitions than the four annotated
step rises. Do not interchange their ranges or averages.

## Analysis tools and reproducibility

| Tool or artifact | Use |
| --- | --- |
| `python/calibration_model.py` | Shared density, prediction, fit and scoring functions |
| `python/analyze.py` | Analyse legacy `POINT` captures from on-board calibration |
| `python/plot_stream_200hz.py` | Plot streams against manual labels; those labels do not establish dynamic timing |
| `python/evaluate_reference.py` | Compare our logger's `STREAM` rows with an external reference using an explicitly supplied time offset |
| `python/correct_zero_offset.py` | Offline correction of a known false-zero speed in Wind Tunnel Logger exports |
| `outputs/team4_dynamic_analysis/analyse_runs.py` | Recalculate the broader descriptive dynamics analysis |
| `outputs/team4_dynamic_analysis/plot_annotated_sections.py` | Regenerate the current combined step/ramp figures and final-pulse metrics |
| `outputs/lab_run03/calibrated_wind_speed.png` | Original run03 model applied to recorded raw samples |
| `outputs/lab_run06_diagnostics/calibrated_wind_speed.png` | Original run06 model applied to recorded raw samples, with assumed window speeds |

The raw-calibration time-series plots apply the saved model **without adding a
software EMA**. The approximately 5 Hz raw logs cannot reconstruct the exact
streaming EMA history or fast mechanical motion.

The earlier offline zero correction uses
`corrected_speed = sqrt(max(0, reported_speed^2 − 1.442^2))`, based on the confirmed
initial no-wind reading and approximately constant density. Its results are in
[outputs/real_20261105_zero_corrected](outputs/real_20261105_zero_corrected).
Running that script does not change firmware coefficients or repair scale errors.

Some saved provenance files and plotting scripts contain absolute paths from the
recording computer. The original later test exports are outside this repository.
To reproduce the dynamics plots elsewhere, obtain those CSVs, update `SOURCE` in
`analyse_runs.py`, rerun that analysis, then run `plot_annotated_sections.py`.
Preserve original data and distinguish measured references from assumptions.
`outputs/demo/` contains synthetic demonstration results and is not experimental
evidence.

## Check serial output rate

Use Stage1 for the sequence diagnostic; the speed-only sketch cannot enter `j`:

```bash
python3 python/check_200hz.py \
  --port /dev/cu.usbmodem103 \
  --seconds 12 \
  --output data/serial_rate_debug.csv
```

The check sends `j`, records sequence numbers, checks for gaps and estimates host
throughput, then sends `x`. It accepts 195–205 lines/s with no missing sequence
numbers. Host arrivals include USB and operating-system buffering, so this check
does not establish exact device timing, fresh ADC rate or airspeed accuracy.
