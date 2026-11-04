# Tunnel Reference Calibration Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Calibrate the assembled load-cell airspeed sensor against real reference speeds exported by the installed Wind Tunnel Logger.

**Architecture:** Run the tutorial logger for the tunnel reference only and our logger for the Nucleo, on the same laptop. Join steady time windows offline, fit the existing density-corrected square-root model, and export the existing `k ZERO SIGMA SIGN BETA` restore command. Use the tutorial normally with our board for final independent validation.

**Tech Stack:** Existing Python/numpy/pandas/matplotlib/pyserial and STM32 Arduino C++.

**Spec:** The workflow and decisions below are the proposed design, pending user review. No implementation is included in this document.

## Workflow and decisions

- Keep the installed tutorial package unchanged. Its GUI can record ground truth without student readings; verify this on the actual tunnel before the full run.
- Use one laptop and its host epoch clock for both logs. Each program owns a different device connection. Never connect both programs to the Nucleo simultaneously.
- Record tutorial `timestamp_epoch`, `value_raw_mps`, `pa_raw`, and `pa_corrected`. Use the unclipped speed column as reference; reject simulated runs by default.
- Our existing idle `LIVE` output already includes raw ADC and temperature at approximately 5 Hz, even without a valid model. This is sufficient for steady calibration; retain raw ADC rather than the EMA delta for fitting.
- Warm up the system, fix mounting and wind direction, enter ambient pressure and temperature in the tutorial, and zero both systems with the fan off. Record a quiet baseline and run `z` once before the calibration series. Do not run `z` again midway through a series.
- Suggested calibration plateaus: approximately 2, 3, 4, 6, 8, and 10 m/s. Use actual recorded reference means, not target settings. Allow settling, then explicitly mark a 10-second usable interval per plateau. These durations are proposed starting values to check in the lab.
- Suggested held-out validation plateaus: approximately 2.5, 5, 7, and 9 m/s, with repeated settings and a decreasing-speed pass to expose hysteresis. Exclude these windows from fitting.
- A window manifest stores `name,role,start_epoch,end_epoch`, with role `cal` or `val`. Our logger provides start/end markers and rejects overlapping/nested windows. Read the reference CSV after both logs have been saved.
- Average reference speed, raw ADC and sensor temperature independently over each shared steady interval. Require at least 10 valid sensor readings, at least 2 valid reference readings, and reference coverage reaching within 1 second of each endpoint; reject larger than 1-second reference gaps. Report counts, duration, variability and coverage. These are configurable initial quality limits, not claims about reference sampling rate.
- Produce plateau plots for review before accepting a model; settling, drift, and unstable airflow must be visible. Do not claim precise dynamic alignment from host timestamps.
- Fit `x_i = sqrt(max(0, sign*(mean_adc_i-zero_adc)/rho_i))`, `beta = sum(x_i*v_ref_i)/sum(x_i*x_i)` using calibration windows only. Select sign from the largest absolute calibration delta and exclude signals at/below `3*zero_sigma`. Require at least two useful calibration windows. Score all held-out validation windows with the firmware's noise deadband.
- Keep the firmware's 101325 Pa density convention for both offline fitting and deployment so the existing four-parameter restore interface remains valid. Enter actual ambient pressure in the tutorial reference. The fitted beta absorbs a constant pressure difference during calibration; a materially different ambient pressure later requires recalibration or a future explicit pressure-aware model.
- Temperature corrects air density; this does not calibrate the MCP9808 or compensate load-cell thermal drift. Compare the temperature sensor with a trusted thermometer as a separate check.
- Export model JSON, window summaries, plots, validation metrics and a four-parameter restore text file. Preserve raw files and provenance including pressure/temperature settings, firmware version, and mounting description. Synthetic fixtures are for software checks only.
- Restore via the existing logger `load` command; use `q` for a no-wind drift check without clearing the model. Then close our logger, connect the tutorial to the board, enter `g` beforehand as needed, and collect independent 200 Hz speed-only validation runs. Alternatively embed the model and upload for automatic streaming.

## Global Constraints

- Final firmware output remains one numeric speed in m/s per line at 200 Hz and 115200 baud.
- A 200 Hz stream is not 200 independent load-cell conversions per second.
- Both firmware copies must retain identical calibration behavior.
- Use real tunnel reference data for calibration and reported performance.
- Host time pairing supports steady calibration; USB/device delays remain unmeasured.

