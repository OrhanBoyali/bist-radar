#!/usr/bin/env python3
"""
BIST RADAR v2 — çok kaynaklı, saatlik çalışabilen veri üretici
Yahoo Finance'ten BIST, sektör, küresel, döviz, altın verilerini çeker;
RSI/MA/ATR/genişlik/tetik bayrakları hesaplar → output/radar.json

Zaman dilimi: günlük göstergeler SADECE günlük barlarla. Gün içi veri ayrı etiketli.
"""

import json
import os
from datetime import datetime, timezone, timedelta

import pandas as pd
import yfinance as yf

TR_TZ = timezone(timedelta(hours=3))
NOW_TR = datetime.now(TR_TZ)
OUTPUT_FILE = "output/radar.json"
TICKERS_FILE = "tickers.txt"

# --- SİSTEM SEVİYELERİ (ana kayıttan; değişince burayı güncelle) ------------
LEVELS = {"korunan_taban": 13000, "tez_cizgisi_haftalik": 12600}
NASDAQ_DUZELTME_ESIK = -15.0   # zirveden % (yabancı hisse tetiği)
ALTIN_DUZELTME_ESIK = -5.0     # zirveden % (altın fonu tetiği)

# --- TICKER'LAR ----------------------------------------------------------
BIST = {"bist100": "XU100.IS", "bist30": "XU030.IS"}
SEKTOR = {"banka": "XBANK.IS", "sinai": "XUSIN.IS", "holding": "XHOLD.IS",
          "teknoloji": "XUTEK.IS", "mali": "XUMAL.IS"}
KURESEL = {"sp500": "^GSPC", "nasdaq": "^IXIC", "vix": "^VIX",
           "dolar_endeksi": "DX-Y.NYB", "brent": "BZ=F", "abd_10y": "^TNX"}
DOVIZ = {"usdtry": "USDTRY=X", "eurtry": "EURTRY=X", "eurusd": "EURUSD=X"}
ALTIN = {"ons_altin": "GC=F", "gumus": "SI=F"}


# --- YARDIMCI HESAPLAR ---------------------------------------------------
def rsi_wilder(close: pd.Series, period: int = 14):
    if len(close) < period + 1:
        return None
    d = close.diff()
    g = d.clip(lower=0).ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    v = 100 - 100 / (1 + g / l)
    return round(float(v.iloc[-1]), 2)


def atr(df: pd.DataFrame, period: int = 14):
    if len(df) < period + 1:
        return None
    pc = df["Close"].shift(1)
    tr = pd.concat([df["High"]-df["Low"], (df["High"]-pc).abs(), (df["Low"]-pc).abs()], axis=1).max(axis=1)
    return round(float(tr.ewm(alpha=1/period, adjust=False).mean().iloc[-1]), 2)


def fetch_daily(ticker: str, days: int = 400) -> pd.DataFrame:
    df = yf.download(ticker, period=f"{days}d", interval="1d", auto_adjust=False, progress=False)
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna(subset=["Close"])


def split_partial(df: pd.DataFrame):
    """Son bar bugünse ve piyasa kapanmadıysa 'kısmi' say; tamamlanmış barları ayır."""
    last_date = df.index[-1].date()
    today = NOW_TR.date()
    market_open = NOW_TR.weekday() < 5 and NOW_TR.hour < 18 or (NOW_TR.hour == 18 and NOW_TR.minute < 15)
    partial = (last_date == today) and market_open
    completed = df.iloc[:-1] if partial else df
    return completed, partial


def pct(a, b):
    try:
        return round((float(a) / float(b) - 1) * 100, 2)
    except Exception:
        return None


