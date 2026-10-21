"""도구 호출 전 요청 의도·확인 대기·포함/제외 대상을 해석한다.

등록된 서비스명과 정해진 한국어 표현을 지원한다. 모호하면 대상을
추측하지 않고 확인한다. 과거 관측값은 이 모듈에 전달하지 않는다.
"""
import re

FOLLOWUP = re.compile(
    r"다시\s*(?:확인|조회|진단|조사|봐|보|체크)|재\s*(?:조회|진단|확인)|"
    r"그\s*(?:서비스|서버|시스템)|아까.*(?:서비스|서버|시스템)|복구.*(?:됐|되었|확인)"
)
INCIDENT = re.compile(r"장애|진단|다운|지연|급증|느[려리]|부족|타임아웃|문제|이상|확인|조회|조사|점검|cpu|메모리|디스크", re.I)
SERVICE_NAME = re.compile(r"(?<![a-z0-9_-])[a-z][a-z0-9_-]*-(?:service|\d+)(?![a-z0-9_-])", re.I)
EXCLUDE_AFTER = re.compile(r"^\s*(?:은|는|이|가|을|를)?\s*(?:말고|대신|제외|빼고|빼줘|아니라)")
EXCLUSION = re.compile(r"말고|대신|제외|빼고|빼줘|아니라")
LIST_JOIN = re.compile(r"^[\s,·/]*(?:(?:랑|와|과|하고|및|그리고)\s*)?$")
EXPLANATION = re.compile(r"설명|뜻|의미|요약|정리|뭔지|뭐야|무엇")
ACTION = re.compile(r"(?:확인|조회|진단|조사|점검|체크)(?:해|하|요청)|재조회|재진단")
NO_LOOKUP = re.compile(
    r"(?:확인|조회|진단|조사|점검|체크)(?:은|는|을|를)?\s*"
    r"(?:하지\s*(?:마|말|않)|말아|안\s*해|안\s*하|금지|(?:할\s*)?필요\s*없)|"
    r"(?:조회|진단|조사)\s*없이|도구\s*(?:없이|쓰지\s*마)"
)
CANCEL = re.compile(r"^\s*(?:(?:그\s*요청|이번\s*요청|확인\s*요청|진단|조회)[은는을를]?\s*)?(?:취소|그만|중단)(?:해|해줘|해주세요|할게|하자|요|해요|하세요)?[.!?\s]*$")
NEGATED_GROUP = re.compile(r"(?:둘\s*다|모두|전부)\s*(?:아니|말고|제외|빼)")
GROUP = re.compile(r"둘\s*다|모두|전부")


def mentioned_systems(query: str, known: set[str]) -> list[str]:
    return [m.group() for m in SERVICE_NAME.finditer(query.lower()) if m.group() in known]


def _system_choices(query: str) -> tuple[list[str], set[str], bool]:
    """A 말고 B, A와 B 빼고 C의 제외 대상을 분리한다."""
    matches = list(SERVICE_NAME.finditer(query.lower()))
    excluded = set()
    for i, match in enumerate(matches):
        if not EXCLUDE_AFTER.search(query[match.end():]):
            continue
        excluded.add(match.group())
        # 쉼표/접속사로 연결된 바로 앞 목록까지 같은 제외 범위다.
        j = i
        while j > 0 and LIST_JOIN.fullmatch(query[matches[j-1].end():matches[j].start()]):
            j -= 1
            excluded.add(matches[j].group())
    active = list(dict.fromkeys(m.group() for m in matches if m.group() not in excluded))
    return active, excluded, bool(EXCLUSION.search(query))


def _clarify(query: str, candidates: list[str], reply: str, reason: str) -> dict:
    candidates = list(dict.fromkeys(candidates))
    choices = f"\n선택 가능: {', '.join(candidates)}" if candidates else "\n조회할 서비스명을 직접 입력해 주세요."
    return {"mode": "clarify", "reply": reply + choices,
            "pending": {"query": query, "candidates": candidates, "reason": reason}}


