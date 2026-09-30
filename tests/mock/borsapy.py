"""Sahte borsapy — gerçek API yerine kontrollü veri döndürür."""
import numpy as np, pandas as pd
from datetime import datetime, timedelta
def _son_is_gunu():
    """Hangi gün çalışırsa çalışsın (hafta sonu, pazartesi) son tamamlanmış iş günü."""
    return (pd.Timestamp.today().normalize() - pd.offsets.BDay(1)).date()
def _ohlc(n=300, start=14000, end=13250, seed=1):
    idx = pd.bdate_range(end=_son_is_gunu(), periods=n); n = len(idx)
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
        idx = pd.bdate_range(end=_son_is_gunu(), periods=70)
        p = np.linspace(5.0, 5.5, len(idx))
        if self.c == "DLY": p[-1] = 0.0                      # TEST 1: TEFAS sıfır fiyat hatası
        if self.c == "YLB": p[-1] = p[-2] * 1.30              # TEST 2: %30 şüpheli sıçrama
        if self.c == "AKU": p[-1] = p[-2] * 1.05              # TEST: endeks +%0,x iken fon +%5 → takip sapması
        if self.c == "TIE": p = p[:-3]; idx = idx[:-3]        # TEST: 3 iş günü bayat fiyat
        return pd.DataFrame({"Price": p, "FundSize": np.full(len(idx), np.nan), "Investors": np.full(len(idx), np.nan)}, index=idx)
    @property
    def info(self):
        size = 1e8 if self.c == "KCK" else 1e9           # KCK: küçük fon senaryosu
        return {"fund_size": size, "investor_count": 1000, "sell_valor": 0, "risk_value": 1}
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

def screen_funds(fund_type="YAT", limit=50, **k):
    """Sahte fon evreni — bilinçli senaryolar içerir."""
    rows = [
        # para piyasası: bizimkiler
        ("YLB", "YAPI KREDİ PORTFÖY PARA PİYASASI FONU", 3.06, 9.8, 46.5),
        ("IJV", "İSTANBUL PORTFÖY PARA PİYASASI FONU", 3.13, 10.0, 47.2),
        ("DLY", "DENİZ PORTFÖY PARA PİYASASI FONU", 3.02, 9.7, 45.9),
        ("ZBJ", "ZİRAAT PORTFÖY BAŞAK PARA PİYASASI FONU", 3.10, 9.9, 47.0),  # 30 Eyl: portföye girdi
        ("ZPX", "ZİRAAT PORTFÖY PARA PİYASASI FONU", 3.30, 10.6, 49.5),        # gerçek aday
        ("KCK", "KÜÇÜK PORTFÖY PARA PİYASASI FONU", 3.35, 10.7, 50.0),         # aday ama küçük
        ("SUS", "ÖRNEK PORTFÖY PARA PİYASASI FONU", 4.20, 12.5, 60.0),         # şüpheli yüksek
        ("TP2", "TERA PORTFÖY PARA PİYASASI FONU", 4.10, 12.4, 60.2),          # tasfiye kurucu
        ("SRB", "XYZ PORTFÖY PARA PİYASASI SERBEST FON", 3.50, 11.0, 52.0),    # nitelikli, gruba girmez
        ("ZSP", "KUVEYT TÜRK PORTFÖY İKİNCİ SEPET HESAP PARA PİYASASI KATILIM FONU", 3.40, 10.5, 62.0),  # TEFAS'ta kapalı
        ("Y1O", "ÖRNEK2 PORTFÖY PARA PİYASASI FONU", 3.20, 10.3, 60.0),       # aylık normal, yıllık aşırı yüksek
        ("BY1", "BÜYÜK1 PORTFÖY PARA PİYASASI FONU", 3.25, 10.5, 49.0),       # 3'ten fazla aday senaryosu
        ("BY2", "BÜYÜK2 PORTFÖY PARA PİYASASI FONU", 3.25, 10.5, 48.8),
        ("BY3", "BÜYÜK3 PORTFÖY PARA PİYASASI FONU", 3.25, 10.5, 48.5),
        ("TKP", "KAPALI PORTFÖY PARA PİYASASI FONU", 3.28, 10.55, 49.2),     # künyede TEFAS'ta kapalı
        # BIST 30 endeks
        ("TIE", "İŞ PORTFÖY BIST 30 ENDEKSİ HİSSE SENEDİ FONU", -5.02, 2.0, 31.28),
        ("AKU", "AK PORTFÖY BIST 30 ENDEKSİ HİSSE SENEDİ FONU", -3.54, 3.0, 35.68),
        ("GBX", "GARANTİ PORTFÖY BIST 30 ENDEKSİ HİSSE SENEDİ FONU", -3.00, 3.8, 38.0),
        ("DZE", "DENİZ PORTFÖY BIST 100 ENDEKSİ HİSSE SENEDİ FONU", -4.0, 2.5, 33.0),
        ("IDH", "İŞ PORTFÖY BIST 100 DIŞI ŞİRKETLER HİSSE SENEDİ FONU", -8.0, -5.0, 20.0),
    ]
    rows += [(f"F{i:02d}", f"DOLGU PORTFÖY BORÇLANMA ARAÇLARI FONU {i}", 2.5, 8.0, 40.0) for i in range(50)]
    def kat(n):
        if "PARA PİYASASI" in n: return "Para Piyasası Fonu"
        if "HİSSE" in n: return "Hisse Senedi Fonu"
        return "Borçlanma Araçları Fonu"
    return pd.DataFrame([{"fund_code": c, "name": n, "fund_type": kat(n), "return_1m": a, "return_3m": b,
                          "return_1y": y} for c, n, a, b, y in rows])
