"""저장된 측정 JSON을 비교표로 표시한다. 수치를 임의로 생성하지 않는다."""
import html
import json
from pathlib import Path
root=Path(__file__).resolve().parent
before=json.loads((root/'before.json').read_text());after=json.loads((root/'after.json').read_text())
rows=''.join(f'<tr><td>{html.escape(b["case"])}</td><td>{"통과" if b["pass"] else "미충족"}</td><td class="pass">{"통과" if a["pass"] else "미충족"}</td></tr>' for b,a in zip(before['cases'],after['cases']))
(root/'comparison.html').write_text(f'''<!doctype html><html lang="ko"><meta charset="utf-8"><title>대화 복원·후속 진단 기능 비교</title>
<style>body{{background:#f3f5fa;color:#20283a;font-family:-apple-system,"Apple SD Gothic Neo",sans-serif;margin:0;padding:38px}}main{{max-width:1100px;margin:auto;background:white;padding:32px;border-radius:16px}}h1{{font-size:27px;margin:8px 0 14px}}p{{line-height:1.6}}.tag{{color:#5b5bd6;font-weight:700}}.cards{{display:flex;gap:16px;margin:22px 0}}.card{{background:#f0f0ff;border-radius:12px;padding:20px;flex:1}}strong{{font-size:29px;display:block;margin-top:8px}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{border-bottom:1px solid #e3e6ee;padding:9px 12px;text-align:left}}th{{background:#f3f5fa}}.pass{{color:#176943}}.note{{font-size:13px;color:#555f73;background:#f4f6fa;padding:14px;border-radius:8px}}</style>
<main><div class="tag">AI Mini-Project · 동일 입력으로 기능 비교</div><h1>대화 복원과 후속 진단 대상 연결</h1>
<p>개선 전: 기본 코드 <code>5c6b9a0</code> · 개선 후: 대화 저장·맥락 해석 기능 추가</p>
<div class="cards"><div class="card">후속 요청의 기대 대상만 새로 조회<strong>{before['followup_correct']}/{before['followup_total']} → {after['followup_correct']}/{after['followup_total']}</strong></div><div class="card">전체 확인 항목 충족<strong>{before['checks_passed']}/{before['checks_total']} → {after['checks_passed']}/{after['checks_total']}</strong></div></div>
<table><thead><tr><th>확인 항목</th><th>개선 전</th><th>개선 후</th></tr></thead><tbody>{rows}</tbody></table>
<p class="note">조건: 동일한 고정 입력, fake LLM 및 기록용 MCP 사용. 실제 그래프·API·SQLite를 실행한 결과이며, 자유로운 자연어 전체의 정확도나 실모델 응답 속도 개선을 뜻하지 않습니다. 기동 스크립트 항목은 DB 삭제 정책을 분리 검증했습니다.<br>원본: eval/before.json · eval/after.json · 실제 Ollama 검증은 별도 기록.</p></main></html>''')
print('eval/comparison.html 생성 완료')
