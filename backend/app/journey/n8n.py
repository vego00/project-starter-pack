"""Turns a service design into an n8n workflow the user imports and finishes in the n8n editor.

Deterministic: the same design gives the same JSON. Node types, versions and the workflow shape
(nodes, connections, settings) were checked against n8n 2.49.5, released 2026-11-23
(github.com/n8n-io/n8n at tag n8n@2.49.5: packages/workflow/src/interfaces.ts for INode and
IConnection, each node's *.node.ts for its name and versions). Sticky notes that say what to do
next, and the chat model joined to an agent by an `ai_languageModel` connection, follow the
workflows the author built in an n8n course. The logic inside each node (code bodies, prompts,
Switch expressions, credentials) is left for the user; the notes say what each node must do.
"""

import json
import uuid
from collections import defaultdict

from app.journey.design import Node, ServiceDesign

N8N_VERSION = "2.49.5"
N8N_IMAGE = f"docker.n8n.io/n8nio/n8n:{N8N_VERSION}"
WORKFLOW_PATH = "n8n/workflow.json"

TRIGGER = ("n8n-nodes-base.webhook", 2.2)
STICKY = ("n8n-nodes-base.stickyNote", 1)
SWITCH = ("n8n-nodes-base.switch", 3.5)
BY_KIND = {
    "code": ("n8n-nodes-base.code", 2),
    "agent": ("@n8n/n8n-nodes-langchain.agent", 3.1),
    "human": ("n8n-nodes-base.wait", 1.1),
}
# Providers n8n has its own chat model node for. Others get a note to attach one by hand.
CHAT_MODELS = {
    "openai": ("@n8n/n8n-nodes-langchain.lmChatOpenAi", 1.3),
    "gemini": ("@n8n/n8n-nodes-langchain.lmChatGoogleGemini", 1.2),
    "ollama": ("@n8n/n8n-nodes-langchain.lmChatOllama", 1),
}
TRIGGER_NAME = "요청 받기"
STEP_X, STEP_Y = 260, 180


def _id(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"project-starter-pack/n8n/{name}"))


def _node(name: str, kind: tuple[str, float], position: list[int], parameters: dict) -> dict:
    node_type, version = kind
    return {
        "parameters": parameters,
        "id": _id(name),
        "name": name,
        "type": node_type,
        "typeVersion": version,
        "position": position,
    }


def _parameters(node: Node) -> dict:
    if node.kind == "code":
        body = f"// {node.responsibility}\n// 끝 조건: {node.done_when}\nreturn $input.all();"
        return {"mode": "runOnceForAllItems", "language": "javaScript", "jsCode": body}
    if node.kind == "agent":
        return {
            "promptType": "define",
            "text": "={{ JSON.stringify($json) }}",
            "options": {"systemMessage": node.responsibility},
        }
    return {"resume": "webhook", "options": {}}


def _notes(node: Node, limits: list[str]) -> str:
    lines = [f"맡은 일: {node.responsibility}", f"끝 조건: {node.done_when}",
             f"실패하면: {node.on_failure}"]  # fmt: skip
    lines += [f"도구 {tool.name}({tool.access}): {tool.reason}" for tool in node.tools]
    return "\n".join(lines + limits)


def _depths(design: ServiceDesign) -> dict[str, int]:
    """Steps from the entry along the edges, for a left-to-right layout."""
    depth = {design.workflow.entry: 0}
    frontier = [design.workflow.entry]
    while frontier:
        following = []
        for edge in design.workflow.edges:
            if edge.source in frontier and edge.target not in depth:
                depth[edge.target] = depth[edge.source] + 1
                following.append(edge.target)
        frontier = following
    last = max(depth.values(), default=0)
    return {node.id: depth.get(node.id, last + 1) for node in design.nodes}


