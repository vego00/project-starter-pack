# 저장된 초안 다시 검사 (20261118T083003586515Z-v7-C4-design)

## C4-design flow run 1 · 시도 1

- 판정: 거절 · 규칙: io.unconnected · 실행 때와 비교: 같음
- 모델: gemini-3.5-flash-lite · 프롬프트: design-v7 · 토큰 in/out: 2186/4069
- 이 시도가 받은 고칠 점: 0개

거절 이유:
- `io.unconnected` 노드 handle_failure의 입력 repo_url을 만드는 곳이 없어요

관련 노드와 연결선:
- `handle_failure` (code) 도구: write_error_log(write)
  - code_test_runner → handle_failure [실패 길] 조건: 테스트 실행이 실패하거나 멈췄을 때
  - feedback_writer_agent → handle_failure [실패 길] 조건: 생성 중 오류가 발생했을 때
  - code_analyzer_agent → handle_failure [실패 길] 조건: 정제 중 오류가 발생했을 때
  - instructor_review_human → handle_failure 조건: 강사가 피드백을 거절했을 때
  - feedback_sender_code → handle_failure [실패 길] 조건: 전송 중 오류가 발생했을 때

## C4-design flow run 2 · 시도 1

- 판정: 거절 · 규칙: decision.too_few_agents, trace.output_not_produced · 실행 때와 비교: 같음
- 모델: gemini-3.5-flash-lite · 프롬프트: design-v7 · 토큰 in/out: 2186/4130
- 이 시도가 받은 고칠 점: 0개

거절 이유:
- `decision.too_few_agents` 선택한 구조에는 에이전트가 2개 이상 필요한데 1개예요
- `trace.output_not_produced` 요구사항 req_history의 산출물 mistake_history을 담당 노드가 만들지 않아요

## C4-design flow run 2 · 시도 2

- 판정: 거절 · 규칙: owner.reader_has_no_input · 실행 때와 비교: 같음
- 모델: gemini-3.5-flash-lite · 프롬프트: design-v7 · 토큰 in/out: 2275/5055
- 이 시도가 받은 고칠 점: 2개
  - 선택한 구조에는 에이전트가 2개 이상 필요한데 1개예요 (고치는 법: 권한, 컨텍스트, 모델 능력이 다른 일을 찾아 agent 노드를 나누세요)
  - 요구사항 req_history의 산출물 mistake_history을 담당 노드가 만들지 않아요

거절 이유:
- `owner.reader_has_no_input` 노드 test_and_history_agent는 mistake_history을 읽는다고 했지만 그런 입력이 없어요

관련 노드와 연결선:
- `test_and_history_agent` (agent) 도구: db_read_history(read), code_tester(read)
  - collect_submissions → test_and_history_agent 조건: 제출 데이터 수집 성공
  - test_and_history_agent → feedback_draft_agent 조건: 테스트 및 이력 조회 성공
  - test_and_history_agent → handle_failure [실패 길] 조건: 테스트 실행 실패

## C4-design flow run 3 · 시도 1

- 판정: 거절 · 규칙: owner.reader_has_no_input · 실행 때와 비교: 같음
- 모델: gemini-3.5-flash-lite · 프롬프트: design-v7 · 토큰 in/out: 2186/4288
- 이 시도가 받은 고칠 점: 0개

거절 이유:
- `owner.reader_has_no_input` 노드 feedback_agent는 student_history을 읽는다고 했지만 그런 입력이 없어요

관련 노드와 연결선:
- `feedback_agent` (agent) 도구: vector_search(read), history_db(read)
  - test_runner_agent → feedback_agent 조건: 테스트 완료 시
  - feedback_agent → instructor_review 조건: 피드백 초안 생성 완료 시
  - feedback_agent → handle_failure [실패 길] 조건: 초안 생성 실패 시
  - instructor_review → feedback_agent 조건: 강사 거절 시 재작성 요청

## C4-design flow run 3 · 시도 2

- 판정: 거절 · 규칙: io.unconnected, owner.reader_has_no_input · 실행 때와 비교: 같음
- 모델: gemini-3.5-flash-lite · 프롬프트: design-v7 · 토큰 in/out: 2246/4291
- 이 시도가 받은 고칠 점: 1개
  - 노드 feedback_agent는 student_history을 읽는다고 했지만 그런 입력이 없어요 (고치는 법: readers에는 그 이름을 inputs로 받는 노드만 넣으세요)

거절 이유:
- `io.unconnected` 노드 history_agent의 입력 student_id을 만드는 곳이 없어요
- `io.unconnected` 노드 handle_failure의 입력 error_message을 만드는 곳이 없어요
- `owner.reader_has_no_input` 노드 feedback_agent는 feedback_draft을 읽는다고 했지만 그런 입력이 없어요

관련 노드와 연결선:
- `history_agent` (agent) 도구: db_read_history(read)
  - test_runner_code → history_agent 조건: 테스트 실행 성공
  - history_agent → feedback_agent
- `handle_failure` (code) 도구: log_error_to_db(write)
  - test_runner_code → handle_failure [실패 길] 조건: 테스트 실행 실패
  - send_feedback → handle_failure [실패 길] 조건: 발송 실패
- `feedback_agent` (agent) 도구: vector_search_lectures(read)
  - history_agent → feedback_agent
  - feedback_agent → instructor_review
  - instructor_review → feedback_agent 조건: 강사가 피드백 거절 및 수정 요청

## C4-design flow run 4 · 시도 1

