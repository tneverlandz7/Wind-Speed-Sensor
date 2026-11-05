import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
from correct_zero_offset import correct_speeds, run


class ZeroCorrectionTests(unittest.TestCase):
    def test_squared_speed_correction(self):
        result = correct_speeds([0, 1, 1.442, 3, 9.35], 1.442)
        np.testing.assert_allclose(result[:3], [0, 0, 0])
        np.testing.assert_allclose(result[3:], np.sqrt(np.array([3., 9.35])**2-1.442**2))
        np.testing.assert_allclose(correct_speeds([0, 2, 5], 0), [0, 2, 5])

    def test_invalid_inputs_rejected(self):
        for speeds, zero in [([np.nan], 1.442), ([np.inf], 1.442), ([-1], 1.442),
                             ([2], -1), ([2], np.nan)]:
            with self.assertRaises(ValueError):
                correct_speeds(speeds, zero)

    def test_export_preserves_source_readings_and_records_assumptions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            aligned, student, reference = (root/f'{name}.csv' for name in ['aligned', 'student', 'reference'])
            t = [1000., 1000.25, 1000.5]
            pd.DataFrame({'timestamp_epoch': t, 'ground_truth_mps': [0, 2, 4], 'student_mps': [1.442, 3, 5]}).to_csv(aligned, index=False)
            pd.DataFrame({'timestamp_epoch': t, 'value_raw_mps': [1.442, 3, 5]}).to_csv(student, index=False)
            pd.DataFrame({'timestamp_epoch': t, 'value_raw_mps': [0, 2, 4]}).to_csv(reference, index=False)
            before = [p.read_bytes() for p in [aligned, student, reference]]
            out = root/'out'
            metrics = run(aligned, student, reference, out, 1.442, steady_range=(.25, .5))
            corrected = pd.read_csv(out/'aligned_corrected.csv')
            np.testing.assert_allclose(corrected.student_mps, [1.442, 3, 5])
            self.assertEqual(corrected.corrected_student_mps.iloc[0], 0)
            self.assertIn('constant air density', metrics['assumption'])
            self.assertEqual(metrics['steady']['original']['n'], 2)
            self.assertEqual(json.loads((out/'zero_correction_metrics.json').read_text())['zero_anchor_mps'], 1.442)
            self.assertTrue((out/'zero_corrected_comparison.png').exists())
            self.assertEqual([p.read_bytes() for p in [aligned, student, reference]], before)
            with self.assertRaises(FileExistsError):
                run(aligned, student, reference, out, 1.442)
            # A valid-looking export from another board/run must not be mixed
            # with the supplied alignment and its error metrics.
            wrong = pd.read_csv(student)
            wrong['value_raw_mps'] += 1
            wrong.to_csv(student, index=False)
            with self.assertRaisesRegex(ValueError, 'student files do not match'):
                run(aligned, student, reference, root/'wrong_source', 1.442)
            self.assertFalse((root/'wrong_source').exists())
