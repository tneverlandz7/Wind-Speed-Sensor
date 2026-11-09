# Repository cleanup

This cleanup preserves wind-speed equations, active calibration constants, serial command names, real raw logs, and experimental result contents.

## Renamed paths

| Original | Current |
| --- | --- |
| `firmware_Arduino/COMP0219_Stage1/` | `firmware/arduino/wind_sensor/` (sketch also renamed to match) |
| `firmware_Arduino/COMP0219_SpeedOnly_Lab03/` | `firmware/arduino/wind_sensor_stream_experimental/` (sketch also renamed to match) |
| `python/analyze.py` | `python/analyze_calibration_points.py` |
| `python/calibrate_from_tunnel.py` | `python/calibrate_sensor.py` |
| `python/check_200hz.py` | `python/check_serial_rate.py` |
| `python/logger_200hz.py` | `python/log_serial.py` |
| `python/make_embedded_config.py` | `python/generate_calibration_header.py` |
| `python/plot_stream_200hz.py` | `python/plot_serial_stream.py` |
| `outputs/lab_run06_diagnostics/plot_calibrated.py` | `python/plot_run06_calibration.py` |
| Remaining experimental `outputs/` contents | `results/` |

Imports, test references, firmware provenance collection, header targets, script defaults, and reproduction paths use the new names. Historical model JSON remains unchanged to preserve hashes and provenance. Main Arduino and PlatformIO firmware remain matching copies for their respective build tools.

## Removed files

- `docs/superpowers/plans/`: obsolete development plans and progress notes.
- `python/demo.py`, `data/demo_SYNTHETIC_DO_NOT_SUBMIT.csv`: standalone synthetic demo generator and generated log.
- `outputs/demo/`, `outputs/official_SYNTHETIC_TEST/`: generated synthetic figures, metrics, and predictions.

Real logs, partial experimental sessions, calibration results, diagnostic plots, and existing tests remain. Synthetic fixtures under tests remain clearly labeled. Original files remain available in Git history.

The README now describes the project; workflow and data inventory carry operating details and evidence limitations. Obsolete Lab03 comments and unused commented-out constants were removed from the experimental stream sketch. Its active values are unchanged; the unexplained manual zero override is documented.

## Verification on 2026-11-09

- All 29 existing tests passed with Python 3.13.5 and MinGW C++ 15.1.0, including the two native firmware checks. On this Windows installation, the matching MinGW bin directory was placed first on PATH to avoid conflicting STM32 toolchain runtime DLLs.
- Both Arduino sketches compiled for `STMicroelectronics:stm32:Nucleo_64:pnum=NUCLEO_F411RE` using the installed STM32 Arduino core 3.0.0. Main sketch: 49,704 bytes flash, 2,784 bytes global RAM. Experimental stream: 25,588 bytes flash, 1,544 bytes global RAM.
- The separate native timing harness passed its simulated 200-slot schedule and restore-command checks.
- Run03 measured-reference and run06 assumed-speed fits reproduced the stored parameters and calibration/validation metrics exactly.
- All 34 retained experimental files matched their original Git blob bytes. CSV and historical result attributes prevent checkout line-ending conversion from breaking provenance hashes.
- All eight general-purpose command-line tools loaded their help after renaming; the header generator wrote matching headers to both build targets. The fixed run06 plot script reproduced its derived outputs, after which the original stored result bytes were restored.
- The reference evaluation tool ran against the labeled synthetic fixtures as a software smoke check; those generated outputs are excluded from the submission archive.

No firmware was uploaded and no hardware timing or wind-tunnel performance was measured during cleanup. PlatformIO itself was not installed in this environment, so its build command was not run; its main source and calibration header match the successfully compiled main Arduino sketch.
