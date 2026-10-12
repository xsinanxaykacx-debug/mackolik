
# -*- coding: utf-8 -*-
"""
DATA.xlsx futbol bahis arşivi - Alt/Üst 2,5 gol performans analizi

Dönemler:
    Egitim       : 2013-2017
    Dogrulama    : 2018-2019
    Sonraki      : 2020-2021

Pazarlar:
    ALT 2,5 : 25A_num
    ÜST 2,5 : 25Ü_num

Kurallar:
    - Ham tablo ve Excel dosyası değiştirilmez.
    - matches_analysis tablosu salt okunur açılır.
    - FT skorundan sonuç yeniden hesaplanır.
    - Kaynak sonucu ile FT skoru uyuşmayan maçlar dışarıda bırakılır.
    - Eksik, geçersiz ve 1.00 veya altındaki oranlar oynanabilir
      oran olarak kabul edilmez.
    - Her bahis için 1 birim sabit bahis kullanılır.
    - ROI güven aralığı yaklaşık normal yaklaşımıyla hesaplanır.
"""

import os
import sys
import re
import logging

import duckdb
import pandas as pd
import numpy as np


# ==================================================
# AYARLAR
# ==================================================

DB_PATH = r"C:\Users\bzdye\Downloads\DATA.duckdb"
OUTPUT_DIR = r"C:\Users\bzdye\Downloads"

OUTPUT_CSV = os.path.join(
    OUTPUT_DIR,
    "alt_ust_donem_performansi.csv"
)

OUTPUT_JSON = os.path.join(
    OUTPUT_DIR,
    "alt_ust_donem_performansi.json"
)

LOG_PATH = os.path.join(
    OUTPUT_DIR,
    "duckdb_alt_ust_performans.log"
)

TABLE_NAME = "matches_analysis"

RANDOM_SEED = 20261012

PERIODS = [
    ("EGITIM_2013_2017", "2013-01-01", "2017-12-31"),
    ("DOGRULAMA_2018_2019", "2018-01-01", "2019-12-31"),
    ("SONRAKI_DONEM_2020_2021", "2020-01-01", "2021-12-31"),
]

MARKETS = [
    ("ALT", "25A_num"),
    ("UST", "25Ü_num"),
]


# ==================================================
# LOG
# ==================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger(__name__)


# ==================================================
# YARDIMCI FONKSİYONLAR
# ==================================================

def parse_score(value):
    """FT skorunu (ev golü, deplasman golü) olarak döndürür."""

    if value is None:
        return None

    match = re.fullmatch(
        r"\s*(\d+)\s*[-:]\s*(\d+)\s*",
        str(value),
    )

    if not match:
        return None

    return int(match.group(1)), int(match.group(2))


def calculate_result(score):
    """
    2,5 gol çizgisinin sonucu:
        toplam gol <= 2 : ALT
        toplam gol >= 3 : UST
    """

    parsed = parse_score(score)

    if parsed is None:
        return None

    total_goals = parsed[0] + parsed[1]

    return "ALT" if total_goals <= 2 else "UST"


def max_losing_streak(wins):
    """Zaman sıralı kazanma/kaybetme dizisindeki en uzun kayıp serisi."""

    longest = 0
    current = 0

    for win in wins:
        if bool(win):
            current = 0
        else:
            current += 1
            longest = max(longest, current)

    return longest


def max_drawdown(profits):
    """
    Birikimli kâr eğrisinin tepe noktasından en büyük gerilemesi.
    Bahisler kronolojik sırada olmalıdır.
    """

    if len(profits) == 0:
        return 0.0

    cumulative = np.cumsum(
        np.asarray(profits, dtype=float)
    )

    cumulative_with_initial = np.concatenate(
        ([0.0], cumulative)
    )

    peaks = np.maximum.accumulate(
        cumulative_with_initial
    )

    drawdowns = peaks - cumulative_with_initial

    return float(np.max(drawdowns))


def wilson_interval(wins, bets, z=1.959963984540054):
    """Kazanma oranı için Wilson %95 güven aralığı."""

    if bets <= 0:
        return np.nan, np.nan

    p = wins / bets
    denominator = 1 + z * z / bets

    center = (
        p + z * z / (2 * bets)
    ) / denominator

    margin = (
        z
        * np.sqrt(
            p * (1 - p) / bets
            + z * z / (4 * bets * bets)
        )
        / denominator
    )

    return max(0.0, center - margin), min(1.0, center + margin)


