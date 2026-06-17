# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

No build step. Open `index.html` directly in a browser, or serve it with any static file server:

```
npx serve .
# or
python -m http.server 8080
```

All dependencies (Tailwind CSS, Day.js, Firebase) are loaded via CDN at runtime.

## Architecture

**Everything lives in one file: `index.html`.** There is no framework, no bundler, no npm, and no tests.

The script tag at the bottom is `type="module"` and uses Firebase ES module imports from `gstatic.com`. The entire application logic is inside `runApp(db)`, which is called after Firebase auth resolves.

### State

Three mutable objects hold all app state:

| Variable            | What it contains                                                                                   |
| ------------------- | -------------------------------------------------------------------------------------------------- |
| `masterTeachers`    | Array of teacher objects with `id`, `name`, `department`, `subjects[]`, and `blockedSlotsByDate{}` |
| `fullTimetable`     | `{ [teacherId]: { Odd/Even: { monday/tuesday/…: [ {period, level, subject, stream} ] } } }`        |
| `reliefTasksByDate` | `{ [YYYY-MM-DD]: [ reliefTask ] }` — the core operational data                                     |

A relief task object shape:

```js
{
  id: string,
  date: 'YYYY-MM-DD',
  periods: [ { id, time } ],          // from the PERIODS constant
  details: { subject, level, stream }, // the class being covered
  originalTeacher: { id, name, department },
  status: 'pending' | 'assigned',
  assignedTeacher?: { id, name }       // only present when assigned
}
```

All state is persisted to a single Firestore document: `app_data/main`. Every mutation ends with `saveStateToFirestore()`.

### Data flow

1. Firebase auth (anonymous) resolves → `setupApp(db)` called
2. `onSnapshot` on `app_data/main` fires → calls `loadStateFromFirestore()` or `initializeAppStateAndSave()` (first run with mock data)
3. Any user action mutates the three state objects → `saveStateToFirestore()` → Firestore `onSnapshot` fires again → `loadStateFromFirestore()` re-renders the UI

### Week type (Odd/Even)

`getWeekType(date)` determines whether a date falls on an Odd or Even week by finding the closest term start date and computing `(weekNumber - startWeekNumber) % 2`. Term start dates default to 2025 values and are configurable in Settings. All timetable lookups require both a week type and a day-of-week string (lowercase full name, e.g. `'monday'`).

### Teacher ranking

`findAndRankTeachers(reliefContext)` returns candidates in four tiers:

- **G1** — teaches exact same level + subject + stream anywhere in their full timetable
- **G2** — has the subject in their `subjects[]` array
- **G3** — any other available teacher with a free slot
- **G4** — unavailable (day off) or teaching during the relief period

Within tiers, candidates are sorted by daily load then weekly relief load (ascending).

### CSV import format

Headers follow the pattern `Odd Mon P1`, `Odd Mon P2`, … `Even Fri P16` (160 period columns after the `Teacher` column). Cell values are parsed by `parseClassDetails()` which extracts level (`Sec N`), subject, and stream from strings like `"3 Math E1"`. Download the template via the Settings modal to see the exact format.

## Firebase

- Project: `smart-relief-system`
- Auth: anonymous sign-in only — no user accounts
- Database: Firestore, single document `app_data/main`
- Security rules: `firestore.rules` in repo root — deploy with `firebase deploy --only firestore:rules`
  - Auth gate: `request.auth != null` (anonymous sign-in passes; bare REST calls without SDK are blocked)
  - Path allowlist: only `app_data/main` accessible; wildcard deny covers everything else
  - Write validation: 5 required top-level keys, type checks on `masterTeachers` (list), `messageTemplate` (string), `termStartDates` (map with term1–4)

## CSP Notes

- `<meta http-equiv="Content-Security-Policy">` is in `index.html` immediately after `<meta viewport>`
- `'unsafe-inline'` is required — the entire app is an inline `<script type="module">`
- `'unsafe-eval'` is required — Tailwind Play CDN uses `eval()` for JIT CSS generation
- `frame-ancestors` is not supported in `<meta>` CSP — only works via HTTP response header
- To remove both `unsafe-*` directives: replace Tailwind Play CDN with a static Tailwind CLI build and move the app script to an external `.js` file

## Security Rules

- All Firestore-sourced values injected into `innerHTML` **must** be wrapped with `esc()` — defined inside `runApp()` near `draftMessageMap`. Never interpolate `teacher.name`, `slot.subject`, `slot.level`, or `slot.stream` directly into template literals used with `innerHTML`.
- Per-button data is stored in `draftMessageMap` (a `Map` keyed by `task.id`). Do not put serialised JSON in HTML attributes — read from the Map in click handlers via `e.target.dataset.msgKey`.

## UI Conventions

- Multi-step modals use `.step-badge` CSS class (blue circle `1`, `2`, `3`) defined in `<style>` around line 119. Apply it to any new modal with a sequential user flow.
- Message notification template lives in `messageTemplate` (module-scoped in `runApp()`), persisted to Firestore as `data.messageTemplate`. It is editable via Settings (`#messageTemplateInput`). Any new notification flow should read from this variable and use `.replace(/\{varName\}/g, value)` substitution.

## Changelog

| Date    | What Changed                                                                                                                |
| ------- | --------------------------------------------------------------------------------------------------------------------------- |
| 2026-06 | Mobile UX: step badges in Assign Relief modal, flex-col-reverse button layout, tab scroll shadow, hint text on disabled CTA |
| 2026-06 | Message template customisation added to Settings modal; persisted to Firestore                                              |
| 2026-06 | XSS hardening: `esc()` helper, Map-based data attributes, DOM API teacher dropdown, 8 innerHTML call sites wrapped          |
| 2026-06 | SRI integrity hashes on DayJS ×4 and PDF.js CDN scripts; 15 MB upload size guard added                                      |
| 2026-06 | Firestore security rules added (`firestore.rules` + `firebase.json`): auth gate, path allowlist, write shape validation     |
| 2026-06 | CSP `<meta>` tag added to `index.html`; `unsafe-inline`/`unsafe-eval` documented as Tailwind Play CDN constraints           |
