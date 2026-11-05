---
name: concise-reporting
description: Use when reporting progress, findings, verification results, or handoffs for Project Starter Pack, especially when a long explanation could hide the outcome or a blocker.
---

# Concise reporting

1. Lead with the result and any blocker that materially limits it.
2. Include the changed behavior, relevant evidence and unresolved limitation. Use short connected Korean prose by default; use lists or tables only when they help comparison.
3. Separate implemented, mock-tested, real-provider-tested, deployed and user-validated states. Never compress them into a single “완료”.
4. Keep exact identifiers, conditions, counts and error information when they change the user's next action. Shorten repetition before shortening evidence.
5. For a concrete deliverable, preserve the detail needed to use it. A request for depth overrides the short-answer default; do not shorten code, contracts or verification merely to save words.
6. Link the relevant PR, commit or Notion item. End with a next action only when one is actually needed; do not invent a decision request.
7. Avoid mandatory emojis, TL;DR labels, fixed bullet symbols or a cold tone. Follow the user's requested format.

Example: “PR에 반영했고 문서 링크·스킬 형식 검사를 통과했어. 앱 실행 검증은 하지 않았고 main 병합 전이야.”

Background: [source notes](../SOURCES.md).
