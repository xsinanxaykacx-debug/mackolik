import numpy as np
import pandas as pd
import pytest
import denetim_1x2 as audit

def sample():
    dates=pd.date_range("2016-01-01",periods=12,freq="D")
    return pd.DataFrame({"match_date":dates,"_rowid":range(12),"odds":[1.8]*12,
      "kazandi":[True]*8+[False]*4,"net_getiri":[.8]*8+[-1]*4,
      "p_fair":[.5]*12})

def test_synthetic_pattern_detected():
    g=sample()
    result=audit.audit(g,seed=123)
    assert result["roi"]>0
    assert result["tutma"]==pytest.approx(8/12)
    assert result["edge"]>0

def test_empty_and_single_row():
    empty=sample().iloc[:0]
    assert audit.audit(empty)["n"]==0
    one=sample().iloc[:1]
    result=audit.audit(one)
    assert result["n"]==1
    assert np.isnan(result["roi_ci_alt"])

def test_missing_one_of_three_odds_does_not_pair():
    frame=pd.DataFrame({"MS1":[1.8],"MSX":[np.nan],"MS2":[3.4]})
    nums={c:audit.odds_numeric(frame[c]) for c in ["MS1","MSX","MS2"]}
    assert nums["MS1"].notna().all()
    assert nums["MSX"].isna().all()

def test_roi_arithmetic_two_ways():
    g=sample()
    result=audit.audit(g)
    assert result["roi"]==pytest.approx(result["roi_kontrol"])
    assert result["roi_fark"]<1e-12

def test_deterministic_seed():
    g=sample()
    first=audit.audit(g,seed=456); second=audit.audit(g,seed=456)
    for key in first:
        if isinstance(first[key],float) and np.isnan(first[key]):
            assert np.isnan(second[key])
        else:
            assert first[key]==second[key]

def test_overround_for_valid_triples():
    odds=np.array([[1.8,3.5,4.2],[2.1,3.2,3.8]])
    overround=(1/odds).sum(axis=1)
    assert np.all(overround>1)
