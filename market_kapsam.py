# -*- coding: utf-8 -*-
"""Veritabanında bulunan ek futbol marketlerini keşfeder ve dönemsel ROI denetler."""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
OUT = BASE / "market_kapsam_ciktilari"
SEED = 20261020
BOOTSTRAPS = 1000


def norm_col(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper().replace("İ", "I").replace("Ü", "U")
    return re.sub(r"[^A-Z0-9]", "", text)


def parse_score(value: object) -> tuple[float, float]:
    if pd.isna(value):
        return np.nan, np.nan
    match = re.fullmatch(r"\s*(\d+)\s*[-:–—]\s*(\d+)\s*", str(value))
    if not match:
        return np.nan, np.nan
    return float(match.group(1)), float(match.group(2))


def find_column(columns: list[str], aliases: tuple[str, ...]) -> str | None:
    by_norm = {norm_col(col): col for col in columns}
    for alias in aliases:
        if norm_col(alias) in by_norm:
            return by_norm[norm_col(alias)]
    return None


def numeric_odds(series: pd.Series) -> pd.Series:
    if series.dtype == object or pd.api.types.is_string_dtype(series):
        series = series.astype("string").str.replace(",", ".", regex=False)
    return pd.to_numeric(series, errors="coerce").astype("float64")


def market_definitions(columns: list[str]) -> list[dict]:
    definitions = []
    for tenths in (15, 25, 35, 45, 55):
        label = f"{tenths / 10:.1f}"
        over_aliases = (
            f"{tenths}A_num", f"{tenths}A", f"{tenths}Ust", f"Over{label}",
            f"O{label}", f"Over{tenths}", f"O{tenths}",
        )
        under_aliases = (
            f"{tenths}Ü_num", f"{tenths}U_num", f"{tenths}Ü", f"{tenths}U",
            f"{tenths}Alt", f"Under{label}", f"U{label}", f"Under{tenths}", f"U{tenths}",
        )
        definitions.extend([
            {"market": f"MS toplam gol ÜST {label}", "selection": "ÜST",
             "odds_col": find_column(columns, over_aliases), "kind": "total_over",
             "line": tenths / 10},
            {"market": f"MS toplam gol ALT {label}", "selection": "ALT",
             "odds_col": find_column(columns, under_aliases), "kind": "total_under",
             "line": tenths / 10},
        ])

    definitions.extend([
        {"market": "KG VAR", "selection": "VAR",
         "odds_col": find_column(columns, ("KGV_num", "KGV", "KGVAR", "BTTSYES", "BTTSY")),
         "kind": "btts_yes"},
        {"market": "KG YOK", "selection": "YOK",
         "odds_col": find_column(columns, ("KGY_num", "KGY", "KGYOK", "BTTSNO", "BTTSN")),
         "kind": "btts_no"},
    ])
    for selection, aliases in (
        ("1", ("IY1_num", "IY1", "İY1", "HT1", "HT1X2_1", "FIRSTHALF1")),
        ("X", ("IYX_num", "IYX", "İYX", "HTX", "HT1X2_X", "FIRSTHALFX")),
        ("2", ("IY2_num", "IY2", "İY2", "HT2", "HT1X2_2", "FIRSTHALF2")),
    ):
        definitions.append({
            "market": f"İlk yarı 1X2 {selection}", "selection": selection,
            "odds_col": find_column(columns, aliases), "kind": f"ht_{selection}",
        })
    return definitions


def roi_ci_by_day(frame: pd.DataFrame, rng: np.random.Generator) -> tuple[float, float]:
    if len(frame) < 2:
        return np.nan, np.nan
    daily = frame.assign(_day=frame["match_date"].dt.normalize()).groupby("_day", sort=True)["profit"].agg(["sum", "count"])
    sums = daily["sum"].to_numpy(float)
    counts = daily["count"].to_numpy(float)
    if len(sums) < 2:
        return np.nan, np.nan
    n_days = len(sums)
    block = min(7, n_days)
    n_blocks = int(np.ceil(n_days / block))
    starts = rng.integers(0, n_days - block + 1, size=(BOOTSTRAPS, n_blocks))
    indices = starts[:, :, None] + np.arange(block)[None, None, :]
    indices = indices.reshape(BOOTSTRAPS, -1)[:, :n_days]
    profits = sums[indices].sum(axis=1)
    bets = counts[indices].sum(axis=1)
    samples = profits / bets
    low, high = np.quantile(samples, [0.025, 0.975])
    return float(low), float(high)


def score_outcomes(raw: pd.DataFrame) -> pd.DataFrame:
    result = raw.copy()
    ft = result["FT"].map(parse_score)
    result["ft_home"] = ft.map(lambda pair: pair[0])
    result["ft_away"] = ft.map(lambda pair: pair[1])
    if "HT" in result.columns:
        ht = result["HT"].map(parse_score)
        result["ht_home"] = ht.map(lambda pair: pair[0])
        result["ht_away"] = ht.map(lambda pair: pair[1])
    else:
        result["ht_home"] = np.nan
        result["ht_away"] = np.nan
    result["match_date"] = pd.to_datetime(result["match_date"], errors="coerce")
    result["year"] = result["match_date"].dt.year
    result["total_goals"] = result["ft_home"] + result["ft_away"]
    return result


def outcome_for(row: pd.Series, kind: str, line: float | None = None) -> bool | None:
    if kind.startswith("ht_"):
        home, away = row["ht_home"], row["ht_away"]
        if pd.isna(home) or pd.isna(away):
            return None
        actual = "1" if home > away else ("X" if home == away else "2")
        return actual == kind[-1]
    home, away = row["ft_home"], row["ft_away"]
    if pd.isna(home) or pd.isna(away):
        return None
    if kind.startswith("total_"):
        total = home + away
        if kind == "total_over":
            return total > float(line)
        return total < float(line)
    if kind == "btts_yes":
        return home > 0 and away > 0
    if kind == "btts_no":
        return home == 0 or away == 0
    return None


def run(db_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not db_path.is_file():
        raise FileNotFoundError(f"Veritabanı bulunamadı: {db_path}")
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        info = con.execute("PRAGMA table_info('matches_analysis')").df()
        if info.empty:
            raise RuntimeError("matches_analysis tablosu bulunamadı.")
        columns = info["name"].astype(str).tolist()
        required = {"match_date", "FT"}
        missing = required - set(columns)
        if missing:
            raise RuntimeError("Zorunlu sütun eksik: " + ", ".join(sorted(missing)))
        raw = con.execute('SELECT * FROM "matches_analysis"').df()
    finally:
        con.close()

    raw = score_outcomes(raw)
    definitions = market_definitions(columns)
    coverage = []
    results = []
    for definition in definitions:
        odds_col = definition["odds_col"]
        coverage.append({
            "market": definition["market"],
            "selection": definition["selection"],
            "odds_column": odds_col or "",
            "status": "ORAN_SUTUNU_VAR" if odds_col else "ORAN_SUTUNU_YOK",
        })
        if not odds_col:
            continue
        odds = numeric_odds(raw[odds_col])
        valid_score = raw["ft_home"].notna() & raw["ft_away"].notna() & raw["match_date"].notna()
        if definition["kind"].startswith("ht_"):
            valid_score &= raw["ht_home"].notna() & raw["ht_away"].notna()
        valid = valid_score & odds.notna() & np.isfinite(odds) & odds.gt(1.0)
        frame = raw.loc[valid, ["match_date", "year"]].copy()
        frame["odds"] = odds.loc[valid].to_numpy(float)
        frame["won"] = [
            bool(outcome_for(raw.loc[idx], definition["kind"], definition.get("line")))
            for idx in frame.index
        ]
        frame["profit"] = np.where(frame["won"], frame["odds"] - 1.0, -1.0)
        for period, mask in (
            ("KESIF_2013_2017", frame["year"].between(2013, 2017)),
            ("DOGRULAMA_2018_2020", frame["year"].between(2018, 2020)),
            ("TUM_VERI", frame["year"].between(2013, 2021)),
        ):
            part = frame.loc[mask].copy()
            n = len(part)
            rng = np.random.default_rng(SEED)
            ci_low, ci_high = roi_ci_by_day(part, rng) if n else (np.nan, np.nan)
            results.append({
                "market": definition["market"],
                "selection": definition["selection"],
                "odds_column": odds_col,
                "period": period,
                "bets": n,
                "wins": int(part["won"].sum()) if n else 0,
                "win_rate": float(part["won"].mean()) if n else np.nan,
                "average_odds": float(part["odds"].mean()) if n else np.nan,
                "net_profit": float(part["profit"].sum()) if n else 0.0,
                "roi": float(part["profit"].mean()) if n else np.nan,
                "roi_ci95_low": ci_low,
                "roi_ci95_high": ci_high,
            })
    OUT.mkdir(parents=True, exist_ok=True)
    coverage_df = pd.DataFrame(coverage)
    results_df = pd.DataFrame(results)
    coverage_df.to_csv(OUT / "01_market_kapsami.csv", index=False, encoding="utf-8-sig")
    results_df.to_csv(OUT / "02_market_baseline.csv", index=False, encoding="utf-8-sig")
    report = [
        "# Ek Market Kapsamı ve Temel ROI Denetimi",
        "",
        f"- Veritabanı satırı: {len(raw):,}",
        f"- Tarih aralığı: {raw['match_date'].min()} — {raw['match_date'].max()}",
        "- Ham veritabanı salt okunur açıldı; kaynak dosya değiştirilmedi.",
        "- ROI, her seçim için maç başına 1 birim sabit bahis varsayar.",
        "- Güven aralığı, gün bazında 7 günlük blok bootstrap (%95, 1.000 tekrar) ile hesaplanır.",
        "- Keşif dönemi 2013–2017, bağımsız doğrulama dönemi 2018–2020 olarak ayrıdır.",
        "- Bu dosya ilk kapsam taramasıdır; doğrulama dönemindeki pozitif ROI tek başına kârlılık kanıtı değildir.",
        "",
        "## Oran sütunu kapsamı",
        "",
        "| Market | Seçim | Bulunan sütun | Durum |",
        "|---|---|---|---|",
    ]
    for row in coverage:
        report.append(f"| {row['market']} | {row['selection']} | {row['odds_column'] or '—'} | {row['status']} |")
    report.extend([
        "",
        "## Sonuçlar",
        "",
        "| Market | Dönem | Bahis | Kazanç | Ortalama oran | ROI | ROI %95 GA |",
        "|---|---|---:|---:|---:|---:|---|",
    ])
    for row in results:
        def fmt(value):
            return "—" if pd.isna(value) else f"{value:.2%}"
        avg = "—" if pd.isna(row["average_odds"]) else f"{row['average_odds']:.3f}"
        report.append(
            f"| {row['market']} | {row['period']} | {row['bets']} | {row['wins']} | "
            f"{avg} | {fmt(row['roi'])} | [{fmt(row['roi_ci95_low'])}; {fmt(row['roi_ci95_high'])}] |"
        )
    report.extend([
        "",
        "## Yorumlama kuralı",
        "",
        "Kârlı aday demek için doğrulama ROI'sinin pozitif olması ve ROI %95 güven aralığı alt sınırının sıfırın üzerinde bulunması gerekir. Bu tarama yeni market oranı bulunup bulunmadığını da açıkça raporlar; oran sütunu olmayan market için performans sonucu üretilmez.",
    ])
    (OUT / "RAPOR.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("Veritabanı satırı:", len(raw))
    print("Tarih aralığı:", raw["match_date"].min(), "-", raw["match_date"].max())
    print("Oran sütunu bulunan market:", int((coverage_df["status"] == "ORAN_SUTUNU_VAR").sum()))
    print("Oran sütunu bulunmayan market:", int((coverage_df["status"] == "ORAN_SUTUNU_YOK").sum()))
    print("Çıktılar:", OUT)
    return coverage_df, results_df


if __name__ == "__main__":
    db = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / "DATA.duckdb"
    run(db)
