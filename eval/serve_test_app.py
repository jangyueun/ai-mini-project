"""화면 검증 전용 서버. 실제 그래프/SQLite + 고정 응답 LLM/기록용 MCP.
운영 실행은 README의 Ollama 스크립트를 사용한다.
"""
import argparse
import os
from pathlib import Path
import sys
p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--port',type=int,required=True);p.add_argument('--db');p.add_argument('--frontend-backend');a=p.parse_args()
sys.path.insert(0,str(Path(a.root).resolve()))
os.environ.update(LANGCHAIN_TRACING_V2='false',LANGSMITH_TRACING='false',LLM_BACKEND='fake',SUPERVISOR_VERSION='v2')
import uvicorn
if a.frontend_backend:
 import web_demo_server
 web_demo_server.BACKEND=a.frontend_backend
 app=web_demo_server.app
else:
 import server
 from agent.session_store import SqliteSessionStore
 class MCP:
  async def start(self): self.n=0
  async def stop(self): pass
  async def find_prompt(self,*args): return 'ops'
  async def get_prompt(self,*args,**kw): return '현재 상태와 대응 매뉴얼을 확인하세요.'
  async def find_resource_template(self,*args): return 'ops','runbook://incident-response/{incident_type}'
  async def read_resource(self,uri,**kw):
   name=uri.rsplit('/',1)[-1]
   return (Path(a.root)/'data/runbooks'/f'{name}.md').read_text()
  async def call_tool(self,name,arguments):
   self.n+=1
   return {'system_name':arguments['system_name'],'status':'degraded','cpu_percent':90+self.n/10,'memory_percent':56.0,'alerts':['CPU high'],'last_checked':f'2026-10-21T10:00:{self.n:02d}+09:00'}
 server.MCPClient=MCP
 server.SqliteSessionStore=lambda:SqliteSessionStore(Path(a.db))
 app=server.app
uvicorn.run(app,host='127.0.0.1',port=a.port,log_level='warning')
