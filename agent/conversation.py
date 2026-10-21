"""후속 요청의 대상만 복원한다. 과거 관측값은 재사용하지 않는다.

지원 범위는 등록된 서비스명과 명시적인 재조회 표현이다.
자유로운 대화 전체의 의미를 추측하지 않고, 모호하면 확인한다.
"""
import re

FOLLOWUP = re.compile(r"다시\s*(?:확인|조회|진단|조사|봐|보|체크)|재\s*(?:조회|진단|확인)|그\s*(?:서비스|서버|시스템)|아까.*(?:서비스|서버|시스템)|복구.*(?:됐|되었|됐는|확인)")
INCIDENT = re.compile(r"장애|진단|다운|지연|급증|느[려리]|부족|타임아웃|문제|이상|확인|조회|조사|점검|cpu|메모리|디스크", re.I)
SERVICE_NAME = re.compile(r"(?<![a-z0-9_-])[a-z][a-z0-9_-]*-(?:service|\d+)(?![a-z0-9_-])", re.I)


def mentioned_systems(query: str, known: set[str]) -> list[str]:
    # 부분 문자열 때문에 unknown-payments-service를 payments-service로 오인하지 않는다.
    return [m.group() for m in SERVICE_NAME.finditer(query.lower()) if m.group() in known]


def resolve_request(query: str, context: dict, known: set[str]) -> dict:
    explicit = list(dict.fromkeys(mentioned_systems(query, known)))
    unknown = [m.group() for m in SERVICE_NAME.finditer(query.lower()) if m.group() not in known]
    pending = context.get("pending") or {}
    followup = bool(FOLLOWUP.search(query))
    if query.strip() in {"취소", "취소해", "그만"} and pending:
        return {"mode": "cancel", "reply": "확인 요청을 취소했어요. 새로운 질문을 입력해 주세요.", "pending": None}
    if unknown:
        return {"mode": "clarify", "reply": f"등록되지 않은 서비스입니다: {', '.join(unknown)}. 조회할 서비스명을 확인해 주세요.",
                "pending": {"query": query, "candidates": sorted(known)}}
    if pending and re.search(r"둘\s*다|모두|전부", query):
        explicit = pending.get("candidates", [])
    if explicit:
        # 서비스명만 답하면 직전 확인 요청을 이어서 처리. 새 증상이 있으면 새 요청 우선.
        selection_only = bool(pending) and not INCIDENT.search(query) and not followup
        effective = f"{pending['query']}\n조회 대상: {', '.join(explicit)}. 현재 상태를 새로 조회해 진단하세요." if selection_only else query
        return {"mode": "incident" if selection_only or followup or INCIDENT.search(query) else "normal",
                "targets": explicit, "query": effective, "inherited": selection_only}
    if followup:
        targets = [s for s in context.get("last_targets", []) if s in known]
        if len(targets) == 1:
            return {"mode": "incident", "targets": targets,
                    "query": f"{query}\n직전 조사 대상: {targets[0]}. 과거 수치 대신 현재 상태를 새로 조회해 진단하세요.", "inherited": True}
        candidates = targets or sorted(known)
        reason = "직전에 여러 서비스를 조사했어요." if targets else "이 대화에는 이전 조사 대상이 없어요."
        return {"mode": "clarify", "reply": f"{reason} 어떤 서비스를 확인할까요?\n선택 가능: {', '.join(candidates)}",
                "pending": {"query": query, "candidates": candidates}}
    if pending and not INCIDENT.search(query):
        # 잡담에 답하면서 확인 대기는 보존한다. 다음 서비스명 답변도 연결할 수 있다.
        return {"mode": "normal", "targets": [], "query": query}
    if INCIDENT.search(query):
        return {"mode": "clarify", "reply": f"조회할 서비스명을 알려 주세요. 임의의 서비스를 조사하지 않을게요.\n선택 가능: {', '.join(sorted(known))}",
                "pending": {"query": query, "candidates": sorted(known)}}
    return {"mode": "normal", "targets": [], "query": query}
