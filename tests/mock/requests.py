"""Sahte requests — Fonoloji API'sini taklit eder. Sadece test düzeneğinde kullanılır."""
import pandas as pd

class _Resp:
    def __init__(self, data, status=200):
        self._d, self.status_code, self.headers = data, status, {}
    def json(self): return self._d
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")

def _son_is_gunu():
    return (pd.Timestamp.today().normalize() - pd.offsets.BDay(1)).date()

def get(url, params=None, headers=None, timeout=20):
    code = url.rstrip("/").split("/funds/")[-1].split("/")[0]
    son = _son_is_gunu()
    if url.endswith("/history"):
        idx = pd.bdate_range(end=son, periods=250)
        if code == "TIE":                      # TEST: 3 iş günü bayat fiyat
            idx = idx[:-3]
        n = len(idx)
        katsayi = 1.003 if code == "IJV" else 1.0   # TEST: IJV iki kaynakta farklı → çapraz uyarı
        pts = []
        for i, d in enumerate(idx):
            price = 5.0 * (1.03 ** (i / 22)) * katsayi            # ayda ~%3 (para piyasası benzeri)
            if code == "AKU" and i == n - 1:
                price *= 1.05                                      # TEST: son gün +%5 → endeksten kopma
            pts.append({"date": d.strftime("%Y-%m-%d"), "price": round(price, 6),
                        "total_value": 1e9 * (0.75 if i > n - 12 else 1.0),   # TEST: son 2 haftada %25 küçülme
                        "investor_count": 10000 - (2000 if i > n - 12 else 0)})
        return _Resp({"code": code, "period": "1y", "points": pts})
    aum = 1e8 if code == "KCK" else 7.5e8                        # KCK: küçük fon senaryosu
    durum = "TEFAS'TA İŞLEME KAPALI" if code == "TKP" else "AKTİF" # TKP: kapalı fon senaryosu
    return _Resp({"fund": {"code": code, "name": f"{code} FONU", "category": "Para Piyasası", "risk_score": 1,
                           "buy_valor": 0, "sell_valor": 0, "current_price": 5.5, "current_date": str(son),
                           "return_1y": 0.47, "aum": aum, "investor_count": 9970, "trading_status": durum,
                           "management_company": "Test Portföy"},
                  "portfolio": {"stock": 0, "cash": 100}})
