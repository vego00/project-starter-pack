# 평가 실행 20261119T001010665207Z

- commit: 890ece2
- working_tree_dirty: False
- provider: gemini
- decider: jev (typesafe)
- design_model: gemini-3.5-flash-lite
- prompt: design-v7.1
- runs: 5
- label: v71-C4
- design_calls: 8
- design_input_tokens: 10860
- design_output_tokens: 22311
- design_cost: 미확인
- start_calls: 0
- intake_budget: 20
- intake_card_dependencies: mock (extraction only)

| 사례 | 흐름 | 회수 | 맞춤 설계 | 단일 draft 통과 | 분기 있음 | 반복 한도 있음 | 조건 연결선(중앙값) | 걸린 규칙 | 429 | 초(중앙값) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C4 (초안) | flow | 5 | 3/5 | 2/5 | 3/3 | 3/3 | 11 | io.unconnected 1, decision.too_few_agents 1 | 0 | 35.072 |

| 사례 | 회 | 물은 카드 | 뺀 카드 | 꼭 물을 카드 누락 | 추천이 사례 선택과 같음 |
| --- | --- | --- | --- | --- | --- |
| C4 | 1 | 11 | devops.orchestration 0.89 | 0 | 6/9 |
| C4 | 2 | 11 | devops.orchestration 0.93 | 0 | 6/9 |
| C4 | 3 | 11 | devops.orchestration 0.89 | 0 | 6/9 |
| C4 | 4 | 11 | devops.orchestration 0.89 | 0 | 6/9 |
| C4 | 5 | 11 | devops.orchestration 0.88 | 0 | 5/9 |

단일 draft 통과는 designer.draft 1회에 성공한 결과다. SDK 내부 HTTP 재시도는 미계측이다.
mock은 파이프라인 검증이며 모델 품질 결과가 아니다. 같은 family의 변형은 새 사용자 시나리오가 아니다.

| 평가 | 사례 | family | 완료 상태 | 자동 pass/fail/not_run | 사람 평가 대기 |
| --- | --- | --- | --- | --- | --- |
| design | C4 | C4 | completed | 5/0/0 | 0 |
| design | C4 | C4 | completed | 5/0/0 | 0 |
| design | C4 | C4 | completed | 5/0/0 | 0 |
| design | C4 | C4 | completed | 5/0/0 | 0 |
| design | C4 | C4 | completed | 5/0/0 | 0 |

횟수가 작아 1~2회 차이는 잡음으로 본다. 원자료는 같은 폴더의 results.json.
