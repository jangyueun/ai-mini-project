"""같은 고정 입력으로 개선 전후를 비교. LLM/MCP는 테스트용 의존성으로 교체.
実行例: .venv/bin/python3 eval/compare_conversations.py --root . --output eval/after.json
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

p=argparse.ArgumentParser(); p.add_argument('--root',required=True); p.add_argument('--output',required=True); args=p.parse_args()
root=Path(args.root).resolve(); sys.path.insert(0,str(root))
os.environ.update(LANGCHAIN_TRACING_V2='false',LANGSMITH_TRACING='false',LLM_BACKEND='fake',SUPERVISOR_VERSION='v2')
from fastapi.testclient import TestClient
import server
from agent.session_store import SqliteSessionStore

class MCP:
    def __init__(self): self.calls=[]
    async def start(self): pass
    async def stop(self): pass
    async def find_prompt(self,*args): return 'ops'
    async def get_prompt(self,*args,**kw): return '모니터링과 대응 절차를 확인하세요.'
    async def find_resource_template(self,*args): return 'ops','runbook://incident-response/{incident_type}'
    async def read_resource(self,*args,**kw): return '# CPU 대응\n1. 상태 확인\n2. 로그 확인 권장\n3. 추가 조사'
    async def call_tool(self,name,arguments):
        self.calls.append(arguments['system_name'])
        return {'system_name':arguments['system_name'],'status':'degraded','cpu_percent':70+len(self.calls),'memory_percent':50,'alerts':['CPU high']}

rows=[]
with tempfile.TemporaryDirectory() as tmp:
    db=Path(tmp)/'eval.db'; mcp=MCP()
    with patch.object(server,'MCPClient',return_value=mcp),patch.object(server,'SqliteSessionStore',side_effect=lambda:SqliteSessionStore(db)):
        with TestClient(server.app) as client:
            def ask(message,thread):
                r=client.post('/chat',json={'message':message,'thread_id':thread}); r.raise_for_status(); return r.json()
            cases=[(s,'그 서비스 다시 확인해줘') for s in ['payments-service','cache-service','auth-service','web-01','log-service','gateway-service']]
            cases += [('payments-service',s) for s in ['다시 확인해줘','그 서버 다시 조회해줘','재진단해줘','그 시스템 다시 진단해줘']]
            for i,(target,q) in enumerate(cases):
                thread=f'followup-{i}'; ask(f'{target} CPU 급증 원인 진단해줘',thread); n=len(mcp.calls)
                result=ask(q,thread); calls=mcp.calls[n:]
                rows.append({'case':f'후속 요청 {i+1}','input':q,'expected':[target],'actual':calls,'pass':calls==[target]})
            ask('payments-service cache-service 장애 진단해줘','ambiguous'); n=len(mcp.calls)
            result=ask('그 서비스 다시 확인해줘','ambiguous')
            rows.append({'case':'복수 대상 확인 요청','pass':result['metadata']['route']=='clarify' and len(mcp.calls)==n})
            n=len(mcp.calls); ask('cache-service','ambiguous')
            rows.append({'case':'확인 질문에 서비스명으로 답변','expected':['cache-service'],'actual':mcp.calls[n:],'pass':mcp.calls[n:]==['cache-service']})
            n=len(mcp.calls); result=ask('그 서비스 다시 확인해줘','new-thread')
            rows.append({'case':'새 대화에서 이전 대상 사용 차단','pass':result['metadata']['route']=='clarify' and len(mcp.calls)==n})
            restored=client.get('/sessions/followup-0')
            ok=restored.status_code==200 and len(restored.json().get('messages',[]))==4
            rows.append({'case':'저장 대화 복원 API','pass':ok})
        # 실제 서버 수명주기 종료 후 동일 DB로 다시 초기화한다.
        with TestClient(server.app) as client:
            r=client.get('/sessions/followup-0')
            rows.append({'case':'API 재시작 후 메시지·대상 복원','pass':r.status_code==200 and r.json().get('context',{}).get('last_targets')==['payments-service']})
    # 기동 스크립트의 DB 초기화 정책만 분리 검증. 전체 기동/모델 속도 비교는 아니다.
    marker=Path(tmp)/'session.db'; marker.write_text('보존 확인')
    delete_lines=[l for l in (root/'sh/run_agent_ollma.sh').read_text().splitlines() if l.strip()=='rm -f session.db']
    for line in delete_lines: subprocess.run(['bash','-c',line],cwd=tmp,check=True)
    rows.append({'case':'Ollama 기동 스크립트 DB 보존 정책','pass':marker.exists()})
report={'source_root':str(root),'mode':'fixed inputs; fake LLM + recording MCP; real graph/API/SQLite',
        'followup_correct':sum(r['pass'] for r in rows[:10]),'followup_total':10,
        'checks_passed':sum(r['pass'] for r in rows),'checks_total':len(rows),'cases':rows}
Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=False))
