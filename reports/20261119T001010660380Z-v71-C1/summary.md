# 평가 실행 20261119T001010660380Z

- commit: 890ece2
- working_tree_dirty: False
- provider: gemini
- decider: jev (typesafe)
- design_model: gemini-3.5-flash-lite
- prompt: design-v7.1
- runs: 5
- label: v71-C1
- design_calls: 7
- design_input_tokens: 12411
- design_output_tokens: 16957
- design_cost: 미확인
- start_calls: 0
- intake_budget: 20
- intake_card_dependencies: mock (extraction only)

| 사례 | 흐름 | 회수 | 맞춤 설계 | 단일 draft 통과 | 분기 있음 | 반복 한도 있음 | 조건 연결선(중앙값) | 걸린 규칙 | 429 | 초(중앙값) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C1 (확정) | flow | 5 | 4/5 | 3/5 | 4/4 | 0/4 | 7.0 | io.unconnected 2, owner.reader_has_no_input 1 | 0 | 32.703 |

| 사례 | 회 | 물은 카드 | 뺀 카드 | 꼭 물을 카드 누락 | 추천이 사례 선택과 같음 |
| --- | --- | --- | --- | --- | --- |
| C1 | 1 | 12 | - | 0 | 2/8 |
| C1 | 2 | 12 | - | 0 | 1/8 |
| C1 | 3 | 12 | - | 0 | 1/8 |
| C1 | 4 | 12 | - | 0 | 1/8 |
| C1 | 5 | 12 | - | 0 | 1/8 |

단일 draft 통과는 designer.draft 1회에 성공한 결과다. SDK 내부 HTTP 재시도는 미계측이다.
mock은 파이프라인 검증이며 모델 품질 결과가 아니다. 같은 family의 변형은 새 사용자 시나리오가 아니다.

| 평가 | 사례 | family | 완료 상태 | 자동 pass/fail/not_run | 사람 평가 대기 |
| --- | --- | --- | --- | --- | --- |
| design | C1 | C1 | completed | 5/0/0 | 0 |
| design | C1 | C1 | completed | 5/0/0 | 0 |
| design | C1 | C1 | completed | 5/0/0 | 0 |
| design | C1 | C1 | completed | 5/0/0 | 0 |
| design | C1 | C1 | completed | 5/0/0 | 0 |

횟수가 작아 1~2회 차이는 잡음으로 본다. 원자료는 같은 폴더의 results.json.
