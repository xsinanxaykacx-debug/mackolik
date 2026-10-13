# Oran Kaynağı ve Türkiye Piyasası Uyumu — Veri Envanteri

**Tarih:** 2026-10-13  
**Kapsam:** `DATA.duckdb` içindeki oran alanlarının muhtemel kaynağı, Türkiye yasal piyasasıyla uyumu ve Avrupa oranlarıyla karşılaştırma gereksinimi.  
**Bu rapor bir veri envanteri/doğrulama raporudur; bahis stratejisi önermez.**

## 1. Yönetici özeti

- **En güçlü kaynak göstergesi Maçkolik–İddaa hattıdır.** Maçkolik'ten maç ve oran toplayan açık kaynak arşiv projesi, verisini açıkça Türkiye'nin resmî sabit oranlı bahis oyunu İddaa oranları olarak tanımlar; tarih, maç ve `MS1/MSX/MS2`, ALT/ÜST gibi pazar alanlarını da listeler. Bu, bu arşiv ailesinin Türkiye kaynaklı olduğuna dair güçlü kanıttır. [Kaynak 1](https://github.com/boardsofcanada/mackolik) [Kaynak 2](https://github.com/evrimulgen/mackolik)
- **Ancak `DATA.duckdb` dosyasının kendisi bu GitHub deposunda bulunmuyor.** Bu nedenle bu incelemede veritabanındaki belirli 2020 maç satırlarını doğrudan okuyup aynı maçların Avrupa oranlarıyla bire bir fark yüzdesini hesaplamak mümkün olmadı. Aşağıdaki 2020 maç örnekleri dış kaynaklı Avrupa oranlarıdır; bunlar veritabanı satırıymış gibi sunulmuyor.
- **Yaklaşık %20 1X2 overround, Türkiye piyasası için makul ve tarihsel kanıtla uyumlu bir değer.** iGaming Business'ın 2020'de yayımladığı, La Liga'nın yeniden başlaması dönemindeki ülke karşılaştırmasında Türkiye için overround 1,198 (yaklaşık **%19,8**) raporlanmıştı. Bu sınırlı bir dönem/maç örneklemidir; bütün yıllar ve bütün pazarlar için sabit oran sayılmamalıdır. [Kaynak 3](https://igamingbusiness.com/sports-betting/bookies-matrix-puts-overrounds-under-the-microscope/)
- **Sonuç:** Mevcut kanıt, veritabanı oranlarının Avrupa'nın düşük marjlı bookmaker kapanış oranlarından ziyade Türkiye İddaa/Maçkolik kaynaklı olma ihtimalini güçlü biçimde destekliyor. Yine de dosya içi metadata ve aynı maç satırlarının doğrudan karşılaştırması olmadan bunu kesin veri-soyu kanıtı olarak nitelemiyorum.

## 2. Veritabanı envanteri ve kaynak kanıtı

Bilinen veritabanı envanteri:

| Alan | Bilinen durum |
|---|---|
| Dosya/tablo | `DATA.duckdb` / `matches_analysis` |
| Kapsam | Yaklaşık 181.946 maç kaydı; 2013–2021 |
| 1X2 | `MS1_num`, `MSX_num`, `MS2_num` |
| ALT/ÜST 2,5 | `25A_num`, `25Ü_num` |
| Lig adı | Bilinen şemada ayrı lig adı sütunu yok |
| Kaynak metaverisi | Bu incelemede doğrudan doğrulanamadı |
| DuckDB dosyasının GitHub'da bulunması | Hayır; depo aramasında dosya bulunmadı |

Maçkolik arşivleme projelerinin belgeleri, tarih bazında Maçkolik canlı veri uç noktasından maç kimliklerini bulup arşiv maç sayfalarından oranları aldıklarını ve bunları İddaa oranları olarak sakladıklarını açıklıyor. CSV şemasında `MS1`, `MSX`, `MS2`, `2.5A`, `2.5U`, `KGV`, `KGY` gibi alanlar yer alıyor. Bu alan ailesi, mevcut veritabanında bilinen oran adlarıyla örtüşüyor. Bu örtüşme **kaynak ailesi için güçlü bir ipucu**, fakat tek başına yerel DuckDB dosyasının her satırını kanıtlamaz. [Kaynak 1](https://github.com/boardsofcanada/mackolik)

## 3. Aynı dönem için çevrimiçi Avrupa oranı örnekleri

CheckBestOdds'un Türkiye 2020/2021 tarihsel arşivi, maç bazında 1-X-2 oranlarını ve sayfanın açıklamasına göre kaydedilen bookmaker'lar arasındaki **son en yüksek oranları** listeliyor. Aşağıdaki iki örnek bu arşivden alınmıştır. Bunlar tek bir bookmaker'ın tam fiyat seti değil, farklı bookmaker'lardan alınan en yüksek fiyatların birleşimi olduğundan, marjı olduğundan düşük gösterebilir. [Kaynak 4](https://checkbestodds.com/football-odds/archive-turkey/2020-2021)

| Maç | Tarih | 1 | X | 2 | Oranlardan hesaplanan overround |
|---|---:|---:|---:|---:|---:|
| Çaykur Rizespor – Fenerbahçe | 11.09.2020 | 4,13 | 3,92 | 1,97 | yaklaşık **%0,48** |
| Sivasspor – Alanyaspor | 12.09.2020 | 2,17 | 3,75 | 3,46 | yaklaşık **%1,65** |

Hesaplama: `overround = (1/1_oranı + 1/X_oranı + 1/2_oranı - 1) × 100`.

**Bu iki satırın yorumu:** Çok düşük sonuçlar, arşivin “son en yüksek oran” metoduyla uyumludur; bunlar normal bir bookmaker'ın tek başına sunduğu 1X2 fiyat seti olarak değerlendirilmemelidir. Dolayısıyla bu örnekler Avrupa/uluslararası oranların nasıl görünebildiğini gösterir, ancak `DATA.duckdb` ile bire bir fark yüzdesi vermez.

### Doğrudan eşleşme karşılaştırmasının durumu

Bu oturumda veritabanının kendisi mevcut olmadığı ve depo içinde `DATA.duckdb` bulunmadığı için Rizespor–Fenerbahçe veya Sivasspor–Alanyaspor satırlarının `MS1_num/MSX_num/MS2_num` değerleri okunamadı. Bu nedenle şu ölçümler **hesaplanmış gibi gösterilmemiştir**:

- Veritabanı oranı ile Avrupa oranı arasındaki maç bazlı fark yüzdesi;
- Aynı maçın veritabanı overround'u ile Avrupa bookmaker overround'u arasındaki fark;
- 2020 Süper Lig örneklemi genelinde ortalama/medyan oran farkı.

Bire bir kıyas için aynı maç ve aynı zaman damgası (açılış/kapanış/maç öncesi snapshot) eşleştirilmeli; ayrıca “en yüksek oran” ile tek bookmaker oranı birbirine karıştırılmamalıdır.

## 4. Overround: Türkiye ve Avrupa kıyası

### 4.1 Türkiye için yaklaşık %20 gerçekçi mi?

Evet, **1X2 pazarı açısından tarihsel olarak makul**. 2020'deki ülke karşılaştırmasında Türkiye için 1,198 book percentage, yani yaklaşık %19,8 overround raporlanmış; bu oran çalışmada incelenen ülkeler arasında en yükseklerden biri olarak belirtilmiştir. Çalışma, Türkiye ve İzlanda'yı sonraki ülkelerden belirgin biçimde yüksek bulmuş ve bunu rekabetin sınırlı olduğu piyasa yapısıyla ilişkilendirmiştir. [Kaynak 3](https://igamingbusiness.com/sports-betting/bookies-matrix-puts-overrounds-under-the-microscope/)

Daha yeni akademik çalışma da Türkiye'deki ana yasal sağlayıcı ile altı yasal çevrimiçi sağlayıcının oranlarını ve yurt dışı merkezli bir sağlayıcının oranlarını 18 Ağustos–18 Eylül 2024 arasında 464 maçta karşılaştırmış; yurt dışı sağlayıcının ortalama 1X2 oranlarını daha yüksek bulmuştur. Örneğin ortalama ev sahibi galibiyeti oranı yasal ana sağlayıcıda 2,32, karşılaştırılan yurt dışı sağlayıcıda 2,54; beraberlik 3,4553'e karşı 3,8132; deplasman galibiyeti 3,41'e karşı 3,64'tür. Yurt dışı oranlarının yasal ana sağlayıcıya göre bu ortalama farkları sırasıyla yaklaşık **%9,5**, **%10,4** ve **%6,7** daha yüksektir. Bu oran farkları, **aynı maçlarda marj arındırılmış olasılık veya overround farkıyla aynı şey değildir**; çalışma da tüm Avrupa bookmaker'larını temsil etmez. [Kaynak 5](https://dergipark.org.tr/en/download/article-file/4827828)

### 4.2 Avrupa oranları için kıyas ölçütü

“Avrupa oranı” tek bir piyasa değildir. Ülke, bookmaker, maç, pazar türü, fiyatın alındığı zaman ve en yüksek oranların birleştirilip birleştirilmemesi sonucu değiştirir. Bu yüzden tek bir genel Avrupa marjı ile Türkiye'yi karşılaştırmak yerine, aynı maçlar için şu ayrı referanslar tutulmalıdır:

1. **Tek bookmaker kapanış oranı** (ör. Bet365 veya Pinnacle; sağlayıcı ve zaman damgası kayıtlı);
2. **Piyasa ortalaması** (aynı maç ve zaman penceresindeki oranların ortalaması);
3. **En yüksek erişilebilir oran** (birden çok bookmaker'ın sonuç bazında en iyi fiyatı; overround'u yapay biçimde düşürebilir);
4. Türkiye İddaa/Maçkolik oranı.

Düşük marjlı Avrupa 1X2 pazarları çoğu zaman birkaç yüzde puanlık marj düzeyindedir; fakat lig ve operatöre göre değişir. Bu raporda “Avrupa geneli kesin ortalama %X” iddiası yapılmıyor, çünkü elde aynı kapsam ve yöntemle oluşturulmuş karşılaştırılabilir örneklem yok.

## 5. %20 overround sonuçların genellenebilirliğini nasıl etkiler?

Eğer `DATA.duckdb` oranları Türkiye İddaa/Maçkolik fiyatlarıysa:

- **Kârlılık sonuçları doğrudan Avrupa piyasasına taşınamaz.** Aynı tahmin olasılığı, daha düşük marjlı Avrupa fiyatlarında farklı beklenen getiri üretebilir.
- **Oran bantları ve eşikler piyasa-özel olabilir.** Türkiye'deki yüksek marj ve fiyatlama biçimiyle belirlenen 1,80–2,00 gibi bir bant, Avrupa kapanış oranlarında aynı ekonomik anlama gelmeyebilir.
- **Marj arındırması gerekli ama yeterli değildir.** `1/oran` olasılıklarını toplam olasılığa bölerek normalize etmek overround'u gideren bir yaklaşımdır; ancak favori–uzun at eğilimi, bookmaker'a özgü fiyatlama ve zaman farkı gibi etkileri otomatik olarak düzeltmez.
- **Veri sızıntısı ve zaman uyumu kontrol edilmelidir.** Maçkolik'te kaydedilmiş oranların açılış mı, kapanış mı, yoksa arşiv sayfasında görülen belirli bir snapshot mı olduğu belgelenmeden, bunları Avrupa kapanış oranlarıyla eşleştirmek sağlıklı değildir.
- **Sonuçların kapsamı açık yazılmalıdır.** Şimdiki denetimlerdeki negatif ROI, bu veri setindeki fiyatlar ve test dönemi için geçerlidir; tek başına bütün Avrupa piyasalarının veya her yasal/uluslararası sağlayıcının performansını kanıtlamaz.

## 6. Önerilen veri envanteri yolu

1. **Kaynak soyunu doğrula:** `DATA.duckdb` dosyasının oluşturulma betiği, indirilen ham dosya, scraper URL'leri ve kolon eşlemeleri saklanmalı. Kaynak ve toplama tarihi dosya düzeyinde belgelenmeli.
2. **Satır düzeyinde örnek çıkar:** 2020 Süper Lig'den en az 30–50 maçı, `match_date`, ev/deplasman, skor ve `MS1_num/MSX_num/MS2_num` alanlarıyla dışa aktar. Lig adı yoksa takım ve fikstür kaynaklarıyla lig eşlemesi doğrulanmalı.
3. **Aynı maçları dış arşivle eşleştir:** Tarih + ev sahibi + deplasman anahtarı kullan; takım isimlerindeki yazım farklarını normalize et. Eşleşmeyen maçları rapordan çıkarma, ayrı say.
4. **Zaman ve fiyat türünü sabitle:** İddaa arşiv oranı ile Avrupa kapanış oranını karşılaştırıyorsan bunu açıkça etiketle; mümkün değilse “yaklaşık tarihsel fiyat kıyası” de.
5. **Her 1X2 üçlüsünde overround hesapla:** `(1/MS1 + 1/MSX + 1/MS2 - 1) × 100`. Her sağlayıcıyı ayrı hesapla; best-odds birleşimini ayrı bir kategori tut.
6. **Oran farkını her seçim için hesapla:** `fark_% = (Avrupa_oranı / veritabanı_oranı - 1) × 100`. Sonra maçlar arasında ortalama yerine medyanı ve çeyrekler arası aralığı da raporla; uç oranlar ortalamayı bozabilir.
7. **Pazar bazında ayrı tut:** 1X2, ALT/ÜST 2,5 ve diğer marketlerin overround'larını birbirine karıştırma.

## 7. Nihai karar

**En olası kaynak: Türkiye İddaa oranlarını Maçkolik üzerinden arşivleyen veri hattı.** Bu sonuç, Maçkolik/İddaa kaynaklı arşiv projelerinin açık dokümantasyonu ve Türkiye için raporlanmış yaklaşık %19,8 tarihsel 1X2 overround bulgusuyla tutarlıdır.

**Güven düzeyi: orta-yüksek kaynak ailesi çıkarımı; doğrudan dosya içi doğrulama tamamlanmadı.** `DATA.duckdb` bu depoda olmadığından, veritabanındaki 2020 maç oranlarıyla Avrupa oranlarının maç bazlı yüzde farkı henüz hesaplanmadı. Yukarıdaki dış örnekler ve araştırma bulguları bu boşluğu gizlemiyor. Avrupa oranlarıyla gelecek kıyaslamalarda ayrı bir Avrupa referans sütun seti oluşturulmalı; Türkiye oranları silinmemeli veya üzerlerine yazılmamalı.

## Kaynaklar

1. [boardsofcanada/mackolik — Maçkolik'ten İddaa oranlarını arşivleyen proje ve CSV alanları](https://github.com/boardsofcanada/mackolik)
2. [evrimulgen/mackolik — İddaa oranı kaynağı ve arşiv yöntemine ilişkin ikinci proje belgesi](https://github.com/evrimulgen/mackolik)
3. [iGaming Business — Bookies Matrix puts overrounds under the microscope](https://igamingbusiness.com/sports-betting/bookies-matrix-puts-overrounds-under-the-microscope/) (2020; La Liga yeniden başlama dönemi karşılaştırması)
4. [CheckBestOdds — Turkey historical odds 2020/2021](https://checkbestodds.com/football-odds/archive-turkey/2020-2021) (11–12 Eylül 2020 maç örnekleri; sayfa “son en yüksek oranları” listeliyor)
5. [Ötkan & Halıcı (2025), “Odds and betting diversity of legal and illegal bookmakers in Türkiye: A comparative analysis”](https://dergipark.org.tr/en/download/article-file/4827828) (464 maç; 18 Ağustos–18 Eylül 2024)
