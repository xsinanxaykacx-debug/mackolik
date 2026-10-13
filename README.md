# Maçkolik Futbol Bahis Marketleri Denetimi

**Amaç:** DATA.duckdb üzerinden futbol maç sonuçlarının bahis marketleri bazında bağımsız dönem ve güven aralığı disipliniyle denetimi.

## Veri kaynağı ve kapsam

| Alan | Açıklama |
|---|---|
| Veritabanı | `DATA.duckdb` |
| Tablo | `matches_analysis` |
| Kapsam | 181.946 kayıt, 2013–2021 |
| Sonuç alanları | `FT`, `HT`, `MS25AÜ` |
| ALT/ÜST oran alanları | `25A_num`, `25Ü_num` |
| 1X2 oran alanları | `MS1`, `MSX`, `MS2` |
| Diğer alanlar | Denetimlerde kullanılan tarih, skor ve oran sütunları |

Veri şeması ve oranların yıllara göre doluluğu analiz öncesinde doğrulanmalıdır. Aşağıdaki sonuçlar, bu depodaki denetim çalışmalarında raporlanan dönem ve bant tanımlarına aittir.

## Yöntem sözleşmesi

- **Keşif dönemi:** 2013–2017. Aday bantlar yalnızca bu dönemin verisi kullanılarak seçilir.
- **Doğrulama dönemi:** 2018–2020. Keşifte seçilen adayların bağımsız dönem performansı burada sınanır.
- **2021 kararı:** ALT/ÜST için `25A_num` ve `25Ü_num` oran sütunlarının boş olması nedeniyle 2021 dışlanır. 1X2 denetiminde `MS1`, `MSX`, `MS2` doluluk kontrolü ayrı yapılır; raporlanan 1X2 çalışmasında 2021, oran kapsamı uygunsa nihai test dönemi olarak dahil edilebilir.
- **Marj arındırma:** Olasılıklar, overround (oranların ima ettiği olasılıkların toplamı) dikkate alınarak normalize edilir.
- **Tutma oranı güven aralığı:** Wilson %95 güven aralığı kullanılır.
- **ROI güven aralığı:** 7 günlük hareketli blok bootstrap, 1000 tekrar ile uygulanır.
- **Drawdown:** Kümülatif net getiri eğrisi 0'dan başlar; ilk bahsin sonucu da hesaba katılır.
- **Çoklu karşılaştırma:** Keşif dönemindeki bant testlerinde Benjamini–Hochberg (BH) düzeltmesi uygulanır.
- **Aday seçimi:** Yalnızca keşif döneminden yapılır; doğrulama sonuçlarına bakarak bant seçilmez.
- **Sınırlama:** Pozitif edge veya pozitif tutma farkı tek başına pozitif ROI anlamına gelmez. ROI ve güven aralığı ayrıca değerlendirilir.

## Tamamlanan denetimler ve sonuçlar

### ALT/ÜST 2.5

| Metrik | Sonuç |
|---|---:|
| Keşif + doğrulama aday bandı | 55 |
| Doğrulamada pozitif ROI'li bant | 0 |
| En iyi görünen doğrulama bandı | ÜST 1,15–1,20 |
| ROI | -%10,29 |
| Hareketli blok bootstrap %95 GA | [-%15,85; -%5,16] |

Doğrulama döneminde pozitif ROI'li bant sayısı **0**. En iyi aday olan ÜST 1,15–1,20 bandında ROI -%10,29 ve %95 güven aralığı [-%15,85; -%5,16] olarak ölçüldü.

### 1X2 (MS1, MSX, MS2)

| Metrik | Sonuç |
|---|---:|
| Keşif + doğrulama aday bandı | 110 |
| Doğrulamada pozitif ROI'li bant | 0 |
| `roi_ci_alt > 0` olan bant | 0 |
| En iyi görünen aday | MS2 3,10–3,20 |
| Örnek sayısı (n) | 2.527 |
| ROI | -%7,52 |
| %95 GA | [-%13,29; -%1,74] |

Doğrulama döneminde pozitif ROI'li bant sayısı **0**; `roi_ci_alt > 0` koşulunu sağlayan bant sayısı da **0**. En iyi aday MS2 3,10–3,20 için n=2.527, ROI -%7,52 ve %95 güven aralığı [-%13,29; -%1,74] olarak ölçüldü.

> **Sınırlar:** Bu bulgular piyasanın verimli olduğunu ispatlamaz. Yalnızca bu veri setinde, bu bant tanımlarında ve bu test yönteminde kârlı strateji kanıtı bulunmadığını gösterir.

## Dosya yapısı

