
# -*- coding: utf-8 -*-

import json
from pathlib import Path

import duckdb
import pandas as pd


DB = Path(r"C:\Users\bzdye\Downloads\DATA.duckdb")
OUT = Path(r"C:\Users\bzdye\Downloads")
TABLE = "matches_analysis"


def main():
    if not DB.exists():
        raise FileNotFoundError(f"Veritabanı bulunamadı: {DB}")

    con = duckdb.connect(str(DB), read_only=True)

    try:
        # 1. FT skoru ile MS sonucunun uyuşmadığı maçlar
        mismatches = con.execute(
            f"""
            WITH parsed AS (
                SELECT *,
                    TRY_CAST(
                        split_part(TRIM("FT"), '-', 1) AS INTEGER
                    ) AS home_goals,
                    TRY_CAST(
                        split_part(TRIM("FT"), '-', 2) AS INTEGER
                    ) AS away_goals
                FROM "{TABLE}"
            ),
            evaluated AS (
                SELECT *,
                    CASE
                        WHEN home_goals > away_goals THEN '1'
                        WHEN home_goals = away_goals THEN 'X'
                        WHEN home_goals < away_goals THEN '2'
                    END AS score_result
                FROM parsed
            )
            SELECT
                match_date,
                "TARİH", "SAAT", "EV", "DEP",
                "HT", "FT", "MS",
                score_result,
                "MS1", "MSX", "MS2"
            FROM evaluated
            WHERE score_result IS NOT NULL
              AND TRIM("MS") IN ('1', 'X', '2')
              AND TRIM("MS") <> score_result
            ORDER BY match_date, "SAAT", "EV", "DEP"
            """
        ).df()

        mismatch_path = OUT / "1X2_tutarsiz_maclar.csv"
        mismatches.to_csv(
            mismatch_path, index=False, encoding="utf-8-sig"
        )

        print("=== FT / MS TUTARSIZLIKLARI ===")
        print(f"Uyuşmayan maç sayısı: {len(mismatches):,}")
        print(f"Dosya: {mismatch_path}")

        if not mismatches.empty:
            print(mismatches.to_string(index=False))

        # 2. Her pazar için maç sonuçlarını ve oranları al
        rows = con.execute(
            f"""
            SELECT
                YEAR(match_date) AS year,
                TRIM("MS") AS outcome,
                "MS1_num" AS odds_ms1,
                "MSX_num" AS odds_msx,
                "MS2_num" AS odds_ms2
            FROM "{TABLE}"
            WHERE match_date IS NOT NULL
              AND TRIM("MS") IN ('1', 'X', '2')
            ORDER BY match_date
            """
        ).df()

        markets = [
            ("MS1", "odds_ms1", "1"),
            ("MSX", "odds_msx", "X"),
            ("MS2", "odds_ms2", "2"),
        ]

        annual = []
        missing = []

        for market, odds_col, target in markets:
            valid = rows[
                rows[odds_col].notna() & (rows[odds_col] > 1)
            ].copy()

            missing_rows = rows[
                rows[odds_col].isna() | (rows[odds_col] <= 1)
            ]

            missing.append({
                "market": market,
                "total_matches": len(rows),
                "valid_bets": len(valid),
                "missing_or_invalid_odds": len(missing_rows),
            })

            valid["win"] = (valid["outcome"] == target).astype(int)
            valid["profit"] = valid.apply(
                lambda r: float(r[odds_col]) - 1.0
                if r["outcome"] == target else -1.0,
                axis=1,
            )

            grouped = valid.groupby("year", sort=True).agg(
                bets=("profit", "size"),
                wins=("win", "sum"),
                net_profit=("profit", "sum"),
                average_odds=(odds_col, "mean"),
            ).reset_index()

            grouped["market"] = market
            grouped["losses"] = grouped["bets"] - grouped["wins"]
            grouped["win_rate"] = grouped["wins"] / grouped["bets"]
            grouped["roi"] = grouped["net_profit"] / grouped["bets"]

            annual.append(grouped)

        annual_df = pd.concat(annual, ignore_index=True)
        annual_df = annual_df[
            [
                "year", "market", "bets", "wins", "losses",
                "win_rate", "average_odds", "net_profit", "roi"
            ]
        ]

        annual_path = OUT / "1X2_yillik_roi_detay.csv"
        annual_df.to_csv(
            annual_path, index=False, encoding="utf-8-sig"
        )

        missing_df = pd.DataFrame(missing)
        missing_path = OUT / "1X2_oran_eksikleri.csv"
        missing_df.to_csv(
            missing_path, index=False, encoding="utf-8-sig"
        )

        print("\n=== YILLIK ROI ===")
        print(annual_df.to_string(
            index=False,
            formatters={
                "win_rate": lambda x: f"{x:.2%}",
                "average_odds": lambda x: f"{x:.3f}",
                "net_profit": lambda x: f"{x:.2f}",
                "roi": lambda x: f"{x:.2%}",
            },
        ))

        print("\n=== EKSİK / GEÇERSİZ ORANLAR ===")
        print(missing_df.to_string(index=False))

        print("\n=== DOSYALAR ===")
        print(annual_path)
        print(missing_path)
        print(mismatch_path)

    finally:
        con.close()


if __name__ == "__main__":
    main()
