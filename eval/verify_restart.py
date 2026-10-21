"""실제 서버 재시작 뒤 앞서 만든 실모델 대화가 유지되는지 검증한다."""
import json
from pathlib import Path
import httpx
p=Path('eval/local_model_results.json'); data=json.loads(p.read_text())
with httpx.Client(base_url='http://127.0.0.1:8600',timeout=15) as c:
    r=c.get('/sessions/'+data['thread_id']);r.raise_for_status();restored=r.json()
    assert len(restored['messages'])==4
    assert restored['context']['last_targets']==['payments-service']
    data['restart_verified']={'messages':len(restored['messages']),'last_targets':restored['context']['last_targets'],'pass':True}
p.write_text(json.dumps(data,ensure_ascii=False,indent=2))
print('실제 서버 재시작 뒤 메시지 4개·payments-service 대상 보존 확인')
