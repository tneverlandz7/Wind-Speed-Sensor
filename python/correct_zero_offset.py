"""Offline squared-speed baseline correction for Wind Tunnel Logger exports.

Uses a user-confirmed no-wind speed anchor and assumes constant air density.
Preserves original readings; does not retune beta, filters, or board firmware.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from calibration_model import score
from calibrate_from_tunnel import read_csv, numeric, check_clock, provenance


def correct_speeds(speeds, zero_speed):
    speeds = np.asarray(speeds, dtype=float)
    if (not np.isfinite(speeds).all() or (speeds < 0).any()
            or not np.isfinite(zero_speed) or zero_speed < 0):
        raise ValueError('Speeds and zero anchor must be finite and nonnegative')
    return np.sqrt(np.maximum(0., speeds**2-zero_speed**2))


def comparison(frame):
    return {'mean_reference_mps': float(frame.ground_truth_mps.mean()),
            'mean_original_mps': float(frame.student_mps.mean()),
            'mean_corrected_mps': float(frame.corrected_student_mps.mean()),
            'original': score(frame.ground_truth_mps, frame.student_mps),
            'corrected': score(frame.ground_truth_mps, frame.corrected_student_mps)}


def run(aligned_path, student_path, reference_path, out, zero_speed, steady_range=None,
        alignment_tolerance_s=.15):
    aligned = read_csv(aligned_path, ['timestamp_epoch', 'ground_truth_mps', 'student_mps'])
    student = read_csv(student_path, ['timestamp_epoch', 'value_raw_mps'])
    reference = read_csv(reference_path, ['timestamp_epoch', 'value_raw_mps'])
    for name, frame, columns in [('aligned', aligned, ['ground_truth_mps', 'student_mps']),
                                  ('student', student, ['value_raw_mps']),
                                  ('reference', reference, ['value_raw_mps'])]:
        check_clock(frame, 'timestamp_epoch', name)
        numeric(frame, columns, name)
        if (frame[columns] < 0).any().any():
            raise ValueError(f'{name}: speed must be nonnegative')
    # Ensure the supplied reference is the source of the aligned comparison.
    import pandas as pd
    matched = pd.merge_asof(aligned[['timestamp_epoch', 'ground_truth_mps']],
                            reference[['timestamp_epoch', 'value_raw_mps']],
                            on='timestamp_epoch', direction='nearest', tolerance=1e-5)
    if not np.isfinite(matched.value_raw_mps).all() or not np.allclose(matched.ground_truth_mps, matched.value_raw_mps, rtol=0, atol=1e-6):
        raise ValueError('Aligned and reference files do not match')
    if not np.isfinite(alignment_tolerance_s) or alignment_tolerance_s < 0:
        raise ValueError('Alignment tolerance must be finite and nonnegative')
    # Mirror the logger's tuple sort and bisect-left tie handling, including
    # multiple samples received with the same host timestamp. Validate only;
    # the existing alignment is retained for all error calculations.
    ordered = student.sort_values(['timestamp_epoch', 'value_raw_mps'])
    times = ordered.timestamp_epoch.to_numpy()
    speeds = ordered.value_raw_mps.to_numpy()
    for epoch, reported in zip(aligned.timestamp_epoch, aligned.student_mps):
        i = int(np.searchsorted(times, epoch, side='left'))
        candidates = [j for j in (i-1, i) if 0 <= j < len(times) and abs(times[j]-epoch) <= alignment_tolerance_s]
        if not candidates:
            raise ValueError('Aligned and student files do not match: no sample within alignment tolerance')
        nearest = min(candidates, key=lambda j: abs(times[j]-epoch))
        if not np.isclose(speeds[nearest], reported, rtol=0, atol=1e-6):
            raise ValueError('Aligned and student files do not match: nearest-sample speed differs')
    aligned['corrected_student_mps'] = correct_speeds(aligned.student_mps, zero_speed)
    aligned['original_error_mps'] = aligned.student_mps-aligned.ground_truth_mps
    aligned['corrected_error_mps'] = aligned.corrected_student_mps-aligned.ground_truth_mps
    student['corrected_wind_mps'] = correct_speeds(student.value_raw_mps, zero_speed)
    start_epoch = float(aligned.timestamp_epoch.iloc[0])
    aligned['comparison_elapsed_s'] = aligned.timestamp_epoch-start_epoch
    metrics = {'zero_anchor_mps': float(zero_speed),
               'anchor_basis': 'User confirmed the initial 1.442 m/s reading was no wind.' if zero_speed == 1.442 else 'User-supplied no-wind speed anchor.',
               'formula': 'sqrt(max(0, reported_speed^2 - zero_anchor^2))',
               'assumption': 'Approximate constant air density; temperature was not recorded in these exports.',
               'scope': 'Offline baseline correction only; beta and EMA unchanged. Values at/below anchor become zero.',
               'comparison_note': 'Errors use the existing nearest-sample aligned CSV; no transport-delay correction or new time alignment is inferred.',
               'alignment_tolerance_s': float(alignment_tolerance_s),
               'inputs': {name: provenance(path) for name, path in [('aligned', aligned_path), ('student', student_path), ('reference', reference_path)]},
               'student_samples': len(student), 'overall': comparison(aligned)}
    if steady_range is not None:
        low, high = steady_range
        if not np.isfinite([low, high]).all() or not 0 <= low < high <= aligned.comparison_elapsed_s.max():
            raise ValueError('Steady interval must be finite, ordered and within the recording')
        steady = aligned[aligned.comparison_elapsed_s.between(low, high)]
        if len(steady) < 2:
            raise ValueError('Steady interval needs at least two aligned samples')
        metrics['steady_range_s'] = [float(low), float(high)]
        metrics['steady'] = comparison(steady)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    aligned.to_csv(out/'aligned_corrected.csv', index=False)
    student.to_csv(out/'student_corrected.csv', index=False)
    (out/'zero_correction_metrics.json').write_text(json.dumps(metrics, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    plot(out, aligned, student, reference, start_epoch, zero_speed)
    return metrics


def plot(out, aligned, student, reference, start_epoch, zero_speed):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(3, 1, figsize=(11, 9), gridspec_kw={'height_ratios': [1.6, 1, 1]})
    duration = float(aligned.comparison_elapsed_s.max())
    for ax in axes:
        ax.plot(student.timestamp_epoch-start_epoch, student.value_raw_mps, color='tab:orange', alpha=.65, lw=.8, label='Original board output')
        ax.plot(student.timestamp_epoch-start_epoch, student.corrected_wind_mps, color='tab:green', lw=.9, label='Zero-corrected output')
        ax.plot(reference.timestamp_epoch-start_epoch, reference.value_raw_mps, '.-', color='tab:blue', markersize=2, lw=1, label='Tunnel reference (~4 Hz)')
        ax.set(xlabel='Seconds since first reference sample', ylabel='Wind speed (m/s)')
        ax.grid(alpha=.2)
    axes[0].set_title(f'Baseline correction using confirmed {zero_speed:g} m/s zero-wind anchor')
    axes[0].legend(fontsize=8)
    axes[1].set(xlim=(0, min(8, duration)), ylim=(0, 5.5),
                title='Start: anchor maps to zero; later readings are not automatically re-zeroed')
    axes[2].set(xlim=(max(0, duration-8), duration), ylim=(0, 10.5),
                title='End: remaining low-speed difference after baseline correction')
    fig.text(.5, .012, 'Approximate constant-density correction. No additional smoothing, scale fitting, or firmware changes.', ha='center', fontsize=9)
    fig.tight_layout(rect=[0, .035, 1, 1])
    fig.savefig(out/'zero_corrected_comparison.png', dpi=160)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--aligned', type=Path, required=True)
    parser.add_argument('--student', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--zero-speed', type=float, required=True)
    parser.add_argument('--steady-start-s', type=float)
    parser.add_argument('--steady-end-s', type=float)
    parser.add_argument('--alignment-tolerance-s', type=float, default=.15, help='Tolerance configured in Wind Tunnel Logger (default: 0.15 s)')
    parser.add_argument('--out', type=Path, required=True, help='New output directory')
    args = parser.parse_args()
    if (args.steady_start_s is None) != (args.steady_end_s is None):
        parser.error('Supply both steady interval endpoints')
    steady = None if args.steady_start_s is None else (args.steady_start_s, args.steady_end_s)
    try:
        metrics = run(args.aligned, args.student, args.reference, args.out, args.zero_speed, steady,
                      alignment_tolerance_s=args.alignment_tolerance_s)
    except (OSError, ValueError) as exc:
        parser.exit(2, f'Zero correction failed: {exc}\n')
    print('Saved:', args.out)
    print('Overall:', metrics['overall'])
    if 'steady' in metrics:
        print('Steady interval:', metrics['steady'])
    print(metrics['assumption'])


if __name__ == '__main__':
    main()
