"""Fit steady-window calibration from measured reference or explicit assumed means.

No serial connection is opened. Run only after saving both logs and windows.
"""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from calibration_model import density, fit_model, predict, score, validate_reference_range
from generate_calibration_header import from_line


def read_csv(path, required):
    frame = pd.read_csv(path)
    missing = set(required) - set(frame.columns)
    if missing:
        raise ValueError(f'{path}: missing columns {sorted(missing)}')
    if frame.empty:
        raise ValueError(f'{path}: no rows')
    return frame


def numeric(frame, columns, label):
    for column in columns:
        frame[column] = pd.to_numeric(frame[column], errors='coerce')
        if not np.isfinite(frame[column]).all():
            raise ValueError(f'{label}: {column} must contain finite numbers')


def check_clock(frame, column, label):
    numeric(frame, [column], label)
    if (frame[column].diff().dropna() < 0).any():
        raise ValueError(f'{label}: clock moved backward or rows are out of order; do not independently re-zero timestamps')


def read_windows(path):
    windows = read_csv(path, ['name', 'role', 'start_epoch', 'end_epoch'])
    if windows[['start_epoch', 'end_epoch']].isna().any().any():
        raise ValueError('Window is unfinished: every begin requires end')
    numeric(windows, ['start_epoch', 'end_epoch'], 'windows')
    if windows.name.isna().any() or windows.name.astype(str).str.strip().eq('').any() or windows.name.duplicated().any():
        raise ValueError('Window names must be nonempty and unique')
    if not windows.role.isin(['cal', 'val']).all():
        raise ValueError('Window role must be cal or val')
    if (windows.end_epoch <= windows.start_epoch).any():
        raise ValueError('Window end must be after start')
    windows = windows.sort_values('start_epoch').reset_index(drop=True)
    if (windows.start_epoch.iloc[1:].to_numpy() < windows.end_epoch.iloc[:-1].to_numpy()).any():
        raise ValueError('Measurement windows overlap')
    if (windows.role == 'cal').sum() < 2 or (windows.role == 'val').sum() < 1:
        raise ValueError('Need at least two calibration windows and one independent validation window')
    return windows


def baseline(sensor, first_window):
    zero_rows = sensor[sensor.raw_line.fillna('').astype(str).str.startswith('ZERO,')]
    if len(zero_rows) != 1:
        raise ValueError('Need exactly one ZERO record. Run z before measurements; split runs with multiple baselines')
    row = zero_rows.iloc[0]
    if row.host_epoch_s >= first_window:
        raise ValueError('ZERO must precede all windows')
    fields = dict(piece.split('=', 1) for piece in row.raw_line.split(',')[1:] if '=' in piece)
    try:
        zero, sigma = float(fields['ADC']), float(fields['SIGMA'])
    except (KeyError, ValueError) as exc:
        raise ValueError('ZERO record must contain numeric ADC and SIGMA') from exc
    if not np.isfinite([zero, sigma]).all() or sigma < 0:
        raise ValueError('ZERO parameters must be finite, with nonnegative SIGMA')
    # Reboots/commands between captures would otherwise invalidate the assumed baseline.
    after_zero = sensor[sensor.host_epoch_s > row.host_epoch_s]
    if after_zero.raw_line.fillna('').str.contains('STM32 wind tunnel|RESTORE_OK', regex=True).any():
        raise ValueError('Board restarted or model restored after ZERO; begin a new run')
    if 'command' in after_zero:
        commands = after_zero.command.fillna('').astype(str)
        if commands.str.match(r'^(z|load|k)(\s|$)').any():
            raise ValueError('Baseline changed after ZERO; begin a new run')
    return zero, sigma


def window_samples(frame, time_column, window, minimum, max_gap_s, label):
    rows = frame[(frame[time_column] >= window.start_epoch) & (frame[time_column] < window.end_epoch)].copy()
    if len(rows) < minimum:
        raise ValueError(f'{window["name"]}: need >={minimum} {label} samples, got {len(rows)}')
    times = rows[time_column].to_numpy()
    if times[0] - window.start_epoch > max_gap_s or window.end_epoch - times[-1] > max_gap_s:
        raise ValueError(f'{window["name"]}: {label} does not cover window endpoints')
    if len(times) > 1 and np.diff(times).max() > max_gap_s:
        raise ValueError(f'{window["name"]}: {label} timestamp gap exceeds {max_gap_s:g} s')
    return rows


def provenance(path):
    path = Path(path)
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def read_assumed_speeds(path, windows):
    mapping = read_csv(path, ['name', 'assumed_mps'])
    if mapping.name.isna().any() or mapping.name.duplicated().any():
        raise ValueError('Assumed-speed names must be nonempty and unique')
    numeric(mapping, ['assumed_mps'], 'assumed speeds')
    if (mapping.assumed_mps <= 0).any():
        raise ValueError('Assumed speeds must be positive')
    missing = set(windows.name) - set(mapping.name)
    extra = set(mapping.name) - set(windows.name)
    if missing or extra:
        raise ValueError(f'Assumed-speed mapping must match windows exactly; missing={sorted(missing)}, extra={sorted(extra)}')
    return mapping.set_index('name').assumed_mps.to_dict()


