# -*- coding: utf-8 -*-
"""ALT/ÜST 2.5 tarihsel test v2: aynı gün bilgi sızıntısı yok, sabit taraf kıyaslaması var."""
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
PRIOR_MATCHES = 5.0
MIN_EV = 0.03
MIN_MARKET_EDGE = 0.05
MAX_ODDS = 20.0
BOOTSTRAPS = 2000
SEED = 20261012


def parse_score(value):
    if value is None or pd.isna(value):
        return None
    m = re.fullmatch(r"\s*(\d+)\s*[-:]\s*(\d+)\s*", str(value))
    return (int(m.group(1)), int(m.group(2))) if m else None


def poisson_under25(lam):
    lam = max(0.05, min(float(lam), 9.0))
    return math.exp(-lam) * (1.0 + lam + lam * lam / 2.0)


def block_bootstrap_roi(part, rng):
    """Günleri blok olarak yeniden örnekler; her gün içindeki bahisleri birlikte tutar."""
    if part.empty:
        return (float("nan"), float("nan"))
    daily = part.groupby("date", sort=False).agg(net=("net_1u", "sum"), bets=("net_1u", "size"))
    if len(daily) < 2:
        roi = float(daily["net"].sum() / daily["bets"].sum()) if daily["bets"].sum() else float("nan")
        return (roi, roi)
    nets = daily["net"].to_numpy(float)
    counts = daily["bets"].to_numpy(float)
    n_days = len(daily)
    idx = rng.integers(0, n_days, size=(BOOTSTRAPS, n_days))
    denom = counts[idx].sum(axis=1)
    roi = np.divide(nets[idx].sum(axis=1), denom, out=np.full(BOOTSTRAPS, np.nan), where=denom > 0)
    return tuple(np.nanquantile(roi, [0.025, 0.975]).tolist())


def summarize_bets(label, bets, rng):
    if bets.empty:
        return {"period": label, "bets": 0, "wins": 0, "win_pct": np.nan, "net_1u": 0.0,
                "ROI_pct": np.nan, "ROI_CI95_low_pct": np.nan, "ROI_CI95_high_pct": np.nan,
                "max_drawdown_1u": np.nan, "avg_odds": np.nan, "avg_edge_pp": np.nan}
    part = bets.sort_values(["date", "home", "away"]).copy()
    returns = part["net_1u"].to_numpy(float)
    n = len(part); wins = int(part["won"].sum()); net = float(returns.sum())
    lo, hi = block_bootstrap_roi(part, rng)
    equity = np.cumsum(returns)
    peak = np.maximum.accumulate(np.r_[0.0, equity])[1:]
    dd = peak - equity
    return {"period": label, "bets": n, "wins": wins, "win_pct": 100 * wins / n,
            "net_1u": net, "ROI_pct": 100 * net / n,
            "ROI_CI95_low_pct": 100 * lo, "ROI_CI95_high_pct": 100 * hi,
            "max_drawdown_1u": float(dd.max()) if len(dd) else 0.0,
            "avg_odds": float(part["odds"].mean()),
            "avg_edge_pp": float(part["edge_pp"].mean()) if "edge_pp" in part else np.nan}


