# 평가 실행 20261118T083003583665Z

- commit: 6898f56
- working_tree_dirty: False
- provider: gemini
- decider: jev (typesafe)
- design_model: gemini-3.5-flash-lite
- prompt: design-v7
- runs: 5
- label: v7-C3
- design_calls: 10
- design_input_tokens: 3735
- design_output_tokens: 4810
- design_cost: 미확인
- start_calls: 0
- intake_budget: 20
- intake_card_dependencies: mock (extraction only)

| 사례 | 흐름 | 회수 | 맞춤 설계 | 단일 draft 통과 | 분기 있음 | 반복 한도 있음 | 조건 연결선(중앙값) | 걸린 규칙 | 429 | 초(중앙값) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C3 (초안) | flow | 5 | 0/5 | 0/5 | 0/0 | 0/0 | - | io.unconnected 1, owner.reader_has_no_input 1, owner.writer_has_no_output 1 | 0 | 33.841 |

| 사례 | 회 | 물은 카드 | 뺀 카드 | 꼭 물을 카드 누락 | 추천이 사례 선택과 같음 |
| --- | --- | --- | --- | --- | --- |
| C3 | 1 | 12 | - | 0 | 4/8 |
| C3 | 2 | 12 | - | 0 | 4/8 |
| C3 | 3 | 12 | - | 0 | 4/8 |
| C3 | 4 | 12 | - | 0 | 4/8 |
| C3 | 5 | 12 | - | 0 | 4/8 |

단일 draft 통과는 designer.draft 1회에 성공한 결과다. SDK 내부 HTTP 재시도는 미계측이다.
mock은 파이프라인 검증이며 모델 품질 결과가 아니다. 같은 family의 변형은 새 사용자 시나리오가 아니다.

| 평가 | 사례 | family | 완료 상태 | 자동 pass/fail/not_run | 사람 평가 대기 |
| --- | --- | --- | --- | --- | --- |
| design | C3 | C3 | completed | 5/0/0 | 0 |
| design | C3 | C3 | completed | 5/0/0 | 0 |
| design | C3 | C3 | completed | 5/0/0 | 0 |
| design | C3 | C3 | completed | 5/0/0 | 0 |
| design | C3 | C3 | completed | 5/0/0 | 0 |

횟수가 작아 1~2회 차이는 잡음으로 본다. 원자료는 같은 폴더의 results.json.
