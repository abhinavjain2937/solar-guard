from datetime import datetime, timedelta, timezone
from backend.metrics import energy_kwh, specific_yield_kwh_per_kwp, actual_vs_expected_pct, inverter_efficiency

def expected_power_w(row, site, loss_factor=0.14):
    irradiance = row.get("irradiance_poa_wm2")
    basis = "measured_poa" if irradiance is not None else None
    if irradiance is None and row.get("ghi_wm2") is not None:
        irradiance, basis = row["ghi_wm2"], "ghi_proxy_not_poa"
    if irradiance is None: return None, None
    return max(0, site.capacity_kw * 1000 * irradiance / 1000 * (1-loss_factor)), basis

def summarize(rows, site):
    e = energy_kwh(rows)
    power_expected = [expected_power_w(r,site) for r in rows]
    expected_wh = 0.0
    expected_intervals = 0
    # Integrate estimated power to the next reading when the gap is <= 6 h.
    for idx, (row, (power, _basis)) in enumerate(zip(rows, power_expected)):
        if power is None or idx + 1 == len(rows):
            continue
        try:
            t0 = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(rows[idx + 1]["timestamp"].replace("Z", "+00:00"))
            hours = (t1 - t0).total_seconds() / 3600
        except (KeyError, ValueError):
            continue
        if 0 < hours <= 6:
            expected_wh += power * hours
            expected_intervals += 1
    expected = expected_wh / 1000 if expected_intervals else None
    history_days = 0.0
    if len(rows) > 1:
        try:
            first=datetime.fromisoformat(rows[0]["timestamp"].replace("Z","+00:00"))
            last=datetime.fromisoformat(rows[-1]["timestamp"].replace("Z","+00:00"))
            history_days=max(0.0,(last-first).total_seconds()/86400)
        except (KeyError,TypeError,ValueError): pass
    return {"samples": len(rows), "history_days": round(history_days,1), "energy_kwh": e, "specific_yield_kwh_per_kwp": specific_yield_kwh_per_kwp(e,site.capacity_kw),
            "actual_vs_expected_pct": actual_vs_expected_pct(e,expected), "expected_energy_kwh": expected,
            "baseline_note": "Configured capacity × irradiance × 0.86; GHI is a proxy when POA is absent. Not pvlib-calibrated.",
            "irradiance_basis": sorted({b for _,b in power_expected if b}),
            "mean_inverter_efficiency_pct": _mean([inverter_efficiency(r.get("ac_power_w"),r.get("dc_power_w")) for r in rows]),
            "mean_data_quality_score": _mean([r.get("data_quality_score") for r in rows])}

def _mean(xs):
    vals=[x for x in xs if x is not None]
    return sum(vals)/len(vals) if vals else None

def series(rows, site, limit=500):
    selected = rows[-limit:]
    out = []
    for row in selected:
        expected, basis = expected_power_w(row, site)
        out.append({"timestamp": row.get("timestamp"), "actual_power_w": row.get("ac_power_w"),
                    "expected_power_w": round(expected, 1) if expected is not None else None,
                    "expected_basis": basis})
    return out

def investigations(rows, site):
    flagged=[]; run=[]
    for row in rows:
        p,b=expected_power_w(row,site)
        actual=row.get("ac_power_w")
        threshold=max(100, site.capacity_kw*1000*0.10)
        anomalous = p is not None and p > threshold and actual is not None and actual < p*0.65 and (row.get("data_quality_score") or 0)>=50
        run.append((row,p,b,anomalous))
        if not anomalous and len(run)>=2:
            _emit(run,flagged); run=[]
    _emit(run,flagged)
    return flagged

def _emit(run, out):
    chosen=[x for x in run if x[3]]
    if len(chosen)>=2:
        r,p,b,_=chosen[-1]
        out.append({"start":chosen[0][0]["timestamp"],"end":r["timestamp"],"duration_samples":len(chosen),
                    "actual_power_w":r.get("ac_power_w"),"expected_power_w":round(p,1),"residual_w":round((r.get("ac_power_w") or 0)-p,1),
                    "data_quality_score":r.get("data_quality_score"),"status":r.get("inverter_status"),"fault_code":r.get("fault_code"),
                    "evidence": "Persistent measured AC power below irradiance-capacity baseline; investigation only, not a confirmed fault.","irradiance_basis":b})

def persistence_forecast(rows, site, hours=24):
    if not rows: return []
    recent=rows[-72:]; values=[r.get("ac_power_w") for r in recent if r.get("ac_power_w") is not None]
    if not values: return []
    level=sum(values)/len(values)
    now=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)
    return [{"timestamp":(now+timedelta(hours=i+1)).isoformat(),"power_w":round(level,1),"lower_w":0,"upper_w":round(max(values),1),
             "method":"recent-mean persistence","uncertainty_note":"Range is historical min/max, not a calibrated prediction interval."} for i in range(min(48,max(6,hours)))]