def basic_block(ticker: str, days: int = 400, with_ma: bool = True) -> dict:
    df = fetch_daily(ticker, days)
    if df.empty or len(df) < 3:
        return {"ticker": ticker, "hata": "veri yok"}
    comp, partial = split_partial(df)
    c_all = df["Close"]; c_comp = comp["Close"]
    out = {
        "ticker": ticker,
        "son_bar_tarihi": df.index[-1].strftime("%Y-%m-%d"),
        "son_bar_kismi_mi": partial,
        "son_fiyat": round(float(c_all.iloc[-1]), 2),
        "gunluk_degisim_pct": pct(c_all.iloc[-1], c_all.iloc[-2]),
        "gun_ici_dusuk": round(float(df["Low"].iloc[-1]), 2),
        "gun_ici_yuksek": round(float(df["High"].iloc[-1]), 2),
        "rsi14_tamamlanmis": rsi_wilder(c_comp),
        "rsi14_anlik": rsi_wilder(c_all) if partial else None,
        "atr14": atr(comp),
        "52h_zirve": round(float(df["High"].tail(252).max()), 2),
        "52h_dip": round(float(df["Low"].tail(252).min()), 2),
        "zirveden_pct": pct(c_all.iloc[-1], df["High"].tail(252).max()),
        "haftalik_degisim_pct": pct(c_all.iloc[-1], c_all.iloc[-6]) if len(c_all) > 6 else None,
        "aylik_degisim_pct": pct(c_all.iloc[-1], c_all.iloc[-22]) if len(c_all) > 22 else None,
    }
    if with_ma:
        ma = {}
        for n in (5, 10, 20, 50, 100, 200):
            if len(c_comp) >= n:
                ma[f"sma{n}"] = round(float(c_comp.rolling(n).mean().iloc[-1]), 2)
                ma[f"ema{n}"] = round(float(c_comp.ewm(span=n, adjust=False).mean().iloc[-1]), 2)
        out["hareketli_ortalamalar"] = ma
        wk = comp["Close"].resample("W-FRI").last().dropna()
        if len(wk) >= 2:
            out["haftalik_kapanis"] = {"son_tamamlanan_hafta": round(float(wk.iloc[-2]), 2),
                                      "bu_hafta_son": round(float(wk.iloc[-1]), 2)}
        if "Volume" in df and df["Volume"].tail(20).sum() > 0:
            v20 = float(df["Volume"].tail(21).iloc[:-1].mean())
            out["hacim_bugun"] = int(df["Volume"].iloc[-1])
            out["hacim_20g_ort"] = int(v20)
            out["hacim_orani"] = round(float(df["Volume"].iloc[-1]) / v20, 2) if v20 else None
        out["son_5_kapanis"] = [{"t": d.strftime("%Y-%m-%d"), "k": round(float(x), 2)} for d, x in c_all.tail(5).items()]
    return out


def breadth() -> dict:
    if not os.path.exists(TICKERS_FILE):
        return {"not": "tickers.txt yok"}
    with open(TICKERS_FILE, encoding="utf-8") as f:
        tickers = [t.strip() for t in f if t.strip() and not t.startswith("#")]
    if not tickers:
        return {"not": "tickers.txt boş"}
    df = yf.download(tickers, period="10d", interval="1d", auto_adjust=False, progress=False, group_by="ticker")
    up = down = ld = lu = 0; detail = {}
    for t in tickers:
        try:
            c = df[t]["Close"].dropna()
            chg = (float(c.iloc[-1]) / float(c.iloc[-2]) - 1) * 100
        except Exception:
            continue
        detail[t] = round(chg, 2)
        up += chg > 0; down += chg < 0; ld += chg <= -9.5; lu += chg >= 9.5
    n = len(detail)
    return {"hisse_sayisi": n, "yukselen": int(up), "dusen": int(down),
            "tabana_kilitli": int(ld), "tavana_kilitli": int(lu),
            "yukselen_orani_pct": round(up / n * 100, 1) if n else None, "detay": detail}


