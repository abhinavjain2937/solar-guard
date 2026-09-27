import hashlib, hmac, json, logging, secrets, uuid
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text, func
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from backend.db import Base, engine, SessionLocal, SiteRow, TelemetryRow, UserRow, LoginSessionRow
from backend.schemas import SiteCreate
from backend.ingest import normalize_csv
from backend.analytics import summarize, investigations, persistence_forecast, series
from backend.weather import OpenMeteo
from backend.simulator import estimate_system, as_dict
from backend.solar_features import router as solar_features_router

logging.basicConfig(level=logging.INFO)
log=logging.getLogger("solarsurd")
app=FastAPI(title="SolarSurd AI",version="0.1.0",description="Evidence-led solar production analytics. Values depend on user telemetry and are not a device compatibility guarantee.")
app.include_router(solar_features_router)
Base.metadata.create_all(engine)
FRONTEND_DIR=__import__("pathlib").Path(__file__).resolve().parents[1]/"frontend"
app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR)), name="assets")
SESSION_HOURS = 12

class AuthInput(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)

def _password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    value = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${value.hex()}"

def _password_matches(password: str, encoded: str) -> bool:
    try:
        algorithm, salt_hex, expected = encoded.split("$", 2)
        if algorithm != "scrypt": return False
        actual = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False

def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()

class SimulatorInput(BaseModel):
    panel_count: int = Field(gt=0, le=100000)
    panel_wattage_w: float = Field(gt=0, le=2000)
    peak_sun_hours: float = Field(gt=0, le=12, description="User-entered equivalent full-sun hours per day")
    losses_pct: float = Field(ge=0, le=60, default=14)
    inverter_capacity_kw: float | None = Field(default=None, gt=0)
    tariff_inr_per_kwh: float = Field(ge=0, default=0)
    export_tariff_inr_per_kwh: float = Field(ge=0, default=0)
    self_consumption_pct: float = Field(ge=0, le=100, default=100)
    installed_cost_inr: float | None = Field(default=None, ge=0)
    monthly_bill_inr: float | None = Field(default=None, ge=0)
    grid_co2_kg_per_kwh: float | None = Field(default=None, ge=0, le=5)

@app.middleware("http")
async def request_id(request: Request, call_next):
    rid=request.headers.get("x-request-id") or str(uuid.uuid4())
    response=await call_next(request); response.headers["X-Request-ID"]=rid
    return response

@app.middleware("http")
async def authenticate(request: Request, call_next):
    request.state.user_id = None
    token = request.cookies.get("solar_session")
    if token:
        with SessionLocal() as db:
            session = db.get(LoginSessionRow, _token_digest(token))
            if session and session.expires_at > datetime.now(timezone.utc).replace(tzinfo=None):
                request.state.user_id = session.user_id
            elif session:
                db.delete(session); db.commit()
    public_auth = request.url.path.startswith("/api/v1/auth/")
    if request.url.path.startswith("/api/v1/") and not public_auth and not request.state.user_id:
        return JSONResponse({"detail":"Sign in to access your SolarSurd workspace."}, status_code=401)
    return await call_next(request)

def site_dict(s):
    return {k:getattr(s,k) for k in ("id","name","latitude","longitude","timezone","capacity_kw","performance_ratio","inverter_capacity_kw","tilt_deg","azimuth_deg","commissioned_on","inverter_model","module_model")}
def _site(db,id,user_id):
    s=db.scalars(select(SiteRow).where(SiteRow.id==id, SiteRow.owner_id==user_id)).first()
    if not s: raise HTTPException(404,"Site not found")
    return s
def _rows(db,id):
    return [json.loads(x.payload) for x in db.scalars(select(TelemetryRow).where(TelemetryRow.site_id==id).order_by(TelemetryRow.timestamp))]

@app.get("/",response_class=HTMLResponse)
def dashboard(request: Request):
    from pathlib import Path
    if not request.state.user_id:
        return HTMLResponse((FRONTEND_DIR/"login.html").read_text(encoding="utf-8"))
    return (FRONTEND_DIR/"index.html").read_text(encoding="utf-8")

@app.get("/login",response_class=HTMLResponse)
def login_page(request: Request):
    if request.state.user_id:
        return RedirectResponse("/", status_code=303)
    return HTMLResponse((FRONTEND_DIR/"login.html").read_text(encoding="utf-8"))