def _guide(design: ServiceDesign, provider: str | None) -> str:
    todo = [
        "## 직접 만들 것",
        "",
        "1. 노드마다 메모(Notes)에 적힌 맡은 일대로 내용을 채운다. Code 노드는 네트워크를 쓸 수 "
        "없으니 외부 API 호출은 HTTP Request나 해당 서비스 노드로 바꾼다.",
        "2. 분기 노드(Switch)의 출력 번호 식을 메모의 조건대로 쓴다.",
        "3. AI Agent마다 chat model을 붙이고 자격 증명을 넣는다."
        + (
            ""
            if provider in CHAT_MODELS
            else " 고른 제공자 전용 노드가 없으면 HTTP Request로 부른다."
        ),
        "4. 사람 확인(Wait) 노드는 webhook으로 이어진다. 승인 화면이 필요하면 Form으로 바꾼다.",
    ]
    if design.workflow.loop_limits:
        todo.append("5. 반복 한도는 n8n이 대신 세지 않는다. 메모의 한도대로 횟수를 세어 멈춘다.")
    if design.unknowns:
        todo += ["", "## 먼저 정할 것", "", *[f"- {u.text}" for u in design.unknowns]]
    return "\n".join(todo)


def build_workflow(design: ServiceDesign, provider: str | None) -> dict:
    depth = _depths(design)
    row: dict[int, int] = defaultdict(int)

    def place(column: float) -> list[int]:
        key = int(column * 2)
        position = [int(column * STEP_X), row[key] * STEP_Y]
        row[key] += 1
        return position

    limits: dict[str, list[str]] = defaultdict(list)
    for limit in design.workflow.loop_limits:
        text = (f"반복 한도: {', '.join(limit.node_ids)} 최대 {limit.max_iterations}회, "
                f"넘으면 {limit.on_exceeded}")  # fmt: skip
        for node_id in limit.node_ids:
            limits[node_id].append(text)

    nodes = [_node(TRIGGER_NAME, TRIGGER, place(0),
                   {"httpMethod": "POST", "path": "service", "options": {}})]  # fmt: skip
    nodes[0]["webhookId"] = _id(f"webhook/{TRIGGER_NAME}")
    connections: dict[str, dict] = {}

    def link(source: str, output: int, target: str, kind: str = "main") -> None:
        outputs = connections.setdefault(source, {}).setdefault(kind, [])
        while len(outputs) <= output:
            outputs.append([])
        outputs[output].append({"node": target, "type": kind, "index": 0})

    for node in design.nodes:
        item = _node(node.id, BY_KIND[node.kind], place(depth[node.id] + 1), _parameters(node))
        item["notes"] = _notes(node, limits[node.id])
        if node.kind == "human":
            item["webhookId"] = _id(f"webhook/{node.id}")
        nodes.append(item)
        if node.kind == "agent" and provider in CHAT_MODELS:
            model = f"{node.id} 모델"
            nodes.append(_node(model, CHAT_MODELS[provider], place(depth[node.id] + 1.5),
                               {"options": {}}))  # fmt: skip
            link(model, 0, node.id, "ai_languageModel")
    link(TRIGGER_NAME, 0, design.workflow.entry)

    by_name = {item["name"]: item for item in nodes}
    for node in design.nodes:
        going = [e for e in design.workflow.edges if e.source == node.id and not e.on_failure]
        failing = [e for e in design.workflow.edges if e.source == node.id and e.on_failure]
        if len(going) == 1:
            link(node.id, 0, going[0].target)
        elif going:
            switch = f"{node.id} 분기"
            nodes.append(_node(switch, SWITCH, place(depth[node.id] + 1.5), {
                "mode": "expression", "numberOutputs": len(going), "output": "={{ 0 }}"}))  # fmt: skip
            nodes[-1]["notes"] = "\n".join(
                f"출력 {i}: {e.condition or '조건 없음'} → {e.target}" for i, e in enumerate(going)
            )
            link(node.id, 0, switch)
            for i, edge in enumerate(going):
                link(switch, i, edge.target)
        if failing:
            # The error output is the node's second main output (onError: continueErrorOutput).
            by_name[node.id]["onError"] = "continueErrorOutput"
            connections.setdefault(node.id, {}).setdefault("main", [[]])
            for edge in failing:
                link(node.id, 1, edge.target)

    nodes.append(_node("직접 만들 것", STICKY, [0, -360],
                       {"content": _guide(design, provider), "width": 520, "height": 340}))  # fmt: skip
    return {
        "name": "starter-pack workflow",
        "nodes": nodes,
        "pinData": {},
        "connections": connections,
        "active": False,
        "settings": {"executionOrder": "v1"},
    }


def workflow_json(design: ServiceDesign, provider: str | None) -> str:
    return json.dumps(build_workflow(design, provider), ensure_ascii=False, indent=2) + "\n"
