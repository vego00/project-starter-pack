# 평가 실행 20261116T030101286796Z

- commit: 762c531
- working_tree_dirty: False
- provider: gemini
- decider: jev (typesafe)
- design_model: gemini-3.8-flash
- prompt: design-v6
- runs: 5
- label: design-3.8-flash
- design_calls: 28
- start_calls: 0
- intake_budget: 20
- intake_card_dependencies: mock (extraction only)

| 사례 | 흐름 | 회수 | 맞춤 설계 | 단일 draft 통과 | 분기 있음 | 반복 한도 있음 | 조건 연결선(중앙값) | 걸린 규칙 | 429 | 초(중앙값) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C1 (확정) | flow | 5 | 5/5 | 4/5 | 5/5 | 0/5 | 5 | owner.writer_has_no_output 1 | 0 | 38.127 |
| C3 (초안) | flow | 5 | 4/5 | 4/5 | 4/4 | 0/4 | 5.5 | owner.writer_has_no_output 1 | 0 | 47.795 |
| C4-design (초안) | flow | 5 | 5/5 | 2/5 | 5/5 | 0/5 | 8 | owner.reader_has_no_input 2, permission.write_without_approval 2, io.unconnected 1, owner.writer_has_no_output 1 | 0 | 107.756 |
| C4 (초안) | flow | 5 | 4/5 | 2/5 | 4/4 | 2/4 | 7.0 | owner.writer_has_no_output 3, permission.write_without_approval 2, owner.reader_has_no_input 1 | 0 | 104.224 |

| 사례 | 회 | 물은 카드 | 뺀 카드 | 꼭 물을 카드 누락 | 추천이 사례 선택과 같음 |
| --- | --- | --- | --- | --- | --- |
| C1 | 1 | 12 | - | 0 | 1/8 |
| C1 | 2 | 12 | - | 0 | 1/8 |
| C1 | 3 | 12 | - | 0 | 1/8 |
| C1 | 4 | 12 | - | 0 | 1/8 |
| C1 | 5 | 12 | - | 0 | 1/8 |
| C3 | 1 | 12 | - | 0 | 4/8 |
| C3 | 2 | 12 | - | 0 | 4/8 |
| C3 | 3 | 12 | - | 0 | 4/8 |
| C3 | 4 | 12 | - | 0 | 4/8 |
| C3 | 5 | 12 | - | 0 | 4/8 |
| C4-design | 1 | 11 | devops.orchestration 0.95 | 0 | 7/11 |
| C4-design | 2 | 11 | devops.orchestration 0.95 | 0 | 7/11 |
| C4-design | 3 | 11 | devops.orchestration 0.93 | 0 | 7/11 |
| C4-design | 4 | 11 | devops.orchestration 0.92 | 0 | 7/11 |
| C4-design | 5 | 11 | devops.orchestration 0.88 | 0 | 7/11 |
| C4 | 1 | 11 | devops.orchestration 0.89 | 0 | 5/9 |
| C4 | 2 | 11 | devops.orchestration 0.92 | 0 | 6/9 |
| C4 | 3 | 11 | devops.orchestration 0.92 | 0 | 5/9 |
| C4 | 4 | 11 | devops.orchestration 0.88 | 0 | 5/9 |
| C4 | 5 | 11 | devops.orchestration 0.92 | 0 | 5/9 |

단일 draft 통과는 designer.draft 1회에 성공한 결과다. SDK 내부 HTTP 재시도는 미계측이다.
mock은 파이프라인 검증이며 모델 품질 결과가 아니다. 같은 family의 변형은 새 사용자 시나리오가 아니다.

| 평가 | 사례 | family | 완료 상태 | 자동 pass/fail/not_run | 사람 평가 대기 |
| --- | --- | --- | --- | --- | --- |
| design | C1 | C1 | completed | 5/0/0 | 0 |
| design | C1 | C1 | completed | 5/0/0 | 0 |
| design | C1 | C1 | completed | 5/0/0 | 0 |
| design | C1 | C1 | completed | 5/0/0 | 0 |
| design | C1 | C1 | completed | 5/0/0 | 0 |
| design | C3 | C3 | completed | 5/0/0 | 0 |
| design | C3 | C3 | completed | 5/0/0 | 0 |
| design | C3 | C3 | completed | 5/0/0 | 0 |
| design | C3 | C3 | completed | 5/0/0 | 0 |
| design | C3 | C3 | completed | 5/0/0 | 0 |
| design | C4-design | C4-feedback | completed | 5/0/0 | 6 |
| design | C4-design | C4-feedback | completed | 5/0/0 | 6 |
| design | C4-design | C4-feedback | completed | 5/0/0 | 6 |
| design | C4-design | C4-feedback | completed | 5/0/0 | 6 |
| design | C4-design | C4-feedback | completed | 5/0/0 | 6 |
| design | C4 | C4 | completed | 5/0/0 | 0 |
| design | C4 | C4 | completed | 5/0/0 | 0 |
| design | C4 | C4 | completed | 5/0/0 | 0 |
| design | C4 | C4 | completed | 5/0/0 | 0 |
| design | C4 | C4 | completed | 5/0/0 | 0 |

횟수가 작아 1~2회 차이는 잡음으로 본다. 원자료는 같은 폴더의 results.json.
