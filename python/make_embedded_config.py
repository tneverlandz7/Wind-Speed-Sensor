"""Generate embedded firmware calibration headers from a *real* STM32 RESTORE_CMD export.

Not an estimator: all windspeed estimation remains on Nucleo at deployment.
"""
import argparse
import re
from pathlib import Path


def from_line(line):
    line = line.strip()
    if line.startswith('RESTORE_CMD,'):
        line = line.split(',', 1)[1]
    m = re.fullmatch(r'k\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+]?[0-9]+)\s+([-+0-9.eE]+)', line)
    if not m:
        raise ValueError('Expected line: k ZERO_ADC NOISE_SIGMA +/-1 BETA')
    zero, sigma, sign, beta = (float(m[1]), float(m[2]), int(m[3]), float(m[4]))
    if not all(map(__import__('math').isfinite, [zero, sigma, beta])) or sigma < 0 or sign not in (-1, 1) or beta <= 0:
        raise ValueError('Invalid calibration parameters')
    return zero, sigma, sign, beta


def render(zero, sigma, sign, beta):
    return f'''#pragma once
// GENERATED from a real tunnel calibration. Keep source logs in supplementary ZIP.
// Recalibrate after mechanical changes (mounter/plate/load cell repositioning).
#define COMP0219_AUTOSTART 1
#define COMP0219_SAVED_ZERO_ADC {zero:.4f}f
#define COMP0219_SAVED_ZERO_SIGMA {sigma:.4f}f
#define COMP0219_SAVED_SIGN {sign}
#define COMP0219_SAVED_BETA {beta:.9f}f
'''


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--model-file', type=Path, required=True)
    p.add_argument('--target-root', type=Path, default=Path('.'))
    args = p.parse_args()
    line = args.model_file.read_text(encoding='utf-8').strip()
    payload = render(*from_line(line))
    paths = [args.target_root/'firmware/src/calibration_config.h',
             args.target_root/'firmware_Arduino/COMP0219_Stage1/calibration_config.h']
    for path in paths:
        if not path.parent.is_dir():
            raise ValueError(f'Missing firmware directory: {path.parent}')
        path.write_text(payload, encoding='utf-8')
        print('Saved auto-start calibration:', path)
    print('IMPORTANT: only enable this for final assessment AFTER verifying real calibration and no-wind zero drift.')

if __name__ == '__main__':
    main()
