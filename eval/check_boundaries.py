"""고정된 경계 시나리오를 실제 그래프·API로 평가. 자연어 전반 정확도 평가는 아니다."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

parser=argparse.ArgumentParser()
parser.add_argument('--root',required=True)
parser.add_argument('--output',required=True)
args=parser.parse_args()
root=Path(args.root).resolve()
sys.path.insert(0,str(root))
os.environ.update(LANGCHAIN_TRACING_V2='false',LANGSMITH_TRACING='false',LLM_BACKEND='fake',SUPERVISOR_VERSION='v2')
from fastapi.testclient import TestClient
from agent.session_store import SqliteSessionStore
from fixed_mcp import MonitoringMCP
import server

dataset=Path(__file__).with_name('boundary_cases.json').read_bytes()
cases=json.loads(dataset);results=[]
with tempfile.TemporaryDirectory() as tmp:
    db=Path(tmp)/'boundary.db';mcp=MonitoringMCP()
    with patch.object(server,'MCPClient',return_value=mcp),patch.object(server,'SqliteSessionStore',side_effect=lambda:SqliteSessionStore(db)):
        with TestClient(server.app) as client:
            def ask(query,thread):
                r=client.post('/chat',json={'message':query,'thread_id':thread});r.raise_for_status();return r.json()
            for i,case in enumerate(cases):
                thread=f'boundary-{i}'
                for query in case['setup']:ask(query,thread)
                count=len(mcp.calls);answer=ask(case['query'],thread)
                actual=mcp.calls[count:];route=answer['metadata']['route']
                passed=sorted(actual)==sorted(case['expected_targets']) and route==case['expected_route']
                results.append({**case,'actual_route':route,'actual_targets':actual,'pass':passed})
report={'mode':'fixed boundary scenarios; fake LLM + recording MCP; real graph/API/SQLite',
        'dataset_sha256':hashlib.sha256(dataset).hexdigest(),'passed':sum(x['pass'] for x in results),'total':len(results),'cases':results}
Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=False))
