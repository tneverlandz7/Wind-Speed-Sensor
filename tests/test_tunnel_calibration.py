import json
import sys
import tempfile
import subprocess
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
from calibration_model import density, fit_model, predict
from calibrate_from_tunnel import calibrate
from make_embedded_config import from_line


class ModelTests(unittest.TestCase):
    def test_fit_both_signs_and_noise_deadband(self):
        for sign in (1, -1):
            delta = sign * np.array([1., 100., 400.])
            speeds = np.array([9., 2., 4.])
            beta, fitted_sign, useful = fit_model(delta, np.ones(3), speeds, 1.)
            self.assertAlmostEqual(beta, .2)
            self.assertEqual(fitted_sign, sign)
            self.assertEqual(useful.tolist(), [False, True, True])
            np.testing.assert_allclose(predict(sign*np.array([-1., 3., 100.]), 1., beta, sign, 1.), [0, 0, 2])
        with self.assertRaises(ValueError):
            fit_model([1., 2.], [1., 1.], [2., 3.], 1.)


class TunnelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sensor = self.root/'sensor.csv'
        self.reference = self.root/'reference_vdas.csv'
        self.windows = self.root/'windows.csv'
        self.epoch = 1700000000.
        self.write_fixture()

    def write_fixture(self, sign=1):
        sensor = [dict(host_epoch_s=self.epoch, kind='DEVICE', raw_line='ZERO,ADC=1000,SIGMA=1,TEMP_C=20,N=50')]
        reference, windows = [], []
        for i, speed in enumerate([2., 4., 8., 3., 6.]):
            start = self.epoch + 10 + i*20
            role = 'cal' if i < 3 else 'val'
            windows.append(dict(name=f'w{i}', role=role, start_epoch=start, end_epoch=start+10))
            for t in np.arange(start, start+10, .2):
                sensor.append(dict(host_epoch_s=t, kind='LIVE', raw_line='', raw_adc=1000+sign*float(density(20))*(speed/.2)**2,
                                   temperature_c=20, device_ms=(t-self.epoch)*1000))
                reference.append(dict(timestamp_epoch=t, value_raw_mps=speed, value_clipped_mps=0,
                                      pa_raw=10, pa_corrected=9, device_name='VDAS'))
        pd.DataFrame(sensor).to_csv(self.sensor, index=False)
        pd.DataFrame(reference).to_csv(self.reference, index=False)
        pd.DataFrame(windows).to_csv(self.windows, index=False)

    def run_fit(self, out=None):
        return calibrate(self.sensor, self.reference, self.windows, out=out,
                         ambient_pressure_pa=100000., reference_temperature_c=20.)

    def edit(self, path, fn):
        df = pd.read_csv(path)
        fn(df).to_csv(path, index=False)

    def test_known_model_and_export(self):
        for sign in (1, -1):
            self.write_fixture(sign)
            model, summary = self.run_fit()
            self.assertAlmostEqual(model['beta'], .2)
            self.assertEqual(model['sign'], sign)
            self.assertLess(model['validation']['RMSE_m_s'], 1e-10)
            self.assertTrue((summary.reference_mps > 0).all())  # never clipped column
        out = self.root/'out'
        self.run_fit(out)
        zero, sigma, sign, beta = from_line((out/'calibration_restore.txt').read_text())
        self.assertEqual((zero, sigma, sign), (1000., 1., -1))
        self.assertAlmostEqual(beta, .2)
        self.assertEqual(json.loads((out/'model.json').read_text())['reference_settings']['ambient_pressure_pa'], 100000.)
        for name in ['windows_summary.csv', 'fig_plateaus.pdf', 'fig_calibration.pdf', 'fig_validation_error.pdf']:
            self.assertGreater((out/name).stat().st_size, 0)

    def test_validation_does_not_change_fit(self):
        original, _ = self.run_fit()
        self.edit(self.reference, lambda df: df.assign(value_raw_mps=np.where(df.timestamp_epoch > self.epoch+65, 9., df.value_raw_mps)))
        model, _ = self.run_fit()
        self.assertEqual(model['beta'], original['beta'])
        self.assertGreater(model['validation']['RMSE_m_s'], 1)

    def test_command_line_export_and_failed_rerun(self):
        out = self.root/'cli_out'
        command = [sys.executable, str(Path(__file__).resolve().parents[1]/'python/calibrate_from_tunnel.py'),
                   '--sensor', str(self.sensor), '--reference', str(self.reference), '--windows', str(self.windows),
                   '--ambient-pressure-pa', '100000', '--reference-temperature-c', '20',
                   '--firmware-version', 'test-fixture-only', '--out', str(out)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Held-out validation', result.stdout)
        from_line((out/'calibration_restore.txt').read_text())
        metadata = json.loads((out/'model.json').read_text())
        self.assertEqual(metadata['firmware_version'], 'test-fixture-only')
        self.assertEqual(len(metadata['local_firmware_sources']), 4)
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('Calibration failed', result.stderr)

    def test_window_failures(self):
        for mutation, message in [
            (lambda df: df.assign(end_epoch=np.nan), 'unfinished'),
            (lambda df: df.assign(role='bad'), 'role'),
            (lambda df: df.assign(name='same'), 'unique'),
            (lambda df: df.assign(start_epoch=self.epoch+10), 'overlap'),
            (lambda df: df.assign(end_epoch=df.start_epoch-1), 'end'),
        ]:
            with self.subTest(message=message):
                self.write_fixture()
                self.edit(self.windows, mutation)
                with self.assertRaisesRegex(ValueError, message):
                    self.run_fit()

    def test_bad_reference(self):
        for mutation, message in [
            (lambda df: df.drop(columns='value_raw_mps'), 'columns'),
            (lambda df: df.assign(value_raw_mps=np.nan), 'finite'),
            (lambda df: df.iloc[::-1], 'clock'),
            (lambda df: df[df.timestamp_epoch < self.epoch+70], 'w3'),
            (lambda df: df[~df.timestamp_epoch.between(self.epoch+13, self.epoch+16)], 'gap'),
            (lambda df: df.assign(device_name='Simulated'), 'simulated'),
        ]:
            with self.subTest(message=message):
                self.write_fixture()
                self.edit(self.reference, mutation)
                with self.assertRaisesRegex(ValueError, message):
                    self.run_fit()
        self.write_fixture()
        self.reference = self.reference.rename(self.root/'team_simulated_vdas.csv')
        with self.assertRaisesRegex(ValueError, 'simulated'):
            self.run_fit()

    def test_bad_sensor_and_baseline(self):
        for mutation, message in [
            (lambda df: df.iloc[1:], 'ZERO'),
            (lambda df: pd.concat([df.iloc[:1], df], ignore_index=True), 'ZERO'),
            (lambda df: df.assign(raw_adc=np.nan), 'finite'),
            (lambda df: df.iloc[::-1], 'clock'),
            (lambda df: df.drop(columns='host_epoch_s'), 'columns'),
            (lambda df: df[df.kind != 'LIVE'], 'sensor'),
        ]:
            with self.subTest(message=message):
                self.write_fixture()
                self.edit(self.sensor, mutation)
                with self.assertRaisesRegex(ValueError, message):
                    self.run_fit()


if __name__ == '__main__':
    unittest.main()