def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Veritabanı bulunamadı: {DB_PATH}")
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        cols = {r[0] for r in con.execute(f"DESCRIBE {TABLE}").fetchall()}
        required = {"match_date", "EV", "DEP", "FT", "25A_num", "25Ü_num"}
        missing = required - cols
        if missing:
            raise RuntimeError(f"Gerekli sütunlar bulunamadı: {sorted(missing)}")
        df = con.execute(f'''SELECT match_date, EV, DEP, FT,
                                   "25A_num" AS odds_under, "25Ü_num" AS odds_over
                             FROM {TABLE}
                             WHERE match_date IS NOT NULL
                             ORDER BY match_date''').df()
    finally:
        con.close()

    print(f"Okunan satır: {len(df):,}; skor ve tarihler doğrulanıyor...")
    df["match_date"] = pd.to_datetime(df["match_date"], errors="coerce").dt.normalize()
    df["score"] = df["FT"].map(parse_score)
    df = df.loc[df["score"].notna() & df["match_date"].notna()].copy().reset_index(drop=True)
    df["home_score"] = df["score"].map(lambda x: x[0]).astype(int)
    df["away_score"] = df["score"].map(lambda x: x[1]).astype(int)
    df["odds_under"] = pd.to_numeric(df["odds_under"], errors="coerce")
    df["odds_over"] = pd.to_numeric(df["odds_over"], errors="coerce")
    df["year"] = df["match_date"].dt.year
    if df.empty:
        raise RuntimeError("Geçerli tarih ve FT skoru olan maç bulunamadı.")

    # team -> venue -> [matches, scored goals, conceded goals]
    stats = defaultdict(lambda: {"H": [0, 0.0, 0.0], "A": [0, 0.0, 0.0]})
    total_matches = 0
    sum_hg = sum_ag = 0.0
    predictions = []
    unique_dates = df["match_date"].drop_duplicates().sort_values().tolist()
    print(f"Geçerli maç: {len(df):,}; tarih aralığı: {df.year.min()}-{df.year.max()}")
    print("Tahminler gün grupları halinde üretiliyor; aynı günün skorları tahmine girmeyecek...")

    for date in unique_dates:
        day = df.loc[df["match_date"] == date]
        # ÖNCE günün tüm maçlarını yalnızca önceki günlerin istatistikleriyle tahmin et.
        for row in day.itertuples(index=False):
            home = str(row.EV).strip() if pd.notna(row.EV) else ""
            away = str(row.DEP).strip() if pd.notna(row.DEP) else ""
            hg, ag = int(row.home_score), int(row.away_score)
            year = int(row.year)
            if total_matches < 20 or not home or not away or home == away:
                continue

            global_h = sum_hg / total_matches
            global_a = sum_ag / total_matches
            hs = stats[home]["H"]
            ads = stats[away]["A"]
            home_attack = (hs[1] + PRIOR_MATCHES * global_h) / (hs[0] + PRIOR_MATCHES)
            home_defence = (hs[2] + PRIOR_MATCHES * global_a) / (hs[0] + PRIOR_MATCHES)
            away_attack = (ads[1] + PRIOR_MATCHES * global_a) / (ads[0] + PRIOR_MATCHES)
            away_defence = (ads[2] + PRIOR_MATCHES * global_h) / (ads[0] + PRIOR_MATCHES)
            lam_h = max(0.15, min(4.5, (home_attack + away_defence) / 2.0))
            lam_a = max(0.15, min(4.5, (away_attack + home_defence) / 2.0))
            p_under = poisson_under25(lam_h + lam_a)
            p_over = 1.0 - p_under
            ou = float(row.odds_under) if pd.notna(row.odds_under) else float("nan")
            oo = float(row.odds_over) if pd.notna(row.odds_over) else float("nan")
            valid_u = math.isfinite(ou) and 1.01 <= ou <= MAX_ODDS
            valid_o = math.isfinite(oo) and 1.01 <= oo <= MAX_ODDS
            inv_u = 1 / ou if valid_u else float("nan")
            inv_o = 1 / oo if valid_o else float("nan")
            denom = inv_u + inv_o if valid_u and valid_o else float("nan")
            market_u = inv_u / denom if math.isfinite(denom) and denom > 0 else float("nan")
            market_o = inv_o / denom if math.isfinite(denom) and denom > 0 else float("nan")
            actual_u = int(hg + ag <= 2)
            actual_o = 1 - actual_u
            period = "ISINMA" if year <= 2016 else ("DOĞRULAMA" if year <= 2018 else "TEST_OOS")
            candidates = []
            if valid_u and math.isfinite(market_u):
                ev_u = p_under * ou - 1
                edge_u = p_under - market_u
                if ev_u >= MIN_EV and edge_u >= MIN_MARKET_EDGE:
                    candidates.append(("ALT", ou, p_under, market_u, edge_u, ev_u, actual_u))
            if valid_o and math.isfinite(market_o):
                ev_o = p_over * oo - 1
                edge_o = p_over - market_o
                if ev_o >= MIN_EV and edge_o >= MIN_MARKET_EDGE:
                    candidates.append(("ÜST", oo, p_over, market_o, edge_o, ev_o, actual_o))
            pick = max(candidates, key=lambda x: x[4]) if candidates else None
            predictions.append({
                "date": date, "year": year, "period": period, "home": home, "away": away,
                "score": f"{hg}-{ag}", "total_goals": hg + ag, "actual_under": actual_u,
                "odds_under": ou, "odds_over": oo, "model_p_under": p_under,
                "model_p_over": p_over, "market_p_under_no_vig": market_u,
                "market_p_over_no_vig": market_o, "lambda_home": lam_h, "lambda_away": lam_a,
                "pick_side": pick[0] if pick else "", "pick_odds": pick[1] if pick else np.nan,
                "pick_model_prob": pick[2] if pick else np.nan,
                "pick_market_prob_no_vig": pick[3] if pick else np.nan,
                "pick_edge_pp": 100 * pick[4] if pick else np.nan,
                "pick_model_EV_pct": 100 * pick[5] if pick else np.nan,
                "pick_won": pick[6] if pick else np.nan,
                "pick_net_1u": (pick[1] - 1) if pick and pick[6] else (-1.0 if pick else np.nan),
            })

        # SADECE günün tüm tahminleri üretildikten sonra günün sonuçlarını geçmişe ekle.
        for row in day.itertuples(index=False):
            home = str(row.EV).strip() if pd.notna(row.EV) else ""
            away = str(row.DEP).strip() if pd.notna(row.DEP) else ""
            if not home or not away or home == away:
                continue
            hg, ag = int(row.home_score), int(row.away_score)
            hs = stats[home]["H"]
            hs[0] += 1; hs[1] += hg; hs[2] += ag
            ads = stats[away]["A"]
            ads[0] += 1; ads[1] += ag; ads[2] += hg
            total_matches += 1
            sum_hg += hg; sum_ag += ag

    pred = pd.DataFrame(predictions)
    if pred.empty:
        raise RuntimeError("Model tahmini üretilemedi.")
    pred_path = OUT_DIR / "alt_ust_model_v2_tahminler.csv"
    summary_path = OUT_DIR / "alt_ust_model_v2_ozet.csv"
    yearly_path = OUT_DIR / "alt_ust_model_v2_yillik.csv"
    pred.to_csv(pred_path, index=False, encoding="utf-8-sig")

    rng = np.random.default_rng(SEED)
    summary = []
    # Model seçimi ve basit ALT/ÜST kıyasları: aynı test döneminde ayrı ayrı raporlanır.
    for period in ["ISINMA", "DOĞRULAMA", "TEST_OOS"]:
        p = pred[pred.period == period]
        model = p[p.pick_side != ""].copy()
        model_bets = pd.DataFrame({"date": model.date, "home": model.home, "away": model.away,
                                   "odds": model.pick_odds, "won": model.pick_won.astype(int),
                                   "net_1u": model.pick_net_1u, "edge_pp": model.pick_edge_pp})
        summary.append(summarize_bets(f"{period}_MODEL", model_bets, rng))
        for side, odds_col, won_col in [("SUREKLI_ALT", "odds_under", "actual_under"),
                                        ("SUREKLI_UST", "odds_over", None)]:
            valid = p[p[odds_col].between(1.01, MAX_ODDS)].copy()
            if side == "SUREKLI_ALT":
                valid["won"] = valid["actual_under"].astype(int)
            else:
                valid["won"] = (1 - valid["actual_under"]).astype(int)
            valid["odds"] = valid[odds_col].astype(float)
            valid["net_1u"] = np.where(valid.won == 1, valid.odds - 1, -1.0)
            summary.append(summarize_bets(f"{period}_{side}", valid[["date", "home", "away", "odds", "won", "net_1u"]], rng))

    summary_df = pd.DataFrame(summary)
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")
    yearly_rows = []
    for (period, year), p in pred.groupby(["period", "year"]):
        for side, odds_col, won_expr in [
            ("ALT", "odds_under", p["actual_under"] == 1),
            ("UST", "odds_over", p["actual_under"] == 0),
        ]:
            q = p[p[odds_col].between(1.01, MAX_ODDS)].copy()
            if q.empty:
                continue
            q["won"] = won_expr.loc[q.index].astype(int)
            q["odds"] = q[odds_col].astype(float)
            q["net"] = np.where(q.won == 1, q.odds - 1, -1.0)
            yearly_rows.append({"period": period, "year": int(year), "strategy": f"SUREKLI_{side}",
                                "bets": len(q), "wins": int(q.won.sum()),
                                "win_pct": 100 * q.won.mean(), "net_1u": float(q.net.sum()),
                                "ROI_pct": 100 * q.net.mean()})
        q = p[p.pick_side != ""].copy()
        if not q.empty:
            yearly_rows.append({"period": period, "year": int(year), "strategy": "MODEL",
                                "bets": len(q), "wins": int(q.pick_won.sum()),
                                "win_pct": 100 * q.pick_won.mean(), "net_1u": float(q.pick_net_1u.sum()),
                                "ROI_pct": 100 * q.pick_net_1u.mean()})
    yearly_df = pd.DataFrame(yearly_rows)
    yearly_df.to_csv(yearly_path, index=False, encoding="utf-8-sig")

    # Kalibrasyon: tüm tahminlerde Brier score; piyasa kıyası sadece iki oran da mevcutken.
    y = pred.actual_under.to_numpy(float)
    pm = pred.model_p_under.to_numpy(float)
    mask_market = pred.market_p_under_no_vig.notna().to_numpy()
    brier_model = float(np.mean((pm - y) ** 2))
    brier_market = float(np.mean((pred.loc[mask_market, "market_p_under_no_vig"].to_numpy(float) - y[mask_market]) ** 2)) if mask_market.any() else np.nan
    test = pred[pred.period == "TEST_OOS"]
    test_y = test.actual_under.to_numpy(float)
    test_pm = test.model_p_under.to_numpy(float)
    test_market_mask = test.market_p_under_no_vig.notna().to_numpy()
    test_brier_model = float(np.mean((test_pm - test_y) ** 2)) if len(test) else np.nan
    test_brier_market = float(np.mean((test.loc[test_market_mask, "market_p_under_no_vig"].to_numpy(float) - test_y[test_market_mask]) ** 2)) if test_market_mask.any() else np.nan

    print("\n========== V2 SONUÇ ==========")
    print(f"Geçerli maç: {len(df):,} | tarih: {df.year.min()}-{df.year.max()} | gün grupları: {len(unique_dates):,}")
    print("Aynı günün maç sonuçları, o günkü hiçbir tahminde kullanılmadı.")
    print(summary_df.to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    print(f"\nBrier (tüm dönem): model={brier_model:.5f}; piyasa marj arındırılmış={brier_market:.5f}")
    print(f"Brier (TEST_OOS): model={test_brier_model:.5f}; piyasa marj arındırılmış={test_brier_market:.5f}")
    print("\nDosyalar:")
    print(pred_path); print(summary_path); print(yearly_path)
    print("UYARI: Lig sütunu olmadığından takım adları ligler arasında çakışabilir.")
    print("UYARI: Model basit bir gol ortalaması modelidir; pozitif sonuç görülse bile tek başına kârlılık kanıtı değildir.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        raise
