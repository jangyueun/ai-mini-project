"""외부 모델/API 없이 실제 그래프·API·SQLite를 검증한다.
실제 모델 연결 검증은 별도 수동 시나리오로 기록한다.
"""
import os
os.environ['LANGCHAIN_TRACING_V2'] = 'false'
os.environ['LANGSMITH_TRACING'] = 'false'
os.environ['LLM_BACKEND'] = 'fake'
os.environ['SUPERVISOR_VERSION'] = 'v2'
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from agent.conversation import resolve_request
from agent.session_store import SqliteSessionStore
import server

KNOWN = {'payments-service', 'cache-service', 'auth-service', 'web-01'}


class RecordingMCP:
    def __init__(self):
        self.calls = []
    async def start(self): pass
    async def stop(self): pass
    async def find_prompt(self, name): return 'ops'
    async def get_prompt(self, *args, **kwargs): return '상태와 매뉴얼을 조회하세요.'
    async def find_resource_template(self, name): return 'ops', 'runbook://incident-response/{incident_type}'
    async def read_resource(self, uri, **kwargs):
        return '# CPU 대응\n1. 상태 확인\n2. 최근 변경 확인\n3. 추가 조사를 권장합니다.'
    async def call_tool(self, name, arguments):
        self.calls.append(arguments['system_name'])
        return {'system_name': arguments['system_name'], 'status':'degraded',
                'cpu_percent': 70 + len(self.calls), 'memory_percent':50,
                'last_checked':str(len(self.calls)), 'alerts':['CPU high']}


