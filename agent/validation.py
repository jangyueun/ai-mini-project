"""조회한 CPU/메모리와 답변을 대조하는 보수적인 규칙 검수.

지원하는 수치 인용/비교 표현만 검사한다. 일반적인 인과관계나 모든 자연어의
사실성을 보장하지 않는다. 모호하거나 수치가 누락된 답변은 통과시키지 않는다.
"""
import math
import re

METRIC = re.compile(
    r"(?P<label>CPU(?:\s*(?:사용률|사용량))?|메모리(?:\s*(?:사용률|사용량))?|memory(?:\s*usage)?)"
    r"\s*(?:[:=]|[은는이가])?\s*(?:(?:현재|실제|관측|측정)(?:값|치)?\s*)?"
    r"(?P<value>\d+(?:\.\d+)?)\s*%", re.I)
PERCENT = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*%")
SYSTEM = re.compile(r"(?<![a-z0-9-])[a-z][a-z0-9]*(?:-[a-z0-9]+)*-(?:service|\d+)(?![a-z0-9-])")
COMPARISON = re.compile(r"^\s*(?:를|을|보다)?\s*(이상|초과|미만|이하|넘(?:은|는|어|었|고)|높(?:은|다)|낮(?:은|다))")
CONDITION = re.compile(r"(?:경우|이라면|이면|한다면|하면|일\s*때|지속\s*시|(?:초과|이상|미만|이하)\s*시(?:\s|$))")
WRITING_RULES = (
    " 각 서비스마다 서비스명, CPU와 메모리의 관측 숫자 및 %를 반드시 적어라. "
    "CPU와 메모리 바로 뒤에는 관측 숫자를 적고, '실제값' 같은 자리표시자는 쓰지 마라. "
    "현재 측정값과 알림 원문에 적힌 과거 수치를 구분하라. "
    "임계값을 넘었다는 사실 판단은 현재 값으로 계산하라. "
    "매뉴얼의 조건은 'CPU 90%를 넘을 경우'처럼 가정임을 분명히 하라. "
    "로그 조회는 수행하지 않았다. 로그를 분석했다거나 특이 패턴이 없다고 단정하지 말고 "
    "'로그 확인 필요'로 안내하라. 수치 표현은 CPU/메모리 실제 인용과 명확한 비교로 제한하라."
)


def monitoring_facts(collected: list[dict]) -> dict[str, dict]:
    facts = {}
    for item in collected:
        if item.get("source") != "monitoring":
            continue
        d = item.get("data", {})
        if not d.get("system_name") or d.get("status") in {None, "unknown"}:
            continue
        values = [d.get("cpu_percent"), d.get("memory_percent")]
        if all(isinstance(v, (int, float)) and not isinstance(v, bool)
               and math.isfinite(v) and 0 <= v <= 100 for v in values):
            facts[d["system_name"]] = d
    return facts


