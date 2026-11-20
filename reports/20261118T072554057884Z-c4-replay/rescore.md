# 저장된 초안 다시 검사 (20261118T072554057884Z-c4-replay)

## C4 flow run 1 · 시도 1

- 판정: 거절 · 규칙: loop.no_limit, loop.no_way_out · 실행 때와 비교: 같음
- 모델: gemini-3.5-flash-lite · 프롬프트: design-v6 · 토큰 in/out: 1981/4136
- 이 시도가 받은 고칠 점: 0개

거절 이유:
- `loop.no_way_out` 한도를 넘어도 순환을 벗어나지 못해요: draft_feedback, human_review
- `loop.no_limit` 반복 횟수 한도가 없는 순환이에요: fetch_code
- `loop.no_limit` 반복 횟수 한도가 없는 순환이에요: run_tests
- `loop.no_limit` 반복 횟수 한도가 없는 순환이에요: save_feedback

관련 노드와 연결선:
- `draft_feedback` (agent) 도구: 없음
  - rag_search → draft_feedback 조건: 검색 완료
  - rag_search → draft_feedback [실패 길] 조건: 검색 실패 시 기본 초안 작성
  - draft_feedback → human_review 조건: 초안 생성 완료
  - draft_feedback → draft_feedback [실패 길] 조건: 초안 생성 실패 시 재시도
  - human_review → draft_feedback [실패 길] 조건: 수정 요청 및 거절
- `human_review` (human) 도구: 없음
  - draft_feedback → human_review 조건: 초안 생성 완료
  - human_review → save_feedback 조건: 강사 승인
  - human_review → draft_feedback [실패 길] 조건: 수정 요청 및 거절
- `fetch_code` (code) 도구: git_clone(read)
  - fetch_code → run_tests 조건: 다운로드 성공
  - fetch_code → fetch_code [실패 길] 조건: 다운로드 실패 시 재시도
- `run_tests` (code) 도구: test_runner(read)
  - fetch_code → run_tests 조건: 다운로드 성공
  - run_tests → rag_search 조건: 테스트 완료
  - run_tests → run_tests [실패 길] 조건: 테스트 실패 시 해당 과제 재시도
- `save_feedback` (code) 도구: postgres_db(write)
  - human_review → save_feedback 조건: 강사 승인
  - save_feedback → save_feedback [실패 길] 조건: 저장 실패 시 재시도

반복 한도:
- human_review, draft_feedback: 최대 3회, 넘으면 → human_review

## C4 flow run 1 · 시도 2

- 판정: 거절 · 규칙: loop.no_way_out · 실행 때와 비교: 같음
- 모델: gemini-3.5-flash-lite · 프롬프트: design-v6 · 토큰 in/out: 2182/3920
- 이 시도가 받은 고칠 점: 4개
  - 반복 횟수 한도가 없는 순환이에요: fetch_code (고치는 법: 순환하는 노드를 모두 loop_limits의 node_ids에 넣고 max_iterations를 적으세요)
  - 한도를 넘어도 순환을 벗어나지 못해요: draft_feedback, human_review (고치는 법: on_exceeded를 그 순환에 들어 있지 않은 노드로 바꾸세요)
  - 반복 횟수 한도가 없는 순환이에요: run_tests (고치는 법: 순환하는 노드를 모두 loop_limits의 node_ids에 넣고 max_iterations를 적으세요)
  - 반복 횟수 한도가 없는 순환이에요: save_feedback (고치는 법: 순환하는 노드를 모두 loop_limits의 node_ids에 넣고 max_iterations를 적으세요)

거절 이유:
- `loop.no_way_out` 한도를 넘어도 순환을 벗어나지 못해요: feedback_draft_agent, human_review, save_and_notify

관련 노드와 연결선:
- `feedback_draft_agent` (agent) 도구: vector_search_tool(read)
  - code_test_agent → feedback_draft_agent [실패 길] 조건: 테스트 완료
  - feedback_draft_agent → human_review 조건: 초안 작성 완료
  - human_review → feedback_draft_agent 조건: 반려 및 수정 요청
- `human_review` (human) 도구: 없음
  - feedback_draft_agent → human_review 조건: 초안 작성 완료
  - human_review → feedback_draft_agent 조건: 반려 및 수정 요청
  - human_review → save_and_notify 조건: 승인 완료
  - save_and_notify → human_review [실패 길] 조건: 저장 오류 발생 시 재검토
- `save_and_notify` (code) 도구: db_feedback_write(write)
  - human_review → save_and_notify 조건: 승인 완료
  - save_and_notify → human_review [실패 길] 조건: 저장 오류 발생 시 재검토

반복 한도:
- feedback_draft_agent, human_review: 최대 3회, 넘으면 → save_and_notify

## C4 flow run 2 · 시도 1

- 판정: 거절 · 규칙: decision.too_few_agents, loop.no_way_out · 실행 때와 비교: 같음
- 모델: gemini-3.5-flash-lite · 프롬프트: design-v6 · 토큰 in/out: 1981/2590
- 이 시도가 받은 고칠 점: 0개

거절 이유:
- `loop.no_way_out` 한도를 넘어도 순환을 벗어나지 못해요: feedback_generator, instructor_approval
- `decision.too_few_agents` 선택한 구조에는 에이전트가 2개 이상 필요한데 1개예요

관련 노드와 연결선:
- `feedback_generator` (agent) 도구: vector_search(read), db_read(read)
  - code_test_runner → feedback_generator 조건: 테스트가 완료되거나 실패 로그가 수집된 경우
  - feedback_generator → instructor_approval 조건: 피드백 초안 생성이 완료된 경우
  - instructor_approval → feedback_generator 조건: 강사가 반려하여 수정을 요구한 경우
- `instructor_approval` (human) 도구: db_write(write)
  - feedback_generator → instructor_approval 조건: 피드백 초안 생성이 완료된 경우
  - instructor_approval → feedback_generator 조건: 강사가 반려하여 수정을 요구한 경우

반복 한도:
- feedback_generator, instructor_approval: 최대 3회, 넘으면 → instructor_approval

