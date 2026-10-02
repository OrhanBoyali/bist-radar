#!/usr/bin/env python3
"""
BIST RADAR — GÜN AKIŞI TESTİ (29 Eyl)
Betiği AYNI klasörde, günün gerçek sırasıyla çalıştırır (önbellek ve arşiv bir önceki
çalışmadan devralınır, tıpkı depoda olduğu gibi). Her saatin kendine özgü yolunu sınar:
  08:17 sabah (fonlar, rakip, resmi veri taze) → 12:17 öğlen (önbellek yolu)
  → 18:17 ilk akşam (arşiv yazılır) → 18:52 kapanış (arşiv ÜZERİNE yazılır, çift satır yok)
  → Cumartesi (arşiv yazılmaz, çökmeden çalışır)
KURAL: Betikte saate bağlı yeni bir iş eklenirse buraya o saatin kontrolü eklenir.
"""
import csv, json, os, shutil, subprocess, sys, tempfile
from datetime import date, timedelta

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOCK = os.path.join(KOK, "tests", "mock")

def son_is_gunu_bugun():
    from datetime import datetime, timezone
    d = datetime.now(timezone(timedelta(hours=3))).date()   # 3 Eki: Türkiye saati (betikle aynı gün sınırı)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d

def calistir(klasor, zaman):
    env = dict(os.environ, EVDS_API_KEY="test", FONOLOJI_KEY="test", PYTHONPATH=MOCK, RADAR_TEST_NOW=zaman)
    p = subprocess.run([sys.executable, "bist_radar.py"], cwd=klasor, env=env, capture_output=True, text=True, timeout=300)
    with open(os.path.join(klasor, "output", "radar.json"), encoding="utf-8") as f:
        return json.load(f), p

