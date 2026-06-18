#!/bin/bash
# UX journey runner — Smart Relief Allocator
echo "[UX] Running Playwright journeys..."
npx playwright test tests/ux/ --reporter=list
