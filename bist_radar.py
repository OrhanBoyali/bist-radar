#!/usr/bin/env python3
"""
BIST RADAR — günlük teknik veri üretici
Yahoo Finance'ten BIST 100 / BIST 30 günlük verisini çeker,
RSI(14, Wilder), MA50/MA200 (basit+üssel), ATR(14), haftalık kapanış,
kritik seviyelere mesafe ve (opsiyonel) genişlik hesaplar → output/radar.json

Zaman dilimi: SADECE GÜNLÜK. Saatlik karışıklık yok.
"""

import json
import os
from datetime import datetime, timezone, timedelta

import pandas as pd
import yfinance as yf

# --- AYARLAR --------------------------------------------------------------
INDEX_TICKER = "XU100.IS"      # BIST 100
INDEX30_TICKER = "XU030.IS"    # BIST 30
LOOKBACK_DAYS = 400            # MA200 için yeterli tarih
LEVELS = {                     # sistemdeki kritik seviyeler (ana kayıttan)
    "korunan_taban": 13000,
    "tez_cizgisi_haftalik": 12600,
}
TICKERS_FILE = "tickers.txt"   # genişlik için hisse listesi (opsiyonel)
OUTPUT_FILE = "output/radar.json"
TR_TZ = timezone(timedelta(hours=3))


# --- HESAPLAR -------------------------------------------------------------
def rsi_wilder(close: pd.Series, period: int = 14) -> float:
    """Wilder yöntemiyle RSI — investing.com ile aynı tanım."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 2)


def atr(df: pd.DataFrame, period: int = 14) -> float:
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return round(float(tr.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]), 2)


def weekly_close(df: pd.DataFrame) -> dict:
    """Son tamamlanmış haftanın kapanışı + içinde bulunulan haftanın son kapanışı."""
    wk = df["Close"].resample("W-FRI").last().dropna()
    if len(wk) < 2:
        return {}
    return {
        "son_tamamlanan_hafta_kapanis": round(float(wk.iloc[-2]), 2),
        "bu_hafta_son_kapanis": round(float(wk.iloc[-1]), 2),
    }


def summarize_index(ticker: str) -> dict:
    df = yf.download(ticker, period=f"{LOOKBACK_DAYS}d", interval="1d",
                     auto_adjust=False, progress=False)
    if df.empty:
        return {"hata": f"{ticker} verisi çekilemedi"}
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna(subset=["Close"])
    close = df["Close"]
    last = float(close.iloc[-1])
    prev = float(close.iloc[-2])

    ma = {}
    for n in (5, 10, 20, 50, 100, 200):
        if len(close) >= n:
            ma[f"sma{n}"] = round(float(close.rolling(n).mean().iloc[-1]), 2)
            ma[f"ema{n}"] = round(float(close.ewm(span=n, adjust=False).mean().iloc[-1]), 2)

    out = {
        "ticker": ticker,
        "son_kapanis_tarihi": close.index[-1].strftime("%Y-%m-%d"),
        "kapanis": round(last, 2),
        "gunluk_degisim_pct": round((last / prev - 1) * 100, 2),
        "gun_ici_dusuk": round(float(df["Low"].iloc[-1]), 2),
        "gun_ici_yuksek": round(float(df["High"].iloc[-1]), 2),
        "rsi14_gunluk": rsi_wilder(close),
        "atr14": atr(df),
        "hareketli_ortalamalar": ma,
        "haftalik": weekly_close(df),
        "son_5_kapanis": [round(float(x), 2) for x in close.tail(5)],
        "son_5_kapanis_tarih": [d.strftime("%Y-%m-%d") for d in close.tail(5).index],
    }

    # Sistem seviyelerine mesafe
    if ticker == INDEX_TICKER:
        dist = {}
        for name, lvl in LEVELS.items():
            dist[name] = {"seviye": lvl, "mesafe_pct": round((last / lvl - 1) * 100, 2)}
        if "sma200" in ma:
            dist["ma200_basit"] = {"seviye": ma["sma200"],
                                   "mesafe_pct": round((last / ma["sma200"] - 1) * 100, 2)}
        out["seviyelere_mesafe"] = dist
        # Korunan taban testi: son 3 kapanış 13.000-13.400 bandında mı?
        last3 = close.tail(3)
        out["korunan_taban_3gun"] = bool(((last3 >= 12900) & (last3 <= 13500)).all())
    return out


def breadth() -> dict:
    """Genişlik: tickers.txt varsa her hissenin günlük değişimini ölçer."""
    if not os.path.exists(TICKERS_FILE):
        return {"not": "tickers.txt yok — genişlik hesaplanmadı"}
    with open(TICKERS_FILE, encoding="utf-8") as f:
        tickers = [t.strip() for t in f if t.strip() and not t.startswith("#")]
    if not tickers:
        return {"not": "tickers.txt boş"}
    df = yf.download(tickers, period="10d", interval="1d", auto_adjust=False,
                     progress=False, group_by="ticker")
    up = down = limit_down = limit_up = 0
    detail = {}
    for t in tickers:
        try:
            c = df[t]["Close"].dropna()
            chg = (float(c.iloc[-1]) / float(c.iloc[-2]) - 1) * 100
        except Exception:
            continue
        detail[t] = round(chg, 2)
        if chg > 0: up += 1
        elif chg < 0: down += 1
        if chg <= -9.5: limit_down += 1
        if chg >= 9.5: limit_up += 1
    n = len(detail)
    return {
        "hisse_sayisi": n,
        "yukselen": up,
        "dusen": down,
        "tabana_kilitli_(<=-9.5%)": limit_down,
        "tavana_kilitli_(>=9.5%)": limit_up,
        "yukselen_orani_pct": round(up / n * 100, 1) if n else None,
        "detay": detail,
    }


def main():
    result = {
        "uretim_zamani_tr": datetime.now(TR_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "zaman_dilimi": "GÜNLÜK (1d) — saatlik değil",
        "kaynak": "Yahoo Finance (yfinance)",
        "bist100": summarize_index(INDEX_TICKER),
        "bist30": summarize_index(INDEX30_TICKER),
        "genislik": breadth(),
    }
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
