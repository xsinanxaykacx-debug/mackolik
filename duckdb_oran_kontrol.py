
import duckdb
from pathlib import Path

DB = Path(r"C:\Users\bzdye\Downloads\DATA.duckdb")

ORAN_SUTUNLARI = [
    "MS1", "MSX", "MS2",
    "CS_1_2", "CS_1_X", "CS_X_2",
    "KGV", "KGY", "25A", "25Ü", "05A", "05Ü",
    "İY1", "İY2", "İYX",
    "TG01", "TG23", "TG45", "TG6"
]

def main():
    if not DB.exists():
        raise FileNotFoundError(f"Veritabani bulunamadi: {DB}")

    con = duckdb.connect(str(DB), read_only=True)

    try:
        columns = [
            r[1] for r in con.execute(
                "PRAGMA table_info('matches_raw')"
            ).fetchall()
        ]

        print("=== TAMAMEN AYNI KAYITLAR ===")

        quoted = ", ".join(
            '"' + c.replace('"', '""') + '"' for c in columns
        )

        duplicate_sql = f"""
            SELECT {quoted}, COUNT(*) AS tekrar
            FROM matches_raw
            GROUP BY ALL
            HAVING COUNT(*) > 1
            ORDER BY tekrar DESC
            LIMIT 20
        """

        duplicate_rows = con.execute(duplicate_sql).fetchall()
        if not duplicate_rows:
            print("Tekrar bulunamadi.")
        else:
            for row in duplicate_rows:
                record = dict(zip(columns, row[:-1]))
                print(
                    "Tarih:", record.get("TARİH"),
                    "| Saat:", record.get("SAAT"),
                    "| Ev:", record.get("EV"),
                    "| Dep:", record.get("DEP"),
                    "| HT:", record.get("HT"),
                    "| FT:", record.get("FT"),
                    "| Tekrar:", row[-1]
                )

        print("\n=== BAHIS ORANI KONTROLU ===")

        for col in ORAN_SUTUNLARI:
            if col not in columns:
                print(f"\n{col}: SUTUN BULUNAMADI")
                continue

            qcol = '"' + col.replace('"', '""') + '"'
            result = con.execute(f"""
                SELECT
                    COUNT(*) AS toplam,
                    COUNT(NULLIF(TRIM({qcol}), '')) AS dolu,
                    COUNT(
                        TRY_CAST(NULLIF(TRIM({qcol}), '') AS DOUBLE)
                    ) AS sayisal,
                    MIN(
                        TRY_CAST(NULLIF(TRIM({qcol}), '') AS DOUBLE)
                    ) AS minimum,
                    MAX(
                        TRY_CAST(NULLIF(TRIM({qcol}), '') AS DOUBLE)
                    ) AS maksimum
                FROM matches_raw
            """).fetchone()

            total, filled, numeric, minimum, maximum = result
            nonnumeric = filled - numeric

            print(
                f"{col}: toplam={total:,}, dolu={filled:,}, "
                f"sayisal={numeric:,}, sayisal_olmayan={nonnumeric:,}, "
                f"min={minimum}, max={maximum}"
            )

            if nonnumeric:
                examples = con.execute(f"""
                    SELECT DISTINCT TRIM({qcol})
                    FROM matches_raw
                    WHERE NULLIF(TRIM({qcol}), '') IS NOT NULL
                      AND TRY_CAST(NULLIF(TRIM({qcol}), '') AS DOUBLE)
                          IS NULL
                    LIMIT 8
                """).fetchall()
                print("  Sayisal olmayan ornekler:", [x[0] for x in examples])

        print("\nKontrol tamamlandi. Veritabani degistirilmedi.")

    finally:
        con.close()

if __name__ == "__main__":
    main()
