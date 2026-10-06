#!/usr/bin/env python3
"""
BIST RADAR v3 — borsapy (birincil) + Yahoo (yedek)
Piyasa verisi üretir → output/radar.json. KİŞİSEL VERİ (pay adedi, tutar) İÇERMEZ.
Her modül ayrı denenir; kırılan modül "saglik" bölümüne yazılır,
iş akışı bunu GitHub Issue olarak açar (e-posta bildirimi).
"""
import json, math, os, socket
from datetime import datetime, timezone, timedelta
socket.setdefaulttimeout(60)   # 3 Eki: cevap vermeyen kaynak betiği sonsuza kadar bekletmesin
import numpy as np
import pandas as pd

TR_TZ = timezone(timedelta(hours=3))
NOW = datetime.now(TR_TZ)
if os.environ.get("RADAR_TEST_NOW"):     # SADECE testler için: günün farklı saatlerini canlandırmak
    NOW = datetime.strptime(os.environ["RADAR_TEST_NOW"], "%Y-%m-%d %H:%M").replace(tzinfo=TR_TZ)
OUT = "output/radar.json"
YAB_HIST = "output/yabanci_gecmis.json"
TICKERS_FILE = "tickers.txt"

# ---- SİSTEM AYARLARI (ana kayıttan; değişince güncelle) -------------------
LEVELS = {"korunan_taban": 13000, "tez_cizgisi_haftalik": 12600}
FUNDS = ["YLB", "IJV", "DLY", "ZBJ", "TIE", "AKU"]   # portföydeki fonlar (30 Eyl: ZBJ eklendi)
CEPHANE = ["YLB", "IJV", "DLY", "ZBJ"]               # reel getiri kuralı SADECE bunlara
STOPAJ_PP = 0.175          # para piyasası fonu stopajı (kârdan). Değişirse güncelle.
REEL_ALARM, REEL_ACIL = 0.5, 0.0   # NET reel getiri eşikleri (aylık %)
TUFE_AYLIK_MANUEL = 1.84   # otomatik alınamazsa kullanılır (Ağustos 2026)
# Politika faizi yılda 8 kez değişir → PPK sonrası BURAYI güncelle
POLITIKA_FAIZI = {"oran": 37.0, "karar_tarihi": "2026-09-10", "sonraki_ppk": "2026-10-22"}
NASDAQ_ESIK, ALTIN_ESIK = -15.0, -5.0
SEKTOR = ["XBANK", "XUSIN", "XHOLD", "XUTEK", "XUMAL"]
YAHOO_INDEX = {"XU100": "XU100.IS", "XU030": "XU030.IS", "XBANK": "XBANK.IS", "XUSIN": "XUSIN.IS"}
KURESEL = {"brent_yahoo": "BZ=F",   # 3 Eki: sadece borsapy BRENT ile çapraz kontrol için
           "sp500": "^GSPC", "nasdaq": "^IXIC", "vix": "^VIX",
           "dolar_endeksi": "DX-Y.NYB", "abd_10y": "^TNX", "ons_altin": "GC=F"}
# Brent Yahoo'dan ALINMAZ: vade geçişinde sahte düşüş gösterdi (21 Eyl). borsapy BRENT kullanılır.
FX_LIST = ["USD", "EUR", "gram-altin", "ceyrek-altin", "yarim-altin", "tam-altin", "BRENT"]  # ons-altin çıkarıldı: borsapy anlamsız değer veriyordu

# ---- SAĞLIK TAKİBİ --------------------------------------------------------
HEALTH = {}
def _gizle(metin):
    """Hata mesajlarında gizli anahtar değerlerini maskeler (depo ve Issue'lar herkese açık)."""
    metin = str(metin)
    for ad in ("FONOLOJI_KEY", "EVDS_API_KEY", "GH_TOKEN", "GITHUB_TOKEN"):
        v = os.environ.get(ad) or ""
        if len(v) >= 6:
            metin = metin.replace(v, "***")
    return metin

def safe(name, fn):
    try:
        r = fn()
        HEALTH[name] = "OK"
        return r
    except Exception as e:
        HEALTH[name] = _gizle(f"HATA: {type(e).__name__}: {str(e)[:200]}")
        return None

try:
    import borsapy as bp
    HEALTH["borsapy_import"] = "OK"
except Exception as e:
    bp = None
    HEALTH["borsapy_import"] = f"HATA: {e}"
try:
    import yfinance as yf
    HEALTH["yfinance_import"] = "OK"
except Exception as e:
    yf = None
    HEALTH["yfinance_import"] = f"HATA: {e}"

