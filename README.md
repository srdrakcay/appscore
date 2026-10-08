# 📊 AppScope — Yerel iOS ASO Analiz Paneli

**AppScope**, iOS uygulamaları için **App Store Optimization (ASO)** analizini kendi bilgisayarında, kurulum ve API anahtarı gerektirmeden yapmanı sağlayan yerel bir web panelidir.

Bir **App ID** girersin; panel ülke bazlı rating'leri, otomatik bulunan keyword'lerin sıralamalarını, yorumları, metadata kalitesini ve rakipleri senin için çıkarır. Veriler tamamen yerelde (SQLite) saklanır.

---

## ✨ Özellikler

| Sekme | Ne yapar? |
|---|---|
| **Genel Bakış** | Seçili ülkelerde rating ortalaması, rating sayısı, mevcut sürüm rating'i, kategori, sürüm, fiyat, boyut, minimum iOS, dil sayısı, screenshot'lar, release notes ve rating geçmişi grafiği. |
| **Keyword Sıralama** | App ID'den **keyword'leri otomatik üretir** ve her ülkede ilk 200 sonuç içindeki sıranı bulur. Takip listesine ekleme seçeneği vardır. |
| **Takip & Geçmiş** | Takip edilen keyword'lerin sıra değişimi (▲▼), zaman grafiği, CSV dışa aktarma. |
| **Yorumlar** | Seçili ülkeden son yorumlar (yaklaşık 150), yıldız dağılımı, sık geçen kelimeler. |
| **Metadata Skoru** | Başlık/açıklama uzunluğu, screenshot, dil, rating gibi 10 kontrolle ASO skoru ve kelime yoğunluğu analizi. |
| **Rakip & Öneri** | Bir keyword için ilk 10 app ve rakip metinlerinden keyword fikirleri. |

Ek olarak:
- **20 ülke** desteği (ABD, Türkiye, Almanya, Japonya, Brezilya vb.)
- **Günlük otomatik kontrol:** Sunucu açıkken, takip edilen keyword'ler ve rating'ler 24 saatte bir kaydedilir.
- **Çoklu app:** Birden fazla app ekleyip aralarında geçiş yapabilirsin.

---

## 🚀 Kurulum ve Çalıştırma

**Gereksinim:** Python 3.9 veya üzeri. Başka paket kurmak gerekmez, yalnızca standart kütüphane kullanılır.

```bash
git clone <repo-url>
cd <repo-klasoru>
python3 server.py
```

Ardından tarayıcıdan **http://localhost:8765** adresini aç.

> İnternet bağlantısı gerekir, çünkü veriler Apple'ın herkese açık API'lerinden çekilir. Sunucu yalnızca `127.0.0.1` üzerinde dinler, dışarıya açılmaz.

---

## 🧭 Kullanım

1. **App ekle:** Sol üstteki alana App ID'yi (örn. `284882215`) veya App Store URL'sini yapıştır ve **Ekle**'ye bas.
   - App Store URL'sinde ID, `id` ile başlayan sayıdır: `apps.apple.com/us/app/facebook/id284882215`.
2. **Genel Bakış:** Ülkeleri seçip **Analiz Et**'e bas. Her analiz rating geçmişine bir kayıt ekler.
3. **Keyword Sıralama:** Ülkeleri seç, keyword sayısını belirle ve **🔍 Keyword'leri otomatik bul & sırala**'ya bas. Sonuçlar sıraya göre, canlı olarak tabloya eklenir.
4. **Takip & Geçmiş:** Takip edilen keyword'leri, sıra değişimlerini ve zaman grafiğini gör. Satıra tıklayarak grafiği aç, **CSV indir** ile dışa aktar.
5. **Yorumlar / Metadata / Rakip:** İlgili sekmeden ülke seçip analizi çalıştır.

### Keyword'ler nasıl otomatik bulunuyor?
App'in **o ülkedeki lokalize** metadata'sı kullanılır:
- Başlıktaki kelimeler ve ikili ifadeler (en yüksek ağırlık)
- Açıklamada en az 2 kez geçen kelimeler ve ifadeler
- Birincil kategori adı

Linkler ve e-postalar elenir, tekrar eden varyasyonlar azaltılır. İstersen "Ek keyword" alanından elle keyword da ekleyebilirsin.

