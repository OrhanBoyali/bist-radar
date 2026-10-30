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

def _varsayilan_an():
    """17 Eki: testler hafta sonu/öğleden sonra çalıştırılınca ağır pencere açılmıyor ve bazı testler düşüyordu
    (saate bağımlılık, hata #17 benzeri). Varsayılan an: Türkiye saatiyle en son iş günü 09:17 (sabah ağır penceresi)."""
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    g = _dt.now(_tz(_td(hours=3))).date()
    tatil = _tam_tatiller()
    while g.weekday() >= 5 or g.strftime("%Y-%m-%d") in tatil:      # 30 Eki: resmi tatil de atlanır
        g -= _td(days=1)
    return f"{g:%Y-%m-%d} 09:17"

def _tam_tatiller():
    """30 Eki: betikteki tam gün tatil listesini (TATIL_VARSAYILAN) metinden okur — testler tatil gününe düşmesin."""
    import re
    kaynak = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bist_radar.py"), encoding="utf-8").read()
    return set(re.findall(r'"(\d{4}-\d{2}-\d{2})": "tam"', kaynak))
_AN = _varsayilan_an()

def calistir_klasor(tmp, ek_env=None):
    """Aynı klasörde tekrar çalıştır (önbellek/çökme testleri)."""
    env = dict(os.environ, EVDS_API_KEY="test", FONOLOJI_KEY="test", PYTHONPATH=MOCK, RADAR_TEST_HIZLI="1", RADAR_TEST_NOW=_AN); env.update(ek_env or {})
    subprocess.run([sys.executable, "bist_radar.py"], cwd=tmp, env=env, capture_output=True, timeout=300)
    with open(os.path.join(tmp, "output", "radar.json"), encoding="utf-8") as f:
        return json.load(f)

def calistir(tohum=None, ek_env=None, kok=None):
    tmp = tempfile.mkdtemp()
    EVREN["son"] = tmp
    for ad, icerik in (kok or {}).items():          # 6 Eki: ana klasöre dosya (ör. ayarlar.json)
        open(os.path.join(tmp, ad), "w", encoding="utf-8").write(icerik)
    if tohum:                                  # önceden birikmiş dosyalarla başlatma (kalıcılık testi)
        os.makedirs(os.path.join(tmp, "output"), exist_ok=True)
        for ad, icerik in tohum.items():
            json.dump(icerik, open(os.path.join(tmp, "output", ad), "w", encoding="utf-8"))
    else:
        EVREN["klasor"] = tmp
    shutil.copy(os.path.join(KOK, "bist_radar.py"), tmp)
    env = dict(os.environ, EVDS_API_KEY="test", FONOLOJI_KEY="test", PYTHONPATH=MOCK, RADAR_TEST_HIZLI="1", RADAR_TEST_NOW=_AN); env.update(ek_env or {})
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

def piyasa_takvimi_birim():
    """30 Eki: tatil/yarım gün, sonraki iş günü, TÜFE ve PPK tarihleri (gerçek takvimle sabit tarihlerde)."""
    kod = ("import json, bist_radar as br\n"
           "from datetime import date\n"
           "o=br.piyasa_takvimi()\n"
           "print(json.dumps({'yarin': o['sonraki_hafta_ici_gun']['durum'], 'tufe': o['sonraki_tufe'], 'ppk': o['sonraki_ppk'],"
           " 'onceki': str(br.onceki_is_gunu(date(2026,10,30))), 'sonraki': str(br.sonraki_is_gunu(date(2026,10,28))),"
           " 'tatil29': br.is_gunu(date(2026,10,29)), 'yarim28': br.is_gunu(date(2026,10,28)), 'tufe_ocak': str(br._tufe_gunu(2027,1)),"
           " 'not': br.HEALTH.get('piyasa_takvimi_yarin','')}, ensure_ascii=False))")
    env = dict(os.environ, PYTHONPATH=MOCK + os.pathsep + KOK, RADAR_TEST_NOW="2026-10-27 09:17")
    out = subprocess.run([sys.executable, "-c", kod], env=env, capture_output=True, text=True, timeout=60, cwd=tempfile.mkdtemp()).stdout
    try:
        return json.loads(out.strip().splitlines()[-1])
    except Exception:
        return {}

def haftalik_kapanis_birim():
    """24 Eki: pazartesi seans içinde (son bar kısmi) 'son bitmiş hafta' bir önceki cuma olmalı (eskiden 2 hafta önceki okunuyordu)."""
    kod = ("import pandas as pd, bist_radar as br\n"
           "idx=pd.bdate_range('2026-10-12','2026-10-26')\n"
           "c=[100.0]*5+[90.0]*5+[85.0]\n"
           "df=pd.DataFrame({'Open':c,'High':c,'Low':c,'Close':c,'Volume':[1e6]*len(c)},index=idx)\n"
           "o=br.summarize(df,'test')\n"
           "h=o['haftalik_kapanis']['son_biten_hafta']\n"
           "print(o['son_bar_kismi_mi'], h['k'], h['onceki_k'], h['hafta_sonu'])")
    env = dict(os.environ, PYTHONPATH=MOCK + os.pathsep + KOK, RADAR_TEST_NOW="2026-10-26 11:17")
    return subprocess.run([sys.executable, "-c", kod], env=env, capture_output=True, text=True, timeout=60, cwd=tempfile.mkdtemp()).stdout.split()

