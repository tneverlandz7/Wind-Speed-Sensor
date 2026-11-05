import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
from calibration_model import density, predict


class SpeedOnlySketchTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('c++'), 'Native C++ compiler required')
    def test_autostart_numeric_stream_and_embedded_prediction(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory)/'speed_only'
            compilation = subprocess.run(['c++', '-std=c++11', '-I', str(root/'tests/mock'),
                                          str(root/'tests/simulate_speed_only.cpp'), '-o', str(binary)],
                                         capture_output=True, text=True)
            self.assertEqual(compilation.returncode, 0, compilation.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        zero, sigma, sign, beta = map(float, lines[0].split(','))
        expected = float(predict(8810423.9036-zero, density(20.46024), beta, int(sign), sigma))
        self.assertAlmostEqual(float(lines[1]), expected, places=3)
        self.assertIn('200 numeric lines', lines[2])
