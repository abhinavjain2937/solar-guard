"""Download a small, attributed real PV telemetry slice from NREL PVDAQ.

The bundled sample is system 1245 (New Orleans), July 1–20, 2012. The app uses
this only as an optional demo site; it does not replace or alter user sites.
"""
import argparse
import csv
import io
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import httpx

BASE = "https://oedi-data-lake.s3.amazonaws.com"
PREFIX = "pvdaq/csv/pvdata/system_id=1245/year=2012/month=7/"
OUTPUT = Path(__file__).resolve().parents[1] / "frontend" / "pvdaq_1245_demo.csv"


def download_sample(output: Path = OUTPUT) -> int:
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        listing = client.get(BASE, params={"list-type": "2", "prefix": PREFIX})
        listing.raise_for_status()
        root = ET.fromstring(listing.content)
        keys = [node.text for node in root.findall("{*}Contents/{*}Key")]
        if not keys:
            raise RuntimeError("No July 2012 PVDAQ system 1245 files were listed")
        output.parent.mkdir(parents=True, exist_ok=True)
        total = 0
        with output.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "ac_power_w", "energy_wh"])
            for key in sorted(keys):
                response = client.get(f"{BASE}/{key}")
                response.raise_for_status()
                rows = csv.DictReader(io.StringIO(response.text))
                for row in rows:
                    raw_time = row.get("measured_on", "").strip()
                    if not raw_time:
                        continue
                    day = date.fromisoformat(raw_time[:10])
                    if not date(2012, 7, 1) <= day <= date(2012, 7, 20):
                        continue
                    power = next((v for k, v in row.items() if k and k.startswith("w_avg__")), "")
                    energy = next((v for k, v in row.items() if k and k.startswith("wh_sum__")), "")
                    if not power:
                        continue
                    # New Orleans observes UTC-05:00 during this July slice.
                    local_time = datetime.fromisoformat(raw_time).replace(tzinfo=timezone(timedelta(hours=-5)))
                    writer.writerow([local_time.isoformat(), power, energy])
                    total += 1
    if total < 100:
        raise RuntimeError(f"Downloaded only {total} rows; refusing to write an incomplete sample")
    return total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    count = download_sample(args.output)
    print(f"Saved {count:,} measured PVDAQ rows to {args.output}")
    print("Dataset: NREL PVDAQ system 1245, July 1–20, 2012; CC BY 4.0; see README attribution.")


if __name__ == "__main__":
    main()
