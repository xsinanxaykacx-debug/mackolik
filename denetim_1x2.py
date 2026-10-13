# -*- coding: utf-8 -*-
"""1X2 oran denetimi; analiz yalnızca GitHub Actions üzerinde çalıştırılır."""
from pathlib import Path
import re
import sys
import warnings
import duckdb
import numpy as np
import pandas as pd
from scipy import stats

BASE = Path(__file__).resolve().parent
OUT = BASE / "denetim_ciktilari_1x2"
OUT.mkdir(parents=True, exist_ok=True)
SIDES = {"MS1": "1", "MSX": "X", "MS2": "2"}
SEED = 20261012
BOOT_N = 1000
BLOCK_DAYS = 7
MIN_DISCOVERY = 200
MIN_VALIDATION = 100
warnings.filterwarnings("ignore", category=RuntimeWarning)

def parse_ft(value):
    if pd.isna(value): return (np.nan, np.nan)
    m = re.fullmatch(r"\s*(\d+)\s*[-:–—]\s*(\d+)\s*", str(value))
    return (int(m.group(1)), int(m.group(2))) if m else (np.nan, np.nan)

def odds_numeric(s):
    return pd.to_numeric(s.astype("string").str.replace(",", ".", regex=False), errors="coerce").astype("float64")

def odds_status(s):
    x = odds_numeric(s)
    out = pd.Series("gecerli", index=s.index, dtype="object")
    out[s.isna()] = "eksik"
    out[(~s.isna()) & x.isna()] = "sayisal_degil"
    out[x.notna() & (x <= 0)] = "sifir_veya_negatif"
    out[x.notna() & (x > 0) & (x <= 1)] = "1_veya_alti"
    out[x.notna() & (x > 100)] = "100_ustu"
    return x, out

def wilson(k, n, alpha=.05):
    if n == 0: return np.nan, np.nan
    z = stats.norm.ppf(1-alpha/2); p=k/n; d=1+z*z/n
    mid=(p+z*z/(2*n))/d
    rad=z*np.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return mid-rad, mid+rad

def score_test(p, wins):
    p=np.asarray(p,float); wins=np.asarray(wins,bool)
    m=np.isfinite(p) & (p>0) & (p<1); p=p[m]; wins=wins[m]
    if len(p)<30: return len(p),np.nan,np.nan
    var=float(np.sum(p*(1-p)))
    if var<=0: return len(p),np.nan,np.nan
    z=(float(wins.sum())-float(p.sum()))/np.sqrt(var)
    return len(p),float(z),float(2*stats.norm.sf(abs(z)))

def bh_adjust(values):
    p=np.asarray(values,float); n=len(p)
    if not n: return np.array([],float)
    order=np.argsort(p); q=np.empty(n,float)
    sorted_q=np.minimum.accumulate((p[order]*n/np.arange(1,n+1))[::-1])[::-1]
    q[order]=np.clip(sorted_q,0,1)
    return q

def drawdown_stats(net):
    if not len(net): return np.nan,np.nan
    curve=np.r_[0.0,np.cumsum(np.asarray(net,float))]
    dd=np.maximum.accumulate(curve)-curve
    peak_to_trough=float(dd.max())
    return peak_to_trough, peak_to_trough/len(net)

def moving_block_ci(df, rng, n_boot=BOOT_N, block_days=BLOCK_DAYS):
    """7 günlük hareketli blok bootstrap; gün toplamlarıyla vektörleştirilmiştir."""
    if len(df)<2: return np.nan,np.nan
    d=df[["match_date","net_getiri"]].copy()
    d["match_date"]=pd.to_datetime(d["match_date"],errors="coerce")
    d=d.dropna(subset=["match_date"]).sort_values("match_date")
    if len(d)<2: return np.nan,np.nan
    daily=d.assign(_day=d.match_date.dt.normalize()).groupby("_day",sort=True).net_getiri.agg(["sum","count"])
    sums=daily["sum"].to_numpy(float); counts=daily["count"].to_numpy(float); m=len(daily)
    if m<2: return np.nan,np.nan
    if m>=block_days:
        nblocks=int(np.ceil(m/block_days))
        cs=np.r_[0.0,np.cumsum(sums)]; cc=np.r_[0.0,np.cumsum(counts)]
        block_sum=cs[block_days:]-cs[:-block_days]
        block_count=cc[block_days:]-cc[:-block_days]
        starts=rng.integers(0,m-block_days+1,size=(n_boot,nblocks))
        totals=block_sum[starts].sum(axis=1)
        denom=block_count[starts].sum(axis=1)
    else:
        picks=rng.integers(0,m,size=(n_boot,m))
        totals=sums[picks].sum(axis=1); denom=counts[picks].sum(axis=1)
    means=totals/denom
    return tuple(map(float,np.quantile(means,[.025,.975])))

