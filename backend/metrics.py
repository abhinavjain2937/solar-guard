def energy_kwh(rows):
    if any(r.get("energy_wh") is not None for r in rows):
        return sum(float(r.get("energy_wh") or 0) for r in rows) / 1000
    return None

def specific_yield_kwh_per_kwp(energy_kwh_value, capacity_kw):
    return energy_kwh_value / capacity_kw if energy_kwh_value is not None and capacity_kw > 0 else None

def capacity_factor(energy_kwh_value, capacity_kw, interval_hours):
    return energy_kwh_value / (capacity_kw * interval_hours) * 100 if energy_kwh_value is not None and capacity_kw > 0 and interval_hours > 0 else None

def actual_vs_expected_pct(actual_kwh, expected_kwh):
    return actual_kwh / expected_kwh * 100 if actual_kwh is not None and expected_kwh and expected_kwh > 0 else None

def performance_ratio(actual_kwh, poa_irradiation_kwh_m2, capacity_kw):
    denom = poa_irradiation_kwh_m2 * capacity_kw
    return actual_kwh / denom * 100 if actual_kwh is not None and denom > 0 else None

def inverter_efficiency(ac_power_w, dc_power_w):
    return ac_power_w / dc_power_w * 100 if ac_power_w is not None and dc_power_w and dc_power_w > 0 else None

def data_quality_score(row):
    keys = ("ac_power_w", "energy_wh", "dc_power_w", "irradiance_poa_wm2", "ghi_wm2", "ambient_temp_c", "inverter_status")
    return round(100 * sum(row.get(k) is not None for k in keys) / len(keys), 1)