# ---- YARDIMCILAR ----------------------------------------------------------
def J(x):
    """Her şeyi JSON'a uygun hale getirir."""
    if x is None or isinstance(x, str):
        return x
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        x = float(x)
        return None if (math.isnan(x) or math.isinf(x)) else round(x, 4)
    if isinstance(x, (pd.Timestamp, datetime)):
        return x.isoformat()
    if isinstance(x, dict):
        return {str(k): J(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [J(v) for v in x]
    if isinstance(x, pd.Series):
        return J(x.to_dict())
    if isinstance(x, pd.DataFrame):
        return J(x.reset_index().to_dict(orient="records"))
    try:
        return str(x)
    except Exception:
        return None

def pct(a, b):
    try:
        return round((float(a) / float(b) - 1) * 100, 2)
    except Exception:
        return None

def to_dt_index(df):
    if not isinstance(df.index, pd.DatetimeIndex):
        for c in df.columns:
            if str(c).lower() in ("date", "tarih", "datetime", "timestamp", "time"):
                df = df.set_index(c)
                break
        df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df.sort_index()

def norm_ohlc(df):
    if df is None or len(df) == 0:
        raise ValueError("boş veri")
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns={c: str(c).capitalize() for c in df.columns
                            if str(c).lower() in ("open", "high", "low", "close", "volume")})
    if "Close" not in df.columns:
        raise ValueError(f"Close sütunu yok: {list(df.columns)[:8]}")
    return to_dt_index(df).dropna(subset=["Close"])

def rsi(close, p=14):
    if len(close) < p + 1:
        return None
    d = close.diff()
    g = d.clip(lower=0).ewm(alpha=1/p, min_periods=p, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1/p, min_periods=p, adjust=False).mean()
    return J((100 - 100 / (1 + g / l)).iloc[-1])

def atr(df, p=14):
    if not {"High", "Low"} <= set(df.columns) or len(df) < p + 1:
        return None
    pc = df["Close"].shift(1)
    tr = pd.concat([df["High"]-df["Low"], (df["High"]-pc).abs(), (df["Low"]-pc).abs()], axis=1).max(axis=1)
    return J(tr.ewm(alpha=1/p, adjust=False).mean().iloc[-1])

def split_partial(df, bist=True):
    if not bist:
        return df, False
    open_now = NOW.weekday() < 5 and 10 <= NOW.hour and (NOW.hour < 18 or (NOW.hour == 18 and NOW.minute < 15))
    partial = df.index[-1].date() == NOW.date() and open_now
    return (df.iloc[:-1] if partial else df), partial

def summarize(df, src, with_ma=True, bist=True):
    comp, partial = split_partial(df, bist)
    c, cc = df["Close"], comp["Close"]
    out = {"kaynak": src, "son_bar_tarihi": df.index[-1].strftime("%Y-%m-%d"),
           "son_bar_kismi_mi": partial, "son_fiyat": J(c.iloc[-1]),
           "gunluk_degisim_pct": pct(c.iloc[-1], c.iloc[-2]) if len(c) > 1 else None,
           "rsi14_tamamlanmis": rsi(cc), "rsi14_anlik": rsi(c) if partial else None,
           "atr14": atr(comp),
           "52h_zirve_kapanis": J(c.tail(252).max()), "zirveden_pct": pct(c.iloc[-1], c.tail(252).max()),
           "haftalik_degisim_pct": pct(c.iloc[-1], c.iloc[-6]) if len(c) > 6 else None,
           "aylik_degisim_pct": pct(c.iloc[-1], c.iloc[-22]) if len(c) > 22 else None}
    if "Low" in df.columns:
        out["gun_ici_dusuk"], out["gun_ici_yuksek"] = J(df["Low"].iloc[-1]), J(df["High"].iloc[-1])
    if with_ma:
        out["hareketli_ortalamalar"] = {f"{k}{n}": J(v) for n in (5, 10, 20, 50, 100, 200) if len(cc) >= n
                                        for k, v in (("sma", cc.rolling(n).mean().iloc[-1]),
                                                     ("ema", cc.ewm(span=n, adjust=False).mean().iloc[-1]))}
        wk = cc.resample("W-FRI").last().dropna()
        if len(wk) >= 2:
            out["haftalik_kapanis"] = {"son_tamamlanan_hafta": J(wk.iloc[-2]), "bu_hafta_son": J(wk.iloc[-1])}
        if "Volume" in df.columns and df["Volume"].tail(20).sum() > 0:
            v20 = df["Volume"].tail(21).iloc[:-1].mean()
            out["hacim_orani_20g"] = J(df["Volume"].iloc[-1] / v20) if v20 else None
        out["son_5_kapanis"] = [{"t": d.strftime("%Y-%m-%d"), "k": J(v)} for d, v in c.tail(5).items()]
    return out

def index_block(sym, with_ma=True):
    df = None
    if bp:
        df = safe(f"borsapy_endeks_{sym}", lambda: norm_ohlc(bp.Index(sym).history(period="1y")))
        if df is not None:
            return summarize(df, "borsapy", with_ma)
    ysym = YAHOO_INDEX.get(sym)
    if yf and ysym:
        df = safe(f"yahoo_yedek_{sym}", lambda: norm_ohlc(
            yf.download(ysym, period="400d", interval="1d", auto_adjust=False, progress=False)))
        if df is not None:
            return summarize(df, "yahoo (yedek)", with_ma)
    return {"hata": "veri alınamadı"}

# ---- MODÜLLER -------------------------------------------------------------
def fund_block(code):
    f = bp.Fund(code)
    h = None
    for per in ("3mo", "1mo"):
        try:
            h = f.history(period=per)
            if h is not None and len(h):
                break
        except Exception:
            continue
    if h is None or len(h) == 0:
        raise ValueError("fon geçmişi boş")
    h = to_dt_index(h.copy())
    pc = next((c for c in h.columns if str(c).lower() in ("price", "fiyat", "close")), None)
    if pc is None:
        nums = [c for c in h.columns if pd.api.types.is_numeric_dtype(h[c])]
        pc = nums[0]
    s = pd.to_numeric(h[pc], errors="coerce").dropna()
    s = s[s > 0]                         # TEFAS bazen günün fiyatını 0 yayınlıyor (24 Eyl DLY) → at
    if len(s) >= 2 and abs(s.iloc[-1] / s.iloc[-2] - 1) > 0.15:
        s = s.iloc[:-1]                  # tek günde %15+ sıçrama = veri hatası, son noktayı at
        HEALTH[f"fon_{code}_veri"] = f"UYARI: {code} son fiyatı şüpheli (%15+ günlük değişim), bir önceki gün kullanıldı"
    if s.empty:
        raise ValueError("geçerli fiyat yok")
    last_d = s.index[-1]
    past = s[s.index <= last_d - pd.Timedelta(days=30)]
    trend = {}
    for col, key in (("FundSize", "buyukluk"), ("Investors", "yatirimci")):
        try:
            if col not in h.columns:
                continue
            x = pd.to_numeric(h[col], errors="coerce").dropna()
            x = x[x > 0]
            if x.empty:
                trend[f"{key}_not"] = "veri boş"
                continue
            xp = x[x.index <= x.index[-1] - pd.Timedelta(days=30)]
            trend[f"{key}_son"] = J(x.iloc[-1])
            trend[f"{key}_30g_degisim_pct"] = pct(x.iloc[-1], xp.iloc[-1]) if len(xp) else None
        except Exception as ex:
            trend[f"{key}_hata"] = str(ex)[:80]
    out_trend = trend
    out = {"fiyat": J(s.iloc[-1]), "fiyat_tarihi": last_d.strftime("%Y-%m-%d"), "akis": out_trend,
           "gunluk_getiri_pct": pct(s.iloc[-1], s.iloc[-2]) if len(s) > 1 else None,
           "getiri_30g_pct": pct(s.iloc[-1], past.iloc[-1]) if len(past) else None}
    info = safe(f"fon_bilgi_{code}", lambda: f.info) or {}
    keep = ("name", "fund_name", "title", "category", "category_rank", "daily_return",
            "buy_valor", "sell_valor", "risk", "risk_value", "fund_size", "investor_count")
    out["bilgi"] = J({k: v for k, v in info.items() if k in keep}) if isinstance(info, dict) else None
    out["yonetim_ucreti"] = J(safe(f"fon_ucret_{code}", lambda: f.management_fee))
    return out

def breadth_and_foreign():
    comps = bp.Index("XU030").component_symbols
    if not comps:
        raise ValueError("BIST 30 bileşenleri boş")
    up = down = ld = lu = 0
    detail, foreign, fails = {}, {}, 0
    for s in comps:
        try:
            t = bp.Ticker(s)
            h = norm_ohlc(t.history(period="1ay"))
            chg = pct(h["Close"].iloc[-1], h["Close"].iloc[-2])
            detail[s] = chg
            up += chg > 0; down += chg < 0; ld += chg <= -9.5; lu += chg >= 9.5
            try:
                fr = t.fast_info["foreign_ratio"]
                if fr is not None:
                    foreign[s] = float(fr)
            except Exception:
                pass
        except Exception:
            fails += 1
    if fails > len(comps) / 2:
        raise ValueError(f"{fails}/{len(comps)} hisse alınamadı")
    n = len(detail)
    return {"kaynak": "borsapy", "hisse_sayisi": n, "yukselen": int(up), "dusen": int(down),
            "tabana_kilitli": int(ld), "tavana_kilitli": int(lu),
            "yukselen_orani_pct": round(up / n * 100, 1) if n else None,
            "alinamayan": fails, "detay": detail}, foreign

def breadth_scan(index_code="XUTUM", min_rows=100):
    """Tek sorguda genişlik. XUTUM = ordu (tüm piyasa), XU030 = generaller."""
    df = bp.scan(index_code, "change_percent > -100", limit=800)
    col = next((c for c in df.columns if "change" in str(c).lower()), None)
    if col is None or len(df) < min_rows:
        raise ValueError(f"tarama eksik: {len(df)} satır, sütunlar {list(df.columns)[:6]}")
    ch = pd.to_numeric(df[col], errors="coerce").dropna()
    return {"kaynak": f"borsapy scan ({index_code})", "hisse_sayisi": int(len(ch)),
            "yukselen": int((ch > 0).sum()), "dusen": int((ch < 0).sum()),
            "tabana_kilitli": int((ch <= -9.5).sum()), "tavana_kilitli": int((ch >= 9.5).sum()),
            "yukselen_orani_pct": round(float((ch > 0).mean() * 100), 1),
            "medyan_degisim_pct": round(float(ch.median()), 2)}


def foreign_ratios():
    import time
    comps = bp.Index("XU030").component_symbols
    out, fails = {}, 0
    for sym in comps:
        try:
            fr = bp.Ticker(sym).fast_info["foreign_ratio"]
            if fr is not None:
                out[sym] = float(fr)
        except Exception:
            fails += 1
        time.sleep(0.4)   # kaynağı yormamak için
    if fails > len(comps) / 2:
        raise ValueError(f"{fails}/{len(comps)} yabancı oranı alınamadı")
    return out


def breadth_yahoo():
    with open(TICKERS_FILE, encoding="utf-8") as f:
        ts = [t.strip() for t in f if t.strip() and not t.startswith("#")]
    df = yf.download(ts, period="10d", interval="1d", auto_adjust=False, progress=False, group_by="ticker")
    up = down = ld = 0; det = {}
    for t in ts:
        try:
            c = df[t]["Close"].dropna(); ch = pct(c.iloc[-1], c.iloc[-2])
            det[t] = ch; up += ch > 0; down += ch < 0; ld += ch <= -9.5
        except Exception:
            pass
    n = len(det)
    return {"kaynak": "yahoo (yedek)", "hisse_sayisi": n, "yukselen": int(up), "dusen": int(down),
            "tabana_kilitli": int(ld), "yukselen_orani_pct": round(up / n * 100, 1) if n else None}

def foreign_trend(today):
    hist = {}
    if os.path.exists(YAB_HIST):
        try:
            hist = json.load(open(YAB_HIST, encoding="utf-8"))
        except Exception:
            hist = {}
    key = NOW.strftime("%Y-%m-%d")
    hist[key] = today
    hist = dict(sorted(hist.items())[-40:])
    os.makedirs("output", exist_ok=True)
    json.dump(hist, open(YAB_HIST, "w", encoding="utf-8"), ensure_ascii=False)
    dates = sorted(hist)
    def avg(d):
        v = list(hist[d].values()); return sum(v) / len(v) if v else None
    res = {"bugun_ort_yabanci_orani": J(avg(key)), "gecmis_gun_sayisi": len(dates)}
    old = [d for d in dates if d <= (NOW - timedelta(days=7)).strftime("%Y-%m-%d")]
    if old:
        a, b = avg(key), avg(old[-1])
        res["1hafta_degisim_puan"] = J(a - b) if a is not None and b is not None else None
        common = set(hist[key]) & set(hist[old[-1]])
        ch = {s: round(hist[key][s] - hist[old[-1]][s], 2) for s in common}
        res["en_cok_artan"] = dict(sorted(ch.items(), key=lambda x: -x[1])[:5])
        res["en_cok_azalan"] = dict(sorted(ch.items(), key=lambda x: x[1])[:5])
    else:
        res["not"] = "1 haftalık geçmiş birikiyor"
    return res

def tcmb_block():
    """borsapy.TCMB() yanlış okuyor (7,0) → kullanılmıyor. Manuel politika faizi + EVDS AOFM."""
    out = {"politika_faizi": {**POLITIKA_FAIZI, "kaynak": "MANUEL (PPK sonrası güncellenir)"}}
    try:
        days = (datetime.strptime(POLITIKA_FAIZI["sonraki_ppk"], "%Y-%m-%d").date() - NOW.date()).days
        out["ppk_kalan_gun"] = days
        if days < 0:
            HEALTH["politika_faizi_guncelle"] = (f"UYARI: {POLITIKA_FAIZI['sonraki_ppk']} PPK geçti; "
                                                  "betikteki POLITIKA_FAIZI güncellenmeli.")
    except Exception:
        pass
    if not os.environ.get("EVDS_API_KEY"):
        out["aofm"] = {"not": "EVDS_API_KEY tanımlı değil — fiili fonlama maliyeti alınmıyor"}
        return out
    def _aofm():
        ev = bp.evds_series("TP.APIFON4", period="3mo", frequency="daily")   # frekans açıkça (22 Eyl dersi)
        df = ev.to_frame() if isinstance(ev, pd.Series) else ev
        df = to_dt_index(df.copy())
        num = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        s_ = df[num[0]].dropna()
        val = float(s_.iloc[-1])
        if not 15 <= val <= 70:
            raise ValueError(f"makul olmayan değer {val}")
        prev30 = s_[s_.index <= s_.index[-1] - pd.Timedelta(days=30)]
        return {"oran": round(val, 2), "tarih": s_.index[-1].strftime("%Y-%m-%d"),
                "30g_once": round(float(prev30.iloc[-1]), 2) if len(prev30) else None,
                "kaynak": "TCMB EVDS (TP.APIFON4)"}
    out["aofm"] = safe("evds_aofm", _aofm) or {"hata": "alınamadı"}
    return out


KESIF_FILE = "output/evds_kesif.json"
KESIF_TERIMLER = {
    "yabanci_hisse_islemleri": "yurt dışı yerleşiklerin hisse senedi",
    "yabanci_menkul_kiymet": "yurt dışı yerleşikler menkul kıymet",
    "rezerv": "rezerv varlıklar",
    "brut_rezerv": "brüt rezerv",
    "piyasa_katilimcilari_anketi": "piyasa katılımcıları anketi",
    "beklenti_enflasyon": "12 ay sonrası TÜFE beklentisi",
    "beklenti_kur": "12 ay sonrası döviz kuru beklentisi",
    "mevduat_faizi": "mevduat faiz oranları",
    "tufe": "tüketici fiyat endeksi",
}

def evds_kesif():
    """Bir kerelik: EVDS'de arama yapıp seri kodlarını dosyaya yazar. Dosya varsa çalışmaz.
    Tekrar çalıştırmak için depodan output/evds_kesif.json silinir."""
    if os.path.exists(KESIF_FILE):
        return "zaten var"
    out = {"zaman": NOW.strftime("%Y-%m-%d %H:%M")}
    for ad, terim in KESIF_TERIMLER.items():
        try:
            df = bp.evds_search(terim)
            out[ad] = {"terim": terim, "sonuc": J(df.head(20)) if hasattr(df, "head") else J(df)}
        except Exception as e:
            out[ad] = {"terim": terim, "hata": f"{type(e).__name__}: {str(e)[:150]}"}
    os.makedirs("output", exist_ok=True)
    json.dump(out, open(KESIF_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return "yazıldı"


KESIF2_FILE = "output/evds_kesif2.json"
KESIF2_GRUPLAR = {                      # 1. keşifte bulunan grupların içini aç
    "yabanci_portfoy": "bie_mknethar",
    "mevduat_faizi_akim": "bie_mt100h",
    "tufe_2025": "bie_tukfiy2025",
}
KESIF2_TERIMLER = {                     # 1. keşifte bulunamayanlar, farklı kelimelerle
    "haftalik_rezerv": "haftalık rezerv",
    "brut_doviz_rezervi": "brüt döviz rezervleri",
    "uluslararasi_rezervler": "uluslararası rezervler",
    "katilimci": "piyasa katılımcıları",
    "beklenti_anketi": "beklenti anketi",
    "enflasyon_beklentisi": "enflasyon beklentisi",
    "kur_beklentisi": "döviz kuru beklentisi",
}

def evds_kesif2():
    """2. keşif, bir kerelik. Dosya varsa çalışmaz."""
    if os.path.exists(KESIF2_FILE):
        return "zaten var"
    e = bp.EVDS()
    out = {"zaman": NOW.strftime("%Y-%m-%d %H:%M")}
    for ad, grup in KESIF2_GRUPLAR.items():
        try:
            out["grup_" + ad] = {"grup": grup, "seriler": J(e.series_in_group(grup).head(80))}
        except Exception as ex:
            out["grup_" + ad] = {"grup": grup, "hata": f"{type(ex).__name__}: {str(ex)[:150]}"}
    for ad, terim in KESIF2_TERIMLER.items():
        try:
            out["ara_" + ad] = {"terim": terim, "sonuc": J(bp.evds_search(terim).head(25))}
        except Exception as ex:
            out["ara_" + ad] = {"terim": terim, "hata": f"{type(ex).__name__}: {str(ex)[:150]}"}
    try:
        dg = e.datagroups()
        mask = dg.astype(str).apply(
            lambda r: r.str.contains("Katılımcı|Beklenti|Rezerv", case=False, regex=True)).any(axis=1)
        out["veri_gruplari_filtre"] = J(dg[mask].head(80))
    except Exception as ex:
        out["veri_gruplari_filtre"] = {"hata": f"{type(ex).__name__}: {str(ex)[:150]}"}
    os.makedirs("output", exist_ok=True)
    json.dump(out, open(KESIF2_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return "yazıldı"


EVDS_SERILER = {   # 22 Eyl keşfiyle doğrulandı — (kod, frekans). Frekans AÇIKÇA verilir:
    # verilmezse borsapy haftalık serileri aylık ortalamaya çeviriyor (22 Eyl hatası).
    "yabanci_hisse_net_haftalik": ("TP.MKNETHAR.M7", "weekly"),
    "yabanci_dibs_net_haftalik": ("TP.MKNETHAR.M8", "weekly"),
    "mevduat_tl_1ay": ("TP.TRY.MT01", "weekly"),
    "mevduat_tl_3ay": ("TP.TRY.MT02", "weekly"),
    "tufe_endeks": ("TP.TUKFIY2025.GENEL", "monthly"),
    "pka_12ay_enflasyon": ("TP.ENFBEK.PKA12ENF", "monthly"),
    "brut_doviz_rezerv": ("TP.AB.N07", "weekly"),
    "net_uluslararasi_rezerv": ("TP.AB.N06", "weekly"),
}
EVDS_ESKI_ESIK = {"haftalik": 21, "aylik": 70}   # bu kadar gün yeni veri yoksa uyarı

def _evds_frame(code, yil=2, freq=None):
    start = (NOW - timedelta(days=365 * yil)).strftime("%Y-%m-%d")
    df = bp.evds_series(code, start=start, frequency=freq) if freq else bp.evds_series(code, start=start)
    df = df.to_frame() if isinstance(df, pd.Series) else df
    df = to_dt_index(df.copy())
    num = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if not num:
        raise ValueError(f"{code}: sayısal sütun yok {list(df.columns)[:5]}")
    ser = df[num[0]].dropna()
    if ser.empty:
        raise ValueError(f"{code}: boş seri")
    return ser

def _ozet(ser, n=6):
    return {"son": J(ser.iloc[-1]), "tarih": ser.index[-1].strftime("%Y-%m-%d"),
            "onceki": J(ser.iloc[-2]) if len(ser) > 1 else None,
            "veri_yasi_gun": (NOW.date() - ser.index[-1].date()).days,
            "son_gozlemler": [{"t": d.strftime("%Y-%m-%d"), "v": J(v)} for d, v in ser.tail(n).items()]}

def pka_faiz_beklentisi():
    """Piyasa katılımcılarının politika faizi beklentisi (grup içinden adla; seçimi doğrulama için yazar)."""
    e = bp.EVDS()
    adaylar = []
    for grp in ("bie_pkauo", "bie_urbek"):
        try:
            df = e.series_in_group(grp)
        except Exception:
            continue
        nc = next(c for c in df.columns if str(c).upper() == "SERIE_NAME")
        cc = next(c for c in df.columns if str(c).upper() == "SERIE_CODE")
        fz = df[df[nc].astype(str).str.contains("politika faiz|repo", case=False, regex=True)]
        adaylar += [f"{r[cc]} | {r[nc]}" for _, r in fz.head(12).iterrows()]
        sec = fz[fz[nc].astype(str).str.contains("12 ay|yıl sonu|yil sonu", case=False, regex=True)]
        if len(sec):
            row = sec.iloc[0]
            ser = _evds_frame(row[cc], freq="monthly")
            return {"kod": row[cc], "ad": row[nc], **_ozet(ser), "adaylar": adaylar}
    raise ValueError("politika faizi beklentisi bulunamadı; adaylar: " + "; ".join(adaylar[:8]))

def pka_kur_beklentisi():
    """Kur beklentisi serisini grup içinden adla bulur; seçimi ve adayları yazar (doğrulama için)."""
    e = bp.EVDS()
    adaylar_tum = []
    for grp in ("bie_pkauo", "bie_urbek"):
        try:
            df = e.series_in_group(grp)
        except Exception:
            continue
        nc = next(c for c in df.columns if str(c).upper() == "SERIE_NAME")
        cc = next(c for c in df.columns if str(c).upper() == "SERIE_CODE")
        kur = df[df[nc].astype(str).str.contains("kur|dolar|USD", case=False, regex=True)]
        adaylar_tum += [f"{r[cc]} | {r[nc]}" for _, r in kur.head(12).iterrows()]
        sec = kur[kur[nc].astype(str).str.contains("12 ay", case=False)]
        if len(sec):
            row = sec.iloc[0]
            ser = _evds_frame(row[cc], freq="monthly")
            return {"kod": row[cc], "ad": row[nc], "grup": grp, **_ozet(ser), "adaylar": adaylar_tum}
    raise ValueError("12 ay kur beklentisi bulunamadı; adaylar: " + "; ".join(adaylar_tum[:8]))

def evds_resmi():
    out = {}
    for ad, (code, freq) in EVDS_SERILER.items():
        ser = safe(f"evds_{ad}", lambda code=code, freq=freq: _evds_frame(code, freq=freq))
        if ser is None:
            out[ad] = {"kod": code, "hata": "alınamadı"}
            continue
        o = {"kod": code, **_ozet(ser)}
        if ad == "tufe_endeks" and len(ser) >= 13:
            o["aylik_pct"] = pct(ser.iloc[-1], ser.iloc[-2])
            o["yillik_pct"] = pct(ser.iloc[-1], ser.iloc[-13])
        if "rezerv" in ad and len(ser) >= 5:
            o["4hafta_degisim_pct"] = pct(ser.iloc[-1], ser.iloc[-5])
        if ad.startswith("yabanci_"):
            o["son_4_hafta_toplam"] = J(ser.tail(4).sum())
        esik = EVDS_ESKI_ESIK["aylik"] if ad in ("tufe_endeks", "pka_12ay_enflasyon") else EVDS_ESKI_ESIK["haftalik"]
        if o["veri_yasi_gun"] > esik:
            HEALTH[f"evds_{ad}"] = f"UYARI: son veri {o['veri_yasi_gun']} gün önce ({code}) — seri güncellenmiyor olabilir"
        out[ad] = o
    out["pka_kur_beklentisi"] = safe("evds_pka_kur", pka_kur_beklentisi) or {"hata": "alınamadı"}
    out["pka_faiz_beklentisi"] = safe("evds_pka_faiz", pka_faiz_beklentisi) or {"hata": "alınamadı"}
    return out


# ---- RAKİP FON TARAMASI (28 Eyl) -------------------------------------------
TASFIYE_KURUCULAR = ["TERA", "PUSULA", "HEDEF", "ATLAS", "A1 CAPITAL", "A1 PORTFOY", "PARDUS", "BULLS"]
def _tr_up(x):
    x = str(x).upper()
    for a, b in (("İ", "I"), ("Ş", "S"), ("Ğ", "G"), ("Ü", "U"), ("Ö", "O"), ("Ç", "C")):
        x = x.replace(a, b)
    return x
RAKIP_GRUPLARI = {
    "para_piyasasi": {"bizim": ["YLB", "IJV", "DLY", "ZBJ"],
                      # "SEPET HESAP": bankaya özel, TEFAS'ta işleme kapalı fonlar (29 Eyl ZA2 dersi)
                      "filtre": lambda n: "PARA PIYASASI" in n and "SERBEST" not in n and "SEPET HESAP" not in n and "OZEL FON" not in n,
                      "esik": {"1m": 0.15, "3m": 0.40, "1y": 1.5}, "supheli_1m": 0.6, "supheli_1y": 8.0},
    "bist30_endeks": {"bizim": ["TIE", "AKU"],
                      "filtre": lambda n: "BIST 30" in n and "ENDEKS" in n and "OZEL FON" not in n,
                      "esik": {"1m": 0.0, "3m": 0.5, "1y": 2.0}, "supheli_1m": 3.0, "supheli_1y": 10.0},
    "bist100_endeks": {"bizim": [],
                       "filtre": lambda n: ("BIST 100 ENDEKS" in n or "BIST100 ENDEKS" in n) and "DISI" not in n,
                       "esik": {"1m": 0.0, "3m": 0.5, "1y": 2.0}, "supheli_1m": 3.0, "supheli_1y": 10.0},
}
MIN_FON_BUYUKLUGU = 500_000_000   # aday için asgari büyüklük (likidite)
RAKIP_SURUM = 7                   # yapı değişince artır → ilk çalışmada tarama önbelleği yenilenir
RAKIP_KUNYE_MAX = 60              # grup başına künyesi çekilecek en fazla fon (kota/limit koruması)
RAKIP_ADAY_MAX = 20               # listelenecek en fazla aday (eskiden 3'tü — 29 Eyl kullanıcı talebi)

KUNYE_FILE = "output/fon_kunye.json"      # tüm evren için künye önbelleği
EVREN_CSV = "output/fon_evreni.csv"        # bütün fonlar tek tabloda (analiz için)
KUNYE_TTL_GUN = 7                          # künye bu kadar günden eskiyse yenilenir
KUNYE_GUNLUK_LIMIT = 150                   # bir çalışmada en fazla yenilenecek künye (Fonoloji varken)
KUNYE_GUNLUK_LIMIT_BORSAPY = 40            # Fonoloji yoksa (TEFAS'ı yormamak için)

def _kunye_cek(code):
    """Tek fon künyesi — önce Fonoloji (1 kayıt), yoksa borsapy."""
    if os.environ.get("FONOLOJI_KEY"):
        try:
            yan = fonoloji_get(f"/funds/{code}") or {}
            f = yan.get("fund") or {}
            if f:
                pc = lambda v: J(v * 100) if isinstance(v, (int, float)) else None
                pf = yan.get("portfolio") or {}
                num = lambda k: float(pf.get(k) or 0)
                portfoy = {"portfoy_yok": True} if not pf else {}
                portfoy = portfoy or ({"kamu_payi": round(num("government_bond") + num("treasury_bill"), 2),
                            "ozel_payi": round(num("corporate_bond"), 2), "hisse_payi": round(num("stock"), 2),
                            "nakit_repo_payi": round(num("cash"), 2), "eurobond_payi": round(num("eurobond"), 2),
                            "altin_payi": round(num("gold"), 2), "fon_payi": round(num("fund"), 2)} if pf else {})
                return {**portfoy, "buyukluk": J(f.get("aum")), "yatirimci": J(f.get("investor_count")),
                        "alis_valoru": f.get("buy_valor"), "satis_valoru": f.get("sell_valor"), "risk": f.get("risk_score"),
                        "kurucu": f.get("management_company"), "tefas_durum": f.get("trading_status"),
                        "max_dusus_1y": pc(f.get("max_drawdown_1y")), "reel_getiri_1y": pc(f.get("real_return_1y")),
                        "yonetim_ucreti": f.get("management_fee"), "kunye_kaynak": "fonoloji"}
        except Exception:
            pass
    import time
    bi = bp.Fund(code).info or {}
    time.sleep(0.3)
    return {"buyukluk": J(bi.get("fund_size")), "yatirimci": J(bi.get("investor_count")),
            "satis_valoru": J(bi.get("sell_valor")), "risk": J(bi.get("risk_value")), "kunye_kaynak": "borsapy"}

def _kunye_isaretle(k):
    durum = _tr_up((k or {}).get("tefas_durum") or "")
    k["tefas_kapali"] = bool(durum) and ("KAPAL" in durum or "CLOSED" in durum or "PASIF" in durum)
    k["kucuk"] = bool(k.get("buyukluk")) and k["buyukluk"] < MIN_FON_BUYUKLUGU
    return k

def kunye_onbellek_guncelle(evren_df, oncelikli):
    """Künye önbelleğini yükler; eksik/eskimiş olanlardan günlük limit kadarını yeniler.
    Öncelik: bizim gruplardaki fonlar, sonra 1 yıllık getirisi yüksek olanlar."""
    cache = {}
    if os.path.exists(KUNYE_FILE):
        try:
            cache = json.load(open(KUNYE_FILE, encoding="utf-8"))
        except Exception:
            cache = {}
    bugun = NOW.date()
    fono = bool(os.environ.get("FONOLOJI_KEY"))
    def eski(code):
        e = cache.get(code) or {}
        # 3 Eki: eski kodla çekilmiş, portföy bilgisi olmayan künyeler süresini beklemeden yenilenir
        if fono and e.get("kunye_kaynak") == "fonoloji" and "kamu_payi" not in e and not e.get("portfoy_yok"):
            return True
        # 6 Eki: TEFAS'tan gelmiş (portföysüz) künye → Fonoloji yeniden denenir; kapsamadığı fonlar için 3 günde bir
        if fono and e.get("kunye_kaynak") == "borsapy":
            dn = e.get("fonoloji_denendi")
            if not dn or (bugun - datetime.strptime(dn, "%Y-%m-%d").date()).days >= 3:
                return True
        t = e.get("t")
        return (not t) or (bugun - datetime.strptime(t, "%Y-%m-%d").date()).days >= KUNYE_TTL_GUN
    eksik = [c for c in oncelikli if eski(c) and "kamu_payi" not in (cache.get(c) or {})]
    sirali = list(dict.fromkeys(eksik + list(oncelikli) +
                                list(evren_df.sort_values("return_1y", ascending=False)["fund_code"])))
    limit = KUNYE_GUNLUK_LIMIT if os.environ.get("FONOLOJI_KEY") else KUNYE_GUNLUK_LIMIT_BORSAPY
    yenilenen, hata = 0, 0
    for code in sirali:
        if yenilenen >= limit:
            break
        if not eski(code):
            continue
        try:
            k = _kunye_cek(code)
            k["t"] = bugun.strftime("%Y-%m-%d")
            if fono and k.get("kunye_kaynak") == "borsapy":
                k["fonoloji_denendi"] = k["t"]      # Fonoloji bu fonu vermedi → 3 gün sonra tekrar
            # büyüklük geçmişi: sınıf bazında "para nereye akıyor" hesabı için (son 10 kayıt)
            g = list((cache.get(code) or {}).get("g") or [])
            if k.get("buyukluk"):
                g = [x for x in g if x[0] != k["t"]] + [[k["t"], k["buyukluk"]]]
            k["g"] = g[-10:]
            cache[code] = _kunye_isaretle(k)
            yenilenen += 1
        except Exception:
            hata += 1
            if hata > 25:
                break
    os.makedirs("output", exist_ok=True)
    json.dump(cache, open(KUNYE_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    kapsam = sum(1 for c in evren_df["fund_code"] if c in cache)
    return cache, {"yenilenen": yenilenen, "hata": hata, "kapsam": kapsam, "evren": int(len(evren_df))}

def evren_tablosu(df, cache, supheli_kodlar):
    """Bütün fonlar tek tabloda + kategori özetleri."""
    rows = []
    for _, x in df.iterrows():
        k = cache.get(x["fund_code"]) or {}
        n = x["_n"]
        rows.append({"kod": x["fund_code"], "ad": x["name"], "kategori": x.get("fund_type") or "",
                     "1a": x.get("return_1m"), "3a": x.get("return_3m"), "6a": x.get("return_6m"),
                     "yb": x.get("return_ytd"), "1y": x.get("return_1y"), "3y": x.get("return_3y"),
                     "buyukluk": k.get("buyukluk"), "yatirimci": k.get("yatirimci"), "kurucu": k.get("kurucu"),
                     "satis_valoru": k.get("satis_valoru"), "risk": k.get("risk"),
                     "tasfiye_kurucu": isinstance(x.get("elenen"), str), "nitelikli_serbest": "SERBEST" in n,
                     "sepet": "SEPET HESAP" in n, "ozel_fon": "OZEL FON" in n, "tefas_kapali": bool(k.get("tefas_kapali")),
                     "sinif": _sinif(x["name"], x.get("fund_type") or "", k),
                     "kamu_payi": k.get("kamu_payi"), "ozel_payi": k.get("ozel_payi"), "hisse_payi": k.get("hisse_payi"),
                     "max_dusus_1y": k.get("max_dusus_1y"),
                     "kucuk": bool(k.get("kucuk")), "supheli": x["fund_code"] in supheli_kodlar,
                     "kunye_tarihi": k.get("t")})
    tab = pd.DataFrame(rows)
    os.makedirs("output", exist_ok=True)
    tab.to_csv(EVREN_CSV, index=False)
    temiz = tab[~(tab["tasfiye_kurucu"] | tab["nitelikli_serbest"] | tab["sepet"] | tab["ozel_fon"] | tab["tefas_kapali"] | tab["supheli"])]
    ozet = {}
    for kat, g in temiz.groupby("kategori"):
        if not kat:
            continue
        uygun = g[~g["kucuk"] & g["buyukluk"].notna()].sort_values("1y", ascending=False)
        ozet[kat] = {"fon_sayisi": int(len(g)),
                     "medyan_1a": J(g["1a"].median()), "medyan_3a": J(g["3a"].median()), "medyan_1y": J(g["1y"].median()),
                     "en_iyi_5_buyuk": J(uygun[["kod", "ad", "1a", "3a", "1y", "buyukluk", "kurucu"]].head(5))}
    return {"toplam_fon": int(len(tab)), "temiz_fon": int(len(temiz)), "kategori_sayisi": len(ozet),
            "kategoriler": ozet, "tablo_dosyasi": EVREN_CSV}


ADAY_IZLEME_FILE = "output/aday_izleme.json"
OLGUNLUK_IS_GUNU = 20            # aday en az bu kadar iş günü görülmeli (~4 hafta)
OLGUNLUK_TAKVIM_GUN = 28         # ve ilk görülmesinin üstünden en az bu kadar gün geçmeli
BASABAS_MAX_GUN = 30             # geçiş maliyeti avantajla en fazla bu kadar günde çıkmalı

def gecis_basabas(bizim, aday, kategori_hisse):
    """Geçişte para kaç gün piyasa dışında kalır, bu maliyeti aday avantajı kaç günde çıkarır."""
    sat = bizim.get("satis_valoru")
    al = aday.get("alis_valoru")
    sat = int(sat) if isinstance(sat, (int, float)) else (2 if kategori_hisse else 0)
    al = int(al) if isinstance(al, (int, float)) else (1 if kategori_hisse else 0)
    # T+0 satışta para genelde öğleden sonra gelir → alım ertesi günün fiyatından: en az 1 gün boşluk
    bosluk = max(1, sat) + (0 if kategori_hisse else 0)
    y_biz = bizim.get("1y")
    fark_1y = aday.get("fark_1y")
    if y_biz is None or not fark_1y or fark_1y <= 0:
        return {"piyasa_disi_gun": bosluk, "basabas_gun": None}
    gunluk_biz = y_biz / 365.0
    gunluk_avantaj = fark_1y / 365.0
    # para piyasasında maliyet = kaçan getiri; hisse fonunda kaçan getiri yerine piyasa riski (gün olarak raporlanır)
    maliyet = bosluk * gunluk_biz if not kategori_hisse else 0.0
    return {"piyasa_disi_gun": bosluk,
            "basabas_gun": round(maliyet / gunluk_avantaj, 1) if gunluk_avantaj > 0 and maliyet > 0 else 0.0}

def aday_izleme_guncelle(rt):
    """Her büyük adayın kaç farklı günde aday olduğunu kaydeder (günde bir kez sayılır)."""
    iz = {}
    if os.path.exists(ADAY_IZLEME_FILE):
        try:
            iz = json.load(open(ADAY_IZLEME_FILE, encoding="utf-8"))
        except Exception:
            iz = {}
    bugun = NOW.strftime("%Y-%m-%d")
    for grup in ("para_piyasasi", "bist30_endeks"):
        for kod, v in ((rt.get(grup) or {}).get("bizim") or {}).items():
            for a in v.get("buyuk_adaylar") or []:
                k = iz.setdefault(kod, {}).setdefault(a["kod"], {"ilk": bugun, "gunler": []})
                if bugun not in k["gunler"]:
                    k["gunler"].append(bugun)
                k["gunler"] = k["gunler"][-80:]
                k["son"] = bugun
                k["son_fark_1y"] = a.get("fark_1y")
    os.makedirs("output", exist_ok=True)
    json.dump(iz, open(ADAY_IZLEME_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    ozet = {}
    for kod, adaylar in iz.items():
        for ak, k in adaylar.items():
            gun_sayisi = len(k["gunler"])
            takvim = (NOW.date() - datetime.strptime(k["ilk"], "%Y-%m-%d").date()).days
            aktif = k.get("son") == bugun
            ozet.setdefault(kod, {})[ak] = {"ilk_goruldu": k["ilk"], "aday_gun_sayisi": gun_sayisi,
                                             "takvim_gun": takvim, "bugun_hala_aday": aktif,
                                             "olgun": bool(aktif and gun_sayisi >= OLGUNLUK_IS_GUNU and takvim >= OLGUNLUK_TAKVIM_GUN),
                                             "son_fark_1y": k.get("son_fark_1y")}
    return ozet


def _kunye(code, cache):
    """Fon künyesi: büyüklük, yatırımcı, valör, kurucu, TEFAS durumu. Önce Fonoloji (1 kayıt), yoksa borsapy."""
    if code in cache:
        return cache[code]
    out = {}
    if os.environ.get("FONOLOJI_KEY"):
        try:
            f = (fonoloji_get(f"/funds/{code}") or {}).get("fund") or {}
            out = {"buyukluk": J(f.get("aum")), "yatirimci": J(f.get("investor_count")),
                   "satis_valoru": f.get("sell_valor"), "risk": f.get("risk_score"),
                   "kurucu": f.get("management_company"), "tefas_durum": f.get("trading_status"), "kunye_kaynak": "fonoloji"}
        except Exception:
            out = {}
    if not out:
        try:
            import time
            bi = bp.Fund(code).info or {}
            out = {"buyukluk": J(bi.get("fund_size")), "yatirimci": J(bi.get("investor_count")),
                   "satis_valoru": J(bi.get("sell_valor")), "risk": J(bi.get("risk_value")), "kunye_kaynak": "borsapy"}
            time.sleep(0.3)
        except Exception:
            out = {"kunye_kaynak": "alınamadı"}
    durum = _tr_up(out.get("tefas_durum") or "")
    out["tefas_kapali"] = bool(durum) and ("KAPAL" in durum or "CLOSED" in durum or "PASIF" in durum)
    out["kucuk"] = bool(out.get("buyukluk")) and out["buyukluk"] < MIN_FON_BUYUKLUGU
    cache[code] = out
    return out

def _fon_evreni_cek():
    """TEFAS fon taraması — sabahları takılabiliyor (6 Eki): 3 deneme, aralarda artan bekleme."""
    import time
    bekle = 0 if (os.environ.get("RADAR_TEST_NOW") or os.environ.get("RADAR_TEST_HIZLI")) else 15
    son_hata = None
    for deneme in range(3):
        try:
            return bp.screen_funds(fund_type="YAT", limit=5000)
        except Exception as e:
            son_hata = e
            time.sleep(bekle * (deneme + 1))
    raise son_hata

def rakip_tarama():
    """TEFAS'taki tüm yatırım fonlarını çekip her fonumuzu kendi grubuyla karşılaştırır."""
    df = _fon_evreni_cek()
    if df is None or len(df) < 50:
        raise ValueError(f"fon evreni eksik: {0 if df is None else len(df)}")
    df = df.copy()
    df["_n"] = df["name"].map(_tr_up)
    df["elenen"] = df["_n"].map(lambda n: next((k for k in TASFIYE_KURUCULAR if k in n), None))
    out = {"evren": int(len(df)), "zaman": NOW.strftime("%Y-%m-%d %H:%M")}
    grup_fonlari = df.loc[df["_n"].map(lambda n: any(g["filtre"](n) for g in RAKIP_GRUPLARI.values())), "fund_code"].tolist()
    oncelikli = []
    # 5 Eki: tahvil kararları için borçlanma ailesi de öncelikli (portföy bilgisi = kamu/özel ayrımı)
    borc_maske = df["_n"].str.contains("BORCLANMA|TAHVIL|BONO|KIRA SERTIFIKA|TUFE|ENFLASYON|EUROBOND", regex=True) & \
                 ~df["_n"].str.contains("SERBEST|OZEL FON|SEPET HESAP", regex=True)
    oncelikli = [c for c in df.loc[borc_maske].sort_values("return_3m", ascending=False)["fund_code"]]
    oncelikli += [c for c in grup_fonlari if c not in oncelikli]   # 6 Eki: tahvil kararı için borçlanma ailesi en önde
    kcache_global, out["kunye_durumu"] = kunye_onbellek_guncelle(df[df["elenen"].isna()], oncelikli)
    supheli_tum = set()
    for grup, g in RAKIP_GRUPLARI.items():
        d = df[df["_n"].map(g["filtre"])].copy()
        if d.empty:
            out[grup] = {"hata": "grup boş"}
            continue
        temiz = d[d["elenen"].isna()]
        med1 = temiz["return_1m"].median()
        med1y = temiz["return_1y"].median()
        # Tera dersi: grubundan kısa VEYA uzun vadede belirgin ayrışan getiri = şüpheli, aday değil
        d["supheli"] = (d["return_1m"] > med1 + g["supheli_1m"]) | (d["return_1y"] > med1y + g.get("supheli_1y", 99))
        aday_havuz = d[d["elenen"].isna() & ~d["supheli"]].copy()
        aday_havuz = aday_havuz.sort_values("return_1y", ascending=False, na_position="last").reset_index(drop=True)
        aday_havuz["sira"] = aday_havuz.index + 1
        cols = ["fund_code", "name", "return_1m", "return_3m", "return_1y"]
        # künye: bizim en zayıf fonumuzdan daha iyi (ya da ona eşit) sıradaki herkes + bizimkiler
        bizim_sira = aday_havuz.loc[aday_havuz["fund_code"].isin(g["bizim"]), "sira"]
        kesme = int(bizim_sira.max()) if len(bizim_sira) else 10
        kunye_kodlari = list(aday_havuz.loc[aday_havuz["sira"] <= kesme, "fund_code"])[:RAKIP_KUNYE_MAX]
        kunye_kodlari += [k for k in g["bizim"] if k not in kunye_kodlari]
        kcache = {c: v for c, v in kcache_global.items()}
        siralama = []
        for _, x in aday_havuz.iterrows():
            row = {"sira": int(x["sira"]), "kod": x["fund_code"], "ad": x["name"],
                   "1a": J(x["return_1m"]), "3a": J(x["return_3m"]), "1y": J(x["return_1y"]),
                   "bizim": x["fund_code"] in g["bizim"]}
            if x["fund_code"] in kcache or x["fund_code"] in kunye_kodlari:
                row.update(_kunye(x["fund_code"], kcache))
            siralama.append(row)
        supheli_tum |= set(d.loc[d["supheli"], "fund_code"])
        res = {"surum": RAKIP_SURUM, "fon_sayisi": int(len(d)), "temiz_havuz": int(len(aday_havuz)),
               "medyan_1m": J(med1), "medyan_1y": J(med1y),
               "elenen_tasfiye": d.loc[d["elenen"].notna(), "fund_code"].tolist(),
               "supheli_yuksek": d.loc[d["supheli"] & d["elenen"].isna(), "fund_code"].tolist(),
               "tefas_kapali": [r["kod"] for r in siralama if r.get("tefas_kapali")],
               "en_iyi_5_1y": J(aday_havuz[cols].head(5)),
               "siralama": siralama, "bizim": {}}
        sira_map = {r["kod"]: r for r in siralama}
        for kod in g["bizim"]:
            r = d[d["fund_code"] == kod]
            if r.empty:
                res["bizim"][kod] = {"hata": "grupta bulunamadı"}
                continue
            r = r.iloc[0]
            e = g["esik"]
            def gecer(x):
                ok = True
                for per, col in (("1m", "return_1m"), ("3m", "return_3m"), ("1y", "return_1y")):
                    if pd.notna(x[col]) and pd.notna(r[col]):
                        ok &= (x[col] - r[col]) >= e[per]
                    elif per != "1y":
                        ok = False
                return bool(ok)
            gecen = aday_havuz[(aday_havuz["fund_code"] != kod) & aday_havuz.apply(gecer, axis=1)].head(RAKIP_ADAY_MAX)
            aday_list = []
            for _, a in gecen.iterrows():
                kun = sira_map.get(a["fund_code"], {})
                if "kunye_kaynak" not in kun:
                    kun = {**kun, **_kunye(a["fund_code"], kcache)}
                item = {"kod": a["fund_code"], "ad": a["name"], "sira": int(a["sira"]),
                        "fark_1m": J(a["return_1m"] - r["return_1m"]) if pd.notna(a["return_1m"]) else None,
                        "fark_3m": J(a["return_3m"] - r["return_3m"]) if pd.notna(a["return_3m"]) else None,
                        "fark_1y": J(a["return_1y"] - r["return_1y"]) if pd.notna(a["return_1y"]) and pd.notna(r["return_1y"]) else None,
                        "buyukluk": kun.get("buyukluk"), "yatirimci": kun.get("yatirimci"),
                        "satis_valoru": kun.get("satis_valoru"), "kurucu": kun.get("kurucu"),
                        "tefas_kapali": kun.get("tefas_kapali"), "kucuk": kun.get("kucuk"),
                        "risk": kun.get("risk"), "max_dusus_1y": kun.get("max_dusus_1y"),
                        "yonetim_ucreti": kun.get("yonetim_ucreti"), "alis_valoru": kun.get("alis_valoru")}
                bizim_kun = {**sira_map.get(kod, {}), "1y": J(r["return_1y"])}
                item.update(gecis_basabas(bizim_kun, item, grup != "para_piyasasi"))
                if kun.get("kucuk"):
                    item["not"] = "küçük fon — likidite riski"
                if kun.get("tefas_kapali"):
                    item["not"] = "TEFAS'ta işleme kapalı"
                aday_list.append(item)
            buyuk = [a for a in aday_list if not a.get("not") and a.get("buyukluk")][:5]
            res["bizim"][kod] = {"return_1m": J(r["return_1m"]), "return_3m": J(r["return_3m"]),
                                 "return_1y": J(r["return_1y"]),
                                 "gruptaki_sira_1y": sira_map.get(kod, {}).get("sira"),
                                 "aday_havuz_sayisi": int(len(aday_havuz)),
                                 "gecis_adaylari": aday_list, "buyuk_adaylar": buyuk}
        out[grup] = res
    # kategori içi şüpheli (Tera dersi) — tüm kategoriler için
    for kat, g in df[df["elenen"].isna()].groupby("fund_type"):
        if len(g) >= 5:
            m1, m1y = g["return_1m"].median(), g["return_1y"].median()
            supheli_tum |= set(g.loc[(g["return_1m"] > m1 + 3 * max(g["return_1m"].std(), 0.2)) |
                                     (g["return_1y"] > m1y + 3 * max(g["return_1y"].std(), 2.0)), "fund_code"])
    out["evren_ozeti"] = evren_tablosu(df, kcache_global, supheli_tum)
    out["aday_izleme"] = aday_izleme_guncelle(out)
    try:
        out["sektor_akis"] = sektor_akis(out, kcache_global)
    except Exception as e:
        out["sektor_akis"] = {"hata": str(e)[:120]}
    try:
        out["tahvil_adaylari"] = tahvil_adaylari(df, kcache_global, supheli_tum)
    except Exception as e:
        out["tahvil_adaylari"] = {"hata": f"{type(e).__name__}: {str(e)[:120]}"}
    try:
        out["varlik_siniflari"] = varlik_siniflari(df, kcache_global, supheli_tum)
    except Exception as e:
        out["varlik_siniflari"] = {"hata": f"{type(e).__name__}: {str(e)[:120]}"}
    return out


# ---- FONOLOJİ (28 Eyl): fonlar için BİRİNCİL kaynak; borsapy çapraz kontrol/yedek --------
FONOLOJI_BASE = "https://fonoloji.com/v1"

FONOLOJI_SAYAC = {"cagri": 0, "limit_429": 0}

def fonoloji_get(path, params=None, timeout=20):
    import requests
    key = os.environ.get("FONOLOJI_KEY")
    FONOLOJI_SAYAC["cagri"] += 1
    if not key:
        raise ValueError("FONOLOJI_KEY tanımlı değil")
    r = requests.get(FONOLOJI_BASE + path, params=params or {}, headers={"X-API-Key": key}, timeout=timeout)
    if r.status_code == 429:
        FONOLOJI_SAYAC["limit_429"] += 1
        raise ValueError(f"Fonoloji kota/limit (429), retry-after={r.headers.get('retry-after')}")
    r.raise_for_status()
    return r.json()

def fonoloji_fund(code):
    """Tek fon: künye + son 1 yıllık fiyat/büyüklük/yatırımcı geçmişi. Kota: 2 kayıt."""
    d = fonoloji_get(f"/funds/{code}")
    f = d.get("fund") or {}
    h = fonoloji_get(f"/funds/{code}/history", {"period": "1y"})
    pts = [p for p in (h.get("points") or []) if p.get("price")]
    if not f.get("current_price") or not pts:
        raise ValueError("fonoloji boş yanıt")
    ser = pd.Series({pd.Timestamp(p["date"]): float(p["price"]) for p in pts}).sort_index()
    aum = pd.Series({pd.Timestamp(p["date"]): p.get("total_value") for p in pts}).dropna().sort_index()
    inv = pd.Series({pd.Timestamp(p["date"]): p.get("investor_count") for p in pts}).dropna().sort_index()
    last_d = ser.index[-1]
    past = ser[ser.index <= last_d - pd.Timedelta(days=30)]
    def chg30(x):
        if not len(x):
            return None
        xp = x[x.index <= x.index[-1] - pd.Timedelta(days=30)]
        return pct(x.iloc[-1], xp.iloc[-1]) if len(xp) else None
    return {"kaynak": "fonoloji",
            "fiyat": J(ser.iloc[-1]), "fiyat_tarihi": last_d.strftime("%Y-%m-%d"),
            "gunluk_getiri_pct": pct(ser.iloc[-1], ser.iloc[-2]) if len(ser) > 1 else None,
            "getiri_30g_pct": pct(ser.iloc[-1], past.iloc[-1]) if len(past) else None,
            "getiri_1y_pct": J(f["return_1y"] * 100) if f.get("return_1y") is not None else None,
            "akis": {"buyukluk_son": J(aum.iloc[-1]) if len(aum) else None,
                     "buyukluk_30g_degisim_pct": chg30(aum),
                     "yatirimci_son": J(inv.iloc[-1]) if len(inv) else None,
                     "yatirimci_30g_degisim_pct": chg30(inv)},
            "bilgi": {"name": f.get("name"), "category": f.get("category"), "risk_value": f.get("risk_score"),
                      "buy_valor": f.get("buy_valor"), "sell_valor": f.get("sell_valor"),
                      "fund_size": f.get("aum"), "investor_count": f.get("investor_count"),
                      "trading_status": f.get("trading_status"), "management_company": f.get("management_company")},
            "portfoy": d.get("portfolio")}

SEKTOR_REFERANS_N = 12          # sektör akışı için en büyük kaç rakip fonun geçmişine bakılır
GORELI_ESIK_BUYUKLUK = 15.0     # fonun 30 günlük büyüklük değişimi sektör ortancasından bu kadar puan kötüyse alarm
GORELI_ESIK_YATIRIMCI = 10.0    # yatırımcı sayısında aynı mantık
MUTLAK_ACIL_ESIK = -50.0        # sektörden bağımsız: büyüklük %50+ erirse her durumda alarm

def _akis30(code):
    """Fonoloji geçmişinden 30 günlük büyüklük ve yatırımcı değişimi (1 kayıt)."""
    h = fonoloji_get(f"/funds/{code}/history", {"period": "1y"})   # 6 Eki: "3m" çalışmıyordu; kendi fonlarımızda çalışan periyot
    pts = h.get("points") or []
    aum = pd.Series({pd.Timestamp(p["date"]): p.get("total_value") for p in pts}).dropna().sort_index()
    inv = pd.Series({pd.Timestamp(p["date"]): p.get("investor_count") for p in pts}).dropna().sort_index()
    def chg(x):
        if len(x) < 2:
            return None
        xp = x[x.index <= x.index[-1] - pd.Timedelta(days=30)]
        return pct(x.iloc[-1], xp.iloc[-1]) if len(xp) else None
    return {"buyukluk_30g": chg(aum), "yatirimci_30g": chg(inv)}

def sektor_akis(rt, kunye):
    """Her grubun en büyük rakiplerinin 30 günlük akış ortancası → 'sektör geneli mi, fona özgü mü?'"""
    if not os.environ.get("FONOLOJI_KEY"):
        return {"not": "FONOLOJI_KEY yok — sektör referansı hesaplanamadı"}
    out = {}
    for grup in ("para_piyasasi", "bist30_endeks"):
        g = rt.get(grup) or {}
        bizim = set((g.get("bizim") or {}).keys())
        adaylar = [r for r in g.get("siralama") or [] if r["kod"] not in bizim and (kunye.get(r["kod"]) or {}).get("buyukluk")]
        adaylar = sorted(adaylar, key=lambda r: -(kunye[r["kod"]]["buyukluk"]))[:SEKTOR_REFERANS_N]
        degerler, hatalar = [], []
        for r in adaylar:
            try:
                degerler.append(_akis30(r["kod"]))
            except Exception as e:
                hatalar.append(f"{r['kod']}: {type(e).__name__}: {str(e)[:80]}")
        if adaylar and not degerler:
            # 6 Eki: hatayı yutma — referans yoksa alarmlar mutlak moda düşer, bunu bilmek gerekir
            HEALTH[f"sektor_akis_{grup}"] = _gizle(f"UYARI: sektör referansı hesaplanamadı ({len(hatalar)} fon), ilk hata: {hatalar[0] if hatalar else '?'}")
        b = [v["buyukluk_30g"] for v in degerler if v["buyukluk_30g"] is not None]
        y = [v["yatirimci_30g"] for v in degerler if v["yatirimci_30g"] is not None]
        out[grup] = {"referans_fon_sayisi": len(degerler), "hata_sayisi": len(hatalar),
                     "medyan_buyukluk_30g": J(float(np.median(b))) if b else None,
                     "medyan_yatirimci_30g": J(float(np.median(y))) if y else None}
    return out


SINIF_IZLEME_FILE = "output/sinif_izleme.json"
SINIF_ESIK_1A, SINIF_ESIK_3A = 0.2, 0.5     # PPF'yi bu kadar puan geçmeli (1 ay VE 3 ay)
SINIF_OLGUNLUK_IS_GUNU = 10                  # ~2 hafta kesintisiz üstünlük

def _sinif(n, kat, kunye=None):
    """Önce fonun GERÇEK portföyü (Fonoloji künyesi), yoksa isim/kategori kuralları."""
    n, kat = _tr_up(n), _tr_up(kat)
    k = kunye or {}
    if "PARA PIYASASI" in kat or "PARA PIYASASI" in n:
        return "Para piyasası"
    hp, kp, op = k.get("hisse_payi"), k.get("kamu_payi"), k.get("ozel_payi")
    if hp is not None and hp >= 50:
        return "BIST endeks hisse" if ("ENDEKS" in n and "DISI" not in n) else "Hisse (aktif)"
    if "ALTIN" in n or "KIYMETLI MADEN" in kat or "GUMUS" in n or (k.get("altin_payi") or 0) >= 50:
        return "Altın / kıymetli maden"
    if "TUFE" in n or "ENFLASYON" in n:
        return "Enflasyona endeksli"
    if "EUROBOND" in n or "DOVIZ" in n or "DOLAR" in n or "YABANCI BORCLANMA" in n or (k.get("eurobond_payi") or 0) >= 50:
        return "Eurobond / döviz"
    if "HISSE" in n or "HISSE" in kat or any(w in n for w in ("ENERJI", "TEKNOLOJI", "BANKACILIK", "SANAYI", "SURDURULEBILIRLIK", "TEMETTU")) and "BORCLANMA" not in n:
        return "BIST endeks hisse" if ("ENDEKS" in n and "DISI" not in n) else "Hisse (aktif)"
    if "KIRA SERTIFIKA" in n:
        return "Kira sertifikası / katılım"
    borc = "BORCLANMA" in kat or "BORCLANMA" in n or "TAHVIL" in n or "BONO" in n
    if borc:
        if "KISA VADE" in n:
            return "Kısa vadeli borçlanma"
        if (op is not None and op >= 40) or "OZEL SEKTOR" in n:
            return "Özel sektör borçlanma"
        if (kp is not None and kp >= 50) or any(w in n for w in ("KAMU", "DIBS", "DEVLET", "HAZINE")):
            return "Kamu borçlanma (devlet tahvili)"
        return "Borçlanma (karma)"
    if "KATILIM" in kat or "KATILIM" in n:
        return "Kira sertifikası / katılım"
    if "KARMA" in kat or "DEGISKEN" in kat:
        return "Karma / değişken"
    return None

def _getiri_serisi(ser):
    ser = ser.dropna()
    if len(ser) < 2:
        return {}
    son, t = ser.iloc[-1], ser.index[-1]
    def onceki(gun):
        x = ser[ser.index <= t - pd.Timedelta(days=gun)]
        return pct(son, x.iloc[-1]) if len(x) else None
    return {"1a": onceki(30), "3a": onceki(91), "1y": onceki(365)}

TAHVIL_KAMU_ESIK = 50.0   # portföyünün en az bu kadarı devlet kâğıdı olan fon "devlet tahvili ağırlıklı"

def tahvil_adaylari(df, kunye, supheli):
    """Devlet tahvili ağırlıklı, büyük, erişilebilir borçlanma fonları + veri kapsamı."""
    d = df[df["elenen"].isna() & ~df["fund_code"].isin(supheli)].copy()
    d = d[~d["_n"].str.contains("SERBEST|SEPET HESAP|OZEL FON|PARA PIYASASI", regex=True)]
    d = d[d["_n"].str.contains("BORCLANMA|TAHVIL|BONO|KIRA SERTIFIKA|TUFE|ENFLASYON", regex=True)]
    aday, bilinmeyen = [], 0
    for _, x in d.iterrows():
        k = kunye.get(x["fund_code"]) or {}
        if k.get("tefas_kapali"):
            continue
        if "kamu_payi" not in k:
            bilinmeyen += 1
            continue
        if (k.get("kamu_payi") or 0) < TAHVIL_KAMU_ESIK or (k.get("buyukluk") or 0) < MIN_FON_BUYUKLUGU:
            continue
        n = x["_n"]
        vade = "uzun" if "UZUN VADE" in n else ("kısa" if "KISA VADE" in n else "orta/belirsiz")
        tur = "enflasyona endeksli" if ("TUFE" in n or "ENFLASYON" in n) else ("kira sertifikası" if "KIRA" in n else "sabit/karma")
        aday.append({"kod": x["fund_code"], "ad": x["name"], "vade_ipucu": vade, "tur": tur,
                     "kamu_payi": k.get("kamu_payi"), "ozel_payi": k.get("ozel_payi"), "nakit_repo_payi": k.get("nakit_repo_payi"),
                     "buyukluk": k.get("buyukluk"), "yatirimci": k.get("yatirimci"), "kurucu": k.get("kurucu"),
                     "satis_valoru": k.get("satis_valoru"), "risk": k.get("risk"), "max_dusus_1y": k.get("max_dusus_1y"),
                     "1a": J(x.get("return_1m")), "3a": J(x.get("return_3m")), "1y": J(x.get("return_1y"))})
    aday.sort(key=lambda a: (-(a["kamu_payi"] or 0), -(a["buyukluk"] or 0)))
    return {"esik_kamu_payi": TAHVIL_KAMU_ESIK, "aday_sayisi": len(aday), "adaylar": aday[:25],
            "portfoyu_bilinmeyen_borclanma_fonu": bilinmeyen,
            "not": "Portföyü bilinmeyen fonlar künye yenilendikçe değerlendirmeye girer."}


def varlik_siniflari(df, kunye, supheli):
    """Paranın gidebileceği her yer aynı panoda: fon sınıfları + mevduat, dolar, gram altın."""
    d = df[df["elenen"].isna()].copy()
    d = d[~d["_n"].str.contains("SERBEST|SEPET HESAP|OZEL FON", regex=True) & ~d["fund_code"].isin(supheli)]
    d = d[~d["fund_code"].map(lambda c: bool((kunye.get(c) or {}).get("tefas_kapali")))]
    d["sinif"] = [_sinif(n, kt, kunye.get(c)) for n, kt, c in
                  zip(d["name"], d.get("fund_type", pd.Series([""] * len(d))).fillna(""), d["fund_code"])]
    d = d[d["sinif"].notna()]
    siniflar = {}
    for snf, g in d.groupby("sinif"):
        buyuk = g[g["fund_code"].map(lambda c: (kunye.get(c) or {}).get("buyukluk") or 0) >= MIN_FON_BUYUKLUGU]
        # sınıf riski: künyesi bilinenlerin 1 yıllık en derin düşüş ortancası
        dd = [kunye[c]["max_dusus_1y"] for c in g["fund_code"] if (kunye.get(c) or {}).get("max_dusus_1y") is not None]
        # sınıf para akışı: ~30 gün önceki büyüklükle karşılaştırılabilen fonların toplamı
        simdi = once = 0.0; n_akis = 0
        sinir = (NOW.date() - timedelta(days=25)).strftime("%Y-%m-%d")
        for c in g["fund_code"]:
            gg = (kunye.get(c) or {}).get("g") or []
            eski = [x for x in gg if x[0] <= sinir]
            if gg and eski:
                simdi += gg[-1][1]; once += eski[-1][1]; n_akis += 1
        siniflar[snf] = {"fon_sayisi": int(len(g)), "buyuk_fon_sayisi": int(len(buyuk)),
                         "medyan_max_dusus_1y": J(float(np.median(dd))) if dd else None,
                         "akis_30g_pct": pct(simdi, once) if once else None, "akis_kapsam": n_akis,
                         "1a": J(g["return_1m"].median()), "3a": J(g["return_3m"].median()), "1y": J(g["return_1y"].median()),
                         "en_iyi_3_buyuk": J(buyuk.sort_values("return_3m", ascending=False)[["fund_code", "name", "return_1m", "return_3m", "return_1y"]].head(3))}
    # fon dışı karşılaştırmalar
    disari = {}
    try:
        disari["Gram altın (fiziki)"] = _getiri_serisi(norm_ohlc(bp.FX("gram-altin").history(period="1y"))["Close"])
    except Exception as e:
        disari["Gram altın (fiziki)"] = {"hata": str(e)[:60]}
    try:
        disari["Dolar (USD/TRY)"] = _getiri_serisi(norm_ohlc(bp.FX("USD").history(period="1y"))["Close"])
    except Exception as e:
        disari["Dolar (USD/TRY)"] = {"hata": str(e)[:60]}
    try:
        ev = _evds_frame("TP.TRY.MT01", yil=1, freq="weekly")      # 1 aya kadar TL mevduat, yıllık %
        r = float(ev.iloc[-1])
        disari["TL mevduat (1 ay, brüt)"] = {"yillik_oran": round(r, 2), "1a": round(r * 30 / 365, 2), "3a": round(r * 91 / 365, 2),
                                            "not": "faiz oranından hesaplanan beklenen getiri, gerçekleşen değil"}
    except Exception as e:
        disari["TL mevduat (1 ay, brüt)"] = {"hata": str(e)[:60]}
    ppf = siniflar.get("Para piyasası") or {}
    ustu = {}
    for ad, v in list(siniflar.items()) + list(disari.items()):
        if ad == "Para piyasası" or not isinstance(v, dict):
            continue
        if None in (v.get("1a"), v.get("3a"), ppf.get("1a"), ppf.get("3a")):
            continue
        f1, f3 = round(v["1a"] - ppf["1a"], 2), round(v["3a"] - ppf["3a"], 2)
        v["ppf_farki_1a"], v["ppf_farki_3a"] = f1, f3
        if f1 >= SINIF_ESIK_1A and f3 >= SINIF_ESIK_3A:
            ustu[ad] = {"fark_1a": f1, "fark_3a": f3}
    # kalıcılık takibi (günde bir kez sayılır)
    iz = {}
    if os.path.exists(SINIF_IZLEME_FILE):
        try:
            iz = json.load(open(SINIF_IZLEME_FILE, encoding="utf-8"))
        except Exception:
            iz = {}
    bugun = NOW.strftime("%Y-%m-%d")
    for ad in ustu:
        k = iz.setdefault(ad, {"gunler": []})
        if bugun not in k["gunler"]:
            k["gunler"].append(bugun)
        k["gunler"] = k["gunler"][-60:]
    json.dump(iz, open(SINIF_IZLEME_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    for ad, v in ustu.items():
        g = iz.get(ad, {}).get("gunler", [])
        # kesintisiz: son kayıtlı günlerin bugüne kadar ardışık iş günleri olması
        ardisik = 0
        gun = pd.Timestamp(NOW.date())
        for t in sorted(g, reverse=True):
            if pd.Timestamp(t) == gun:
                ardisik += 1
                gun = gun - pd.offsets.BDay(1)
            else:
                break
        v["ardisik_is_gunu"] = ardisik
        v["olgun"] = ardisik >= SINIF_OLGUNLUK_IS_GUNU
    return {"siniflar": siniflar, "fon_disi": disari, "para_piyasasi_ustu": ustu,
            "not": "Vergi farkları (fon stopajı, hisse yoğun fon, mevduat, fiziki altın/döviz) karar anında ayrıca hesaplanır."}


def fon_capraz(fonoloji, borsapy_fon):
    """İki bağımsız aktarım hattını karşılaştırır. Fark → HEALTH uyarısı."""
    out = {}
    for c, a in (fonoloji or {}).items():
        b = (borsapy_fon or {}).get(c)
        if not a or not b or not a.get("fiyat") or not b.get("fiyat"):
            continue
        r = {"fonoloji_fiyat": a["fiyat"], "borsapy_fiyat": b["fiyat"],
             "fonoloji_tarih": a["fiyat_tarihi"], "borsapy_tarih": b["fiyat_tarihi"]}
        if a["fiyat_tarihi"] == b["fiyat_tarihi"]:
            fark = pct(a["fiyat"], b["fiyat"])
            r["fark_pct"] = fark
            if fark is not None and abs(fark) > 0.05:
                HEALTH[f"fon_{c}_kaynak_celiskisi"] = (f"UYARI: {c} fiyatı iki kaynakta farklı — fonoloji {a['fiyat']} vs "
                                                        f"borsapy {b['fiyat']} ({fark}%) — aktarım hatası olabilir")
        else:
            r["not"] = "tarihler farklı — biri geriden geliyor"
            HEALTH[f"fon_{c}_tarih_farki"] = f"UYARI: {c} fonoloji {a['fiyat_tarihi']}, borsapy {b['fiyat_tarihi']}"
        out[c] = r
    return out


def onceki_islem_gunu_getirisi(kapanislar, fon_tarihi):
    """Hisse fonunun 'D' tarihli fiyatı, D'den önceki son işlem gününün kapanışıyla hesaplanır (TEFAS).
    Bu yüzden fonun D günkü getirisi, endeksin D'den ÖNCEKİ son işlem günündeki getirisiyle karşılaştırılır.
    kapanislar: [{"t": "YYYY-MM-DD", "k": fiyat}, ...] (tamamlanmış günler)."""
    once = [x for x in kapanislar if x["t"] < fon_tarihi]
    if len(once) < 2:
        return None
    return pct(once[-1]["k"], once[-2]["k"])


def fon_tutarlilik(R):
    """Bağımsız kaynak yok → iç tutarlılık kontrolleri (28 Eyl). Sapma varsa HEALTH'e yazar."""
    fon = R.get("fonlar") or {}
    son_is = (pd.Timestamp(NOW.date()) - pd.offsets.BDay(1)).date()
    b30 = R.get("bist30") or {}
    kap = list(b30.get("son_5_kapanis") or [])
    if b30.get("son_bar_kismi_mi"):
        kap = kap[:-1]
    out = {}
    for c, fb in fon.items():
        if not fb or fb.get("fiyat_tarihi") is None:
            continue
        r = {}
        ft = datetime.strptime(fb["fiyat_tarihi"], "%Y-%m-%d").date()
        yas = (son_is - ft).days
        r["fiyat_yasi_is_gunu"] = yas
        if yas > 1:
            HEALTH[f"fon_{c}_bayat"] = f"UYARI: {c} fiyatı {fb['fiyat_tarihi']} tarihli, son iş günü {son_is} — bayat olabilir"
        g = fb.get("gunluk_getiri_pct")
        if c in CEPHANE and g is not None and abs(g) > 0.35:
            HEALTH[f"fon_{c}_gunluk_sapma"] = f"UYARI: para piyasası fonu {c} günde %{g} hareket etti (normal ±0,15) — veri şüpheli"
            r["sapma"] = "para piyasası için anormal günlük hareket"
        endeks_gun = onceki_islem_gunu_getirisi(kap, fb["fiyat_tarihi"]) if c in ("TIE", "AKU") else None
        if c in ("TIE", "AKU") and g is not None and endeks_gun is not None:
            fark = round(g - endeks_gun, 2)
            r["endeks_gun"] = endeks_gun; r["fon_eksi_endeks"] = fark
            if abs(fark) > 1.5:
                HEALTH[f"fon_{c}_takip_sapmasi"] = f"UYARI: {c} günlük %{g}, BIST 30 %{endeks_gun} — {fark} puan sapma, veri veya takip sorunu"
        out[c] = r
    return out


FON_HIST = "output/fon_gecmis.json"

def fon_akis_trend(fonlar):
    """Fon künyesindeki büyüklük ve yatırımcı sayısını günlük kaydeder, ≤30 günlük değişimi hesaplar."""
    hist = {}
    if os.path.exists(FON_HIST):
        try:
            hist = json.load(open(FON_HIST, encoding="utf-8"))
        except Exception:
            hist = {}
    bugun = NOW.strftime("%Y-%m-%d")
    snap = {}
    for c, fb in (fonlar or {}).items():
        bi = (fb or {}).get("bilgi") or {}
        if bi.get("fund_size") and bi.get("investor_count"):
            snap[c] = {"b": bi["fund_size"], "y": bi["investor_count"]}
    if snap:
        hist[bugun] = snap
    hist = dict(sorted(hist.items())[-60:])
    json.dump(hist, open(FON_HIST, "w", encoding="utf-8"), ensure_ascii=False)
    tarihler = sorted(hist)
    esik = (NOW - timedelta(days=30)).strftime("%Y-%m-%d")
    uygun = [t for t in tarihler if t <= esik]
    ref = uygun[-1] if uygun else tarihler[0]
    out = {"referans_tarih": ref, "gun": (NOW.date() - datetime.strptime(ref, "%Y-%m-%d").date()).days}
    for c, v in hist.get(bugun, {}).items():
        r = hist[ref].get(c)
        if r:
            out[c] = {"buyukluk_degisim_pct": pct(v["b"], r["b"]), "yatirimci_degisim_pct": pct(v["y"], r["y"])}
    return out


ARSIV_FILE = "output/gunluk_arsiv.csv"

def _sinif_arsiv(R):
    """Arşive kısa sütunlar: sınıf ortancaları (1a, 3a) — gidişatı izlemek için."""
    kis = {"Para piyasası": "ppf", "Kamu borçlanma (devlet tahvili)": "kamu_borc", "Özel sektör borçlanma": "ozel_borc",
           "Borçlanma (karma)": "karma_borc", "Kısa vadeli borçlanma": "kisa_borc",
           "Enflasyona endeksli": "tufe", "Kira sertifikası / katılım": "katilim", "Altın / kıymetli maden": "altin_fon",
           "Eurobond / döviz": "eurobond", "BIST endeks hisse": "bist_endeks"}
    sn = (((R.get("rakip_tarama") or {}).get("varlik_siniflari") or {}).get("siniflar") or {})
    out = {}
    for ad, k in kis.items():
        v = sn.get(ad) or {}
        out[f"{k}_1a"], out[f"{k}_3a"] = v.get("1a"), v.get("3a")
    tz = (R.get("tetikler") or {}).get("tahvil_zamanlama") or {}
    out["iki_yil_eksi_politika"] = tz.get("iki_yil_eksi_politika")
    out["egri_egimi"] = tz.get("egri_egimi_10y_2y")
    out["pka_faiz_beklentisi"] = tz.get("pka_politika_faizi_beklentisi")
    return out

def gunluk_arsiv(R):
    """Her iş günü akşam (18:00 sonrası ilk çalışmada) günün özetini tek satır ekler. Silinmez."""
    if NOW.weekday() >= 5 or NOW.hour < 18:
        return "saat değil"
    T = R.get("tetikler") or {}
    b = R.get("bist100") or {}
    g = R.get("genislik") or {}
    g30 = R.get("genislik_bist30") or {}
    fx = R.get("doviz_altin") or {}
    fon = R.get("fonlar") or {}
    reel = T.get("reel_getiri") or {}
    def fxl(k):
        v = fx.get(k); return v.get("last") if isinstance(v, dict) else None
    satir = {
        "tarih": NOW.strftime("%Y-%m-%d"),
        "bist100": b.get("son_fiyat"), "bist100_gun_pct": b.get("gunluk_degisim_pct"),
        "rsi14": b.get("rsi14_anlik") or b.get("rsi14_tamamlanmis"),
        "bist30": (R.get("bist30") or {}).get("son_fiyat"),
        "banka_gun_pct": (R.get("sektor", {}).get("XBANK") or {}).get("gunluk_degisim_pct"),
        "tum_yukselen_pct": g.get("yukselen_orani_pct"), "tum_taban": g.get("tabana_kilitli"),
        "tum_medyan_pct": g.get("medyan_degisim_pct"), "bist30_yukselen_pct": g30.get("yukselen_orani_pct"),
        "yapay_taban": T.get("yapay_taban_sinyali"), "kamu_alim_proxy": T.get("kamu_alim_proxy"),
        "aofm": T.get("aofm"), "aofm_30g_puan": T.get("aofm_30g_degisim_puan"),
        "politika_faizi": T.get("politika_faizi"),
        "yabanci_ort_oran": (R.get("yabanci") or {}).get("bugun_ort_yabanci_orani"),
        "yabanci_hisse_net_hafta": T.get("yabanci_hisse_net_son_hafta"),
        "brut_rezerv_4h_pct": T.get("brut_rezerv_4hafta_pct"),
        "tufe_aylik": T.get("tufe_aylik"), "dolar_makasi": T.get("dolar_makasi_puan"),
        "usd": fxl("USD"), "gram_altin": fxl("gram-altin"), "brent": fxl("BRENT"),
        "vix": T.get("vix"), "nasdaq_zirveden": T.get("nasdaq_zirveden_pct"),
        **{f"sinif_{k}": v for k, v in _sinif_arsiv(R).items()},
    }
    for c in FUNDS:
        satir[f"fiyat_{c}"] = (fon.get(c) or {}).get("fiyat")
    for c in CEPHANE:
        satir[f"reel_net_{c}"] = (reel.get(c) or {}).get("reel_net_pct")
    yeni = pd.DataFrame([satir])
    if os.path.exists(ARSIV_FILE):
        eski = pd.read_csv(ARSIV_FILE)
        eski = eski[eski["tarih"] != satir["tarih"]]          # aynı gün tekrar çalışırsa üzerine yaz
        yeni = pd.concat([eski, yeni], ignore_index=True)
    os.makedirs("output", exist_ok=True)
    yeni.to_csv(ARSIV_FILE, index=False)
    return f"{len(yeni)} gün kayıtlı"


def find_monthly_cpi(obj):
    """Enflasyon çıktısında aylık TÜFE değişimini arar."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            if any(w in kl for w in ("monthly", "aylik", "aylık", "mom")) and isinstance(v, (int, float)):
                return float(v)
            r = find_monthly_cpi(v)
            if r is not None:
                return r
    if isinstance(obj, list):
        for v in obj:
            r = find_monthly_cpi(v)
            if r is not None:
                return r
    return None

# ---- ANA AKIŞ -------------------------------------------------------------
def tufe_yenile_gerekli(son_tarih, simdi):
    """TÜİK ayın ilk günlerinde (≤8) 10:00'da açıklar. Elimizdeki son TÜFE geçen aydan eskiyse yenile."""
    if not son_tarih or simdi.day > 8 or simdi.hour < 10:
        return False
    ilk = simdi.replace(day=1)
    beklenen = (ilk - timedelta(days=1)).replace(day=1).strftime("%Y-%m-%d")   # geçen ayın 1'i
    return son_tarih < beklenen


def agir_slot():
    """Bu çalışma hangi 'ağır iş' penceresinde? Hafta sonu ve gün içi: yok (önbellek)."""
    if NOW.weekday() >= 5:
        return None
    if 7 <= NOW.hour < 12:
        return NOW.strftime("%Y-%m-%d") + "-sabah"
    if (NOW.hour == 18 and NOW.minute >= 40) or NOW.hour >= 19:
        return NOW.strftime("%Y-%m-%d") + "-aksam"
    return None


def main():
    if os.environ.get("RADAR_TEST_COKME"):
        raise RuntimeError("test amaçlı kontrollü çökme")
    R = {"surum": "v3", "uretim_zamani_tr": NOW.strftime("%Y-%m-%d %H:%M:%S"),
         "not": "Kişisel veri yok. BIST verisi ~15 dk gecikmeli. Günlük göstergeler tamamlanmış barlarla."}

    R["bist100"] = index_block("XU100")
    R["bist30"] = index_block("XU030")
    R["sektor"] = {s: index_block(s, with_ma=False) for s in SEKTOR}

    prev = {}
    if os.path.exists(OUT):
        try:
            prev = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            prev = {}
    # 3 Eki: ağır işler (fonlar, rakip/künye, EVDS, yabancı oranı) günde İKİ kez: sabah ilk çalışma ve
    # kesin kapanış fiyatlarının geldiği 18:40 sonrası. Eskiden 08,09,18,19 saatlerinin hepsinde çalışıyordu
    # (kota ve süre iki katı, TEFAS engelleme riski).
    slot = agir_slot()
    gunluk_saat = bool(slot) and prev.get("agir_slot") != slot
    R["agir_slot"] = slot if gunluk_saat else prev.get("agir_slot")
    zorla = str(os.environ.get("RADAR_AGIR", "")).lower() == "true"   # 5 Eki: Run workflow → "ağır çalıştır" kutusu
    if zorla:
        gunluk_saat = True   # slot kaydı değişmez: planlı sabah/akşam ağır çalışmaları etkilenmez
    R["agir_calisma"] = gunluk_saat
    R["agir_zorla"] = zorla
    agir_basarisiz = []

    R["genislik"] = (safe("genislik_tum_piyasa", lambda: breadth_scan("XUTUM", 100)) if bp else None) or {"hata": "alınamadı"}
    g30 = safe("genislik_bist30", lambda: breadth_scan("XU030", 25)) if bp else None
    if g30 is None and yf and os.path.exists(TICKERS_FILE):
        g30 = safe("yahoo_yedek_genislik", breadth_yahoo)
    R["genislik_bist30"] = g30 or {"hata": "alınamadı"}

    onceki_yab = prev.get("yabanci") or {}
    if bp and (gunluk_saat or not onceki_yab or "hata" in onceki_yab):
        fr = safe("yabanci_orani", foreign_ratios)
        R["yabanci"] = safe("yabanci_trend", lambda: foreign_trend(fr)) if fr else {"hata": "yabancı oranı alınamadı"}
    else:
        R["yabanci"] = onceki_yab
        if isinstance(R["yabanci"], dict):
            R["yabanci"] = {**R["yabanci"], "not_onbellek": "yabancı oranı günde 2 kez güncellenir"}

    fon_saati = gunluk_saat or not prev.get("fonlar")
    if fon_saati:
        fono = {c: safe(f"fonoloji_{c}", lambda c=c: fonoloji_fund(c)) for c in FUNDS} if os.environ.get("FONOLOJI_KEY") else {}
        bors = {c: safe(f"fon_{c}", lambda c=c: fund_block(c)) for c in FUNDS} if bp else {}
        R["fonlar_borsapy"], R["fonlar_fonoloji"] = bors, fono
        R["fonlar"] = {c: (fono.get(c) or bors.get(c)) for c in FUNDS}          # birincil: fonoloji
        R["fonlar_kaynak"] = {c: ("fonoloji" if fono.get(c) else ("borsapy" if bors.get(c) else "yok")) for c in FUNDS}
        R["fon_capraz"] = fon_capraz(fono, bors)
        for c in FUNDS:   # 6 Eki: birincil (Fonoloji) çalıştıysa yedek TEFAS hatası bildirim üretmez
            if fono.get(c) and str(HEALTH.get(f"fon_{c}", "")).startswith("HATA"):
                HEALTH[f"yedek_borsapy_fon_{c}"] = HEALTH.pop(f"fon_{c}") + " (birincil Fonoloji çalıştı)"
        if not any(R["fonlar"].values()):
            agir_basarisiz.append("fonlar")
        R["fonlar_zamani"] = NOW.strftime("%Y-%m-%d %H:%M")
        R["fon_akis"] = safe("fon_akis", lambda: fon_akis_trend(R["fonlar"]))
        R["fon_tutarlilik"] = safe("fon_tutarlilik", lambda: fon_tutarlilik(R))

    elif prev.get("fonlar"):
        R["fonlar"] = prev["fonlar"]
        onceki = str(prev.get("fonlar_zamani", "önceki çalışma")).split(" (önbellek")[0]
        R["fonlar_zamani"] = onceki + " (önbellek — TEFAS günde 1 fiyat)"
        R["fon_akis"] = prev.get("fon_akis", {})
        for k in ("fonlar_borsapy", "fonlar_fonoloji", "fonlar_kaynak", "fon_capraz"):
            R[k] = prev.get(k)
    _prt = prev.get("rakip_tarama") or {}
    _prt_surum = ((_prt.get("para_piyasasi") or {}).get("surum")) if isinstance(_prt, dict) else None
    if bp and (gunluk_saat or not _prt or _prt_surum != RAKIP_SURUM):
        yeni = safe("rakip_tarama", rakip_tarama)
        if yeni is None and _prt:
            # 6 Eki: tarama başarısızsa bir önceki sonuç (tahvil adayları dahil) korunur
            R["rakip_tarama"] = _prt
            R["rakip_tarama_onbellek"] = str(_prt.get("zaman", "önceki"))
            HEALTH["rakip_tarama"] = HEALTH.get("rakip_tarama", "HATA") + " → önceki tarama korundu"
        else:
            R["rakip_tarama"] = yeni
        if yeni is None and gunluk_saat:
            agir_basarisiz.append("rakip_tarama")
    else:
        R["rakip_tarama"] = prev.get("rakip_tarama")
    if bp:
        R["tcmb"] = tcmb_block()
        if os.environ.get("EVDS_API_KEY"):
            if gunluk_saat or not prev.get("evds_resmi"):
                R["evds_resmi"] = evds_resmi()
                R["evds_resmi_zamani"] = NOW.strftime("%Y-%m-%d %H:%M")
            else:
                R["evds_resmi"] = prev["evds_resmi"]
                R["evds_resmi_zamani"] = str(prev.get("evds_resmi_zamani", "")).split(" (önbellek")[0] + " (önbellek)"
                # 5 Eki: enflasyon günü — sabah çalışması 10:00'daki veriyi kaçırdıysa sadece TÜFE'yi tazele
                tu = (R["evds_resmi"] or {}).get("tufe_endeks") or {}
                if tufe_yenile_gerekli(tu.get("tarih"), NOW):
                    ser = safe("evds_tufe_ek_cekim", lambda: _evds_frame("TP.TUKFIY2025.GENEL", freq="monthly"))
                    if ser is not None and len(ser) >= 13:
                        R["evds_resmi"] = {**R["evds_resmi"], "tufe_endeks": {"kod": "TP.TUKFIY2025.GENEL", **_ozet(ser),
                                           "aylik_pct": pct(ser.iloc[-1], ser.iloc[-2]), "yillik_pct": pct(ser.iloc[-1], ser.iloc[-13])}}
                        R["tufe_ek_cekim"] = NOW.strftime("%Y-%m-%d %H:%M")
        R["enflasyon"] = safe("enflasyon", lambda: J(bp.Inflation().latest()))
        R["tahvil"] = safe("tahvil", lambda: J(bp.bonds()))
        R["doviz_altin"] = {k: safe(f"fx_{k}", lambda k=k: J(bp.FX(k).current)) for k in FX_LIST}
        R["takvim_tr"] = safe("takvim_tr", lambda: J(bp.economic_calendar(period="1w", country="TR").head(25)))
        R["takvim_abd_onemli"] = safe("takvim_abd", lambda: J(
            bp.EconomicCalendar().events(period="1w", country="US", importance="high").head(15)))

    if bp:
        gdf = safe("gram_altin_gecmis", lambda: bp.FX("gram-altin").history(period="1y"))
        if gdf is not None:
            try:
                gdf = norm_ohlc(gdf)
                R["gram_altin_1y"] = {"son": J(gdf["Close"].iloc[-1]), "zirve_1y": J(gdf["Close"].max()),
                                      "zirveden_pct": pct(gdf["Close"].iloc[-1], gdf["Close"].max())}
            except Exception as e:
                HEALTH["gram_altin_gecmis"] = f"HATA: {e}"

    if yf:
        R["kuresel"] = {}
        for k, t in KURESEL.items():
            df = safe(f"yahoo_{k}", lambda t=t: norm_ohlc(
                yf.download(t, period="300d", interval="1d", auto_adjust=False, progress=False)))
            R["kuresel"][k] = summarize(df, "yahoo", with_ma=False, bist=False) if df is not None else {"hata": "yok"}
            sb = R["kuresel"][k].get("son_bar_tarihi")
            if sb:
                yas = (NOW.date() - datetime.strptime(sb, "%Y-%m-%d").date()).days
                if yas > 4:
                    HEALTH[f"yahoo_{k}_bayat"] = f"UYARI: {k} son verisi {sb} ({yas} gün önce) — Yahoo güncellemiyor olabilir"

    # ---- TETİKLER ----
    T = {}
    try:
        b = R["bist100"]; f = b["son_fiyat"]
        T["korunan_taban_mesafe_pct"] = pct(f, LEVELS["korunan_taban"])
        T["tez_cizgisi_mesafe_pct"] = pct(f, LEVELS["tez_cizgisi_haftalik"])
        T["k3_tetik_13000_alti_kapanis"] = bool(f < LEVELS["korunan_taban"] and not b["son_bar_kismi_mi"])
        T["k3_yaklasiyor_anlik"] = bool(f < LEVELS["korunan_taban"] and b["son_bar_kismi_mi"])
        wkc = b.get("haftalik_kapanis", {})
        hafta_tamam = (datetime.strptime(b["son_bar_tarihi"], "%Y-%m-%d").weekday() == 4
                       and not b["son_bar_kismi_mi"])
        hk = wkc.get("bu_hafta_son") if hafta_tamam else wkc.get("son_tamamlanan_hafta")
        T["tez_cizgisi_referans_kapanis"] = hk
        T["tez_cizgisi_haftalik_kirildi"] = bool(hk and hk < LEVELS["tez_cizgisi_haftalik"])
        T["korunan_taban_3gun"] = all(12900 <= x["k"] <= 13500 for x in b["son_5_kapanis"][-3:])
        ma200 = b.get("hareketli_ortalamalar", {}).get("sma200")
        T["ma200_ustu"] = bool(ma200 and f > ma200)
        bk = R["sektor"]["XBANK"].get("gunluk_degisim_pct"); ix = b.get("gunluk_degisim_pct")
        if bk is not None and ix is not None:
            T["banka_minus_endeks_pct"] = round(bk - ix, 2)
            T["kamu_alim_proxy"] = "GÜÇLÜ" if bk - ix > 2 else ("VAR" if bk - ix > 0.7 else "YOK")
            T["kamu_alim_proxy_not"] = "ZAYIF PROXY: banka primi faiz indirimi beklentisinden de gelebilir; haberle teyit şart"
    except Exception as e:
        T["bist_tetik_hata"] = str(e)[:150]
    try:
        g = R.get("genislik", {}); g30 = R.get("genislik_bist30", {})
        T["genislik_tabana_kilitli_tum"] = g.get("tabana_kilitli")
        T["genislik_yukselen_orani_tum"] = g.get("yukselen_orani_pct")
        T["genislik_yukselen_orani_bist30"] = g30.get("yukselen_orani_pct")
        if g.get("yukselen_orani_pct") is not None and g30.get("yukselen_orani_pct") is not None:
            fark = round(g30["yukselen_orani_pct"] - g["yukselen_orani_pct"], 1)
            T["generaller_eksi_ordu_puan"] = fark
            taban = g.get("tabana_kilitli") or 0
            medyan = g.get("medyan_degisim_pct")
            genel_zayif = medyan is not None and medyan < -1.0
            T["yapay_taban_sinyali"] = bool(fark > 30 or (taban >= 15 and genel_zayif))
            T["yapay_taban_gerekce"] = ("generaller-ordu farkı >30 puan" if fark > 30 else
                                        ("çok hisse tabanda VE medyan hisse < -%1" if (taban >= 15 and genel_zayif) else
                                         ("tabanda çok hisse var ama genel piyasa zayıf değil — muhtemelen tasfiye hisseleri"
                                          if taban >= 15 else "yok")))
        T["yabanci_1hafta_puan"] = R.get("yabanci", {}).get("1hafta_degisim_puan")
        k = R.get("kuresel", {})
        T["nasdaq_zirveden_pct"] = k.get("nasdaq", {}).get("zirveden_pct")
        T["nasdaq_duzeltme_tetik"] = bool(T["nasdaq_zirveden_pct"] is not None and T["nasdaq_zirveden_pct"] <= NASDAQ_ESIK)
        T["altin_zirveden_pct"] = k.get("ons_altin", {}).get("zirveden_pct")
        T["altin_duzeltme_tetik"] = bool(T["altin_zirveden_pct"] is not None and T["altin_zirveden_pct"] <= ALTIN_ESIK)
        T["vix"] = k.get("vix", {}).get("son_fiyat")
        br = (R.get("doviz_altin") or {}).get("BRENT") or {}
        T["brent"] = br.get("last") if isinstance(br, dict) else None
        T["brent_kaynak"] = "borsapy"
        by = (k.get("brent_yahoo") or {}).get("son_fiyat")
        if T["brent"] and by:
            fark = round((T["brent"] / by - 1) * 100, 2)
            T["brent_capraz"] = {"borsapy": T["brent"], "yahoo": by, "fark_pct": fark}
            if abs(fark) > 3:
                HEALTH["brent_kaynak_celiskisi"] = (f"UYARI: Brent borsapy {T['brent']} / Yahoo {by} (%{fark} fark) — "
                                                   "biri bayat ya da vade geçişi; haberle teyit et")
        T["gram_altin_zirveden_pct"] = (R.get("gram_altin_1y") or {}).get("zirveden_pct")
    except Exception as e:
        T["kuresel_tetik_hata"] = str(e)[:150]
    try:
        tc = R.get("tcmb") or {}
        a = (tc.get("aofm") or {}).get("oran"); pf = tc["politika_faizi"]["oran"]
        T["politika_faizi"] = pf
        T["ppk_kalan_gun"] = tc.get("ppk_kalan_gun")
        if a is not None:
            T["aofm"] = a
            T["aofm_eksi_politika"] = round(a - pf, 2)
            T["ortulu_para_politikasi"] = ("SIKILAŞMA" if a - pf > 1 else ("GEVŞEME" if a - pf < -1 else "NÖTR"))
            a30 = (tc.get("aofm") or {}).get("30g_once")
            if a30 is not None:
                d30 = round(a - a30, 2)
                T["aofm_30g_degisim_puan"] = d30
                T["aofm_30g_yon"] = ("GEVŞEME — fon getirileri önümüzdeki haftalarda düşer" if d30 <= -1 else
                                     ("SIKILAŞMA — fon getirileri önümüzdeki haftalarda artar" if d30 >= 1 else "SABİT"))
    except Exception as e:
        T["tcmb_tetik_hata"] = str(e)[:120]

    akis_alarm = {}
    fa = R.get("fon_akis") or {}
    T["fon_akis_pencere_gun"] = fa.get("gun")
    sa = (R.get("rakip_tarama") or {}).get("sektor_akis") or {}
    T["fon_akis_sektor"] = sa
    akis_detay = {}
    for c in FUNDS:
        a = fa.get(c) or {}
        fk = ((R.get("fonlar") or {}).get(c) or {}).get("akis") or {}
        b_ = fk["buyukluk_30g_degisim_pct"] if fk.get("buyukluk_30g_degisim_pct") is not None else a.get("buyukluk_degisim_pct")
        y_ = fk["yatirimci_30g_degisim_pct"] if fk.get("yatirimci_30g_degisim_pct") is not None else a.get("yatirimci_degisim_pct")
        grup = "para_piyasasi" if c in CEPHANE else "bist30_endeks"
        ref = sa.get(grup) or {}
        mb, my = ref.get("medyan_buyukluk_30g"), ref.get("medyan_yatirimci_30g")
        gb = round(b_ - mb, 2) if (b_ is not None and mb is not None) else None
        gy = round(y_ - my, 2) if (y_ is not None and my is not None) else None
        akis_detay[c] = {"buyukluk_30g": b_, "yatirimci_30g": y_, "sektor_buyukluk_30g": mb,
                         "sektor_yatirimci_30g": my, "goreli_buyukluk": gb, "goreli_yatirimci": gy}
        if gb is not None or gy is not None:
            # sektör referansı varsa: fona ÖZGÜ çıkış (Tera/Pusula'yı ayırt eden buydu)
            if (gb is not None and gb <= -GORELI_ESIK_BUYUKLUK) or (gy is not None and gy <= -GORELI_ESIK_YATIRIMCI):
                akis_alarm[c] = {**akis_detay[c], "tur": "fona özgü (sektörden belirgin kötü)"}
        elif (b_ is not None and b_ <= -20) or (y_ is not None and y_ <= -15):
            akis_alarm[c] = {**akis_detay[c], "tur": "mutlak (sektör referansı yok)"}
        if b_ is not None and b_ <= MUTLAK_ACIL_ESIK and c not in akis_alarm:
            akis_alarm[c] = {**akis_detay[c], "tur": "mutlak acil (%50+ erime)"}
    T["fon_akis_detay"] = akis_detay
    T["fon_kitlesel_cikis_alarm"] = akis_alarm   # Tera/Pusula dersi: erken uyarı


    try:
        rt = R.get("rakip_tarama") or {}
        ozet = {}
        for grup in ("para_piyasasi", "bist30_endeks"):
            for kod, v in ((rt.get(grup) or {}).get("bizim") or {}).items():
                ad = [a["kod"] for a in (v.get("buyuk_adaylar") or [])]
                if ad:
                    ozet[kod] = ad
        T["rakip_gecis_adaylari"] = ozet
        olgun = {}
        for kod, adaylar in (rt.get("aday_izleme") or {}).items():
            grup = "para_piyasasi" if kod in RAKIP_GRUPLARI["para_piyasasi"]["bizim"] else "bist30_endeks"
            guncel = {a["kod"]: a for a in (((rt.get(grup) or {}).get("bizim") or {}).get(kod) or {}).get("buyuk_adaylar") or []}
            o = []
            for ak, v in adaylar.items():
                bb = (guncel.get(ak) or {}).get("basabas_gun")
                if v.get("olgun") and (bb is None or bb <= BASABAS_MAX_GUN):
                    o.append({"kod": ak, "aday_gun": v["aday_gun_sayisi"], "basabas_gun": bb,
                              "fark_1y": v.get("son_fark_1y")})
            if o:
                olgun[kod] = o
        # kalıcılık (≥20 iş günü, ≥28 gün) + başabaş (≤30 gün) şartlarını geçmiş adaylar → kullanıcıyla değerlendirilir
        T["rakip_olgun_adaylar"] = olgun
        vs = (rt.get("varlik_siniflari") or {})
        T["varlik_sinifi_ppf_ustu"] = vs.get("para_piyasasi_ustu") or {}
        T["varlik_sinifi_olgun"] = [k for k, v in (vs.get("para_piyasasi_ustu") or {}).items() if v.get("olgun")]
        # tahvil zamanlaması: piyasa ne bekliyor, kim alıyor, tahvil fonları nerede
        tz = {}
        verim = {str(x.get("maturity")): x.get("yield") for x in (R.get("tahvil") or []) if isinstance(x, dict)}
        pf_ = POLITIKA_FAIZI["oran"]
        if verim.get("2Y") is not None:
            tz["iki_yil_verim"] = verim["2Y"]
            tz["iki_yil_eksi_politika"] = round(verim["2Y"] - pf_, 2)   # >0: piyasa güçlü indirim FİYATLAMIYOR
        if verim.get("2Y") is not None and verim.get("10Y") is not None:
            tz["egri_egimi_10y_2y"] = round(verim["10Y"] - verim["2Y"], 2)  # <0: ters eğri
        pkaf = ((R.get("evds_resmi") or {}).get("pka_faiz_beklentisi") or {}).get("son")
        tz["pka_politika_faizi_beklentisi"] = pkaf
        if pkaf is not None:
            tz["beklenen_indirim_puan"] = round(pf_ - pkaf, 2)
        tz["yabanci_dibs_net_4hafta"] = T.get("yabanci_dibs_net_4hafta")
        kb = (vs.get("siniflar") or {}).get("Kamu borçlanma (devlet tahvili)") or {}
        tz["kamu_borclanma_ppf_farki_1a"] = kb.get("ppf_farki_1a")
        tz["kamu_borclanma_ppf_farki_3a"] = kb.get("ppf_farki_3a")
        tz["aofm_30g_yon"] = T.get("aofm_30g_yon")
        T["tahvil_zamanlama"] = tz
        T["rakip_supheli"] = {g: (rt.get(g) or {}).get("supheli_yuksek") for g in ("para_piyasasi", "bist30_endeks")}
    except Exception as e:
        T["rakip_hata"] = str(e)[:120]

    # Reel getiri (Blok 5)
    ev = R.get("evds_resmi") or {}
    tu = ev.get("tufe_endeks") or {}
    if tu.get("aylik_pct") is not None:
        T["tufe_aylik"], T["tufe_kaynak"] = tu["aylik_pct"], f"TÜİK resmi (EVDS, {tu.get('tarih')})"
        T["tufe_yillik"] = tu.get("yillik_pct")
    else:
        tufe = find_monthly_cpi(R.get("enflasyon"))
        T["tufe_aylik"] = tufe if tufe is not None else TUFE_AYLIK_MANUEL
        T["tufe_kaynak"] = "borsapy enflasyon" if tufe is not None else "MANUEL (betikteki sabit)"
    try:
        yh = ev.get("yabanci_hisse_net_haftalik") or {}
        yd = ev.get("yabanci_dibs_net_haftalik") or {}
        T["yabanci_hisse_net_son_hafta"] = yh.get("son"); T["yabanci_hisse_net_4hafta"] = yh.get("son_4_hafta_toplam")
        T["yabanci_dibs_net_4hafta"] = yd.get("son_4_hafta_toplam"); T["yabanci_veri_tarihi"] = yh.get("tarih")
        T["pka_12ay_enflasyon_beklentisi"] = (ev.get("pka_12ay_enflasyon") or {}).get("son")
        T["brut_rezerv_4hafta_pct"] = (ev.get("brut_doviz_rezerv") or {}).get("4hafta_degisim_pct")
        T["mevduat_tl_1ay_brut"] = (ev.get("mevduat_tl_1ay") or {}).get("son")
        T["mevduat_tl_3ay_brut"] = (ev.get("mevduat_tl_3ay") or {}).get("son")
        kb = (ev.get("pka_kur_beklentisi") or {}).get("son")
        usd = ((R.get("doviz_altin") or {}).get("USD") or {}).get("last")
        if kb is not None and usd:
            artis = pct(kb, usd) if kb > 5 else kb          # seviye (TL) ise spota göre %, değilse zaten %
            T["beklenen_kur_artisi_12ay_pct"] = artis
            pf = POLITIKA_FAIZI["oran"]
            T["dolar_makasi_puan"] = round(pf - artis, 2)
            T["dolar_gecis_tetik"] = bool(pf - artis < 8)
    except Exception as e:
        T["evds_tetik_hata"] = str(e)[:150]
    try:
        b = R["bist100"]
        kap = [x["k"] for x in b["son_5_kapanis"]]
        if b["son_bar_kismi_mi"]:
            kap = kap[:-1]
        ma200 = (b.get("hareketli_ortalamalar") or {}).get("sma200")
        iki_gun = bool(ma200 and len(kap) >= 2 and all(x > ma200 for x in kap[-2:]))
        gen_ok = ((R.get("genislik") or {}).get("yukselen_orani_pct") or 0) >= 55
        yab_ok = (T.get("yabanci_hisse_net_son_hafta") or 0) > 0
        T["k3_donus_kapisi"] = {"ma200": ma200, "ma200_ustu_2gun": iki_gun, "genislik_katilim": gen_ok,
                                "yabanci_net_alici": yab_ok, "TETIK": bool(iki_gun and gen_ok and yab_ok)}
        T["k3_dusus_kapisi_TETIK"] = T.get("k3_tetik_13000_alti_kapanis")
    except Exception as e:
        T["k3_kapi_hata"] = str(e)[:120]
    reel = {}
    for c, fb in (R.get("fonlar") or {}).items():
        if c in CEPHANE and fb and fb.get("getiri_30g_pct") is not None:
            brut = fb["getiri_30g_pct"]
            net_getiri = brut * (1 - STOPAJ_PP)
            r_net = round(net_getiri - T["tufe_aylik"], 2)
            reel[c] = {"brut_30g_pct": brut, "net_30g_pct": round(net_getiri, 2),
                       "reel_net_pct": r_net, "reel_brut_pct": round(brut - T["tufe_aylik"], 2),
                       "durum": "ACIL" if r_net <= REEL_ACIL else ("ALARM" if r_net < REEL_ALARM else "OK")}
    T["reel_getiri"] = reel
    T["reel_getiri_yontem"] = f"NET: getiri×(1-{STOPAJ_PP}) − aylık TÜFE; ALARM <{REEL_ALARM}, ACİL ≤{REEL_ACIL}"
    R["tetikler"] = T
    R["arsiv"] = safe("gunluk_arsiv", lambda: gunluk_arsiv(R))

    # ---- SAĞLIK ----
    R["fonoloji_cagri"] = dict(FONOLOJI_SAYAC)
    # 6 Eki: ağır çalışmanın kritik parçası başarısızsa pencere "kullanılmış" sayılmaz → sonraki çalışma yeniden dener
    if agir_basarisiz and not zorla:
        R["agir_slot"] = prev.get("agir_slot")
        R["agir_tekrar_denenecek"] = agir_basarisiz
    for _k in list(HEALTH):
        HEALTH[_k] = _gizle(HEALTH[_k])
    bad = {k: v for k, v in HEALTH.items() if v != "OK"}
    bp_bad = {k: v for k, v in bad.items() if not k.startswith(("yahoo_yedek", "yedek_"))}
    R["saglik"] = {"ozet": "TAMAM" if not bp_bad else "SORUN VAR", "issue_tetikleyen": sorted(bp_bad),
                   "hatali_moduller": bad, "tum_moduller": HEALTH,
                   "aciklama": "SORUN VAR ise bir veya daha fazla modül kırıldı; yedekler devrede olabilir. GitHub Issue açılır."}

    os.makedirs("output", exist_ok=True)
    json.dump(R, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("SAGLIK:", R["saglik"]["ozet"])
    for k, v in bad.items():
        print(" -", k, v)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # 3 Eki: çökmede bir önceki çalışmanın verisi (önbellekler) korunur, sadece sağlık güncellenir
        os.makedirs("output", exist_ok=True)
        onceki = {}
        try:
            if os.path.exists(OUT):
                onceki = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            onceki = {}
        onceki.update({"uretim_zamani_tr": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                       "cokme": _gizle(f"{type(e).__name__}: {e}"),
                       "saglik": {"ozet": "SORUN VAR",
                                  "hatali_moduller": {"ana_akis": _gizle(f"{type(e).__name__}: {e}")},
                                  "tum_moduller": {k: _gizle(v) for k, v in HEALTH.items()},
                                  "aciklama": "Ana akış çöktü; aşağıdaki veriler BİR ÖNCEKİ başarılı çalışmaya aittir."}})
        json.dump(onceki, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("ANA AKIŞ ÇÖKTÜ:", _gizle(e))