| Yol | İşlev |
|---|---|
| `denetim_v5.py` | ALT/ÜST 2.5 iki dönemli denetimi |
| `denetim_1x2.py` | 1X2 market denetimi |
| `denetim_ciktilari/` | ALT/ÜST analiz CSV'leri ve `RAPOR.md` çıktısı |
| `denetim_ciktilari_1x2/` | 1X2 analiz CSV'leri ve `RAPOR.md` çıktısı |
| `.github/workflows/alt-ust-denetim.yml` | ALT/ÜST GitHub Actions iş akışı |
| `.github/workflows/1x2-denetim.yml` | 1X2 GitHub Actions iş akışı |
| `tests/` | Denetim birim testleri |
| `requirements.txt` | Python analiz bağımlılıkları |

Analiz çıktıları çalışma sırasında üretilir; depoda her çalıştırmaya ait CSV ve raporların bulunması garanti değildir.

## Çalıştırma

- Analizler GitHub Actions üzerinde çalıştırılmak üzere tasarlanmıştır.
- Her iki iş akışında da `workflow_dispatch` ile manuel tetikleme tanımlıdır.
- Çalıştırma tamamlandığında üretilen çıktılar Actions artifact olarak yüklenir.
- Yerel Python çalıştırması gerekmez. Her iki iş akışı da gerçek denetimi çalıştırır, beklenen çıktıları doğrular ve sonuçları Actions artifact olarak yükler.

## Testler

- `tests/test_denetim_v5.py`: **5 test** — sentetik örüntü, ROI aritmetik kontrolü, kenar durumlar (boş/tek satır ve eksik oran), aynı seed ile determinizm ve drawdown başlangıcı.
- `tests/test_denetim_1x2.py`: **7 test**.
- Her iki test dosyası CI'da **zorunludur**. Testlerden biri başarısız olursa ilgili workflow kırmızı olur; test dosyalarının eksik olması testlerin atlanmasına yol açmaz.

## CI davranışı

| Değişiklik / olay | Beklenen iş akışı |
|---|---|
| `denetim_v5.py` değişikliği | ALT/ÜST 2.5 denetimi |
| `denetim_1x2.py` değişikliği | 1X2 denetimi |
| `tests/**` değişikliği | Tek başına hiçbir denetim iş akışını tetiklemez |
| `workflow_dispatch` | Her iki iş akışı da manuel tetiklenebilir |

`if: hashFiles(...)` benzeri dosya-varlığına bağlı atlama koşulları kaldırıldı. Test ve gerçek analiz adımları koşulsuz çalışır; gerekli dosya veya çıktı eksikse workflow başarısız olur. `paths` filtresi nedeniyle `tests/**` değişikliği tek başına hiçbir workflow'u tetiklemez.

## Son doğrulanmış durum

### ALT/ÜST

- [GitHub Actions run 38367584191](https://github.com/xsinanxaykacx-debug/mackolik/actions/runs/38367584191): **5 passed in 163.34s**.
- `kesif_bahis=173.372`, `dogrulama_bahis=90.705`, `BH_aile=38`.
- `05_iki_donem_tum_bantlar.csv`: **76 satır**.
- Artifact: [`alt-ust-iki-donem-denetim`](https://github.com/xsinanxaykacx-debug/mackolik/actions/runs/38367584191/artifacts/11797374498).

### 1X2

- [GitHub Actions run 38367584175](https://github.com/xsinanxaykacx-debug/mackolik/actions/runs/38367584175): **7 passed in 1.07s**.
- `kesif_bahis=320.871`, `dogrulama_bahis=170.016`, `BH_aile=110`.
- `05_iki_donem_tum_bantlar.csv`: **321 satır**.
- Artifact: [`1x2-denetim-ciktilari`](https://github.com/xsinanxaykacx-debug/mackolik/actions/runs/38367584175/artifacts/11797288956).

## Dal ve PR durumu

- Uzak dallar: yalnızca `main`.
- Açık PR: **0**.

## Değişiklik geçmişi

- **PR #4:** CI path filtreleri düzenlendi.
- **PR #3:** 1X2 denetimi eklendi.
- **PR #2:** Conflict nedeniyle kapatıldı; ALT/ÜST çalışması temiz taşıma PR'ı ile yeniden sunuldu.
- **PR #5 / `feature/alt-ust-final`:** ALT/ÜST 2.5 denetiminin temiz taşıması; main'e birleştirildi.
- `fix: require real ALT-UST and 1X2 CI audits`
- `chore: branch cleanup (one-time)`
- `test: determinism check for moving-block bootstrap`
- **Merge PR #5:** ALT/ÜST temiz taşıma.

## Gelecek adımlar

- KG (karşılıklı gol), İY/MS ve toplam gol marketleri aynı bağımsız dönem ve güven aralığı disipliniyle incelenebilir.
- Pozitif ROI ve güven aralığıyla desteklenen kanıt bulunmadığı sürece hiçbir bant için “kârlı strateji” iddiası yapılmamalıdır.
