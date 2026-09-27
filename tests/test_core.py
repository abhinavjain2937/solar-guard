import pytest
import asyncio
from types import SimpleNamespace
from backend.ingest import normalize_csv
from backend.metrics import energy_kwh,specific_yield_kwh_per_kwp,capacity_factor,actual_vs_expected_pct,inverter_efficiency,performance_ratio,data_quality_score
from backend.analytics import summarize, series
from backend.simulator import estimate_system
import backend.weather as weather

def test_csv_normalization_aliases_and_time():
    rows=normalize_csv(b'time,AC Power,Energy\n2026-01-01T10:00:00+05:30,500,1000\n')
    assert rows[0]['timestamp']=='2026-01-01T04:30:00+00:00';assert rows[0]['ac_power_w']==500;assert rows[0]['energy_wh']==1000
def test_csv_validation():
    with pytest.raises(ValueError):normalize_csv(b'AC Power\n500\n')
    with pytest.raises(ValueError):normalize_csv(b'timestamp,ac_power\nbad,4\n')
def test_metric_formulas():
    assert energy_kwh([{'energy_wh':1000},{'energy_wh':500}])==1.5
    assert specific_yield_kwh_per_kwp(6,3)==2
    assert capacity_factor(3,1,6)==50
    assert actual_vs_expected_pct(4,5)==80
    assert inverter_efficiency(900,1000)==90
    assert performance_ratio(4,5,1)==80
    assert data_quality_score({'ac_power_w':500})==pytest.approx(14.3,abs=.1)

def test_capacity_irradiance_baseline_is_labeled_and_integrated():
    site=SimpleNamespace(capacity_kw=1)
    rows=[{'timestamp':'2026-06-01T10:00:00+00:00','energy_wh':430,'ghi_wm2':1000,'ac_power_w':430,'data_quality_score':50},
          {'timestamp':'2026-06-01T11:00:00+00:00','energy_wh':430,'ghi_wm2':1000,'ac_power_w':430,'data_quality_score':50}]
    result=summarize(rows,site)
    assert result['expected_energy_kwh']==pytest.approx(.86)
    assert result['actual_vs_expected_pct']==pytest.approx(100)
    assert result['irradiance_basis']==['ghi_proxy_not_poa']
    assert len(series(rows,site))==2

def test_open_meteo_mapping_with_mocked_response(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'hourly': {'time':['2026-06-01T12:00'], 'temperature_2m':[30], 'cloud_cover':[20],
            'precipitation':[0], 'wind_speed_10m':[7.2], 'shortwave_radiation':[600], 'direct_radiation':[450], 'diffuse_radiation':[100]}}
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def get(self,*args,**kwargs): return Response()
    monkeypatch.setattr(weather.httpx, 'AsyncClient', lambda **kwargs: Client())
    site={'latitude':19.0,'longitude':72.0,'timezone':'Asia/Kolkata'}
    records=asyncio.run(weather.OpenMeteo().forecast(site,hours=1))
    assert records[0]['ghi_wm2']==600
    assert records[0]['wind_speed_ms']==pytest.approx(2)
    assert records[0]['irradiance_source']=='open_meteo_model_estimate'

def test_transparent_what_if_calculator():
    result=estimate_system(dc_capacity_kw=7,peak_sun_hours=5,losses_pct=14,
        inverter_capacity_kw=7,tariff_inr_per_kwh=8,export_tariff_inr_per_kwh=0,
        self_consumption_pct=100,grid_co2_kg_per_kwh=0.5,installed_cost_inr=800000)
    assert result.daily_kwh==pytest.approx(30.1)
    assert result.annual_kwh==pytest.approx(10986.5)
    assert result.annual_savings_inr==pytest.approx(87892)
    assert result.payback_years==pytest.approx(800000/87892)
    assert result.annual_co2_avoided_kg==pytest.approx(5493.25)

