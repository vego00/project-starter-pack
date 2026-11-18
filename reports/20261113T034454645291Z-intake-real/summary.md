# 평가 실행 20261113T034454645291Z

- commit: 3ce13a7
- working_tree_dirty: True
- provider: exaone
- decider: jev (typesafe)
- design_model: gemini-3.5-flash-lite
- prompt: design-v6
- runs: 1
- label: intake-real
- design_calls: 0
- start_calls: 1
- intake_budget: 5
- intake_card_dependencies: mock (extraction only)

| 사례 | 흐름 | 회수 | 맞춤 설계 | 단일 draft 통과 | 분기 있음 | 반복 한도 있음 | 조건 연결선(중앙값) | 걸린 규칙 | 429 | 초(중앙값) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

단일 draft 통과는 designer.draft 1회에 성공한 결과다. SDK 내부 HTTP 재시도는 미계측이다.
mock은 파이프라인 검증이며 모델 품질 결과가 아니다. 같은 family의 변형은 새 사용자 시나리오가 아니다.

| 평가 | 사례 | family | 완료 상태 | 자동 pass/fail/not_run | 사람 평가 대기 |
| --- | --- | --- | --- | --- | --- |
| intake | C4-intake-base | C4-feedback | product_error | 6/3/0 | 4 |

횟수가 작아 1~2회 차이는 잡음으로 본다. 원자료는 같은 폴더의 results.json.
