import numpy as np, pandas as pd
from datetime import datetime, timedelta
def download(t, period="300d", interval="1d", **k):
    son = (pd.Timestamp.today().normalize() - pd.offsets.BDay(1)).date()
    if t == "^IXIC":                                   # TEST: Yahoo bayat veri senaryosu (10 gün geride)
        son = (pd.Timestamp.today().normalize() - pd.Timedelta(days=10)).date()
    idx = pd.bdate_range(end=son, periods=260)
    c = np.linspace(100, 110, len(idx))                # BZ=F son değer 110 → borsapy 108 ile %1,8 fark (uyarı YOK)
    import os
    if t == "TUR" and os.environ.get("RADAR_MOCK_TUR_DUSUS"):     # 30 Eki: Türkiye ETF'i son 5 günde ~%12 düşer
        c[-5:] = c[-5:] * 0.88
    if t == "GC=F":     # 5 Kas: ons × TRY=X sahtesi (100→110) / 31,1035 ≈ borsapy gram sahtesi (7500→6800) → kalibrasyon ~1
        c = np.linspace(7500, 6800, len(idx)) * 31.1034768 / np.linspace(100, 110, len(idx))
        if os.environ.get("RADAR_MOCK_ONS_SICRAMA"):            # bugün ons +%3 (borsapy gram henüz dünkü değerde)
            c[-1] = c[-1] * 1.03
        if os.environ.get("RADAR_MOCK_ONS_BOZUK"):              # saçma ons değeri → canlı gram kullanılmamalı
            c = c / 10
    if t == "BZ=F" and os.environ.get("RADAR_MOCK_BRENT_GUNICI"):   # 9 Kas: petrol bugün −%5 (borsapy dünkü kapanışta)
        c[-1] = c[-2] * 0.95
    if t == "HYG" and os.environ.get("RADAR_MOCK_KREDI_STRES"):   # 30 Eki: yüksek getirili tahviller 1 ayda ~%6 düşer
        c[-22:] = c[-22:] * np.linspace(1.0, 0.94, 22)
    return pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c, "Volume": 1000}, index=idx)