### Sıralama nasıl hesaplanıyor?
Her keyword için iTunes Search API ile ilk **200** sonuç çekilir ve app'in o listedeki konumu bulunur. `200+` ilk 200'de olmadığı anlamına gelir.

---

## 🏗️ Mimari

```
.
├── server.py          # Backend: HTTP sunucu, iTunes API istemcisi, SQLite, zamanlayıcı
├── static/
│   └── index.html     # Frontend: tek dosya (HTML + CSS + JS), bağımlılık yok
├── aso.db             # SQLite veritabanı (otomatik oluşur, git'e eklenmez)
└── README.md
```

- **Backend:** Python `http.server` (ThreadingHTTPServer) + `sqlite3` + `urllib`.
- **Frontend:** Vanilla JavaScript, grafikler saf SVG.
- **Veritabanı tabloları:** `apps`, `keywords` (takip listesi), `rankings` (sıra geçmişi), `ratings` (rating geçmişi), `meta`.

### Veri kaynakları
- iTunes **Lookup API:** `itunes.apple.com/lookup`
- iTunes **Search API:** `itunes.apple.com/search`
- App Store **RSS yorum feed'i:** `itunes.apple.com/{ülke}/rss/customerreviews/...`

### API uç noktaları

| Uç nokta | Açıklama |
|---|---|
| `GET /api/apps` | Kayıtlı app'ler |
| `GET /api/app/save?id=` | App ekle |
| `GET /api/app/delete?id=` | App ve tüm geçmişini sil |
| `GET /api/overview?id=&countries=us,tr` | Ülke bazlı genel bilgi ve rating |
| `GET /api/auto-keywords?id=&country=&limit=` | Otomatik keyword üret |
| `GET /api/rank?id=&keywords=a,b&countries=us&save=1` | Keyword sıralaması |
| `GET /api/tracked?id=` | Takip edilen keyword'ler ve geçmişi |
| `GET /api/untrack?id=&keyword=&country=` | Takipten çıkar |
| `GET /api/reviews?id=&country=` | Yorumlar ve analiz |
| `GET /api/metadata?id=&country=` | Metadata skoru ve kelime analizi |
| `GET /api/suggest?keyword=&country=` | Rakip metinlerinden keyword önerisi |
| `GET /api/ratings-history?id=` | Rating geçmişi |
| `GET /api/run-daily` | Tüm takipleri şimdi kontrol et |
| `GET /api/export.csv?id=` | Sıralama geçmişini CSV indir |

### Ayarlar
`server.py` başındaki sabitler:
- `PORT` — varsayılan `8765`
- `DAILY_SECONDS` — otomatik kontrol aralığı (varsayılan 24 saat)
- `COUNTRIES` — desteklenen ülkeler (yeni ülke eklemek için buraya ekle)

---

## ⚠️ Sınırlamalar

- Apple'ın herkese açık API'leri **indirme sayısı, gelir ve keyword arama hacmi (popularity)** vermez. Bunlar için App Store Connect API (yalnızca kendi app'lerin) veya ücretli servisler (Sensor Tower, AppTweak vb.) gerekir.
- **Subtitle** ve Apple'ın gizli **keyword alanı** herkese açık API'de yoktur.
- Sıralamalar iTunes Search API'ye göredir. Gerçek App Store aramasına çok yakındır ama birebir aynı olmayabilir; kişiselleştirme ve cihaz farkları sonucu değiştirebilir.
- Apple istek sınırı uygular (yaklaşık dakikada 20 istek). Bu yüzden çok sayıda keyword × ülke taraması zaman alır.
- Otomatik günlük kontrol yalnızca **sunucu çalışırken** işler. Sürekli çalışması için macOS'ta `launchd` kullanılabilir.
- Keyword'ler app'in kendi metninden türetildiği için yeni keyword fırsatı keşfetmez. Bunun için **Rakip & Öneri** sekmesini kullan.

---

## 🗺️ Yol Haritası (fikirler)
- Rakip app'leri takip listesine ekleme
- Rakip keyword'lerini otomatik aday listesine katma
- Sıralama düşünce bildirim (macOS / e-posta)
- Ülke bazlı lokalizasyon eksiği tespiti
- App Store Connect API ile indirme ve gelir verisi

---

## 📄 Lisans
MIT
