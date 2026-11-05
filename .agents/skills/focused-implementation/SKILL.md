---
name: focused-implementation
description: Use when implementing, fixing, reviewing, or refactoring Project Starter Pack code to keep changes scoped and success criteria testable.
---

# Focused implementation

1. Read the root AGENTS.md and the current task's Notion contract. Identify the primary track, requested behavior and evidence needed for completion.
2. Inspect the affected code and existing conventions before proposing a change. State consequential assumptions; ask only when the answer changes correctness, authorization or the implementation boundary. Continue independent work.
3. Choose the smallest implementation that satisfies the contract. Reuse existing interfaces; do not introduce frameworks, configuration layers or speculative abstractions for possible future use.
4. Preserve the deterministic Journey Controller and Constraint Engine. Keep model decisions behind existing provider interfaces and user decisions behind interrupt.
5. Restrict the diff to the request. Remove imports or helpers made unused by this change; leave unrelated cleanup for a separate task.
6. For a bug, reproduce the failing behavior with a targeted check when feasible, then verify the fix. For other changes, validate observable behavior rather than writing tests that mirror implementation.
7. Inspect the final diff and use the verification-before-completion skill before reporting success.

Do not interpret simplicity as removing required access control, timeout handling, recovery or schema validation. A documentation-only task does not authorize runtime changes.

Background: [source notes](../SOURCES.md).
