# -*- coding: utf-8 -*-
"""
denetim_v5.py
DATA.duckdb ALT/UST oran analizi — iki dönemli denetim (v5.1)

V5'te yapılan düzeltmeler:
  1. Drawdown başlangıcı: kümülatif eğri 0'dan başlar, ilk kayıp dahil.
  2. BH test ailesi: keşif n>=MIN_N_BANT tüm (side, band) çiftleri;
     p_value yoksa aile içinde p=1 ile temsil edilir.
  3. Bootstrap: hareketli blok bootstrap (7 gün) varsayılan; kapsam ve
     sınırlar raporda belgelenir. max_dd_oran tanımı da netleştirildi.
  4. DB yolu: komut satırı > betik yanı > cwd > ~/Downloads.

Korunan ilkeler:
  - Aday seçimi YALNIZCA 2013-2017 keşif döneminden.
  - 2018-2020 doğrulama; 2021 oran verisi eksik olduğu için analiz dışı.
  - Arşiv/FT uyumsuzları ana analizden çıkarılır.
  - edge>0 ve roi>0 AYRI sütunlar; kârlılık için başa baş tutma gerekir.

Gereksinimler:
    pip install duckdb numpy pandas scipy

Çalıştırma:
    python denetim_v5.py [isteğe bağlı: DATA.duckdb tam yolu]
"""

from pathlib import Path
import re
import sys
import unicodedata
import warnings

import duckdb
import numpy as np
import pandas as pd
from scipy import stats


# ================================================================
# 0. AYARLAR
# ================================================================

BASE_DIR = Path(__file__).resolve().parent
OUT = BASE_DIR / "denetim_ciktilari"
OUT.mkdir(parents=True, exist_ok=True)

# Eski üç dönemli çıktılar aynı klasörde kalıp yeni sonucu kirletmesin.
for obsolete in ("04c_bantlar_nihai_test.csv", "05_uc_donem_tum_bantlar.csv"):
    (OUT / obsolete).unlink(missing_ok=True)

ODDS_MIN = 1.01
ODDS_MAX = 100.0

BANT_GENISLIGI = 0.05
MIN_N_BANT     = 200       # BH ailesi ve keşif adayları için eşik
MIN_N_TEST     = 30
MIN_N_DONEM    = 100

BOOTSTRAP_N       = 1000
BOOTSTRAP_BLOCK   = 7        # hareketli blok penceresi (gün)
RNG_SEED          = 20261012
BH_ALPHA          = 0.05

KESIF_BASLANGIC   = 2013
KESIF_BITIS       = 2017
DOGR_BASLANGIC    = 2018
DOGR_BITIS        = 2020

EXCLUDE_MISMATCH  = True     # arşiv/FT uyumsuzları ana analizden çıkarılsın

RNG = np.random.default_rng(RNG_SEED)

def donem_ata(year):
    """Yalnızca keşif/doğrulama; 2021 ve diğer yıllar analiz dışıdır."""
    return np.select(
        [year.between(KESIF_BASLANGIC, KESIF_BITIS),
         year.between(DOGR_BASLANGIC, DOGR_BITIS)],
        ["Kesif","Dogrulama"],
        default="Donem_Disi"
    )


warnings.filterwarnings(
    "ignore",
    message="DataFrameGroupBy.apply operated on the grouping columns"
)


# ================================================================
# 1. VERİTABANI YOLU (düzeltme 4)
# ================================================================

def resolve_db_path():
    adaylar = []
    if len(sys.argv) > 1:
        adaylar.append(Path(sys.argv[1]).expanduser())
    adaylar += [
        BASE_DIR / "DATA.duckdb",
        Path.cwd() / "DATA.duckdb",
        Path.home() / "Downloads" / "DATA.duckdb",
    ]
    gorulen, mevcut = set(), []
    for p in adaylar:
        try:
            p = p.resolve()
        except OSError:
            continue
        if p in gorulen:
            continue
        gorulen.add(p)
        if p.exists():
            mevcut.append(p)
    if not mevcut:
        print("Denenen konumlar:")
        for p in adaylar:
            print(f"  - {p}")
        raise FileNotFoundError(
            "DATA.duckdb bulunamadı. Yol vermek için: "
            "python denetim_v5.py C:\\tam\\yol\\DATA.duckdb"
        )
    return mevcut[0]


# ================================================================
# 2. YARDIMCI FONKSİYONLAR
# ================================================================

def kaydet_csv(df, dosya_adi):
    yol = OUT / dosya_adi
    df.to_csv(yol, index=False, encoding="utf-8-sig")
    return yol


def parse_ft(value):
    if pd.isna(value):
        return np.nan, np.nan
    s = str(value).strip()
    m = re.fullmatch(r"(\d+)\s*[-:–—]\s*(\d+)", s)
    if not m:
        return np.nan, np.nan
    return int(m.group(1)), int(m.group(2))


def normalize_label(value):
    if pd.isna(value):
        return np.nan
    s = str(value).strip().upper()
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("Ü", "U").replace("Ş", "S").replace("İ", "I")
    s = re.sub(r"\s+", " ", s).strip(" .,:;_-/")

    alt_labels = {"A", "ALT", "UNDER", "0",
                  "ALT 2.5", "ALT 2,5", "2.5 ALT", "2,5 ALT"}
    ust_labels = {"UST", "OVER", "1",
                  "UST 2.5", "UST 2,5", "2.5 UST", "2,5 UST"}

    if s in alt_labels: return "ALT"
    if s in ust_labels: return "UST"
    return s


