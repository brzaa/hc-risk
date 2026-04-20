from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from hc_risk.config import PipelineConfig
from hc_risk.features import build_folds, safe_divide


class FeatureTests(unittest.TestCase):
    def test_safe_divide_handles_zero_denominator(self) -> None:
        numerator = pd.Series([10.0, 5.0, 0.0])
        denominator = pd.Series([2.0, 0.0, 4.0])
        result = safe_divide(numerator, denominator)
        self.assertAlmostEqual(result.iloc[0], 5.0)
        self.assertTrue(np.isnan(result.iloc[1]))
        self.assertAlmostEqual(result.iloc[2], 0.0)

    def test_build_folds_assigns_all_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "dataset").mkdir()
            config = PipelineConfig(root_dir=root)
            config.ensure_directories()

            master = pd.DataFrame(
                {
                    "SK_ID_CURR": np.arange(100001, 100101),
                    "TARGET": [0] * 80 + [1] * 20,
                    "dataset_split": ["train"] * 100,
                }
            )
            folds = build_folds(master, config, force=True)
            self.assertEqual(len(folds), 100)
            self.assertEqual(sorted(folds["fold"].unique().tolist()), [0, 1, 2, 3, 4])
            self.assertEqual(folds["SK_ID_CURR"].nunique(), 100)


if __name__ == "__main__":
    unittest.main()
