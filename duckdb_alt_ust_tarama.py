# -*- coding: utf-8 -*-
import duckdb
import pandas as pd
import numpy as np
import re
from pathlib import Path

DB = Path(r"C:\Users\bzdye\Downloads\DATA.duckdb")
SCRIPT_DIR = Path(r"C:\Users\bzdye\Downloads")
OUT = SCRIPT_DIR / "alt_ust_oran_tarama.csv"
DETAIL = SCRIPT_DIR / "alt_ust_oran_tarama_detay.csv"

if not DB.exists():
    raise FileNotFoundError(f"Veritabani bulunamadi: {DB}")

con = duckdb.connect(str(DB), read_only=True)
try:
    df = con.execute("""
        SELECT match_date, FT,
               TRY_CAST("25A_num" AS DOUBLE) AS alt_odds,
               TRY_CAST("25Ü_num" AS DOUBLE) AS ust_odds
        FROM matches_analysis
    """).fetchdf()
finally:
    con.close()

def parse_score(value):
    if pd.isna(value):
        return None
    m = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", str(value))
    if not m:
        return None
    return int(m.group(1)) + int(m.group(2))

df["goals"] = df["FT"].map(parse_score)
df["match_date"] = pd.to_datetime(df["match_date"], errors="coerce")
df = df.dropna(subset=["goals", "match_date"]).copy()
df["goals"] = df["goals"].astype(int)
df["year"] = df["match_date"].dt.year

def get_period(y):
    if y <= 2017:
        return "2013-2017"
    if y <= 2019:
        return "2018-2019"
    return "2020+"

def get_band(o):
    if o < 1.50:
        return "1.00-1.49"
    if o < 1.70:
        return "1.50-1.69"
    if o < 1.90:
        return "1.70-1.89"
    if o < 2.10:
        return "1.90-2.09"
    if o < 2.50:
        return "2.10-2.49"
    return "2.50+"

df["period"] = df["year"].map(get_period)
parts = []

for side, col, condition in [
    ("ALT", "alt_odds", df["goals"] <= 2),
    ("UST", "ust_odds", df["goals"] >= 3)
]:
    x = df[["match_date", "year", "period", col]].copy()
    x = x.rename(columns={col: "odds"})
    x["win"] = np.asarray(condition, dtype=int)
    x["side"] = side
    x = x.dropna(subset=["odds"])
    x = x[(x["odds"] > 1.0) & (x["odds"] < 100.0)].copy()
    x["band"] = x["odds"].map(get_band)
    x["net"] = np.where(x["win"] == 1, x["odds"] - 1.0, -1.0)
    parts.append(x)

bets = pd.concat(parts, ignore_index=True)
rows = []

for keys, g in bets.groupby(
    ["period", "year", "side", "band"], sort=True
):
    g = g.sort_values("match_date", kind="stable")
    n = len(g)
    wins = int(g["win"].sum())
    net = float(g["net"].sum())
    roi = net / n
    se = float(g["net"].std(ddof=1) / np.sqrt(n)) if n > 1 else np.nan
    lo = roi - 1.96 * se if np.isfinite(se) else np.nan
    hi = roi + 1.96 * se if np.isfinite(se) else np.nan

    cumulative = g["net"].cumsum().to_numpy()
    peaks = np.maximum.accumulate(np.r_[0.0, cumulative])[1:]
    max_dd = float(np.max(peaks - cumulative)) if n else 0.0

    longest = current = 0
    for w in g["win"].to_numpy():
        if w == 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0

    p, y, side, band = keys
    rows.append({
        "donem": p,
        "yil": int(y),
        "taraf": side,
        "oran_araligi": band,
        "bahis": n,
        "kazanan": wins,
        "kazanma_yuzdesi": round(100 * wins / n, 3),
        "ortalama_oran": round(float(g["odds"].mean()), 4),
        "net_birim": round(net, 2),
        "roi_yuzde": round(100 * roi, 3),
        "roi_ga95_alt_yaklasik": round(100 * lo, 3) if np.isfinite(lo) else None,
        "roi_ga95_ust_yaklasik": round(100 * hi, 3) if np.isfinite(hi) else None,
        "en_uzun_kayip_serisi": longest,
        "maksimum_dusus_birim": round(max_dd, 2)
    })

detail = pd.DataFrame(rows)
detail.to_csv(DETAIL, index=False, encoding="utf-8-sig")

# Donem ve oran dilimi birlestirmesi
summary = bets.groupby(["period", "side", "band"]).agg(
    bahis=("win", "size"),
    kazanan=("win", "sum"),
    ortalama_oran=("odds", "mean"),
    net_birim=("net", "sum")
).reset_index()
summary["kazanma_yuzdesi"] = 100 * summary["kazanan"] / summary["bahis"]
summary["roi_yuzde"] = 100 * summary["net_birim"] / summary["bahis"]
summary.to_csv(OUT, index=False, encoding="utf-8-sig")

print("Gecerli mac:", len(df))
print("Bahis kaydi:", len(bets))
print("Yillik detay satiri:", len(detail))
print("Ozet dosyasi:", OUT)
print("Detay dosyasi:", DETAIL)

print("\n=== EN AZ 300 BAHISLI POZITIF ROI GRUPLARI ===")
positive = detail[(detail["bahis"] >= 300) & (detail["roi_yuzde"] > 0)]
if positive.empty:
    print("Bu taramada en az 300 bahisli pozitif ROI grubu bulunamadi.")
else:
    print(positive.sort_values("roi_yuzde", ascending=False).to_string(index=False))

print("\n=== DONEM VE ORAN ARALIGI OZETI ===")
print(summary.sort_values(["side", "band", "period"]).to_string(index=False))
print("\nNot: GA yaklasik normal araliktir; maclar arasi bagimliligi ve coklu test etkisini duzeltmez.")
