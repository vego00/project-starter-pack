"""Blind scoring kits: per company, two responses under random IDs in random order.
The A/B key is written outside the scoring folders and is not given to the scorer."""
import json, random, secrets, sys
from pathlib import Path

here = Path(__file__).parent
out = Path(sys.argv[1])
RUBRIC = """채점 기준. 0은 없음, 1은 일부 충족, 2는 아래 기준 충족이다. 항목별 점수 옆에 응답의 근거 문장을 그대로 인용한다.

| 항목 | 2점 기준 |
| --- | --- |
| 실제 문제와 일치 | 원문에서 관찰한 실패와 발생 조건을 짚었다. |
| 실험의 판별력 | 구현 전에 구할 샘플, 비교 대상, 가정을 기각할 관찰 결과가 구체적이다. |
| 실패 후 행동 | 다음에 바꿀 설계 요소가 구체적이고 같은 실험으로 개선을 확인할 수 있다. |
| 사용자 개입 판단 | 주어진 권한에서 시도할 조치와 비용·권한·서비스 요구가 바뀌어 사용자 결정이 필요한 조건을 구별했다. |

규칙
- 네 항목을 합산하지 않는다.
- 응답이 여러 제안을 하면 결과와 맞는 것을 골라 쓰지 말고 응답이 밝힌 최우선 제안 하나를 채점한다. 우선순위가 없으면 처음 제시한 행동을 쓴다.
- 응답이 요청받지 않았는데 스스로 가정이나 실험을 제안해도 그대로 인정한다.
- 평가자용 기록에 없던 실패를 예상했어도 실험의 판별력은 독립적으로 채점한다.
- 사례 입력에 이미 적힌 제약을 되풀이한 것만으로는 ‘실제 문제와 일치’ 점수를 주지 않는다(평가자용 기록의 채점 메모 참고).
"""
FORMAT = """출력 형식. 응답마다 아래를 쓴다. 다른 설명은 붙이지 않는다.

### 응답 <ID>
- 구현 첫날 첫 행동(응답 문장 그대로 인용):
- 채점한 최우선 제안(응답 문장 그대로 인용, 없으면 '없음'):
- 실제 문제와 일치: <0|1|2> — 근거: "<응답 인용>" / 평가자용 기록의 어느 실패와 대응하는지
- 실험의 판별력: <0|1|2> — 근거: "<응답 인용>"
- 실패 후 행동: <0|1|2> — 근거: "<응답 인용>"
- 사용자 개입 판단: <0|1|2> — 근거: "<응답 인용>"

마지막에 두 응답의 구현 첫날 첫 행동이 실질적으로 같은지 다른지 한 문장으로 판정한다(설명 길이가 아니라 첫날 실제로 하는 일 기준).
"""
key = {}
for case in ["toss", "baemin", "daangn"]:
    text = (here / "cases" / f"{case}.md").read_text("utf-8")
    exec_input = (here / "prompts" / f"{case}-A.md").read_text("utf-8").split("\n\n", 1)[1]
    record = "## 평가자용 기록" + text.split("## 평가자용 기록", 1)[1]
    arms = ["A", "B"]
    random.SystemRandom().shuffle(arms)
    ids = [f"R-{secrets.token_hex(2).upper()}" for _ in arms]
    key[case] = dict(zip(ids, arms))
    parts = ["당신은 설계 응답을 채점하는 평가자다. 아래 사례 입력, 평가자용 기록, 채점 기준만 보고 두 익명 응답을 채점하라. "
             "두 응답이 어떤 조건에서 만들어졌는지는 알려 주지 않는다.",
             "## 사례 입력 (응답자가 받은 내용)\n\n" + exec_input.strip(), record.strip(), RUBRIC, FORMAT]
    for rid, arm in zip(ids, arms):
        resp = (here / "runs" / f"{case}-{arm}" / "response.md").read_text("utf-8")
        parts.append(f"## 응답 {rid}\n\n{resp.strip()}")
    d = out / f"score-{case}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "prompt.md").write_text("\n\n".join(parts) + "\n", "utf-8")
(out / "blind-key.json").write_text(json.dumps(key, indent=2), "utf-8")
print("ok", {c: list(v) for c, v in key.items()})
