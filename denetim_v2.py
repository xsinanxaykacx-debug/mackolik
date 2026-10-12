
# -*- coding: utf-8 -*-
"""
ALT / ÜST 2.5 ORAN DENETİMİ
===========================

Kaynak:
    DATA.duckdb
    DuckDB tablosu: matches_analysis

Beklenen sütunlar:
    match_date, FT, MS25AÜ, 25A_num, 25Ü_num

Dönemler:
    Keşif       : 2013-2017
    Doğrulama   : 2018-2020
    Nihai test  : 2021

Analiz:
    - ALT ve ÜST oran bantları
    - Kazanma oranı, net birim ve ROI
    - Hareketli blok bootstrap güven aralığı
    - Maksimum düşüş
    - Keşif döneminde BH çoklu test düzeltmesi
    - Doğrulama ve nihai test dönemleri
    - Veri kalite kontrolleri
    - CSV ve Markdown çıktıları

Önemli:
    ROI sonuçları geçmiş veriye aittir. Gelecekte kâr garantisi değildir.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
import traceback
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


# ============================================================
# AYARLAR
# ============================================================

BASLANGIC_YILI = 2013
KESIF_BITIS_YILI = 2017
DOGRULAMA_BASLANGIC = 2018
DOGRULAMA_BITIS = 2020
NIHAI_TEST_YILI = 2021

EXCLUDE_MISMATCH = True

BANT_GENISLIGI = 0.05
MIN_N_BANT = 200
MIN_N_TEST = 30
MIN_N_DONEM = 100

BOOTSTRAP_N = 1000
BOOTSTRAP_BLOK_TARIH = 7
RANDOM_SEED = 20261012
BH_ALPHA = 0.05

TABLO_ADI = "matches_analysis"
CI_ALPHA = 0.05

BASE_DIR = Path(__file__).resolve().parent
OUT = BASE_DIR / "denetim_ciktilari"

RNG = np.random.default_rng(RANDOM_SEED)


# ============================================================
# VERİTABANI BULMA
# ============================================================

def veritabani_yolunu_bul() -> Path:
    parser = argparse.ArgumentParser(
        description="ALT/ÜST oran denetimi"
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="DATA.duckdb dosyasının tam yolu",
    )
    args = parser.parse_args()

    adaylar = []

    if args.db:
        adaylar.append(Path(args.db).expanduser())

    adaylar.extend([
        BASE_DIR / "DATA.duckdb",
        Path.cwd() / "DATA.duckdb",
        Path.home() / "Downloads" / "DATA.duckdb",
        Path(r"C:\Users\bzdye\Downloads\DATA.duckdb"),
    ])

    gorulen = set()

    for aday in adaylar:
        anahtar = str(aday.resolve()).casefold()

        if anahtar in gorulen:
            continue

        gorulen.add(anahtar)

        if aday.is_file():
            return aday.resolve()

    print("DATA.duckdb bulunamadı. Denenen yollar:")

    for aday in adaylar:
        print(f"  {aday}")

    raise FileNotFoundError(
        "Veritabanı bulunamadı. "
        "--db ile tam dosya yolunu belirt."
    )


# ============================================================
# GENEL YARDIMCILAR
# ============================================================

def guvenli_float(deger):
    if pd.isna(deger):
        return np.nan

    if isinstance(deger, (int, float, np.integer, np.floating)):
        sonuc = float(deger)
        return sonuc if math.isfinite(sonuc) else np.nan

    metin = str(deger).strip().replace(" ", "")

    if not metin:
        return np.nan

    if "," in metin and "." in metin:
        if metin.rfind(",") > metin.rfind("."):
            metin = metin.replace(".", "").replace(",", ".")
        else:
            metin = metin.replace(",", "")
    else:
        metin = metin.replace(",", ".")

    try:
        sonuc = float(metin)
    except ValueError:
        return np.nan

    return sonuc if math.isfinite(sonuc) else np.nan


def normalize_metin(deger):
    if pd.isna(deger):
        return ""

    metin = str(deger).strip().upper()

    cevir = str.maketrans({
        "İ": "I",
        "ı": "I",
        "Ü": "U",
        "Ö": "O",
        "Ş": "S",
        "Ğ": "G",
        "Ç": "C",
    })

    return metin.translate(cevir)


def mac_sonucunu_coz(deger):
    """
    FT sütunundan toplam golü çıkarır.

    Desteklenen örnekler:
        2-1
        2:1
        2 - 1
        2–1

    Toplam gol >= 3 ise ÜST kazanır.
    Toplam gol <= 2 ise ALT kazanır.
    """
    if pd.isna(deger):
        return None

    metin = str(deger).strip()

    eslesme = re.search(
        r"(?<!\d)(\d{1,2})\s*[-:–—]\s*(\d{1,2})(?!\d)",
        metin,
    )

    if not eslesme:
        return None

    ev = int(eslesme.group(1))
    dep = int(eslesme.group(2))
    toplam = ev + dep

    return {
        "ev_gol": ev,
        "dep_gol": dep,
        "toplam_gol": toplam,
        "sonuc": "ÜST" if toplam >= 3 else "ALT",
    }


def sonuc_normalize(deger):
    metin = normalize_metin(deger)

    eslesme = {
        "A": "ALT",
        "ALT": "ALT",
        "UNDER": "ALT",
        "U": "ÜST",
        "UST": "ÜST",
        "ÜST": "ÜST",
        "OVER": "ÜST",
    }

    return eslesme.get(metin)


def oran_bant_anahtari(oran):
    """
    Oranı 0.05 genişlikli bantlara yerleştirir.
    Örnek: 1.87 -> [1.85, 1.90)
    """
    if not np.isfinite(oran):
        return None

    if oran <= 1:
        return None

    alt = math.floor(
        (float(oran) + 1e-10) / BANT_GENISLIGI
    ) * BANT_GENISLIGI

    ust = alt + BANT_GENISLIGI

    return round(alt, 4), round(ust, 4)


def tarih_bloklari(tarihler):
    """
    Sıralı ve benzersiz gözlem tarihlerini döndürür.
    """
    ser = pd.to_datetime(
        pd.Series(tarihler), errors="coerce"
    ).dt.normalize()

    return np.sort(ser.dropna().unique())


# ============================================================
# VERİYİ OKU
# ============================================================

def veriyi_yukle(db_path: Path) -> pd.DataFrame:
    print(f"Veritabanı: {db_path}")
    print(f"Tablo: {TABLO_ADI}")

    con = duckdb.connect(
        database=str(db_path),
        read_only=True,
    )

    try:
        tablo_listesi = con.execute(
            "SHOW TABLES"
        ).fetchdf()

        tablolar = set(
            tablo_listesi.iloc[:, 0].astype(str)
        )

        if TABLO_ADI not in tablolar:
            raise RuntimeError(
                f"'{TABLO_ADI}' tablosu bulunamadı. "
                f"Tablolar: {sorted(tablolar)}"
            )

        kolon_df = con.execute(
            f"DESCRIBE SELECT * FROM {TABLO_ADI}"
        ).fetchdf()

        kolonlar = set(kolon_df["column_name"].astype(str))

        gerekli = {
            "match_date",
            "FT",
            "MS25AÜ",
            "25A_num",
            "25Ü_num",
        }

        eksik = gerekli - kolonlar

        if eksik:
            raise RuntimeError(
                "Gerekli sütunlar eksik: "
                + ", ".join(sorted(eksik))
                + "\nMevcut sütunlar: "
                + ", ".join(sorted(kolonlar))
            )

        sorgu = f"""
            SELECT
                match_date,
                FT,
                "MS25AÜ",
                "25A_num",
                "25Ü_num"
            FROM {TABLO_ADI}
        """

        df = con.execute(sorgu).fetchdf()

    finally:
        con.close()

    df["match_date"] = pd.to_datetime(
        df["match_date"], errors="coerce"
    )

    df["alt_oran"] = df["25A_num"].map(guvenli_float)
    df["ust_oran"] = df["25Ü_num"].map(guvenli_float)

    df["kayit_sonucu"] = df["MS25AÜ"].map(
        sonuc_normalize
    )

    cozulen = df["FT"].map(mac_sonucunu_coz)

    df["ev_gol"] = cozulen.map(
        lambda x: x["ev_gol"] if x else np.nan
    )
    df["dep_gol"] = cozulen.map(
        lambda x: x["dep_gol"] if x else np.nan
    )
    df["toplam_gol"] = cozulen.map(
        lambda x: x["toplam_gol"] if x else np.nan
    )
    df["gercek_sonuc"] = cozulen.map(
        lambda x: x["sonuc"] if x else None
    )

    df["yil"] = df["match_date"].dt.year

    return df


# ============================================================
# VERİ KALİTESİ
# ============================================================

def kalite_kontrol(df: pd.DataFrame):
    rapor = []

    rapor.append({
        "kontrol": "kaynak_satir",
        "sonuc": len(df),
    })

    rapor.append({
        "kontrol": "tarihi_gecersiz",
        "sonuc": int(df["match_date"].isna().sum()),
    })

    rapor.append({
        "kontrol": "FT_cozumlenemedi",
        "sonuc": int(df["gercek_sonuc"].isna().sum()),
    })

    rapor.append({
        "kontrol": "ALT_orani_gecersiz",
        "sonuc": int(
            (~np.isfinite(df["alt_oran"]) | (df["alt_oran"] <= 1)).sum()
        ),
    })

    rapor.append({
        "kontrol": "UST_orani_gecersiz",
        "sonuc": int(
            (~np.isfinite(df["ust_oran"]) | (df["ust_oran"] <= 1)).sum()
        ),
    })

    rapor.append({
        "kontrol": "kayit_sonucu_ile_FT_farkli",
        "sonuc": int(
            (
                df["kayit_sonucu"].notna()
                & df["gercek_sonuc"].notna()
                & (df["kayit_sonucu"] != df["gercek_sonuc"])
            ).sum()
        ),
    })

    return pd.DataFrame(rapor)


# ============================================================
# BAHİS SATIRLARINI OLUŞTUR
# ============================================================

def bahisleri_hazirla(df: pd.DataFrame) -> pd.DataFrame:
    ortak = df.copy()

    ortak["sonuc_farki"] = (
        ortak["kayit_sonucu"].notna()
        & ortak["gercek_sonuc"].notna()
        & (ortak["kayit_sonucu"] != ortak["gercek_sonuc"])
    )

    if EXCLUDE_MISMATCH:
        ortak = ortak.loc[~ortak["sonuc_farki"]].copy()

    ortak = ortak.loc[
        ortak["match_date"].notna()
        & ortak["gercek_sonuc"].notna()
    ].copy()

    alt = ortak.loc[
        np.isfinite(ortak["alt_oran"])
        & (ortak["alt_oran"] > 1)
    ].copy()

    alt["side"] = "ALT"
    alt["odds"] = alt["alt_oran"]
    alt["won"] = (
        alt["gercek_sonuc"] == "ALT"
    ).astype(int)

    ust = ortak.loc[
        np.isfinite(ortak["ust_oran"])
        & (ortak["ust_oran"] > 1)
    ].copy()

    ust["side"] = "ÜST"
    ust["odds"] = ust["ust_oran"]
    ust["won"] = (
        ust["gercek_sonuc"] == "ÜST"
    ).astype(int)

    bahisler = pd.concat(
        [alt, ust],
        ignore_index=True,
    )

    bahisler["net_1u"] = np.where(
        bahisler["won"].eq(1),
        bahisler["odds"] - 1.0,
        -1.0,
    )

    bantlar = bahisler["odds"].map(oran_bant_anahtari)

    bahisler["band_low"] = bantlar.map(
        lambda x: x[0] if x else np.nan
    )
    bahisler["band_high"] = bantlar.map(
        lambda x: x[1] if x else np.nan
    )

    bahisler["band"] = bantlar.map(
        lambda x: (
            f"{x[0]:.2f}-{x[1]:.2f}"
            if x else None
        )
    )

    return bahisler.reset_index(drop=True)


# ============================================================
# ROI, KAZANMA ORANI VE DRAWDOWN
# ============================================================

def drawdown_stats(net_sorted):
    x = np.asarray(net_sorted, dtype=float)
    x = x[np.isfinite(x)]

    if len(x) == 0:
        return np.nan, np.nan

    kum = np.concatenate(([0.0], np.cumsum(x)))
    tepe = np.maximum.accumulate(kum)
    dd = tepe - kum

    max_dd_birim = float(dd.max())

    max_dd_oran = (
        max_dd_birim / len(x)
        if len(x) else np.nan
    )

    return max_dd_birim, max_dd_oran


def roi_audit(part: pd.DataFrame) -> dict:
    if part.empty:
        return {
            "n": 0,
            "wins": 0,
            "win_pct": np.nan,
            "net_1u": np.nan,
            "roi": np.nan,
            "avg_odds": np.nan,
            "max_dd_birim": np.nan,
            "max_dd_oran": np.nan,
        }

    sirali = part.sort_values(
        ["match_date"], kind="stable"
    )

    n = len(sirali)
    wins = int(sirali["won"].sum())
    net = float(sirali["net_1u"].sum())

    max_dd_b, max_dd_o = drawdown_stats(
        sirali["net_1u"].to_numpy()
    )

    return {
        "n": n,
        "wins": wins,
        "win_pct": 100.0 * wins / n,
        "net_1u": net,
        "roi": 100.0 * net / n,
        "avg_odds": float(sirali["odds"].mean()),
        "max_dd_birim": max_dd_b,
        "max_dd_oran": max_dd_o,
    }


# ============================================================
# HAREKETLİ BLOK BOOTSTRAP
# ============================================================

def block_bootstrap_mean_ci(
    values,
    clusters,
    n_boot=BOOTSTRAP_N,
    alpha=CI_ALPHA,
    block_len=BOOTSTRAP_BLOK_TARIH,
):
    """
    7 gözlenen tarihlik dairesel hareketli blok bootstrap.

    Aynı tarihteki tüm bahisler birlikte örneklenir.
    Her tekrar, orijinal benzersiz tarih sayısına ulaşana kadar
    ardışık gözlenen tarihlerden bloklar çeker.

    Günlük bahis sayısı farklı olabileceği için her tekrardaki
    satır sayısı değişebilir.
    """
    values = np.asarray(values, dtype=float)

    dates = pd.to_datetime(
        pd.Series(clusters), errors="coerce"
    ).dt.normalize()

    mask = np.isfinite(values) & dates.notna().to_numpy()

    values = values[mask]
    dates = dates.to_numpy(dtype="datetime64[ns]")[mask]

    if len(values) < 2:
        return np.nan, np.nan

    unique_dates = np.sort(np.unique(dates))
    n_dates = len(unique_dates)

    if n_dates < 2:
        return np.nan, np.nan

    block_len = max(1, min(int(block_len), n_dates))

    rows_by_date = {
        tarih: np.flatnonzero(dates == tarih)
        for tarih in unique_dates
    }

    means = []

    for _ in range(int(n_boot)):
        secilen_tarihler = []

        while len(secilen_tarihler) < n_dates:
            baslangic = int(RNG.integers(0, n_dates))

            for j in range(block_len):
                secilen_tarihler.append(
                    unique_dates[(baslangic + j) % n_dates]
                )

                if len(secilen_tarihler) >= n_dates:
                    break

        indeksler = np.concatenate([
            rows_by_date[tarih]
            for tarih in secilen_tarihler
        ])

        if len(indeksler):
            means.append(float(values[indeksler].mean()))

    if len(means) < 2:
        return np.nan, np.nan

    alt, ust = np.quantile(
        np.asarray(means),
        [alpha / 2, 1 - alpha / 2],
    )

    return float(alt), float(ust)


# ============================================================
# BANT ANALİZİ
# ============================================================

def bant_tablosu(
    bahisler: pd.DataFrame,
    min_n: int,
    bootstrap: bool = True,
) -> pd.DataFrame:
    kayitlar = []

    if bahisler.empty:
        return pd.DataFrame()

    gruplar = bahisler.groupby(
        ["side", "band", "band_low", "band_high"],
        dropna=True,
        sort=True,
    )

    for (side, band, low, high), part in gruplar:
        if len(part) < min_n:
            continue

        metrik = roi_audit(part)

        if bootstrap:
            ci_low, ci_high = block_bootstrap_mean_ci(
                part["net_1u"].to_numpy(),
                part["match_date"],
            )

            metrik["roi_ci_low"] = (
                100.0 * ci_low if np.isfinite(ci_low) else np.nan
            )
            metrik["roi_ci_high"] = (
                100.0 * ci_high if np.isfinite(ci_high) else np.nan
            )
        else:
            metrik["roi_ci_low"] = np.nan
            metrik["roi_ci_high"] = np.nan

        metrik.update({
            "side": side,
            "band": band,
            "band_low": low,
            "band_high": high,
            "roi_pozitif": (
                np.isfinite(metrik["roi"])
                and metrik["roi"] > 0
            ),
        })

        kayitlar.append(metrik)

    sonuc = pd.DataFrame(kayitlar)

    if not sonuc.empty:
        sonuc = sonuc.sort_values(
            ["side", "band_low"]
        ).reset_index(drop=True)

    return sonuc


# ============================================================
# BENJAMINI-HOCHBERG
# ============================================================

def bh_adjust(p_values):
    """
    BH düzeltmesi.

    Hesaplanamayan p değerleri aileden çıkarılmaz;
    düzeltmede 1 olarak değerlendirilir.
    """
    p = np.asarray(p_values, dtype=float)

    if len(p) == 0:
        return np.array([], dtype=float)

    p = np.where(
        np.isfinite(p),
        np.clip(p, 0.0, 1.0),
        1.0,
    )

    siralama = np.argsort(p)
    sirali_p = p[siralama]
    m = len(sirali_p)

    sirali_q = (
        sirali_p * m
        / np.arange(1, m + 1, dtype=float)
    )

    sirali_q = np.minimum.accumulate(
        sirali_q[::-1]
    )[::-1]

    sirali_q = np.clip(sirali_q, 0.0, 1.0)

    q = np.empty(m, dtype=float)
    q[siralama] = sirali_q

    return q


def binom_pozitif_roi_p_degeri(part: pd.DataFrame) -> float:
    """
    H0: bahis kazanma olasılığı, ortalama oranla ima edilen
    başa baş olasılığına eşittir.

    Tek taraflı binom testi: gözlenen galibiyet sayısı
    başa baş olasılığından anlamlı biçimde yüksek mi?

    scipy yoksa NaN döndürür; BH aşamasında p=1 uygulanır.
    """
    if part.empty:
        return np.nan

    try:
        from scipy.stats import binomtest
    except ImportError:
        return np.nan

    n = len(part)
    wins = int(part["won"].sum())

    if n <= 0:
        return np.nan

    p_break_even = float(
        np.mean(1.0 / part["odds"].to_numpy(dtype=float))
    )

    p_break_even = min(
        max(p_break_even, 0.0), 1.0
    )

    try:
        return float(
            binomtest(
                wins,
                n=n,
                p=p_break_even,
                alternative="greater",
            ).pvalue
        )
    except Exception:
        return np.nan


def kesif_bh_uygula(
    bahisler: pd.DataFrame,
    bantlar: pd.DataFrame,
):
    if bantlar.empty:
        bantlar["p_value"] = pd.Series(dtype=float)
        bantlar["p_value_bh"] = pd.Series(dtype=float)
        bantlar["bh_p_1_atandi"] = pd.Series(dtype=bool)
        bantlar["q_value"] = pd.Series(dtype=float)
        bantlar["bh_gecen"] = pd.Series(dtype=bool)

        return bantlar, {
            "aile_buyuklugu": 0,
            "p_hesaplanan": 0,
            "p_1_atanan": 0,
        }

    p_values = []

    for _, satir in bantlar.iterrows():
        part = bahisler.loc[
            (bahisler["side"] == satir["side"])
            & (bahisler["band"] == satir["band"])
        ]

        p_values.append(
            binom_pozitif_roi_p_degeri(part)
        )

    bantlar = bantlar.copy()

    bantlar["p_value"] = p_values

    raw_p = bantlar["p_value"].to_numpy(dtype=float)
    eksik = ~np.isfinite(raw_p)

    bantlar["p_value_bh"] = np.where(
        eksik, 1.0, raw_p
    )

    bantlar["bh_p_1_atandi"] = eksik
    bantlar["q_value"] = bh_adjust(
        bantlar["p_value_bh"].to_numpy(dtype=float)
    )

    bantlar["roi_pozitif"] = (
        pd.to_numeric(
            bantlar["roi"], errors="coerce"
        ) > 0
    )

    bantlar["bh_gecen"] = (
        (bantlar["q_value"] < BH_ALPHA)
        & bantlar["roi_pozitif"]
    )

    qa = {
        "aile_buyuklugu": len(bantlar),
        "p_hesaplanan": int((~eksik).sum()),
        "p_1_atanan": int(eksik.sum()),
    }

    return bantlar, qa


# ============================================================
# ÜÇ DÖNEMİN HAZIRLANMASI
# ============================================================

def donemleri_hazirla(bahisler: pd.DataFrame):
    kesif = bahisler.loc[
        bahisler["yil"].between(
            BASLANGIC_YILI, KESIF_BITIS_YILI
        )
    ].copy()

    dogrulama = bahisler.loc[
        bahisler["yil"].between(
            DOGRULAMA_BASLANGIC, DOGRULAMA_BITIS
        )
    ].copy()

    nihai = bahisler.loc[
        bahisler["yil"] == NIHAI_TEST_YILI
    ].copy()

    return kesif, dogrulama, nihai


# ============================================================
# DÖNEM ÖZETLERİ
# ============================================================

def donem_ozeti(
    bahisler: pd.DataFrame,
    donem_adi: str,
) -> pd.DataFrame:
    kayitlar = []

    if bahisler.empty:
        return pd.DataFrame([{
            "donem": donem_adi,
            "side": "TÜMÜ",
            **roi_audit(pd.DataFrame()),
            "roi_ci_low": np.nan,
            "roi_ci_high": np.nan,
        }])

    for side, part in bahisler.groupby("side"):
        metrik = roi_audit(part)

        if len(part) >= MIN_N_DONEM:
            ci_low, ci_high = block_bootstrap_mean_ci(
                part["net_1u"].to_numpy(),
                part["match_date"],
            )

            roi_ci_low = (
                100.0 * ci_low if np.isfinite(ci_low) else np.nan
            )
            roi_ci_high = (
                100.0 * ci_high if np.isfinite(ci_high) else np.nan
            )
        else:
            roi_ci_low = np.nan
            roi_ci_high = np.nan

        metrik.update({
            "donem": donem_adi,
            "side": side,
            "roi_ci_low": roi_ci_low,
            "roi_ci_high": roi_ci_high,
        })

        kayitlar.append(metrik)

    return pd.DataFrame(kayitlar)


def uc_donem_bant_ozeti(
    kesif: pd.DataFrame,
    dogrulama: pd.DataFrame,
    nihai: pd.DataFrame,
) -> pd.DataFrame:
    """
    Keşif döneminde bulunan bantların diğer dönemlerdeki
    performansını ayrıca gösterir.
    """
    kayitlar = []

    if kesif.empty:
        return pd.DataFrame()

    adaylar = kesif[
        ["side", "band", "band_low", "band_high"]
    ].drop_duplicates()

    donemler = [
        ("KESIF", kesif),
        ("DOGRULAMA", dogrulama),
        ("NIHAI_TEST", nihai),
    ]

    for _, aday in adaylar.iterrows():
        for donem_adi, df in donemler:
            part = df.loc[
                (df["side"] == aday["side"])
                & (df["band"] == aday["band"])
            ]

            metrik = roi_audit(part)

            metrik.update({
                "side": aday["side"],
                "band": aday["band"],
                "band_low": aday["band_low"],
                "band_high": aday["band_high"],
                "donem": donem_adi,
            })

            if len(part) >= MIN_N_DONEM:
                lo, hi = block_bootstrap_mean_ci(
                    part["net_1u"].to_numpy(),
                    part["match_date"],
                )

                metrik["roi_ci_low"] = (
                    100.0 * lo if np.isfinite(lo) else np.nan
                )
                metrik["roi_ci_high"] = (
                    100.0 * hi if np.isfinite(hi) else np.nan
                )
            else:
                metrik["roi_ci_low"] = np.nan
                metrik["roi_ci_high"] = np.nan

            kayitlar.append(metrik)

    return pd.DataFrame(kayitlar)


# ============================================================
# SIRALAMALAR
# ============================================================

def siralamalar(df: pd.DataFrame, etiket: str):
    if df.empty:
        return

    df = df.copy()

    if "roi_pozitif" not in df.columns:
        df["roi_pozitif"] = (
            pd.to_numeric(df["roi"], errors="coerce") > 0
        )

    df.sort_values(
        ["side", "n"],
        ascending=[True, False],
    ).to_csv(
        OUT / f"07a_en_cok_gozlem_{etiket}.csv",
        index=False,
        encoding="utf-8-sig",
    )

    df.sort_values(
        ["side", "roi"],
        ascending=[True, False],
    ).to_csv(
        OUT / f"07b_roi_siralamasi_{etiket}.csv",
        index=False,
        encoding="utf-8-sig",
    )

    df.loc[df["roi_pozitif"]].sort_values(
        ["side", "roi"],
        ascending=[True, False],
    ).to_csv(
        OUT / f"07c_pozitif_roi_{etiket}.csv",
        index=False,
        encoding="utf-8-sig",
    )


# ============================================================
# RAPOR
# ============================================================

def rapor_yaz(
    db_path,
    df,
    bahisler,
    kalite,
    kesif_bant,
    dogrulama_bant,
    nihai_bant,
    donem_ozetleri,
    uc_donem,
    bh_qa,
):
    satirlar = [
        "# ALT / ÜST 2.5 Oran Denetimi",
        "",
        "## Kaynak ve yöntem",
        "",
        f"- Veritabanı: `{db_path}`",
        f"- Tablo: `{TABLO_ADI}`",
        f"- Kaynak satır: {len(df):,}",
        f"- Analize alınan bahis satırı: {len(bahisler):,}",
        f"- Keşif dönemi: {BASLANGIC_YILI}-{KESIF_BITIS_YILI}",
        (
            "- Doğrulama dönemi: "
            f"{DOGRULAMA_BASLANGIC}-{DOGRULAMA_BITIS}"
        ),
        f"- Nihai test dönemi: {NIHAI_TEST_YILI}",
        f"- Oran bant genişliği: {BANT_GENISLIGI:.2f}",
        f"- Minimum keşif bant örneklemi: {MIN_N_BANT}",
        f"- Mismatch dışlama: {EXCLUDE_MISMATCH}",
        "",
        "## İstatistiksel notlar",
        "",
        (
            "- ROI = toplam net birim / bahis adedi × 100. "
            "Her bahis bir birim kabul edilir."
        ),
        (
            "- Maksimum düşüş, başlangıçtaki sıfır bakiye dahil "
            "kümülatif net birim serisinden hesaplanır."
        ),
        (
            "- `max_dd_oran`, maksimum düşüşün bahis adedine oranıdır; "
            "sermaye bazlı klasik yüzde drawdown değildir."
        ),
        (
            f"- Bootstrap: {BOOTSTRAP_BLOK_TARIH} gözlenen tarihlik "
            "hareketli blok bootstrap, {BOOTSTRAP_N} tekrar."
        ),
        (
            "- Blok uzunluğu takvim günü değil, gözlem bulunan "
            "benzersiz tarihlerdir. Aynı tarihteki bahisler beraber "
            "örneklenir. Bootstrap tüm bağımlılık sorunlarını gidermez."
        ),
        (
            "- BH düzeltmesi keşif dönemindeki yeterli örneklemli "
            "bant ailesine uygulanır. Hesaplanamayan p-değerleri "
            "aile içinde 1 kabul edilir."
        ),
        (
            "- Keşif sonuçları tek başına doğrulama değildir. "
            "Doğrulama ve nihai test dönemleri ayrı değerlendirilmelidir."
        ),
        "",
        "## BH kalite bilgisi",
        "",
        f"- BH aile büyüklüğü: {bh_qa['aile_buyuklugu']}",
        f"- Hesaplanan p-değeri: {bh_qa['p_hesaplanan']}",
        f"- 1 atanan p-değeri: {bh_qa['p_1_atanan']}",
        "",
        "## Dönem özeti",
        "",
    ]

    if not donem_ozetleri.empty:
        satirlar.append(
            donem_ozetleri.to_markdown(index=False)
        )
    else:
        satirlar.append("Dönem özeti oluşturulamadı.")

    satirlar.extend([
        "",
        "## Keşif bantları",
        "",
    ])

    if not kesif_bant.empty:
        satirlar.append(
            kesif_bant.to_markdown(index=False)
        )
    else:
        satirlar.append(
            "Minimum örneklem koşulunu sağlayan keşif bandı yok."
        )

    satirlar.extend([
        "",
        "## Doğrulama bantları",
        "",
    ])

    if not dogrulama_bant.empty:
        satirlar.append(
            dogrulama_bant.to_markdown(index=False)
        )
    else:
        satirlar.append("Yeterli örneklemli doğrulama bandı yok.")

    satirlar.extend([
        "",
        "## Nihai test bantları",
        "",
    ])

    if not nihai_bant.empty:
        satirlar.append(
            nihai_bant.to_markdown(index=False)
        )
    else:
        satirlar.append("Yeterli örneklemli nihai test bandı yok.")

    satirlar.extend([
        "",
        "## Keşifte seçilen bantların üç dönem karşılaştırması",
        "",
    ])

    if not uc_donem.empty:
        satirlar.append(
            uc_donem.to_markdown(index=False)
        )
    else:
        satirlar.append("Karşılaştırma tablosu oluşturulamadı.")

    satirlar.extend([
        "",
        "## Veri kalite kontrolleri",
        "",
        kalite.to_markdown(index=False),
        "",
        "## Yorum sınırı",
        "",
        (
            "Geçmişte pozitif ROI görülmesi tek başına gerçek bir bahis "
            "avantajını kanıtlamaz. Çoklu denemeler, dönem etkileri, "
            "oran marjı, veri kalitesi ve örneklem büyüklüğü dikkate "
            "alınmalıdır. Nihai test sonuçları seçme sürecinde "
            "kullanılmamalıdır."
        ),
        "",
    ])

    (OUT / "RAPOR.md").write_text(
        "\n".join(satirlar),
        encoding="utf-8",
    )


# ============================================================
# ANA PROGRAM
# ============================================================

def main():
    OUT.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("ALT / ÜST 2.5 ORAN DENETİMİ")
    print("=" * 72)

    db_path = veritabani_yolunu_bul()
    df = veriyi_yukle(db_path)

    if df.empty:
        raise RuntimeError("Kaynak tablo boş.")

    kalite = kalite_kontrol(df)
    kalite.to_csv(
        OUT / "08_veri_kalite.csv",
        index=False,
        encoding="utf-8-sig",
    )

    bahisler = bahisleri_hazirla(df)

    if bahisler.empty:
        raise RuntimeError(
            "Temizleme sonrasında analiz edilecek bahis kalmadı. "
            "FT, oran ve MS25AÜ sütunlarını kontrol et."
        )

    kesif, dogrulama, nihai = donemleri_hazirla(
        bahisler
    )

    print(f"Kaynak satır: {len(df):,}")
    print(f"Analiz bahis satırı: {len(bahisler):,}")
    print(f"Keşif bahis satırı: {len(kesif):,}")
    print(f"Doğrulama bahis satırı: {len(dogrulama):,}")
    print(f"Nihai test bahis satırı: {len(nihai):,}")

    # 1. Dönem özetleri
    donem_ozetleri = pd.concat([
        donem_ozeti(kesif, "KESIF"),
        donem_ozeti(dogrulama, "DOGRULAMA"),
        donem_ozeti(nihai, "NIHAI_TEST"),
    ], ignore_index=True)

    donem_ozetleri.to_csv(
        OUT / "01_donem_ozetleri.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # 2. Keşif bantları
    kesif_bant = bant_tablosu(
        kesif,
        min_n=MIN_N_BANT,
        bootstrap=True,
    )

    kesif_bant, bh_qa = kesif_bh_uygula(
        kesif,
        kesif_bant,
    )

    kesif_bant.to_csv(
        OUT / "02_kesif_bantlari.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # 3. Doğrulama ve nihai test bantları
    dogrulama_bant = bant_tablosu(
        dogrulama,
        min_n=MIN_N_TEST,
        bootstrap=True,
    )

    nihai_bant = bant_tablosu(
        nihai,
        min_n=MIN_N_TEST,
        bootstrap=True,
    )

    dogrulama_bant.to_csv(
        OUT / "03_dogrulama_bantlari.csv",
        index=False,
        encoding="utf-8-sig",
    )

    nihai_bant.to_csv(
        OUT / "04_nihai_test_bantlari.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # 4. Keşifte belirlenen bantları bağımsız dönemlerde incele
    if not kesif_bant.empty:
        secilen = kesif_bant[
            ["side", "band", "band_low", "band_high"]
        ].drop_duplicates()

        kesif_secili = kesif.merge(
            secilen[["side", "band"]],
            on=["side", "band"],
            how="inner",
        )

        dogrulama_secili = dogrulama.merge(
            secilen[["side", "band"]],
            on=["side", "band"],
            how="inner",
        )

        nihai_secili = nihai.merge(
            secilen[["side", "band"]],
            on=["side", "band"],
            how="inner",
        )

        uc_donem = uc_donem_bant_ozeti(
            kesif_secili,
            dogrulama_secili,
            nihai_secili,
        )
    else:
        uc_donem = pd.DataFrame()

    uc_donem.to_csv(
        OUT / "05_uc_donem_karsilastirma.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # 5. Genel bahis ayrıntıları
    bahisler.to_csv(
        OUT / "06_temiz_bahisler.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # 6. Sıralamalar
    siralamalar(kesif_bant, "kesif")
    siralamalar(dogrulama_bant, "dogrulama")
    siralamalar(nihai_bant, "nihai_test")

    # 7. Kalite kontrol dosyası
    qa_rows = [
        {"kontrol": "kaynak_veritabani", "sonuc": str(db_path)},
        {"kontrol": "kaynak_tablo", "sonuc": TABLO_ADI},
        {"kontrol": "kaynak_satir", "sonuc": len(df)},
        {"kontrol": "temiz_bahis_satiri", "sonuc": len(bahisler)},
        {"kontrol": "kesif_bahis_satiri", "sonuc": len(kesif)},
        {"kontrol": "dogrulama_bahis_satiri", "sonuc": len(dogrulama)},
        {"kontrol": "nihai_test_bahis_satiri", "sonuc": len(nihai)},
        {"kontrol": "mismatch_disla", "sonuc": EXCLUDE_MISMATCH},
        {"kontrol": "bant_genisligi", "sonuc": BANT_GENISLIGI},
        {"kontrol": "min_n_bant", "sonuc": MIN_N_BANT},
        {"kontrol": "min_n_test", "sonuc": MIN_N_TEST},
        {"kontrol": "bootstrap_tekrar", "sonuc": BOOTSTRAP_N},
        {"kontrol": "bootstrap_blok_tarih", "sonuc": BOOTSTRAP_BLOK_TARIH},
        {"kontrol": "BH_alpha", "sonuc": BH_ALPHA},
        {"kontrol": "BH_aile_tanim", "sonuc": f"Keşif n>={MIN_N_BANT}; eksik p=1"},
        {"kontrol": "BH_aile_buyuklugu", "sonuc": bh_qa["aile_buyuklugu"]},
        {"kontrol": "BH_p_hesaplanan", "sonuc": bh_qa["p_hesaplanan"]},
        {"kontrol": "BH_p_1_atanan", "sonuc": bh_qa["p_1_atanan"]},
    ]

    pd.DataFrame(qa_rows).to_csv(
        OUT / "09_kalite_kontrol.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # 8. Markdown raporu
    rapor_yaz(
        db_path=db_path,
        df=df,
        bahisler=bahisler,
        kalite=kalite,
        kesif_bant=kesif_bant,
        dogrulama_bant=dogrulama_bant,
        nihai_bant=nihai_bant,
        donem_ozetleri=donem_ozetleri,
        uc_donem=uc_donem,
        bh_qa=bh_qa,
    )

    print()
    print("=" * 72)
    print("ANALİZ TAMAMLANDI")
    print("=" * 72)
    print(f"Çıktı klasörü: {OUT.resolve()}")
    print()

    for dosya in sorted(OUT.iterdir()):
        if dosya.is_file():
            print(f"{dosya.name:42s} {dosya.stat().st_size:>12,} bayt")

    print()
    print(
        "Not: SciPy kurulu değilse p-değerleri hesaplanamaz; "
        "BH aşamasında bunlar 1 olarak tutulur."
    )
    print(
        "Not: Çalıştırma sonucu görülmeden analiz sonuçları "
        "doğrulanmış kabul edilmemelidir."
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nİşlem kullanıcı tarafından durduruldu.")
        sys.exit(130)
    except Exception as exc:
        print(f"\nHATA: {exc}")
        traceback.print_exc()
        sys.exit(1)