def calibrate(sensor_path, reference_path, windows_path, out=None, *, ambient_pressure_pa=None,
              reference_temperature_c=None, max_gap_s=1., mounting_notes='', firmware_version='not supplied',
              min_reference_mps=2., max_reference_mps=10., assumed_speeds_path=None):
    if (reference_path is None) == (assumed_speeds_path is None):
        raise ValueError('Supply exactly one measured reference CSV or assumed-speed mapping')
    assumed = assumed_speeds_path is not None
    validate_reference_range(min_reference_mps, max_reference_mps)
    if not np.isfinite(max_gap_s) or max_gap_s <= 0:
        raise ValueError('Maximum gap must be finite and positive')
    if not assumed and (ambient_pressure_pa is None or reference_temperature_c is None
                        or not np.isfinite([ambient_pressure_pa, reference_temperature_c]).all()
                        or ambient_pressure_pa <= 0 or not -40 <= reference_temperature_c <= 125):
        raise ValueError('Measured reference requires valid --ambient-pressure-pa and --reference-temperature-c')
    if not assumed and re.search(r'(?:^|[_\W])(simulated|synthetic)(?:[_\W]|$)', Path(reference_path).stem, re.I):
        raise ValueError('Cannot calibrate from simulated/synthetic reference runs')
    sensor = read_csv(sensor_path, ['host_epoch_s', 'kind', 'raw_line', 'raw_adc', 'temperature_c'])
    reference = None
    if not assumed:
        reference = read_csv(reference_path, ['timestamp_epoch', 'value_raw_mps'])
        if 'device_name' in reference and reference.device_name.fillna('').str.contains('simulated|synthetic', case=False).any():
            raise ValueError('Cannot calibrate from simulated/synthetic reference runs')
        check_clock(reference, 'timestamp_epoch', 'reference')
        numeric(reference, ['value_raw_mps'], 'reference')
    check_clock(sensor, 'host_epoch_s', 'sensor')
    windows = read_windows(windows_path)
    assumed_speeds = read_assumed_speeds(assumed_speeds_path, windows) if assumed else None
    zero, sigma = baseline(sensor, windows.start_epoch.min())
    live = sensor[sensor.kind == 'LIVE'].copy()
    if live.empty:
        raise ValueError('No LIVE sensor readings; record raw ADC/temperature before g mode')
    if 'device_ms' in live:
        valid_device = pd.to_numeric(live.device_ms, errors='coerce').dropna()
        if (valid_device.diff().dropna() < 0).any():
            raise ValueError('Sensor device clock reset; begin a new run')
    summaries = []
    for _, window in windows.iterrows():
        raw = window_samples(live, 'host_epoch_s', window, 10, max_gap_s, 'sensor')
        ref = None if assumed else window_samples(reference, 'timestamp_epoch', window, 2, max_gap_s, 'reference')
        numeric(raw, ['raw_adc', 'temperature_c'], f'{window["name"]}: sensor')
        density(raw.temperature_c)
        mean_reference = float(assumed_speeds[window['name']]) if assumed else float(ref.value_raw_mps.mean())
        if not min_reference_mps <= mean_reference <= max_reference_mps:
            raise ValueError(f'{window["name"]}: mean reference speed {mean_reference:.4f} m/s must be within '
                             f'{min_reference_mps:g}..{max_reference_mps:g} m/s. '
                             'Use --min-reference-mps / --max-reference-mps to explicitly accept a different range; '
                             'actual measured speeds are never rounded to the limits.')
        summaries.append({**window.to_dict(), 'duration_s': window.end_epoch-window.start_epoch,
                          'reference_source': 'assumed_window_means' if assumed else 'measured_tunnel',
                          'sensor_n': len(raw), 'reference_n': 0 if assumed else len(ref),
                          'sensor_coverage_s': float(raw.host_epoch_s.iloc[-1]-raw.host_epoch_s.iloc[0]),
                          'reference_coverage_s': np.nan if assumed else float(ref.timestamp_epoch.iloc[-1]-ref.timestamp_epoch.iloc[0]),
                          'mean_adc': float(raw.raw_adc.mean()), 'std_adc': float(raw.raw_adc.std()),
                          'temperature_c': float(raw.temperature_c.mean()),
                          'temperature_std_c': float(raw.temperature_c.std()),
                          'reference_mps': mean_reference, 'reference_std_mps': np.nan if assumed else float(ref.value_raw_mps.std())})
    summary = pd.DataFrame(summaries)
    summary['delta_adc'] = summary.mean_adc - zero
    summary['rho'] = density(summary.temperature_c)
    cal_mask = summary.role == 'cal'
    cal = summary[cal_mask]
    beta, sign, useful = fit_model(cal.delta_adc, cal.rho, cal.reference_mps, sigma,
                                  min_reference_mps=min_reference_mps, max_reference_mps=max_reference_mps)
    summary['used_in_fit'] = False
    summary.loc[cal_mask, 'used_in_fit'] = useful
    summary['exclusion_reason'] = np.where(cal_mask & ~summary.used_in_fit, 'at/below noise or opposite sign', '')
    summary['predicted_mps'] = predict(summary.delta_adc, summary.rho, beta, sign, sigma)
    summary['error_mps'] = summary.predicted_mps - summary.reference_mps
    try:
        revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=Path(__file__).resolve().parents[1],
                                  capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        revision = 'unknown'
    input_paths = [('sensor', sensor_path), ('windows', windows_path),
                   ('assumed_speeds', assumed_speeds_path) if assumed else ('reference', reference_path)]
    interpretation = ('Agreement with assumed speeds only; not measured accuracy against tunnel ground truth.'
                      if assumed else 'Errors relative to measured tunnel reference window means.')
    model = {'zero_adc': zero, 'zero_sigma_adc': sigma, 'sign': sign, 'beta': beta,
             'reference_source': 'assumed_window_means' if assumed else 'measured_tunnel',
             'metrics_interpretation': interpretation,
             'model': 'v=beta*sqrt(max(0,sign*(ADC-zero)/rho)); zero if sign*(ADC-zero)<=3*sigma',
             'density_convention_pa': 101325., 'max_gap_s': max_gap_s,
             'reference_range_mps': [min_reference_mps, max_reference_mps],
             'reference_settings': None if assumed else {'ambient_pressure_pa': ambient_pressure_pa, 'temperature_c': reference_temperature_c,
                                    'note': 'User-supplied tutorial settings; reference speeds are read directly from CSV'},
             'mounting_notes': mounting_notes, 'git_revision': revision,
             'firmware_version': firmware_version,
             'firmware_provenance_note': 'Version is user-supplied. Host checkout revision/source hashes do not establish what is flashed on the board.',
             'local_firmware_sources': [provenance(Path(__file__).resolve().parents[1]/path)
                                        for path in ('firmware/src/main.cpp', 'firmware/src/calibration_config.h',
                                                     'firmware/arduino/wind_sensor/wind_sensor.ino',
                                                     'firmware/arduino/wind_sensor/calibration_config.h')
                                        if (Path(__file__).resolve().parents[1]/path).exists()],
             'inputs': {name: provenance(path) for name, path in input_paths},
             'calibration': score(summary[cal_mask].reference_mps, summary[cal_mask].predicted_mps),
             'validation': score(summary[~cal_mask].reference_mps, summary[~cal_mask].predicted_mps),
             'limitations': interpretation + ' Steady-window averages only; inspect plateau stability. Host timestamps do not establish dynamic latency. Recalibrate after mounting or material ambient pressure changes.'}
    if out is not None:
        export(Path(out), model, summary, live, reference)
    return model, summary


