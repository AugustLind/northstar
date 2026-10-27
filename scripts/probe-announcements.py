"""Check public NewsWeb connectivity from Oracle; no portfolio or body text logged."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import announcements

try:
    record=announcements.fetch_recent()
    sample=next((i for i in record['items'] if i['classification']['kind']=='calendar'),None)
    result={'status':'available','source':'Oslo Børs NewsWeb','notices':len(record['items']),
            'partial':record['partial'],'skipped':record['skipped'],'from':record['from'],'to':record['to']}
    if sample:
        try:
            dates=announcements.fetch_calendar(sample)
            result['calendar_probe']={'notice_id':sample['id'],'explicit_dates':len(dates)}
        except Exception as error:
            result['calendar_probe']={'status':'unavailable','reason':announcements.error_message(error)}
    print(json.dumps(result))
except Exception as error:
    print(json.dumps({'status':'provider_unavailable','source':'Oslo Børs NewsWeb','reason':announcements.error_message(error)}))
