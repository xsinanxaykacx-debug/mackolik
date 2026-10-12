# -*- coding: utf-8 -*-
"""Tarihsel, sızıntısız ALT/ÜST 2.5 model testi. DuckDB salt okunur açılır."""
from __future__ import annotations
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

DB_PATH = Path(r"C:\Users\bzdye\Downloads\DATA.duckdb")
OUT_DIR = Path(r"C:\Users\bzdye\Downloads")
TABLE = "matches_analysis"
PRIOR_MATCHES = 5.0       # takım oranlarını genel ortalamaya yumuşatma
MIN_EV = 0.03             # oran üzerinden tahmini beklenen getiri eşiği: %3
MIN_MARKET_EDGE = 0.05    # marjdan arındırılmış piyasa olasılığına fark: 5 puan
MAX_ODDS = 20.0
BOOTSTRAPS = 2000
SEED = 20261012


def parse_score(value):
    if value is None or pd.isna(value):
        return None
    m = re.fullmatch(r"\s*(\d+)\s*[-:]\s*(\d+)\s*", str(value))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def poisson_under25(lam):
    lam = max(0.05, min(float(lam), 9.0))
    return math.exp(-lam) * (1.0 + lam + (lam * lam / 2.0))


def ci_bootstrap(returns, rng):
    arr = np.asarray(returns, dtype=float)
    if len(arr) < 2:
        return (float("nan"), float("nan"))
    # İşlem bazlı bootstrap; maçlar arası bağımlılığı tamamen gidermez.
    idx = rng.integers(0, len(arr), size=(BOOTSTRAPS, len(arr)))
    means = arr[idx].mean(axis=1)
    return tuple(np.quantile(means, [0.025, 0.975]).tolist())


