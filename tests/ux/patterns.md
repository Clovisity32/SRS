# UX Fix Patterns

> Reusable solutions discovered during audits.
> Added automatically when /ux-audit resolves a chronic issue.

| Date       | Pattern                                                                                                                      | Roles Affected | Fix Applied                                                                            |
| ---------- | ---------------------------------------------------------------------------------------------------------------------------- | -------------- | -------------------------------------------------------------------------------------- |
| 2026-06-18 | Suppress empty-field parens — use `${val ? \` (${esc(val)})\` : ""}` not `(${esc(val)})` when field may be empty             | coordinator    | Empty stream "()" removed from task cards, period list, daily summary                  |
| 2026-06-18 | Hidden-tap affordance — add faint "Tap to find replacement →" hint on clickable cards that trigger a non-obvious mode change | coordinator    | Pending task card in sidebar now signals its primary action                            |
| 2026-06-18 | Error next-step — append what to do next to every inline validation error, not just what went wrong                          | coordinator    | Duplicate-teacher error now ends with "Select a different teacher or change the date." |
