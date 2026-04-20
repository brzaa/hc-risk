from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from hc_risk.metrics import categorical_psi
from hc_risk.scorecard import MISSING_LABEL, WOETransformer


class ScorecardTests(unittest.TestCase):
    def test_woe_transformer_handles_numeric_and_categorical(self) -> None:
        frame = pd.DataFrame(
            {
                "income_ratio": [0.1, 0.2, 0.3, 0.8, 0.9, np.nan, 0.4, 0.7],
                "income_type": ["Working", "Working", "Pensioner", "Business", None, "Working", "Working", "Business"],
            }
        )
        target = pd.Series([1, 1, 1, 0, 0, 1, 0, 0])

        transformer = WOETransformer(min_bin_size=0.1)
        transformer.fit(frame, target)
        transformed = transformer.transform(frame)

        self.assertEqual(set(transformed.columns), {"income_ratio", "income_type"})
        self.assertFalse(transformed.isna().any().any())
        self.assertIn("income_ratio", transformer.top_features(2))
        exported = transformer.export_rules()
        self.assertTrue((exported["feature"] == "income_ratio").any())
        self.assertTrue((exported["label"] == MISSING_LABEL).any())

    def test_label_frame_and_numeric_rule_metadata(self) -> None:
        frame = pd.DataFrame(
            {
                "utilization": [0.05, 0.08, 0.1, 0.18, 0.3, 0.45, 0.7, np.nan, 0.9, 0.95],
                "segment": ["A", "A", "A", "B", "B", "B", "C", "C", None, "C"],
            }
        )
        target = pd.Series([0, 0, 0, 0, 1, 1, 1, 0, 1, 1])

        transformer = WOETransformer(min_bin_size=0.1, max_bins=4)
        transformer.fit(frame, target)
        labels = transformer.label_frame(frame)

        self.assertEqual(set(labels.columns), {"utilization", "segment"})
        self.assertFalse(labels.isna().any().any())
        self.assertEqual(transformer.rules_["utilization"]["binning_strategy"], "supervised_monotonic_merge")

    def test_categorical_psi_uses_fixed_categories(self) -> None:
        payload = categorical_psi(
            expected_labels=["low", "low", "mid", "high"],
            actual_labels=["low", "mid", "mid", "high"],
            categories=["low", "mid", "high"],
        )
        self.assertIn("psi", payload)
        self.assertEqual(len(payload["components"]), 3)
        self.assertGreaterEqual(payload["psi"], 0.0)


if __name__ == "__main__":
    unittest.main()