## Review Focus

- Simulated or malformed reference input must fail clearly rather than produce a deployable model.
- Missing coverage, timestamp gaps, clock jumps and overlapping windows must be detected.
- Re-zeroing midway through a run must not mix measurements from different baselines.
- Offline prediction must match firmware sign selection, fitting exclusions and noise deadband.
- Independent validation must not influence beta; hardware throughput remains a separate check.

### Task 1: Record raw sensor data and explicit windows

**Files:** Modify `python/logger_200hz.py`; create `tests/test_calibration_logging.py`.

**Interfaces:** Add numeric `host_epoch_s` to each row; write a sibling windows CSV with `name,role,start_epoch,end_epoch`; accept `begin cal NAME`, `begin val NAME`, and `end`.

- [ ] Test epoch timestamps, marker boundaries, overlapping markers, an unfinished window, and rejected `z` while a window is open.
- [ ] Implement marker recording; retain the existing ISO timestamp and relative elapsed time. Preserve logging of uncalibrated LIVE raw ADC/temperature.
- [ ] Add explicit `speed-p MPS` and `speed-v MPS` commands for optional direct firmware capture, leaving legacy pressure commands clearly labeled. The offline workflow does not require p/v captures.
- [ ] Run `python3 -m unittest discover -s tests -p 'test_calibration_logging.py'` and verify pass.

### Task 2: Import reference windows and fit/export the model

**Files:** Create `python/calibrate_from_tunnel.py`, `python/calibration_model.py`, and `tests/test_tunnel_calibration.py`; modify `python/analyze.py` to use shared model math where applicable.

**Interfaces:** CLI `calibrate_from_tunnel.py --sensor SENSOR.csv --reference RUN_vdas.csv --windows WINDOWS.csv --out DIR`; `calibration_model.py` owns density, sign selection, beta fitting and firmware-equivalent prediction. Produce `calibration_restore.txt`, `model.json`, `windows_summary.csv`, plots and held-out metrics.

- [ ] Test recovery of a known coefficient for both ADC signs, baseline noise exclusions, zero output below the deadband, and independent validation outliers leaving beta unchanged.
- [ ] Test invalid/missing columns, nonfinite values, simulated filename rejection, insufficient samples, missing coverage, large gaps, overlapping windows and multiple ZERO records. Reject multiple baselines initially with instructions to split the run.
- [ ] Parse `host_epoch_s` and tutorial `timestamp_epoch` without converting one file to an independently zeroed time axis. Check timestamp order before sorting; reject backward clock jumps.
- [ ] Implement shared-window aggregation and summary/plots; fit only valid calibration windows and report excluded windows with reasons. Fail rather than silently dropping requested validation windows.
- [ ] Write existing-format `k` export and provenance. Make offline analysis honor the same deadband and useful-point rules as firmware; retain support for legacy POINT logs.
- [ ] Run `python3 -m unittest discover -s tests -p 'test_tunnel_calibration.py'` and verify pass; round-trip the export through `make_embedded_config.from_line` and confirm constants.

### Task 3: Document and verify deployment on the real system

**Files:** Modify `README.md`; inspect `firmware/src/main.cpp`, both `calibration_config.h` copies and `python/make_embedded_config.py`. No firmware algorithm change is planned unless verification exposes a mismatch.

- [ ] Document device ownership, reference-only tutorial capture, zeroing, markers, CSV import, restore, and held-out validation. Record the ambient-pressure convention explicitly.
- [ ] Add/check a meaningful firmware-versus-Python prediction fixture for positive and negative signs and the noise threshold; use the existing mock Arduino interfaces where practical.
- [ ] Bench-check recording and export with clearly labeled synthetic input; never publish those metrics as real calibration results.
- [ ] In the lab, confirm reference-only saving works, record real plateaus, inspect stability and held-out residuals, restore the model and check zero drift.
- [ ] Generate both embedded headers only after reviewing real calibration, upload, and verify no-wind output and a known reference speed.
- [ ] Run the existing 200 Hz sequence diagnostic and tutorial numeric-stream capture. Report measured results and any systematic speed-dependent error; do not introduce a more complex fit without that evidence.

## Completion evidence

Deliver the real source logs, reviewed plateau summaries/plots, a reproducible model export, independent validation errors and measured stream-throughput results. Software checks alone cannot establish calibration accuracy or hardware readiness.
