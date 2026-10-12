
# -*- coding: utf-8 -*-
"""
DATA.xlsx / DuckDB - 1X2 temel performans raporu

Kaynak:
  DATA.duckdb
  matches_analysis

Üretilen dosyalar:
  1X2_temel_rapor.json
  1X2_yillik_rapor.csv
  1X2_bahis_performansi.csv

Ham veri değiştirilmez.
"""

import json
import math
from pathlib import Path

import duckdb
import pandas as pd


DB_PATH = Path(r"C:\Users\bzdye\Downloads\DATA.duckdb")
OUT_DIR = Path(r"C:\Users\bzdye\Downloads")

TABLE = "matches_analysis"


def wilson_interval(wins, total, z=1.959963984540054):
    """Kazanma oranı için Wilson %95 güven aralığı."""
    if total <= 0:
        return None, None

    p = wins / total
    z2 = z * z
    den = 1 + z2 / total
    center = (p + z2 / (2 * total)) / den
    margin = (
        z
        * math.sqrt(
            p * (1 - p) / total
            + z2 / (4 * total * total)
        )
        / den
    )

    return max(0.0, center - margin), min(1.0, center + margin)


def roi_confidence_interval(profits, z=1.959963984540054):
    """
    Maç başına net kâr üzerinden yaklaşık %95 normal güven aralığı.
    Her bahiste bir birim sabit stake varsayılır.
    """
    n = len(profits)

    if n < 2:
        return None, None

    mean_profit = sum(profits) / n
    variance = sum((x - mean_profit) ** 2 for x in profits) / (n - 1)
    standard_error = math.sqrt(variance / n)

    return (
        mean_profit - z * standard_error,
        mean_profit + z * standard_error,
    )