def validate_answer(draft: str, collected: list[dict]) -> dict:
    issues = []
    if len(draft.strip()) < 30 or "1)" not in draft:
        issues.append("형식 미달: 30자 이상이며 1) 번호 절차가 필요합니다.")
    facts = monitoring_facts(collected)
    if not facts:
        issues.append("유효한 CPU·메모리 조회 근거가 없습니다.")
        return {"ok": False, "issues": issues, "scope": "CPU/memory citation and supported comparisons"}
    text = draft.replace("**", "").replace("％", "%")
    # fake 모델이 인용하는 사용자 질문은 사실 주장으로 채점하지 않는다.
    text = text[text.find("1)"):] if "1)" in text else text
    runbooks = "\n".join(str(c.get("data", "")) for c in collected if c.get("source") == "runbook")
    source_alerts = " ".join(" ".join(d.get("alerts", [])) for d in facts.values())
    seen = set()
    owner = next(iter(facts)) if len(facts) == 1 else None
    blocks = re.split(r"\n|(?<!\d)\.(?!\d)|(?<!\d)[1-9]\)\s*|\s+·\s+", text)
    for block in blocks:
        names = list(SYSTEM.finditer(block))
        # 같은 문장에 여러 서비스가 있으면 서비스명마다 구간을 나눈다.
        starts = [0] + [m.start() for m in names if m.start() > 0]
        for left, right in zip(starts, starts[1:] + [len(block)]):
            part = block[left:right]
            found = SYSTEM.search(part)
            if found:
                name = found.group()
                if name in facts:
                    owner = name
                elif name not in source_alerts:
                    issues.append(f"조회하지 않은 서비스 언급: {name}")
                    owner = None
            handled = set()
            for m in METRIC.finditer(part):
                value = float(m["value"])
                field = "cpu_percent" if m["label"].lower().startswith("cpu") else "memory_percent"
                prefix, suffix = part[:m.start()], part[m.end():]
                number_start = m.start("value")
                handled.add(number_start)
                if not owner:
                    issues.append("수치의 서비스명을 명확히 구분해야 합니다.")
                    continue
                d = facts[owner]
                metric_name = "CPU" if field == "cpu_percent" else "메모리"
                compare = COMPARISON.search(suffix)
                conditional = bool(CONDITION.search(suffix[:25]) or "만약" in prefix[-10:])
                if conditional:
                    allowed = {float(x) for x in PERCENT.findall(runbooks)} | {d[field]}
                    if value not in allowed:
                        issues.append(f"매뉴얼에 없는 조건 수치: {metric_name} {value:g}%")
                    continue
                if compare:
                    op = compare[1]
                    actual = d[field]
                    valid = (actual >= value if op == "이상" else actual <= value if op == "이하"
                             else actual < value if op == "미만" or op.startswith("낮") else actual > value)
                    if not valid:
                        issues.append(f"{owner} {metric_name} 비교 오류: 실제 {actual:g}%, '{value:g}% {op}'는 거짓입니다.")
                    continue
                # 알림 원문은 현재 계측값과 구분하고, 해당 서비스 원문에 있는 값만 허용.
                if re.search(r"알림|경고문|원문", prefix[-24:]):
                    alert_values = {float(x) for x in PERCENT.findall(" ".join(d.get("alerts", [])))}
                    if value not in alert_values:
                        issues.append(f"{owner} 알림에 없는 수치: {value:g}%")
                    continue
                if not math.isclose(value, d[field], abs_tol=0.00001):
                    issues.append(f"{owner} {metric_name} 인용 오류: 실제 {d[field]:g}%, 답변 {value:g}%")
                else:
                    seen.add((owner, field))
            # 지원하지 않는 퍼센트 문장을 그냥 합격시키지 않는다.
            for m in PERCENT.finditer(part):
                if m.start(1) in handled:
                    continue
                prefix = part[:m.start()]
                value = float(m[1])
                alerts = " ".join(facts[owner].get("alerts", [])) if owner else ""
                alert_context = re.search(r"알림|경고|threshold|기준|원문|임계값", prefix[-55:], re.I)
                if alert_context and value in {float(x) for x in PERCENT.findall(alerts)}:
                    continue
                # 'CPU 88.4%는 90% 임계값을 초과'처럼 관측값 뒤의 비교도 검사한다.
                suffix = part[m.end():]
                previous = list(METRIC.finditer(prefix))
                if owner and previous and re.match(r"\s*(?:임계값|기준)?\s*(?:을|를|보다)?\s*(?:초과|이상|미만|이하|넘|높|낮)", suffix):
                    field = 'cpu_percent' if previous[-1]['label'].lower().startswith('cpu') else 'memory_percent'
                    allowed = {float(x) for x in PERCENT.findall(runbooks + ' ' + alerts)} | {facts[owner][field]}
                    if value in allowed:
                        op = re.search(r"초과|이상|미만|이하|넘|높|낮",suffix)[0]
                        actual = facts[owner][field]
                        valid = (actual >= value if op=='이상' else actual <= value if op=='이하'
                                 else actual < value if op in {'미만','낮'} else actual > value)
                        if not CONDITION.search(suffix[:25]) and not valid:
                            issues.append(f"{owner} 비교 오류: 실제 {actual:g}%, '{value:g}% {op}'는 거짓입니다.")
                        continue
                issues.append(f"서비스·지표 또는 근거를 확인할 수 없는 수치: {value:g}%")
    for name in facts:
        for field, label in [("cpu_percent", "CPU"), ("memory_percent", "메모리")]:
            if (name, field) not in seen:
                issues.append(f"{name}의 실제 {label} 수치를 서비스명과 함께 명시하세요.")
    # 이 프로그램에는 로그 조회 도구가 없다. 권고와 이미 수행했다는 단정을 구분한다.
    if re.search(r"(?:로그|패턴).{0,30}(?:확인|분석).{0,20}(?:특이.*없|이상.*없|완료|확인됐|확인되었)", text):
        issues.append("로그 조회 근거가 없습니다. '로그 확인 필요'처럼 미확인 사항으로 표현하세요.")
    return {"ok": not issues, "issues": list(dict.fromkeys(issues)),
            "scope": "CPU/memory citation and supported comparisons"}


def evidence_fallback(collected: list[dict]) -> str:
    lines = ["답변 검증을 통과하지 못해 AI 초안을 제공하지 않습니다.", "확인된 모니터링 값:"]
    for name, d in monitoring_facts(collected).items():
        lines.append(f"- {name}: 상태 {d['status']}, CPU {d['cpu_percent']:g}%, 메모리 {d['memory_percent']:g}%"
                     + (f", 조회 시각 {d['last_checked']}" if d.get("last_checked") else ""))
    if len(lines) == 2:
        lines.append("- 유효한 모니터링 수치가 없습니다.")
    lines.append("원인과 조치는 확인되지 않았습니다. 위 수치와 원본 매뉴얼을 확인해 주세요.")
    return "\n".join(lines)
