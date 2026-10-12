
# -*- coding: utf-8 -*-
"""
1X2 bahis arşivi: kayıp serisi, maksimum düşüş ve dönem testi.
Kaynak veritabanı salt okunur açılır.
Ham veya analiz tablosundan kayıt silinmez.
"""

import re
from pathlib import Path

import duckdb
import pandas as pd


DB = Path(r"C:\Users\bzdye\Downloads\DATA.duckdb")
OUT = Path(r"C:\Users\bzdye\Downloads")
TABLE = "matches_analysis"

MARKETS = [
    ("MS1", "MS1_num", "1"),
    ("MSX", "MSX_num", "X"),
    ("MS2", "MS2_num", "2"),
]


def score_outcome(score):
    if not isinstance(score, str):
        return None

    match = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", score)

    if not match:
        return None

    home = int(match.group(1))
    away = int(match.group(2))

    if home > away:
        return "1"
    if home == away:
        return "X"
    return "2"


def metrics(group, odds_col, target):
    """Kronolojik, birim stake bazlı risk ölçümleri."""
    if group.empty:
        return {
            "bets": 0,
            "wins": 0,
            "win_rate": None,
            "net_profit": None,
            "roi": None,
            "max_losing_streak": 0,
            "max_drawdown_units": None,
        }

    group = group.sort_values(
        ["match_date", "SAAT", "EV", "DEP"],
        kind="stable",
    ).copy()

    odds = pd.to_numeric(group[odds_col], errors="coerce")
    valid = odds.notna() & (odds > 1) & group["MS"].isin(["1", "X", "2"])
    group = group.loc[valid].copy()
    odds = odds.loc[valid]

    if group.empty:
        return {
            "bets": 0,
            "wins": 0,
            "win_rate": None,
            "net_profit": None,
            "roi": None,
            "max_losing_streak": 0,
            "max_drawdown_units": None,
        }

    wins = group["MS"].eq(target)
    profit = odds.where(wins, -1.0).copy()
    profit.loc[wins] = odds.loc[wins] - 1.0

    equity = profit.cumsum()
    running_peak = equity.cummax().clip(lower=0)
    drawdown = running_peak - equity

    max_streak = 0
    current_streak = 0

    for is_win in wins.tolist():
        if is_win:
            current_streak = 0
        else:
            current_streak += 1
            max_streak = max(max_streak, current_streak)

    n = len(group)
    total_profit = float(profit.sum())

    return {
        "bets": int(n),
        "wins": int(wins.sum()),
        "win_rate": float(wins.mean()),
        "average_odds": float(odds.mean()),
        "net_profit": total_profit,
        "roi": total_profit / n,
        "max_losing_streak": int(max_streak),
        "max_drawdown_units": float(drawdown.max()),
    }


def main():
    if not DB.exists():
        raise FileNotFoundError(f"Veritabanı bulunamadı: {DB}")

    con = duckdb.connect(str(DB), read_only=True)

    try:
        df = con.execute(
            f"""
            SELECT
                match_date,
                "SAAT",
                "EV",
                "DEP",
                TRIM("FT") AS FT,
                TRIM("MS") AS MS,
                "MS1_num",
                "MSX_num",
                "MS2_num"
            FROM "{TABLE}"
            WHERE match_date IS NOT NULL
            ORDER BY match_date, "SAAT", "EV", "DEP"
            """
        ).df()
    finally:
        con.close()

    df["score_result"] = df["FT"].map(score_outcome)
    df["score_consistent"] = (
        df["score_result"].notna()
        & df["MS"].eq(df["score_result"])
    )

    # Dönemler önceden belirlenmiştir; sonuçlara göre seçilmemiştir.
    def period_for(year):
        if 2013 <= year <= 2017:
            return "2013-2017"
        if 2018 <= year <= 2019:
            return "2018-2019"
        if 2020 <= year <= 2021:
            return "2020-2021"
        return "Diger"

    df["period"] = df["match_date"].map(
        lambda d: period_for(d.year)
    )

    reports = []

    for scope, data in [
        ("TUM_KAYITLAR", df),
        ("SKORUYLA_UYUMLU", df[df["score_consistent"]]),
    ]:
        for period in ["TUM_DONEM", "2013-2017", "2018-2019", "2020-2021"]:
            part = data if period == "TUM_DONEM" else data[data["period"] == period]

            for market, odds_col, target in MARKETS:
                result = metrics(part, odds_col, target)
                reports.append({
                    "scope": scope,
                    "period": period,
                    "market": market,
                    **result,
                })

    report = pd.DataFrame(reports)
    report_path = OUT / "1X2_risk_ve_donem_raporu.csv"
    report.to_csv(report_path, index=False, encoding="utf-8-sig")

    mismatch_path = OUT / "1X2_tutarsizlik_kontrol.csv"
    df.loc[~df["score_consistent"]].to_csv(
        mismatch_path, index=False, encoding="utf-8-sig"
    )

    print("=== VERI KONTROLU ===")
    print(f"Toplam maç: {len(df):,}")
    print(f"Skor ve MS uyumlu: {int(df['score_consistent'].sum()):,}")
    print(f"Skor ve MS uyumsuz/eksik: {int((~df['score_consistent']).sum()):,}")

    print("\n=== RISK VE DONEM RAPORU ===")
    display_cols = [
        "scope", "period", "market", "bets", "wins",
        "win_rate", "average_odds", "net_profit", "roi",
        "max_losing_streak", "max_drawdown_units",
    ]
    print(report[display_cols].to_string(
        index=False,
        formatters={
            "win_rate": lambda x: "" if pd.isna(x) else f"{x:.2%}",
            "average_odds": lambda x: "" if pd.isna(x) else f"{x:.3f}",
            "net_profit": lambda x: "" if pd.isna(x) else f"{x:.2f}",
            "roi": lambda x: "" if pd.isna(x) else f"{x:.2%}",
            "max_drawdown_units": lambda x: "" if pd.isna(x) else f"{x:.2f}",
        },
    ))

    print("\n=== DOSYALAR ===")
    print(report_path)
    print(mismatch_path)


if __name__ == "__main__":
    main()
