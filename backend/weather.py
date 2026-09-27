import os, httpx

class OpenMeteo:
    def __init__(self, timeout=None):
        self.base = os.getenv("OPEN_METEO_BASE_URL", "https://api.open-meteo.com/v1/forecast")
        self.timeout = timeout or float(os.getenv("REQUEST_TIMEOUT_SECONDS", "10"))
    async def forecast(self, site, hours=48):
        value = lambda key: site[key] if isinstance(site, dict) else getattr(site, key)
        params = {"latitude": value("latitude"), "longitude": value("longitude"), "timezone": value("timezone"),
                  "forecast_days": min(3, max(1, (hours + 23)//24)),
                  "hourly": "temperature_2m,cloud_cover,precipitation,wind_speed_10m,shortwave_radiation,direct_radiation,diffuse_radiation"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(self.base, params=params); response.raise_for_status(); data = response.json()
        hourly = data.get("hourly", {})
        return [{"timestamp": t, "ambient_temp_c": hourly.get("temperature_2m", [None]*len(hourly.get("time", [])))[i],
                 "cloud_cover_pct": hourly.get("cloud_cover", [None]*len(hourly.get("time", [])))[i],
                 "precipitation_mm": hourly.get("precipitation", [None]*len(hourly.get("time", [])))[i],
                 "wind_speed_ms": (hourly.get("wind_speed_10m", [None]*len(hourly.get("time", [])))[i] or 0)/3.6,
                 "ghi_wm2": hourly.get("shortwave_radiation", [None]*len(hourly.get("time", [])))[i],
                 "dni_wm2": hourly.get("direct_radiation", [None]*len(hourly.get("time", [])))[i],
                 "dhi_wm2": hourly.get("diffuse_radiation", [None]*len(hourly.get("time", [])))[i],
                 "irradiance_source": "open_meteo_model_estimate"} for i,t in enumerate(hourly.get("time", []))][:hours]

