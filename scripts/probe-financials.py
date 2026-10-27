"""Deployment diagnostic for one public company. No portfolio or credentials logged."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import fundamentals

try:
    record=fundamentals.fetch('KOG.OL')
    report=fundamentals.analyse(record)
    print(json.dumps({'symbol':'KOG.OL','status':report['status'],'period':report['period'],
                      'available_fields':list(report['metrics']), 'missing':report['missing']}))
except Exception as error:
    print(json.dumps({'symbol':'KOG.OL','status':'provider_unavailable','reason':fundamentals.error_message(error)}))
