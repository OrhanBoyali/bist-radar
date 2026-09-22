#!/usr/bin/env python3
"""
BIST RADAR v3 — borsapy (birincil) + Yahoo (yedek)
Piyasa verisi üretir → output/radar.json. KİŞİSEL VERİ (pay adedi, tutar) İÇERMEZ.
Her modül ayrı denenir; kırılan modül "saglik" bölümüne yazılır,
iş akışı bunu GitHub Issue olarak açar (e-posta bildirimi).
"""
import json, math, os
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

TR_TZ = timezone(timedelta(hours=3))
NOW = datetime.now(TR_TZ)
OUT = "output/radar.json"
YAB_HIST = "output/yabanci_gecmis.json"
TICKERS_FILE = "tickers.txt"

# ---- SİSTEM AYARLARI (ana kayıttan; değişince güncelle) -------------------
LEVELS = {"korunan_taban": 13000, "tez_cizgisi_haftalik": 12600}
FUNDS = ["YLB", "IJV", "DLY", "TIE", "AKU"]          # portföydeki fonlar
CEPHANE = ["YLB", "IJV", "DLY"]                      # reel getiri kuralı SADECE bunlara
STOPAJ_PP = 0.175          # para piyasası fonu stopajı (kârdan). Değişirse güncelle.
REEL_ALARM, REEL_ACIL = 0.5, 0.0   # NET reel getiri eşikleri (aylık %)
TUFE_AYLIK_MANUEL = 1.84   # otomatik alınamazsa kullanılır (Ağustos 2026)
# Politika faizi yılda 8 kez değişir → PPK sonrası BURAYI güncelle
POLITIKA_FAIZI = {"oran": 37.0, "karar_tarihi": "2026-09-10", "sonraki_ppk": "2026-10-22"}
NASDAQ_ESIK, ALTIN_ESIK = -15.0, -5.0
SEKTOR = ["XBANK", "XUSIN", "XHOLD", "XUTEK", "XUMAL"]
YAHOO_INDEX = {"XU100": "XU100.IS", "XU030": "XU030.IS", "XBANK": "XBANK.IS", "XUSIN": "XUSIN.IS"}
KURESEL = {"sp500": "^GSPC", "nasdaq": "^IXIC", "vix": "^VIX",
           "dolar_endeksi": "DX-Y.NYB", "abd_10y": "^TNX", "ons_altin": "GC=F"}
# Brent Yahoo'dan ALINMAZ: vade geçişinde sahte düşüş gösterdi (21 Eyl). borsapy BRENT kullanılır.
FX_LIST = ["USD", "EUR", "gram-altin", "ceyrek-altin", "yarim-altin", "tam-altin", "BRENT"]  # ons-altin çıkarıldı: borsapy anlamsız değer veriyordu

# ---- SAĞLIK TAKİBİ --------------------------------------------------------
HEALTH = {}
def safe(name, fn):
    try:
        r = fn()
        HEALTH[name] = "OK"
        return r
    except Exception as e:
        HEALTH[name] = f"HATA: {type(e).__name__}: {str(e)[:200]}"
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
    s = h[pc].dropna()
    last_d = s.index[-1]
    past = s[s.index <= last_d - pd.Timedelta(days=30)]
    trend = {}
    for col, key in (("FundSize", "buyukluk"), ("Investors", "yatirimci")):
        if col in h.columns:
            x = h[col].dropna()
            xp = x[x.index <= last_d - pd.Timedelta(days=30)]
            trend[f"{key}_son"] = J(x.iloc[-1])
            trend[f"{key}_30g_degisim_pct"] = pct(x.iloc[-1], xp.iloc[-1]) if len(xp) else None
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

