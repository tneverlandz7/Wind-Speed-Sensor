import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
from calibration_model import fit_model, predict


class FirmwareModelTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('c++'), 'Native C++ compiler required for firmware math check')
    def test_python_matches_actual_firmware_math(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory)/'compare_model'
            subprocess.run(['c++', '-std=c++11', '-I', str(root/'tests/mock'),
                            str(root/'tests/compare_model.cpp'), '-o', str(binary)], check=True, capture_output=True)
            lines = subprocess.check_output([str(binary)], text=True).splitlines()
        self.assertEqual(len(lines), 8)
        for line in lines:
            sign, delta, firmware_beta, firmware_speed = map(float, line.split(','))
            beta, fitted_sign, _ = fit_model([sign, sign*100, sign*400], [1, 1, 1], [9, 2, 4], 1)
            self.assertEqual(fitted_sign, sign)
            self.assertAlmostEqual(beta, firmware_beta, places=6)
            self.assertAlmostEqual(float(predict(sign*delta, 1, beta, int(sign), 1)), firmware_speed, places=6)


if __name__ == '__main__':
    unittest.main()