def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Veritabanı bulunamadı: {DB_PATH}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=True)

    try:
        table_exists = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name = ?",
            [TABLE],
        ).fetchone()[0]

        if not table_exists:
            raise RuntimeError(f"{TABLE} tablosu bulunamadı.")

        total_rows = con.execute(
            f'SELECT COUNT(*) FROM "{TABLE}"'
        ).fetchone()[0]

        # Skor ve maç sonucu tutarlılığı.
        score_check = con.execute(
            f"""
            WITH parsed AS (
                SELECT
                    TRIM("FT") AS ft,
                    TRIM("MS") AS ms,
                    CASE
                        WHEN regexp_full_match(
                            TRIM("FT"), '[0-9]+-[0-9]+'
                        )
                        THEN TRY_CAST(split_part(TRIM("FT"), '-', 1) AS INTEGER)
                    END AS home_goals,
                    CASE
                        WHEN regexp_full_match(
                            TRIM("FT"), '[0-9]+-[0-9]+'
                        )
                        THEN TRY_CAST(split_part(TRIM("FT"), '-', 2) AS INTEGER)
                    END AS away_goals
                FROM "{TABLE}"
            ),
            evaluated AS (
                SELECT *,
                    CASE
                        WHEN home_goals > away_goals THEN '1'
                        WHEN home_goals = away_goals THEN 'X'
                        WHEN home_goals < away_goals THEN '2'
                    END AS score_outcome
                FROM parsed
            )
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (
                    WHERE home_goals IS NULL OR away_goals IS NULL
                ) AS invalid_score,
                COUNT(*) FILTER (
                    WHERE ms IS NULL OR ms NOT IN ('1', 'X', '2')
                ) AS invalid_ms,
                COUNT(*) FILTER (
                    WHERE score_outcome IS NOT NULL
                      AND ms IN ('1', 'X', '2')
                      AND ms <> score_outcome
                ) AS inconsistent_result
            FROM evaluated
            """
        ).fetchone()

        score_summary = {
            "total": score_check[0],
            "invalid_ft_score": score_check[1],
            "invalid_ms_result": score_check[2],
            "ft_ms_inconsistency": score_check[3],
        }

        # Sonuç frekansları.
        outcome_rows = con.execute(
            f"""
            SELECT TRIM("MS") AS outcome, COUNT(*) AS matches
            FROM "{TABLE}"
            GROUP BY TRIM("MS")
            ORDER BY TRIM("MS")
            """
        ).fetchall()

        outcome_counts = {
            str(outcome): int(count)
            for outcome, count in outcome_rows
        }

        # Yıllık dağılım.
        yearly_df = con.execute(
            f"""
            SELECT
                YEAR(match_date) AS year,
                COUNT(*) AS matches,
                COUNT(*) FILTER (WHERE TRIM("MS") = '1') AS home_wins,
                COUNT(*) FILTER (WHERE TRIM("MS") = 'X') AS draws,
                COUNT(*) FILTER (WHERE TRIM("MS") = '2') AS away_wins
            FROM "{TABLE}"
            WHERE match_date IS NOT NULL
            GROUP BY YEAR(match_date)
            ORDER BY YEAR(match_date)
            """
        ).df()

        if not yearly_df.empty:
            yearly_df.to_csv(
                OUT_DIR / "1X2_yillik_rapor.csv",
                index=False,
                encoding="utf-8-sig",
            )

        # Her sonuç seçimi için sabit 1 birim stake.
        selections = [
            ("MS1", "MS1_num", "1"),
            ("MSX", "MSX_num", "X"),
            ("MS2", "MS2_num", "2"),
        ]

        performance = []

        for market, odds_col, target in selections:
            rows = con.execute(
                f"""
                SELECT
                    TRIM("MS") AS outcome,
                    "{odds_col}" AS odds
                FROM "{TABLE}"
                WHERE TRIM("MS") IN ('1', 'X', '2')
                  AND "{odds_col}" IS NOT NULL
                  AND "{odds_col}" > 1
                """
            ).fetchall()

            n = len(rows)
            wins = 0
            profits = []
            odds_values = []

            for outcome, odds in rows:
                odds = float(odds)
                odds_values.append(odds)

                if outcome == target:
                    wins += 1
                    profits.append(odds - 1.0)
                else:
                    profits.append(-1.0)

            roi = sum(profits) / n if n else None
            win_rate = wins / n if n else None

            win_low, win_high = wilson_interval(wins, n)
            roi_low, roi_high = roi_confidence_interval(profits)

            performance.append({
                "market": market,
                "selection": target,
                "bets": n,
                "wins": wins,
                "losses": n - wins,
                "win_rate": win_rate,
                "win_rate_ci95_low": win_low,
                "win_rate_ci95_high": win_high,
                "average_odds": (
                    sum(odds_values) / len(odds_values)
                    if odds_values else None
                ),
                "total_stake": float(n),
                "net_profit": sum(profits),
                "roi": roi,
                "roi_ci95_low_approx": roi_low,
                "roi_ci95_high_approx": roi_high,
            })

        performance_df = pd.DataFrame(performance)
        performance_df.to_csv(
            OUT_DIR / "1X2_bahis_performansi.csv",
            index=False,
            encoding="utf-8-sig",
        )

        report = {
            "database": str(DB_PATH),
            "table": TABLE,
            "record_count": total_rows,
            "score_validation": score_summary,
            "outcome_counts": outcome_counts,
            "yearly_report": yearly_df.to_dict(orient="records"),
            "betting_performance": performance,
            "methodology": {
                "stake_per_bet": 1,
                "roi_formula": "(net profit / total stake)",
                "win_ci": "Wilson 95% confidence interval",
                "roi_ci": (
                    "Approximate normal 95% confidence interval; "
                    "not a time-independent validation"
                ),
                "important_note": (
                    "These are unconditional 1X2 baselines, not "
                    "a profitable strategy claim. Each market is "
                    "evaluated only where its odds are available "
                    "and greater than 1."
                ),
            },
        }

        json_path = OUT_DIR / "1X2_temel_rapor.json"
        with json_path.open("w", encoding="utf-8") as f:
            json.dump(
                report,
                f,
                ensure_ascii=False,
                indent=2,
                default=str,
            )

        print("\n=== VERI OZETI ===")
        print(f"Analiz tablosu: {TABLE}")
        print(f"Toplam kayit: {total_rows:,}")

        print("\n=== FT / MS TUTARLILIK KONTROLU ===")
        for key, value in score_summary.items():
            print(f"{key}: {value:,}")

        print("\n=== MAC SONUCU DAGILIMI ===")
        for outcome, count in outcome_counts.items():
            print(f"{outcome}: {count:,}")

        print("\n=== 1X2 TEMEL BAHIS PERFORMANSI ===")
        for item in performance:
            print(f"\n{item['market']} / seçim {item['selection']}")
            print(f"Bahis sayısı: {item['bets']:,}")
            print(f"Kazanç: {item['wins']:,}")
            print(f"Kazanma oranı: {item['win_rate']:.4%}")
            print(f"Ortalama oran: {item['average_odds']:.4f}")
            print(f"Net kâr: {item['net_profit']:.2f} birim")
            print(f"ROI: {item['roi']:.4%}")
            print(
                "ROI yaklaşık %95 GA: "
                f"[{item['roi_ci95_low_approx']:.4%}, "
                f"{item['roi_ci95_high_approx']:.4%}]"
            )

        print("\n=== DOSYALAR ===")
        print(json_path)
        print(OUT_DIR / "1X2_yillik_rapor.csv")
        print(OUT_DIR / "1X2_bahis_performansi.csv")

    finally:
        con.close()


if __name__ == "__main__":
    main()
