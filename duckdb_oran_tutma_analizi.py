# -*- coding: utf-8 -*-
"""Maçkolik DuckDB: ALT/ÜST 2.5 oranları ile gerçekleşen tutma oranı analizi.
Salt okunur; oran bantları, tam oranlar, yıl/dönem, saat ve haftanın günü.
Bu betik strateji optimize etmez; keşifsel örüntüleri ve çoklu test riskini raporlar.
"""
from __future__ import annotations
import math
import re
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd

DB_PATH = Path(r"C:\Users\bzdye\Downloads\DATA.duckdb")
OUT_DIR = Path(r"C:\Users\bzdye\Downloads")
TABLE = "matches_analysis"
MIN_ODDS = 1.01
MAX_ODDS = 20.0
BIN_WIDTH = 0.05
MIN_GROUP_N = 200


def parse_score(value):
    if value is None or pd.isna(value):
        return None
    m = re.fullmatch(r"\s*(\d+)\s*[-:]\s*(\d+)\s*", str(value))
    return (int(m.group(1)), int(m.group(2))) if m else None


def wilson_interval(wins: int, n: int, z: float = 1.959963984540054):
    if n <= 0:
        return (np.nan, np.nan)
    p = wins / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt((p * (1 - p) / n) + z * z / (4 * n * n)) / den
    return center - half, center + half


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bh_adjust(p_values):
    """Benjamini-Hochberg FDR adjustment; NaNs remain NaN."""
    p = np.asarray(p_values, dtype=float)
    out = np.full(p.shape, np.nan)
    idx = np.flatnonzero(np.isfinite(p))
    if len(idx) == 0:
        return out
    order = idx[np.argsort(p[idx])]
    m = len(order)
    ranked = p[order] * m / np.arange(1, m + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    out[order] = np.clip(ranked, 0, 1)
    return out


def add_group_stats(group: pd.DataFrame, keys, label):
    rows = []
    for vals, g in group.groupby(keys, dropna=False, observed=True, sort=True):
        if not isinstance(vals, tuple):
            vals = (vals,)
        n = len(g)
        wins = int(g["won"].sum())
        p_hat = wins / n if n else np.nan
        avg_odds = float(g["odds"].mean()) if n else np.nan
        # 1/oran: yalnızca brüt başa baş eşiği; gerçek/fair olasılık değildir.
        implied = float((1.0 / g["odds"]).mean()) if n else np.nan
        lo, hi = wilson_interval(wins, n)
        # Keşifsel tek-örneklem oran testi: gözlenen tutma oranı, ortalama 1/oran'a karşı.
        # Bağımsız maç varsayımı yaklaşık olup çoklu test düzeltmesi ayrıca yapılır.
        se = math.sqrt(max(implied * (1 - implied), 1e-12) / n) if n else np.nan
        z = (p_hat - implied) / se if n and se > 0 else np.nan
        pval = 2 * (1 - normal_cdf(abs(z))) if np.isfinite(z) else np.nan
        roi = float(np.where(g["won"].to_numpy(bool), g["odds"].to_numpy(float) - 1.0, -1.0).mean() * 100) if n else np.nan
        row = {k: v for k, v in zip(keys, vals)}
        row.update({
            "analysis": label, "bets": n, "wins": wins,
            "win_pct": 100 * p_hat, "win_CI95_low_pct": 100 * lo,
            "win_CI95_high_pct": 100 * hi, "avg_odds": avg_odds,
            "break_even_pct_avg_inverse_odds": 100 * implied,
            "hit_minus_break_even_pp": 100 * (p_hat - implied),
            "ROI_pct": roi, "z_vs_inverse_odds": z, "p_value_raw": pval,
        })
        rows.append(row)
    return pd.DataFrame(rows)


def apply_fdr(df):
    if df.empty:
        df["p_value_FDR"] = []
        return df
    df = df.copy()
    df["p_value_FDR"] = bh_adjust(df["p_value_raw"].to_numpy(float))
    return df


def make_period(year):
    if year <= 2016:
        return "2013-2016"
    if year <= 2018:
        return "2017-2018"
    if year <= 2021:
        return "2019-2021"
    return "OTHER"


def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Veritabanı bulunamadı: {DB_PATH}")
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        cols = {r[0] for r in con.execute(f'DESCRIBE "{TABLE}"').fetchall()}
        required = {"match_date", "SAAT", "EV", "DEP", "FT", "25A_num", "25Ü_num"}
        missing = required - cols
        if missing:
            raise RuntimeError(f"Gerekli sütunlar bulunamadı: {sorted(missing)}")
        df = con.execute(f'''SELECT match_date, "SAAT" AS match_time, EV, DEP, FT,
                                    "25A_num" AS odds_under, "25Ü_num" AS odds_over
                             FROM "{TABLE}"
                             WHERE match_date IS NOT NULL''').df()
    finally:
        con.close()

    print(f"Okunan satır: {len(df):,}; skor, oran, tarih ve saat alanları kontrol ediliyor...")
    df["date"] = pd.to_datetime(df["match_date"], errors="coerce").dt.normalize()
    df["score"] = df["FT"].map(parse_score)
    df = df.loc[df["date"].notna() & df["score"].notna()].copy()
    df["home_goals"] = df["score"].map(lambda x: x[0]).astype(int)
    df["away_goals"] = df["score"].map(lambda x: x[1]).astype(int)
    df["total_goals"] = df["home_goals"] + df["away_goals"]
    df["year"] = df["date"].dt.year
    df["period"] = df["year"].map(make_period)
    df["weekday"] = df["date"].dt.dayofweek.map({0:"Pazartesi",1:"Salı",2:"Çarşamba",3:"Perşembe",4:"Cuma",5:"Cumartesi",6:"Pazar"})
    # Saat alanında HH:MM, HH.MM, tarih-saat veya benzeri metinler olabilir.
    def get_hour(v):
        if v is None or pd.isna(v): return np.nan
        s = str(v).strip()
        m = re.search(r"(?:^|\D)([01]?\d|2[0-3])[:.]([0-5]\d)(?:\D|$)", s)
        if m: return int(m.group(1))
        m = re.fullmatch(r"\s*([01]?\d|2[0-3])\s*", s)
        return int(m.group(1)) if m else np.nan
    df["hour"] = df["match_time"].map(get_hour)
    for col in ["odds_under", "odds_over"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    all_sides = []
    for side, odds_col, win_col in [
        ("ALT", "odds_under", "under_won"),
        ("UST", "odds_over", "over_won"),
    ]:
        side_df = df[["date", "year", "period", "weekday", "hour", "EV", "DEP", "total_goals", odds_col]].copy()
        side_df = side_df.rename(columns={odds_col: "odds"})
        side_df["side"] = side
        side_df["won"] = (side_df["total_goals"] <= 2) if side == "ALT" else (side_df["total_goals"] >= 3)
        side_df = side_df[side_df["odds"].between(MIN_ODDS, MAX_ODDS)].copy()
        # Dar 0.05 bantlar, oranı aşağıdaki sınıfın başlangıcına yuvarlamadan yerleştirir.
        side_df["odds_bin_low"] = np.floor(side_df["odds"] / BIN_WIDTH + 1e-9) * BIN_WIDTH
        side_df["odds_bin"] = side_df["odds_bin_low"].map(lambda x: f"{x:.2f}-{x + BIN_WIDTH:.2f}")
        side_df["odds_exact"] = side_df["odds"].round(2).map(lambda x: f"{x:.2f}")
        all_sides.append(side_df)
    bets = pd.concat(all_sides, ignore_index=True)
    if bets.empty:
        raise RuntimeError("Geçerli oranlı bahis kaydı bulunamadı.")

    print(f"Geçerli maç: {len(df):,}; analiz edilen ALT/ÜST bahis kaydı: {len(bets):,}")
    print("Analiz: 0,05 oran bantları, tam oranlar, yıl/dönem, saat ve haftanın günü...")
    reports = []
    # Genel ve dönemler arası oran bantları
    for name, keys in [
        ("oran_bant_genel", ["side", "odds_bin"]),
        ("oran_bant_yil", ["side", "year", "odds_bin"]),
        ("oran_bant_donem", ["side", "period", "odds_bin"]),
        ("tam_oran_genel", ["side", "odds_exact"]),
        ("tam_oran_yil", ["side", "year", "odds_exact"]),
        ("haftanin_gunu", ["side", "weekday"]),
        ("saat_genel", ["side", "hour"]),
        ("oran_bant_saat", ["side", "hour", "odds_bin"]),
        ("oran_bant_hafta_gunu", ["side", "weekday", "odds_bin"]),
    ]:
        part = bets if name in ("oran_bant_genel", "tam_oran_genel", "haftanin_gunu", "saat_genel") else bets
        if name in ("saat_genel", "oran_bant_saat"):
            part = part[part["hour"].notna()].copy()
            part["hour"] = part["hour"].astype(int)
        out = add_group_stats(part, keys, name)
        # Küçük gruplar raporda dursun ama anlamlı bulgu olarak değerlendirilmesin.
        out["meets_min_n"] = out["bets"] >= MIN_GROUP_N
        out.loc[~out["meets_min_n"], ["p_value_raw"]] = np.nan
        out = apply_fdr(out)
        reports.append((name, out))

    for name, out in reports:
        out.to_csv(OUT_DIR / f"alt_ust_{name}.csv", index=False, encoding="utf-8-sig")

    # Yıl özeti: oranlara bakmadan tarafın temel gerçekleşme oranı.
    yearly = add_group_stats(bets, ["side", "year"], "yil_genel")
    yearly.to_csv(OUT_DIR / "alt_ust_yil_genel.csv", index=False, encoding="utf-8-sig")

    # En büyük gruplar ve dönemler arasında tekrarlanan bantlar için kısa terminal özeti.
    overall = dict((name, out) for name, out in reports)
    top = overall["oran_bant_genel"].query("bets >= @MIN_GROUP_N").copy()
    top = top.sort_values(["side", "odds_bin"])
    top.to_csv(OUT_DIR / "alt_ust_oran_bant_genel_tum.csv", index=False, encoding="utf-8-sig")
    print("\n========== ORAN BANTLARI: GENEL ==========")
    cols_show = ["side", "odds_bin", "bets", "wins", "win_pct", "win_CI95_low_pct", "win_CI95_high_pct", "avg_odds", "break_even_pct_avg_inverse_odds", "hit_minus_break_even_pp", "ROI_pct", "p_value_FDR"]
    print(top[cols_show].to_string(index=False, formatters={c: (lambda x: f"{x:.2f}") for c in ["win_pct", "win_CI95_low_pct", "win_CI95_high_pct", "avg_odds", "break_even_pct_avg_inverse_odds", "hit_minus_break_even_pp", "ROI_pct", "p_value_FDR"]}))
    print("\n========== YIL BAZINDA TUTMA ==========")
    yshow = yearly.sort_values(["side", "year"])
    print(yshow[["side", "year", "bets", "wins", "win_pct", "break_even_pct_avg_inverse_odds", "hit_minus_break_even_pp", "ROI_pct"]].to_string(index=False, formatters={c: (lambda x: f"{x:.2f}") for c in ["win_pct", "break_even_pct_avg_inverse_odds", "hit_minus_break_even_pp", "ROI_pct"]}))
    print("\nDosyalar C:\\Users\\bzdye\\Downloads klasörüne kaydedildi.")
    print("Önemli: p_value_FDR çoklu karşılaştırma düzeltmesidir; yalnızca FDR < 0,05 ve yeterli örnekli grupları inceleyin.")
    print("Not: 1/oran başa baş oranıdır; marjı arındırılmış gerçek olasılık değildir. Oran grubu tutma analizi tek başına kârlılık kanıtı değildir.")

if __name__ == "__main__":
    main()