def odds_status(series):
    numeric = pd.to_numeric(series, errors="coerce")
    status = pd.Series("gecerli", index=series.index, dtype="object")
    missing = series.isna()
    nonnumeric = ~missing & numeric.isna()
    status.loc[missing] = "eksik"
    status.loc[nonnumeric] = "sayisal_degil"
    rem = ~(missing | nonnumeric)
    status.loc[rem & (numeric <= 0)] = "sifir_veya_negatif"
    status.loc[rem & (numeric > 0) & (numeric <= 1)] = "0_ile_1_arasi"
    status.loc[rem & (numeric > 1) & (numeric < ODDS_MIN)] = "1_ile_alt_sinir_arasi"
    status.loc[numeric > ODDS_MAX] = "ust_sinir_ustu"
    return numeric, status


def wilson(k, n, alpha=0.05):
    if n <= 0:
        return np.nan, np.nan
    z = stats.norm.ppf(1 - alpha / 2)
    p = k / n
    d = 1 + z * z / n
    merkez = (p + z * z / (2 * n)) / d
    yaricap = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return merkez - yaricap, merkez + yaricap


def score_test(p_fair, wins):
    p_fair = np.asarray(p_fair, dtype=float)
    wins   = np.asarray(wins, dtype=bool)
    mask   = np.isfinite(p_fair) & (p_fair > 0) & (p_fair < 1)
    p_fair = p_fair[mask]; wins = wins[mask]
    n = len(p_fair)
    if n < MIN_N_TEST:
        return n, np.nan, np.nan
    observed = float(wins.sum())
    expected = float(p_fair.sum())
    variance = float(np.sum(p_fair * (1 - p_fair)))
    if variance <= 0:
        return n, np.nan, np.nan
    z = (observed - expected) / np.sqrt(variance)
    return n, float(z), float(2 * stats.norm.sf(abs(z)))


def bh_adjust(p_values):
    p = np.asarray(p_values, dtype=float)
    q = np.full(p.shape, np.nan, dtype=float)
    valid_idx = np.where(np.isfinite(p))[0]
    if len(valid_idx) == 0:
        return q
    pv = p[valid_idx]
    order_local = np.argsort(pv)
    sorted_p = pv[order_local]
    m = len(sorted_p)
    sorted_q = sorted_p * m / np.arange(1, m + 1)
    sorted_q = np.minimum.accumulate(sorted_q[::-1])[::-1]
    sorted_q = np.clip(sorted_q, 0, 1)
    q[valid_idx[order_local]] = sorted_q
    return q


# ---------- Bootstrap (düzeltme 3) ----------

def moving_block_bootstrap_mean_ci(
    df,
    value_col="net_getiri",
    date_col="match_date",
    block_days=BOOTSTRAP_BLOCK,
    n_boot=BOOTSTRAP_N,
    alpha=0.05,
    rng=None,
):
    """
    Hareketli blok bootstrap. Bahisler tarihe göre sıralanır; ardışık
    'block_days' günlük pencereler blok kabul edilir. Her bootstrap
    örneği için bloklar geri koymalı seçilir.

    Kapsam:
      - Ardışık günler arası kısa vadeli otokorelasyon korunur.
      - Aynı günün gözlemleri zaten birlikte hareket eder.
      - Uzun vadeli trendler tamamen modellenmez; GA yine de
        bağımsız örnekleme göre daha gerçekçidir.
    """
    if rng is None:
        rng = RNG

    if len(df) < 2:
        return np.nan, np.nan

    df_s = df[[date_col, value_col]].copy()
    df_s[date_col] = pd.to_datetime(df_s[date_col], errors="coerce")
    df_s = df_s.dropna(subset=[date_col]).sort_values(date_col)
    if len(df_s) < 2:
        return np.nan, np.nan

    df_s["_gun"] = df_s[date_col].dt.normalize()
    gunler = pd.unique(df_s["_gun"])
    m = len(gunler)
    if m < block_days:
        # Blok sayısı yetersizse küme bootstrap'a düş
        return cluster_bootstrap_mean_ci(
            df_s[value_col].values, df_s["_gun"].values,
            n_boot=n_boot, alpha=alpha, rng=rng
        )

    gun_to_idx = {g: np.where(df_s["_gun"].values == g)[0] for g in gunler}
    values = df_s[value_col].to_numpy(dtype=float)

    blok_sayisi = int(np.ceil(m / block_days))
    means = np.empty(n_boot, dtype=float)
    for b in range(n_boot):
        starts = rng.integers(0, m - block_days + 1, size=blok_sayisi)
        idx_all = []
        for s in starts:
            for g in gunler[s:s + block_days]:
                idx_all.append(gun_to_idx[g])
        idx = np.concatenate(idx_all)
        means[b] = values[idx].mean()

    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return float(lo), float(hi)


def cluster_bootstrap_mean_ci(values, clusters, n_boot=BOOTSTRAP_N,
                              alpha=0.05, rng=None):
    """Gün kümesi bazlı küme bootstrap (yedek yöntem)."""
    if rng is None:
        rng = RNG
    values   = np.asarray(values, dtype=float)
    clusters = np.asarray(clusters)
    mask = np.isfinite(values)
    values, clusters = values[mask], clusters[mask]
    if len(values) < 2:
        return np.nan, np.nan

    unique = pd.unique(clusters)
    if len(unique) < 2:
        return np.nan, np.nan

    idx_by_cluster = {k: np.where(clusters == k)[0] for k in unique}
    cluster_keys = np.array(list(idx_by_cluster.keys()), dtype=object)
    m = len(cluster_keys)

    means = np.empty(n_boot, dtype=float)
    for b in range(n_boot):
        picks = rng.integers(0, m, size=m)
        idx = np.concatenate([idx_by_cluster[cluster_keys[j]] for j in picks])
        means[b] = values[idx].mean()

    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return float(lo), float(hi)


