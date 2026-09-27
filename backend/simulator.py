from dataclasses import dataclass


@dataclass
class SystemEstimate:
    dc_capacity_kw: float
    effective_ac_capacity_kw: float
    daily_kwh: float
    monthly_kwh: float
    annual_kwh: float
    annual_savings_inr: float
    monthly_savings_inr: float
    annual_co2_avoided_kg: float | None
    payback_years: float | None


def estimate_system(*, dc_capacity_kw: float, peak_sun_hours: float,
                    losses_pct: float, inverter_capacity_kw: float | None,
                    tariff_inr_per_kwh: float, export_tariff_inr_per_kwh: float,
                    self_consumption_pct: float, grid_co2_kg_per_kwh: float | None,
                    installed_cost_inr: float | None, monthly_bill_inr: float | None = None):
    """Transparent calculator, not a PV physics or weather simulation."""
    ac_kw = min(dc_capacity_kw, inverter_capacity_kw) if inverter_capacity_kw else dc_capacity_kw
    daily = ac_kw * peak_sun_hours * (1 - losses_pct / 100)
    annual = daily * 365
    monthly = daily * 30
    consumed = annual * self_consumption_pct / 100
    exported = annual - consumed
    annual_savings = consumed * tariff_inr_per_kwh + exported * export_tariff_inr_per_kwh
    if monthly_bill_inr is not None:
        annual_savings = min(annual_savings, monthly_bill_inr * 12)
    monthly_savings = annual_savings / 12
    payback = installed_cost_inr / annual_savings if installed_cost_inr and annual_savings > 0 else None
    co2 = consumed * grid_co2_kg_per_kwh if grid_co2_kg_per_kwh is not None else None
    return SystemEstimate(dc_capacity_kw, ac_kw, daily, monthly, annual, annual_savings,
                          monthly_savings, co2, payback)


def as_dict(estimate: SystemEstimate):
    return {key: round(value, 2) if isinstance(value, float) else value
            for key, value in estimate.__dict__.items()}
