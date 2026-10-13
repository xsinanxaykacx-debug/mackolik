# -*- coding: utf-8 -*-
"""İki dönemli denetimin dönem sözleşmesi için regresyon testleri."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest

import numpy as np
import pandas as pd


class TwoPeriodContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).resolve().parents[1] / "denetim_v5.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        fn = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "donem_ata"
        )
        isolated = ast.Module(body=[fn], type_ignores=[])
        namespace = {
            "np": np,
            "KESIF_BASLANGIC": 2013,
            "KESIF_BITIS": 2017,
            "DOGR_BASLANGIC": 2018,
            "DOGR_BITIS": 2020,
        }
        exec(compile(isolated, str(source), "exec"), namespace)
        cls.donem_ata = staticmethod(namespace["donem_ata"])

    def test_only_discovery_and_validation_are_analysis_periods(self):
        years = pd.Series([2012, 2013, 2017, 2018, 2020, 2021, 2022])
        self.assertEqual(
            self.donem_ata(years).tolist(),
            ["Donem_Disi", "Kesif", "Kesif", "Dogrulama",
             "Dogrulama", "Donem_Disi", "Donem_Disi"],
        )

    def test_no_final_test_constant_or_label_in_script(self):
        source = (Path(__file__).resolve().parents[1] / "denetim_v5.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("NIHAI_TEST_YILI", source)
        self.assertNotIn('"NihaiTest"', source)
        self.assertIn('"05_iki_donem_tum_bantlar.csv"', source)
        self.assertNotIn('kaydet_csv(bandlar_nihai, "04c_bantlar_nihai_test.csv")', source)


if __name__ == "__main__":
    unittest.main()

# CI workflow trigger: run the two-period audit on GitHub Actions.