def breadth_market():
    """Tüm BIST (XUTUM) tek taramada: 'ordu' genişliği. BIST 30 = generaller, burada değil."""
    df = bp.scan("XUTUM", "change_percent > -100", limit=800)
    col = next((c for c in df.columns if "change" in str(c).lower()), None)
    if col is None or len(df) < 100:
        raise ValueError(f"tarama eksik: {len(df)} satır, sütunlar {list(df.columns)[:6]}")
    ch = pd.to_numeric(df[col], errors="coerce").dropna()
    return {"kaynak": "borsapy scan (XUTUM)", "hisse_sayisi": int(len(ch)),
            "yukselen": int((ch > 0).sum()), "dusen": int((ch < 0).sum()),
            "tabana_kilitli": int((ch <= -9.5).sum()), "tavana_kilitli": int((ch >= 9.5).sum()),
            "yukselen_orani_pct": round(float((ch > 0).mean() * 100), 1),
            "medyan_degisim_pct": round(float(ch.median()), 2)}


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
        ev = bp.evds_series("TP.APIFON4", period="3mo")
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
def main():
    R = {"surum": "v3", "uretim_zamani_tr": NOW.strftime("%Y-%m-%d %H:%M:%S"),
         "not": "Kişisel veri yok. BIST verisi ~15 dk gecikmeli. Günlük göstergeler tamamlanmış barlarla."}

    R["bist100"] = index_block("XU100")
    R["bist30"] = index_block("XU030")
    R["sektor"] = {s: index_block(s, with_ma=False) for s in SEKTOR}

    gen, today_foreign = None, {}
    if bp:
        r = safe("genislik_ve_yabanci", breadth_and_foreign)
        if r:
            gen, today_foreign = r
    if gen is None and yf and os.path.exists(TICKERS_FILE):
        gen = safe("yahoo_yedek_genislik", breadth_yahoo)
    R["genislik_bist30"] = gen or {"hata": "alınamadı"}
    R["genislik"] = (safe("genislik_tum_piyasa", breadth_market) if bp else None) or {"hata": "alınamadı"}
    R["yabanci"] = safe("yabanci_trend", lambda: foreign_trend(today_foreign)) if today_foreign else {"hata": "yabancı oranı alınamadı"}

    prev = {}
    if os.path.exists(OUT):
        try:
            prev = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            prev = {}
    fon_saati = NOW.hour in (8, 9, 18, 19) or not prev.get("fonlar")   # 08:17 ve 18:52 çalışmaları (gecikme payıyla)
    if bp and fon_saati:
        R["fonlar"] = {c: safe(f"fon_{c}", lambda c=c: fund_block(c)) for c in FUNDS}
        R["fonlar_zamani"] = NOW.strftime("%Y-%m-%d %H:%M")
    elif prev.get("fonlar"):
        R["fonlar"] = prev["fonlar"]
        R["fonlar_zamani"] = prev.get("fonlar_zamani", "önceki çalışma") + " (önbellek — TEFAS günde 1 fiyat)"
    if bp:
        R["tcmb"] = tcmb_block()
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
            T["yapay_taban_sinyali"] = bool(fark > 30 or (g.get("tabana_kilitli") or 0) >= 15)
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
    except Exception as e:
        T["tcmb_tetik_hata"] = str(e)[:120]

    akis_alarm = {}
    for c, fb in (R.get("fonlar") or {}).items():
        a = (fb or {}).get("akis") or {}
        b_ = a.get("buyukluk_30g_degisim_pct"); y_ = a.get("yatirimci_30g_degisim_pct")
        if (b_ is not None and b_ <= -20) or (y_ is not None and y_ <= -15):
            akis_alarm[c] = {"buyukluk_30g": b_, "yatirimci_30g": y_}
    T["fon_kitlesel_cikis_alarm"] = akis_alarm   # Tera/Pusula dersi: erken uyarı

    # Reel getiri (Blok 5)
    tufe = find_monthly_cpi(R.get("enflasyon"))
    T["tufe_aylik"] = tufe if tufe is not None else TUFE_AYLIK_MANUEL
    T["tufe_kaynak"] = "otomatik" if tufe is not None else "MANUEL (betikteki sabit)"
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

    # ---- SAĞLIK ----
    bad = {k: v for k, v in HEALTH.items() if v != "OK"}
    bp_bad = {k: v for k, v in bad.items() if not k.startswith("yahoo_yedek")}
    R["saglik"] = {"ozet": "TAMAM" if not bp_bad else "SORUN VAR",
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
        os.makedirs("output", exist_ok=True)
        json.dump({"surum": "v3", "uretim_zamani_tr": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                   "saglik": {"ozet": "SORUN VAR", "hatali_moduller": {"ana_akis": f"{type(e).__name__}: {e}"},
                              "tum_moduller": HEALTH}},
                  open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("ANA AKIŞ ÇÖKTÜ:", e)
