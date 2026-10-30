"""Sahte requests — Fonoloji API'sini taklit eder. Sadece test düzeneğinde kullanılır."""
import pandas as pd

def _portfoy(code):
    import os      # 20 Eki: RADAR_MOCK_OSBA="YLB:12,IJV:30" → o fonların özel sektör tahvili payı
    for parca in (os.environ.get("RADAR_MOCK_OSBA") or "").split(","):
        if ":" in parca and parca.split(":")[0] == code:
            p = float(parca.split(":")[1])
            return {"corporate_bond": p, "government_bond": 10, "cash": 90 - p, "stock": 0}
    if code.startswith("KB") or code == "PB1":
        return {"government_bond": 85, "cash": 15}
    if code.startswith("OS"):
        return {"corporate_bond": 70, "government_bond": 10, "cash": 20}
    if code == "KNJ":
        return {"stock": 90, "cash": 10}
    return {"stock": 0, "cash": 100}

class _Resp:
    def __init__(self, data, status=200, headers=None, text=""):
        self._d, self.status_code, self.headers, self.text = data, status, (headers or {}), text
    def json(self): return self._d
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")

def _son_is_gunu():
    return (pd.Timestamp.today().normalize() - pd.offsets.BDay(1)).date()


def _sahte_verim(gun):
    """7 Eki: sahte 2 yıllık gösterge faizi (puan) — EVDS ve Fonoloji sahteleri AYNI yolu kullanır."""
    import math
    return 40.0 + 2.0 * math.sin(gun.toordinal() / 20.0)

_SURE = {"YOT": 1.5, "KB0": 4.0}      # 7 Eki: bilinen faiz duyarlılığı (yıl) → etkin süre testi

_SAYAC = [0]
_BIZIM = ("YLB", "IJV", "ZBJ", "BGP", "TIE", "AKU")

_DOVIZ_SAYFA = {   # 15 Eki: doviz.com/tahvil sayfası senaryoları
    "bot": "<html><head><title>Just a moment...</title></head><body>cf-chl</body></html>",
    "yeni": ("<html><head><title>Tahvil Faizleri</title></head><body><table class='yeni'><tbody>"
             "<tr><td>TR 2 Yıllık</td><td>39,58</td><td>%0,33</td></tr>"
             "<tr><td>TR 5 Yıllık</td><td>38,62</td><td>%0,78</td></tr>"
             "<tr><td>TR 10 Yıllık</td><td>35,52</td><td>%0,28</td></tr></tbody></table></body></html>")}

_ZA = set()

def get(url, params=None, headers=None, timeout=20):
    import os
    _kod = url.rstrip("/").split("/funds/")[-1].split("/")[0] if "/funds/" in url else None
    if _kod and _kod in (os.environ.get("RADAR_MOCK_FONO_TIMEOUT_HEP") or "").split(","):      # 15 Eki: Fonoloji hep zaman aşımı
        raise TimeoutError("HTTPSConnectionPool(host='fonoloji.com', port=443): Read timed out. (read timeout=20)")
    if _kod and _kod in (os.environ.get("RADAR_MOCK_FONO_TIMEOUT") or "").split(",") and _kod not in _ZA:
        _ZA.add(_kod)                                                                          # 15 Eki: tek seferlik zaman aşımı
        raise TimeoutError("HTTPSConnectionPool(host='fonoloji.com', port=443): Read timed out. (read timeout=20)")
    if "doviz.com/tahvil" in url:
        return _Resp({}, 200, {}, _DOVIZ_SAYFA.get(os.environ.get("RADAR_MOCK_DOVIZ_SAYFA") or "bot"))
    # 30 Eki: kripto borsaları (USDT/TL primi). Gerçek biçim: BtcTurk {"data":[{pair, pairNormalized, last, ...}]},
    # Paribu {"USDT_TL": {"last": ...}}. Resmi kur sahtesi: borsapy FX("USD") = 48,83.
    _usdt = round(48.83 * (1 + float(os.environ.get("RADAR_MOCK_USDT_PRIM") or 0.8) / 100), 4)
    if "api.btcturk.com" in url:
        if os.environ.get("RADAR_MOCK_BTCTURK_HATA"):
            raise ConnectionError("HTTPSConnectionPool(host='api.btcturk.com', port=443): Max retries exceeded")
        return _Resp({"data": [{"pair": "BTCTRY", "pairNormalized": "BTC_TRY", "last": 4100000.0, "bid": 4099000.0, "ask": 4101000.0},
                               {"pair": "USDTTRY", "pairNormalized": "USDT_TRY", "last": _usdt, "bid": _usdt - 0.01, "ask": _usdt + 0.01,
                                "numeratorSymbol": "USDT", "denominatorSymbol": "TRY"}], "success": True, "message": None, "code": 0})
    if "paribu.com/ticker" in url:
        return _Resp({"BTC_TL": {"last": 4100000.0, "lowestAsk": 4101000.0, "highestBid": 4099000.0},
                      "USDT_TL": {"last": _usdt, "lowestAsk": _usdt + 0.01, "highestBid": _usdt - 0.01}})
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
        p_tahvil = 5.0
        for i, d in enumerate(idx):
            price = 5.0 * (1.03 ** (i / 22)) * katsayi            # ayda ~%3 (para piyasası benzeri)
            if code in _SURE:                                      # tahvil: taşıma − süre × Δverim
                if i:
                    dy = (_sahte_verim(d.date()) - _sahte_verim(idx[i - 1].date())) / 100.0
                    p_tahvil *= (1 + 0.38 / 252 - _SURE[code] * dy)
                price = p_tahvil
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
