import csv, io
import re
from datetime import datetime, timezone
from backend.metrics import data_quality_score

ALIASES = {
    "timestamp": ["timestamp", "time", "date", "datetime", "local_time"],
    "inverter_id": ["inverter_id", "serial_number", "device_id"],
    "ac_power_w": ["ac_power_w", "ac_power", "active_power", "power_ac", "pac", "power"],
    "energy_wh": ["energy_wh", "energy", "daily_energy", "yield", "e_day"],
    "dc_power_w": ["dc_power_w", "dc_power", "power_dc", "pdc"],
    "dc_voltage_v": ["dc_voltage_v", "dc_voltage", "voltage_dc", "vdc"],
    "dc_current_a": ["dc_current_a", "dc_current", "current_dc", "idc"],
    "irradiance_poa_wm2": ["irradiance_poa_wm2", "poa", "poa_irradiance"],
    "ghi_wm2": ["ghi_wm2", "ghi", "global_irradiance"],
    "dni_wm2": ["dni_wm2", "dni", "direct_normal_irradiance"],
    "dhi_wm2": ["dhi_wm2", "dhi", "diffuse_horizontal_irradiance"],
    "ambient_temp_c": ["ambient_temp_c", "temperature", "temp_c", "air_temperature"],
    "module_temp_c": ["module_temp_c", "module_temperature", "cell_temperature"],
    "wind_speed_ms": ["wind_speed_ms", "wind_speed", "wind_speed_m_s"],
    "cloud_cover_pct": ["cloud_cover_pct", "cloud_cover", "clouds_pct"],
    "precipitation_mm": ["precipitation_mm", "precipitation", "rain_mm"],
    "inverter_status": ["inverter_status", "status"], "fault_code": ["fault_code", "error_code"],
}
NUMERIC = {"ac_power_w", "energy_wh", "dc_power_w", "dc_voltage_v", "dc_current_a", "irradiance_poa_wm2", "ghi_wm2", "dni_wm2", "dhi_wm2", "ambient_temp_c", "module_temp_c", "wind_speed_ms", "cloud_cover_pct", "precipitation_mm"}

def normalize_csv(content: bytes, field_mapping: dict | None = None):
    try: text = content.decode("utf-8-sig")
    except UnicodeDecodeError as e: raise ValueError("CSV must be UTF-8 encoded") from e
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames: raise ValueError("CSV has no header row")
    # Treat common provider formatting differences (spaces, hyphens, units) uniformly.
    lookup = {re.sub(r"[^a-z0-9]+", "_", h.strip().lower()).strip("_"): h for h in reader.fieldnames if h}
    mapping = {key: next((lookup[name] for name in names if name in lookup), None) for key, names in ALIASES.items()}
    if field_mapping:
        for key, header in field_mapping.items():
            if key not in ALIASES:
                raise ValueError(f"Unsupported mapped field: {key}")
            if header in (None, ""):
                mapping[key] = None
                continue
            normalized_header = re.sub(r"[^a-z0-9]+", "_", str(header).strip().lower()).strip("_")
            if normalized_header not in lookup:
                raise ValueError(f"Mapped column was not found: {header}")
            mapping[key] = lookup[normalized_header]
    if mapping["timestamp"] is None: raise ValueError("Required timestamp column not found")
    if not any(mapping[k] for k in ("ac_power_w", "energy_wh", "dc_power_w")): raise ValueError("At least one recognized power or energy column is required")
    out = []
    for line, source in enumerate(reader, start=2):
        if not any(source.values()): continue
        raw = source.get(mapping["timestamp"], "")
        try:
            stamp = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
            if stamp.tzinfo is None: stamp = stamp.replace(tzinfo=timezone.utc)
        except Exception as e: raise ValueError(f"Invalid timestamp on CSV row {line}") from e
        row = {"timestamp": stamp.astimezone(timezone.utc).isoformat(), "source": "csv_upload"}
        for key, col in mapping.items():
            if key == "timestamp" or col is None: continue
            value = source.get(col, "").strip()
            if not value: row[key] = None
            elif key in NUMERIC:
                try: row[key] = float(value)
                except ValueError as e: raise ValueError(f"Invalid numeric value for {key} on CSV row {line}") from e
            else: row[key] = value
        row["data_quality_score"] = data_quality_score(row)
        out.append(row)
    if not out: raise ValueError("CSV contains no telemetry rows")
    return out

