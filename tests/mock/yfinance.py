import numpy as np, pandas as pd
from datetime import datetime, timedelta
def download(t, period="300d", interval="1d", **k):
    son = (pd.Timestamp.today().normalize() - pd.offsets.BDay(1)).date()
    if t == "^IXIC":                                   # TEST: Yahoo bayat veri senaryosu (10 gün geride)
        son = (pd.Timestamp.today().normalize() - pd.Timedelta(days=10)).date()
    idx = pd.bdate_range(end=son, periods=260)
    c = np.linspace(100, 110, len(idx))                # BZ=F son değer 110 → borsapy 108 ile %1,8 fark (uyarı YOK)
    return pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c, "Volume": 1000}, index=idx)