def audit(g, seed=SEED):
    n=len(g)
    if not n:
        return dict(n=0,kazanan=0,tutma=np.nan,wilson_alt=np.nan,wilson_ust=np.nan,
                    ort_oran=np.nan,basabas_tutma=np.nan,tutma_fark_basabas=np.nan,
                    roi=np.nan,roi_kontrol=np.nan,roi_fark=np.nan,roi_ci_alt=np.nan,
                    roi_ci_ust=np.nan,max_dd_birim=np.nan,max_dd_oran=np.nan,
                    n_paired=0,tutma_paired=np.nan,piyasa_p=np.nan,edge=np.nan,
                    z_score=np.nan,p_value=np.nan)
    g=g.sort_values(["match_date","_rowid"],kind="stable")
    wins=g.kazandi.to_numpy(bool); odds=g.odds.to_numpy(float)
    net=np.where(wins,odds-1,-1.0)
    roi=float(net.mean()); roi2=float((odds[wins].sum()-n)/n)
    avg=float(odds.mean()); k=int(wins.sum()); lo,hi=wilson(k,n)
    paired=g.loc[g.p_fair.notna()]
    npair,z,p=score_test(paired.p_fair.to_numpy(),paired.kazandi.to_numpy())
    tp=float(paired.kazandi.mean()) if len(paired) else np.nan
    mp=float(paired.p_fair.mean()) if len(paired) else np.nan
    dd,ddr=drawdown_stats(net)
    rng=np.random.default_rng(seed)
    ci_lo,ci_hi=moving_block_ci(g.assign(net_getiri=net),rng)
    return dict(n=n,kazanan=k,tutma=k/n,wilson_alt=lo,wilson_ust=hi,
        ort_oran=avg,basabas_tutma=1/avg,tutma_fark_basabas=k/n-1/avg,
        roi=roi,roi_kontrol=roi2,roi_fark=abs(roi-roi2),roi_ci_alt=ci_lo,
        roi_ci_ust=ci_hi,max_dd_birim=dd,max_dd_oran=ddr,n_paired=npair,
        tutma_paired=tp,piyasa_p=mp,edge=tp-mp if np.isfinite(tp) and np.isfinite(mp) else np.nan,
        z_score=z,p_value=p)

def band_for(odds):
    if 1.01 <= odds < 2.00:
        width=.05; lo=np.floor((odds+1e-9)/width)*width
    elif 2.00 <= odds < 4.00:
        width=.10; lo=np.floor((odds+1e-9)/width)*width
    elif 4.00 <= odds < 10.00:
        width=.50; lo=np.floor((odds+1e-9)/width)*width
    elif odds >= 10.00:
        width=1.00; lo=np.floor((odds+1e-9)/width)*width
    else: return np.nan,np.nan,""
    lo=round(float(lo),2); hi=round(lo+width,2)
    return lo,hi,f"{lo:.2f}-{hi:.2f}"

def read_data(db_path):
    con=duckdb.connect(str(db_path),read_only=True)
    try:
        info=con.execute("PRAGMA table_info('matches_analysis')").df()
        cols=set(info["name"].astype(str))
        required={"match_date","FT","MS1","MSX","MS2"}
        missing=required-cols
        if missing: raise RuntimeError("Eksik sütunlar: "+", ".join(sorted(missing)))
        # Ön koşul: 2021 kararından önce yıllık doluluk sorgusu ve raporu.
        sql='''SELECT EXTRACT(YEAR FROM match_date) AS y, COUNT(*) AS n,
          COUNT(MS1) AS ms1_dolu, COUNT(MSX) AS msx_dolu, COUNT(MS2) AS ms2_dolu
          FROM matches_analysis GROUP BY 1 ORDER BY 1'''
        years=con.execute(sql).df()
        print("2021 dahil/haric kararından önce zorunlu yıllık oran doluluk sorgusu:")
        print(years.to_string(index=False))
        raw=con.execute("SELECT match_date, FT, MS1, MSX, MS2 FROM matches_analysis").df()
        return raw,years
    finally: con.close()