def analyze_group(part, market, period, missing_odds, invalid_odds):
    """Bir pazar ve dönem için bütün performans ölçülerini hesaplar."""

    if part.empty:
        return {
            "period": period,
            "market": market,
            "bets": 0,
            "wins": 0,
            "win_rate": np.nan,
            "win_rate_ci95_low": np.nan,
            "win_rate_ci95_high": np.nan,
            "average_odds": np.nan,
            "net_profit": 0.0,
            "roi": np.nan,
            "roi_ci95_low": np.nan,
            "roi_ci95_high": np.nan,
            "max_losing_streak": 0,
            "max_drawdown_units": 0.0,
            "missing_odds_rows": missing_odds,
            "invalid_odds_rows": invalid_odds,
        }

    part = part.sort_values(
        ["match_date", "SAAT", "EV", "DEP"],
        kind="mergesort",
    ).copy()

    odds = part["odds"].to_numpy(dtype=float)
    wins_array = part["win"].to_numpy(dtype=bool)

    # Kazanırsa net kâr = oran - 1; kaybederse -1 birim.
    profits = np.where(wins_array, odds - 1.0, -1.0)

    bets = len(part)
    wins = int(np.sum(wins_array))
    net_profit = float(np.sum(profits))
    roi = net_profit / bets

    win_rate = wins / bets
    win_ci_low, win_ci_high = wilson_interval(wins, bets)

    # ROI için yaklaşık %95 normal güven aralığı.
    # Bahis getirilerinin bağımsız olduğu varsayımına dayanır.
    standard_error = float(np.std(profits, ddof=1) / np.sqrt(bets)) if bets > 1 else np.nan

    if np.isfinite(standard_error):
        roi_ci_low = roi - 1.959963984540054 * standard_error
        roi_ci_high = roi + 1.959963984540054 * standard_error
    else:
        roi_ci_low = np.nan
        roi_ci_high = np.nan

    return {
        "period": period,
        "market": market,
        "bets": int(bets),
        "wins": wins,
        "win_rate": float(win_rate),
        "win_rate_ci95_low": float(win_ci_low),
        "win_rate_ci95_high": float(win_ci_high),
        "average_odds": float(np.mean(odds)),
        "net_profit": net_profit,
        "roi": float(roi),
        "roi_ci95_low": float(roi_ci_low),
        "roi_ci95_high": float(roi_ci_high),
        "max_losing_streak": int(max_losing_streak(wins_array)),
        "max_drawdown_units": max_drawdown(profits),
        "missing_odds_rows": int(missing_odds),
        "invalid_odds_rows": int(invalid_odds),
    }


# ==================================================
# ANA İŞLEM
# ==================================================

