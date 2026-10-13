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

Önceki PR #2 kapsamında raporlanan sonuçlara göre doğrulama döneminde pozitif ROI üreten bant bulunmadı. En iyi görünen bant da negatif ROI ve sıfırın altında kalan güven aralığı gösterdi.

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

Sonuçlar, belirtilen dönemlerde ve bant tanımlarında test edilen adaylar için pozitif kârlılık kanıtı vermemektedir.

> **Sınırlı sonuç:** “Bu bulgular piyasanın verimli olduğunu ispatlamaz. Yalnızca bu veri setinde, kullanılan bant tanımlarında ve bu test yönteminde kârlı bir stratejiye dair kanıt bulunmadığını gösterir.”

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
- Yerel Python çalıştırması gerekmez. İş akışları, veri dosyasının ve beklenen test dosyalarının mevcut olmasına bağlı olarak doğrulama adımlarını yürütür.

## CI davranışı

| Değişiklik / olay | Beklenen iş akışı |
|---|---|
| `denetim_v5.py` değişikliği | ALT/ÜST 2.5 denetimi |
| `denetim_1x2.py` değişikliği | 1X2 denetimi |
| `tests/**` değişikliği | Tek başına hiçbir denetim iş akışını tetiklemez |
| `workflow_dispatch` | Her iki iş akışı da manuel tetiklenebilir |

İş akışlarının `paths` filtreleri betik, ilgili çıktı klasörü ve workflow dosyasındaki değişiklikleri izler; `tests/**` tek başına filtre kapsamına dahil değildir. Yeşil bir workflow sonucu, ilgili analiz adımlarının gerçekten çalıştığı kontrol edilmeden analiz çıktısının üretildiği anlamına gelmez; koşullu olarak atlanan adımlar da incelenmelidir.

## Değişiklik geçmişi

- **PR #4:** CI path filtreleri düzenlendi.
- **PR #3:** 1X2 denetimi eklendi.
- **PR #2:** Conflict nedeniyle kapatıldı; ALT/ÜST çalışması temiz taşıma PR'ı ile yeniden sunuldu.
- **PR #5 / `feature/alt-ust-final`:** ALT/ÜST 2.5 denetiminin temiz taşıması; main'e birleştirildi.

## Gelecek adımlar

- KG (karşılıklı gol), İY/MS ve toplam gol marketleri aynı bağımsız dönem ve güven aralığı disipliniyle incelenebilir.
- Pozitif ROI ve güven aralığıyla desteklenen kanıt bulunmadığı sürece hiçbir bant için “kârlı strateji” iddiası yapılmamalıdır.
