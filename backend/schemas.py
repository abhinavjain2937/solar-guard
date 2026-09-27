from datetime import date
from pydantic import BaseModel, Field

class SiteCreate(BaseModel):
    name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: str = "UTC"
    capacity_kw: float = Field(gt=0)
    performance_ratio: float = Field(default=0.8, ge=0.5, le=1.0)
    inverter_capacity_kw: float | None = Field(default=None, gt=0)
    tilt_deg: float | None = Field(default=None, ge=0, le=90)
    azimuth_deg: float | None = Field(default=None, ge=0, le=360)
    commissioned_on: date | None = None
    inverter_model: str | None = None
    module_model: str | None = None

class Site(SiteCreate):
    id: int

class Telemetry(BaseModel):
    timestamp: str
    site_id: int | None = None
    inverter_id: str | None = None
    ac_power_w: float | None = None
    energy_wh: float | None = None
    dc_power_w: float | None = None
    dc_voltage_v: float | None = None
    dc_current_a: float | None = None
    irradiance_poa_wm2: float | None = None
    ghi_wm2: float | None = None
    dni_wm2: float | None = None
    dhi_wm2: float | None = None
    ambient_temp_c: float | None = None
    module_temp_c: float | None = None
    wind_speed_ms: float | None = None
    cloud_cover_pct: float | None = None
    precipitation_mm: float | None = None
    inverter_status: str | None = None
    fault_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    timezone: str | None = None
    capacity_kw: float | None = None
    tilt_deg: float | None = None
    azimuth_deg: float | None = None
    module_model: str | None = None
    inverter_model: str | None = None
    missing_flag: bool = False
    data_quality_score: float | None = None

