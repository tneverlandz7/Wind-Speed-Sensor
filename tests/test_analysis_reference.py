import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
from analyze import reference_values


class ReferenceTests(unittest.TestCase):
    def test_direct_speed_and_unknown_reference(self):
        frame = pd.DataFrame({'pressure_pa': [np.nan, 60., np.nan], 'ref_mps': [4.12, 10., np.nan]})
        result = reference_values(frame)
        np.testing.assert_allclose(result[:2], [4.12, 10.])
        self.assertTrue(np.isnan(result[2]))

    def test_legacy_pressure_only(self):
        np.testing.assert_allclose(reference_values(pd.DataFrame({'pressure_pa': [0., 15., 60.]})), [0., 5., 10.])
