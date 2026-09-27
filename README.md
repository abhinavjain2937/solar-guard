# SolarSurd AI

SolarSurd is a PV analytics starter: validated CSV ingestion, transparent telemetry metrics, optional Open-Meteo context, a first-order Solar Digital Twin/What-if calculator, residual investigations, forecasts, and a small dashboard. The project does not claim device compatibility, measured irradiance where data is estimated, or model accuracy without evaluation.

## Quick start

Python 3.11+ is recommended.

```powershell
# Run these commands from the extracted solarsurd-ai project folder
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn backend.app:app --reload
```

Open http://127.0.0.1:8000/docs for OpenAPI and http://127.0.0.1:8000 for the dashboard. SQLite is used by default for local development; set `DATABASE_URL` to a PostgreSQL URL for PostgreSQL. No public example is added to your database until you click **Load real public PVDAQ sample**.

On Windows, you can double-click `start_solar_surds.bat`. It creates the local virtual environment if needed, installs web/API requirements only when missing, starts the API, waits for its health endpoint, and then opens the connected dashboard. If the Python launcher is present without a separate Python install, it falls back to the Codex-bundled Python runtime when available. Do not open `frontend/index.html` by double-clicking it if you want site creation and dropdown data; a `file://` page cannot use the API. It will now show that explanation instead of failing silently.

## Local sign-in

The first visit opens `/login`. Create an account with an email and a 12-character minimum password. Google sign-in is deferred until the project is ready for deployment. Passwords are stored as scrypt hashes; signed-in sessions use random opaque tokens, are HTTP-only, and expire after 12 hours. On an existing database, the first account adopts its previously saved sites. Later accounts see only their own sites. There is no email verification, password reset, or rate limiting; keep this prototype bound to localhost and do not expose it to the public internet.

The signed-in app includes dedicated Performance, Cleaning trend, Appliance timing, Savings & bills, Warranty, and Export credit views. Enter daily kWh from the inverter/meter and monthly bill figures to populate the charts. Historical irradiance and hourly forecasts use Open-Meteo when available. If the network service is unavailable, expected output and timing recommendations remain blank rather than using invented weather. Warranty projections are kept separate and labelled synthetic. The selected-site control stays visible as you move between pages.

## Try the dashboard without a solar system

Create a demo site with name `Demo Rooftop`, latitude `19.0760`, longitude `72.8777`, timezone `Asia/Kolkata`, DC capacity `5` kWp, and the default performance ratio `0.80`. Open **Performance** and choose **Try 14-day demo** to add clearly tagged walkthrough readings. These values are synthetic and excluded from measured performance alerts, savings, and warranty actuals. Enter daily meter readings to replace demo dates with measured values. The included telemetry CSV is also explicitly tagged `SYNTHETIC_DEMO_ONLY`; it is fabricated and must not be interpreted as site production, financial savings, or a confirmed equipment fault.

For a real site, use a CSV exported from your inverter, monitoring portal, or generation meter. Minimum required columns: timestamp and at least one recognized power or energy column. The sample includes `timestamp`, `ac_power_w`, `energy_wh`, `dc_power_w`, and `ghi_wm2`; GHI is an irradiance context value, not a panel sensor reading.

## Public measured-data example

