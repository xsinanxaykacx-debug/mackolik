
from pathlib import Path
from collections import Counter
from datetime import datetime, date
import re
import duckdb

DB = Path(r"C:\Users\bzdye\Downloads\DATA.duckdb")

def parse_date(value):
    if value is None:
        return None
    value = str(value).strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None

con = duckdb.connect(str(DB), read_only=True)

try:
    headers = [
        row[1]
        for row in con.execute("PRAGMA table_info('matches_raw')").fetchall()
    ]

    date_idx = headers.index("TARİH")
    home_idx = headers.index("EV")
    away_idx = headers.index("DEP")
    ft_idx = headers.index("FT")
    ht_idx = headers.index("HT")

    cur = con.execute("SELECT * FROM matches_raw")

    total = 0
    invalid_dates = 0
    invalid_ft = 0
    invalid_ht = 0
    missing_teams = 0
    date_min = None
    date_max = None
    by_year = Counter()
    duplicates = Counter()
    bad_date_samples = []
    bad_ft_samples = []
    score_pattern = re.compile(r"^\d+\s*[-:]\s*\d+$")

    while True:
        batch = cur.fetchmany(5000)
        if not batch:
            break

        for row in batch:
            total += 1

            d = parse_date(row[date_idx])
            if d is None:
                invalid_dates += 1
                if len(bad_date_samples) < 10:
                    bad_date_samples.append(row[date_idx])
            else:
                date_min = d if date_min is None else min(date_min, d)
                date_max = d if date_max is None else max(date_max, d)
                by_year[d.year] += 1

            if not row[home_idx] or not row[away_idx]:
                missing_teams += 1

            ft = str(row[ft_idx] or "").strip()
            if not score_pattern.fullmatch(ft):
                invalid_ft += 1
                if len(bad_ft_samples) < 10:
                    bad_ft_samples.append(ft)

            ht = str(row[ht_idx] or "").strip()
            if ht and not score_pattern.fullmatch(ht):
                invalid_ht += 1

            duplicates[tuple(row)] += 1

    duplicate_groups = sum(1 for n in duplicates.values() if n > 1)
    duplicate_extra = sum(n - 1 for n in duplicates.values() if n > 1)

    print("\n=== DUZELTILMIS DOGRULAMA ===")
    print("DuckDB kayit sayisi:", total)
    print("Gecersiz tarih:", invalid_dates)
    print("Ilk tarih:", date_min)
    print("Son tarih:", date_max)
    print("Eksik takim alanli satir:", missing_teams)
    print("Gecersiz FT skoru:", invalid_ft)
    print("Gecersiz ve bos olmayan HT skoru:", invalid_ht)
    print("Tamamen ayni satir grubu:", duplicate_groups)
    print("Fazladan tekrar eden satir:", duplicate_extra)

    print("\nYillara gore kayit:")
    for year in sorted(by_year):
        print(year, f"{by_year[year]:,}")

    print("\nGecersiz tarih ornekleri:", bad_date_samples)
    print("Gecersiz FT skoru ornekleri:", bad_ft_samples)

finally:
    con.close()
