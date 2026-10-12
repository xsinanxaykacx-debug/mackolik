
# -*- coding: utf-8 -*-
"""
DATA.duckdb - Birebir aynı kayıtları güvenli şekilde temizler.
Yalnızca matches_analysis tablosu değiştirilir.
matches_raw tablosuna ve DATA.xlsx dosyasına dokunulmaz.
Temizlik tam olarak 60 fazla kayıt bulursa uygulanır.
"""

import sys
from pathlib import Path

import duckdb


DB_PATH = Path(r"C:\Users\bzdye\Downloads\DATA.duckdb")
TABLE = "matches_analysis"
TEMP_TABLE = "matches_analysis_temiz"

BEKLENEN_SILINECEK_KAYIT = 60


def main():
    if not DB_PATH.exists():
        print(f"HATA: Veritabanı bulunamadı: {DB_PATH}")
        sys.exit(1)

    con = duckdb.connect(str(DB_PATH))

    try:
        con.execute("BEGIN TRANSACTION")

        tablolar = {
            row[0]
            for row in con.execute("SHOW TABLES").fetchall()
        }

        if TABLE not in tablolar:
            raise RuntimeError(f"{TABLE} tablosu bulunamadı.")

        if TEMP_TABLE in tablolar:
            con.execute(f'DROP TABLE "{TEMP_TABLE}"')

        ham_once = con.execute(
            "SELECT COUNT(*) FROM matches_raw"
        ).fetchone()[0]

        once = con.execute(
            f'SELECT COUNT(*) FROM "{TABLE}"'
        ).fetchone()[0]

        # DISTINCT, yalnızca tüm sütunları birebir aynı satırları birleştirir.
        con.execute(
            f'''
            CREATE TABLE "{TEMP_TABLE}" AS
            SELECT DISTINCT *
            FROM "{TABLE}"
            '''
        )

        sonra = con.execute(
            f'SELECT COUNT(*) FROM "{TEMP_TABLE}"'
        ).fetchone()[0]

        silinecek = once - sonra

        print("=== TEMİZLİK ÖN KONTROLÜ ===")
        print(f"Ham tablo kaydı: {ham_once:,}")
        print(f"Analiz tablosu önce: {once:,}")
        print(f"Birebir tekrar fazlası: {silinecek:,}")
        print(f"Temizlik sonrası beklenen: {sonra:,}")

        # Beklenen sayı değilse hiçbir değişiklik uygulama.
        if silinecek != BEKLENEN_SILINECEK_KAYIT:
            con.execute("ROLLBACK")
            print(
                "\nİŞLEM İPTAL: Birebir tekrar sayısı 60 değil. "
                "Tablo değiştirilmedi."
            )
            print(
                "Lütfen bu çıktıyı paylaş; kayıtları inceleyelim."
            )
            return

        # Yeni tablonun tam olarak 60 satır azalmasını doğrula.
        if sonra != once - 60:
            raise RuntimeError("Kayıt sayısı doğrulaması başarısız.")

        # Eski analiz tablosunu temiz tabloyla değiştir.
        con.execute(f'DROP TABLE "{TABLE}"')
        con.execute(
            f'ALTER TABLE "{TEMP_TABLE}" RENAME TO "{TABLE}"'
        )

        # Kaynak tablonun değişmediğini doğrula.
        ham_sonra = con.execute(
            "SELECT COUNT(*) FROM matches_raw"
        ).fetchone()[0]

        if ham_sonra != ham_once:
            raise RuntimeError("Ham tablo kayıt sayısı değişti.")

        con.execute("COMMIT")

        # Son durum kontrolleri.
        analiz_son = con.execute(
            f'SELECT COUNT(*) FROM "{TABLE}"'
        ).fetchone()[0]

        tekrar_kontrol = con.execute(
            f'''
            SELECT COUNT(*)
            FROM (
                SELECT *
                FROM "{TABLE}"
                GROUP BY ALL
                HAVING COUNT(*) > 1
            ) AS tekrarlar
            '''
        ).fetchone()[0]

        print("\n=== TEMİZLİK SONUCU ===")
        print(f"Analiz tablosu önce: {once:,}")
        print(f"Silinen birebir tekrar: {silinecek:,}")
        print(f"Analiz tablosu sonra: {analiz_son:,}")
        print(f"Ham tablo: {ham_sonra:,}")
        print(f"Kalan birebir tekrar grubu: {tekrar_kontrol}")

        if analiz_son == once - 60 and tekrar_kontrol == 0:
            print("\nBAŞARILI: 60 mükerrer kayıt temizlendi.")
        else:
            print("\nUYARI: Son kontrol beklenen sonucu vermedi.")

    except Exception as exc:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass

        print(f"\nHATA: {exc}")
        print("İşlem geri alındı; tekrar deneyebilirsin.")
        sys.exit(1)

    finally:
        con.close()


if __name__ == "__main__":
    main()