The dashboard can add a separate sample site for NREL PVDAQ system 1245 in New Orleans. It contains 5,631 measured AC-power and energy readings from July 1–20, 2012, at approximately five-minute intervals. This is historical public research data, not a live connection to your inverter. Attribution: National Renewable Energy Laboratory (NREL), Photovoltaic Data Acquisition (PVDAQ), system 1245, July 2012, [PVDAQ public dataset record](https://catalog.data.gov/dataset/photovoltaic-data-acquisition-pvdaq-public-datasets), licensed CC BY 4.0. The bundled subset can be regenerated with `python scripts/download_public_data.py`.

The app's forecast repeats a recent average; its min/max band is not calibrated. The baseline investigation indicator does not confirm a fault. Open-Meteo weather is hourly model context and depends on internet access. The saved site's coordinates need to match the actual system location for that context to be meaningful.

## Commands

```powershell
pip install -r requirements.txt
python scripts/download_public_data.py --help
python scripts/preprocess.py --input data/raw.csv --output data/processed.csv
python -m ml.train --input data/processed.csv --output artifacts/model.json
python -m ml.evaluate --input data/processed.csv --model artifacts/model.json
uvicorn backend.app:app --reload
# The dashboard is served with the API at http://127.0.0.1:8000
pytest
docker compose up --build
```

Public-data download is deliberately not automatic: choose a dataset and verify its current license, access terms, and request limits first. SolarEdge API use requires user authorization and provider credentials. No real provider connector is claimed supported. Deployment has not been performed.

## API

- `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`, `GET /api/v1/auth/me`
- `POST /api/v1/sites`
- `POST /api/v1/sites/{site_id}/ingest/csv` (multipart CSV)
- `POST /api/v1/sites/{site_id}/sync` (returns honest unsupported-provider response)
- `GET /api/v1/sites/{site_id}/metrics`
- `POST /api/v1/sites/{site_id}/simulator`
- `GET /api/v1/sites/{site_id}/forecast`
- `GET /api/v1/sites/{site_id}/anomalies`
- `GET /api/v1/sites/{site_id}/weather`
- `GET /api/v1/sites/{site_id}/report`
- `GET /api/v1/providers`, `GET /health`

See `/docs` for request schemas. Weather calls require network access and may be unavailable. `/weather` degrades gracefully. Open-Meteo radiation values are API-derived model/reanalysis context, never measured sensor data.

## Canonical telemetry and metrics

The normalized schema is in `backend/schemas.py`; common vendor headers map in `backend/ingest.py`. Required timestamp and at least one production field are checked. Timestamps are parsed as UTC unless an offset is present. Units are retained explicitly in column names.

- Energy: sum of `energy_wh` / 1000 to kWh.
- Specific yield: energy kWh / installed DC kWp.
- Capacity factor: energy kWh / (capacity kW × interval hours) × 100; only available when a duration is supplied.
- Actual/expected: actual energy / baseline energy × 100.
- Performance ratio: measured energy / (POA irradiation kWh/m² × capacity kWp) × 100; only offered with POA basis.
- Inverter efficiency: AC watts / DC watts × 100, only where both positive values exist.
- Quality score: proportion of present values among recognized telemetry fields (0–100); a completeness indicator, not a sensor-accuracy score.

The fallback baseline uses configured capacity and available irradiance with documented configurable loss factor; it is not a pvlib ModelChain simulation. pvlib is an optional dependency and the precise model requires inputs/configuration not guaranteed by generic CSVs.

### Solar Digital Twin / What-if calculator

The simulator compares the site's saved DC capacity against a proposed panel count × panel wattage. It estimates daily energy as `effective_ac_capacity_kW × user_entered_peak_sun_hours × (1 − losses_pct/100)`, then uses 30 days/month and 365 days/year. If inverter capacity is entered, it is used as a simple AC clipping ceiling. Savings use the user's tariff, self-consumption share, and optional export tariff. Optional CO₂ estimates require a user-supplied grid emissions factor; no default conversion is invented. This first-order calculator does not model tilt, azimuth, shading, hourly weather, taxes, financing, degradation, or seasonal variation and is not an engineering design or investment quote.

## Forecasting and ML limits

`ml.train` fits a CPU HistGradientBoostingRegressor on chronological train/validation/test partitions. Features use only telemetry available at each record time; this repository does not yet archive weather forecast vintages, so the learned model is an offline baseline and is not represented as an operational future-weather forecast. Forecast endpoint uses recent production persistence, only where history exists. Prediction bands are simple historical residual quantiles, not calibrated confidence intervals. Do not use these estimates for operational or financial decisions without site validation.

## Deployment / integration status

Local sign-in and per-account site ownership are implemented for this prototype. Local Docker configuration and PostgreSQL support are provided, but production use still needs reviewed database migrations, login abuse protection, credential-recovery flows, stronger session/CSRF controls, robust observability, object storage, provider OAuth, scheduled synchronization, forecast-vintage storage, and deployment/security verification. Credentials belong in environment variables and are not committed. Keep the prototype bound to localhost until those controls have been reviewed.

References checked 2026-09-24:
- [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api)
- [NASA POWER Daily API](https://power.larc.nasa.gov/docs/services/api/temporal/daily/)
- [pvlib ModelChain](https://pvlib-python.readthedocs.io/en/stable/reference/generated/pvlib.modelchain.ModelChain.html)
- [SolarEdge Developer Platform](https://developer.solaredge.com/)
- [NREL PVDAQ dataset](https://catalog.data.gov/dataset/photovoltaic-data-acquisition-pvdaq-public-datasets)

## Truthful completion report

| Status | Items |
|---|---|
| Implemented | Canonical schema, CSV validation/normalization, SQLite/PostgreSQL persistence, basic metrics, persistence forecast, evidence-based residual flags, report JSON, weather adapter, provider matrix, dashboard navigation and method notes, optional attributed PVDAQ sample site, Docker files, training/evaluation scripts. |
| Tested and passed | Earlier core suite: 5 passed, including a mocked Open-Meteo response. Simulator API smoke passed with a fresh SQLite database (5 kWp current vs 7 kWp proposed; returned 21.5 vs 30.1 estimated kWh/day). Python syntax and JavaScript syntax checks passed. |
| Implemented but not fully tested | Network weather calls, PostgreSQL configuration, pvlib optional pathway. |
| Requires external credentials/manual authorization | SolarEdge OAuth/site access; any user-owned provider. |
| Not completed | Production auth/tenant isolation, Alembic revision history, operational LightGBM residual model with forecast weather vintages, SunSpec edge agent, savings with meter imports/exports, production deployment and site evaluation. |

