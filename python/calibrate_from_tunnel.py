"""Fit steady-window calibration from tutorial reference + raw Nucleo logs.

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

from calibration_model import density, fit_model, predict, score
from make_embedded_config import from_line


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


def calibrate(sensor_path, reference_path, windows_path, out=None, *, ambient_pressure_pa,
              reference_temperature_c, max_gap_s=1., mounting_notes='', firmware_version='not supplied'):
    if (not np.isfinite([ambient_pressure_pa, reference_temperature_c, max_gap_s]).all()
            or ambient_pressure_pa <= 0 or not -40 <= reference_temperature_c <= 125 or max_gap_s <= 0):
        raise ValueError('Invalid ambient pressure, reference temperature, or maximum gap')
    if re.search(r'(?:^|[_\W])(simulated|synthetic)(?:[_\W]|$)', Path(reference_path).stem, re.I):
        raise ValueError('Cannot calibrate from simulated/synthetic reference runs')
    sensor = read_csv(sensor_path, ['host_epoch_s', 'kind', 'raw_line', 'raw_adc', 'temperature_c'])
    reference = read_csv(reference_path, ['timestamp_epoch', 'value_raw_mps'])
    if 'device_name' in reference and reference.device_name.fillna('').str.contains('simulated|synthetic', case=False).any():
        raise ValueError('Cannot calibrate from simulated/synthetic reference runs')
    check_clock(sensor, 'host_epoch_s', 'sensor')
    check_clock(reference, 'timestamp_epoch', 'reference')
    numeric(reference, ['value_raw_mps'], 'reference')
    windows = read_windows(windows_path)
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
        ref = window_samples(reference, 'timestamp_epoch', window, 2, max_gap_s, 'reference')
        numeric(raw, ['raw_adc', 'temperature_c'], f'{window["name"]}: sensor')
        density(raw.temperature_c)
        mean_reference = float(ref.value_raw_mps.mean())
        if not 2 <= mean_reference <= 10:
            raise ValueError(f'{window["name"]}: mean reference speed must be within 2..10 m/s')
        summaries.append({**window.to_dict(), 'duration_s': window.end_epoch-window.start_epoch,
                          'sensor_n': len(raw), 'reference_n': len(ref),
                          'sensor_coverage_s': float(raw.host_epoch_s.iloc[-1]-raw.host_epoch_s.iloc[0]),
                          'reference_coverage_s': float(ref.timestamp_epoch.iloc[-1]-ref.timestamp_epoch.iloc[0]),
                          'mean_adc': float(raw.raw_adc.mean()), 'std_adc': float(raw.raw_adc.std()),
                          'temperature_c': float(raw.temperature_c.mean()),
                          'temperature_std_c': float(raw.temperature_c.std()),
                          'reference_mps': mean_reference, 'reference_std_mps': float(ref.value_raw_mps.std())})
    summary = pd.DataFrame(summaries)
    summary['delta_adc'] = summary.mean_adc - zero
    summary['rho'] = density(summary.temperature_c)
    cal_mask = summary.role == 'cal'
    cal = summary[cal_mask]
    beta, sign, useful = fit_model(cal.delta_adc, cal.rho, cal.reference_mps, sigma)
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
    model = {'zero_adc': zero, 'zero_sigma_adc': sigma, 'sign': sign, 'beta': beta,
             'model': 'v=beta*sqrt(max(0,sign*(ADC-zero)/rho)); zero if sign*(ADC-zero)<=3*sigma',
             'density_convention_pa': 101325., 'max_gap_s': max_gap_s,
             'reference_settings': {'ambient_pressure_pa': ambient_pressure_pa, 'temperature_c': reference_temperature_c,
                                    'note': 'User-supplied tutorial settings; reference speeds are read directly from CSV'},
             'mounting_notes': mounting_notes, 'git_revision': revision,
             'firmware_version': firmware_version,
             'firmware_provenance_note': 'Version is user-supplied. Host checkout revision/source hashes do not establish what is flashed on the board.',
             'local_firmware_sources': [provenance(Path(__file__).resolve().parents[1]/path)
                                        for path in ('firmware/src/main.cpp', 'firmware/src/calibration_config.h',
                                                     'firmware_Arduino/COMP0219_Stage1/COMP0219_Stage1.ino',
                                                     'firmware_Arduino/COMP0219_Stage1/calibration_config.h')
                                        if (Path(__file__).resolve().parents[1]/path).exists()],
             'inputs': {name: provenance(path) for name, path in [('sensor', sensor_path), ('reference', reference_path), ('windows', windows_path)]},
             'calibration': score(summary[cal_mask].reference_mps, summary[cal_mask].predicted_mps),
             'validation': score(summary[~cal_mask].reference_mps, summary[~cal_mask].predicted_mps),
             'limitations': 'Steady-window averages only; inspect plateau stability. Host timestamps do not establish dynamic latency. Recalibrate after mounting or material ambient pressure changes.'}
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


def plot_results(out, model, summary, live, reference):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    with PdfPages(out/'fig_plateaus.pdf') as pdf:
        for _, window in summary.iterrows():
            raw = live[live.host_epoch_s.between(window.start_epoch, window.end_epoch, inclusive='left')]
            ref = reference[reference.timestamp_epoch.between(window.start_epoch, window.end_epoch, inclusive='left')]
            fig, axes = plt.subplots(3, 1, figsize=(8, 7), sharex=True)
            axes[0].plot(ref.timestamp_epoch-window.start_epoch, ref.value_raw_mps)
            axes[0].set_ylabel('Reference (m/s)')
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
    ax.set(xlabel='Signed ADC change', ylabel='Reference wind speed (m/s)')
    ax.legend(); fig.tight_layout(); fig.savefig(out/'fig_calibration.pdf'); plt.close(fig)
    fig, ax = plt.subplots(figsize=(7, 4))
    val = summary[summary.role == 'val']
    ax.scatter(val.reference_mps, val.error_mps)
    ax.axhline(0, color='black', linewidth=1)
    ax.set(xlabel='Reference wind speed (m/s)', ylabel='Prediction error (m/s)', title='Held-out validation')
    fig.tight_layout(); fig.savefig(out/'fig_validation_error.pdf'); plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sensor', required=True, type=Path)
    parser.add_argument('--reference', required=True, type=Path)
    parser.add_argument('--windows', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path, help='New output directory (must not already exist)')
    parser.add_argument('--ambient-pressure-pa', required=True, type=float, help='Ambient pressure entered in tutorial, Pa')
    parser.add_argument('--reference-temperature-c', required=True, type=float, help='Air temperature entered in tutorial, C')
    parser.add_argument('--max-gap-s', type=float, default=1., help='Maximum internal gap and uncovered edge, seconds')
    parser.add_argument('--mounting-notes', default='')
    parser.add_argument('--firmware-version', default='not supplied', help='Identifier of firmware actually uploaded; cannot be detected from current serial protocol')
    args = parser.parse_args()
    try:
        model, _ = calibrate(args.sensor, args.reference, args.windows, args.out,
                             ambient_pressure_pa=args.ambient_pressure_pa,
                             reference_temperature_c=args.reference_temperature_c,
                             max_gap_s=args.max_gap_s, mounting_notes=args.mounting_notes,
                             firmware_version=args.firmware_version)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f'Calibration failed: {exc}\n')
    print('Saved:', args.out)
    print('Calibration:', model['calibration'])
    print('Held-out validation:', model['validation'])
    print('Inspect fig_plateaus.pdf and validation errors before loading calibration_restore.txt.')
    print('This does not verify hardware throughput or dynamic timing.')


if __name__ == '__main__':
    main()