- 판정: 거절 · 규칙: owner.reader_has_no_input · 실행 때와 비교: 같음
- 모델: gemini-3.5-flash-lite · 프롬프트: design-v7 · 토큰 in/out: 2186/4993
- 이 시도가 받은 고칠 점: 0개

거절 이유:
- `owner.reader_has_no_input` 노드 feedback_writer_agent는 context_summary을 읽는다고 했지만 그런 입력이 없어요

관련 노드와 연결선:
- `feedback_writer_agent` (agent) 도구: vector_search_lectures(read)
  - rag_helper_agent → feedback_writer_agent 조건: 컨텍스트 요약이 완료된 경우
  - feedback_writer_agent → instructor_review 조건: 초안 작성이 완료된 경우
  - feedback_writer_agent → handle_failure [실패 길] 조건: 에이전트 호출 실패 시
  - instructor_review → feedback_writer_agent 조건: 강사가 거절하여 초안을 다시 작성해야 하는 경우

## C4-design flow run 4 · 시도 2

- 판정: 거절 · 규칙: graph.no_exit, ref.unknown · 실행 때와 비교: 같음
- 모델: gemini-3.5-flash-lite · 프롬프트: design-v7 · 토큰 in/out: 2248/4645
- 이 시도가 받은 고칠 점: 1개
  - 노드 feedback_writer_agent는 context_summary을 읽는다고 했지만 그런 입력이 없어요 (고치는 법: readers에는 그 이름을 inputs로 받는 노드만 넣으세요)

거절 이유:
- `ref.unknown` 흐름 종료점: 없는 노드를 가리켜요: delivery_status
- `ref.unknown` 흐름 종료점: 없는 노드를 가리켜요: failure_log
- `graph.no_exit` 종료점으로 갈 수 없는 노드예요: handle_failure
- `graph.no_exit` 종료점으로 갈 수 없는 노드예요: code_test_agent
- `graph.no_exit` 종료점으로 갈 수 없는 노드예요: instructor_review_node
- `graph.no_exit` 종료점으로 갈 수 없는 노드예요: feedback_writer_agent
- `graph.no_exit` 종료점으로 갈 수 없는 노드예요: collector_node
- `graph.no_exit` 종료점으로 갈 수 없는 노드예요: delivery_node
- `graph.no_exit` 종료점으로 갈 수 없는 노드예요: history_loader_node

관련 노드와 연결선:
- `handle_failure` (code) 도구: save_failure_log(write)
  - code_test_agent → handle_failure [실패 길] 조건: 테스트 실패 또는 중단 시
- `code_test_agent` (agent) 도구: run_sandbox_test(read)
  - history_loader_node → code_test_agent
  - code_test_agent → feedback_writer_agent 조건: 테스트 성공 시
  - code_test_agent → handle_failure [실패 길] 조건: 테스트 실패 또는 중단 시
- `instructor_review_node` (human) 도구: 없음
  - feedback_writer_agent → instructor_review_node
  - instructor_review_node → delivery_node 조건: 강사 승인 시
  - instructor_review_node → feedback_writer_agent 조건: 강사 거절 및 수정 요청 시
- `feedback_writer_agent` (agent) 도구: search_lecture_notes(read)
  - code_test_agent → feedback_writer_agent 조건: 테스트 성공 시
  - feedback_writer_agent → instructor_review_node
  - instructor_review_node → feedback_writer_agent 조건: 강사 거절 및 수정 요청 시
- `collector_node` (code) 도구: save_submission_db(write)
  - collector_node → history_loader_node
- `delivery_node` (code) 도구: send_feedback_notification(external_write), save_approved_feedback(write)
  - instructor_review_node → delivery_node 조건: 강사 승인 시
- `history_loader_node` (code) 도구: read_history_db(read)
  - collector_node → history_loader_node
  - history_loader_node → code_test_agent

## C4-design flow run 5 · 시도 2

- 판정: 거절 · 규칙: io.unconnected, owner.reader_has_no_input · 실행 때와 비교: 같음
- 모델: gemini-3.5-flash-lite · 프롬프트: design-v7 · 토큰 in/out: 2299/4301
- 이 시도가 받은 고칠 점: 2개
  - state_fields.0.writers: List should have at least 1 item after validation, not 0 (고치는 법: 그 이름을 내보내는 노드를 writers에 넣거나 그 상태 필드를 빼세요)
  - state_fields.1.writers: List should have at least 1 item after validation, not 0 (고치는 법: 그 이름을 내보내는 노드를 writers에 넣거나 그 상태 필드를 빼세요)

거절 이유:
- `io.unconnected` 노드 handle_failure의 입력 error_info을 만드는 곳이 없어요
- `owner.reader_has_no_input` 노드 draft_feedback는 feedback_draft을 읽는다고 했지만 그런 입력이 없어요

관련 노드와 연결선:
- `handle_failure` (code) 도구: postgres_log_write(write)
  - fetch_and_test → handle_failure [실패 길] 조건: 테스트 실행이 실패했을 때
  - draft_feedback → handle_failure [실패 길] 조건: 초안 생성이 실패했을 때
  - deliver_feedback → handle_failure [실패 길] 조건: 피드백 전달이 실패했을 때
- `draft_feedback` (agent) 도구: pgvector_search(read)
  - fetch_and_test → draft_feedback 조건: 테스트 및 이력 조회가 성공했을 때
  - draft_feedback → instructor_review 조건: 초안 생성이 성공했을 때
  - draft_feedback → handle_failure [실패 길] 조건: 초안 생성이 실패했을 때
  - instructor_review → draft_feedback 조건: 강사가 피드백을 거절하고 수정을 요청했을 때

