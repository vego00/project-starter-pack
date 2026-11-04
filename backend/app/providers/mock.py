from typing import Protocol

from app.schemas import AgentBlueprint, GenerateRequest, StarterPack


class StarterPackProvider(Protocol):
    async def generate_structured(self, task_input: GenerateRequest) -> StarterPack: ...


class MockProvider:
    """A deterministic UI/API fixture, not an analysis of the user's problem."""

    async def generate_structured(self, task_input: GenerateRequest) -> StarterPack:
        assumptions = [
            "이 결과는 화면과 API 연결을 확인하기 위한 고정 템플릿입니다.",
            "에이전트 필요성, 적합한 도구와 실행 가능성은 아직 판단하지 않았습니다.",
        ]
        assumptions.append(
            f"사용자가 제공한 참고 맥락: {task_input.context}"
            if task_input.context
            else "사용자, 작업 환경, 성공 기준은 추가 확인이 필요합니다."
        )
        return StarterPack(
            pain_point=task_input.pain_point,
            goal="입력한 불편을 검증 가능한 작은 프로젝트로 구체화하기 (예시 목표)",
            assumptions=assumptions,
            agent_recommended=None,
            agent_blueprint=AgentBlueprint(
                architecture="undetermined",
                roles=["요구사항 정리 (예시)", "설계 검토 (예시)"],
                workflow=[
                    "문제와 사용자 확인",
                    "성공 기준 작성",
                    "최소 해결 방법 비교",
                    "작은 사례로 검증",
                ],
                tools=[],
            ),
            next_steps=[
                "입력한 문제가 발생한 실제 사례 한 가지를 적어보세요.",
                "어떤 결과가 나오면 도움이 될지 성공 기준을 한 문장으로 정하세요.",
                "일반 코드나 규칙으로 충분한지 먼저 비교하고 에이전트 필요성을 검토하세요.",
            ],
        )