def sozlesme_kontrol():
    """9 Eki (hata #22): Sahte kütüphane gerçeğinden farklıysa testler geçer ama canlı kırılır.
    (1) Betiğin bp.<fonksiyon>(...) çağrılarında kullandığı anahtar kelimeler GERÇEK borsapy imzasında var mı?
    (2) Sahte evds_search'ün döndürdüğü sütunlar gerçek borsapy kaynağında üretiliyor mu?"""
    import ast, inspect, importlib.util
    try:
        import borsapy as gercek
    except Exception:
        return {"ok": True, "gercek": False, "sorun": []}
    sorun = []
    agac = ast.parse(open(os.path.join(KOK, "bist_radar.py"), encoding="utf-8").read())
    for n in ast.walk(agac):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id == "bp":
            ad = n.func.attr
            f = getattr(gercek, ad, None)
            if f is None:
                sorun.append(f"bp.{ad} gerçek borsapy'de yok"); continue
            try:
                imza = inspect.signature(f)
            except (TypeError, ValueError):
                continue
            serbest = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in imza.parameters.values())
            for kw in n.keywords:
                if kw.arg and not serbest and kw.arg not in imza.parameters:
                    sorun.append(f"bp.{ad}(…{kw.arg}=…) gerçek imzada yok")
    spec = importlib.util.spec_from_file_location("sahte_bp", os.path.join(MOCK, "borsapy.py"))
    sahte = importlib.util.module_from_spec(spec); spec.loader.exec_module(sahte)
    # 15 Eki: TradingView sağlayıcısı (tahvil faizi yedeği) — gerçek imza betiğin kullandığı parametreleri içeriyor mu
    try:
        from borsapy._providers.tradingview import get_tradingview_provider, TradingViewProvider
        _im = inspect.signature(TradingViewProvider.get_history)
        for _p in ("symbol", "period", "interval", "exchange"):
            if _p not in _im.parameters:
                sorun.append(f"TradingViewProvider.get_history gerçek imzasında '{_p}' yok")
    except Exception as e:
        sorun.append(f"TradingView sağlayıcısı içe aktarılamadı: {type(e).__name__}: {e}")
    # 15 Eki: İş Yatırım tarama ekranı (yabancı oranı toplu)
    try:
        _af = inspect.signature(gercek.Screener.add_filter)
        for _p in ("criteria", "min", "max"):
            if _p not in _af.parameters:
                sorun.append(f"Screener.add_filter gerçek imzasında '{_p}' yok")
        from borsapy._providers.isyatirim_screener import IsyatirimScreenerProvider
        if IsyatirimScreenerProvider.CRITERIA_MAP.get("foreign_ratio") != "40":
            sorun.append("İş Yatırım kriter kodu değişmiş: foreign_ratio != 40 (betik criteria_40 okuyor)")
        if 'f"criteria_{key}"' not in inspect.getsource(IsyatirimScreenerProvider.screen):
            sorun.append("İş Yatırım tarama sonucu artık criteria_<id> sütunu üretmiyor")
    except Exception as e:
        sorun.append(f"Screener sözleşmesi kontrol edilemedi: {type(e).__name__}: {e}")
    kaynak = inspect.getsource(gercek.EVDS.search)
    for sutun in sahte.evds_search("gösterge").columns:
        if f'"{sutun}"' not in kaynak:
            sorun.append(f"sahte evds_search sütunu '{sutun}' gerçekte üretilmiyor")
    if sorun:
        print("SÖZLEŞME SORUNLARI:", *sorun, sep="\n  ")
    return {"ok": not sorun, "gercek": True, "sorun": sorun}

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
                                           # 6 Eki: eski çalışmanın yanlış işaretlediği künye (tek seferlik onarımla temizlenmeli)
                                           "OS0": {"t": _d.today().strftime("%Y-%m-%d"), "buyukluk": 7.5e8, "kunye_kaynak": "borsapy",
                                                   "fonoloji_denendi": _d.today().strftime("%Y-%m-%d")},
                                           # 3 Eki: bugün çekilmiş ama portföyü olmayan (eski kod) künye → yenilenmeli
                                           "YLB": {"t": _d.today().strftime("%Y-%m-%d"), "buyukluk": 1e11, "kunye_kaynak": "fonoloji"},
                                           # 6 Eki: bugün TEFAS'tan (borsapy) gelmiş portföysüz künye → Fonoloji yeniden denenmeli
                                           "PB1": {"t": _d.today().strftime("%Y-%m-%d"), "buyukluk": 7.5e8, "kunye_kaynak": "borsapy"}}})
    kunye_sonra = json.load(open(os.path.join(EVREN["son"], "output", "fon_kunye.json"), encoding="utf-8"))
    akis_kamu = (((d_sinif.get("rakip_tarama") or {}).get("varlik_siniflari") or {}).get("siniflar") or {}).get(
        "Kamu borçlanma (devlet tahvili)", {}).get("akis_30g_pct")
    sinif_olgun = d_sinif["tetikler"].get("varlik_sinifi_olgun", [])
    import csv as _csv
    d = calistir(); T = d["tetikler"]
    _ana = EVREN["son"]
    k = T.get("k3_donus_kapisi", {}); fon = d.get("fonlar_borsapy") or d.get("fonlar", {})   # borsapy filtre testleri ham borsapy verisine bakar
    d_cokme = calistir_klasor(_ana, {"RADAR_TEST_COKME": "1"})   # aynı klasörde kontrollü çökme
    _aj = lambda x: json.dumps(x, ensure_ascii=False)
    d_ayar_ozel = calistir(kok={"ayarlar.json": _aj({"fonlar": {"YLB": "cephane", "XYZ": "cephane", "TIE": "borsa"},
        "politika_faizi": {"oran": 35.0, "karar_tarihi": "2026-10-22", "sonraki_ppk": "2026-12-11"}})})
    d_ayar_bozuk = calistir(kok={"ayarlar.json": "{ bozuk json"})
    d_ayar_gecersiz = calistir(kok={"ayarlar.json": _aj({"fonlar": {"YLB": "yanlis_rol"}, "stopaj_ppf": 5})})
    d_429 = calistir(ek_env={"RADAR_MOCK_429": "3"})
    d_429k = calistir(ek_env={"RADAR_MOCK_429_KUNYE": "1"})
    _k429 = json.load(open(os.path.join(EVREN["son"], "output", "fon_kunye.json"), encoding="utf-8"))
    _giris = (_pd.Timestamp(_d.today()) - _pd.offsets.BDay(20)).strftime("%Y-%m-%d")
    _gelecek = (_pd.Timestamp(_d.today()) + _pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    def _poz(**deg):
        kural = {"giris_tarihi": _giris, "kiyas": "YLB", "kar_sarti_puan": 2, "kar_tarihi": "2099-01-31",
                 "zaman_duragi_tarihi": "2099-12-11", "zarar_siniri_pct": -4, "baslangic_politika_faizi": 37.0}
        kural.update(deg)
        return _aj({"fonlar": {"YLB": "cephane", "BGP": "cephane", "YOT": "tahvil", "TIE": "borsa"},
                    "pozisyon_kurallari": {"YOT": kural}})
    d_poz = calistir(kok={"ayarlar.json": _poz()})
    d_poz_zarar = calistir(kok={"ayarlar.json": _poz(zarar_siniri_pct=50)})
    d_poz_bekl = calistir(kok={"ayarlar.json": _poz(giris_tarihi=_gelecek)})
    d_poz_gecersiz = calistir(kok={"ayarlar.json": _aj({"pozisyon_kurallari": {"YOT": {"giris_tarihi": _giris}}})})
    # 7 Eki tahvil altyapısı: banka teyitli giriş fiyatı ile zarar sınırına yakın senaryo (getiri ≈ −%3,5)
    sys.path.insert(0, MOCK); import requests as _mreq; sys.path.pop(0)
    _p_son = _mreq.get("https://x/v1/funds/YOT/history", {"period": "1y"}).json()["points"][-1]["price"]
    d_poz_yakin = calistir(kok={"ayarlar.json": _poz(giris_fiyati=round(_p_son / 0.965, 6))})
    # 19 Eki: kıyas fona göre (göreli) zarar sınırı — aynı −%3,5 senaryosunda fark ≈ −3,5 − YLB getirisi
    _gf = round(_p_son / 0.965, 6)
    d_poz_goreli = calistir(kok={"ayarlar.json": _poz(giris_fiyati=_gf, goreli_zarar_puan=-1)})
    _fy = ((d_poz_yakin.get("pozisyon_takip") or {}).get("YOT") or {}).get("fark_puan") or -4.0
    d_poz_goreli_yakin = calistir(kok={"ayarlar.json": _poz(giris_fiyati=_gf, goreli_zarar_puan=round(_fy / 0.85, 2))})
    d_poz_goreli_bozuk = calistir(kok={"ayarlar.json": _poz(goreli_zarar_puan=1)})
    # 20 Eki (hata #25): para piyasası fonlarındaki özel sektör tahvili payı alarmı
    _gun5 = (_pd.Timestamp(_AN[:10]) - _pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    _gun60 = (_pd.Timestamp(_AN[:10]) - _pd.Timedelta(days=60)).strftime("%Y-%m-%d")
    d_osba_yuksek = calistir(ek_env={"RADAR_MOCK_OSBA": "YLB:12"})
    d_osba_artis = calistir(tohum={"ozel_tahvil_gecmis.json": {_gun5: {"ZBJ": 1.0}, _gun60: {"ZBJ": 0.0}}},
                            ek_env={"RADAR_MOCK_OSBA": "ZBJ:6.5"})
    d_osba_eski = calistir(tohum={"ozel_tahvil_gecmis.json": {_gun60: {"ZBJ": 0.0}}}, ek_env={"RADAR_MOCK_OSBA": "ZBJ:6.5"})
    d_osba_yakin = calistir(ek_env={"RADAR_MOCK_OSBA": "BGP:8"})
    d_osba_izleme = calistir(kok={"ayarlar.json": _aj({"fonlar": {"YLB": "cephane", "IJV": "izleme", "TIE": "borsa"}})},
                             ek_env={"RADAR_MOCK_OSBA": "IJV:30"})
    d_kaba = calistir(kok={"ayarlar.json": _poz()}, ek_env={"EVDS_API_KEY": "", "RADAR_MOCK_TV_HATA": "1"})   # verim geçmişi yok → kaba tahmin
    # 9 Eki: EVDS'de gösterge seri yok (canlıdaki gerçek durum) → bilgi notu, Issue yok, aday listesi dosyada, haftada bir yeniden arama
    d_vyok = calistir(kok={"ayarlar.json": _poz()}, ek_env={"RADAR_MOCK_EVDS_VERIM_YOK": "1", "RADAR_MOCK_TV_HATA": "1"})
    _vyok_dosya = json.load(open(os.path.join(EVREN["son"], "output", "verim_evds.json"), encoding="utf-8"))
    d_vyok2 = calistir_klasor(EVREN["son"], {"RADAR_MOCK_EVDS_VERIM_YOK": "1", "RADAR_AGIR": "true"})
    d_vkod = calistir(kok={"ayarlar.json": _aj({**json.loads(_poz()), "verim_evds_kodu": "TP.DIBS.G2Y"})},
                      ek_env={"RADAR_MOCK_EVDS_VERIM_YOK": "1"})
    sozlesme = sozlesme_kontrol()
    # 15 Eki: tahvil faizi kaynağı (doviz.com) bozuldu → yedekler
    d_th1 = calistir(kok={"ayarlar.json": _poz()}, ek_env={"RADAR_MOCK_TAHVIL_HATA": "1", "RADAR_MOCK_DOVIZ_SAYFA": "yeni"})
    d_th2 = calistir(kok={"ayarlar.json": _poz()}, ek_env={"RADAR_MOCK_TAHVIL_HATA": "1", "RADAR_MOCK_DOVIZ_SAYFA": "bot"})
    _tani = json.load(open(os.path.join(EVREN["son"], "output", "tahvil_tani.json"), encoding="utf-8"))
    for _i in range(4):                                     # art arda 4 bozuk birincil, yedek çalışıyor
        d_th2b = calistir_klasor(EVREN["son"], {"RADAR_MOCK_TAHVIL_HATA": "1", "RADAR_MOCK_DOVIZ_SAYFA": "bot"})
    d_th3 = calistir(kok={"ayarlar.json": _poz()}, ek_env={"RADAR_MOCK_TAHVIL_HATA": "1", "RADAR_MOCK_TV_HATA": "1"})
    d_tvh = calistir(kok={"ayarlar.json": _poz()}, ek_env={"RADAR_AGIR": "true", "RADAR_MOCK_EVDS_VERIM_YOK": "1"})
    # 15 Eki: yanlış ama "başarılı" kaynak verisi, bozuk arşiv kaydı, Fonoloji zaman aşımı
    d_sacma = calistir(tohum={"verim_gecmisi.json": {"2026-10-14": {"2Y": 3.29, "5Y": 2.35, "10Y": 3.01, "None": 4.05},
                                                     "2026-10-13": {"2Y": 39.58, "5Y": 38.62, "10Y": 35.52}}},
                       ek_env={"RADAR_MOCK_TAHVIL_SACMA": "1", "RADAR_MOCK_DOVIZ_SAYFA": "yeni"})
    _ars_sacma = json.load(open(os.path.join(EVREN["son"], "output", "verim_gecmisi.json"), encoding="utf-8"))
    d_yt1 = calistir(ek_env={"RADAR_AGIR": "true"})
    d_yt2 = calistir(ek_env={"RADAR_AGIR": "true", "RADAR_MOCK_TARAMA_HATA": "1"})
    # 17 Eki: borsa planı (kullanıcı kararı B) + panik dibi alarmı
    _gercek_ayar = json.load(open(os.path.join(KOK, "ayarlar.json"), encoding="utf-8"))
    _bp = _gercek_ayar["borsa_plani"]
    def _plan(**degis):
        import copy
        bp_ = copy.deepcopy(_bp)
        for k in bp_["kurallar"]:
            k.update(degis.get(k["ad"], {}))
        return _aj({**json.loads(_poz()), "borsa_plani": bp_, "panik_dibi": _gercek_ayar["panik_dibi"]})
    d_plan = calistir(kok={"ayarlar.json": _plan()})
    d_plan2 = calistir(kok={"ayarlar.json": _plan(azalt1={"gerceklesti": True}, azalt2={"gerceklesti": True}, koruma={"seviye": 20000})})
    d_panik = calistir(kok={"ayarlar.json": _plan()}, ek_env={"RADAR_MOCK_PANIK": "1"})
    # 24 Eki (kullanıcı kararı A): koruma kuralına "panik haftası" istisnası
    _kor = _plan(koruma={"seviye": 12000})
    d_kor_ertele = calistir(kok={"ayarlar.json": _kor}, ek_env={"RADAR_MOCK_HAFTA_PANIK": "1"})
    d_kor_ikinci = calistir(kok={"ayarlar.json": _kor}, ek_env={"RADAR_MOCK_HAFTA_PANIK": "2"})
    d_kor_yavas = calistir(kok={"ayarlar.json": _kor}, ek_env={"RADAR_MOCK_HAFTA_PANIK": "3"})
    _hafta_birim = haftalik_kapanis_birim()
    # 30 Eki: küresel para akışı, USDT primi, piyasa takvimi, kalibrasyon
    _takvim = piyasa_takvimi_birim()
    d_tur = calistir(ek_env={"RADAR_MOCK_TUR_DUSUS": "1", "RADAR_MOCK_KREDI_STRES": "1"})
    d_usdt_yedek = calistir(ek_env={"RADAR_MOCK_BTCTURK_HATA": "1"})
    _an_gun = _pd.Timestamp(_AN[:10])
    _usdt_gecmis = {(_an_gun - _pd.offsets.BDay(i)).strftime("%Y-%m-%d"): 0.8 for i in range(1, 8)}
    d_usdt_alarm = calistir(tohum={"usdt_prim_gecmis.json": _usdt_gecmis}, ek_env={"RADAR_MOCK_USDT_PRIM": "4.0"})
    d_usdt_yeni = calistir(ek_env={"RADAR_MOCK_USDT_PRIM": "4.0"})
    d_tatil_aksam = calistir(ek_env={"RADAR_TEST_NOW": "2026-10-29 18:17"})
    d_kalib = calistir(kok={"ayarlar.json": _poz()}, ek_env={"RADAR_AGIR": "true"})
    d_tatil_ayar = calistir(kok={"ayarlar.json": _aj({"tatiller": [{"tarih": "2026-11-02", "tur": "yanlis"}]})})
    d_plan_bozuk = calistir(kok={"ayarlar.json": _aj({"borsa_plani": {"kurallar": [{"ad": "x", "tip": "yanlis", "seviye": 12000, "islem": "?"}]}})})
    d_fz1 = calistir(ek_env={"RADAR_MOCK_FONO_TIMEOUT": "YLB"})
    d_fz2 = calistir(ek_env={"RADAR_MOCK_FONO_TIMEOUT_HEP": "YLB"})
    # 12 Eki: sabah ağır çalışması 40 dk'da iptal edildi → süre bütçesi + sert sınır
    calistir()                                             # önceki veriyi üreten temel çalışma
    _sure_klasor = EVREN["son"]
    d_butce = calistir_klasor(_sure_klasor, {"RADAR_BUTCE_DK": "0", "RADAR_AGIR": "true"})
    d_sert = calistir_klasor(_sure_klasor, {"RADAR_SERT_DK": "0.05", "RADAR_TEST_YAVAS": "8",
                                            "RADAR_TEST_NOW": "2026-10-12 08:17"})
    # 12 Eki öğlen: TEFAS hiç yanıt vermiyor (gerçek olay) → devre kesici, sadece taramanın tekrarı, yabancı oranı süre sınırı
    calistir(ek_env={"RADAR_TEST_NOW": "2026-10-09 19:00"})      # önceki gün akşamı: sağlam veri
    _tf = EVREN["son"]
    d_tf1 = calistir_klasor(_tf, {"RADAR_MOCK_TEFAS_TIMEOUT": "1", "RADAR_TEST_NOW": "2026-10-12 08:17",
                                  "RADAR_YABANCI_SURE_SN": "0", "RADAR_MOCK_TARAMA_HATA": "1"})
    _sayac2 = os.path.join(_tf, "tefas_sayac_saatlik.txt")
    d_tf2 = calistir_klasor(_tf, {"RADAR_MOCK_TEFAS_TIMEOUT": "1", "RADAR_TEST_NOW": "2026-10-12 10:17",
                                  "RADAR_MOCK_SAYAC": _sayac2})
    _cagri2 = open(_sayac2).read().split() if os.path.exists(_sayac2) else []
    for _sa in ("11:17", "12:17", "13:17"):                      # kullanıcı kararı: alınana kadar her saat denenir (sınır yok)
        d_tf5 = calistir_klasor(_tf, {"RADAR_MOCK_TEFAS_TIMEOUT": "1", "RADAR_TEST_NOW": f"2026-10-12 {_sa}"})
    d_tf3 = calistir_klasor(_tf, {"RADAR_TEST_NOW": "2026-10-12 14:17"})
    d_yedek = calistir(ek_env={"RADAR_MOCK_FON_HATA": "YLB,IJV", "RADAR_MOCK_HISTORY_HATA": "1"})  # 6 Eki: TEFAS boş + rakip geçmişleri hata
    rt = d.get("rakip_tarama") or {}; pp = rt.get("para_piyasasi") or {}
    vs = rt.get("varlik_siniflari") or {}
    _taf = ((d_poz.get("tahvil_analiz") or {}).get("fonlar") or {})
    ta_yot, ta_kb0 = _taf.get("YOT") or {}, _taf.get("KB0") or {}
    def _sen(t, dy):
        return next((x["fark_puan"] for x in ((t.get("senaryo") or {}).get("senaryolar") or []) if x["verim_degisimi_puan"] == dy), 0)
    ta = rt.get("tahvil_adaylari") or {}
    _p = os.path.join(EVREN["klasor"], "output", "fon_evreni.csv")
    _rows = list(_csv.DictReader(open(_p, encoding="utf-8"))) if os.path.exists(_p) else []
    ev_satir = len(_rows); ev_bayrak = {r["kod"]: r for r in _rows}
    def adaylar(grup, kod):
        return [a["kod"] for a in ((rt.get(grup) or {}).get("bizim", {}).get(kod, {}).get("gecis_adaylari") or [])]
    testler = [
        # (koşul, açıklama, eklendiği tarih/sebep)
        (fon["DLY"]["fiyat"] > 0,                                   "Sıfır fon fiyatı elenir (24 Eyl TEFAS DLY=0)"),
        (all(v.get("durum") != "ACIL" for v in T["reel_getiri"].values()), "Sıfır fiyat yanlış ACİL alarmı üretmez"),
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
        # --- 7 Eki tahvil altyapısı: faiz duyarlılığı, senaryo, verim geçmişi ---
        (1.3 <= ((ta_yot.get("etkin_sure") or {}).get("sure_yil") or 0) <= 1.7 and ((ta_yot.get("etkin_sure") or {}).get("r2") or 0) >= 0.5,
                                                                    "Tahvil: YOT'un faiz duyarlılığı (~1,5 yıl) veriden doğru hesaplanır"),
        (3.6 <= ((ta_kb0.get("etkin_sure") or {}).get("sure_yil") or 0) <= 4.4, "Tahvil: uzun vadeli fonun (~4 yıl) daha yüksek duyarlılığı ayırt edilir"),
        (_sen(ta_yot, -2) > 0 and _sen(ta_yot, 2) < 0,             "Senaryo: faiz düşerse tahvil fonu para piyasasını geçer, yükselirse geride kalır"),
        (isinstance((ta_yot.get("senaryo") or {}).get("basabas_verim_degisimi_puan"), (int, float)), "Senaryo: başabaş faiz değişimi hesaplanır"),
        ((d_poz.get("verim_evds") or {}).get("kod") == "TP.DIBS.G2Y", "Verim: EVDS'de 2 yıllık gösterge serisi adla bulunur (5 yıllık seçilmez)"),
        ((d_poz.get("verim_arsivi") or {}).get("gun_sayisi", 0) >= 1, "Verim: günlük tahvil faizi arşivi tutulur"),
        # --- 9 Eki: EVDS gösterge serisi bulunamazsa (canlı durum) ---
        (str(d_vyok["saglik"]["tum_moduller"].get("verim_evds", "")).startswith("NOT:")
         and "verim_evds" not in d_vyok["saglik"].get("issue_tetikleyen", []),
                                                                    "Verim: EVDS'de seri yoksa bilgi notu düşer, Issue (bildirim) açılmaz"),
        (any("TP.MKNETHAR.M2" in str(x) for x in _vyok_dosya.get("adaylar", [])) and _vyok_dosya.get("kod") is None,
                                                                    "Verim: incelenen EVDS adayları dosyaya yazılır (gerçek sütun adlarıyla okunur)"),
        ("yeniden aranacak" in str((d_vyok2.get("verim_evds") or {}).get("durum", "")),
                                                                    "Verim: bulunamayan seri her çalışmada değil haftada bir yeniden aranır"),
        ("KABA TAHMİN" in str((((d_vyok.get("tahvil_analiz") or {}).get("fonlar") or {}).get("YOT") or {}).get("sure_kaynagi"))
         and d_vyok["saglik"]["tum_moduller"].get("tahvil_analiz") == "OK",
                                                                    "Verim: seri yokken tahvil analizi çalışmaya devam eder (kaba tahmin etiketiyle)"),
        ((d_vkod.get("verim_evds") or {}).get("kod") == "TP.DIBS.G2Y" and "elle" in str((d_vkod.get("verim_evds") or {}).get("ad")),
                                                                    "Verim: ayarlar.json'daki 'verim_evds_kodu' ile seri elle verilebilir"),
        # --- 12 Eki: süre yönetimi ---
        (str(d_butce["saglik"]["tum_moduller"].get("rakip_tarama", "")).startswith("NOT: süre")
         and "rakip_tarama" not in d_butce["saglik"].get("issue_tetikleyen", [])
         and bool((d_butce.get("rakip_tarama") or {}).get("para_piyasasi")),
                                                                    "Süre: bütçe dolunca ağır tarama atlanır, önceki tarama korunur, bildirim açılmaz"),
        ("rakip_tarama" not in (d_butce.get("agir_tekrar_denenecek") or []),
                                                                    "Süre: bütçeyle atlanan tarama her saat yeniden denenmez (akşam çalışması yapar)"),
        (bool(d_butce.get("tahvil_analiz")),                       "Süre: tahvil analizi atlanırsa önceki sonuç korunur"),
        (isinstance(d_butce["saglik"].get("en_yavas_moduller_sn"), dict) and d_butce["saglik"]["en_yavas_moduller_sn"]
         and isinstance(d_butce.get("calisma_suresi_dk"), (int, float)),
                                                                    "Süre: her modülün süresi ölçülür, en yavaşlar raporlanır"),
        ("sert süre" in str(d_sert.get("cokme", "")) and bool((d_sert.get("bist100") or {}).get("son_fiyat")),
                                                                    "Süre: sert sınırda çalışma kesilir, önceki veri korunur (iş iptal edilmez)"),
        (d_sert.get("agir_slot") == "2026-10-12-sabah",            "Süre: sert sınıra takılan ağır pencere kullanılmış sayılır (saatlik deneme zinciri olmaz)"),
        # --- 12 Eki: TEFAS kesintisi ---
        (str(d_tf1["saglik"]["tum_moduller"].get("tefas_devre", "")).startswith("NOT:")
         and any("bu turda atlandı" in str(v) for k, v in d_tf1["saglik"]["tum_moduller"].items() if k.startswith("yedek_borsapy_fon_")),
                                                                    "TEFAS: iki ağ hatasından sonra diğer TEFAS çağrıları denenmez (devre kesici)"),
        (not any(k.startswith(("fon_bilgi_", "fon_ucret_")) or k in [f"fon_{c}" for c in ("YLB", "IJV", "ZBJ", "BGP", "YOT", "TIE", "AKU")]
                 for k in d_tf1["saglik"].get("issue_tetikleyen", [])),
                                                                    "TEFAS: Fonoloji çalışırken yedek bilgi/ücret hataları bildirim açmaz"),
        (d_tf1.get("agir_slot") == "2026-10-12-sabah" and d_tf1.get("rakip_tekrar") == 1
         and bool((d_tf1.get("rakip_tarama") or {}).get("para_piyasasi")),
                                                                    "TEFAS: tarama başarısızsa ağır pencere tüketilir, önceki tarama korunur, tekrar sayacı başlar"),
        (_cagri2.count("screen") == 1 and len(_cagri2) <= 3,       "Döngü yok: saatlik tekrarda TEFAS'a en fazla 3 istek gider (tarama 1 kez, fon verisi devre kesiciyle 2)"),
        (d_tf2.get("rakip_tekrar") == 2 and not d_tf2.get("agir_calisma"),
                                                                    "TEFAS: sonraki saatte sadece tarama yeniden denenir (bütün ağır iş değil)"),
        (d_tf5.get("rakip_tekrar") == 5 and d_tf5.get("tefas_yedek_tekrar") == 5,
                                                                    "TEFAS: tarama ve yedek fon verisi alınana kadar her saat yeniden denenir (üst sınır yok)"),
        (d_tf1.get("tefas_yedek_tekrar") == 1 and not d_tf3.get("tefas_yedek_tekrar")
         and str(d_tf3.get("tefas_yedek_zamani", "")).startswith("2026-10-12 14") and bool(d_tf3.get("fonlar_borsapy", {}).get("YLB")),
                                                                    "TEFAS: düzelince yedek fon verisi (çapraz kontrol) aynı gün alınır, sayaç sıfırlanır"),
        (not d_tf3.get("rakip_tekrar") and str((d_tf3.get("rakip_tarama") or {}).get("zaman", "")).startswith("2026-10-12 14"),
                                                                    "TEFAS: düzelince tarama yenilenir ve sayaç sıfırlanır"),
        (str(d_tf5["saglik"]["tum_moduller"].get("kaynak_tefas", "")).startswith("UYARI")
         and "kaynak_tefas" in d_tf5["saglik"].get("issue_tetikleyen", []),
                                                                    "Karne: bir kaynak art arda başarısız olursa bildirim açılır (erişimi düzelt / yeni kaynak)"),
        ("kaynak_tefas" not in d_tf3["saglik"]["tum_moduller"]
         and {"08", "10", "11", "12", "13"} <= set(((d_tf3.get("kaynak_karnesi") or {}).get("tefas") or {}).get("basarisiz_saatler", {})),
                                                                    "Karne: kaynak düzelince uyarı kalkar; başarısız olduğu saatler kayıtlı"),
        (((d_tf3.get("kaynak_karnesi") or {}).get("fonoloji") or {}).get("ardisik_basarisiz") == 0
         and os.path.exists(os.path.join(_tf, "output", "kaynak_karnesi.json")),
                                                                    "Karne: her kaynağın geçmişi dosyada birikir (Fonoloji kesintisiz)"),
        (str(d_tf1["saglik"]["tum_moduller"].get("yabanci_orani", "")).startswith("NOT:")
         and "önceki veri" in str((d_tf1.get("yabanci") or {}).get("not_onbellek", "")),
                                                                    "Yabancı oranı: kaynak yavaşsa süre sınırında durur, önceki veri kullanılır, bildirim yok"),
        # --- 15 Eki: tahvil faizi yedekleri + TradingView geçmişi ---
        (d_th1.get("tahvil_kaynak") == "doviz.com (kendi okuma)" and str(d_th1["saglik"]["tum_moduller"].get("tahvil", "")).startswith("NOT")
         and "tahvil" not in d_th1["saglik"].get("issue_tetikleyen", [])
         and any(x.get("maturity") == "2Y" and abs(x.get("yield", 0) - 39.58) < 0.01 for x in d_th1.get("tahvil") or []),
                                                                    "Tahvil: borsapy okuyamazsa doviz.com sayfası kendi yöntemimizle okunur (tablo kimliğine bağlı değil)"),
        (str(d_th2.get("tahvil_kaynak", "")).startswith("TVC:TR02Y") and not any(k.startswith("tahvil") for k in d_th2["saglik"].get("issue_tetikleyen", [])),
                                                                    "Tahvil: sayfa da okunamazsa TradingView yedeği devreye girer, bildirim açılmaz"),
        (_tani.get("bot_isareti") is True and _tani.get("baslik") == "Just a moment...",
                                                                    "Tahvil: okunamayan sayfanın ne döndürdüğü tanı dosyasına yazılır (bot sayfası teşhisi)"),
        (str(d_th2b["saglik"]["tum_moduller"].get("kaynak_tahvil_faizi", "")).startswith("NOT")
         and "kaynak_tahvil_faizi" not in d_th2b["saglik"].get("issue_tetikleyen", []),
                                                                    "Karne: birincil kaynak bozuk ama yedeği çalışıyorsa uyarı değil not düşer"),
        ("tahvil" in d_th3["saglik"].get("issue_tetikleyen", []),  "Tahvil: bütün kaynaklar bozuksa bildirim açılır"),
        ((d_tvh.get("verim_tv") or {}).get("dogrulandi") is True and (d_tvh.get("verim_tv") or {}).get("kod") == "TVC:TR02Y"
         and (d_tvh.get("verim_tv") or {}).get("gozlem", 0) >= 400,
                                                                    "Tahvil: 2 yıllık faizin 2 yıllık geçmişi TradingView'den alınır, kendi arşivimizle doğrulanır"),
        (str((d_tvh.get("tahvil_analiz") or {}).get("verim_kaynagi", "")).startswith("TradingView")
         and 1.3 <= ((((d_tvh.get("tahvil_analiz") or {}).get("fonlar") or {}).get("YOT") or {}).get("etkin_sure") or {}).get("sure_yil", 0) <= 1.7,
                                                                    "Tahvil: EVDS'de seri yokken bile YOT'un faize duyarlılığı geçmiş veriden hesaplanır (kaba tahmin bitti)"),
        (abs((d_tvh.get("verim_tv") or {}).get("ortalama_fark_puan", 9) if (d_tvh.get("verim_tv") or {}).get("ortalama_fark_puan") is not None else 9) < 0.05,
                                                                    "Tahvil: TradingView yarıyıllık verimi yıllık bileşiğe çevrilir (birim farkı ~3,3 puan giderilir)"),
        (d_sacma.get("tahvil_kaynak") == "doviz.com (kendi okuma)" and "makul değil" in str(d_sacma["saglik"]["tum_moduller"].get("tahvil", "")),
                                                                    "Tahvil: kaynak 'çalıştı' ama değer saçmaysa (2Y=3,29) başarısız sayılır, yedeğe geçilir"),
        ("2026-10-14" not in _ars_sacma and _ars_sacma.get("2026-10-13", {}).get("2Y") == 39.58
         and all(5 <= v <= 80 for e in _ars_sacma.values() for v in e.values()),
                                                                    "Tahvil: arşivdeki bozuk kayıtlar temizlenir, sağlamlar korunur"),
        (d_fz1["saglik"]["tum_moduller"].get("fonoloji_YLB") == "OK" and d_fz1.get("fonlar_kaynak", {}).get("YLB") == "fonoloji",
                                                                    "Fonoloji: tek seferlik zaman aşımında bir kez daha denenir, veri gelir"),
        (str(d_fz2["saglik"]["tum_moduller"].get("fonoloji_YLB", "")).startswith("NOT") and "fonoloji_YLB" not in d_fz2["saglik"].get("issue_tetikleyen", [])
         and d_fz2.get("fonlar_kaynak", {}).get("YLB") == "borsapy",
                                                                    "Fonoloji: kalıcı zaman aşımında TEFAS yedeği kullanılır, bildirim değil not düşer"),
        (d_yt1.get("yabanci_kaynak") == "İş Yatırım tarama (toplu)" and (d_yt1.get("yabanci") or {}).get("bugun_ort_yabanci_orani") == 41.0,
                                                                    "Yabancı oranı: tek istekle (İş Yatırım tarama) alınır, sadece BIST 30 hisseleri kullanılır"),
        (d_yt2.get("yabanci_kaynak") == "hisse hisse (yedek)" and str(d_yt2["saglik"]["tum_moduller"].get("yabanci_orani_toplu", "")).startswith("NOT")
         and "yabanci_orani_toplu" not in d_yt2["saglik"].get("issue_tetikleyen", []),
                                                                    "Yabancı oranı: toplu tarama çalışmazsa eski yöntem yedek olarak devreye girer, bildirim açılmaz"),
        ((lambda bpk: bpk.get("azalt1") == "TETİKLENDİ" and bpk.get("azalt2") == "TETİKLENDİ" and bpk.get("plan1") == "BEKLİYOR"
                     and bpk.get("koruma") == "BEKLİYOR")({k["ad"]: k["durum"] for k in ((d_plan["tetikler"].get("borsa_plani") or {}).get("kurallar") or [])})
         and "borsa_plani_azalt1" in d_plan["saglik"].get("issue_tetikleyen", []),
                                                                    "Borsa planı: seviye görülünce kural tetiklenir ve bildirim açılır (12.200 / 12.600 azaltma)"),
        ((lambda bpk: bpk.get("azalt1") == "YAPILDI" and bpk.get("koruma") == "TETİKLENDİ")({k["ad"]: k["durum"] for k in ((d_plan2["tetikler"].get("borsa_plani") or {}).get("kurallar") or [])})
         and "borsa_plani_azalt1" not in d_plan2["saglik"]["tum_moduller"] and "borsa_plani_koruma" in d_plan2["saglik"].get("issue_tetikleyen", []),
                                                                    "Borsa planı: yapıldı işaretli kural susar; haftalık koruma seviyesi altında koruma tetiklenir"),
        (((d_panik["tetikler"].get("borsa_plani") or {}).get("panik_dibi") or {}).get("durum") == "ALARM"
         and "panik_dibi" in d_panik["saglik"].get("issue_tetikleyen", [])
         and ((d_plan["tetikler"].get("borsa_plani") or {}).get("panik_dibi") or {}).get("durum") == "YOK",
                                                                    "Panik dibi: sert düşüş + yüksek hacim + ertesi gün dönüş → alarm; normal günde alarm yok"),
        ({k["ad"]: k for k in ((d_kor_ertele["tetikler"].get("borsa_plani") or {}).get("kurallar") or [])}.get("koruma", {}).get("durum") == "ERTELENDİ (panik haftası)"
         and "borsa_plani_koruma_ertelendi" in d_kor_ertele["saglik"].get("issue_tetikleyen", [])
         and "borsa_plani_koruma" not in d_kor_ertele["saglik"]["tum_moduller"],
                                                                    "Koruma: seviyenin altına ilk inilen haftada panik günü varsa satış 1 hafta ertelenir ve bildirilir"),
        ({k["ad"]: k for k in ((d_kor_ikinci["tetikler"].get("borsa_plani") or {}).get("kurallar") or [])}.get("koruma", {}).get("durum") == "TETİKLENDİ"
         and "borsa_plani_koruma" in d_kor_ikinci["saglik"].get("issue_tetikleyen", []),
                                                                    "Koruma: ikinci hafta da altındaysa panik olsa bile satış tetiklenir"),
        ({k["ad"]: k for k in ((d_kor_yavas["tetikler"].get("borsa_plani") or {}).get("kurallar") or [])}.get("koruma", {}).get("durum") == "TETİKLENDİ"
         and "borsa_plani_koruma" in d_kor_yavas["saglik"].get("issue_tetikleyen", []),
                                                                    "Koruma: panik günü olmadan (yavaş düşüş) altında kapanış → satış tetiklenir"),
        (_hafta_birim == ["True", "90.0", "100.0", "2026-10-23"],
                                                                    "Haftalık kapanış: pazartesi seans içinde son bitmiş hafta doğru seçilir (2 hafta öncesi değil)"),
        ("borsa_plani" in str(d_plan_bozuk["saglik"]["hatali_moduller"].get("ayarlar")),
                                                                    "Borsa planı: ayarlar.json'da hatalı kural reddedilir, uyarı verilir"),
        (sozlesme["ok"],                                            "Sözleşme: sahte borsapy, gerçek borsapy ile aynı arama sütunlarını ve betiğin kullandığı parametreleri taşır"
                                                                    + ("" if sozlesme["gercek"] else " (gerçek borsapy yüklü değil — ATLANDI)")),
        ("KABA TAHMİN" in str((((d_kaba.get("tahvil_analiz") or {}).get("fonlar") or {}).get("YOT") or {}).get("sure_kaynagi")),
                                                                    "Tahvil: geçmiş veri yoksa duyarlılık 'KABA TAHMİN' diye açıkça etiketlenir"),
        (str(((d_poz_yakin.get("pozisyon_takip") or {}).get("YOT") or {}).get("giris_fiyati_kaynak", "")).startswith("banka"),
                                                                    "Pozisyon: bankadan teyitli giriş fiyatı esas alınır"),
        ("pozisyon_YOT_yakin" in d_poz_yakin["saglik"]["tum_moduller"] and "pozisyon_YOT_yakin" not in d_poz_yakin["saglik"].get("issue_tetikleyen", []),
                                                                    "Pozisyon: zarar sınırına yaklaşınca bildirimsiz erken not düşer"),
        # --- 30 Eki: küresel para akışı, USDT primi, piyasa takvimi, kalibrasyon ---
        (((d["tetikler"].get("kuresel_akis")) or {}).get("turkiye_vs_gelismekte", {}).get("durum") == "NORMAL"
         and ((d_tur["tetikler"].get("kuresel_akis")) or {}).get("turkiye_vs_gelismekte", {}).get("durum") == "TÜRKİYE'YE ÖZGÜ BASKI",
                                                                    "Küresel: Türkiye ETF'i gelişmekte olan ülkelerden ayrışınca 'Türkiye'ye özgü baskı' der"),
        (((d["tetikler"].get("kuresel_akis")) or {}).get("kuresel_kredi", {}).get("durum") == "NORMAL"
         and ((d_tur["tetikler"].get("kuresel_akis")) or {}).get("kuresel_kredi", {}).get("durum") == "STRES",
                                                                    "Küresel: yüksek riskli tahviller 1 ayda sert düşünce kredi stresi işaretlenir"),
        (isinstance(((d["tetikler"].get("kuresel_akis")) or {}).get("bitcoin", {}).get("son_cumadan_beri_pct"), (int, float)),
                                                                    "Küresel: Bitcoin'in son cumadan beri değişimi (hafta sonu risk iştahı) hesaplanır"),
        (isinstance(((d["tetikler"].get("bist_dolar")) or {}).get("son"), (int, float)) and ((d["tetikler"].get("bist_dolar")) or {}).get("52h_dip") is not None
         and ((d["tetikler"].get("bist_dolar")) or {}).get("durum"),
                                                                    "BIST dolar bazında: değer, 52 haftalık aralık ve konum hesaplanır"),
        (((d["tetikler"].get("usdt_prim")) or {}).get("kaynak") == "BtcTurk" and ((d["tetikler"].get("usdt_prim")) or {}).get("durum") == "NORMAL"
         and abs((((d["tetikler"].get("usdt_prim")) or {}).get("prim_pct") or 0) - 0.8) < 0.05,
                                                                    "USDT primi: BtcTurk fiyatı resmi kurla karşılaştırılır (normal prim)"),
        (((d_usdt_yedek["tetikler"].get("usdt_prim")) or {}).get("kaynak") == "Paribu"
         and not any(k.startswith("usdt_") for k in d_usdt_yedek["saglik"].get("issue_tetikleyen", [])),
                                                                    "USDT primi: BtcTurk erişilemezse Paribu yedeği çalışır, bildirim üretmez"),
        (((d_usdt_alarm["tetikler"].get("usdt_prim")) or {}).get("durum") == "ALARM" and "usdt_prim_alarm" in d_usdt_alarm["saglik"].get("issue_tetikleyen", []),
                                                                    "USDT primi: olağanın belirgin üstüne çıkınca (%4 vs %0,8) bildirim gelir"),
        (str(((d_usdt_yeni["tetikler"].get("usdt_prim")) or {}).get("durum", "")).startswith("YÜKSEK")
         and "usdt_prim_alarm" not in d_usdt_yeni["saglik"].get("issue_tetikleyen", []),
                                                                    "USDT primi: geçmiş birikmeden (olağan bilinmeden) yanlış alarm verilmez"),
        (_takvim.get("yarin", "").startswith("YARIM") and _takvim.get("tufe") == "2026-11-03" and _takvim.get("ppk") == "2026-12-10"
         and _takvim.get("onceki") == "2026-10-28" and _takvim.get("sonraki") == "2026-10-30" and _takvim.get("tatil29") is False
         and _takvim.get("yarim28") is True and _takvim.get("tufe_ocak") == "2027-01-04" and "13:30" in _takvim.get("not", ""),
                                                                    "Piyasa takvimi: tatil/yarım gün, iş günü sayımı, TÜFE ve PPK tarihleri doğru; yarın yarım günse uyarır"),
        (d_tatil_aksam.get("arsiv") == "saat değil",
                                                                    "Piyasa takvimi: resmi tatil akşamı günlük arşive (bayat veriyle) satır yazılmaz"),
        ("tatiller" in str(d_tatil_ayar["saglik"]["hatali_moduller"].get("ayarlar")),
                                                                    "Piyasa takvimi: hatalı yazılmış tatil kaydı reddedilir ve uyarılır"),
        (isinstance((((d["tetikler"].get("kalibrasyon")) or {}).get("bist_oynaklik") or {}).get("gerceklesen_60g"), (int, float)),
                                                                    "Kalibrasyon: BIST'in gerçekleşen oynaklığı simülasyon varsayımıyla karşılaştırılır"),
        ((lambda y: isinstance(y.get("duzeltme_yillik_puan"), (int, float)) and y.get("uygulandi") is True)
         (((d_kalib["tetikler"].get("kalibrasyon") or {}).get("tahvil_tasima") or {}).get("YOT") or {})
         and "kalibrasyon" in str((((d_kalib.get("tahvil_analiz") or {}).get("fonlar") or {}).get("YOT") or {}).get("senaryo", {}).get("varsayimlar", {}).get("tasima")),
                                                                    "Kalibrasyon: YOT'un gerçekleşen getirisinden taşıma farkı çıkarılır ve senaryoya uygulanır"),
        # --- 20 Eki özel sektör tahvili payı (hata #25) ---
        ((((d_osba_yuksek.get("tetikler") or {}).get("ozel_tahvil") or {}).get("fonlar") or {}).get("YLB", {}).get("durum") == "YÜKSEK PAY"
         and "ozel_tahvil_YLB" in d_osba_yuksek["saglik"].get("issue_tetikleyen", []),
                                                                    "Özel tahvil: para piyasası fonunda şirket tahvili payı %10'u geçince bildirim gelir"),
        ((((d_osba_artis.get("tetikler") or {}).get("ozel_tahvil") or {}).get("fonlar") or {}).get("ZBJ", {}).get("durum") == "HIZLI ARTIŞ"
         and "ozel_tahvil_ZBJ" in d_osba_artis["saglik"].get("issue_tetikleyen", []),
                                                                    "Özel tahvil: pay eşiğin altında olsa da 30 günde ≥5 puan artarsa bildirim gelir"),
        ((((d_osba_eski.get("tetikler") or {}).get("ozel_tahvil") or {}).get("fonlar") or {}).get("ZBJ", {}).get("durum") == "OK"
         and "ozel_tahvil_ZBJ" not in d_osba_eski["saglik"].get("issue_tetikleyen", []),
                                                                    "Özel tahvil: 30 günden eski kayıt artış hesabına girmez (yanlış alarm yok)"),
        ("ozel_tahvil_BGP_yakin" in d_osba_yakin["saglik"]["tum_moduller"]
         and "ozel_tahvil_BGP_yakin" not in d_osba_yakin["saglik"].get("issue_tetikleyen", []),
                                                                    "Özel tahvil: eşiğe yaklaşınca bildirimsiz not düşer"),
        ("IJV" not in ((((d_osba_izleme.get("tetikler") or {}).get("ozel_tahvil") or {}).get("fonlar")) or {})
         and not any(k.startswith("ozel_tahvil_IJV") for k in d_osba_izleme["saglik"].get("issue_tetikleyen", [])),
                                                                    "Özel tahvil: elimizde olmayan ('izleme') fon alarm üretmez"),
        ((((d_osba_artis.get("tetikler") or {}).get("ozel_tahvil") or {}).get("fonlar") or {}).get("ZBJ", {}).get("gozlem_gun") == 1
         and (((d_osba_artis.get("tetikler") or {}).get("ozel_tahvil") or {}).get("fonlar") or {}).get("ZBJ", {}).get("30g_en_dusuk_pct") == 1.0,
                                                                    "Özel tahvil: günlük pay geçmişi tutulur ve gözlem sayısı raporlanır"),
        # --- 19 Eki göreli zarar sınırı (YOT kural revizyonu) ---
        (((d_poz_goreli.get("pozisyon_takip") or {}).get("YOT") or {}).get("durum") == "GÖRELİ ZARAR SINIRI"
         and "pozisyon_YOT" in d_poz_goreli["saglik"].get("issue_tetikleyen", []),
                                                                    "Pozisyon: kıyas fonun 1 puan gerisine düşünce (mutlak sınır aşılmasa da) bildirim gelir"),
        (((d_poz_goreli_yakin.get("pozisyon_takip") or {}).get("YOT") or {}).get("durum") == "İZLEMEDE"
         and "pozisyon_YOT_goreli_yakin" in d_poz_goreli_yakin["saglik"]["tum_moduller"]
         and "pozisyon_YOT_goreli_yakin" not in d_poz_goreli_yakin["saglik"].get("issue_tetikleyen", []),
                                                                    "Pozisyon: göreli sınıra yaklaşınca bildirimsiz erken not düşer"),
        ("pozisyon_kurallari" in str(d_poz_goreli_bozuk["saglik"]["hatali_moduller"].get("ayarlar"))
         and ((d_poz.get("pozisyon_takip") or {}).get("YOT") or {}).get("goreli_sinira_mesafe_puan") is None,
                                                                    "Pozisyon: göreli sınır pozitif yazılırsa reddedilir; yazılmazsa eski davranış sürer"),
        # --- 7 Eki tahvil rolü ve pozisyon kuralları ---
        ((d_poz.get("pozisyon_takip") or {}).get("YOT", {}).get("durum") == "İZLEMEDE"
         and isinstance((d_poz.get("pozisyon_takip") or {}).get("YOT", {}).get("fark_puan"), (int, float)),
                                                                    "Pozisyon: YOT alıştan bu yana getiri ve kıyas fona fark izlenir"),
        ("YOT" in d_poz["tetikler"].get("reel_getiri_tahvil", {}) and "YOT" not in d_poz["tetikler"].get("reel_getiri", {}),
                                                                    "Tahvil rolü: para piyasası alarmlarına karışmaz, bilgi olarak izlenir"),
        ((d_poz_zarar.get("pozisyon_takip") or {}).get("YOT", {}).get("durum") == "ZARAR SINIRI"
         and "pozisyon_YOT" in d_poz_zarar["saglik"].get("issue_tetikleyen", []),
                                                                    "Pozisyon: zarar sınırı aşılınca bildirim gelir"),
        ((d_poz_bekl.get("pozisyon_takip") or {}).get("YOT", {}).get("durum") == "BEKLİYOR",
                                                                    "Pozisyon: alım henüz fiyatlanmadıysa 'bekliyor' der, hata vermez"),
        ("pozisyon_kurallari" in str(d_poz_gecersiz["saglik"]["hatali_moduller"].get("ayarlar")),
                                                                    "Pozisyon: eksik yazılmış kural reddedilir ve uyarılır"),
        # --- 6 Eki Fonoloji hız sınırı ---
        ((d_429.get("fonoloji_cagri") or {}).get("limit_429", 0) >= 3 and bool(d_429.get("fonlar", {}).get("YLB")),
                                                                    "Hız sınırı: 429'da bekleyip yeniden dener, veri eksiksiz gelir"),
        (not any(v.get("fonoloji_denendi") for v in _k429.values()), "Hız sınırı: engellenen fonlar 'Fonoloji vermiyor' diye işaretlenmez"),
        ("kunye_hiz_siniri" in d_429k["saglik"]["tum_moduller"],    "Hız sınırı: künye turu durdurulup sebebi raporlanır"),
        ("kunye_hiz_siniri" not in d_429k["saglik"].get("issue_tetikleyen", []), "Hız sınırı: kendi kendini onaran durum bildirim üretmez"),
        ("kamu_payi" in (kunye_sonra.get("OS0") or {}),             "Onarım: yanlışlıkla 'Fonoloji vermiyor' işaretlenen künye yeniden denenir"),
        # --- 6 Eki ayar dosyası (parametrik yapı) ---
        (str(d.get("ayarlar", {}).get("kaynak", "")).startswith("varsayılan"), "Ayarlar: dosya yoksa varsayılanlarla çalışır"),
        ("BGP" in T["reel_getiri"] and "DLY" not in T["reel_getiri"], "Ayarlar: BGP portföyde (cephane), DLY sadece izlemede"),
        (set(d_ayar_ozel["tetikler"].get("reel_getiri", {})) == {"YLB", "XYZ"}, "Ayarlar: fon listesi koddan değil dosyadan gelir"),
        (d_ayar_ozel["tetikler"].get("politika_faizi") == 35.0 and d_ayar_ozel["saglik"]["tum_moduller"].get("ayarlar") == "OK",
                                                                    "Ayarlar: politika faizi dosyadan güncellenir"),
        ("UYARI" in str(d_ayar_bozuk["saglik"]["hatali_moduller"].get("ayarlar")) and "BGP" in d_ayar_bozuk["tetikler"].get("reel_getiri", {}),
                                                                    "Ayarlar: bozuk dosyada çökmez, uyarır, varsayılana döner"),
        ("fonlar" in str(d_ayar_gecersiz["saglik"]["hatali_moduller"].get("ayarlar")) and "stopaj" in str(d_ayar_gecersiz["saglik"]["hatali_moduller"].get("ayarlar"))
         and "BGP" in d_ayar_gecersiz["tetikler"].get("reel_getiri", {}),
                                                                    "Ayarlar: geçersiz alanlar tek tek reddedilir, varsayılan kullanılır"),
        # --- 6 Eki sertleştirme ---
        ("yedek_borsapy_fon_YLB" in d_yedek["saglik"]["hatali_moduller"] and "fon_YLB" not in d_yedek["saglik"]["hatali_moduller"],
                                                                    "Yedek: birincil çalışınca TEFAS hatası 'yedek' olarak sınıflanır"),
        (not any(k.startswith("yedek_") for k in d_yedek["saglik"].get("issue_tetikleyen", [])),
                                                                    "Yedek: yedek kaynak hatası telefona bildirim (Issue) üretmez"),
        (bool(d_yedek.get("fonlar", {}).get("YLB")),                "Yedek: TEFAS çalışmasa da fon fiyatı Fonoloji'den gelir"),
        ("kamu_payi" in (kunye_sonra.get("PB1") or {}),             "Künye: TEFAS'tan gelmiş portföysüz künye Fonoloji'den yeniden denenir"),
        ("sektor_akis_para_piyasasi" in d_yedek["saglik"]["hatali_moduller"], "Sektör referansı hesaplanamazsa sebebiyle uyarı verir (hata yutulmaz)"),
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
        ("fona özgü" in str(T.get("fon_kitlesel_cikis_alarm", {}).get("BGP", {}).get("tur", "")),
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