@app.post("/api/v1/auth/register")
def register(payload: AuthInput, request: Request):
    email = payload.email.strip().lower()
    if "@" not in email or "." not in email.rsplit("@",1)[-1]:
        raise HTTPException(422, "Enter a valid email address.")
    if len(payload.password) < 12:
        raise HTTPException(422, "Use a password with at least 12 characters.")
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(UserRow)) >= 50:
            raise HTTPException(429, "This local demo supports up to 50 accounts.")
        if db.scalars(select(UserRow).where(UserRow.email == email)).first():
            raise HTTPException(409, "An account with that email already exists. Sign in instead.")
        first_account = db.scalar(select(func.count()).select_from(UserRow)) == 0
        user = UserRow(email=email, password_hash=_password_hash(payload.password), created_at=datetime.now(timezone.utc).replace(tzinfo=None))
        db.add(user); db.flush()
        if first_account:
            db.execute(text("UPDATE sites SET owner_id=:uid WHERE owner_id IS NULL"), {"uid":user.id})
        token = secrets.token_urlsafe(32)
        expires = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=SESSION_HOURS)
        db.add(LoginSessionRow(token_hash=_token_digest(token), user_id=user.id, expires_at=expires)); db.commit()
    response = JSONResponse({"authenticated":True,"email":email,"claimed_legacy_sites":first_account})
    response.set_cookie("solar_session", token, httponly=True, secure=request.url.scheme == "https", samesite="strict", max_age=SESSION_HOURS*3600, path="/")
    return response

@app.post("/api/v1/auth/login")
def login(payload: AuthInput, request: Request):
    email = payload.email.strip().lower()
    with SessionLocal() as db:
        user = db.scalars(select(UserRow).where(UserRow.email == email)).first()
        if not user or not _password_matches(payload.password, user.password_hash):
            raise HTTPException(401, "Email or password is incorrect.")
        token = secrets.token_urlsafe(32)
        expires = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=SESSION_HOURS)
        db.add(LoginSessionRow(token_hash=_token_digest(token), user_id=user.id, expires_at=expires)); db.commit()
    response = JSONResponse({"authenticated":True,"email":email})
    response.set_cookie("solar_session", token, httponly=True, secure=request.url.scheme == "https", samesite="strict", max_age=SESSION_HOURS*3600, path="/")
    return response

@app.post("/api/v1/auth/logout")
def logout(request: Request):
    token = request.cookies.get("solar_session")
    if token:
        with SessionLocal() as db:
            session = db.get(LoginSessionRow, _token_digest(token))
            if session: db.delete(session); db.commit()
    response = JSONResponse({"authenticated":False})
    response.delete_cookie("solar_session", path="/", httponly=True, samesite="strict")
    return response

@app.get("/api/v1/auth/me")
def who_am_i(request: Request):
    if not request.state.user_id: return {"authenticated":False}
    with SessionLocal() as db:
        user = db.get(UserRow, request.state.user_id)
        return {"authenticated":bool(user),"email":user.email if user else None}

@app.get("/style.css")
def frontend_stylesheet():
    return FileResponse(FRONTEND_DIR/"style.css", media_type="text/css")

@app.get("/app.js")
def frontend_script():
    return FileResponse(FRONTEND_DIR/"app.js", media_type="text/javascript")

@app.get("/auth.js")
def frontend_auth_script():
    return FileResponse(FRONTEND_DIR/"auth.js", media_type="text/javascript")

@app.get("/sample_synthetic_demo.csv")
def sample_demo_csv():
    return FileResponse(FRONTEND_DIR/"sample_synthetic_demo.csv", media_type="text/csv", filename="sample_synthetic_demo.csv")