# ---------- Drawdown (düzeltme 1) ----------

def drawdown_stats(net_sorted, total_staked=None):
    """
    net_sorted: maç tarihine göre sıralanmış net getiri dizisi.
    Başlangıç sermaye eğrisi 0 kabul edilir; ilk bahsin kaybı da
    drawdown'a dahil edilir.

    Döner:
      max_dd_birim : birim bahis cinsinden en derin tepe-dip farkı
      max_dd_oran  : max_dd_birim / toplam yatırılan birim
                     (klasik % drawdown DEĞİL, kayıp/ciro oranı)
    """
    x = np.asarray(net_sorted, dtype=float)
    if len(x) == 0:
        return np.nan, np.nan

    kum = np.cumsum(x)
    kum_with_start = np.r_[0.0, kum]
    tepe = np.maximum.accumulate(kum_with_start)
    dd   = tepe - kum_with_start
    max_dd = float(dd.max())

    denom = total_staked if total_staked else len(x)
    max_dd_oran = max_dd / denom if denom else np.nan
    return max_dd, max_dd_oran


def roi_audit(df):
    n = len(df)
    if n == 0:
        return {
            "n":0, "galibiyet":0, "tutma":np.nan, "ort_oran":np.nan,
            "basabas_tutma":np.nan, "roi":np.nan, "roi_kontrol":np.nan,
            "roi_fark":np.nan, "toplam_net":np.nan,
            "max_dd_birim":np.nan, "max_dd_oran":np.nan,
        }
    df_s = df.sort_values("match_date")
    wins = df_s["kazandi"].astype(bool)
    net  = df_s["net_getiri"].astype(float)
    winning_odds_sum = df_s.loc[wins, "odds"].sum()
    roi_prog = float(net.mean())
    roi_kont = float((winning_odds_sum - n) / n)
    ort_oran = float(df_s["odds"].mean())
    max_dd_b, max_dd_o = drawdown_stats(net.values, total_staked=n)
    return {
        "n": int(n),
        "galibiyet": int(wins.sum()),
        "tutma": float(wins.mean()),
        "ort_oran": ort_oran,
        "basabas_tutma": 1.0 / ort_oran if ort_oran > 0 else np.nan,
        "roi": roi_prog,
        "roi_kontrol": roi_kont,
        "roi_fark": abs(roi_prog - roi_kont),
        "toplam_net": float(net.sum()),
        "max_dd_birim": max_dd_b,
        "max_dd_oran":  max_dd_o,
    }