class ResolverTests(unittest.TestCase):
    def test_single_previous_target(self):
        r=resolve_request('그 서비스 다시 확인해줘',{'last_targets':['payments-service']},KNOWN)
        self.assertEqual(r['targets'],['payments-service'])
        self.assertTrue(r['inherited'])
    def test_multiple_previous_targets_clarify(self):
        r=resolve_request('다시 확인해줘',{'last_targets':['payments-service','cache-service']},KNOWN)
        self.assertEqual(r['mode'],'clarify')
        self.assertEqual(len(r['pending']['candidates']),2)
    def test_no_previous_target_clarify(self):
        self.assertEqual(resolve_request('다시 확인해줘',{},KNOWN)['mode'],'clarify')
    def test_explicit_target_overrides_previous(self):
        r=resolve_request('cache-service 다시 진단해줘',{'last_targets':['payments-service']},KNOWN)
        self.assertEqual(r['targets'],['cache-service'])
    def test_unknown_system_never_substituted(self):
        self.assertEqual(resolve_request('billing-service 장애 진단',{},KNOWN)['mode'],'clarify')
    def test_substring_does_not_match_known_target(self):
        self.assertEqual(resolve_request('unknown-payments-service 진단해줘',{},KNOWN)['mode'],'clarify')
    def test_pending_selection_keeps_original_request(self):
        r=resolve_request('cache-service',{'pending':{'query':'그 서비스 다시 확인해줘','candidates':['cache-service']}},KNOWN)
        self.assertEqual(r['mode'],'incident'); self.assertIn('다시 확인',r['query'])
    def test_greeting_is_not_incident(self):
        self.assertEqual(resolve_request('안녕',{},KNOWN)['mode'],'normal')
    def test_cancel_pending(self):
        self.assertEqual(resolve_request('취소',{'pending':{'query':'x'}},KNOWN)['mode'],'cancel')
    def test_missing_target_not_defaulted(self):
        self.assertEqual(resolve_request('로그인이 느려요',{},KNOWN)['mode'],'clarify')


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.path=Path(self.temp.name)/'test.db'
        self.store=SqliteSessionStore(self.path)
    def tearDown(self): self.store.close(); self.temp.cleanup()
    def turn(self):
        return {'final':'진단 결과','collected':[{'source':'monitoring','data':{'system_name':'payments-service','status':'degraded'}}], 'events':[{'type':'Finalize'}]}
    def test_reopen_preserves_history_and_context(self):
        self.store.save_turn('a','진단해줘',self.turn()); self.store.close(); self.store=SqliteSessionStore(self.path)
        self.assertEqual(len(self.store.load('a')),2)
        self.assertEqual(self.store.context('a')['last_targets'],['payments-service'])
    def test_other_thread_is_empty(self):
        self.store.save_turn('a','진단해줘',self.turn())
        self.assertEqual(self.store.load('b'),[]); self.assertEqual(self.store.context('b'),{})
    def test_clear_only_selected_thread(self):
        self.store.save_turn('a','a',self.turn()); self.store.save_turn('b','b',self.turn()); self.store.clear('a')
        self.assertEqual(self.store.load('a'),[]); self.assertEqual(self.store.context('a'),{})
        self.assertEqual(len(self.store.load('b')),2)
    def test_existing_database_migration(self):
        p=Path(self.temp.name)/'old.db'
        c=sqlite3.connect(p); c.execute('CREATE TABLE messages(thread_id TEXT,role TEXT,content TEXT,created TEXT)')
        c.execute("INSERT INTO messages VALUES('old','user','원본 기록','today')"); c.commit(); c.close()
        st=SqliteSessionStore(p)
        self.assertEqual(st.messages('old')[0]['content'],'원본 기록'); st.close()
    def test_pending_persists_without_overwriting_targets(self):
        self.store.save_turn('a','q',self.turn())
        self.store.save_turn('a','모호함',{'final':'선택해 주세요','pending_context':{'query':'다시 확인','candidates':['payments-service']}})
        self.assertEqual(self.store.context('a')['last_targets'],['payments-service'])
        self.assertTrue(self.store.context('a')['pending'])


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.path=Path(self.temp.name)/'api.db'
        self.mcp=RecordingMCP()
        self.patches=[patch.object(server,'MCPClient',return_value=self.mcp),
                      patch.object(server,'SqliteSessionStore',side_effect=lambda:SqliteSessionStore(self.path))]
        for p in self.patches:p.start()
        self.client=TestClient(server.app); self.client.__enter__()
    def tearDown(self):
        self.client.__exit__(None,None,None)
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def ask(self,message,thread='a'):
        r=self.client.post('/chat',json={'message':message,'thread_id':thread}); self.assertEqual(r.status_code,200); return r.json()
    def test_followup_uses_fresh_tool_data(self):
        self.ask('payments-service CPU 급증 진단해줘')
        first_calls=len(self.mcp.calls)
        r=self.ask('그 서비스 다시 확인해줘')
        self.assertEqual(self.mcp.calls[first_calls:],['payments-service'])
        self.assertIn('72%',r['reply'])
        self.assertTrue(any(e['type']=='ContextResolved' for e in r['events']))
    def test_multiple_targets_clarify_then_selection(self):
        self.ask('payments-service cache-service 장애 진단해줘')
        count=len(self.mcp.calls)
        r=self.ask('그 서비스 다시 확인해줘')
        self.assertEqual(r['metadata']['route'],'clarify'); self.assertEqual(len(self.mcp.calls),count)
        self.ask('cache-service')
        self.assertEqual(self.mcp.calls[count:],['cache-service'])
    def test_new_thread_does_not_inherit(self):
        self.ask('payments-service 장애 진단해줘','a'); n=len(self.mcp.calls)
        r=self.ask('다시 확인해줘','b')
        self.assertEqual(r['metadata']['route'],'clarify'); self.assertEqual(len(self.mcp.calls),n)
    def test_restore_messages_steps_context(self):
        self.ask('payments-service 장애 진단해줘')
        data=self.client.get('/sessions/a').json()
        self.assertEqual(len(data['messages']),2)
        self.assertTrue(data['messages'][1]['metadata']['events'])
        self.assertEqual(data['context']['last_targets'],['payments-service'])
    def test_delete_clears_context_too(self):
        self.ask('payments-service 장애 진단해줘'); self.client.delete('/sessions/a')
        self.assertEqual(self.client.get('/sessions/a').json()['messages'],[])
        self.assertEqual(self.ask('다시 확인해줘')['metadata']['route'],'clarify')
    def test_stream_saves_before_final_event_and_done(self):
        r=self.client.get('/chat/stream',params={'message':'payments-service 장애 진단해줘','thread_id':'stream'})
        events=[json.loads(x[6:]) for x in r.text.splitlines() if x.startswith('data: ') and x[6:]!='[DONE]']
        self.assertTrue(events[-1]['saved']); self.assertEqual(events[-1]['type'],'FinalAnswer')
        self.assertIn('[DONE]',r.text)
        self.assertEqual(len(self.client.get('/sessions/stream').json()['messages']),2)
        self.ask('그 서비스 다시 확인해줘','stream'); self.assertEqual(self.mcp.calls[-1],'payments-service')
    def test_failed_stream_does_not_save_partial_turn(self):
        async def broken(*args,**kwargs): raise RuntimeError('test failure')
        with patch.object(self.mcp,'call_tool',side_effect=broken):
            r=self.client.get('/chat/stream',params={'message':'payments-service 장애 진단해줘','thread_id':'failed'})
        self.assertIn('StreamError',r.text)
        self.assertEqual(self.client.get('/sessions/failed').json()['messages'],[])
    def test_api_input_validation(self):
        self.assertEqual(self.client.post('/chat',json={'message':'','thread_id':'a'}).status_code,422)
        self.assertEqual(self.client.get('/sessions/bad.id').status_code,422)
    def test_unknown_service_never_calls_tool(self):
        self.ask('billing-service 장애 진단해줘'); self.assertEqual(self.mcp.calls,[])
    def test_explicit_target_not_replaced_by_model(self):
        self.ask('payments-service 장애 진단해줘')
        # Fake plan이 추가하는 web-01을 대상 게이트가 제거한다.
        self.assertEqual(self.mcp.calls,['payments-service'])
    def test_api_reopen_preserves_pending_selection(self):
        self.ask('payments-service cache-service 장애 진단해줘'); self.ask('다시 확인해줘')
        self.client.__exit__(None,None,None)
        self.client=TestClient(server.app); self.client.__enter__()
        self.ask('cache-service')
        self.assertEqual(self.mcp.calls[-1],'cache-service')


if __name__=='__main__': unittest.main()