def run_audit(raw, years):
    raw=raw.copy()
    raw["match_date"]=pd.to_datetime(raw.match_date,errors="coerce")
    parsed=raw.FT.map(parse_ft)
    raw["home_goals"]=parsed.map(lambda x:x[0]); raw["away_goals"]=parsed.map(lambda x:x[1])
    raw["sonuc"]=np.select([
        raw.home_goals.notna() & raw.away_goals.notna() & (raw.home_goals>raw.away_goals),
        raw.home_goals.notna() & raw.away_goals.notna() & (raw.home_goals==raw.away_goals),
        raw.home_goals.notna() & raw.away_goals.notna() & (raw.home_goals<raw.away_goals)],
        ["1","X","2"],default="")
    raw["year"]=raw.match_date.dt.year
    raw["_rowid"]=np.arange(len(raw))
    # Required 2021 check uses the requested SQL counts; do not infer before this point.
    y2021=years.loc[pd.to_numeric(years.y,errors="coerce").eq(2021)]
    has2021=not y2021.empty
    empty2021=(not has2021 or all(int(y2021.iloc[0][c] or 0)==0 for c in ["ms1_dolu","msx_dolu","ms2_dolu"]))
    use2021=has2021 and not empty2021
    if empty2021: print("2021 DISLANDI: 2021'de MS1/MSX/MS2 sütunlarının üçü de tamamen boş (SQL COUNT sonucu 0).")
    else: print("2021 DOKUNULMAMIŞ NİHAİ TEST: en az bir 1X2 oran sütununda veri var.")
    score=raw.sonuc.ne("") & raw.match_date.notna()
    raw["sonuc_gecerli"]=score
    match=raw.groupby(["sonuc"],dropna=False).size().rename("kayit").reset_index()
    match.to_csv(OUT/"01_sonuc_eslesmesi.csv",index=False,encoding="utf-8-sig")
    status=[]
    numeric={}
    for side in SIDES:
        numeric[side],st=odds_status(raw[side])
        for key,count in st.value_counts(dropna=False).items(): status.append({"secim":side,"durum":key,"kayit":int(count)})
    pd.DataFrame(status,columns=["secim","durum","kayit"]).to_csv(OUT/"02_oran_durumlari.csv",index=False,encoding="utf-8-sig")
    for side in SIDES: raw[side+"_num"]=numeric[side]
    valid_odds=raw[[s+"_num" for s in SIDES]].apply(lambda c:c.between(1.01,100,inclusive="both")).all(axis=1)
    p={s:1/raw[s+"_num"] for s in SIDES}
    raw["overround"]=p["MS1"]+p["MSX"]+p["MS2"]
    raw["p1_fair"]=p["MS1"]/raw.overround; raw["pX_fair"]=p["MSX"]/raw.overround; raw["p2_fair"]=p["MS2"]/raw.overround
    all_valid=valid_odds & raw.overround.gt(1) & np.isfinite(raw.overround) & score
    if (raw.loc[all_valid,"overround"]<=1).any(): raise AssertionError("Overround > 1 kontrolü başarısız")
    long_parts=[]
    for side,label in SIDES.items():
        fair_col={"MS1":"p1_fair","MSX":"pX_fair","MS2":"p2_fair"}[side]
        g=raw.loc[raw[side+"_num"].between(1.01,100,inclusive="both") & score].copy()
        # paired metrics only when all three odds exist and overround is valid.
        g["p_fair"]=np.where(all_valid.loc[g.index],g[fair_col],np.nan)
        g["side"]=side; g["odds"]=g[side+"_num"]; g["kazandi"]=g.sonuc.eq(label)
        g["net_getiri"]=np.where(g.kazandi,g.odds-1,-1.0)
        bands=g.odds.map(band_for)
        g["band_alt"]=bands.map(lambda x:x[0]); g["band_ust"]=bands.map(lambda x:x[1]); g["band"]=bands.map(lambda x:x[2])
        g["donem"]=np.select([g.year.between(2013,2017),g.year.between(2018,2020),g.year.eq(2021)],
            ["Kesif","Dogrulama","NihaiTest"],default="Donem_Disi")
        if empty2021: g.loc[g.year.eq(2021),"donem"]="Donem_Disi"
        if not use2021: g=g[g.donem.ne("NihaiTest")]
        long_parts.append(g)
    long=pd.concat(long_parts,ignore_index=True).sort_values(["match_date","side"],kind="stable")
    # No combined 1X2 bets: every side is summarized independently.
    general=[]
    for period in ["Kesif","Dogrulama"]+(["NihaiTest"] if use2021 else []):
        for side,g in long[long.donem.eq(period)].groupby("side"):
            a=audit(g); general.append({"secim":side,"donem":period,**a})
    pd.DataFrame(general,columns=["secim","donem","n","kazanan","tutma","wilson_alt","wilson_ust","ort_oran","basabas_tutma","tutma_fark_basabas","roi","roi_kontrol","roi_fark","roi_ci_alt","roi_ci_ust","max_dd_birim","max_dd_oran","n_paired","tutma_paired","piyasa_p","edge","z_score","p_value"]).to_csv(OUT/"03_roi_genel.csv",index=False,encoding="utf-8-sig")
    def band_table(period,min_n):
        rows=[]
        part=long[long.donem.eq(period)]
        for (side,ba,band),g in part.groupby(["side","band_alt","band"],dropna=True,sort=True):
            if len(g)<min_n: continue
            rows.append({"secim":side,"band_alt":ba,"band":band,**audit(g)})
        return pd.DataFrame(rows)
    disc=band_table("Kesif",MIN_DISCOVERY)
    val=band_table("Dogrulama",MIN_VALIDATION)
    if len(disc):
        ps=disc.p_value.fillna(1.0).to_numpy(float)
        disc["q_value"]=bh_adjust(ps)
        disc["bh_gecen"]=(disc.q_value<.05)&(disc.edge>0)
    else:
        disc["q_value"]=pd.Series(dtype=float); disc["bh_gecen"]=pd.Series(dtype=bool)
    disc.to_csv(OUT/"04a_bantlar_kesif.csv",index=False,encoding="utf-8-sig")
    val.to_csv(OUT/"04b_bantlar_dogrulama.csv",index=False,encoding="utf-8-sig")
    # Only bands selected in discovery are carried forward; validation never selects candidates.
    candidates=disc[["secim","band_alt","band","q_value","bh_gecen"]].drop_duplicates() if len(disc) else pd.DataFrame(columns=["secim","band_alt","band","q_value","bh_gecen"])
    rows=[]
    for _,cand in candidates.iterrows():
        for period in ["Kesif","Dogrulama"]+(["NihaiTest"] if use2021 else []):
            g=long[(long.side==cand.secim)&(long.band_alt==cand.band_alt)&(long.donem==period)]
            if len(g)<(MIN_DISCOVERY if period=="Kesif" else MIN_VALIDATION): continue
            rows.append({"donem":period,"secim":cand.secim,"band":cand.band,"bh_gecen":bool(cand.bh_gecen),"q_value_kesif":cand.q_value,**audit(g)})
    both=pd.DataFrame(rows)
    both.to_csv(OUT/"05_iki_donem_tum_bantlar.csv",index=False,encoding="utf-8-sig")
    edge_no_roi=both[(both.edge>0)&(both.roi<=0)].copy() if len(both) else pd.DataFrame()
    edge_no_roi.to_csv(OUT/"06_edge_var_roi_yok.csv",index=False,encoding="utf-8-sig")
    # Exact 2021 SQL counts preserved in quality report.
    ydict={int(r.y):r for _,r in years.iterrows() if pd.notna(r.y)}
    y=ydict.get(2021)
    quality=[
      {"kontrol":"veritabani_satir","sonuc":len(raw)},
      {"kontrol":"2021_mac_sayisi","sonuc":int(y.n) if y is not None else 0},
      {"kontrol":"2021_MS1_dolu","sonuc":int(y.ms1_dolu) if y is not None else 0},
      {"kontrol":"2021_MSX_dolu","sonuc":int(y.msx_dolu) if y is not None else 0},
      {"kontrol":"2021_MS2_dolu","sonuc":int(y.ms2_dolu) if y is not None else 0},
      {"kontrol":"2021_karari","sonuc":"DISLANDI_uc_oran_sutunu_da_bos" if empty2021 else "NIHAI_TEST"},
      {"kontrol":"analiz_bahis_satiri","sonuc":len(long)},
      {"kontrol":"kesif_bahis","sonuc":int(long.donem.eq("Kesif").sum())},
      {"kontrol":"dogrulama_bahis","sonuc":int(long.donem.eq("Dogrulama").sum())},
      {"kontrol":"nihai_test_bahis","sonuc":int(long.donem.eq("NihaiTest").sum())},
      {"kontrol":"overround_1den_buyuk_tum_uclu_oranli","sonuc":int(all_valid.sum())},
      {"kontrol":"BH_aile_buyuklugu","sonuc":len(disc)},
      {"kontrol":"BH_p_hesaplanan","sonuc":int(disc.p_value.notna().sum()) if len(disc) else 0},
      {"kontrol":"BH_p_1_atanan","sonuc":int(disc.p_value.isna().sum()) if len(disc) else 0},
      {"kontrol":"BH_gecen","sonuc":int(disc.bh_gecen.sum()) if len(disc) else 0},
      {"kontrol":"bootstrap","sonuc":"moving_block_7_gun_1000_tekrar"},
      {"kontrol":"drawdown_baslangic","sonuc":"kumulatif_0"},
    ]
    pd.DataFrame(quality).to_csv(OUT/"08_kalite_kontrol.csv",index=False,encoding="utf-8-sig")
    # Most promising validation band by ROI; descriptive only, not a new selection rule.
    best=val.sort_values(["roi","n"],ascending=[False,False]).head(1) if len(val) else val
    val_positive=int((val.roi>0).sum()) if len(val) else 0
    val_ci_positive=int((val.roi_ci_alt>0).sum()) if len(val) else 0
    report=["# 1X2 market denetimi","",
      f"- Kayıt: {len(raw)}; geçerli sonuç ve tarih: {int(score.sum())}.",
      "- Keşif: 2013–2017; doğrulama: 2018–2020. Bant adayları yalnızca keşifte seçilir.",
      f"- 2021 SQL doluluk kontrolü: satır={int(y.n) if y is not None else 0}; MS1={int(y.ms1_dolu) if y is not None else 0}; MSX={int(y.msx_dolu) if y is not None else 0}; MS2={int(y.ms2_dolu) if y is not None else 0}.",
      ("- 2021 tamamen dışlandı: üç oran sütununun da COUNT değeri 0; 2021 nihai testi yapılmadı." if empty2021 else "- 2021 oran verisi mevcut; 2021 yalnızca dokunulmamış NihaiTest olarak raporlandı."),
      "- Her seçim (MS1/MSX/MS2) ayrı analiz edilir; seçimler birleştirilerek bahis yapılmaz.",
      "- Fair olasılık yalnızca üç oranı geçerli, sonlu ve overround > 1 olan satırlarda hesaplanır.",
      f"- BH ailesi: keşifte n≥{MIN_DISCOVERY} olan tüm seçim-bant çiftleri; p hesaplanamayan değerler p=1.",
      f"- BH aile büyüklüğü={len(disc)}, hesaplanan p={int(disc.p_value.notna().sum()) if len(disc) else 0}, p=1 atanan={int(disc.p_value.isna().sum()) if len(disc) else 0}.",
      "- ROI GA: hareketli blok bootstrap, 7 gün, 1000 tekrar; seed=20261012. Drawdown kümülatif 0'dan başlar.",
      f"- Doğrulama döneminde pozitif ROI'li bant sayısı: {val_positive}.",
      f"- Doğrulama döneminde roi_ci_alt > 0 olan bant sayısı: {val_ci_positive}.","",
      "## Doğrulamada en iyi görünen bant (betimleyici; seçim keşiften)","",
      (best[["secim","band","n","roi","roi_ci_alt","roi_ci_ust","max_dd_birim","max_dd_oran"]].to_markdown(index=False) if len(best) else "_Yeterli örneklemli doğrulama bandı yok._"),
      "","Bu rapor yalnızca bu veri seti ve belirtilen test tanımı için geçerlidir; genel piyasa verimliliği iddiası değildir."]
    (OUT/"RAPOR.md").write_text("\n".join(report)+"\n",encoding="utf-8")
    print("\nRAPOR özeti:"); print("\n".join(report[-8:]))
    return {"val_positive":val_positive,"val_ci_positive":val_ci_positive,"best":best.to_dict("records")}

def main():
    db=Path(sys.argv[1]) if len(sys.argv)>1 else BASE/"DATA.duckdb"
    if not db.is_file(): raise FileNotFoundError(f"DATA.duckdb bulunamadı: {db}")
    raw,years=read_data(db)
    print("\nZorunlu 2021 SQL çıktısı yukarıda raporlandı; bundan sonra dönem kararı veriliyor.")
    run_audit(raw,years)

if __name__=="__main__": main()