def main():
    R = {"uretim_zamani_tr": NOW_TR.strftime("%Y-%m-%d %H:%M:%S"),
         "not": "Günlük göstergeler tamamlanmış barlarla; son bar kısmiyse 'rsi14_anlik' ayrı verilir.",
         "kaynak": "Yahoo Finance"}

    # BIST
    R["bist100"] = basic_block(BIST["bist100"])
    R["bist30"] = basic_block(BIST["bist30"])
    R["sektor"] = {k: basic_block(v, 120, with_ma=False) for k, v in SEKTOR.items()}
    R["genislik"] = breadth()

    # Küresel / döviz / altın
    R["kuresel"] = {k: basic_block(v, 300, with_ma=False) for k, v in KURESEL.items()}
    R["doviz"] = {k: basic_block(v, 300, with_ma=False) for k, v in DOVIZ.items()}
    R["altin"] = {k: basic_block(v, 300, with_ma=False) for k, v in ALTIN.items()}
    try:
        ons = R["altin"]["ons_altin"]["son_fiyat"]; usd = R["doviz"]["usdtry"]["son_fiyat"]
        R["altin"]["gram_altin_hesap"] = round(ons * usd / 31.1035, 2)
    except Exception:
        pass

    # Tetik bayrakları
    b = R["bist100"]; T = {}
    try:
        fiyat = b["son_fiyat"]
        T["korunan_taban_mesafe_pct"] = pct(fiyat, LEVELS["korunan_taban"])
        T["tez_cizgisi_mesafe_pct"] = pct(fiyat, LEVELS["tez_cizgisi_haftalik"])
        T["k3_tetik_13000_alti_kapanis"] = bool(fiyat < LEVELS["korunan_taban"]) and not b["son_bar_kismi_mi"]
        T["k3_yaklasiyor_anlik"] = bool(fiyat < LEVELS["korunan_taban"]) and b["son_bar_kismi_mi"]
        hk = b.get("haftalik_kapanis", {}).get("bu_hafta_son")
        T["tez_cizgisi_haftalik_kirildi"] = bool(hk and hk < LEVELS["tez_cizgisi_haftalik"])
        last3 = [x["k"] for x in b["son_5_kapanis"][-3:]]
        T["korunan_taban_3gun"] = all(12900 <= x <= 13500 for x in last3)
        ma200 = b.get("hareketli_ortalamalar", {}).get("sma200")
        T["ma200_ustu"] = bool(ma200 and fiyat > ma200)
        # Radar 7 proxy: banka endeksi endeksten ne kadar ayrışıyor
        bk = R["sektor"]["banka"].get("gunluk_degisim_pct"); ix = b.get("gunluk_degisim_pct")
        if bk is not None and ix is not None:
            T["banka_minus_endeks_pct"] = round(bk - ix, 2)
            T["kamu_alim_proxy"] = "GÜÇLÜ" if bk - ix > 2 else ("VAR" if bk - ix > 0.7 else "YOK")
        b30 = R["bist30"].get("gunluk_degisim_pct")
        if b30 is not None and ix is not None:
            T["bist30_minus_bist100_pct"] = round(b30 - ix, 2)
        # Küresel tetikler
        nq = R["kuresel"]["nasdaq"].get("zirveden_pct")
        T["nasdaq_zirveden_pct"] = nq
        T["nasdaq_duzeltme_tetik"] = bool(nq is not None and nq <= NASDAQ_DUZELTME_ESIK)
        au = R["altin"]["ons_altin"].get("zirveden_pct")
        T["altin_zirveden_pct"] = au
        T["altin_duzeltme_tetik"] = bool(au is not None and au <= ALTIN_DUZELTME_ESIK)
        T["vix"] = R["kuresel"]["vix"].get("son_fiyat")
        T["genislik_tabana_kilitli"] = R["genislik"].get("tabana_kilitli")
    except Exception as e:
        T["hata"] = str(e)
    R["tetikler"] = T

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, indent=2)
    print(json.dumps(R["tetikler"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
