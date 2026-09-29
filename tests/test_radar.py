#!/usr/bin/env python3
"""
BIST RADAR — TEST DÜZENEĞİ
Gerçek kaynaklar yerine tests/mock/ içindeki sahte borsapy ve yfinance ile betiği baştan sona çalıştırır,
bilinen hata senaryolarının doğru ele alındığını kontrol eder.

KURAL: Betiğe her yeni özellik eklendiğinde buraya en az bir test eklenir.
       Canlıya almadan önce: python tests/test_radar.py  → hepsi GEÇTİ olmalı.
"""
import json, os, shutil, subprocess, sys, tempfile

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOCK = os.path.join(KOK, "tests", "mock")

def calistir():
    tmp = tempfile.mkdtemp()
    shutil.copy(os.path.join(KOK, "bist_radar.py"), tmp)
    env = dict(os.environ, EVDS_API_KEY="test", FONOLOJI_KEY="test", PYTHONPATH=MOCK)
    subprocess.run([sys.executable, "bist_radar.py"], cwd=tmp, env=env, capture_output=True, timeout=300)
    with open(os.path.join(tmp, "output", "radar.json"), encoding="utf-8") as f:
        return json.load(f)

def birim_tarih_hizalama():
    """28 Eyl yanlış alarmının birim testi: fon fiyat tarihi ↔ endeksin bir önceki işlem günü."""
    kod = ("import bist_radar as br\n"
           "k=[{'t':'2026-09-24','k':100.0},{'t':'2026-09-25','k':100.16},{'t':'2026-09-28','k':98.11}]\n"
           "print(br.onceki_islem_gunu_getirisi(k,'2026-09-28'), br.onceki_islem_gunu_getirisi(k,'2026-09-29'))")
    env = dict(os.environ, PYTHONPATH=MOCK + os.pathsep + KOK)
    out = subprocess.run([sys.executable, "-c", kod], env=env, capture_output=True, text=True, timeout=60).stdout.split()
    return [float(x) for x in out] if len(out) == 2 else [None, None]

