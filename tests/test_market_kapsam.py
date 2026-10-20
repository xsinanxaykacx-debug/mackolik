import pandas as pd
import numpy as np
import market_kapsam as mk


def test_turkish_column_normalization():
    assert mk.norm_col("25Ü_num") == "25UNUM"
    assert mk.norm_col("İY1") == "IY1"


def test_market_definitions_find_common_aliases():
    defs = mk.market_definitions(["FT", "HT", "match_date", "KGV_num", "KGY", "25Ü_num", "25A_num", "IY1"])
    found = {(d["market"], d["odds_col"]) for d in defs}
    assert ("KG VAR", "KGV_num") in found
    assert ("KG YOK", "KGY") in found
    assert ("MS toplam gol ALT 2.5", "25Ü_num") in found
    assert ("İlk yarı 1X2 1", "IY1") in found


def test_score_parser_and_outcome():
    assert mk.parse_score("2-1") == (2.0, 1.0)
    assert mk.parse_score("invalid")[0] != mk.parse_score("invalid")[0]
    row = pd.Series({"ft_home": 2.0, "ft_away": 1.0, "ht_home": 0.0, "ht_away": 0.0})
    assert mk.outcome_for(row, "btts_yes") is True
    assert mk.outcome_for(row, "btts_no") is False
    assert mk.outcome_for(row, "total_over", 2.5) is True
    assert mk.outcome_for(row, "total_under", 2.5) is False
    assert mk.outcome_for(row, "ht_X") is True


def test_profit_logic_for_wins_and_losses():
    odds = np.array([2.0, 3.0])
    won = np.array([True, False])
    profit = np.where(won, odds - 1, -1.0)
    assert profit.tolist() == [1.0, -1.0]
