# Execution record: 2026-10-28-tunnel-calibration.md

- Implementing the approved workflow in the user's current checkout; no checkout,
  merge, commit, installed tutorial modification or hardware upload is performed.
- Task 1: complete. Added shared epoch/ISO timestamps, persisted complete and
  unfinished windows, protected active windows and direct measured-speed commands.
  Logging tests observed failing before implementation, then passing (4 tests).
- Task 2: complete. Added CSV/window validation, steady averages, shared model math,
  reference importer, provenance, plots, held-out metrics and restore export.
  Import/model tests observed failing before implementation, then passing (6 tests).
- Ruling: require ambient pressure and reference temperature as CLI arguments so
  recorded provenance reflects explicit tutorial settings instead of invented defaults.
- Ruling: apply the one-second coverage/gap check to both streams; sensor outages
  should not silently produce a calibration even when reference coverage is good.
- Ruling: require a new output directory and refuse overwriting existing raw logs;
  prevents a failed rerun from appearing to have a valid old export.
- Task 3: software work complete; hardware steps pending real tunnel access. Added
  lab instructions and compiled native fixture comparing Python against the actual
  firmware fit and deadband for both signs. The complete initial suite passed
  (11 tests). No production firmware change was required.
- Independent review completed. Corrected the tutorial handoff instructions to
  require embedded autostart: normal logger stop exits streaming. Clarified that
  the repository revision is host provenance, not proof of the uploaded firmware;
  added optional firmware-version notes and local firmware source hashes.
- Added command-level serial mocks proving uncalibrated raw ADC/temperature
  recording, active-window protection and measured-speed reference labels.
  Added CLI export/rerun checks and legacy reference-label tests. Final suite:
  17 tests passed, including native firmware math compilation/comparison.
- Native timing/restore simulation and legacy synthetic analysis also passed;
  these are software checks only, not real calibration/performance evidence.
- Remaining: actual lab capture/validation/upload/throughput measurements (cannot
  be established here). Real calibration headers remain unchanged placeholders.
