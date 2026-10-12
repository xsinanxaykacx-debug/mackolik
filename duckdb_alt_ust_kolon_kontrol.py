
# -*- coding: utf-8 -*-
"""
DATA.xlsx / DuckDB - Alt/Üst sütunlarını doğrulama

Amaç:
1. matches_analysis tablosunun varlığını kontrol etmek.
2. MS25AÜ, 25A ve 25Ü sütunlarının gerçek değerlerini incelemek.
3. Değer dağılımlarını ve boş kayıtları raporlamak.
4. FT skorundan hesaplanan 2,5 Alt/Üst sonucuyla
   MS25AÜ sütununu karşılaştırmak.
5. Örnek kayıtları CSV dosyasına kaydetmek.

Bu script veri değiştirmez.
"""

import os
import sys
import csv
import logging
from collections import Counter

import duckdb


# --------------------------------------------------
# AYARLAR
# --------------------------------------------------

DB_PATH = r"C:\Users\bzdye\Downloads\DATA.duckdb"
OUTPUT_DIR = r"C:\Users\bzdye\Downloads"

SAMPLE_CSV = os.path.join(
    OUTPUT_DIR,
    "alt_ust_kolon_ornekleri.csv"
)

LOG_PATH = os.path.join(
    OUTPUT_DIR,
    "alt_ust_kolon_kontrol.log"
)

TABLE_NAME = "matches_analysis"

TARGET_COLUMNS = [
    "MS25AÜ",
    "25A",
    "25Ü",
    "FT",
    "TARİH",
    "EV",
    "DEP",
]

REQUIRED_COLUMNS = [
    "MS25AÜ",
    "25A",
    "25Ü",
    "FT",
]


# --------------------------------------------------
# LOG AYARLARI
# --------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(
            LOG_PATH,
            encoding="utf-8"
        ),
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger(__name__)


# --------------------------------------------------
# YARDIMCI FONKSİYONLAR
# --------------------------------------------------

def quote_identifier(name):
    """DuckDB sütun/tablo adını güvenli biçimde tırnaklar."""
    return '"' + name.replace('"', '""') + '"'


def clean_value(value):
    """Değerleri okunabilir metne dönüştürür."""
    if value is None:
        return ""

    return str(value).strip()


def parse_score(value):
    """
    FT skorunu çözümler.
    Örnek: 2-1 -> (2, 1)
    Geçersiz veya boş değer -> None
    """
    import re

    if value is None:
        return None

    match = re.fullmatch(
        r"\s*(\d+)\s*[-:]\s*(\d+)\s*",
        str(value)
    )

    if not match:
        return None

    return int(match.group(1)), int(match.group(2))


def get_over_under_result(score):
    """
    2,5 gol çizgisinin sonucunu FT skorundan hesaplar.
    Toplam gol 0-2 ise ALT, 3 veya üzeriyse ÜST.
    """
    parsed = parse_score(score)

    if parsed is None:
        return ""

    home_goals, away_goals = parsed
    total_goals = home_goals + away_goals

    return "ALT" if total_goals <= 2 else "ÜST"


