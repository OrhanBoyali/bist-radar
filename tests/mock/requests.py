"""Sahte requests — Fonoloji API'sini taklit eder. Sadece test düzeneğinde kullanılır."""
import pandas as pd

def _portfoy(code):
    if code.startswith("KB") or code == "PB1":
        return {"government_bond": 85, "cash": 15}
    if code.startswith("OS"):
        return {"corporate_bond": 70, "government_bond": 10, "cash": 20}
    if code == "KNJ":
        return {"stock": 90, "cash": 10}
    return {"stock": 0, "cash": 100}

class _Resp:
    def __init__(self, data, status=200, headers=None):
        self._d, self.status_code, self.headers = data, status, (headers or {})
    def json(self): return self._d
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")

def _son_is_gunu():
    return (pd.Timestamp.today().normalize() - pd.offsets.BDay(1)).date()

_SAYAC = [0]
_BIZIM = ("YLB", "IJV", "ZBJ", "BGP", "TIE", "AKU")

def get(url, params=None, headers=None, timeout=20):
    import os
    code = url.rstrip("/").split("/funds/")[-1].split("/")[0]
    _SAYAC[0] += 1
    if _SAYAC[0] <= int(os.environ.get("RADAR_MOCK_429") or 0):            # 6 Eki: ilk N istek hız sınırı
        return _Resp({}, 429, {"retry-after": "0"})
    if os.environ.get("RADAR_MOCK_429_KUNYE") and not url.endswith("/history") and code not in _BIZIM:
        return _Resp({}, 429, {"retry-after": "0"})                         # künye istekleri sürekli engelli
    son = _son_is_gunu()
    if url.endswith("/history"):
        import os
        if (params or {}).get("period") not in (None, "1y"):      # 6 Eki: gerçekte sadece "1y" çalıştığı varsayımı
            raise ValueError(f"400 Bad Request: geçersiz periyot {(params or {}).get('period')}")
        if os.environ.get("RADAR_MOCK_HISTORY_HATA") and code not in ("YLB", "IJV", "ZBJ", "BGP", "TIE", "AKU"):   # portföy fonları (DLY artık izlemede)
            raise ValueError("500 Server Error: history")
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
                        # TEST: sektörün tamamı son 2 haftada %25 küçülüyor; BGP %55 (fona özgü çıkış senaryosu)
                        "total_value": 1e9 * ((0.45 if code == "BGP" else 0.75) if i > n - 12 else 1.0),
                        "investor_count": 10000 - (2000 if i > n - 12 else 0)})
        return _Resp({"code": code, "period": "1y", "points": pts})
    aum = 1e8 if code == "KCK" else 7.5e8                        # KCK: küçük fon senaryosu
    durum = "TEFAS'TA İŞLEME KAPALI" if code == "TKP" else "AKTİF" # TKP: kapalı fon senaryosu
    hisse = code in ("TIE", "AKU", "GBX", "DZE", "IDH")         # gerçekteki gibi: hisse fonu alış T+1, satış T+2
    return _Resp({"fund": {"code": code, "name": f"{code} FONU", "category": "Hisse Senedi" if hisse else "Para Piyasası",
                           "risk_score": 6 if hisse else 1,
                           "buy_valor": 1 if hisse else 0, "sell_valor": 2 if hisse else 0, "current_price": 5.5, "current_date": str(son),
                           "return_1y": 0.47, "aum": aum, "investor_count": 9970, "trading_status": durum,
                           "management_company": "Test Portföy"},
                  "portfolio": _portfoy(code)})
