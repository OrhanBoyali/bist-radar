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
    env = dict(os.environ, EVDS_API_KEY="test", PYTHONPATH=MOCK)
    subprocess.run([sys.executable, "bist_radar.py"], cwd=tmp, env=env, capture_output=True, timeout=300)
    with open(os.path.join(tmp, "output", "radar.json"), encoding="utf-8") as f:
        return json.load(f)

def main():
    d = calistir(); T = d["tetikler"]; k = T.get("k3_donus_kapisi", {}); fon = d.get("fonlar", {})
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
