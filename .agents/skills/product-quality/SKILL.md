---
name: product-quality
description: Use when building or reviewing frontend UI, product copy, generated summaries, or code comments to remove generic filler while preserving usability and meaning.
---

# Product quality

1. Start from the user's task, existing frontend conventions and relevant Notion design. Preserve established visual decisions unless the requested change requires revisiting them.
2. Design around the user's next decision: input a problem, compare choices, confirm a decision, understand a result. Use specific action labels such as “선택 확정” or “설계 요약 다운로드”.
3. Give color, spacing, cards and motion a functional reason. Do not add template sections, decorative dashboards or a theme toggle just to satisfy a generic style recipe. Consistent decision cards are appropriate for comparing equivalent choices.
4. Show actual product state. Label mock recommendations and synthetic examples; never present the initial target of 20 users as achieved usage or concurrency.
5. Implement empty, loading, failure and retry states for changed flows. Keep user decisions recoverable and make the next action understandable to beginners.
6. Check changed controls for real behavior, semantic labels, keyboard operation and visible focus. Check relevant mobile widths, text overflow and shipped themes. Measure contrast when changing colors; do not claim an accessibility audit from visual inspection alone.
7. Keep product text concrete. Remove inflated claims and repeated explanations, but retain uncertainty, source links and decision consequences.
8. In comments, explain non-obvious constraints and reasons. Preserve protocol, security, concurrency, workaround and license information. A comment cleanup request does not authorize logic changes.
9. Review the changed UI in a browser when available. Record what was exercised; if unavailable, distinguish source inspection from interaction testing.

Apply these checks while implementing authorized changes. For review-only requests, return findings without editing. Do not require a new mode-selection question each session.

Background: [source notes](../SOURCES.md).