@app.post("/api/v1/demo/pvdaq")
def load_pvdaq_demo(request: Request):
    """Load a bundled, attributed slice of measured NREL PVDAQ data on request."""
    demo_name = "NREL PVDAQ 1245 · New Orleans (public sample)"
    with SessionLocal() as db:
        existing = db.scalars(select(SiteRow).where(SiteRow.name == demo_name, SiteRow.owner_id == request.state.user_id)).first()
        if existing:
            return {"site": site_dict(existing), "accepted": db.query(TelemetryRow).filter(TelemetryRow.site_id == existing.id).count(), "existing": True}
        content = (FRONTEND_DIR/"pvdaq_1245_demo.csv").read_bytes()
        try: records = normalize_csv(content)
        except ValueError as e: raise HTTPException(500, f"Bundled PVDAQ sample is invalid: {e}") from e
        site = SiteRow(name=demo_name, latitude=29.951, longitude=-90.0812,
            timezone="America/Chicago", capacity_kw=2.82, inverter_capacity_kw=3.0,
            tilt_deg=32, azimuth_deg=170, commissioned_on="2012-02-27",
            inverter_model="Fronius IG 3.0 Plus", module_model=None, owner_id=request.state.user_id)
        db.add(site); db.flush()
        for row in records:
            row.update({"site_id": site.id, "latitude": site.latitude, "longitude": site.longitude,
                "timezone": site.timezone, "capacity_kw": site.capacity_kw, "tilt_deg": site.tilt_deg,
                "azimuth_deg": site.azimuth_deg, "module_model": None, "inverter_model": site.inverter_model,
                "missing_flag": False, "source": "NREL PVDAQ public dataset, system 1245"})
        db.add_all(TelemetryRow(site_id=site.id, timestamp=row["timestamp"], payload=json.dumps(row)) for row in records)
        db.commit(); db.refresh(site)
        return {"site": site_dict(site), "accepted": len(records), "existing": False}

@app.get("/health")
def health():
    try:
        with SessionLocal() as db: db.execute(text("SELECT 1"))
        return {"status":"ok","database":"connected"}
    except Exception:
        log.exception("health check failed")
        raise HTTPException(503,"Database unavailable")

@app.post("/api/v1/sites")
def create_site(payload:SiteCreate, request: Request):
    with SessionLocal() as db:
        s=SiteRow(**payload.model_dump(mode="json"), owner_id=request.state.user_id); db.add(s); db.commit(); db.refresh(s); return site_dict(s)

@app.get("/api/v1/sites")
def sites(request: Request):
    with SessionLocal() as db: return [site_dict(s) for s in db.scalars(select(SiteRow).where(SiteRow.owner_id==request.state.user_id).order_by(SiteRow.id))]

@app.post("/api/v1/sites/{site_id}/ingest/csv")
async def ingest(site_id:int,request:Request,file:UploadFile=File(...),mapping:str|None=Form(None)):
    if not file.filename.lower().endswith(".csv"): raise HTTPException(415,"Upload a .csv file")
    content=await file.read(20_000_001)
    if len(content)>20_000_000: raise HTTPException(413,"CSV exceeds 20 MB")
    try:
        field_mapping=json.loads(mapping) if mapping else None
        if field_mapping is not None and not isinstance(field_mapping,dict): raise ValueError("Column mapping must be a JSON object")
        records=normalize_csv(content,field_mapping)
    except ValueError as e: raise HTTPException(422,str(e)) from e
    with SessionLocal() as db:
        s=_site(db,site_id,request.state.user_id)
        for r in records:
            r.update({"site_id":site_id,"latitude":s.latitude,"longitude":s.longitude,"timezone":s.timezone,
                      "capacity_kw":s.capacity_kw,"tilt_deg":s.tilt_deg,"azimuth_deg":s.azimuth_deg,
                      "module_model":s.module_model,"inverter_model":s.inverter_model,"missing_flag":False})
        db.add_all(TelemetryRow(site_id=site_id,timestamp=r["timestamp"],payload=json.dumps(r)) for r in records)
        db.commit()
    mean_quality=sum(r.get("data_quality_score",0) for r in records)/len(records)
    return {"accepted":len(records),"source":"user_csv","mean_data_quality_score":round(mean_quality,1),"normalized_fields":sorted(set().union(*(r.keys() for r in records)))}

@app.post("/api/v1/sites/{site_id}/sync")
def sync(site_id:int,request:Request):
    with SessionLocal() as db: _site(db,site_id,request.state.user_id)
    return {"status":"not_configured","message":"No live provider adapter is enabled. No provider is currently labelled supported."}

@app.get("/api/v1/sites/{site_id}/metrics")
def metrics(site_id:int,request:Request):
    with SessionLocal() as db:
        s=_site(db,site_id,request.state.user_id); rows=_rows(db,site_id); result=summarize(rows,s); result["site"]=site_dict(s)
        result["data_sources"]=sorted({r.get("source","csv_upload") for r in rows})
        return result

