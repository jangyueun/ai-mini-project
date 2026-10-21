"""실제 Ollama 서버에 2회 요청해 맥락 연결과 신규 MCP 호출을 확인한다."""
import json
from pathlib import Path
import time
from uuid import uuid4
import httpx

thread='t-live-'+uuid4().hex
requests=[]
with httpx.Client(base_url='http://127.0.0.1:8600',timeout=240) as client:
    health=client.get('/health').json()
    if health.get('llm_backend')!='ollama': raise SystemExit('Ollama 서버를 먼저 실행하세요.')
    for query in ['payments-service CPU 급증 원인 진단해줘','그 서비스 다시 확인해줘']:
        started=time.perf_counter()
        r=client.get('/chat/stream',params={'message':query,'thread_id':thread}); r.raise_for_status()
        events=[json.loads(line[6:]) for line in r.text.splitlines() if line.startswith('data: ') and line[6:]!='[DONE]']
        final=next((e for e in events if e.get('type')=='FinalAnswer'),None)
        if not final: raise RuntimeError('최종 답변이 없습니다.')
        targets=[e['target'] for e in events if e.get('type')=='TaskCompleted' and e.get('source')=='monitoring']
        assert targets==['payments-service'],targets
        requests.append({'query':query,'elapsed_seconds':round(time.perf_counter()-started,2),'targets':targets,
                         'context_resolved':any(e.get('type')=='ContextResolved' for e in events),'reply':final['reply']})
        print(json.dumps({k:v for k,v in requests[-1].items() if k!='reply'},ensure_ascii=False),flush=True)
    assert requests[-1]['context_resolved']
    restored=client.get('/sessions/'+thread).json()
    assert len(restored['messages'])==4
    report={'mode':'real Ollama + real MCP subprocess + SQLite','thread_id':thread,'backend':health,
            'requests':requests,'restored_messages':len(restored['messages']),'last_targets':restored['context']['last_targets']}
    Path('eval/local_model_results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('실제 모델 검증 완료',flush=True)
