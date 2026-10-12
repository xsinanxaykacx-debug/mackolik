
import duckdb
from pathlib import Path

DB = Path(r"C:\Users\bzdye\Downloads\DATA.duckdb")

ODDS = [
    "MS1", "MSX", "MS2",
    "CS_1_2", "CS_1_X", "CS_X_2",
    "KGV", "KGY", "25A", "25Ü", "05A", "05Ü",
    "İY1", "İY2", "İYX",
    "TG01", "TG23", "TG45", "TG6"
]

def quote(name):
    return '"' + name.replace('"', '""') + '"'

def main():
    if not DB.exists():
        raise FileNotFoundError(f"Veritabani bulunamadi: {DB}")

    con = duckdb.connect(str(DB))

    try:
        columns = [
            r[1] for r in con.execute(
                "PRAGMA table_info('matches_raw')"
            ).fetchall()
        ]

        if "TARİH" not in columns:
            raise ValueError("TARİH sutunu bulunamadi.")

        if any(c not in columns for c in ODDS):
            raise ValueError("Beklenen oran sutunlarindan biri eksik.")

        # Birden fazla tarih biçimini güvenli şekilde dene.
        date_expr = """
            COALESCE(
                TRY_STRPTIME(TRIM("TARİH"), '%d/%m/%Y'),
                TRY_STRPTIME(TRIM("TARİH"), '%d-%m-%Y'),
                TRY_STRPTIME(TRIM("TARİH"), '%Y-%m-%d'),
                TRY_STRPTIME(TRIM("TARİH"), '%d.%m.%Y')
            )::DATE
        """

        additions = [f"{date_expr} AS match_date"]

        for col in ODDS:
            q = quote(col)
            additions.append(
                f"TRY_CAST("
                f"REPLACE(NULLIF(TRIM({q}), ''), ',', '.') "
                f"AS DOUBLE) AS {quote(col + '_num')}"
            )

        original_cols = ", ".join(quote(c) for c in columns)
        extra_cols = ",\n    ".join(additions)

        con.execute("DROP TABLE IF EXISTS matches_analysis")
        con.execute(f"""
            CREATE TABLE matches_analysis AS
            SELECT
                {original_cols},
                {extra_cols}
            FROM matches_raw
        """)

        raw_count = con.execute(
            "SELECT COUNT(*) FROM matches_raw"
        ).fetchone()[0]
        clean_count = con.execute(
            "SELECT COUNT(*) FROM matches_analysis"
        ).fetchone()[0]

        print("=== ANALIZ TABLOSU ===")
        print("Ham tablo kaydi:", f"{raw_count:,}")
        print("Analiz tablosu kaydi:", f"{clean_count:,}")

        if raw_count != clean_count:
            raise RuntimeError("Kayit sayisi degisti; kontrol gerekli.")

        print("\n=== TARIH KONTROLU ===")
        print(con.execute("""
            SELECT
                MIN(match_date),
                MAX(match_date),
                COUNT(*) FILTER (WHERE match_date IS NULL)
            FROM matches_analysis
        """).fetchone())

        print("\n=== DONUSTURULEN ORANLAR ===")
        for col in ODDS:
            q_raw = quote(col)
            q_num = quote(col + "_num")

            result = con.execute(f"""
                SELECT
                    COUNT(*) FILTER (
                        WHERE NULLIF(TRIM({q_raw}), '') IS NOT NULL
                    ),
                    COUNT(*) FILTER (
                        WHERE NULLIF(TRIM({q_raw}), '') IS NOT NULL
                          AND {q_num} IS NOT NULL
                    ),
                    COUNT(*) FILTER (
                        WHERE NULLIF(TRIM({q_raw}), '') IS NOT NULL
                          AND {q_num} IS NULL
                    ),
                    COUNT(*) FILTER (
                        WHERE {q_num} IS NOT NULL AND {q_num} <= 1
                    )
                FROM matches_analysis
            """).fetchone()

            print(
                f"{col}: dolu={result[0]:,}, "
                f"sayisal={result[1]:,}, "
                f"donusmeyen={result[2]:,}, "
                f"1_veya_altinda={result[3]:,}"
            )

        print("\n=== TEKRAR KONTROLU ===")
        print(con.execute("""
            SELECT COUNT(*) AS toplam,
                   COUNT(DISTINCT hash(
                       "TARİH", "SAAT", "EV", "DEP", "HT", "FT"
                   )) AS farkli_mac_kimligi
            FROM matches_analysis
        """).fetchone())

        print("\nTamamlandi. Ham matches_raw tablosu korunmustur.")
        print("Yeni tablo: matches_analysis")

    finally:
        con.close()

if __name__ == "__main__":
    main()
