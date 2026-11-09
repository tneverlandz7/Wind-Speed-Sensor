# Wind Speed Sensor — COMP0219 Stage 1

A contact-based wind-speed sensor using a load cell and plate, HX711 Weight-I2C interface, MCP9808 temperature sensor, and STM32 Nucleo-F411RE. The MCU estimates speed; Python records data, fits calibration parameters, and produces plots.

Target range: 2–10 m/s. Assessment output: one numeric speed in m/s per line at 115200 baud, scheduled every 5 ms (200 Hz). **Output rate does not mean 200 independent sensor measurements per second.** Verify timing and accuracy on the actual assembly.

## Repository layout

| Path | Purpose |
| --- | --- |
| `firmware/src/` | Main PlatformIO firmware |
| `firmware/platformio.ini` | Nucleo-F411RE build configuration |
| `firmware/arduino/wind_sensor/` | Same main firmware for Arduino IDE; calibration and diagnostics |
| `firmware/arduino/wind_sensor_stream_experimental/` | Standalone output experiment with separate provisional constants |
| `python/` | Recording, calibration, evaluation, and plotting tools |
| `data/` | Original experimental logs, window markers, and assumed-speed mapping |
| `results/` | Calibration results, diagnostics, and offline zero correction |
| `tests/` | Python tests, native C++ mocks, and labeled synthetic fixtures |
| `docs/` | Hardware diagram, workflow, data inventory, and cleanup notes |

## Build and run

Install dependencies from the repository root:

```sh
python -m pip install -r python/requirements.txt
```

For Arduino IDE, open `firmware/arduino/wind_sensor/wind_sensor.ino`, select Nucleo-F411RE with the STM32 Arduino core installed, then compile and upload. Keep the sketch filename identical to its containing directory.

For PlatformIO Core:

```sh
pio run --project-dir firmware
pio run --project-dir firmware --target upload
```

Both main-firmware headers initially have `COMP0219_AUTOSTART=0` and placeholder calibration constants. Follow the [operating workflow](docs/workflow.md) to measure and embed a model. The experimental stream sketch has separate constants and is not updated by the header generator.

Close Serial Monitor before opening a serial tool; replace `COM7` with the actual port:

```sh
python python/log_serial.py --port COM7 --output data/new_session.csv
python python/check_serial_rate.py --port COM7 --seconds 12 --output data/new_rate_check.csv
```

The rate check uses diagnostic mode `j`, which needs no calibration. It measures host throughput and sequence continuity, not ADC conversion rate or precise timer jitter.

## Python tools

| Script | Purpose |
| --- | --- |
| `log_serial.py` | Record readings, commands, output streams, and steady-window markers |
| `check_serial_rate.py` | Check throughput and missing sequence numbers |
| `calibrate_sensor.py` | Fit steady-window calibration from measured or explicitly assumed speeds |
| `calibration_model.py` | Shared density, fitting, deadband, prediction, and error calculations |
| `generate_calibration_header.py` | Write both main-firmware headers from a saved restore command |
| `analyze_calibration_points.py` | Analyze on-board POINT captures and manual reference annotations |
| `plot_serial_stream.py` | Plot output streams with manual annotations |
| `evaluate_reference.py` | Compare output with a separately recorded, time-aligned reference |
| `correct_zero_offset.py` | Apply an explicitly supplied offline zero-speed correction |
| `plot_run06_calibration.py` | Reproduce the run06 raw-sample plot from its existing assumed-speed model |

Use `--help` for script arguments, except `plot_run06_calibration.py`, which is a fixed historical reproduction script.

## Results and limitations

Read the [data inventory](docs/data_inventory.md) before selecting report figures.

- Run03 uses a recorded reference; its single validation window has RMSE about **1.748 m/s**. This does not establish acceptable accuracy across the target range.
- Run06 calibration uses assumed window speeds, not a recorded reference. Its errors describe agreement with those assumptions.
- The experimental stream sketch uses a manual zero override of `8837482`, versus the run06 model baseline `8840126`. The repository does not document a measurement supporting the override. Its coefficient, direction, and noise match the assumed-speed model.
- The 2026-11-05 correction is offline post-processing; the original external exports are missing. It is not part of the deployed firmware.
- Manual annotations and host timestamps alone do not establish precise dynamic latency. Synthetic test fixtures are not experimental evidence.

## Verification

```sh
python -m unittest discover -s tests -v
```

Two tests require a native `c++` compiler on PATH and otherwise skip. Arduino/Wire mocks do not replace an STM32 build, upload, or wind-tunnel test. See [cleanup notes](docs/cleanup_notes.md) for renamed paths and preserved provenance.
