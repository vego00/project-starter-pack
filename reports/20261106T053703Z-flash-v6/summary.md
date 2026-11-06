# 평가 실행 20261106T053703Z

- commit: ed17a72
- provider: gemini
- decider: jev (typesafe)
- design_model: gemini-3.5-flash
- prompt: design-v6
- runs: 3
- label: flash-v6
- design_calls: 50

| 사례 | 흐름 | 회수 | 맞춤 설계 | 첫 시도 통과 | 분기 있음 | 반복 한도 있음 | 조건 연결선(중앙값) | 걸린 규칙 | 429 | 초(중앙값) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C1 (확정) | flow | 3 | 1/3 | 0/3 | 1/1 | 0/1 | 12 | ref.unknown 2, owner.reader_has_no_input 1, owner.writer_has_no_output 1, graph.no_exit 1 | 0 | 91.1 |
| C1 (확정) | blank | 3 | 1/3 | 0/3 | 1/1 | 1/1 | 9 | ref.unknown 3, graph.no_exit 2 | 3 | 58.3 |
| C3 (초안) | flow | 3 | 1/3 | 1/3 | 1/1 | 0/1 | 6 | - | 6 | 26.5 |
| C3 (초안) | blank | 3 | 0/3 | 0/3 | 0/0 | 0/0 | - | - | 9 | 6.1 |
| C4 (초안) | flow | 3 | 0/3 | 0/3 | 0/0 | 0/0 | - | - | 7 | 26.3 |
| C4 (초안) | blank | 3 | 0/3 | 0/3 | 0/0 | 0/0 | - | loop.no_way_out 1, ref.unknown 1 | 8 | 6.5 |

| 사례 | 회 | 물은 카드 | 뺀 카드 | 꼭 물을 카드 누락 | 추천이 사례 선택과 같음 |
| --- | --- | --- | --- | --- | --- |
| C1 | 1 | 10 | - | 0 | 0/8 |
| C1 | 2 | 10 | - | 0 | 1/8 |
| C1 | 3 | 10 | - | 0 | 1/8 |
| C3 | 1 | 10 | - | 0 | 3/8 |
| C3 | 2 | 10 | - | 0 | 3/8 |
| C3 | 3 | 10 | - | 0 | 4/8 |
| C4 | 1 | 9 | devops.orchestration 0.88 | 0 | 6/9 |
| C4 | 2 | 9 | devops.orchestration 0.92 | 0 | 6/9 |
| C4 | 3 | 9 | devops.orchestration 0.91 | 0 | 6/9 |

횟수가 작아 1~2회 차이는 잡음으로 본다. 원자료는 같은 폴더의 results.json.
