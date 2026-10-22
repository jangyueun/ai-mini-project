"""동일한 고정 초안을 기존 형식 검수와 새 검수로 비교. LLM 정확도 평가 아님."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent.validation import validate_answer


def evidence(case):
    if case.get('empty'):
        return []
    rows = [{'source':'monitoring','data':{'system_name':'payments-service','status':'degraded',
        'cpu_percent':88.4,'memory_percent':53.7,'alerts':['CPU 91% (threshold 80%)']}}]
    if case.get('multi'):
        rows.append({'source':'monitoring','data':{'system_name':'cache-service','status':'degraded',
            'cpu_percent':42,'memory_percent':87.8,'alerts':[]}})
    rows.append({'source':'runbook','data':'CPU 90% 초과 시 추가 점검. 로그 확인 필요.'})
    return rows


def compare():
    raw = Path(__file__).with_name('validation_cases.json').read_bytes()
    results=[]
    for c in json.loads(raw):
        # 이전 validator의 실제 합격 조건. 이 평가에서는 모든 초안이 첫 시도 형식을 만족.
        before=len(c['draft'])>=30 and '1)' in c['draft']
        after=validate_answer(c['draft'],evidence(c))
        results.append({**c,'before_accepted':before,'after_accepted':after['ok'],'issues':after['issues']})
    invalid=[r for r in results if not r['valid']];valid=[r for r in results if r['valid']]
    return {'mode':'same fixed drafts and recorded monitoring evidence; no LLM benchmark',
        'baseline':'e33a5d7 validate_node: length>=30 and numbered format',
        'dataset_sha256':hashlib.sha256(raw).hexdigest(),'total':len(results),
        'error_cases':len(invalid),'valid_cases':len(valid),
        'before_errors_blocked':sum(not r['before_accepted'] for r in invalid),
        'after_errors_blocked':sum(not r['after_accepted'] for r in invalid),
        'before_valid_accepted':sum(r['before_accepted'] for r in valid),
        'after_valid_accepted':sum(r['after_accepted'] for r in valid),'cases':results}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',default='eval/validation_comparison.json');a=p.parse_args()
    report=compare();Path(a.output).write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=False))
    if report['after_errors_blocked']!=report['error_cases'] or report['after_valid_accepted']!=report['valid_cases']:
        raise SystemExit('검증 실패: 비교 결과를 확인하세요.')
