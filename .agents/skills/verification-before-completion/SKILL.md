---
name: verification-before-completion
description: Use before claiming a change is fixed, complete, passing, deployed, or ready for review, and before committing or opening a PR.
---

# Verify the claim

1. List the claims you intend to make and the evidence each requires.
2. Select checks from repository configuration and the task's Definition of Done. Never invent a test command.
3. Run the applicable checks on the final changed state. Read the exit code and failure summary; inspect relevant errors. Keep verbose logs out of the conversation.
4. Inspect the final diff for scope, accidental removals, broken references and conflicting instructions.
5. Report only what the evidence supports. Record failures, skipped checks and environmental blockers explicitly. A failed or unavailable check is not a pass.
6. After a relevant edit, rerun affected checks. Reuse evidence from this task only when the checked inputs and environment have not changed; do not repeat expensive checks just because a new message is being sent.
7. Before reporting a remote change, verify the target branch/commit and resulting diff. Distinguish a pushed branch, an open PR and a merged main branch.

| Claim | Evidence required |
| --- | --- |
| Instructions updated | Final file content, valid skill frontmatter, resolved local links and scope review |
| Bug fixed | Original symptom or targeted regression check now passes |
| Tests pass | Actual command, exit status and covered scope |
| Build works | Actual build result; lint alone is insufficient |
| UI works | Relevant interactions and states exercised; source review is not a click test |
| Provider works | Actual permitted provider response; mock tests cover only adapter behavior |
| Deployed | Target environment reachable and core flow exercised |
| User value verified | Actual user evidence; downloads or test counts alone are insufficient |

Follow AGENTS.md for model/data/image downloads and external costs. Do not fetch large assets, call paid models or deploy merely to obtain evidence. Perform available lightweight checks and report the remaining gap.

Background: [source notes](../SOURCES.md).