def _diagnose(query: str, targets: list[str], inherited: bool = False) -> dict:
    return {"mode": "incident", "targets": targets, "inherited": inherited,
            "query": f"{query}\n확정된 조회 대상: {', '.join(targets)}. 이 대상만 현재 상태를 새로 조회해 진단하세요."}


def resolve_request(query: str, context: dict, known: set[str]) -> dict:
    query = query.strip()
    pending = context.get("pending") or {}
    last_targets = [s for s in context.get("last_targets", []) if s in known]
    active, excluded, has_exclusion = _system_choices(query)
    followup = bool(FOLLOWUP.search(query))
    explanation = bool(EXPLANATION.search(query))

    # 금지/취소 의도를 재조회 키워드보다 먼저 적용한다.
    if CANCEL.fullmatch(query) or NO_LOOKUP.search(query):
        if explanation:
            return {"mode": "chat", "query": query, "targets": [], "pending": None}
        return {"mode": "cancel", "reply": "추가 조회 요청을 취소했어요. 기존 대화와 조사 기록은 유지됩니다.", "pending": None}
    if explanation and not ACTION.search(query):
        return {"mode": "chat", "query": query, "targets": []}

    if NEGATED_GROUP.search(query):
        return _clarify(pending.get("query", query), sorted(known),
                        "이전 후보를 선택하지 않았어요. 조회할 서비스명을 알려 주세요.", "rejected_candidates")

    unknown = [s for s in active if s not in known]
    if unknown:
        return _clarify(query, sorted(known - excluded),
                        f"등록되지 않은 서비스입니다: {', '.join(unknown)}. 조회할 서비스명을 확인해 주세요.", "unknown")
    explicit = [s for s in active if s in known]
    if GROUP.search(query) and (pending or has_exclusion):
        pool = pending.get("candidates", sorted(known))
        explicit = [s for s in pool if s in known and s not in excluded]

    if has_exclusion and not excluded:
        # 복잡한 제외 표현을 이해했다고 가정하여 둘 다 조회하지 않는다.
        return _clarify(query, sorted(known), "제외할 대상과 조회할 대상을 서비스명으로 구분해 알려 주세요.", "ambiguous_exclusion")
    if has_exclusion and not explicit:
        return _clarify(query, sorted(known - excluded),
                        f"{', '.join(sorted(excluded))}는 조회 대상에서 제외했어요. 대신 어떤 서비스를 확인할까요?", "excluded")

    if explicit:
        selection_only = bool(pending) and not INCIDENT.search(query) and not followup
        if selection_only:
            return _diagnose(pending["query"], explicit, inherited=True)
        if followup or INCIDENT.search(query) or has_exclusion:
            return _diagnose(query, explicit)
        return {"mode": "normal", "query": query, "targets": explicit}

    # 확인 대기 중에는 마지막 성공 대상을 재사용하지 않는다.
    if pending:
        if followup or INCIDENT.search(query):
            return _clarify(pending["query"], [s for s in pending.get("candidates", []) if s in known],
                            "아직 조회할 대상이 정해지지 않았어요. 서비스명을 선택해 주세요.", pending.get("reason", "pending"))
        return {"mode": "chat", "query": query, "targets": []}

    if followup:
        if len(last_targets) == 1:
            return _diagnose(query, last_targets, inherited=True)
        reason = "직전에 여러 서비스를 조사했어요." if last_targets else "이 대화에는 이전 조사 대상이 없어요."
        return _clarify(query, last_targets or sorted(known), reason + " 어떤 서비스를 확인할까요?", "multiple" if last_targets else "missing")
    if INCIDENT.search(query):
        return _clarify(query, sorted(known), "조회할 서비스명을 알려 주세요. 임의의 서비스를 조사하지 않을게요.", "missing")
    return {"mode": "normal", "query": query, "targets": []}
