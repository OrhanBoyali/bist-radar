"""Sahte borsapy — gerçek API yerine kontrollü veri döndürür."""
import numpy as np, pandas as pd
from datetime import datetime, timedelta
def _ohlc(n=300, start=14000, end=13250, seed=1):
    idx = pd.bdate_range(end=datetime.now().date() - timedelta(days=1), periods=n)
    rng = np.random.default_rng(seed)
    c = np.linspace(start, end, n) + rng.normal(0, 60, n)
    return pd.DataFrame({"Open": c, "High": c + 80, "Low": c - 80, "Close": c, "Volume": rng.integers(1e6, 2e6, n)}, index=idx)
class Index:
    def __init__(self, s): self.s = s
    def history(self, period="1y"):
        if self.s == "XU100":   # son iki kapanış MA200'ün üstünde olsun → dönüş kapısı teste açık
            df = _ohlc(); df.iloc[-2:, df.columns.get_loc("Close")] = [13700, 13720]; return df
        return _ohlc(seed=hash(self.s) % 100)
    @property
    def component_symbols(self): return [f"H{i}" for i in range(30)]
class Ticker:
    def __init__(self, s): self.s = s
    @property
    def fast_info(self): return {"foreign_ratio": 40.0}
def scan(index, cond, limit=800):
    n = 30 if index == "XU030" else 580
    ch = np.r_[np.full(int(n*0.6), 1.0), np.full(n - int(n*0.6), -0.5)]   # %60 yükselen
    return pd.DataFrame({"symbol": range(n), "change_percent": ch})
class Fund:
    def __init__(self, c): self.c = c
    def history(self, period="3mo"):
        idx = pd.bdate_range(end=datetime.now().date(), periods=70)
        p = np.linspace(5.0, 5.5, 70)
        if self.c == "DLY": p[-1] = 0.0                      # TEST 1: TEFAS sıfır fiyat hatası
        if self.c == "YLB": p[-1] = p[-2] * 1.30              # TEST 2: %30 şüpheli sıçrama
        return pd.DataFrame({"Price": p, "FundSize": np.nan, "Investors": np.nan}, index=idx)
    @property
    def info(self): return {"fund_size": 1e9, "investor_count": 1000, "sell_valor": 0}
    @property
    def management_fee(self): return 1.0
class Inflation:
    def latest(self): return {"monthly": 1.84}
def bonds(): return pd.DataFrame({"maturity": ["2Y", "10Y"], "yield": [39.7, 35.1], "change_pct": [0.1, 0.2]})
class FX:
    def __init__(self, k): self.k = k
    @property
    def current(self): return {"last": {"USD": 48.83, "EUR": 57.0}.get(self.k, 6800.0)}
    def history(self, period="1y"): return _ohlc(250, 7500, 6800)
def economic_calendar(**k): return pd.DataFrame({"Date": ["2026-09-24"], "Event": ["test"]})
class EconomicCalendar:
    def events(self, **k): return pd.DataFrame({"Date": ["2026-09-24"], "Event": ["test"]})
def evds_series(code, start=None, frequency=None, period=None):
    freq = {"weekly": "W-FRI", "daily": "B"}.get(frequency, "MS")
    idx = pd.date_range(end=datetime.now(), periods=60, freq=freq); n = len(idx)
    val = {"TP.APIFON4": 37.0, "TP.MKNETHAR.M7": 277.67, "TP.TUKFIY2025.GENEL": None}.get(code, 100.0)
    if code == "TP.TUKFIY2025.GENEL": v = 100 * (1.0184 ** np.arange(n))
    elif code == "TP.APIFON4": v = np.r_[np.full(n - 20, 40.0), np.full(20, 37.0)]
    else: v = np.full(n, val)
    return pd.DataFrame({code: v}, index=idx)
class EVDS:
    def series_in_group(self, g):
        return pd.DataFrame({"SERIE_CODE": ["TP.PKAUO.S05.C.U"], "SERIE_NAME": ["12 ay sonrası ABD Doları kuru beklentisi"]})
    def datagroups(self): return pd.DataFrame()
def evds_search(t): return pd.DataFrame()