def main():
    tmp = tempfile.mkdtemp()
    shutil.copy(os.path.join(KOK, "bist_radar.py"), tmp)
    g = son_is_gunu_bugun().strftime("%Y-%m-%d")
    cmt = (son_is_gunu_bugun() + timedelta(days=(5 - son_is_gunu_bugun().weekday()) % 7 or 7)).strftime("%Y-%m-%d")
    sonuc = []
    def kontrol(k, a): sonuc.append((bool(k), a))

    d, p = calistir(tmp, f"{g} 08:17")
    kontrol("ana_akis" not in d["saglik"]["hatali_moduller"],       "08:17 — betik çökmeden tamamlandı")
    kontrol("önbellek" not in str(d.get("fonlar_zamani")),          "08:17 — fonlar taze çekildi")
    kontrol(bool(d.get("rakip_tarama")) and "hata" not in str(d.get("rakip_tarama"))[:40], "08:17 — rakip taraması çalıştı")
    kontrol(bool(d.get("evds_resmi")),                               "08:17 — resmi (EVDS) veriler çekildi")
    kontrol(d.get("arsiv") == "saat değil",                          "08:17 — arşive yazılmadı (doğru)")
    kontrol(((d.get("rakip_tarama") or {}).get("kunye_durumu") or {}).get("yenilenen", 0) > 0, "08:17 — fon künyeleri ilk kez çekildi")

    d, p = calistir(tmp, f"{g} 09:17")
    kontrol(d.get("agir_calisma") is False,                         "09:17 — ağır işler TEKRAR çalışmadı (sabah slotu 08:17'de doldu)")
    kontrol("önbellek" in str(d.get("fonlar_zamani")),              "09:17 — fonlar önbellekten (kota korunuyor)")

    d, p = calistir(tmp, f"{g} 12:17")
    kontrol("ana_akis" not in d["saglik"]["hatali_moduller"],       "12:17 — betik çökmeden tamamlandı (önbellek yolu)")
    kontrol("önbellek" in str(d.get("fonlar_zamani")),              "12:17 — fonlar önbellekten geldi")
    kontrol(str(d.get("fonlar_zamani")).count("önbellek") == 1,     "12:17 — önbellek etiketi tekrarlanmıyor")
    kontrol(bool(d.get("rakip_tarama")),                             "12:17 — rakip taraması önbellekten korunuyor")
    kontrol(bool(d.get("fonlar")) and all(v for v in d["fonlar"].values()), "12:17 — beş fonun verisi eksiksiz")

    d, p = calistir(tmp, f"{g} 18:17")
    kontrol("ana_akis" not in d["saglik"]["hatali_moduller"],       "18:17 — betik çökmeden tamamlandı")
    kontrol("gün kayıtlı" in str(d.get("arsiv")),                   "18:17 — arşive yazıldı")

    kontrol(d.get("agir_calisma") is False,                         "18:17 — hafif çalışma (kesin kapanış fiyatları 18:40 sonrası)")
    d, p = calistir(tmp, f"{g} 18:52")
    kontrol(d.get("agir_calisma") is True,                          "18:52 — akşamın tek ağır çalışması")
    kontrol("ana_akis" not in d["saglik"]["hatali_moduller"],       "18:52 — KAPANIŞ çalışması çökmeden tamamlandı")
    kontrol("önbellek" not in str(d.get("fonlar_zamani")),          "18:52 — fonlar taze (kapanış fiyatı)")
    kontrol(d["bist100"].get("son_bar_kismi_mi") is False,          "18:52 — son bar kesinleşmiş kapanış sayılıyor")
    kontrol("k3_donus_kapisi" in d["tetikler"],                      "18:52 — üçüncü kademe kapıları hesaplandı")
    kontrol("tez_cizgisi_haftalik_kirildi" in d["tetikler"],         "18:52 — haftalık tez çizgisi kontrolü var")
    kontrol(d["tetikler"].get("reel_getiri"),                         "18:52 — net reel getiri hesaplandı")
    kontrol(((d.get("rakip_tarama") or {}).get("kunye_durumu") or {}).get("yenilenen", 1) == 0, "18:52 — künyeler önbellekten (aynı gün tekrar çekilmedi, kota korunuyor)")
    _iz = ((d.get("rakip_tarama") or {}).get("aday_izleme") or {}).get("YLB", {})
    kontrol(bool(_iz) and all(v["aday_gun_sayisi"] == 1 for v in _iz.values()), "18:52 — aynı gün iki tarama adayı iki kez saymaz (kalıcılık doğru ölçülür)")
    with open(os.path.join(tmp, "output", "gunluk_arsiv.csv"), encoding="utf-8") as f:
        satirlar = [r for r in csv.DictReader(f) if r["tarih"] == g]
    kontrol(len(satirlar) == 1,                                      "18:52 — arşivde bugün için TEK satır (18:17'nin üzerine yazıldı)")
    kontrol(satirlar and satirlar[0].get("fiyat_YLB") not in ("", None), "18:52 — arşiv satırında fon fiyatları dolu")
    kontrol(satirlar and satirlar[0].get("reel_net_YLB") not in ("", None), "18:52 — arşiv satırında net reel getiri dolu")
    kontrol(satirlar and satirlar[0].get("sinif_ppf_1a") not in ("", None) and satirlar[0].get("sinif_kamu_borc_3a") not in ("", None)
            and satirlar[0].get("sinif_iki_yil_eksi_politika") not in ("", None),
            "18:52 — arşivde varlık sınıflarının 1a/3a ortancaları (gidişat için)")

    d, p = calistir(tmp, f"{cmt} 11:00")
    kontrol("ana_akis" not in d["saglik"]["hatali_moduller"],       "Cumartesi — betik çökmeden tamamlandı")
    kontrol(d.get("arsiv") == "saat değil",                          "Cumartesi — arşive yazılmadı (doğru)")

    gecen = 0
    for i, (ok, a) in enumerate(sonuc, 1):
        print(f"{'✓ GEÇTİ' if ok else '✗ KALDI'} | {i:>2} — {a}")
        gecen += ok
    print(f"\n{gecen}/{len(sonuc)} gün akışı testi geçti")
    if gecen != len(sonuc):
        print("\n--- son çalışmanın hata çıktısı ---\n", p.stderr[-1500:])
    sys.exit(0 if gecen == len(sonuc) else 1)

if __name__ == "__main__":
    main()
