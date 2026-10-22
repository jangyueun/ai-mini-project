"""실측 JSON을 브라우저에서 읽는 비교표로 변환한다. 캡처의 원본이다."""
import html
import json
from pathlib import Path

root=Path(__file__).resolve().parent.parent
r=json.loads((root/'eval/validation_comparison.json').read_text())
rows=[('수치·비교 오류 차단',f"{r['before_errors_blocked']}/{r['error_cases']}",f"{r['after_errors_blocked']}/{r['error_cases']}"),
      ('정상 초안 통과',f"{r['before_valid_accepted']}/{r['valid_cases']}",f"{r['after_valid_accepted']}/{r['valid_cases']}")]
table=''.join(f'<tr><td>{a}</td><td>{b}</td><td>{c}</td></tr>' for a,b,c in rows)
cases=''.join(f"<tr><td>{html.escape(c['id'])}</td><td>{'정상' if c['valid'] else '오류'}</td><td>{'통과' if c['before_accepted'] else '차단'}</td><td>{'통과' if c['after_accepted'] else '차단'}</td></tr>" for c in r['cases'])
page=f'''<!doctype html><meta charset="utf-8"><title>수치 검증 개선 전후 실측</title>
<style>body{{font-family:'Apple SD Gothic Neo',sans-serif;margin:40px;color:#172139;background:#fff;max-width:1120px}}h1{{font-size:34px;margin-bottom:8px}}p{{font-size:20px;line-height:1.5}}table{{border-collapse:collapse;width:100%;margin:22px 0;font-size:25px}}td,th{{padding:18px;text-align:left;border:1px solid #ccd0dd}}th{{background:#172139;color:white}}tr:nth-child(even){{background:#f1f2f9}}.small{{font-size:16px;color:#566177}}.cases{{font-size:17px}}.cases td,.cases th{{padding:8px 14px}}</style>
<h1>수치 검증 개선 전후 실측</h1><p>동일한 초안 20개와 모니터링 근거로 검수기를 비교했습니다.</p>
<table><tr><th>검증 항목</th><th>기존 형식 검수</th><th>개선한 근거 검수</th></tr>{table}</table>
<p>사례: 실제 CPU 88.4%인데 “CPU 90% 초과”라고 쓴 초안은 차단합니다.</p>
<p class="small">조건: 고정된 개발·회귀 검증셋, 오류 13개 + 정상 7개. 모델 생성 정확도 또는 자연어 전반의 정확도를 뜻하지 않습니다.<br>원본: eval/validation_comparison.json<br>데이터셋 SHA-256: {r['dataset_sha256']}</p>
<h2>개별 판정</h2><table class="cases"><tr><th>고정 사례</th><th>기대</th><th>기존</th><th>개선</th></tr>{cases}</table>'''
(root/'doc/evidence/validation-comparison.html').write_text(page)
print(root/'doc/evidence/validation-comparison.html')
