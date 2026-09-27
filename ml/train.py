import argparse, json
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
import joblib

FEATURES=["ghi_wm2","irradiance_poa_wm2","ambient_temp_c","wind_speed_ms","cloud_cover_pct","hour","dayofyear","ac_power_lag_1","ac_power_rolling_3"]
def main():
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    d=pd.read_csv(a.input,parse_dates=['timestamp']).sort_values('timestamp')
    if 'ac_power_w' not in d:raise SystemExit('Need ac_power_w target; no model trained.')
    ts=d.timestamp; d['hour']=ts.dt.hour;d['dayofyear']=ts.dt.dayofyear
    # Shifted production features are observable at issue time; current target
    # power is intentionally excluded to prevent target leakage.
    d['ac_power_lag_1']=d['ac_power_w'].shift(1)
    d['ac_power_rolling_3']=d['ac_power_w'].shift(1).rolling(3,min_periods=1).mean()
    features=[c for c in FEATURES if c in d]
    data=d.dropna(subset=['ac_power_w']); n=len(data)
    if n<30:raise SystemExit('Need at least 30 valid time-ordered records for the chronological split.')
    i=int(n*.7);j=int(n*.85);x=data[features];y=data.ac_power_w
    model=make_pipeline(SimpleImputer(),StandardScaler(),HistGradientBoostingRegressor(max_iter=150,random_state=42))
    model.fit(x.iloc[:i],y.iloc[:i]); pred=model.predict(x.iloc[i:j]); mae=mean_absolute_error(y.iloc[i:j],pred)
    payload={'model':model,'features':features,'split_counts':{'train':i,'validation':j-i,'test':n-j},'validation_mae_w':mae,'feature_version':'v1','target':'ac_power_w','time_ordered':True}
    joblib.dump(payload,a.output); print(json.dumps({k:v for k,v in payload.items() if k not in ('model',)},default=str))
if __name__=='__main__':main()