def export(out, model, summary, live, reference):
    # A new directory prevents failed reruns being confused with stale valid exports.
    out.mkdir(parents=True, exist_ok=False)
    summary.to_csv(out/'windows_summary.csv', index=False)
    (out/'model.json').write_text(json.dumps(model, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    plot_results(out, model, summary, live, reference)
    restore = f'k {model["zero_adc"]:.9g} {model["zero_sigma_adc"]:.9g} {model["sign"]} {model["beta"]:.9g}'
    from_line(restore)  # Validate against the existing deployment parser before export.
    (out/'calibration_restore.txt').write_text(restore+'\n', encoding='utf-8')
    constants = (f'const float ZERO_ADC = {model["zero_adc"]:.4f}f;\n'
                 f'const float ZERO_SIGMA_ADC = {model["zero_sigma_adc"]:.4f}f;\n'
                 f'const int WIND_SIGN = {model["sign"]};\n'
                 f'const float BETA = {model["beta"]:.9e}f;\n')
    (out/'calibration_constants.txt').write_text('// '+model['metrics_interpretation']+'\n'+constants, encoding='utf-8')
    if model['reference_source'] == 'assumed_window_means':
        (out/'ASSUMED_REFERENCES.txt').write_text(model['metrics_interpretation']+'\n'
                                                'No wind tunnel reference recording was supplied. '
                                                'Reference means came from the explicit assumed-speed mapping.\n', encoding='utf-8')


def plot_results(out, model, summary, live, reference):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    assumed = model['reference_source'] == 'assumed_window_means'
    reference_label = 'Assumed speed (m/s)' if assumed else 'Reference wind speed (m/s)'
    with PdfPages(out/'fig_plateaus.pdf') as pdf:
        for _, window in summary.iterrows():
            raw = live[live.host_epoch_s.between(window.start_epoch, window.end_epoch, inclusive='left')]
            fig, axes = plt.subplots(3, 1, figsize=(8, 7), sharex=True)
            if assumed:
                axes[0].plot([0, window.duration_s], [window.reference_mps]*2, '--', color='tab:orange')
                axes[0].set_title('Assumed mean; no reference recording', fontsize=10)
            else:
                ref = reference[reference.timestamp_epoch.between(window.start_epoch, window.end_epoch, inclusive='left')]
                axes[0].plot(ref.timestamp_epoch-window.start_epoch, ref.value_raw_mps)
            axes[0].set_ylabel(reference_label)
            axes[1].plot(raw.host_epoch_s-window.start_epoch, raw.raw_adc-model['zero_adc'])
            axes[1].set_ylabel('ADC minus zero')
            axes[2].plot(raw.host_epoch_s-window.start_epoch, raw.temperature_c)
            axes[2].set(ylabel='Temperature (C)', xlabel='Time in window (s)')
            fig.suptitle(f'{window["name"]} ({window.role}): inspect settling, drift and variability')
            fig.tight_layout(); pdf.savefig(fig); plt.close(fig)
    fig, ax = plt.subplots(figsize=(7, 4))
    for role, marker in [('cal', 'o'), ('val', 'x')]:
        rows = summary[summary.role == role]
        ax.scatter(model['sign']*rows.delta_adc, rows.reference_mps, marker=marker, label=role)
    x = np.linspace(0, max(1., float((model['sign']*summary.delta_adc).max()))*1.05, 250)
    ax.plot(x, predict(x, float(summary.rho.median()), model['beta'], 1, model['zero_sigma_adc']), label='Fit at median density')
    ax.set(xlabel='Signed ADC change', ylabel=reference_label)
    if assumed:
        ax.set_title('Provisional calibration using assumed speeds')
    ax.legend(); fig.tight_layout(); fig.savefig(out/'fig_calibration.pdf'); plt.close(fig)
    fig, ax = plt.subplots(figsize=(7, 4))
    val = summary[summary.role == 'val']
    ax.scatter(val.reference_mps, val.error_mps)
    ax.axhline(0, color='black', linewidth=1)
    ax.set(xlabel=reference_label,
           ylabel='Prediction minus assumed speed (m/s)' if assumed else 'Prediction error (m/s)',
           title='Held-out agreement with assumed speed' if assumed else 'Held-out validation')
    fig.tight_layout(); fig.savefig(out/'fig_validation_error.pdf'); plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sensor', required=True, type=Path)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--reference', type=Path, help='Measured tunnel reference CSV')
    source.add_argument('--assumed-speeds', type=Path, help='Explicit name,assumed_mps CSV; produces provisional calibration')
    parser.add_argument('--windows', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path, help='New output directory (must not already exist)')
    parser.add_argument('--ambient-pressure-pa', type=float, help='Required with --reference: ambient pressure entered in tutorial, Pa')
    parser.add_argument('--reference-temperature-c', type=float, help='Required with --reference: air temperature entered in tutorial, C')
    parser.add_argument('--max-gap-s', type=float, default=1., help='Maximum internal gap and uncovered edge, seconds')
    parser.add_argument('--min-reference-mps', type=float, default=2., help='Minimum accepted window mean; lower explicitly for measurements just below 2 m/s')
    parser.add_argument('--max-reference-mps', type=float, default=10., help='Maximum accepted window mean (default: 10 m/s)')
    parser.add_argument('--mounting-notes', default='')
    parser.add_argument('--firmware-version', default='not supplied', help='Identifier of firmware actually uploaded; cannot be detected from current serial protocol')
    args = parser.parse_args()
    try:
        model, _ = calibrate(args.sensor, args.reference, args.windows, args.out,
                             ambient_pressure_pa=args.ambient_pressure_pa,
                             reference_temperature_c=args.reference_temperature_c,
                             max_gap_s=args.max_gap_s, mounting_notes=args.mounting_notes,
                             firmware_version=args.firmware_version,
                             min_reference_mps=args.min_reference_mps, max_reference_mps=args.max_reference_mps,
                             assumed_speeds_path=args.assumed_speeds)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f'Calibration failed: {exc}\n')
    print('Saved:', args.out)
    print(model['metrics_interpretation'])
    print('Calibration:', model['calibration'])
    print('Held-out validation:', model['validation'])
    print('Inspect fig_plateaus.pdf and validation errors before loading calibration_restore.txt.')
    print('This does not verify hardware throughput or dynamic timing.')


if __name__ == '__main__':
    main()