@app.post("/api/v1/sites/{site_id}/simulator")
def simulator(site_id:int, inputs:SimulatorInput, request:Request):
    with SessionLocal() as db:
        site=_site(db,site_id,request.state.user_id)
        shared={"peak_sun_hours":inputs.peak_sun_hours,"losses_pct":inputs.losses_pct,
                "tariff_inr_per_kwh":inputs.tariff_inr_per_kwh,
                "export_tariff_inr_per_kwh":inputs.export_tariff_inr_per_kwh,
                "self_consumption_pct":inputs.self_consumption_pct,
                "grid_co2_kg_per_kwh":inputs.grid_co2_kg_per_kwh,
                "monthly_bill_inr":inputs.monthly_bill_inr}
        current=estimate_system(dc_capacity_kw=site.capacity_kw,
            inverter_capacity_kw=site.inverter_capacity_kw,
            installed_cost_inr=None, **shared)
        proposed_kw=inputs.panel_count*inputs.panel_wattage_w/1000
        proposed=estimate_system(dc_capacity_kw=proposed_kw,
            inverter_capacity_kw=inputs.inverter_capacity_kw,
            installed_cost_inr=inputs.installed_cost_inr, **shared)
        return {"site_id":site_id,"current":as_dict(current),"proposed":as_dict(proposed),
                "difference":{"daily_kwh":round(proposed.daily_kwh-current.daily_kwh,2),
                    "annual_kwh":round(proposed.annual_kwh-current.annual_kwh,2),
                    "annual_savings_inr":round(proposed.annual_savings_inr-current.annual_savings_inr,2)},
                "assumptions":["First-order capacity × user-entered peak sun hours × (1 − losses).",
                    "Inverter capacity is treated as an AC clipping limit.",
                    "Tilt, azimuth, shading, hourly weather, degradation, taxes, and financing are not modeled.",
                    "CO₂ is shown only when you enter an emissions factor.",
                    "Savings use your self-consumption percentage and entered tariffs; monthly bill caps monthly savings."]}

@app.get("/api/v1/sites/{site_id}/series")
def telemetry_series(site_id:int,request:Request,limit:int=500):
    with SessionLocal() as db:
        s=_site(db,site_id,request.state.user_id); return {"site_id":site_id,"points":series(_rows(db,site_id),s,max(1,min(2000,limit)))}

@app.get("/api/v1/sites/{site_id}/forecast")
def forecast(site_id:int,request:Request,hours:int=24):
    with SessionLocal() as db:
        s=_site(db,site_id,request.state.user_id); data=persistence_forecast(_rows(db,site_id),s,hours); return {"site_id":site_id,"points":data,"status":"history_required" if not data else "persistence_baseline"}

@app.get("/api/v1/sites/{site_id}/anomalies")
def anomalies(site_id:int,request:Request):
    with SessionLocal() as db:
        s=_site(db,site_id,request.state.user_id); return {"items":investigations(_rows(db,site_id),s),"classification":"investigation indicators; not confirmed hardware faults"}

@app.get("/api/v1/sites/{site_id}/weather")
async def weather(site_id:int,request:Request):
    with SessionLocal() as db:
        s=_site(db,site_id,request.state.user_id); sdata=site_dict(s)
    try: return {"source":"Open-Meteo forecast API; model-derived context","items":await OpenMeteo().forecast(sdata)}
    except Exception as e:
        log.warning("weather unavailable: %s",type(e).__name__)
        return {"source":None,"items":[],"status":"unavailable","detail":"Weather provider could not be reached; telemetry analytics remain available."}

@app.get("/api/v1/sites/{site_id}/report")
def report(site_id:int,request:Request):
    with SessionLocal() as db:
        s=_site(db,site_id,request.state.user_id); rows=_rows(db,site_id)
        sources=sorted({r.get("source","csv_upload") for r in rows})
        return {"site":site_dict(s),"metrics":summarize(rows,s),"investigations":investigations(rows,s),"generated_at":__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),"data_sources":sources,"limitations":["Investigations do not confirm faults.","Baseline is a documented simple proxy, not pvlib-calibrated."]}

@app.get("/api/v1/providers")
def providers(): return [{"provider":"CSV upload","status":"implemented"},{"provider":"Open-Meteo weather","status":"implemented; network-dependent"},{"provider":"NASA POWER","status":"planned"},{"provider":"SolarEdge","status":"not implemented; authorization required"},{"provider":"SunSpec edge agent","status":"not implemented"}]

