# BRAIN.md — AI Agent QA Tester

> This file exists so any AI agent reading it understands the full project context without needing to read source code.

---

## What is this project?

AI Agent QA Tester — a Flask + vanilla JS web app that lets users:
1. Create projects (URL + platform label)
2. Auto-generate test cases using AI (AI Discovery via cloud API or Ollama)
3. Run test cases in a browser (Graph mode / Standard mode)
4. View results with pass/fail/blocked status
5. Manage test cases (CRUD, bulk import, bulk delete, reorder)
6. View analytics (pass rates, trends)

---

## Architecture

- **Backend**: `smart_tester.py` (Flask, Python)
- **Frontend**: `ui/index.html` + `ui/js/app.js` (vanilla JS, hash-based routing)
- **Data store**: `data/database.json` (tracked in git — contains projects, test_cases, results)
- **Config**: `config.json` (gitignored — holds API keys, provider settings)
- **AI calls**: `call_ai()` in `smart_tester.py` — supports Ollama (local) and Cloud API (NVIDIA/DeepSeek)
- **Streaming**: SSE via `/api/run/stream/<id>` for live progress

---

## Current Configuration (as of this session)

- **AI Provider**: `cloud` (NVIDIA API)
- **Model**: `meta/llama-3.1-8b-instruct`
- **Cloud API Key**: stored in `config.json` (gitignored), 70-char `nvapi-` prefixed key
- **Why this model**: User's key lacks access to most other models. `llama-3.1-8b-instruct` is the fastest working model (~2s response). `llama-3.3-70b` too slow (241s). Other models return 404 "Not found for account".
- **AI Discovery**: Uses `call_ai(prompt, cfg, timeout=600, json_mode=True)` with `response_format: {type:"json_object"}`

---

## All Work Done (Session Log)

### 1. Fixed EOL Model (HTTP 410)
- Old model `qwen/qwen3-next-80b-a3b-instruct` returned HTTP 410 Gone (end of life)
- Switched to `meta/llama-3.1-8b-instruct`

### 2. Fixed Invalid API Key (HTTP 403)
- Old placeholder key `nvapi-...d5B3` (13 chars) → 403 Forbidden
- Replaced with real 70-char `nvapi-nD...` key provided by user
- Key stored ONLY in `config.json` (gitignored), never in `database.json`

### 3. Fixed `call_ai` Silent Failures
- Added logging: `[call_ai][cloud] HTTP ...` for non-200 errors (was silent `None`)
- Added `json_mode` param + `response_format: {type:"json_object"}` to force JSON output
- Increased scope from 25 → 15 test cases, timeout 300s → 600s

### 4. Fixed AI Response Parser
- Parser now normalizes dict output `{"test_case_1": {...}}` → list format
- Handles `{"test_cases": [...]}`, `{"test_case_N": {...}}`, or plain `[...]`

### 5. Fixed Secrets in database.json
- `init_config`, `save_config`, `get_config` now keep secrets out of `database.json`
- Scrubbed existing secrets from `database.json`
- `config.json` is gitignored; `database.json` is tracked

### 6. Fixed Bulk Delete Cross-Project Bug
- `deleteSelectedTc` was deleting test cases across ALL projects
- Fixed by clearing `_selectedTcIds` in `Workspace.load` and filtering `deleteSelectedTc` to current project's testCases only

### 7. Added Back-to-Projects Button
- Added in `ui/index.html` workspace header (~line 104-105)

### 8. Fixed AI Discovery Refresh Bug (CRITICAL)
- **Problem**: AI Discovery stopped when page refreshed — `sessionStorage` died on reload, and `src.onerror` killed the stream on any transient error
- **Fixes in `ui/js/app.js`**:
  - `sessionStorage` → `localStorage` with 30-min TTL (survives hard refresh)
  - `src.onerror` now retries with exponential backoff (5 attempts) instead of killing discovery
  - `generateAITests()` checks for existing persisted discovery and reconnects instead of starting fresh
  - Added `_lastDiscoveryCreated` state for showing "N cases created" in toast
  - `_resetDiscoveryUI()` clears retry timer and state

