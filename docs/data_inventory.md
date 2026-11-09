# Data and result inventory

Raw CSV contents and previously generated result files are preserved byte-for-byte. Original filenames retain experiment IDs and timestamps. Historical JSON paths describe the machine at generation time; they are not executable paths in the current checkout.

| Data | Results | Interpretation |
| --- | --- | --- |
| `data/lab_run03.csv`, `lab_run03_windows.csv`, `T4_20261104_155058_giga_vdas.csv` | `results/lab_run03/` | Recorded reference; stored model uses two calibration windows and one validation window |
| `data/lab_run04.csv`, `lab_run04_windows.csv` | None | Partial session; marker CSV has no completed windows |
| `data/lab_run05.csv`, `lab_run05_windows.csv` | None | Partial session; marker CSV has no completed windows |
| `data/lab_run06.csv`, `lab_run06_windows.csv`, `lab_run06_assumed_speeds.csv` | `results/lab_run06_assumed/` | Real sensor data with assumed reference speeds; not measured reference accuracy |
| Same run06 inputs | `results/lab_run06_diagnostics/` | Raw-sample conversion; not a replay of 200 Hz filtered output |
| `data/preflight_200hz.csv` | None | Preserved preflight log; filename alone does not establish a hardware pass |
| Missing external 2026-11-05 exports | `results/real_20261105_diagnostics/`, `results/real_20261105_zero_corrected/` | Historical comparison and offline correction; full reproduction requires missing original exports |
| `tests/ref_SYNTHETIC.csv`, `tests/sensor_SYNTHETIC.csv` | Software fixtures only | Synthetic data, never experimental evidence |

Stored run03 validation RMSE is 1.747736 m/s for one window. Run06 validation RMSE is 0.486781 m/s against an assumed speed. These are not directly comparable measurements of tunnel accuracy.

The standalone experimental stream sketch uses run06's assumed-speed coefficient, sign, and noise with a different manual zero baseline. Identify the actual firmware used for each recording; host source hashes do not prove what was flashed.

Keep raw logs, markers, calibration provenance, and limitations alongside report figures. Missing external exports, board timing evidence, the report, and mechanical design files must be supplied separately; this repository cleanup does not create them.