def main():
    if not os.path.isfile(DB_PATH):
        logger.error("Veritabanı bulunamadı: %s", DB_PATH)
        return 1

    connection = None

    try:
        connection = duckdb.connect(
            database=DB_PATH,
            read_only=True,
        )

        logger.info("Veritabanı salt okunur açıldı.")

        # Sütun doğrulaması
        schema = connection.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'main'
              AND table_name = ?
            """,
            [TABLE_NAME],
        ).fetchall()

        columns = {row[0] for row in schema}

        required = {
            "match_date",
            "SAAT",
            "EV",
            "DEP",
            "FT",
            "MS25AÜ",
            "25A_num",
            "25Ü_num",
        }

        missing = sorted(required - columns)

        if missing:
            logger.error(
                "Eksik sütunlar: %s",
                ", ".join(missing),
            )
            return 1

        # Yalnızca gerekli sütunları al.
        df = connection.execute(
            """
            SELECT
                match_date,
                SAAT,
                EV,
                DEP,
                FT,
                MS25AÜ,
                "25A_num" AS ALT_odds,
                "25Ü_num" AS UST_odds
            FROM matches_analysis
            WHERE match_date IS NOT NULL
              AND match_date >= DATE '2013-01-01'
              AND match_date <= DATE '2021-12-31'
            """
        ).fetchdf()

        logger.info("Tarih aralığındaki kayıt: %s", f"{len(df):,}")

        if df.empty:
            logger.error("Analiz edilecek kayıt bulunamadı.")
            return 1

        # Sonuçları FT skorundan yeniden hesapla.
        df["calculated_result"] = df["FT"].apply(calculate_result)

        # Kaynak sonucu ALT/ÜST ile aynı mı?
        df["source_result"] = (
            df["MS25AÜ"]
            .astype(str)
            .str.strip()
            .str.upper()
            .replace({"ÜST": "UST"})
        )

        valid_scores = df["calculated_result"].notna()

        consistent = (
            valid_scores
            & (df["source_result"] == df["calculated_result"])
        )

        mismatch_count = int(
            (valid_scores & ~consistent).sum()
        )

        invalid_score_count = int((~valid_scores).sum())

        logger.info("Geçerli FT skoru: %s", f"{int(valid_scores.sum()):,}")
        logger.info("Kaynak sonucu ile uyumsuz: %s", f"{mismatch_count:,}")
        logger.info("Geçersiz FT skoru: %s", f"{invalid_score_count:,}")

        # Sonuç uyuşmazlıklarını tüm pazarlardan çıkar.
        df = df.loc[consistent].copy()

        if df.empty:
            logger.error("Skoruyla uyumlu kayıt kalmadı.")
            return 1

        df["match_date"] = pd.to_datetime(
            df["match_date"],
            errors="coerce",
        )

        df["ALT_odds"] = pd.to_numeric(
            df["ALT_odds"],
            errors="coerce",
        )

        df["UST_odds"] = pd.to_numeric(
            df["UST_odds"],
            errors="coerce",
        )

        # Sonuç dağılımı
        logger.info("=== SKORLA DOĞRULANMIŞ SONUÇ DAĞILIMI ===")

        distribution = df["calculated_result"].value_counts()

        for result in ["ALT", "UST"]:
            logger.info(
                "%s: %s",
                result,
                f"{int(distribution.get(result, 0)):,}",
            )

        # Dönem ve pazar bazında rapor.
        output_rows = []

        for period_name, start_date, end_date in PERIODS:
            period_mask = (
                (df["match_date"] >= pd.Timestamp(start_date))
                & (df["match_date"] <= pd.Timestamp(end_date))
            )

            period_df = df.loc[period_mask].copy()

            logger.info(
                "=== DÖNEM: %s | MAÇ: %s ===",
                period_name,
                f"{len(period_df):,}",
            )

            for market, odds_column in [("ALT", "ALT_odds"), ("UST", "UST_odds")]:
                raw_odds = period_df[odds_column]

                missing_odds = int(raw_odds.isna().sum())

                invalid_odds = int(
                    (
                        raw_odds.notna()
                        & (
                            ~np.isfinite(raw_odds)
                            | (raw_odds <= 1.0)
                        )
                    ).sum()
                )

                # Yalnızca geçerli oranı bulunan bahisler.
                valid_odds_mask = (
                    raw_odds.notna()
                    & np.isfinite(raw_odds)
                    & (raw_odds > 1.0)
                )

                part = period_df.loc[valid_odds_mask].copy()
                part["odds"] = part[odds_column]

                part["win"] = (
                    part["calculated_result"] == market
                )

                result = analyze_group(
                    part=part,
                    market=market,
                    period=period_name,
                    missing_odds=missing_odds,
                    invalid_odds=invalid_odds,
                )

                output_rows.append(result)

                logger.info(
                    "%s | bahis=%s | galibiyet=%s | "
                    "kazanma=%.2f%% | ort_oran=%.3f | "
                    "net=%+.2f | ROI=%+.2f%% | "
                    "ROI %%95 GA=[%+.2f%%, %+.2f%%] | "
                    "kayıp_serisi=%s | max_DD=%.2f",
                    market,
                    f"{result['bets']:,}",
                    f"{result['wins']:,}",
                    result["win_rate"] * 100
                    if np.isfinite(result["win_rate"]) else 0.0,
                    result["average_odds"]
                    if np.isfinite(result["average_odds"]) else 0.0,
                    result["net_profit"],
                    result["roi"] * 100
                    if np.isfinite(result["roi"]) else 0.0,
                    result["roi_ci95_low"] * 100
                    if np.isfinite(result["roi_ci95_low"]) else 0.0,
                    result["roi_ci95_high"] * 100
                    if np.isfinite(result["roi_ci95_high"]) else 0.0,
                    result["max_losing_streak"],
                    result["max_drawdown_units"],
                )

        # CSV
        result_df = pd.DataFrame(output_rows)

        result_df.to_csv(
            OUTPUT_CSV,
            index=False,
            encoding="utf-8-sig",
            sep=";",
            decimal=",",
        )

        # JSON
        result_df.to_json(
            OUTPUT_JSON,
            orient="records",
            force_ascii=False,
            indent=2,
        )

        logger.info("=== ANALİZ TAMAMLANDI ===")
        logger.info("CSV raporu: %s", OUTPUT_CSV)
        logger.info("JSON raporu: %s", OUTPUT_JSON)
        logger.info("Log dosyası: %s", LOG_PATH)
        logger.info("Veritabanında değişiklik yapılmadı.")

        logger.info(
            "UYARI: ROI güven aralığı yaklaşık normal aralıktır; "
            "bahis getirilerinin bağımsız olduğu varsayımına dayanır. "
            "Dönem sonuçları tek başına gelecekteki kârlılığı garanti etmez."
        )

        return 0

    except Exception:
        logger.exception("Analiz sırasında hata oluştu.")
        return 1

    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    sys.exit(main())