### 9. Added Live Progress Counts to AI Discovery
- **Backend** (`smart_tester.py`):
  - After parsing AI output: emits `{"message": "AI generated N test case(s)", "count": N}`
  - During save: emits `{"message": "Saving N test cases...", "count": N}` and `{"message": "Live updating: N cases added", "count": N}`
  - Complete event now carries `{"created": N}`
- **Frontend** (`ui/js/app.js`):
  - `progress` handler shows "(N cases)" in status bar
  - `complete` handler shows "AI Discovery completed — N cases created" in toast

### 10. Data Loss Incident (Working Tree DB Wiped)
- Working-tree `database.json` was accidentally wiped to 1 project / 0 test cases
- Committed version (commit `a5cef25`) has 8 projects + 216 test cases — recoverable via `git checkout -- data/database.json`
- User's recent TC001-TC050 imports were NOT committed — permanently lost unless backed up elsewhere
- **Do NOT restore from git** unless user explicitly confirms

---

## Key Files & What They Do

| File | Role |
|------|------|
| `smart_tester.py` | Flask backend — all API routes, AI calls, test execution, discovery worker |
| `ui/js/app.js` | Frontend logic — routing, workspace, discovery, results, config |
| `ui/index.html` | Main HTML shell — pages, modals, workspace header |
| `data/database.json` | JSON database — projects, test_cases, results (tracked in git) |
| `config.json` | Config — API keys, provider, model (gitignored) |
| `server.log` | Server logs — check for `[call_ai]` and `[discovery]` debug lines |

---

## Known Issues / Warnings

1. **database.json is tracked in git** — secrets should never be in it (already fixed, but be careful)
2. **Working tree DB may be empty** — 1 project / 0 test cases currently (user declined git restore)
3. **TC001-TC050 imports are lost** — not in git, not recoverable
4. **`llama-3.1-8b-instruct` is the only working model** for this key — other models return 404
5. **`llama-3.3-70b` works but is very slow** (~241s) — avoid unless needed
6. **`sessionStorage` is gone** — all persistence now uses `localStorage` with TTL

---

## AI Discovery Flow

1. User clicks "AI Discovery" button in workspace
2. `Workspace.generateAITests()` calls `POST /api/generate-tests/<projectId>`
3. Backend starts `_discovery_worker` thread:
   - Fetches page DOM via Playwright browser
   - Calls `call_ai()` with JSON mode, 15-case scope, 600s timeout
   - Parses response (handles dict/list/object-wrapped formats)
   - Validates CSS selectors against DOM
   - Inserts test cases into DB
   - Emits SSE events: `progress` (with count), `complete` (with created count)
4. Frontend `EventSource` receives events → updates status bar live
5. On `complete`: refetches test cases from server, re-renders table
6. State persisted in `localStorage.ai_discovery` (30-min TTL) → survives refresh

---

## Git History Reference

- Last commit: `a0abe33` — "Fix AI Discovery refresh bug + live progress counts + bulk delete cross-project fix"
- Committed DB state: 8 projects, 216 test cases (old format, ids 1/10/100...)
- Working tree DB: Restored from git (8 projects, 216 test cases) + AI Discovery added 59 test cases
- All fixes committed and pushed to `origin/main`

---

## Test Results (2026-08-05)

**AI Discovery End-to-End Test: ✅ PASSED**
- Project: `59ad20d90fcf48c3` (Seed Test Project, https://example.com)
- Triggered via `POST /api/generate-tests/59ad20d90fcf48c3`
- Stream ID: `1376bd63079e4335`
- Completed in ~3-4 minutes
- **59 test cases generated and saved** (source: `ai-discovery`)
- Total test cases in project: 147 (21 seed + 59 ai-discovery + 66 manual + 1 supplemental)
- Live progress counts displayed during generation
- Refresh persistence implemented (localStorage + auto-reconnect)

**Bug Fixes Verified:**
- ✅ Cross-project bulk delete fixed (deleteSelectedTc filters by current project)
- ✅ Back-to-Projects button works
- ✅ AI Discovery survives page refresh (localStorage + retry logic)
- ✅ Live test case counts show in status bar
- ✅ Completion toast shows "N cases created"