def normalize_text(value):
    """Karşılaştırma için metni standartlaştırır."""
    text = clean_value(value).upper()

    replacements = {
        "Ü": "U",
        "İ": "I",
        "Ş": "S",
        "Ğ": "G",
        "Ç": "C",
        "Ö": "O",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return text


def classify_result(value):
    """
    MS25AÜ değerinin ALT/ÜST sonucu olup olmadığını
    yalnızca bilinen açık metinlerden sınıflandırır.
    """
    text = normalize_text(value)

    if not text:
        return ""

    if text in {"A", "ALT", "UNDER", "U25", "25A"}:
        return "ALT"

    if text in {"U", "UST", "OVER", "O25", "25U"}:
        return "ÜST"

    return ""


# --------------------------------------------------
# ANA KONTROL
# --------------------------------------------------

def main():
    if not os.path.isfile(DB_PATH):
        logger.error(
            "DuckDB dosyası bulunamadı: %s",
            DB_PATH
        )
        return 1

    connection = None

    try:
        connection = duckdb.connect(
            database=DB_PATH,
            read_only=True
        )

        logger.info("DuckDB bağlantısı kuruldu.")
        logger.info("Veritabanı: %s", DB_PATH)

        # Tablo kontrolü
        tables = connection.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'main'
            """
        ).fetchall()

        table_names = {row[0] for row in tables}

        if TABLE_NAME not in table_names:
            logger.error(
                "'%s' tablosu bulunamadı.",
                TABLE_NAME
            )
            logger.info(
                "Mevcut tablolar: %s",
                ", ".join(sorted(table_names))
            )
            return 1

        # Sütun yapısı
        schema = connection.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'main'
              AND table_name = ?
            ORDER BY ordinal_position
            """,
            [TABLE_NAME],
        ).fetchall()

        column_types = {
            name: data_type
            for name, data_type in schema
        }

        logger.info("Tablo: %s", TABLE_NAME)
        logger.info("Toplam sütun: %d", len(schema))

        logger.info("=== TABLO YAPISI ===")

        for name, data_type in schema:
            logger.info(
                "Sütun: %-20s Tür: %s",
                name,
                data_type
            )

        missing_columns = [
            name
            for name in REQUIRED_COLUMNS
            if name not in column_types
        ]

        if missing_columns:
            logger.error(
                "Eksik sütunlar: %s",
                ", ".join(missing_columns)
            )
            return 1

        row_count = connection.execute(
            f"SELECT COUNT(*) FROM {quote_identifier(TABLE_NAME)}"
        ).fetchone()[0]

        logger.info("Toplam analiz kaydı: %s", f"{row_count:,}")

        # --------------------------------------------------
        # SÜTUNLARIN DEĞER DAĞILIMLARI
        # --------------------------------------------------

        logger.info("=== ALT/ÜST SÜTUN DAĞILIMLARI ===")

        for column in REQUIRED_COLUMNS:
            q_column = quote_identifier(column)
            q_table = quote_identifier(TABLE_NAME)

            summary = connection.execute(
                f"""
                SELECT
                    COUNT(*) AS total_rows,
                    COUNT({q_column}) AS non_null_rows,
                    COUNT(*) - COUNT({q_column}) AS null_rows,
                    SUM(
                        CASE
                            WHEN TRIM(CAST({q_column} AS VARCHAR)) = ''
                            THEN 1 ELSE 0
                        END
                    ) AS blank_rows
                FROM {q_table}
                """
            ).fetchone()

            logger.info(
                "%s | toplam=%s | dolu=%s | NULL=%s | boş metin=%s",
                column,
                f"{summary[0]:,}",
                f"{summary[1]:,}",
                f"{summary[2]:,}",
                f"{summary[3] or 0:,}",
            )

            distributions = connection.execute(
                f"""
                SELECT
                    TRIM(CAST({q_column} AS VARCHAR)) AS value,
                    COUNT(*) AS quantity
                FROM {q_table}
                GROUP BY 1
                ORDER BY quantity DESC, value
                LIMIT 30
                """
            ).fetchall()

            logger.info("%s | en sık değerler:", column)

            for value, quantity in distributions:
                display_value = value if value else "<BOŞ>"

                logger.info(
                    "  %-20s %s kayıt",
                    display_value,
                    f"{quantity:,}"
                )

        # --------------------------------------------------
        # FT SKORUNDAN ALT/ÜST SONUCU HESAPLAMA
        # --------------------------------------------------

        q_table = quote_identifier(TABLE_NAME)

        select_columns = [
            quote_identifier(column)
            for column in TARGET_COLUMNS
            if column in column_types
        ]

        query = (
            f"SELECT {', '.join(select_columns)} "
            f"FROM {q_table}"
        )

        records = connection.execute(query).fetchall()

        selected_columns = [
            name
            for name in TARGET_COLUMNS
            if name in column_types
        ]

        positions = {
            name: index
            for index, name in enumerate(selected_columns)
        }

        result_counts = Counter()
        comparison_counts = Counter()
        mismatch_examples = []
        csv_rows = []

        for row in records:
            row_data = {
                name: row[index]
                for name, index in positions.items()
            }

            ft_score = row_data.get("FT")
            source_result = row_data.get("MS25AÜ")
            calculated_result = get_over_under_result(ft_score)

            if calculated_result:
                result_counts[calculated_result] += 1
            else:
                result_counts["GEÇERSİZ_SKOR"] += 1

            source_class = classify_result(source_result)

            if not clean_value(source_result):
                comparison_status = "KAYNAK_SONUC_BOS"
            elif not calculated_result:
                comparison_status = "FT_SKORU_GECERSIZ"
            elif not source_class:
                comparison_status = "KAYNAK_DEGERI_TANINMIYOR"
            elif source_class == calculated_result:
                comparison_status = "UYUMLU"
            else:
                comparison_status = "UYUMSUZ"

            comparison_counts[comparison_status] += 1

            output_row = {
                "TARİH": clean_value(row_data.get("TARİH")),
                "EV": clean_value(row_data.get("EV")),
                "DEP": clean_value(row_data.get("DEP")),
                "FT": clean_value(ft_score),
                "MS25AÜ_kaynak": clean_value(source_result),
                "FTden_hesaplanan": calculated_result,
                "karsilastirma": comparison_status,
                "25A_degeri": clean_value(row_data.get("25A")),
                "25Ü_degeri": clean_value(row_data.get("25Ü")),
            }

            csv_rows.append(output_row)

            if (
                comparison_status in {
                    "UYUMSUZ",
                    "KAYNAK_DEGERI_TANINMIYOR",
                }
                and len(mismatch_examples) < 30
            ):
                mismatch_examples.append(output_row)

        logger.info("=== FT SKORUNDAN HESAPLANAN SONUÇLAR ===")

        for result, quantity in result_counts.items():
            logger.info(
                "%-20s %s",
                result,
                f"{quantity:,}"
            )

        logger.info("=== MS25AÜ KARŞILAŞTIRMA SONUÇLARI ===")

        for status, quantity in comparison_counts.items():
            logger.info(
                "%-28s %s",
                status,
                f"{quantity:,}"
            )

        if mismatch_examples:
            logger.info(
                "=== İLK %d UYUŞMAZLIK / TANINMAYAN DEĞER ===",
                len(mismatch_examples)
            )

            for item in mismatch_examples:
                logger.info(
                    "Tarih=%s | Ev=%s | Dep=%s | FT=%s | "
                    "Kaynak=%s | Hesaplanan=%s | Durum=%s",
                    item["TARİH"],
                    item["EV"],
                    item["DEP"],
                    item["FT"],
                    item["MS25AÜ_kaynak"],
                    item["FTden_hesaplanan"],
                    item["karsilastirma"],
                )

        # --------------------------------------------------
        # ÖRNEKLERİ CSV'YE KAYDET
        # --------------------------------------------------

        fieldnames = [
            "TARİH",
            "EV",
            "DEP",
            "FT",
            "MS25AÜ_kaynak",
            "FTden_hesaplanan",
            "karsilastirma",
            "25A_degeri",
            "25Ü_degeri",
        ]

        with open(
            SAMPLE_CSV,
            "w",
            newline="",
            encoding="utf-8-sig",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=fieldnames,
                delimiter=";",
            )

            writer.writeheader()
            writer.writerows(csv_rows)

        logger.info("=== TAMAMLANDI ===")
        logger.info("Örnek/veri kontrol CSV: %s", SAMPLE_CSV)
        logger.info("Log dosyası: %s", LOG_PATH)
        logger.info(
            "Veritabanında hiçbir değişiklik yapılmadı."
        )

        logger.info(
            "NOT: 25A ve 25Ü sütunlarının oran mı sonuç mu olduğu, "
            "değer dağılımı ve kaynak veri anlamı birlikte "
            "değerlendirilerek kesinleştirilmelidir."
        )

        return 0

    except Exception:
        logger.exception("Kontrol sırasında hata oluştu.")
        return 1

    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    sys.exit(main())