def main():
    hz = birim_tarih_hizalama()
    d = calistir(); T = d["tetikler"]; k = T.get("k3_donus_kapisi", {}); fon = d.get("fonlar_borsapy") or d.get("fonlar", {})   # borsapy filtre testleri ham borsapy verisine bakar
    rt = d.get("rakip_tarama") or {}; pp = rt.get("para_piyasasi") or {}
    def adaylar(grup, kod):
        return [a["kod"] for a in ((rt.get(grup) or {}).get("bizim", {}).get(kod, {}).get("gecis_adaylari") or [])]
    testler = [
        # (koşul, açıklama, eklendiği tarih/sebep)
        (fon["DLY"]["fiyat"] > 0,                                   "Sıfır fon fiyatı elenir (24 Eyl TEFAS DLY=0)"),
        (T["reel_getiri"]["DLY"]["durum"] != "ACIL",                "Sıfır fiyat yanlış ACİL alarmı üretmez"),
        (fon["YLB"]["fiyat"] < 6,                                   "Tek günde %15+ sıçrayan fiyat elenir"),
        ("fon_YLB_veri" in d["saglik"]["hatali_moduller"],          "Şüpheli fiyat sağlık raporuna düşer"),
        (k.get("yabanci_net_alici") is True,                        "Dönüş kapısı yabancıyı EVDS'den sonra okur (24 Eyl sıra hatası)"),
        (k.get("ma200_ustu_2gun") and k.get("genislik_katilim"),    "Dönüş kapısı MA200 ve genişlik şartlarını algılar"),
        (k.get("TETIK") is True,                                    "Üç şart birlikte → dönüş kapısı açılır"),
        (str(T.get("aofm_30g_yon", "")).startswith("GEVŞEME"),      "Fiili faiz 40→37 gevşemesi algılanır (günlük frekans)"),
        (str(T.get("tufe_kaynak", "")).startswith("TÜİK"),          "Resmi TÜFE (EVDS) kullanılır"),
        (T.get("dolar_makasi_puan") is not None,                    "Dolar makası hesaplanır"),
        (bool(d.get("fon_akis")) and "YLB" in d["fon_akis"],        "Fon büyüklük/yatırımcı kaydı tutulur"),
        (d["genislik"].get("hisse_sayisi", 0) >= 100,               "Tüm piyasa genişliği tek taramayla gelir"),
        (T.get("reel_getiri_yontem", "").startswith("NET"),         "Reel getiri NET (stopaj sonrası) hesaplanır"),
        ("TIE" not in T.get("reel_getiri", {}),                     "Reel getiri sadece cephane fonlarına uygulanır"),
        # --- Rakip fon taraması (28 Eyl) ---
        ("TP2" in pp.get("elenen_tasfiye", []),                     "Rakip: tasfiye kurucusunun fonu elenir (Tera dersi)"),
        ("SUS" in pp.get("supheli_yuksek", []),                     "Rakip: grubundan şüpheli yüksek getirili fon işaretlenir"),
        ("SUS" not in adaylar("para_piyasasi", "YLB"),              "Rakip: şüpheli fon aday gösterilmez"),
        ("SRB" not in str(pp),                                      "Rakip: nitelikli (serbest) fon gruba girmez"),
        ("ZPX" in adaylar("para_piyasasi", "YLB"),                  "Rakip: 1a+3a+1y'de geçen gerçek aday bulunur"),
        ("KCK" not in T.get("rakip_gecis_adaylari", {}).get("YLB", []), "Rakip: küçük fon özet aday listesine girmez"),
        ("GBX" in adaylar("bist30_endeks", "TIE"),                  "Rakip: BIST 30'da TIE'den iyi takip eden fon bulunur"),
        ("AKU" in adaylar("bist30_endeks", "TIE"),                  "Rakip: AKU, TIE'ye karşı aday çıkar (28 Eyl gözlemi)"),
        ("IDH" not in str(rt.get("bist100_endeks", {})),            "Rakip: 'BIST 100 dışı' fon endeks grubuna girmez (hata #1)"),
        ("ZSP" not in str(pp),                                      "Rakip: TEFAS'ta kapalı 'sepet hesap' fonu gruba girmez (29 Eyl ZA2)"),
        ("Y1O" in pp.get("supheli_yuksek", []),                     "Rakip: yıllık getirisi grubundan aşırı yüksek fon şüpheli sayılır"),
        ("Y1O" not in adaylar("para_piyasasi", "YLB"),              "Rakip: yıllık aykırı fon aday gösterilmez"),
        # --- Fon veri tutarlılığı (28 Eyl) ---
        ("fon_TIE_bayat" in d["saglik"]["hatali_moduller"],         "Tutarlılık: bayat fon fiyatı uyarı verir"),
        ("fon_AKU_takip_sapmasi" in d["saglik"]["hatali_moduller"], "Tutarlılık: endeks fonu endeksten koparsa uyarı verir"),
        ("fon_IJV_bayat" not in d["saglik"]["hatali_moduller"],     "Tutarlılık: güncel fiyat yanlış alarm üretmez"),
        # --- Tarih hizalama (28 Eyl yanlış alarmı) ---
        (hz[0] is not None and abs(hz[0] - 0.16) < 0.01,            "Hizalama: 28 Eyl tarihli fon fiyatı 25 Eyl endeks getirisiyle (%0,16) karşılaştırılır"),
        (hz[1] is not None and abs(hz[1] - (-2.05)) < 0.02,         "Hizalama: 29 Eyl tarihli fon fiyatı 28 Eyl düşüşüyle (%-2,05) karşılaştırılır"),
        # --- Fonoloji birincil kaynak + çapraz kontrol (28 Eyl) ---
        (d.get("fonlar_kaynak", {}).get("YLB") == "fonoloji",       "Fonoloji: anahtar varsa fonlar için birincil kaynak"),
        ("fon_IJV_kaynak_celiskisi" in d["saglik"]["hatali_moduller"], "Fonoloji: iki kaynak farklıysa çapraz uyarı düşer"),
        ("fon_YLB_kaynak_celiskisi" not in d["saglik"]["hatali_moduller"], "Fonoloji: kaynaklar uyumluysa uyarı yok"),
        (bool(T.get("fon_kitlesel_cikis_alarm", {}).get("YLB")),   "Fonoloji: 1 yıllık büyüklük geçmişiyle kitlesel çıkış alarmı çalışır"),
        (d["fonlar"]["YLB"].get("bilgi", {}).get("sell_valor") == 0, "Fonoloji: valör künyeden okunur"),
    ]
    gecen = 0
    for i, (kosul, aciklama) in enumerate(testler, 1):
        durum = "✓ GEÇTİ" if kosul else "✗ KALDI"
        gecen += bool(kosul)
        print(f"{durum} | {i:>2} — {aciklama}")
    print(f"\n{gecen}/{len(testler)} test geçti")
    sys.exit(0 if gecen == len(testler) else 1)

if __name__ == "__main__":
    main()
