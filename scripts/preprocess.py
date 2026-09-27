import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.ingest import normalize_csv
import pandas as pd
def main():
 p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True);a=p.parse_args();rows=normalize_csv(open(a.input,'rb').read());pd.DataFrame(rows).to_csv(a.output,index=False);print(f'normalized {len(rows)} rows')
if __name__=='__main__':main()

