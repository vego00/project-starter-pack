"""Builds the A/B prompts from each case's execution input. The brief fixes both sentences."""
import re, sys
from pathlib import Path

A = "아래 요구와 제약을 바탕으로 초기 설계안을 작성하고, 구현 첫날 무엇부터 할지 제안하라."
B_EXTRA = ("틀리면 설계를 크게 바꿔야 할 가정 하나를 골라라. 가장 작은 실험의 입력, 비교 대상, "
           "실패로 판단할 관찰 결과를 적어라. 실패했을 때 직접 시도할 조치와 사용자 결정이 필요한 조건을 구분하라.")

here = Path(__file__).parent
out = Path(sys.argv[1])
for case in ["toss", "baemin", "daangn"]:
    text = (here / "cases" / f"{case}.md").read_text("utf-8")
    block = text.split("## 실행 입력", 1)[1].split("\n## ", 1)[0]
    lines = [l[1:].lstrip() if l.startswith(">") else None for l in block.strip().splitlines()]
    body = "\n".join(l for l in lines if l is not None).strip()
    for arm, head in (("A", A), ("B", f"{A} {B_EXTRA}")):
        prompt = f"{head}\n\n{body}\n"
        (here / "prompts" / f"{case}-{arm}.md").write_text(prompt, "utf-8")
        d = out / f"{case}-{arm}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "prompt.md").write_text(prompt, "utf-8")
print("ok")
