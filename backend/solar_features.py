"""Manual solar monitoring features requested in SolarGuard requirement guide."""
from datetime import date, datetime, timedelta
import math
import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, delete

from backend.db import SessionLocal, SiteRow, DailyGenerationRow, MonthlyBillRow, WarrantyPointRow, SyntheticWarrantyRow

router = APIRouter(prefix="/api/v1/sites/{site_id}")


class DailyInput(BaseModel):
    day: date
    actual_kwh: float = Field(ge=0)


class BillInput(BaseModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    consumed_kwh: float = Field(ge=0)
    exported_kwh: float = Field(ge=0)
    import_tariff: float = Field(ge=0)
    export_tariff: float = Field(ge=0)
    export_credit_inr: float = Field(ge=0)
    self_use_pct: float = Field(default=60, ge=0, le=100)


class WarrantyInput(BaseModel):
    points: list[dict] = Field(min_length=2, max_length=30)


def owned_site(db, site_id, user_id):
    site = db.scalars(select(SiteRow).where(SiteRow.id == site_id, SiteRow.owner_id == user_id)).first()
    if not site:
        raise HTTPException(404, "Site not found")
    return site


async def archive_irradiance(site, start, end):
    """Return daily global radiation in kWh/m²; None means provider unavailable."""
    base = "https://archive-api.open-meteo.com/v1/archive"
    params = {"latitude": site.latitude, "longitude": site.longitude, "start_date": start,
              "end_date": end, "daily": "shortwave_radiation_sum", "timezone": site.timezone}
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.get(base, params=params)
            response.raise_for_status()
            daily = response.json().get("daily", {})
        return {d: (float(v) / 3.6 if v is not None else None)
                for d, v in zip(daily.get("time", []), daily.get("shortwave_radiation_sum", []))}
    except (httpx.HTTPError, ValueError, TypeError):
        return None


@router.post("/daily-generation")
def save_daily(site_id: int, payload: DailyInput, request: Request):
    with SessionLocal() as db:
        owned_site(db, site_id, request.state.user_id)
        row = db.scalars(select(DailyGenerationRow).where(DailyGenerationRow.site_id == site_id,
                                                            DailyGenerationRow.day == payload.day.isoformat())).first()
        if row:
            row.actual_kwh = payload.actual_kwh
            row.record_kind = "actual"
            row.source = "manual_entry"
        else:
            row = DailyGenerationRow(site_id=site_id, day=payload.day.isoformat(), actual_kwh=payload.actual_kwh,
                                     record_kind="actual", source="manual_entry")
            db.add(row)
        db.commit()
        return {"saved": True, "day": row.day, "actual_kwh": row.actual_kwh, "record_kind": "actual"}


@router.get("/daily-generation")
def daily_records(site_id: int, request: Request, days: int = 60):
    with SessionLocal() as db:
        owned_site(db, site_id, request.state.user_id)
        rows = db.scalars(select(DailyGenerationRow).where(DailyGenerationRow.site_id == site_id)
                          .order_by(DailyGenerationRow.day.desc()).limit(max(1, min(days, 365)))).all()
        return {"items": [{"day": r.day, "actual_kwh": r.actual_kwh, "record_kind": r.record_kind} for r in reversed(rows)]}


@router.post("/daily-generation/demo")
def seed_demo_generation(site_id: int, request: Request):
    """Create clearly labeled walkthrough rows; actual analytics never count these."""
    with SessionLocal() as db:
        site = owned_site(db, site_id, request.state.user_id)
        end = date.today()
        db.execute(delete(DailyGenerationRow).where(DailyGenerationRow.site_id == site_id,
                      DailyGenerationRow.record_kind == "synthetic_demo"))
        rows = []
        profile = [0.82, 0.95, 0.88, 1.02, 0.91, 0.77, 1.04, 0.93, 0.86, 0.98, 0.89, 1.01, 0.78, 0.94]
        for i, factor in enumerate(profile):
            day = end - timedelta(days=len(profile)-1-i)
            rows.append(DailyGenerationRow(site_id=site_id, day=day.isoformat(),
                    actual_kwh=round(site.capacity_kw * 4.1 * site.performance_ratio * factor, 2),
                    record_kind="synthetic_demo", source="walkthrough"))
        db.add_all(rows)
        db.commit()
        return {"saved": True, "record_kind": "synthetic_demo", "count": len(rows),
                "message": "14 invented walkthrough values added. They are not actual readings and are excluded from alerts, savings, and warranty measurements."}


@router.get("/performance/daily")
async def daily_performance(site_id: int, request: Request, days: int = 30):
    start = date.today() - timedelta(days=max(1, min(days, 90)) - 1)
    with SessionLocal() as db:
        site = owned_site(db, site_id, request.state.user_id)
        rows = db.scalars(select(DailyGenerationRow).where(DailyGenerationRow.site_id == site_id,
                DailyGenerationRow.day >= start.isoformat())
                .order_by(DailyGenerationRow.day)).all()
        items = [{"day": r.day, "actual_kwh": r.actual_kwh if r.record_kind == "actual" else None,
                  "demo_kwh": r.actual_kwh if r.record_kind == "synthetic_demo" else None,
                  "record_kind": r.record_kind} for r in rows]
        actual_days = {r.day for r in rows if r.record_kind == "actual"}
        ratio, capacity = site.performance_ratio, site.capacity_kw
        site_copy = type("Site", (), {"latitude": site.latitude, "longitude": site.longitude, "timezone": site.timezone})()
    radiation = await archive_irradiance(site_copy, start.isoformat(), date.today().isoformat())
    if radiation is None:
        return {"status": "weather_unavailable", "items": [{**x, "expected_kwh": None, "ratio_pct": None} for x in items],
                "message": "Historical solar-resource data is unavailable. No expected output or drop alert was calculated."}
    out = []
    for item in items:
        ghi = radiation.get(item["day"])
        expected = capacity * ghi * ratio if ghi is not None else None
        actual = item["actual_kwh"]
        out.append({**item, "irradiation_kwh_m2": ghi, "expected_kwh": round(expected, 2) if expected is not None else None,
                    "ratio_pct": round(actual / expected * 100, 1) if actual is not None and expected and expected > 0 else None})
    weak = 0
    longest_weak = 0
    prior_day = None
    for x in out:
        current_day = date.fromisoformat(x["day"])
        if x["day"] not in actual_days:
            continue
        if x["ratio_pct"] is not None and x["ratio_pct"] < 75 and (prior_day is None or (current_day-prior_day).days == 1):
            weak += 1
        elif x["ratio_pct"] is not None and x["ratio_pct"] < 75:
            weak = 1
        else:
            weak = 0
        longest_weak = max(longest_weak, weak)
        prior_day = current_day
    alert = longest_weak >= 3
    return {"status": "ready" if radiation is not None else "weather_unavailable", "items": out,
            "drop_alert": alert, "consecutive_low_days": longest_weak, "performance_ratio": ratio,
            "message": "Three or more consecutive actual days below 75% of the irradiance baseline; review the system." if alert else "No 3-day drop pattern in available paired measurements."}


@router.get("/cleaning-trend")
async def cleaning_trend(site_id: int, request: Request, days: int = 14):
    result = await daily_performance(site_id, request, days=max(14, min(days, 30)))
    items = [x for x in result.get("items", []) if x.get("ratio_pct") is not None]
    paired = sorted(items, key=lambda x: x["day"])
    acute = bool(result.get("drop_alert"))
    if len(paired) < 10:
        return {"status": "insufficient_data", "trend_pct": None, "sample_count": len(paired), "possible_cleaning_review": False,
                "message": "Add at least 10 actual generation days with available historical irradiance (within 14 days)."}
    n = len(paired); split = max(1, n // 3)
    early = sum(x["ratio_pct"] for x in paired[:split]) / split
    late = sum(x["ratio_pct"] for x in paired[-split:]) / len(paired[-split:])
    drop = max(0, (early - late) / early * 100) if early > 0 else 0
    flagged = drop >= 7 and not acute
    return {"status": "review" if flagged else "stable_or_acute", "trend_pct": round(drop, 1), "sample_count": n,
            "possible_cleaning_review": flagged, "message": "Slow normalized-output decline: consider inspecting/cleaning panels if safe and due." if flagged else
            ("A sudden-drop pattern takes priority; investigate that first." if acute else "No 7% slow decline in the available normalized readings."),
            "items": paired}


@router.get("/suggest-time")
async def suggest_time(site_id: int, request: Request):
    with SessionLocal() as db:
        site = owned_site(db, site_id, request.state.user_id)
        site_data = {"latitude": site.latitude, "longitude": site.longitude, "timezone": site.timezone,
                     "capacity_kw": site.capacity_kw, "performance_ratio": site.performance_ratio}
    try:
        from backend.weather import OpenMeteo
        hours = await OpenMeteo().forecast(site_data, 24)
    except Exception:
        hours = []
    solar = [h for h in hours if h.get("ghi_wm2") is not None]
    if not solar:
        return {"status": "weather_unavailable", "hours": [], "best_window": None,
                "message": "Hourly solar forecast is unavailable. Try again when weather data is reachable."}
    windows = [(sum((solar[j].get("ghi_wm2") or 0) for j in range(i, i + 3)), i)
               for i in range(max(0, len(solar) - 2))]
    _, index = max(windows, default=(0, 0))
    selected = solar[index:index + 3]
    energy = sum((x.get("ghi_wm2") or 0) / 1000 * site_data["capacity_kw"] * site_data["performance_ratio"] for x in selected)
    return {"status": "ready", "hours": solar, "best_window": {"start": selected[0]["timestamp"], "end": selected[-1]["timestamp"],
            "irradiance_sum": round(sum(x.get("ghi_wm2") or 0 for x in selected)), "estimated_generation_kwh": round(energy, 2)},
            "message": "Model forecast only; run flexible appliances in this window when practical."}


@router.post("/bills")
def save_bill(site_id: int, payload: BillInput, request: Request):
    with SessionLocal() as db:
        owned_site(db, site_id, request.state.user_id)
        row = db.scalars(select(MonthlyBillRow).where(MonthlyBillRow.site_id == site_id, MonthlyBillRow.month == payload.month)).first()
        values = payload.model_dump()
        if row:
            for key, value in values.items(): setattr(row, key, value)
        else:
            row = MonthlyBillRow(site_id=site_id, **values); db.add(row)
        db.commit()
        return {"saved": True, **values}


def monthly_values(db, site_id):
    actuals = db.scalars(select(DailyGenerationRow).where(DailyGenerationRow.site_id == site_id,
                                DailyGenerationRow.record_kind == "actual")).all()
    bills = db.scalars(select(MonthlyBillRow).where(MonthlyBillRow.site_id == site_id)).all()
    gen = {}
    for row in actuals:
        key = row.day[:7]; gen[key] = gen.get(key, 0) + row.actual_kwh
    output = []
    for bill in sorted(bills, key=lambda x: x.month):
        produced = gen.get(bill.month, 0)
        exported = min(produced, bill.exported_kwh) if bill.exported_kwh > 0 else produced * (1 - bill.self_use_pct / 100)
        self_used = max(0, produced - exported)
        savings = self_used * bill.import_tariff + exported * bill.export_tariff
        output.append({"month": bill.month, "generation_kwh": round(produced, 2), "self_used_kwh": round(self_used, 2),
            "exported_kwh": round(exported, 2), "savings_inr": round(savings, 2), "bill_credit_inr": bill.export_credit_inr,
            "consumed_kwh": bill.consumed_kwh, "import_tariff": bill.import_tariff, "export_tariff": bill.export_tariff,
            "self_use_pct": bill.self_use_pct, "credit_arithmetic_inr": round(bill.exported_kwh * bill.export_tariff, 2)})
    return output


@router.get("/bills")
def bills(site_id: int, request: Request):
    with SessionLocal() as db:
        owned_site(db, site_id, request.state.user_id)
        return {"items": monthly_values(db, site_id)}


@router.get("/monthly-savings")
def monthly_savings(site_id: int, request: Request):
    with SessionLocal() as db:
        owned_site(db, site_id, request.state.user_id)
        items = monthly_values(db, site_id)
        return {"items": items, "total_savings_inr": round(sum(x["savings_inr"] for x in items), 2),
                "total_generation_kwh": round(sum(x["generation_kwh"] for x in items), 2),
                "message": "Savings use your entered monthly bill tariff and self-use assumption; months without daily generation are not invented."}


@router.post("/warranty/curve")
def save_warranty(site_id: int, payload: WarrantyInput, request: Request):
    points = []
    for item in payload.points:
        try: year, pct = int(item["year"]), float(item["guaranteed_pct"])
        except (KeyError, TypeError, ValueError): raise HTTPException(422, "Each point needs year and guaranteed_pct.")
        if year < 1 or year > 40 or pct < 0 or pct > 150: raise HTTPException(422, "Warranty year must be 1-40; guarantee must be 0-150%.")
        points.append((year, pct))
    if len({x[0] for x in points}) != len(points): raise HTTPException(422, "Warranty years must be unique.")
    with SessionLocal() as db:
        owned_site(db, site_id, request.state.user_id)
        db.execute(delete(WarrantyPointRow).where(WarrantyPointRow.site_id == site_id))
        db.execute(delete(SyntheticWarrantyRow).where(SyntheticWarrantyRow.site_id == site_id))
        db.add_all(WarrantyPointRow(site_id=site_id, year=y, guaranteed_pct=p) for y, p in sorted(points))
        db.commit()
    return {"saved": True, "points": [{"year": y, "guaranteed_pct": p} for y, p in sorted(points)]}


@router.post("/warranty/synthetic")
def make_synthetic(site_id: int, request: Request):
    with SessionLocal() as db:
        site = owned_site(db, site_id, request.state.user_id)
        points = db.scalars(select(WarrantyPointRow).where(WarrantyPointRow.site_id == site_id).order_by(WarrantyPointRow.year)).all()
        if len(points) < 2: raise HTTPException(400, "Enter at least two manufacturer warranty curve points first.")
        rows = db.scalars(select(DailyGenerationRow).where(DailyGenerationRow.site_id == site_id,
                    DailyGenerationRow.record_kind == "actual")).all()
        year1 = sum(x.actual_kwh for x in rows if x.day[:4] == (site.commissioned_on or date.today().isoformat())[:4])
        if year1 <= 0: raise HTTPException(400, "Enter actual daily generation for your first operating year before projecting.")
        def curve(y):
            before = max((p for p in points if p.year <= y), key=lambda p:p.year, default=points[0])
            after = min((p for p in points if p.year >= y), key=lambda p:p.year, default=points[-1])
            if before.year == after.year: return before.guaranteed_pct
            return before.guaranteed_pct + (after.guaranteed_pct-before.guaranteed_pct)*(y-before.year)/(after.year-before.year)
        db.execute(delete(SyntheticWarrantyRow).where(SyntheticWarrantyRow.site_id == site_id))
        projections = [SyntheticWarrantyRow(site_id=site_id, year=y, generation_kwh=round(year1*curve(y)/100, 2),
                        performance_pct=round(curve(y), 2)) for y in range(2, min(25, points[-1].year)+1)]
        db.add_all(projections); db.commit()
        return {"saved": True, "baseline_year": 1, "baseline_actual_kwh": round(year1, 2),
                "items": [{"year":x.year,"generation_kwh":x.generation_kwh,"performance_pct":x.performance_pct,"record_kind":"synthetic_projection"} for x in projections]}


@router.get("/warranty")
def warranty(site_id: int, request: Request):
    with SessionLocal() as db:
        site = owned_site(db, site_id, request.state.user_id)
        points = db.scalars(select(WarrantyPointRow).where(WarrantyPointRow.site_id == site_id).order_by(WarrantyPointRow.year)).all()
        rows = db.scalars(select(DailyGenerationRow).where(DailyGenerationRow.site_id == site_id,
                                DailyGenerationRow.record_kind == "actual")).all()
        annual = {}
        for row in rows: annual[row.day[:4]] = annual.get(row.day[:4], 0) + row.actual_kwh
        synthetic = db.scalars(select(SyntheticWarrantyRow).where(SyntheticWarrantyRow.site_id == site_id).order_by(SyntheticWarrantyRow.year)).all()
        baseline_year = (site.commissioned_on or date.today().isoformat())[:4]
        baseline = annual.get(baseline_year)
        real = [{"year": int(y)-int(baseline_year)+1, "calendar_year": y, "generation_kwh": round(value,2),
                 "performance_pct": round(value/baseline*100,1) if baseline else None, "record_kind":"actual"} for y,value in sorted(annual.items())]
        return {"curve":[{"year":p.year,"guaranteed_pct":p.guaranteed_pct} for p in points], "actual":real,
                "synthetic":[{"year":p.year,"generation_kwh":p.generation_kwh,"performance_pct":p.performance_pct,"record_kind":p.record_kind} for p in synthetic],
                "baseline_actual_kwh":baseline}


@router.get("/discom-check")
def discom_check(site_id: int, request: Request, month: str | None = None):
    with SessionLocal() as db:
        owned_site(db, site_id, request.state.user_id)
        items = monthly_values(db, site_id)
        row = next((x for x in items if x["month"] == month), None) if month else (items[-1] if items else None)
        if not row: return {"status":"no_bill", "month":month, "message":"Enter a monthly bill and generation readings to run this estimate."}
        calc = row["credit_arithmetic_inr"]; stated = row["bill_credit_inr"]
        variance = abs(calc-stated)/max(stated, 1) * 100
        return {"status":"review" if variance > 5 else "within_tolerance", "month":row["month"],
                "estimated_export_kwh":row["exported_kwh"], "bill_export_kwh":None,
                "printed_credit_inr":stated,"export_units_times_rate_inr":calc,"variance_pct":round(variance,1),
                "message":"Printed credit differs by more than 5% from billed export units × export rate; review the bill and tariff." if variance > 5 else
                "Arithmetic is within 5%. Generated-vs-exported comparison remains an estimate; a meter export register is preferred."}
