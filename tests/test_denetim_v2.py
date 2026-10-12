# -*- coding: utf-8 -*-
"""denetim_v2 yardımcı fonksiyonları için sentetik regresyon testleri."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

import denetim_v2 as audit


class ScoreParsingTests(unittest.TestCase):
    """Skor çözümleme ve market etiketi davranışlarını sınar."""

    def test_under_over_boundary_and_separators(self) -> None:
        """2 toplam gol ALT, 3 toplam gol ÜST olmalı; ayraç çeşitleri çalışmalı."""
        self.assertEqual(audit.mac_sonucunu_coz("1-1")["sonuc"], "ALT")
        self.assertEqual(audit.mac_sonucunu_coz("2:1")["sonuc"], "ÜST")
        self.assertEqual(audit.mac_sonucunu_coz("2 – 0")["toplam_gol"], 2)
        self.assertEqual(audit.mac_sonucunu_coz(" 3 — 1 ")["sonuc"], "ÜST")

    def test_invalid_scores(self) -> None:
        """Boş veya skor içermeyen değerler çözümlenmemeli."""
        for value in (None, "", "ertelendi", "abc", "2/1"):
            self.assertIsNone(audit.mac_sonucunu_coz(value))

    def test_market_normalization(self) -> None:
        """ALT/ÜST için Türkçe ve İngilizce etiketler normalize edilmeli."""
        self.assertEqual(audit.sonuc_normalize("ALT"), "ALT")
        self.assertEqual(audit.sonuc_normalize("under"), "ALT")
        self.assertEqual(audit.sonuc_normalize("ÜST"), "ÜST")
        self.assertEqual(audit.sonuc_normalize("over"), "ÜST")
        self.assertIsNone(audit.sonuc_normalize("X"))


class OddsAndROItests(unittest.TestCase):
    """Oran bandı, bahis üretimi ve ROI hesaplarını sentetik veriyle sınar."""

    def test_odds_band_boundaries_and_invalid_values(self) -> None:
        """Oranlar 0.05 genişlikli yarı açık bantlara yerleşmeli."""
        self.assertEqual(audit.oran_bant_anahtari(1.87), (1.85, 1.9))
        self.assertEqual(audit.oran_bant_anahtari(1.90), (1.9, 1.95))
        self.assertIsNone(audit.oran_bant_anahtari(1.0))
        self.assertIsNone(audit.oran_bant_anahtari(np.nan))

    def test_roi_arithmetic_matches_two_methods(self) -> None:
        """Net getiri toplamı ile kazanma-kaybetme formülü aynı ROI'yi vermeli."""
        part = pd.DataFrame({
            "match_date": pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"]),
            "won": [1, 0, 1],
            "odds": [2.0, 1.8, 2.2],
            "net_1u": [1.0, -1.0, 1.2],
        })
        result = audit.roi_audit(part)
        direct = 100.0 * part["net_1u"].sum() / len(part)
        by_outcome = 100.0 * ((part.loc[part["won"] == 1, "odds"] - 1).sum()
                              - int((part["won"] == 0).sum())) / len(part)
        self.assertAlmostEqual(result["roi"], direct)
        self.assertAlmostEqual(result["roi"], by_outcome)
        self.assertEqual(result["n"], 3)

    def test_empty_roi_input(self) -> None:
        """Boş bahis tablosu sıfır ROI iddiası üretmemeli."""
        empty = pd.DataFrame(columns=["match_date", "won", "odds", "net_1u"])
        result = audit.roi_audit(empty)
        self.assertEqual(result["n"], 0)
        self.assertTrue(np.isnan(result["roi"]))

    def test_mismatch_excluded_and_missing_odds_handled(self) -> None:
        """FT etiketiyle çelişen kayıt dışlanmalı; geçersiz oran bahis üretmemeli."""
        raw = pd.DataFrame({
            "match_date": pd.to_datetime(["2021-01-01", "2021-01-02", "2021-01-03"]),
            "FT": ["1-0", "2-1", "0-0"],
            "MS25AÜ": ["ALT", "ALT", "ALT"],
            "alt_oran": [1.8, 1.9, np.nan],
            "ust_oran": [2.0, 1.9, 2.1],
            "kayit_sonucu": ["ALT", "ALT", "ALT"],
            "gercek_sonuc": ["ALT", "ÜST", "ALT"],
        })
        bets = audit.bahisleri_hazirla(raw)
        self.assertFalse(((bets["match_date"] == pd.Timestamp("2021-01-02"))).any())
        self.assertFalse((bets["odds"] <= 1).any())
        self.assertFalse(bets["odds"].isna().any())

    def test_bootstrap_repeatable_after_seed_reset(self) -> None:
        """Aynı seed ile bootstrap sonucu tekrar üretilebilir olmalı."""
        values = np.array([1.0, -1.0, 0.5, -1.0, 1.2, -1.0])
        dates = pd.to_datetime([
            "2021-01-01", "2021-01-01", "2021-01-02",
            "2021-01-03", "2021-01-04", "2021-01-04",
        ])
        audit.RNG = np.random.default_rng(audit.RANDOM_SEED)
        first = audit.block_bootstrap_mean_ci(values, dates, n_boot=40, block_len=2)
        audit.RNG = np.random.default_rng(audit.RANDOM_SEED)
        second = audit.block_bootstrap_mean_ci(values, dates, n_boot=40, block_len=2)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
