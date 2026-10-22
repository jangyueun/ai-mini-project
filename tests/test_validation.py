import os
os.environ.update(LANGCHAIN_TRACING_V2='false',LANGSMITH_TRACING='false',LLM_BACKEND='fake',SUPERVISOR_VERSION='v2')
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from agent.validation import validate_answer, evidence_fallback, monitoring_facts
from agent.session_store import SqliteSessionStore
from test_conversation import RecordingMCP
import server


def collected(cpu=88.4, memory=53.7):
    return [{'source':'monitoring','data':{'system_name':'payments-service','status':'degraded',
            'cpu_percent':cpu,'memory_percent':memory,'alerts':[]}}]


def answer(cpu=88.4, memory=53.7):
    return f'1) payments-service: CPU {cpu}%, 메모리 {memory}%. 2) 로그 확인 필요. 3) 원인은 추가 조사하세요.'


class NumericValidationTests(unittest.TestCase):
    def test_fixed_correct_and_incorrect_reports(self):
        # 평가셋의 의미 기준을 그대로 확인. 실제 모델 성능 수치로 일반화하지 않는다.
        from eval.compare_validation import compare
        report=compare()
        for case in report['cases']:
            with self.subTest(case=case['id']):
                self.assertEqual(case['after_accepted'],case['valid'],case['issues'])
    def test_changed_values_are_detected_for_each_metric(self):
        for field in ('cpu','memory'):
            for value in (0,12.3,53.7,88.4,100):
                expected={'cpu':88.4,'memory':53.7}
                if value==expected[field]:continue
                draft=answer(**{**expected,field:value})
                with self.subTest(field=field,value=value):
                    self.assertFalse(validate_answer(draft,collected())['ok'])
    def test_supported_inclusive_and_exclusive_boundaries(self):
        for op,expected in [('이상',True),('이하',True),('초과',False),('미만',False)]:
            with self.subTest(op=op):
                self.assertEqual(validate_answer(answer()+f' CPU 88.4% {op}입니다.',collected())['ok'],expected)
    def test_no_data_is_not_zero_measurement(self):
        self.assertFalse(validate_answer(answer(0,0),[])['ok'])
        self.assertIn('유효한 모니터링 수치가 없습니다',evidence_fallback([]))
    def test_unknown_service_measurements_are_not_trusted(self):
        rows=collected();rows[0]['data']['status']='unknown'
        self.assertEqual(monitoring_facts(rows),{})
    def test_invalid_measurements_are_not_trusted(self):
        for value in (None,float('nan'),float('inf'),-1,101,True,'88.4'):
            with self.subTest(value=value):self.assertEqual(monitoring_facts(collected(cpu=value)),{})
    def test_fallback_contains_evidence_not_the_failed_claim(self):
        text=evidence_fallback(collected())
        self.assertIn('CPU 88.4%',text);self.assertIn('메모리 53.7%',text)
        self.assertIn('원인과 조치는 확인되지 않았습니다',text)
        self.assertNotIn('90%를 초과',text)
    def test_conditional_word_does_not_hide_wrong_observation(self):
        self.assertFalse(validate_answer(answer(99)+ ' 오류일 경우 점검하세요.',collected())['ok'])
    def test_unsupported_unlabelled_percentage_fails_closed(self):
        self.assertFalse(validate_answer(answer()+' 오류율은 17%입니다.',collected())['ok'])
    def test_missing_metric_or_service_is_not_accepted(self):
        rows=collected()+[{'source':'monitoring','data':{'system_name':'cache-service','status':'healthy',
             'cpu_percent':42,'memory_percent':60,'alerts':[]}}]
        self.assertFalse(validate_answer(answer(),rows)['ok'])
    def test_actual_value_label_is_supported(self):
        self.assertTrue(validate_answer(answer().replace('CPU 88.4','CPU 실제값 88.4').replace('메모리 53.7','메모리 현재 53.7'),collected())['ok'])
    def test_threshold_after_observed_value_is_checked(self):
        rows=collected()+[{'source':'runbook','data':'CPU 90% 초과 시 추가 점검'}]
        self.assertFalse(validate_answer(answer()+' CPU 88.4%는 90% 임계값을 초과합니다.',rows)['ok'])
        self.assertTrue(validate_answer(answer(95.2)+' CPU 95.2%는 90% 임계값을 초과합니다.',collected(cpu=95.2)+rows[-1:])['ok'])


class ValidationAPITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=Path(self.temp.name)/'v.db'
        self.mcp=RecordingMCP();self.calls=[]
        self.patches=[patch.object(server,'MCPClient',return_value=self.mcp),
            patch.object(server,'SqliteSessionStore',side_effect=lambda:SqliteSessionStore(self.db))]
        for p in self.patches:p.start()
        self.client=TestClient(server.app);self.client.__enter__()
    def tearDown(self):
        self.client.__exit__(None,None,None)
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    async def write(self,query,rows,attempt,feedback,on_token=None):
        self.calls.append((attempt,feedback));draft=self.bad if attempt<=self.fail_until else answer(rows[0]['data']['cpu_percent'],rows[0]['data']['memory_percent'])
        if on_token:on_token(draft)
        return draft,{'usd':0,'prompt':'test prompt'}
    def run_request(self,fail_until=1,stream=False):
        self.bad=answer(99,99);self.fail_until=fail_until
        with patch.object(server.app.state.deps.quality_llm,'write',side_effect=self.write):
            if stream:return self.client.get('/chat/stream',params={'message':'payments-service CPU 진단해줘','thread_id':'v'})
            return self.client.post('/chat',json={'message':'payments-service CPU 진단해줘','thread_id':'v'})
    def test_feedback_repairs_draft_and_saves_only_final(self):
        result=self.run_request().json()
        self.assertEqual(result['metadata']['validation_status'],'passed')
        self.assertEqual(len(self.calls),2);self.assertIn('인용 오류',self.calls[1][1])
        self.assertIn('CPU 71%',result['reply']);self.assertNotIn('99%',result['reply'])
        data=self.client.get('/sessions/v').json()
        self.assertEqual(data['messages'][1]['content'],result['reply'])
        self.assertEqual(data['messages'][1]['metadata']['validation_status'],'passed')
    def test_three_failures_return_evidence_without_forced_pass(self):
        result=self.run_request(fail_until=9).json()
        self.assertEqual(len(self.calls),3)
        self.assertEqual(result['metadata']['validation_status'],'failed')
        self.assertIn('AI 초안을 제공하지 않습니다',result['reply'])
        self.assertIn('CPU 71%',result['reply']);self.assertNotIn('99%',result['reply'])
        self.assertEqual(result['events'][-2]['status'],'failed')
    def test_sse_never_publishes_unvalidated_incident_tokens(self):
        response=self.run_request(fail_until=9,stream=True)
        events=[json.loads(x[6:]) for x in response.text.splitlines() if x.startswith('data: ') and x[6:]!='[DONE]']
        self.assertFalse(any(e['type']=='AnswerToken' for e in events))
        final=events[-1];self.assertEqual(final['type'],'FinalAnswer');self.assertTrue(final['saved'])
        self.assertNotIn('99%',final['reply']);self.assertIn('CPU 71%',final['reply'])
    def test_valid_first_draft_has_no_extra_model_calls(self):
        result=self.run_request(fail_until=0).json()
        self.assertEqual(result['metadata']['validation_status'],'passed')
        self.assertEqual(len(self.calls),1)
    def test_failed_report_still_preserves_followup_target(self):
        self.run_request(fail_until=9)
        data=self.client.get('/sessions/v').json()
        self.assertEqual(data['context']['last_targets'],['payments-service'])
        self.assertEqual(data['messages'][1]['metadata']['validation_status'],'failed')


if __name__=='__main__':unittest.main()
