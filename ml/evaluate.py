import argparse,json
import pandas as pd
from sklearn.metrics import mean_absolute_error,mean_squared_error
import joblib
def main():
 p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--model',required=True);a=p.parse_args();d=pd.read_csv(a.input,parse_dates=['timestamp']).sort_values('timestamp');d['hour']=d.timestamp.dt.hour;d['dayofyear']=d.timestamp.dt.dayofyear;d['ac_power_lag_1']=d['ac_power_w'].shift(1);d['ac_power_rolling_3']=d['ac_power_w'].shift(1).rolling(3,min_periods=1).mean();bundle=joblib.load(a.model);data=d.dropna(subset=['ac_power_w']);cut=int(len(data)*.85);test=data.iloc[cut:];
 if test.empty:raise SystemExit('No held-out test rows available.')
 pred=bundle['model'].predict(test[bundle['features']]);print(json.dumps({'test_count':len(test),'mae_w':mean_absolute_error(test.ac_power_w,pred),'rmse_w':mean_squared_error(test.ac_power_w,pred)**.5,'metrics_scope':'held-out chronological tail'}))
if __name__=='__main__':main()

