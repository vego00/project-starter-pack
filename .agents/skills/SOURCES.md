# Development skill sources

Reviewed 2026-11-05. These are independently written project instructions informed by the following references, not a vendored installation of their plugins or source files.

| Reference | Reviewed file / blob | Project use |
| --- | --- | --- |
| [anti-slop](https://github.com/miqdadbadjuber/anti-slop) | core, antislop-code, antislop-ui | Purposeful UI, honest content, working states, meaningful comments |
| [Karpathy guidelines](https://github.com/multica-ai/andrej-karpathy-skills/blob/main/skills/karpathy-guidelines/SKILL.md) | 6a62d0441753157ca6ca50479e490c2948033adb | Scoped implementation and explicit assumptions |
| [attention-span Rundown](https://github.com/alexgreensh/attention-span/blob/main/plugins/attention-span/skills/rundown/SKILL.md) | 965f750b3f495dea969a6d1fb78f2427a35f94c4 | Outcome-first reporting without losing blockers |
| [attention-span Spartan](https://github.com/alexgreensh/attention-span/blob/main/plugins/attention-span/skills/spartan/SKILL.md) | 949a2225ed9c0527cbca1669288e898f54266582 | Distinguish short answers from complete deliverables |
| [verification-before-completion](https://github.com/obra/superpowers/blob/main/skills/verification-before-completion/SKILL.md) | Reviewed source at linked path | Match completion claims to observed evidence |

## Deliberate project choices

- Apply during authorized implementation; do not add recurring mode-selection or approval steps.
- Use current Notion design as the design reference; do not require a parallel DESIGN.md.
- Preserve user-requested style and useful existing UI patterns; do not ban punctuation, icon libraries or card layouts categorically.
- Do not impose strict comment line counts when contract or security details need explanation.
- Keep concise reporting flexible; do not force TL;DR, emoji, arrows or cold language.
- Verify the affected scope and preserve fresh evidence; do not require full application/model runs for instruction-only edits.
- Keep all large-download, budget and deployment boundaries in AGENTS.md.
- These skills govern development assistants. They are not runtime prompts, product agents or an LLM Wiki/RAG implementation.
- No installer, hook, MCP server, global setting or personal ChatGPT skill is installed by these files.
