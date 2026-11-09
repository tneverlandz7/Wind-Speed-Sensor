import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
from calibrate_sensor import calibrate
from calibration_model import density
from generate_calibration_header import from_line


class AssumedCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sensor = self.root/'sensor.csv'
        self.windows = self.root/'windows.csv'
        self.speeds = self.root/'assumed_speeds.csv'
        raw = [dict(kind='DEVICE', host_epoch_s=1700000000., raw_line='ZERO,ADC=8400000,SIGMA=30,N=50')]
        windows, speeds = [], []
        for i, speed in enumerate([10., 8., 6., 4.]):
            start = 1700000010.+i*20
            windows.append(dict(name=f'speed_{int(speed)}', role='val' if i == 3 else 'cal', start_epoch=start, end_epoch=start+10))
            speeds.append(dict(name=f'speed_{int(speed)}', assumed_mps=speed))
            for t in np.arange(start, start+10, .2):
                raw.append(dict(kind='LIVE', host_epoch_s=t, raw_line='', temperature_c=21.,
                                raw_adc=8400000-float(density(21))*(speed/.03)**2))
        pd.DataFrame(raw).to_csv(self.sensor, index=False)
        pd.DataFrame(windows).to_csv(self.windows, index=False)
        pd.DataFrame(speeds).to_csv(self.speeds, index=False)

    def run_fit(self, **kwargs):
        return calibrate(self.sensor, None, self.windows, assumed_speeds_path=self.speeds, **kwargs)

    def test_fit_and_provenance_without_reference_samples(self):
        model, summary = self.run_fit()
        self.assertAlmostEqual(model['beta'], .03)
        self.assertEqual(model['sign'], -1)
        self.assertEqual(model['reference_source'], 'assumed_window_means')
        self.assertIn('not measured accuracy', model['metrics_interpretation'])
        self.assertIsNone(model['reference_settings'])
        self.assertNotIn('reference', model['inputs'])
        self.assertIn('assumed_speeds', model['inputs'])
        self.assertTrue((summary.reference_n == 0).all())
        self.assertTrue(summary.reference_std_mps.isna().all())
        self.assertTrue(summary.reference_coverage_s.isna().all())
        self.assertEqual(summary.used_in_fit.tolist(), [True, True, True, False])

    def test_validation_assumption_never_changes_beta(self):
        model, _ = self.run_fit()
        speeds = pd.read_csv(self.speeds)
        speeds.loc[speeds.name == 'speed_4', 'assumed_mps'] = 5.
        speeds.to_csv(self.speeds, index=False)
        changed, _ = self.run_fit()
        self.assertEqual(changed['beta'], model['beta'])
        self.assertAlmostEqual(changed['validation']['bias_m_s'], -1.)

    def test_missing_extra_duplicate_and_nonfinite_mapping_rejected(self):
        original = pd.read_csv(self.speeds)
        bad_frames = [original.iloc[:-1], pd.concat([original, original.iloc[:1]]),
                      pd.concat([original, pd.DataFrame([dict(name='extra', assumed_mps=5.)])]),
                      original.assign(assumed_mps=np.nan), original.assign(assumed_mps=0.),
                      original.assign(assumed_mps=11.)]
        for frame in bad_frames:
            frame.to_csv(self.speeds, index=False)
            with self.assertRaises(ValueError):
                self.run_fit()

    def test_sensor_coverage_still_required(self):
        frame = pd.read_csv(self.sensor)
        frame = frame[~frame.host_epoch_s.between(1700000013., 1700000016.)]
        frame.to_csv(self.sensor, index=False)
        with self.assertRaisesRegex(ValueError, 'gap'):
            self.run_fit()

    def test_sources_are_mutually_exclusive(self):
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            calibrate(self.sensor, None, self.windows)
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            calibrate(self.sensor, self.root/'not_used.csv', self.windows, assumed_speeds_path=self.speeds)

    def test_cli_export_labels_and_preserves_originals(self):
        original_sensor = self.sensor.read_bytes()
        original_windows = self.windows.read_bytes()
        out = self.root/'out'
        script = Path(__file__).resolve().parents[1]/'python/calibrate_sensor.py'
        args = [sys.executable, str(script), '--sensor', str(self.sensor), '--windows', str(self.windows),
                '--assumed-speeds', str(self.speeds), '--out', str(out)]
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('not measured accuracy', result.stdout)
        model = json.loads((out/'model.json').read_text())
        self.assertEqual(model['reference_source'], 'assumed_window_means')
        self.assertIn('not measured accuracy', (out/'ASSUMED_REFERENCES.txt').read_text())
        self.assertEqual(from_line((out/'calibration_restore.txt').read_text())[:3], (8400000., 30., -1))
        for name in ['fig_plateaus.pdf', 'fig_calibration.pdf', 'fig_validation_error.pdf', 'calibration_constants.txt']:
            self.assertGreater((out/name).stat().st_size, 0)
        self.assertEqual(self.sensor.read_bytes(), original_sensor)
        self.assertEqual(self.windows.read_bytes(), original_windows)
        rejected = subprocess.run([*args, '--reference', 'not_used.csv'], capture_output=True, text=True)
        self.assertEqual(rejected.returncode, 2)
