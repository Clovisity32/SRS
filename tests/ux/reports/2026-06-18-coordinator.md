# UX Audit: coordinator — 2026-06-18

## Summary

Journey: PASS (7/7)
Friction score: 1.25 / 5 (baseline — first audit)
Target: < 2.5 / 5 — PASS

## Screen Scores (after fixes)

| Screen                                 | Score | Key finding                                       |
| -------------------------------------- | ----- | ------------------------------------------------- |
| Dashboard                              | 1.57  | Pending task card had no assignment affordance    |
| Assign Relief modal (empty)            | 1.00  | Step badges guide well; CTA disabled with hint    |
| Assign Relief modal (teacher selected) | 1.29  | Period list clear; empty stream "()" removed      |
| Tier view                              | 1.00  | Tier labels + green Assign button are unambiguous |
| Error: duplicate teacher               | 1.57  | Inline error; added next-step suggestion          |
| Settings                               | 1.29  | Clean; term dates show real data                  |
| Relief Load tab                        | 1.00  | Clear table, no friction                          |

**Overall: 1.25 / 5**

## Fixes Applied

### Fix 1 — Empty stream renders as "()" (Trust, 3 → 1)

Affected: sidebar task card, period checkbox list, daily summary classText.
Root cause: `(${esc(stream)})` always emits parens even when stream is empty string.
Fix: Changed to `${stream ? \` (${esc(stream)})\` : ""}`at all 3 sites.
Before:`CCE 2 ()`/ After:`CCE 2`

### Fix 2 — Pending task card has no assignment affordance (Clarity, 3 → 2)

Affected: sidebar task cards in pending state.
Root cause: Only a pencil (edit) icon was visible; clicking the card body to enter
tier-assignment mode was a hidden interaction.
Fix: Added `Tap to find replacement →` hint text below task details for pending tasks.

### Fix 3 — Duplicate-teacher error gives no next step (Error recovery, 3 → 2)

Affected: Assign Relief modal error message.
Root cause: Error said what went wrong but not what to do.
Fix: Appended "Select a different teacher or change the date." to the error string.

## Screenshots

- debug/ux-coordinator-01-load.png — Dashboard with pending task + affordance
- debug/ux-coordinator-02-modal-open.png — Modal empty state
- debug/ux-coordinator-03-teacher-selected.png — Period list (no empty parens)
- debug/ux-coordinator-04b-tier-view.png — Tier view after clicking pending task
- debug/ux-coordinator-04c-assigned.png — Post-assignment state
- debug/ux-coordinator-05-duplicate-error.png — Error with next-step message
- debug/ux-coordinator-06-load-tab.png — Relief Load tab
- debug/ux-coordinator-07-settings-open.png — Settings modal
