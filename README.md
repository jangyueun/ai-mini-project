# 운영 장애 진단 AI 에이전트 개선

SKALA AI Mini-Project의 제공된 기본 프로그램을 바탕으로 대화 복원과 후속 진단 요청 처리를 개선하는 프로젝트입니다.

## 현재 상태

- 제공된 기본 프로그램의 Ollama 로컬 실행과 LangSmith 기록 확인 완료
- 아래 개선 기능은 구현 예정이며, 현재 저장소는 개선 전 기준 코드입니다.

## 개선 계획

1. **대화 기록 보존**: 실행 시 DB 자동 삭제를 제거하고 명시적 초기화로 분리
2. **채팅 화면 복원**: 새로고침 후 대화 ID 유지, 저장 기록 복원, 새 대화 시작
3. **후속 진단 요청**: 직전 조사 대상 연결, 모호한 대상 확인, 모니터링 재조회
4. **검증 및 비교**: 새로고침·재시작 후 복원, 후속 요청의 대상 정확도, 대화 간 분리 테스트

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

**현재 기본 실행 스크립트는 서버 기동 시 `session.db`를 삭제합니다.** 기록 보존은 향후 개선 대상입니다.

## 기술 및 자료

- 기본 구성: FastAPI, LangGraph, MCP, Ollama, SQLite, Vue 3, SSE, LangSmith
- 상세 구조와 기본 사용법: [제공된 README](doc/README.md)
- 모니터링 값은 실습용 샘플 데이터이며 실제 운영 서버에 연결되지 않습니다.
- API 키, 로컬 대화 DB, 가상환경은 Git에 포함하지 않습니다.
