
# -*- coding: utf-8 -*-

from pathlib import Path

import duckdb
import pandas as pd


DB = Path(r"C:\Users\bzdye\Downloads\DATA.duckdb")
OUT = Path(r"C:\Users\bzdye\Downloads")

BANDS = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 6.0, 10.0, float("inf")]
LABELS = [
    "1.00-1.50",
    "1.50-2.00",
    "2.00-2.50",
    "2.50-3.00",
    "3.00-4.00",
    "4.00-6.00",
    "6.00-10.00",
    "10.00+",
]

MARKETS = [
    ("MS1", "MS1_num", "1"),
    ("MSX", "MSX_num", "X"),
    ("MS2", "MS2_num", "2"),
]


def risk_metrics(group):
    group = group.sort_values(
        ["match_date", "SAAT", "EV", "DEP"],
        kind="stable",
    )

    profit = group["profit"].astype(float)
    wins = group["win"].astype(bool)

    equity = profit.cumsum()
    peak = equity.cummax().clip(lower=0)
    drawdown = peak - equity

    current = 0
    longest = 0

    for won in wins:
        if won:
            current = 0
        else:
            current += 1
            longest = max(longest, current)

    n = len(group)
    net = float(profit.sum())

    return {
        "bets": n,
        "wins": int(wins.sum()),
        "win_rate": float(wins.mean()),
        "average_odds": float(group["odds"].mean()),
        "net_profit": net,
        "roi": net / n,
        "max_losing_streak": longest,
        "max_drawdown_units": float(drawdown.max()),
    }


def main():
    if not DB.exists():
        raise FileNotFoundError(f"Veritabanı bulunamadı: {DB}")

    con = duckdb.connect(str(DB), read_only=True)

    try:
        df = con.execute(
            """
            SELECT
                match_date, "SAAT", "EV", "DEP",
                TRIM("FT") AS FT,
                TRIM("MS") AS MS,
                "MS1_num", "MSX_num", "MS2_num"
            FROM matches_analysis
            WHERE match_date IS NOT NULL
            ORDER BY match_date, "SAAT", "EV", "DEP"
            """
        ).df()
    finally:
        con.close()

    # FT skorundan bağımsız olarak MS sonucunu yeniden doğrula.
    score_parts = df["FT"].str.extract(r"^\s*(\d+)\s*-\s*(\d+)\s*$")
    home = pd.to_numeric(score_parts[0], errors="coerce")
    away = pd.to_numeric(score_parts[1], errors="coerce")

    df["score_result"] = "X"
    df.loc[home > away, "score_result"] = "1"
    df.loc[home < away, "score_result"] = "2"

    valid_score = home.notna() & away.notna()
    df = df[
        valid_score
        & df["MS"].isin(["1", "X", "2"])
        & df["MS"].eq(df["score_result"])
    ].copy()

    def period(year):
        if 2013 <= year <= 2017:
            return "EGITIM_2013_2017"
        if 2018 <= year <= 2019:
            return "DOGRULAMA_2018_2019"
        if 2020 <= year <= 2021:
            return "SONRAKI_DONEM_2020_2021"
        return "DIGER"

    df["period"] = df["match_date"].map(lambda d: period(d.year))
    results = []

    for market, odds_col, target in MARKETS:
        part = df.copy()
        part["odds"] = pd.to_numeric(part[odds_col], errors="coerce")
        part = part[part["odds"].notna() & (part["odds"] > 1)].copy()

        part["win"] = part["MS"].eq(target)
        part["profit"] = part["odds"].where(part["win"], -1.0)
        part.loc[part["win"], "profit"] = (
            part.loc[part["win"], "odds"] - 1.0
        )

        part["odds_band"] = pd.cut(
            part["odds"],
            bins=BANDS,
            labels=LABELS,
            right=False,
            include_lowest=True,
        )

        for period_name in [
            "EGITIM_2013_2017",
            "DOGRULAMA_2018_2019",
            "SONRAKI_DONEM_2020_2021",
        ]:
            period_data = part[part["period"] == period_name]

            for band in LABELS:
                group = period_data[
                    period_data["odds_band"] == band
                ]

                if group.empty:
                    results.append({
                        "market": market,
                        "period": period_name,
                        "odds_band": band,
                        "bets": 0,
                        "wins": 0,
                        "win_rate": None,
                        "average_odds": None,
                        "net_profit": 0.0,
                        "roi": None,
                        "max_losing_streak": 0,
                        "max_drawdown_units": None,
                    })
                    continue

                results.append({
                    "market": market,
                    "period": period_name,
                    "odds_band": band,
                    **risk_metrics(group),
                })

    report = pd.DataFrame(results)
    path = OUT / "1X2_oran_aralik_testi.csv"
    report.to_csv(path, index=False, encoding="utf-8-sig")

    print("=== ORAN ARALIĞI TESTİ ===")
    print(f"Skoruyla uyumlu maç: {len(df):,}")
    print(f"Sonuç dosyası: {path}")

    # Eğitim döneminde en az 500 bahis içeren aralıkları göster.
    training = report[
        (report["period"] == "EGITIM_2013_2017")
        & (report["bets"] >= 500)
    ].sort_values(["market", "roi"], ascending=[True, False])

    print("\n=== EĞİTİM DÖNEMİ: EN İYİ GÖRÜNEN ARALIKLAR ===")
    print(
        training[
            ["market", "odds_band", "bets", "win_rate",
             "net_profit", "roi"]
        ].to_string(
            index=False,
            formatters={
                "win_rate": lambda x: "" if pd.isna(x) else f"{x:.2%}",
                "net_profit": lambda x: f"{x:.2f}",
                "roi": lambda x: "" if pd.isna(x) else f"{x:.2%}",
            },
        )
    )

    print(
        "\nNot: Eğitimde iyi görünen bir aralık, doğrulama veya sonraki "
        "dönemde de iyi değilse kârlı strateji kabul edilmez."
    )


if __name__ == "__main__":
    main()
