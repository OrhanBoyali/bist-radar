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

EVREN = {}
def calistir_klasor(tmp, ek_env=None):
    """Aynı klasörde tekrar çalıştır (önbellek/çökme testleri)."""
    env = dict(os.environ, EVDS_API_KEY="test", FONOLOJI_KEY="test", PYTHONPATH=MOCK, **(ek_env or {}))
    subprocess.run([sys.executable, "bist_radar.py"], cwd=tmp, env=env, capture_output=True, timeout=300)
    with open(os.path.join(tmp, "output", "radar.json"), encoding="utf-8") as f:
        return json.load(f)

def calistir(tohum=None):
    tmp = tempfile.mkdtemp()
    EVREN["son"] = tmp
    if tohum:                                  # önceden birikmiş dosyalarla başlatma (kalıcılık testi)
        os.makedirs(os.path.join(tmp, "output"), exist_ok=True)
        for ad, icerik in tohum.items():
            json.dump(icerik, open(os.path.join(tmp, "output", ad), "w", encoding="utf-8"))
    else:
        EVREN["klasor"] = tmp
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
    # 5 Eki: enflasyon günü kuralı birim testi (4 durum)
    _tk = ("import bist_radar as br\nfrom datetime import datetime as D\n"
           "print(br.tufe_yenile_gerekli('2026-08-01', D(2026,10,5,11,0)), br.tufe_yenile_gerekli('2026-09-01', D(2026,10,5,11,0)),"
           " br.tufe_yenile_gerekli('2026-08-01', D(2026,10,5,9,0)), br.tufe_yenile_gerekli('2026-08-01', D(2026,10,15,11,0)))")
    tufe_k = subprocess.run([sys.executable, "-c", _tk], env=dict(os.environ, PYTHONPATH=MOCK + os.pathsep + KOK),
                            capture_output=True, text=True, timeout=60).stdout.split()
    # 3 Eki: gizli anahtar maskeleme birim testi
    _gz = subprocess.run([sys.executable, "-c", "import bist_radar as br; print(br._gizle('istek hatasi: anahtar=gizli12345xyz'))"],
                         env=dict(os.environ, PYTHONPATH=MOCK + os.pathsep + KOK, FONOLOJI_KEY="gizli12345xyz"),
                         capture_output=True, text=True, timeout=60).stdout.strip()
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    class _d:   # 3 Eki: testler de Türkiye saatiyle çalışır (betikle aynı gün sınırı)
        @staticmethod
        def today(): return _dt.now(_tz(_td(hours=3))).date()
    _gecmis = [(_d.today() - _td(days=i)).strftime("%Y-%m-%d") for i in range(40, 5, -1) if (_d.today() - _td(days=i)).weekday() < 5]
    d_olgun = calistir({"aday_izleme.json": {"YLB": {"ZPX": {"ilk": _gecmis[0], "gunler": _gecmis}}}})
    olgun_ylb = [a["kod"] for a in d_olgun["tetikler"].get("rakip_olgun_adaylar", {}).get("YLB", [])]
    import pandas as _pd
    _bugun_tr = _pd.Timestamp(_d.today())
    _isg = [(_bugun_tr - _pd.offsets.BDay(i)).strftime("%Y-%m-%d") for i in range(12, 0, -1)]
    _eski = (_d.today() - _td(days=35)).strftime("%Y-%m-%d")
    d_sinif = calistir({"sinif_izleme.json": {"Kısa vadeli borçlanma": {"gunler": _isg},
                                              "Enflasyona endeksli": {"gunler": _isg[:5]}},
                        "fon_kunye.json": {**{f"KB{i}": {"t": _eski, "buyukluk": 1e9, "g": [[_eski, 1e9]]} for i in range(3)},
                                           # 3 Eki: bugün çekilmiş ama portföyü olmayan (eski kod) künye → yenilenmeli
                                           "YLB": {"t": _d.today().strftime("%Y-%m-%d"), "buyukluk": 1e11, "kunye_kaynak": "fonoloji"}}})
    kunye_sonra = json.load(open(os.path.join(EVREN["son"], "output", "fon_kunye.json"), encoding="utf-8"))
    akis_kamu = (((d_sinif.get("rakip_tarama") or {}).get("varlik_siniflari") or {}).get("siniflar") or {}).get(
        "Kamu borçlanma (devlet tahvili)", {}).get("akis_30g_pct")
    sinif_olgun = d_sinif["tetikler"].get("varlik_sinifi_olgun", [])
    import csv as _csv
    d = calistir(); T = d["tetikler"]
    _ana = EVREN["son"]
    k = T.get("k3_donus_kapisi", {}); fon = d.get("fonlar_borsapy") or d.get("fonlar", {})   # borsapy filtre testleri ham borsapy verisine bakar
    d_cokme = calistir_klasor(_ana, {"RADAR_TEST_COKME": "1"})   # aynı klasörde kontrollü çökme
    rt = d.get("rakip_tarama") or {}; pp = rt.get("para_piyasasi") or {}
    vs = rt.get("varlik_siniflari") or {}
    ta = rt.get("tahvil_adaylari") or {}
    _p = os.path.join(EVREN["klasor"], "output", "fon_evreni.csv")
    _rows = list(_csv.DictReader(open(_p, encoding="utf-8"))) if os.path.exists(_p) else []
    ev_satir = len(_rows); ev_bayrak = {r["kod"]: r for r in _rows}
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
        # --- 5 Eki tahvil paketi ---
        ({"KB0", "KB1", "KB2", "PB1"} <= {x["kod"] for x in ta.get("adaylar", [])}, "Tahvil: devlet tahvili ağırlıklı fonlar aday listesinde"),
        (not any(x["kod"].startswith("OS") for x in ta.get("adaylar", [])), "Tahvil: şirket borcu ağırlıklı fonlar aday değil"),
        (all((x.get("kamu_payi") or 0) >= 50 for x in ta.get("adaylar", [])), "Tahvil: her adayın portföyünün en az yarısı devlet kâğıdı"),
        (isinstance(ta.get("portfoyu_bilinmeyen_borclanma_fonu"), int), "Tahvil: portföyü bilinmeyen fon sayısı raporlanır"),
        (tufe_k == ["True", "False", "False", "False"],             "Enflasyon günü: sadece gerektiğinde (10:00 sonrası, ayın ilk günleri, veri eskiyse) tekrar çekilir"),
        # --- 3 Eki hypercare kod incelemesi ---
        ("gizli12345xyz" not in _gz and "***" in _gz,                "Güvenlik: hata mesajlarında gizli anahtar maskelenir"),
        (bool(d_cokme.get("fonlar")) and "ana_akis" in d_cokme["saglik"]["hatali_moduller"],
                                                                    "Dayanıklılık: çökmede önceki veriler korunur, sağlık SORUN VAR olur"),
        ("yahoo_nasdaq_bayat" in d["saglik"]["hatali_moduller"],    "Bayat veri: birkaç gün geride kalan Yahoo verisi uyarı verir"),
        ((T.get("brent_capraz") or {}).get("fark_pct") is not None and "brent_kaynak_celiskisi" not in d["saglik"]["hatali_moduller"],
                                                                    "Petrol: iki kaynak karşılaştırılır, yakınsa yanlış alarm yok"),
        ((d.get("fonoloji_cagri") or {}).get("cagri", 0) > 0,       "Kota: Fonoloji çağrı sayısı raporlanır"),
        ("kamu_payi" in (kunye_sonra.get("YLB") or {}),             "Künye: portföyü eksik künye süresini beklemeden yenilenir"),
        ("ZBJ" in fon and "ZBJ" in T.get("reel_getiri", {}),        "Portföydeki her fon takipte (30 Eyl: ZBJ eksik kalmıştı)"),
        ((pp.get("bizim") or {}).get("ZBJ", {}).get("gruptaki_sira_1y") is not None, "ZBJ rakip taramasında bizim fon olarak sıralanıyor"),
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
        # --- Rakip taraması v2: tam sıralama + künye + sınırsız aday (29 Eyl) ---
        (len(pp.get("siralama", [])) == pp.get("temiz_havuz") and pp.get("temiz_havuz", 0) > 0 and all(pp["siralama"][i]["1y"] >= pp["siralama"][i+1]["1y"]
            for i in range(len(pp["siralama"]) - 1) if pp["siralama"][i+1]["1y"] is not None),
                                                                    "Rakip v2: grubun tamamı 1 yıllık getiriye göre sıralı yazılır"),
        (len(adaylar("para_piyasasi", "YLB")) > 3,                  "Rakip v2: 3'ten fazla aday listelenebilir"),
        ("TKP" in pp.get("tefas_kapali", []),                       "Rakip v2: künyede TEFAS'ta kapalı görünen fon işaretlenir"),
        ({"ZPX", "BY1"} <= set(T.get("rakip_gecis_adaylari", {}).get("YLB", [])), "Rakip v2: büyük adaylar özet listede"),
        (not {"KCK", "TKP"} & set(T.get("rakip_gecis_adaylari", {}).get("YLB", [])), "Rakip v2: küçük ve kapalı fon büyük adaylara girmez"),
        (all(r.get("buyukluk") for r in pp.get("siralama", []) if r.get("bizim")), "Rakip v2: bizim fonların künyesi dolu"),
        # --- Fon evreni (29 Eyl): bütün fonlar tek tabloda + kategori özetleri ---
        # --- Geçiş karar çerçevesi (30 Eyl): kalıcılık + başabaş + risk ---
        (T.get("rakip_olgun_adaylar") == {},                        "Karar: ilk gün görülen aday 'olgun' sayılmaz (kalıcılık şartı)"),
        ("ZPX" in olgun_ylb,                                        "Karar: 4+ hafta, 20+ iş günü aday kalan fon olgunlaşır"),
        ("BY1" not in olgun_ylb,                                    "Karar: yeni çıkan aday, eskisi olgunlaşsa da beklemede kalır"),
        (all(isinstance(a.get("basabas_gun"), (int, float)) for a in pp["bizim"]["YLB"]["buyuk_adaylar"]),
                                                                    "Karar: para piyasası adayları için başabaş süresi hesaplanır"),
        (all(a.get("piyasa_disi_gun", 0) >= 2 for a in (rt.get("bist30_endeks") or {}).get("bizim", {}).get("TIE", {}).get("gecis_adaylari", [])),
                                                                    "Karar: hisse fonu geçişinde piyasa dışı gün (T+2) raporlanır"),
        # --- Varlık sınıfı panosu (1 Eki): paranın gidebileceği her yer ---
        ({"Para piyasası", "Kamu borçlanma (devlet tahvili)", "Özel sektör borçlanma", "Borçlanma (karma)",
          "Kısa vadeli borçlanma", "Enflasyona endeksli", "Eurobond / döviz",
          "Altın / kıymetli maden", "Kira sertifikası / katılım", "BIST endeks hisse"} <= set(vs.get("siniflar", {})),
                                                                    "Pano: bütün varlık sınıfları ayrı ayrı ölçülür"),
        ({"Gram altın (fiziki)", "Dolar (USD/TRY)", "TL mevduat (1 ay, brüt)"} <= set(vs.get("fon_disi", {})),
                                                                    "Pano: mevduat, dolar ve gram altın da karşılaştırılır"),
        ("Kısa vadeli borçlanma" in T.get("varlik_sinifi_ppf_ustu", {}), "Pano: para piyasasını 1a ve 3a'da geçen sınıf yakalanır"),
        ("Borçlanma (karma)" not in T.get("varlik_sinifi_ppf_ustu", {}), "Pano: geride kalan sınıf yanlış uyarı üretmez"),
        # --- 2 Eki paketi: erişim, gerçek portföyle sınıflama, sınıf akışı, tahvil zamanlaması ---
        ("OZF" not in str(pp.get("siralama")),                      "Paket: 'ÖZEL FON' rakip havuzuna girmez (erişilemez)"),
        (ev_bayrak.get("OZF", {}).get("ozel_fon") == "True",        "Paket: 'ÖZEL FON' evren tablosunda işaretli"),
        (ev_bayrak.get("KNJ", {}).get("sinif") == "Hisse (aktif)",  "Paket: adı 'katılım' olan ama %90 hisse tutan fon hisse sayılır (KNJ)"),
        (ev_bayrak.get("PB1", {}).get("sinif") == "Kamu borçlanma (devlet tahvili)", "Paket: adı sade, portföyü devlet tahvili olan fon kamu sayılır"),
        (ev_bayrak.get("OS0", {}).get("sinif") == "Özel sektör borçlanma", "Paket: özel sektör borçlanma ayrı sınıf"),
        (ev_bayrak.get("KB0", {}).get("kamu_payi") not in ("", None), "Paket: fon portföy dağılımı evren tablosunda"),
        (akis_kamu is not None and abs(akis_kamu - (-25.0)) < 0.5, "Paket: sınıf bazında 30 günlük para akışı hesaplanır"),
        (abs((T.get("tahvil_zamanlama") or {}).get("iki_yil_eksi_politika", 0) - 2.7) < 0.01, "Paket: 2Y verim − politika faizi (piyasanın indirim fiyatlaması)"),
        (abs((T.get("tahvil_zamanlama") or {}).get("egri_egimi_10y_2y", 0) - (-4.6)) < 0.01, "Paket: verim eğrisi eğimi"),
        ((T.get("tahvil_zamanlama") or {}).get("beklenen_indirim_puan") == 7.0, "Paket: anket faiz beklentisinden beklenen indirim"),
        (T.get("varlik_sinifi_olgun") == [],                         "Pano: ilk gün görülen üstünlük 'olgun' sayılmaz (kalıcılık)"),
        ("Kısa vadeli borçlanma" in sinif_olgun,                    "Pano: 2 hafta kesintisiz üstün kalan sınıf olgunlaşır"),
        ("Enflasyona endeksli" not in sinif_olgun,                  "Pano: bugün üstün olmayan sınıf, geçmişi olsa da olgun sayılmaz"),
        ("IDH" not in str((vs.get("siniflar") or {}).get("BIST endeks hisse", {})), "Pano: 'BIST 100 dışı' fon endeks sınıfına girmez"),
        (ev_satir == rt.get("evren"),                               "Evren: bütün fonlar tabloya yazılır (satır sayısı = evren)"),
        (os.path.exists(os.path.join(EVREN["klasor"], "output", "fon_kunye.json")), "Evren: künye önbelleği dosyası oluşur"),
        ((rt.get("kunye_durumu") or {}).get("kapsam", 0) > 0,       "Evren: künye kapsamı raporlanır"),
        ({"Para Piyasası Fonu", "Borçlanma Araçları Fonu"} <= set((rt.get("evren_ozeti") or {}).get("kategoriler", {})),
                                                                    "Evren: her kategori için özet çıkar"),
        (ev_bayrak.get("TP2", {}).get("tasfiye_kurucu") == "True",  "Evren: tasfiye kurucusu tabloda işaretli"),
        (ev_bayrak.get("YLB", {}).get("tasfiye_kurucu") == "False", "Evren: temiz fon YANLIŞLIKLA işaretlenmez (29 Eyl hata)"),
        ((rt.get("evren_ozeti") or {}).get("temiz_fon", 0) > 0,     "Evren: temiz fon sayısı sıfır değil"),
        (ev_bayrak.get("SRB", {}).get("nitelikli_serbest") == "True", "Evren: nitelikli yatırımcı fonu tabloda işaretli"),
        (ev_bayrak.get("KCK", {}).get("kucuk") == "True",           "Evren: küçük fon tabloda işaretli"),
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
        # --- Göreli kitlesel çıkış (1 Eki): sektör geneli değil, fona özgü çıkış alarm verir ---
        (not T.get("fon_kitlesel_cikis_alarm", {}).get("YLB"),     "Göreli akış: sektörle aynı oranda küçülen fon alarm vermez"),
        ("fona özgü" in str(T.get("fon_kitlesel_cikis_alarm", {}).get("DLY", {}).get("tur", "")),
                                                                    "Göreli akış: sektörden belirgin fazla para kaybeden fon alarm verir"),
        ((T.get("fon_akis_sektor") or {}).get("para_piyasasi", {}).get("referans_fon_sayisi", 0) > 0,
                                                                    "Göreli akış: sektör referansı en büyük rakiplerden hesaplanır"),
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