def md_table(df, columns=None, max_rows=30):
    if df is None or len(df) == 0:
        return "_Kayıt yok._"
    view = df.copy()
    if columns is not None:
        available = [c for c in columns if c in view.columns]
        view = view[available]
    view = view.head(max_rows)
    headers = list(view.columns)
    lines = [
        "| " + " | ".join(str(x) for x in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for _, row in view.iterrows():
        vals = []
        for v in row:
            if pd.isna(v): vals.append("")
            elif isinstance(v, (float, np.floating)): vals.append(f"{v:.4f}")
            else: vals.append(str(v).replace("|", "/"))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


# ================================================================
# 3. VERİTABANI
# ================================================================

print("=" * 72)
print("ALT/UST ORAN ANALİZİ — DENETİM V5.1 (iki dönemli)")
print("=" * 72)

DB_PATH = resolve_db_path()
print(f"Veritabanı: {DB_PATH}")
print(f"Çıktı klasörü: {OUT}")

con = duckdb.connect(str(DB_PATH), read_only=True)
try:
    table_info = con.execute("PRAGMA table_info('matches_analysis')").df()
    if table_info.empty:
        raise RuntimeError("'matches_analysis' tablosu bulunamadı.")
    existing = set(table_info["name"].astype(str))
    required = {"match_date","FT","MS25AÜ","25A_num","25Ü_num"}
    missing = sorted(required - existing)
    if missing:
        raise RuntimeError("Eksik sütunlar: " + ", ".join(missing))
    raw = con.execute("""
        SELECT match_date, FT, MS25AÜ,
               "25A_num" AS alt_odds_raw,
               "25Ü_num" AS ust_odds_raw
        FROM matches_analysis
    """).df()
finally:
    con.close()


# ================================================================
# 4. SKOR VE SONUÇ EŞLEŞTİRMESİ
# ================================================================

raw["match_date"] = pd.to_datetime(raw["match_date"], errors="coerce")
parsed = raw["FT"].map(parse_ft)
raw["home_goals"] = parsed.map(lambda x: x[0])
raw["away_goals"] = parsed.map(lambda x: x[1])
raw["total_goals"] = raw["home_goals"] + raw["away_goals"]
raw["year"] = raw["match_date"].dt.year
raw["donem"] = donem_ata(raw["year"])

score_valid = (
    raw["home_goals"].notna()
    & raw["away_goals"].notna()
    & raw["match_date"].notna()
)

raw["gercek_sonuc"] = np.select(
    [score_valid & (raw["total_goals"] < 2.5),
     score_valid & (raw["total_goals"] > 2.5)],
    ["ALT", "UST"], default="GECERSIZ"
)
raw["arsiv_sonuc"] = raw["MS25AÜ"].map(normalize_label)

raw["eslesme_durumu"] = np.select(
    [~score_valid,
     raw["arsiv_sonuc"].isna(),
     ~raw["arsiv_sonuc"].isin(["ALT","UST"]),
     raw["gercek_sonuc"] == raw["arsiv_sonuc"]],
    ["gecersiz_skor_veya_tarih","arsiv_sonucu_eksik",
     "bilinmeyen_arsiv_etiketi","uyumlu"],
    default="uyumsuz"
)

match_counts = (raw["eslesme_durumu"].value_counts(dropna=False)
                .rename_axis("durum").reset_index(name="kayit"))
kaydet_csv(match_counts, "01a_sonuc_eslesmesi.csv")

label_counts = (raw["MS25AÜ"].astype("string").fillna("<EKSIK>")
                .value_counts(dropna=False).rename_axis("ham_etiket")
                .reset_index(name="kayit"))
kaydet_csv(label_counts, "01b_arsiv_etiketleri.csv")

invalid_scores = raw.loc[~score_valid,
    ["match_date","FT","MS25AÜ","home_goals","away_goals"]].copy()
kaydet_csv(invalid_scores, "01c_gecersiz_skorlar.csv")

mismatch = raw.loc[
    raw["eslesme_durumu"].isin(
        ["uyumsuz","bilinmeyen_arsiv_etiketi","arsiv_sonucu_eksik"]),
    ["match_date","FT","total_goals","gercek_sonuc","MS25AÜ",
     "arsiv_sonuc","eslesme_durumu"]].copy()
kaydet_csv(mismatch, "01d_eslesmeyen_kayitlar.csv")

year_counts = (raw.groupby("year", dropna=False).size()
               .rename("mac").reset_index()
               .sort_values("year", na_position="last"))
kaydet_csv(year_counts, "01e_yil_bazinda_mac.csv")

print("\n=== 1. SONUÇ EŞLEŞMESİ ===")
print(match_counts.to_string(index=False))
print("\n=== YIL BAZINDA MAÇ ===")
print(year_counts.to_string(index=False))


# ================================================================
# 5. ORAN KONTROLÜ
# ================================================================

raw["alt_odds"], raw["alt_status"] = odds_status(raw["alt_odds_raw"])
raw["ust_odds"], raw["ust_status"] = odds_status(raw["ust_odds_raw"])

status_order = ["gecerli","eksik","sayisal_degil","sifir_veya_negatif",
                "0_ile_1_arasi","1_ile_alt_sinir_arasi","ust_sinir_ustu"]
rows = []
for side, col in [("ALT","alt_status"),("UST","ust_status")]:
    counts = raw[col].value_counts(dropna=False)
    for st in status_order:
        rows.append({"side": side, "durum": st, "kayit": int(counts.get(st, 0))})
odds_status_df = pd.DataFrame(rows)
kaydet_csv(odds_status_df, "02a_oran_durumlari.csv")

raw["alt_gecerli"] = raw["alt_status"].eq("gecerli")
raw["ust_gecerli"] = raw["ust_status"].eq("gecerli")
raw["iki_oran_gecerli"] = raw["alt_gecerli"] & raw["ust_gecerli"]

pair_counts = pd.DataFrame([
    {"metrik":"toplam_satir","deger":len(raw)},
    {"metrik":"alt_gecerli","deger":int(raw["alt_gecerli"].sum())},
    {"metrik":"ust_gecerli","deger":int(raw["ust_gecerli"].sum())},
    {"metrik":"iki_oran_gecerli","deger":int(raw["iki_oran_gecerli"].sum())},
    {"metrik":"herhangi_oran_gecersiz",
     "deger":int((~raw["iki_oran_gecerli"]).sum())},
    {"metrik":"gecerli_skor","deger":int(score_valid.sum())},
])
kaydet_csv(pair_counts, "02b_oran_ozeti.csv")

print("\n=== 2. ORAN DURUMLARI ===")
print(odds_status_df.to_string(index=False))


# ================================================================
# 6. ANALİZE UYGUN MAÇLAR VE MARJ ARINDIRMA
# ================================================================

temel = raw.loc[
    score_valid & raw["gercek_sonuc"].isin(["ALT","UST"])
].copy()

if EXCLUDE_MISMATCH:
    n_before = len(temel)
    temel = temel[temel["eslesme_durumu"] == "uyumlu"].copy()
    n_excluded = n_before - len(temel)
    print(f"\n[EXCLUDE_MISMATCH] Arşiv/FT uyumsuzları çıkarıldı: {n_excluded} maç")
else:
    n_excluded = 0

paired = temel.loc[temel["iki_oran_gecerli"]].copy()
paired["donem"] = donem_ata(paired["year"])
paired = paired.loc[paired["donem"].isin(["Kesif", "Dogrulama"])].copy()
p_alt_raw = 1.0 / paired["alt_odds"]
p_ust_raw = 1.0 / paired["ust_odds"]
paired["overround"]  = p_alt_raw + p_ust_raw
paired["p_alt_fair"] = p_alt_raw / paired["overround"]
paired["p_ust_fair"] = p_ust_raw / paired["overround"]

side_frames = []
donem_disi_bahis_ham = 0
for side, odds_col, fair_col in [
    ("ALT","alt_odds","p_alt_fair"),
    ("UST","ust_odds","p_ust_fair"),
]:
    eligible = temel.loc[temel[f"{side.lower()}_gecerli"]].copy()
    eligible["side"] = side
    eligible["odds"] = eligible[odds_col]
    eligible["row_id"] = eligible.index

    paired_side = paired.copy()
    paired_side["row_id"] = paired_side.index

    eligible = eligible.merge(
        paired_side[["row_id", fair_col, "donem"]],
        on="row_id", how="left", validate="one_to_one"
    ).rename(columns={fair_col: "p_fair"})

    eligible["donem"] = eligible["donem"].fillna(donem_ata(eligible["year"]))
    donem_disi_bahis_ham += int((~eligible["donem"].isin(["Kesif", "Dogrulama"])).sum())
    eligible = eligible.loc[eligible["donem"].isin(["Kesif", "Dogrulama"])].copy()
    eligible["kazandi"] = eligible["side"].eq(eligible["gercek_sonuc"])
    eligible["net_getiri"] = np.where(
        eligible["kazandi"], eligible["odds"] - 1.0, -1.0
    )
    eligible["band_alt"] = (np.floor(
        eligible["odds"] / BANT_GENISLIGI + 1e-10
    ) * BANT_GENISLIGI).round(2)
    eligible["band_ust"] = (eligible["band_alt"] + BANT_GENISLIGI).round(2)
    eligible["band"] = (eligible["band_alt"].map(lambda x: f"{x:.2f}")
                        + "-"
                        + eligible["band_ust"].map(lambda x: f"{x:.2f}"))
    side_frames.append(eligible)

long = pd.concat(side_frames, ignore_index=True)
long = long.sort_values(["match_date","side"]).reset_index(drop=True)

if long.empty:
    raise RuntimeError("Analize uygun bahis bulunamadı.")
if not long["odds"].between(ODDS_MIN, ODDS_MAX).all():
    raise AssertionError("Analiz setinde oran sınırı dışı değer kaldı.")
if long["kazandi"].isna().any():
    raise AssertionError("Sonucu bilinmeyen bahis var.")


# ================================================================
# 7. GENEL ROI (iki dönem ayrı)
# ================================================================

def genel_ozet(df, etiket):
    out = []
    for side, g in df.groupby("side"):
        a = roi_audit(g); a["side"] = side; a["donem"] = etiket
        out.append(a)
    return pd.DataFrame(out)

roi_genel = pd.concat([
    genel_ozet(long[long.donem=="Kesif"],     "Kesif"),
    genel_ozet(long[long.donem=="Dogrulama"], "Dogrulama"),
    genel_ozet(long,                          "Iki_Donem_Toplam"),
], ignore_index=True)

if (roi_genel["roi_fark"].dropna() > 1e-9).any():
    raise AssertionError("ROI aritmetik kontrolü başarısız.")

kaydet_csv(roi_genel, "03a_roi_genel.csv")

overround_summary = pd.DataFrame({
    "metrik": ["mac_sayisi","ortalama","medyan","min","maks","p10","p90"],
    "deger": [
        len(paired),
        paired["overround"].mean() if len(paired) else np.nan,
        paired["overround"].median() if len(paired) else np.nan,
        paired["overround"].min() if len(paired) else np.nan,
        paired["overround"].max() if len(paired) else np.nan,
        paired["overround"].quantile(0.10) if len(paired) else np.nan,
        paired["overround"].quantile(0.90) if len(paired) else np.nan,
    ],
})
kaydet_csv(overround_summary, "03b_overround.csv")

print("\n=== 3. GENEL ROI (iki dönem ayrı) ===")
print(roi_genel.to_string(index=False))
print("\n=== MARJ / OVERROUND ===")
print(overround_summary.to_string(index=False))


# ================================================================
# 8. BANT ANALİZİ — dönem bazında
# ================================================================

def bant_tablosu(df, min_n):
    rows = []
    for (side, ba, band), g in df.groupby(["side","band_alt","band"], sort=True):
        n = len(g)
        if n < min_n:
            continue
        k = int(g["kazandi"].sum())
        win = k / n
        wlo, whi = wilson(k, n)

        paired_g = g.loc[g["p_fair"].notna()]
        n_paired, z, p = score_test(
            paired_g["p_fair"].values, paired_g["kazandi"].values
        )
        if len(paired_g):
            tp = float(paired_g["kazandi"].mean())
            fp = float(paired_g["p_fair"].mean())
            ed = tp - fp
        else:
            tp = fp = ed = np.nan

        a = roi_audit(g)

        # Hareketli blok bootstrap (varsayılan)
        roi_lo, roi_hi = moving_block_bootstrap_mean_ci(
            g, value_col="net_getiri", date_col="match_date",
            block_days=BOOTSTRAP_BLOCK
        )

        rows.append({
            "side": side, "band_alt": ba, "band": band,
            "n": n, "kazanan": k,
            "tutma": win,
            "wilson_alt": wlo, "wilson_ust": whi,
            "basabas_tutma": a["basabas_tutma"],
            "tutma_fark_basabas": (win - a["basabas_tutma"]) if a["basabas_tutma"] else np.nan,
            "ort_oran": a["ort_oran"],
            "roi": a["roi"],
            "roi_kontrol": a["roi_kontrol"],
            "roi_fark": a["roi_fark"],
            "roi_ci_alt": roi_lo, "roi_ci_ust": roi_hi,
            "toplam_net": a["toplam_net"],
            "max_dd_birim": a["max_dd_birim"],
            "max_dd_oran":  a["max_dd_oran"],
            "n_paired": n_paired,
            "tutma_paired": tp, "piyasa_p": fp, "edge": ed,
            "z_score": z, "p_value": p,
        })
    return pd.DataFrame(rows)

bandlar_kesif = bant_tablosu(long[long.donem=="Kesif"],     MIN_N_BANT)
bandlar_dogr  = bant_tablosu(long[long.donem=="Dogrulama"], MIN_N_DONEM)

# ---- BH test ailesi (düzeltme 2) ----
# Aile: keşif döneminde n>=MIN_N_BANT olan TÜM (side, band) çiftleri.
# p_value hesaplanamayan aile üyeleri aile içinde p=1 ile temsil edilir.
if len(bandlar_kesif):
    aile_p = bandlar_kesif["p_value"].copy()
    n_aile = len(aile_p)
    n_p_hesaplanan = int(aile_p.notna().sum())
    n_p_atanan     = int(aile_p.isna().sum())
    aile_p_etkin   = aile_p.fillna(1.0).values

    bandlar_kesif["q_value"] = bh_adjust(aile_p_etkin)
    bandlar_kesif["bh_gecen"] = (
        (bandlar_kesif["q_value"] < BH_ALPHA) & (bandlar_kesif["edge"] > 0)
    )
    bandlar_kesif["edge_pozitif"] = bandlar_kesif["edge"] > 0
    bandlar_kesif["roi_pozitif"]  = bandlar_kesif["roi"]  > 0
else:
    n_aile = n_p_hesaplanan = n_p_atanan = 0
    bandlar_kesif["q_value"] = np.nan
    bandlar_kesif["bh_gecen"] = False
    bandlar_kesif["edge_pozitif"] = False
    bandlar_kesif["roi_pozitif"]  = False

kaydet_csv(bandlar_kesif, "04a_bantlar_kesif.csv")
kaydet_csv(bandlar_dogr,  "04b_bantlar_dogrulama.csv")

print(f"\n=== 4. BANT ANALİZİ ===")
print(f"BH ailesi büyüklüğü: {n_aile} | "
      f"p hesaplanan: {n_p_hesaplanan} | p=1 atanan: {n_p_atanan}")
print(f"BH'yi geçen ve edge>0: {int(bandlar_kesif['bh_gecen'].sum())}")


# ================================================================
# 9. İKİ DÖNEMLİ TABLO — tüm test edilen bantlar
# ================================================================

def bant_ozet_donem(df_long, side, ba, etiket):
    g = df_long.loc[
        (df_long.side==side) & (df_long.band_alt==ba) &
        (df_long.donem==etiket)
    ]
    if len(g) == 0:
        return None
    a = roi_audit(g)
    k = int(g["kazandi"].sum()); n = len(g)
    wlo, whi = wilson(k, n)
    roi_lo, roi_hi = moving_block_bootstrap_mean_ci(
        g, value_col="net_getiri", date_col="match_date",
        block_days=BOOTSTRAP_BLOCK
    )
    paired_g = g.loc[g["p_fair"].notna()]
    if len(paired_g):
        tp = float(paired_g["kazandi"].mean())
        fp = float(paired_g["p_fair"].mean())
        ed = tp - fp
    else:
        tp = fp = ed = np.nan
    return {
        "donem": etiket, "side": side, "band_alt": ba,
        "band": f"{ba:.2f}-{ba+BANT_GENISLIGI:.2f}",
        "n": n, "tutma": a["tutma"],
        "wilson_alt": wlo, "wilson_ust": whi,
        "basabas_tutma": a["basabas_tutma"],
        "tutma_fark_basabas": (a["tutma"] - a["basabas_tutma"]) if a["basabas_tutma"] else np.nan,
        "ort_oran": a["ort_oran"],
        "roi": a["roi"],
        "roi_ci_alt": roi_lo, "roi_ci_ust": roi_hi,
        "toplam_net": a["toplam_net"],
        "max_dd_birim": a["max_dd_birim"],
        "max_dd_oran":  a["max_dd_oran"],
        "tutma_paired": tp, "piyasa_p": fp, "edge": ed,
        "edge_pozitif": bool(np.isfinite(ed) and ed > 0),
        "roi_pozitif":  bool(a["roi"] > 0),
    }

if len(bandlar_kesif):
    kayitlar = []
    for _, r in bandlar_kesif.iterrows():
        for etiket in ["Kesif","Dogrulama"]:
            o = bant_ozet_donem(long, r["side"], r["band_alt"], etiket)
            if o is not None:
                o["bh_gecen_kesif"] = bool(r["bh_gecen"])
                o["q_value_kesif"]  = (float(r["q_value"])
                                       if np.isfinite(r["q_value"]) else np.nan)
                kayitlar.append(o)
    ikidonem = pd.DataFrame(kayitlar)
else:
    ikidonem = pd.DataFrame()

kaydet_csv(ikidonem, "05_iki_donem_tum_bantlar.csv")

print("\n=== 5. İKİ DÖNEMLİ TABLO (tüm keşif bantları) ===")
if len(ikidonem):
    print(ikidonem.sort_values(["side","band_alt","donem"])
          .head(30).to_string(index=False))
else:
    print("Keşifte test edilen bant yok.")


# ================================================================
# 10. EDGE POZİTİF AMA ROI NEGATİF
# ================================================================

if len(bandlar_kesif):
    edge_var_roi_yok = bandlar_kesif.loc[
        bandlar_kesif["edge_pozitif"] & ~bandlar_kesif["roi_pozitif"],
        ["side","band","n","tutma","basabas_tutma","ort_oran",
         "edge","roi","roi_ci_alt","roi_ci_ust",
         "max_dd_birim","max_dd_oran","q_value","bh_gecen"]
    ].sort_values(["side","edge"], ascending=[True, False])
else:
    edge_var_roi_yok = pd.DataFrame()
kaydet_csv(edge_var_roi_yok, "06_edge_var_roi_yok.csv")


# ================================================================
# 11. BETİMLEYİCİ SIRALAMALAR
# ================================================================

def siralamalar(df, etiket):
    if len(df) == 0:
        return
    df.sort_values(["side","tutma","n"], ascending=[True,False,False]) \
      .to_csv(OUT / f"07a_en_sik_tutan_{etiket}.csv",
              index=False, encoding="utf-8-sig")
    df.sort_values(["side","roi","n"], ascending=[True,False,False]) \
      .to_csv(OUT / f"07b_en_az_kaybettiren_{etiket}.csv",
              index=False, encoding="utf-8-sig")
    df.loc[df["roi_pozitif"]] \
      .sort_values(["side","roi"], ascending=[True,False]) \
      .to_csv(OUT / f"07c_pozitif_roi_{etiket}.csv",
              index=False, encoding="utf-8-sig")

siralamalar(bandlar_kesif, "kesif")
siralamalar(bandlar_dogr,  "dogrulama")


# ================================================================
# 12. KALİTE KONTROL
# ================================================================

quality = pd.DataFrame([
    {"kontrol":"veritabani_satir","sonuc":len(raw)},
    {"kontrol":"gecerli_skor_ve_tarih","sonuc":int(score_valid.sum())},
    {"kontrol":"arsiv_uyumlu",
     "sonuc":int((raw["eslesme_durumu"]=="uyumlu").sum())},
    {"kontrol":"arsiv_uyumsuz_belirsiz",
     "sonuc":int(raw["eslesme_durumu"].isin(
         ["uyumsuz","bilinmeyen_arsiv_etiketi","arsiv_sonucu_eksik"]).sum())},
    {"kontrol":"EXCLUDE_MISMATCH","sonuc":str(EXCLUDE_MISMATCH)},
    {"kontrol":"cikarilan_uyumsuz_mac","sonuc":n_excluded},
    {"kontrol":"iki_oran_gecerli_mac","sonuc":len(paired)},
    {"kontrol":"analiz_edilen_bahis","sonuc":len(long)},
    {"kontrol":"kesif_bahis","sonuc":int((long.donem=="Kesif").sum())},
    {"kontrol":"dogrulama_bahis","sonuc":int((long.donem=="Dogrulama").sum())},
    {"kontrol":"long_donem_disi_bahis","sonuc":int((long.donem=="Donem_Disi").sum())},
    {"kontrol":"donem_disi_ham_bahis","sonuc":donem_disi_bahis_ham},
    {"kontrol":"2021_mac_sayisi","sonuc":int(raw["year"].eq(2021).sum())},
    {"kontrol":"2021_donem_disi_mac","sonuc":int((raw["year"].eq(2021) & raw["donem"].eq("Donem_Disi")).sum())},
    {"kontrol":"2021_alt_oran_dolu","sonuc":int((raw["year"].eq(2021) & raw["alt_odds_raw"].notna()).sum())},
    {"kontrol":"2021_alt_oran_gecerli","sonuc":int((raw["year"].eq(2021) & raw["alt_gecerli"]).sum())},
    {"kontrol":"2021_ust_oran_dolu","sonuc":int((raw["year"].eq(2021) & raw["ust_odds_raw"].notna()).sum())},
    {"kontrol":"2021_ust_oran_gecerli","sonuc":int((raw["year"].eq(2021) & raw["ust_gecerli"]).sum())},
    {"kontrol":"ROI_fark_1e9_ustu",
     "sonuc":int((roi_genel["roi_fark"]>1e-9).sum())},
    {"kontrol":"BH_aile_tanim",
     "sonuc":f"kesif_n>={MIN_N_BANT}_tum_side_band"},
    {"kontrol":"BH_aile_buyuklugu","sonuc":n_aile},
    {"kontrol":"BH_aile_p_hesaplanan","sonuc":n_p_hesaplanan},
    {"kontrol":"BH_aile_p_1_atanan","sonuc":n_p_atanan},
    {"kontrol":"BH_gecen_kenar_sayisi",
     "sonuc":int(bandlar_kesif["bh_gecen"].sum()) if len(bandlar_kesif) else 0},
    {"kontrol":"bootstrap_yontemi",
     "sonuc":f"moving_block_{BOOTSTRAP_BLOCK}gun"},
    {"kontrol":"drawdown_baslangic","sonuc":"kumulatif_0_ile_baslar"},
])
kaydet_csv(quality, "08_kalite_kontrol.csv")
print("\n=== 6. KALİTE KONTROL ===")
print(quality.to_string(index=False))


# ================================================================
# 13. MARKDOWN RAPORU
# ================================================================

date_min, date_max = raw["match_date"].min(), raw["match_date"].max()

report = [
    "# ALT/ÜST Oran Analizi — Denetim V5.1 (iki dönemli)",
    "",
    f"- **Veritabanı:** `{DB_PATH}`",
    f"- **Toplam kayıt:** {len(raw):,}",
    f"- **Tarih aralığı:** {date_min} — {date_max}",
    f"- **Keşif:** {KESIF_BASLANGIC}–{KESIF_BITIS}",
    f"- **Doğrulama:** {DOGR_BASLANGIC}–{DOGR_BITIS}",
    "- **Nihai test:** Yok",
    f"- **EXCLUDE_MISMATCH:** {EXCLUDE_MISMATCH} "
    f"(çıkarılan maç: {n_excluded})",
    "",
    "## Yöntem sözleşmesi",
    "",
    f"- **BH test ailesi:** Keşif döneminde n ≥ {MIN_N_BANT} olan "
    f"tüm (side, band) çiftleri. Aile büyüklüğü: {n_aile}. "
    f"p-değeri hesaplanamayan aile üyeleri p=1 ile temsil edilir "
    f"(atanan: {n_p_atanan}).",
    "- **Aday seçimi:** Yalnızca keşif döneminden; doğrulama dönemi "
    "2018–2020 bağımsız sınama olarak kullanılır.",
    "- **Başa baş tutma:** `1 / ortalama oran`. `edge > 0` piyasa "
    "olasılığına göre avantajı gösterir; **pozitif ROI anlamına gelmez**.",
    f"- **Bootstrap:** Hareketli blok bootstrap ({BOOTSTRAP_BLOCK} gün, "
    f"{BOOTSTRAP_N} tekrar). Ardışık günler arası kısa vadeli otokorelasyon "
    "korunur; uzun vadeli trendler modellenmez. Küme bootstrap ile "
    "karşılaştırma için `04*` çıktıları kullanılabilir.",
    "- **Drawdown:** Kümülatif getiri eğrisi 0'dan başlar; ilk bahsin "
    "kaybı da drawdown'a dahildir. `max_dd_birim` birim bahis cinsinden "
    "tepe-dip farkı, `max_dd_oran` bu değerin **toplam yatırılan birime** "
    "oranıdır. `max_dd_oran` klasik % drawdown **değildir**; sermaye "
    "tanımı verilmedikçe yüzde drawdown raporlanmaz.",
    "- **Veri dönemi notu:** 2021 verisi arşivde bulunmaktadır ancak "
    "25A_num ve 25Ü_num sütunları tamamen boştur. Bu nedenle 2021 hiçbir "
    "analiz döneminde kullanılmamıştır. Nihai test dönemi yoktur; "
    "doğrulama dönemi (2018–2020) bağımsız sınama olarak kullanılmıştır.",
    "",
    "## 1. Sonuç eşleşmesi",
    "",
    md_table(match_counts),
    "",
    "## 2. Oran durumları",
    "",
    md_table(odds_status_df),
    "",
    "## 3. Genel ROI (iki dönem ayrı)",
    "",
    md_table(roi_genel),
    "",
    "## 4. Marj / overround",
    "",
    md_table(overround_summary),
    "",
    "## 5. Keşif bantları (BH ailesi — tümü)",
    "",
    md_table(
        bandlar_kesif.sort_values(["side","edge"], ascending=[True,False]),
        ["side","band","n","tutma","basabas_tutma","tutma_fark_basabas",
         "ort_oran","roi","roi_ci_alt","roi_ci_ust",
         "max_dd_birim","max_dd_oran","edge","q_value","bh_gecen",
         "edge_pozitif","roi_pozitif"],
        max_rows=60
    ),
    "",
    "## 6. İki dönemli tablo (tüm test edilen bantlar)",
    "",
    md_table(
        ikidonem,
        ["donem","side","band","n","tutma","basabas_tutma",
         "ort_oran","roi","roi_ci_alt","roi_ci_ust",
         "max_dd_birim","max_dd_oran","edge",
         "edge_pozitif","roi_pozitif","bh_gecen_kesif","q_value_kesif"],
        max_rows=120
    ),
    "",
    "## 7. Edge pozitif ama ROI negatif (keşif)",
    "",
    md_table(
        edge_var_roi_yok,
        ["side","band","n","tutma","basabas_tutma","ort_oran",
         "edge","roi","roi_ci_alt","roi_ci_ust",
         "max_dd_birim","max_dd_oran","q_value","bh_gecen"],
        max_rows=30
    ),
    "",
    "## Kalite kontrol",
    "",
    md_table(quality),
    "",
    "## Sınırlar",
    "",
    "- Geçmiş performans gelecek kârlılığı **garantilemez**.",
    "- ROI aritmetik kontrolü aynı veriden türetilir; bağımsız veri "
    "doğrulaması değildir.",
    "- Score testi normal yaklaşımdır; kesin Poisson-binomial değildir.",
    "- `edge > 0` tek başına kârlılık göstergesi değildir; başa baş "
    "tutma oranı aşılmadıkça ROI negatif kalır.",
    "- Drawdown maç sırasına duyarlıdır; saat bilgisi olmadığı için "
    "aynı gün içindeki sıra belirsizdir.",
    "- Blok bootstrap ardışık günleri korur ama haftalık/aylık ölçekli "
    "bağımlılığı modellemez; GA fazla dar kalabilir.",
    "- 2,5 gol çizgisinde push yoktur.",
    "",
    "## Çıktı dosyaları",
    "",
    "- `01a_sonuc_eslesmesi.csv`, `01b_arsiv_etiketleri.csv`, "
    "`01c_gecersiz_skorlar.csv`, `01d_eslesmeyen_kayitlar.csv`, "
    "`01e_yil_bazinda_mac.csv`",
    "- `02a_oran_durumlari.csv`, `02b_oran_ozeti.csv`",
    "- `03a_roi_genel.csv`, `03b_overround.csv`",
    "- `04a_bantlar_kesif.csv`, `04b_bantlar_dogrulama.csv`",
    "- `05_iki_donem_tum_bantlar.csv`",
    "- `06_edge_var_roi_yok.csv`",
    "- `07a/07b/07c_*_kesif.csv`, `*_dogrulama.csv`",
    "- `08_kalite_kontrol.csv`",
]

(OUT / "RAPOR.md").write_text("\n".join(report), encoding="utf-8")

print("\n" + "=" * 72)
print("ANALİZ TAMAMLANDI")
print(f"Çıktı klasörü: {OUT.resolve()}")
print("=" * 72)