# 프로젝트 스타터팩 · Project Starter Pack

> Multi-Agent 프로젝트에 필요한 결정을 카드로 비교하며 직접 고르면, 결정 이유가 담긴 설계 문서를 만들어주는 서비스.

**현재 단계: S3 · AI 추천·근거 검증.** 결정 여정(S1·S2)이 동작하고, 모델은 연결 확인 단계다. 실행 골격 생성(S4)과 배포(S5)는 아직 없다.

## 왜 만드는가

막연한 불편을 실제로 개발하고 검증할 수 있는 프로젝트로 바꾸는 과정을 돕는다.
문서 개수나 에이전트 개수를 늘리는 것보다, 사용자가 다음 개발 행동을 결정할 수 있는지가 중요하다.

## 현재 목표

코딩 경험이 적은 현재 부트캠프 참여자를 초기 사용자로 삼아, 서비스를 배포하고 약 20명에게 실제로 제공한다. 사용 과정의 어려움과 피드백을 바탕으로 개선하고, 실제 요청 트래픽과 서비스 운영을 경험하는 것이 현재 목표다. 약 20명은 초기 사용자 규모이며 동시 접속 목표를 뜻하지 않는다.

## 방향

- **확정:** 사용자가 결정 카드를 비교해 직접 고른다. 시스템은 추천과 근거, 영향 범위를 보여준다.
- **확정:** 오케스트레이션은 LangGraph, 다음 카드와 충돌 판정은 결정론적 코드로 처리한다.
- **제안:** 첫 MVP는 결정 여정과 검증 가능한 설계 패키지 생성에 집중한다.
- **확정:** 서비스 자체를 배포해 초기 사용자 약 20명에게 제공한다.
- **후속 검토:** 생성한 에이전트 실행, 코드 생성, 저장소 구성, 사용자 프로젝트의 인프라 생성 및 배포.

이 저장소는 스타터팩을 생성하는 서비스 자체의 설계 공간이다. 사용자가 받는 스타터팩은 별도의 생성 결과물이다.

## 학습 지식 적용

초기에는 부트캠프에서 배운 방법론과 자료를 활용하고, 이후 다른 교육·개인 학습 자료로 확장한다. 강의가 진행 중인 지금은 사람이 확인한 필기만 수동으로 연결하고, 자료가 쌓이면 검색으로 확장한다. 자료의 성격에 따라 기본 지침, 워크플로, RAG로 검색할 지식, 검증 기준으로 구분하여 적용한다. 적용한 자료의 출처와 버전을 추적한다.

우선 에이전트를 설계하는 과정에 학습 지식을 연결한다. 생성된 에이전트가 실행 중 지식을 검색하는 기능은 실행 단계에서 확장한다. 구체적인 검색 기술과 모델은 아직 미확정이다.

## 문서 관리

상세 기획·설계·로드맵은 [노션](https://app.notion.com/p/40f96199efb380ddb7ddeac8ca9d82dd)에서 관리하고, 작업 현황은 [Unified Backlog](https://app.notion.com/p/40f96199efb381e387c2e4ffbfbeedf9)에서 관리한다. 초기 docs는 [이전 커밋](https://github.com/vego00/project-starter-pack/tree/e7a14043bf6383df81d865314714bc9c76254576/docs)에 보존되어 있다.

## 저장소 구조와 브랜치

| 경로 | 용도 |
| --- | --- |
| pyproject.toml, uv.lock | uv 워크스페이스, 공통 개발 도구, 의존성 잠금 |
| compose.yaml | FE·BE·PostgreSQL 로컬 컨테이너 실행 |
| compose.prod.yaml | 운영 VM용 덮어쓰기. FE를 Nginx 정적 이미지로 바꾼다 |
| frontend/ | 사용자 웹 UI (npm) |
| backend/ | API와 서비스 로직 (워크스페이스 멤버) |
| agents/ | 재사용 가능한 에이전트 구성 (추후 멤버 추가) |
| benchmarks/datasets/, benchmarks/evaluators/ | 평가 데이터와 평가기 (추후 멤버 추가) |
| infrastructure/docker/, infrastructure/kubernetes/ | 환경·배포 구성 공간 |
| reports/ | 기계 생성 평가 결과 |
| tests/ | 테스트 |
| experiments/ | experiment 브랜치 전용 실험 |

experiment 브랜치에는 01_jev, 02_reasoning_graph, 03_mcp_tool_use, 04_agent_serving 실험 폴더를 둔다. main에는 experiments/를 추적하지 않는다. 검증된 결과만 제품 경로로 옮겨 반영하며 실험 브랜치를 통째로 병합하지 않는다. .gitignore만으로 추적 파일 유입을 막을 수 없으므로 CI에서도 main의 experiments/ 유입을 검사한다.

.gitkeep만 있는 폴더는 준비 구조이며, 기능 구현 또는 인프라 도입 확정을 의미하지 않는다.

## 로컬 실행

기본값은 mock이다. 이때 결정 카드의 추천은 카드 기본값이며 프로젝트를 분석한 결과가 아니다.
실제 모델을 쓰려면 `.env`에 키를 넣고 `APP_PROVIDER=gemini`, `APP_DECIDER=jev`로 바꾼 뒤 연결을 확인한다.
이때 프로젝트 아이디어가 Gemini API와 Jev 경로(`APP_JEV_ROUTE`)로 전송된다. 무료 경로에는 실제 고객 정보나 기밀을 넣지 않는다.

```bash
uv run python scripts/smoke_models.py
```

```bash
# 로컬 환경 (uv, Node.js 22.12 이상)
uv sync
npm --prefix frontend ci
cp .env.example .env          # 이미 있으면 건너뛴다
docker compose up -d postgres # 여정 저장에 필요하다
./scripts/dev.sh

# 또는 컨테이너
docker compose up --build

# 운영용 프런트(Nginx가 빌드한 정적 파일 제공)로 실행
docker compose -f compose.yaml -f compose.prod.yaml up --build
```

웹 UI는 http://127.0.0.1:5173, API 문서는 http://127.0.0.1:8000/docs 에서 확인한다.

새 Python 멤버를 추가할 때는 해당 폴더에 pyproject.toml을 만들고 루트 pyproject.toml의 `tool.uv.workspace.members`에 등록한 뒤 `uv lock`을 실행한다.

## 산출물

지금은 프로젝트 GCB, 카드별 결정과 이유, 확인할 점을 담은 결정 요약 Markdown을 제공한다. 설계 문서·ADR(R-006)과 실행 골격(S4)은 후속 작업이다.
에이전트가 필요하지 않은 문제에는 일반 코드나 규칙 기반 처리를 제안할 수 있어야 한다.

## 작업 원칙

1. 사실·해석·가정·제안을 구분한다.
2. 모델과 프레임워크보다 사용자 문제와 결과물 계약을 먼저 정한다.
3. 생성 시스템의 역할과 생성되는 에이전트의 역할을 구분한다.
4. 기술 스택은 선택 이유와 도입 조건을 기록한다.
5. 현재 문서의 제안은 구현 완료나 성능 검증을 의미하지 않는다.
