import numpy as np
import pandas as pd
import pytest

import denetim_v5 as audit


def synthetic_bets():
    # 8 wins at 1.80 and 4 losses at unit stake.
    wins = [True] * 8 + [False] * 4
    odds = [1.8] * 12
    net = [0.8] * 8 + [-1.0] * 4
    return pd.DataFrame({
        "match_date": pd.date_range("2016-01-01", periods=12, freq="D"),
        "kazandi": wins,
        "odds": odds,
        "net_getiri": net,
    })


def test_synthetic_known_pattern_and_roi_arithmetic():
    bets = synthetic_bets()
    result = audit.roi_audit(bets)
    # Manual ROI = (8 * 0.8 - 4 * 1) / 12 = 0.2
    manual_roi = (8 * 0.8 - 4.0) / 12
    assert result["n"] == 12
    assert result["galibiyet"] == 8
    assert result["roi"] == pytest.approx(manual_roi)
    assert result["roi_kontrol"] == pytest.approx(manual_roi)
    assert result["roi_fark"] < 1e-12


def test_empty_and_single_row_edges():
    empty = synthetic_bets().iloc[:0]
    empty_result = audit.roi_audit(empty)
    assert empty_result["n"] == 0
    assert np.isnan(empty_result["roi"])

    one = synthetic_bets().iloc[:1]
    one_result = audit.roi_audit(one)
    assert one_result["n"] == 1
    assert one_result["roi"] == pytest.approx(0.8)


def test_missing_odds_are_classified_not_silently_valid():
    values = pd.Series([1.8, np.nan, "bozuk", 1.0])
    numeric, status = audit.odds_status(values)
    assert numeric.iloc[0] == pytest.approx(1.8)
    assert status.iloc[0] == "gecerli"
    assert status.iloc[1] == "eksik"
    assert status.iloc[2] == "sayisal_degil"
    assert status.iloc[3] == "0_ile_1_arasi"


def test_bootstrap_is_deterministic_for_same_seed():
    bets = synthetic_bets()
    values = bets["net_getiri"].to_numpy(dtype=float)
    clusters = bets["match_date"].dt.normalize().to_numpy()
    first = audit.cluster_bootstrap_mean_ci(
        values, clusters, n_boot=20, rng=np.random.default_rng(9876)
    )
    second = audit.cluster_bootstrap_mean_ci(
        values, clusters, n_boot=20, rng=np.random.default_rng(9876)
    )
    assert first == second
    assert first[0] <= first[1]


def test_drawdown_includes_initial_zero_balance():
    # First bet loses, so the curve falls from the initial zero by one unit.
    dd, ratio = audit.drawdown_stats(np.array([-1.0, 0.8]), total_staked=2)
    assert dd == pytest.approx(1.0)
    assert ratio == pytest.approx(0.5)
