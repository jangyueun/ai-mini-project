# 운영 장애 진단 AI 에이전트 개선

SKALA AI Mini-Project의 제공된 기본 프로그램을 바탕으로 대화 복원과 후속 진단 요청 처리를 개선하는 프로젝트입니다.

## 구현 상태

- 서버 재시작 시 대화 DB 보존
- 새로고침 후 대화·처리 단계 복원, 이전 대화 선택, 새 대화 시작, 현재 대화만 삭제
- 직전 조사 대상에 대한 후속 요청 연결, 복수·미등록 대상 확인
- 재진단 시 모니터링 Tool 신규 호출 (과거 수치 재사용 안 함)
- 조회 금지·취소·설명 요청 구분, 제외한 서비스 조회 차단, 확인 대기 중 과거 대상 재사용 차단
- 단위·API 통합 테스트와 개선 전후 비교, 브라우저 화면 검증

구현 설명·평가 조건·한계·화면 캡처: [2일차 구현 기록](doc/day2-implementation.md)

## 실행 방법

프로젝트 폴더에서 최초 환경 준비:

```bash
bash sh/setup_venv.sh
bash sh/setup_ollama.sh
cp .env.example .env
```

`.env`에 본인의 LangSmith 키를 설정합니다. 이미 설정한 `.env`는 덮어쓰지 않습니다. 로컬 Ollama 실행에는 OpenAI 키가 필요하지 않습니다.

첫 번째 터미널에서 백엔드를 실행합니다.

```bash
bash sh/run_agent_ollma.sh
```

두 번째 터미널에서 프론트엔드를 실행합니다.

```bash
bash sh/run_frontend.sh
```

브라우저에서 <http://localhost:8600>에 접속합니다. 각 터미널에서 `Control + C`로 종료합니다.

서버를 다시 켜도 대화 기록을 보존합니다. 화면의 **현재 대화 기록 삭제**는 선택한 대화만 삭제하며, **새 대화 시작**은 기존 기록을 보존하고 별도 대화를 만듭니다.

## 기술 및 자료

- 기본 구성: FastAPI, LangGraph, MCP, Ollama, SQLite, Vue 3, SSE, LangSmith
- 상세 구조와 기본 사용법: [제공된 README](doc/README.md)
- 모니터링 값은 실습용 샘플 데이터이며 실제 운영 서버에 연결되지 않습니다.
- API 키, 로컬 대화 DB, 가상환경은 Git에 포함하지 않습니다.

## 테스트

```bash
.venv/bin/python3 -m unittest discover -s tests -v
```

외부 API를 호출하지 않고 테스트용 의존성을 주입합니다. 실제 Ollama 모델 검증과 고정 입력 비교 결과는 `eval/`에 구분해 기록합니다.

추가 경계 검증: `eval/check_boundaries.py`와 `eval/boundary_cases.json`으로 24개 고정 시나리오를 평가합니다. 결과는 `eval/boundary_before.json`, `eval/boundary_after.json`에 기록하며 자유로운 자연어 전체의 정확도로 일반화하지 않습니다.
