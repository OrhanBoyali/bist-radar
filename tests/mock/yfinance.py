import numpy as np, pandas as pd
from datetime import datetime, timedelta
def download(t, period="300d", interval="1d", **k):
    idx = pd.bdate_range(end=(pd.Timestamp.today().normalize() - pd.offsets.BDay(1)).date(), periods=260)
    c = np.linspace(100, 110, len(idx))
    return pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c, "Volume": 1000}, index=idx)