def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Veritabanı bulunamadı: {DB_PATH}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[1/5] Veritabanı salt okunur açılıyor...")
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        cols = {r[0] for r in con.execute(f"DESCRIBE {TABLE}").fetchall()}
        required = {"match_date", "EV", "DEP", "FT", "25A_num", "25Ü_num"}
        missing = required - cols
        if missing:
            raise RuntimeError(f"Gerekli sütunlar bulunamadı: {sorted(missing)}")
        df = con.execute(f'''SELECT match_date, EV, DEP, FT, "25A_num", "25Ü_num"
                             FROM {TABLE}
                             WHERE match_date IS NOT NULL
                             ORDER BY match_date, EV, DEP''').df()
    finally:
        con.close()

    print(f"[2/5] Okunan satır: {len(df):,}; skorlar doğrulanıyor...")
    df["match_date"] = pd.to_datetime(df["match_date"], errors="coerce")
    parsed_scores = [parse_score(v) for v in df["FT"].tolist()]
    df["_parsed_score"] = parsed_scores
    df = df.loc[df["_parsed_score"].notna() & df["match_date"].notna()].copy().reset_index(drop=True)
    df["home_score"] = df["_parsed_score"].map(lambda x: x[0]).astype(int)
    df["away_score"] = df["_parsed_score"].map(lambda x: x[1]).astype(int)
    df.drop(columns=["_parsed_score"], inplace=True)
    df["25A_num"] = pd.to_numeric(df["25A_num"], errors="coerce")
    df["25Ü_num"] = pd.to_numeric(df["25Ü_num"], errors="coerce")
    df["year"] = df["match_date"].dt.year
    if df.empty:
        raise RuntimeError("Geçerli tarih ve FT skoru olan maç bulunamadı.")

    min_year, max_year = int(df.year.min()), int(df.year.max())
    print(f"[3/5] Geçerli maç: {len(df):,}; tarih aralığı: {min_year}-{max_year}")
    if max_year < 2019:
        print("UYARI: Veri 2019'a ulaşmıyor; son dönem testi için tarih sınırını veri aralığına göre ayarlayın.")

    # stats[team][venue] = [maç, atılan gol, yenilen gol]. Yalnızca geçmiş maçlar.
    stats = defaultdict(lambda: {"H": [0, 0.0, 0.0], "A": [0, 0.0, 0.0]})
    total_matches = 0
    sum_hg = 0.0
    sum_ag = 0.0
    picks = []

    print("[4/5] Geçmişe dayalı takım özellikleri ve tahminler hesaplanıyor...")
    for row in df.itertuples(index=False):
        date = row.match_date
        home = str(row.EV).strip() if pd.notna(row.EV) else ""
        away = str(row.DEP).strip() if pd.notna(row.DEP) else ""
        hg, ag = int(row.home_score), int(row.away_score)
        year = int(row.year)

        # En az 20 geçmiş maç olmadan tahmin üretmeyerek soğuk başlangıç gürültüsünü azalt.
        if total_matches >= 20 and home and away and home != "" and away != "":
            global_h = sum_hg / total_matches
            global_a = sum_ag / total_matches
            hh = stats[home]["H"]
            aa = stats[away]["A"]
            ha = stats[home]["H"]
            ad = stats[away]["A"]
            # Bayesçi küçültme: az geçmişi olan takımın oranı genel ortalamaya yaklaşır.
            home_attack = (hh[1] + PRIOR_MATCHES * global_h) / (hh[0] + PRIOR_MATCHES)
            home_defence = (ha[2] + PRIOR_MATCHES * global_a) / (ha[0] + PRIOR_MATCHES)
            away_attack = (aa[1] + PRIOR_MATCHES * global_a) / (aa[0] + PRIOR_MATCHES)
            away_defence = (ad[2] + PRIOR_MATCHES * global_h) / (ad[0] + PRIOR_MATCHES)
            lam_h = max(0.15, min(4.5, (home_attack + away_defence) / 2.0))
            lam_a = max(0.15, min(4.5, (away_attack + home_defence) / 2.0))
            p_under = poisson_under25(lam_h + lam_a)
            p_over = 1.0 - p_under

            odds_under = float(row._4) if row._4 is not None and not pd.isna(row._4) else float("nan")
            odds_over = float(row._5) if row._5 is not None and not pd.isna(row._5) else float("nan")
            valid_u = math.isfinite(odds_under) and 1.01 <= odds_under <= MAX_ODDS
            valid_o = math.isfinite(odds_over) and 1.01 <= odds_over <= MAX_ODDS
            inv_u = 1.0 / odds_under if valid_u else float("nan")
            inv_o = 1.0 / odds_over if valid_o else float("nan")
            denom = (inv_u + inv_o) if valid_u and valid_o else float("nan")
            market_u = inv_u / denom if math.isfinite(denom) and denom > 0 else float("nan")
            market_o = inv_o / denom if math.isfinite(denom) and denom > 0 else float("nan")
            actual_under = int(hg + ag <= 2)
            actual_over = 1 - actual_under
            candidates = []
            if valid_u:
                ev = p_under * odds_under - 1.0
                edge = p_under - market_u if math.isfinite(market_u) else float("nan")
                if ev >= MIN_EV and math.isfinite(edge) and edge >= MIN_MARKET_EDGE:
                    candidates.append(("ALT", odds_under, p_under, market_u, edge, ev, actual_under, lam_h, lam_a))
            if valid_o:
                ev = p_over * odds_over - 1.0
                edge = p_over - market_o if math.isfinite(market_o) else float("nan")
                if ev >= MIN_EV and math.isfinite(edge) and edge >= MIN_MARKET_EDGE:
                    candidates.append(("ÜST", odds_over, p_over, market_o, edge, ev, actual_over, lam_h, lam_a))
            # Aynı maçta en fazla bir seçim: modelin en yüksek piyasa farkı.
            if candidates:
                side, odds, p_model, p_market, edge, ev, won, lh, la = max(candidates, key=lambda x: x[4])
                # Sabit 1 birim bahis; net getiri.
                net = odds - 1.0 if won else -1.0
                period = "ISINMA" if year <= 2016 else ("DOĞRULAMA" if year <= 2018 else "TEST_OOS")
                picks.append({"date": date, "year": year, "period": period, "home": home, "away": away,
                              "score": f"{hg}-{ag}", "side": side, "odds": odds, "model_prob": p_model,
                              "market_prob_no_vig": p_market, "edge_pp": edge * 100.0,
                              "model_EV_pct": ev * 100.0, "won": int(won), "net_1u": net,
                              "lambda_home": lh, "lambda_away": la})

        # Bu maçın bilgisi tahminden SONRA geçmişe eklenir.
        if home and away:
            sh = stats[home]["H"]
            sh[0] += 1; sh[1] += hg; sh[2] += ag
            sa = stats[away]["A"]
            sa[0] += 1; sa[1] += ag; sa[2] += hg
        total_matches += 1
        sum_hg += hg
        sum_ag += ag

    picks_df = pd.DataFrame(picks)
    picks_path = OUT_DIR / "alt_ust_model_secimler.csv"
    summary_path = OUT_DIR / "alt_ust_model_ozet.csv"
    yearly_path = OUT_DIR / "alt_ust_model_yillik.csv"
    picks_df.to_csv(picks_path, index=False, encoding="utf-8-sig")

    print("[5/5] ROI, düşüş ve bootstrap güven aralığı hesaplanıyor...")
    rng = np.random.default_rng(SEED)
    summaries = []
    if not picks_df.empty:
        for period in ["ISINMA", "DOĞRULAMA", "TEST_OOS"]:
            part = picks_df[picks_df.period == period].sort_values(["date", "home", "away"])
            if part.empty:
                summaries.append({"period": period, "bets": 0, "wins": 0, "win_pct": np.nan,
                                  "net_1u": 0.0, "ROI_pct": np.nan, "ROI_CI95_low_pct": np.nan,
                                  "ROI_CI95_high_pct": np.nan, "max_drawdown_1u": np.nan,
                                  "avg_odds": np.nan, "avg_edge_pp": np.nan})
                continue
            returns = part["net_1u"].to_numpy(dtype=float)
            n = len(part); wins = int(part["won"].sum()); net = float(returns.sum())
            ci_lo, ci_hi = ci_bootstrap(returns, rng)
            equity = np.cumsum(returns)
            peak = np.maximum.accumulate(np.r_[0.0, equity])[1:]
            dd = peak - equity
            summaries.append({"period": period, "bets": n, "wins": wins, "win_pct": 100.0*wins/n,
                              "net_1u": net, "ROI_pct": 100.0*net/n,
                              "ROI_CI95_low_pct": 100.0*ci_lo, "ROI_CI95_high_pct": 100.0*ci_hi,
                              "max_drawdown_1u": float(dd.max()) if len(dd) else 0.0,
                              "avg_odds": float(part.odds.mean()), "avg_edge_pp": float(part.edge_pp.mean())})
    else:
        summaries.append({"period": "TÜMÜ", "bets": 0, "wins": 0, "win_pct": np.nan, "net_1u": 0.0,
                          "ROI_pct": np.nan, "ROI_CI95_low_pct": np.nan, "ROI_CI95_high_pct": np.nan,
                          "max_drawdown_1u": np.nan, "avg_odds": np.nan, "avg_edge_pp": np.nan})
    summary_df = pd.DataFrame(summaries)
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")

    if not picks_df.empty:
        yearly = picks_df.groupby(["period", "year", "side"], dropna=False).agg(
            bets=("won", "size"), wins=("won", "sum"), net_1u=("net_1u", "sum"),
            avg_odds=("odds", "mean"), avg_edge_pp=("edge_pp", "mean")).reset_index()
        yearly["win_pct"] = 100.0 * yearly["wins"] / yearly["bets"]
        yearly["ROI_pct"] = 100.0 * yearly["net_1u"] / yearly["bets"]
    else:
        yearly = pd.DataFrame(columns=["period", "year", "side", "bets", "wins", "net_1u", "avg_odds", "avg_edge_pp", "win_pct", "ROI_pct"])
    yearly.to_csv(yearly_path, index=False, encoding="utf-8-sig")

    print("\n========== SONUÇ ==========")
    print(f"Veri: {len(df):,} geçerli maç | {min_year}-{max_year}")
    print(f"Tahmin koşulu: EV >= %{MIN_EV*100:.0f}, piyasa farkı >= {MIN_MARKET_EDGE*100:.0f} yüzde puan")
    if summary_df.empty:
        print("Hiç sonuç üretilemedi.")
    else:
        print(summary_df.to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    print("\nDosyalar:")
    print(picks_path)
    print(summary_path)
    print(yearly_path)
    print("\nUYARI: Takım adları lig bilgisi olmadan eşleştirilir; aynı isimli farklı lig takımları karışabilir.")
    print("UYARI: Bootstrap aralığı bahis başına yeniden örneklemeye dayanır; maçlar arası bağımlılığı bütünüyle modellemez.")
    print("UYARI: Model avantajı tahmini bir varsayımdır; yalnızca TEST_OOS döneminin sonucu değerlendirilmelidir.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        raise
