"""Public provider diagnostics only; no holdings, keys or private state accessed."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import company_data
import app
try:
    record=company_data.fetch('KOG.OL')
    print(json.dumps({'company_data':record['status'],'sector':record.get('sector'),'source':record['source']}))
except Exception as error:
    print(json.dumps({'company_data':'unavailable','reason':type(error).__name__,'fallback':'Unclassified; user override available.'}))
try:
    q=app.fetch_quote('OSEBX.OL')
    print(json.dumps({'oslo_benchmark':'available','currency':q['currency'],'daily_observations':len(q['history']),'source':q['source']}))
except Exception as error:
    print(json.dumps({'oslo_benchmark':'unavailable','reason':type(error).__name__,'fallback':'Benchmark result remains unavailable; no invented prices.'}))
