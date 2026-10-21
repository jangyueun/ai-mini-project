"""실제 Ollama·MCP에서 제외 대상과 확인 대기·취소 처리를 검증한다."""
import json
from pathlib import Path
import time
from uuid import uuid4
import httpx

thread='t-web-final-'+uuid4().hex
cases=[('payments-service 말고 cache-service 다시 확인해줘','incident',['cache-service']),
       ('billing-service 다시 확인해줘','clarify',[]),
       ('그 서비스 다시 확인해줘','clarify',[]),
       ('그 서비스 다시 확인하지 마','cancelled',[])]
results=[]
with httpx.Client(base_url='http://127.0.0.1:8600',timeout=240) as c:
    assert c.get('/health').json()['llm_backend']=='ollama'
    for query,route,targets in cases:
        started=time.perf_counter()
        r=c.get('/chat/stream',params={'message':query,'thread_id':thread});r.raise_for_status()
        events=[json.loads(line[6:]) for line in r.text.splitlines() if line.startswith('data: ') and line[6:]!='[DONE]']
        answer=next((e for e in events if e.get('type')=='FinalAnswer'),None)
        assert answer and answer['saved']
        actual=[e['target'] for e in events if e.get('type')=='TaskCompleted' and e.get('source')=='monitoring']
        saved=c.get('/sessions/'+thread).json()
        actual_route=saved['messages'][-1]['metadata']['route']
        assert actual==targets and actual_route==route,(actual,actual_route)
        results.append({'query':query,'route':actual_route,'targets':actual,'elapsed_seconds':round(time.perf_counter()-started,2),'reply':answer['reply'],'pass':True})
        print(json.dumps({k:v for k,v in results[-1].items() if k!='reply'},ensure_ascii=False),flush=True)
    assert saved['context'].get('pending') is None
    assert saved['context']['last_targets']==['cache-service']
    Path('eval/local_boundary_results.json').write_text(json.dumps({'mode':'real Ollama + real MCP + SQLite','thread_id':thread,'requests':results,'restored_messages':len(saved['messages']),'passed':len(results),'total':len(cases)},ensure_ascii=False,indent=2))
