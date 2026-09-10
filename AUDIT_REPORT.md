# 🔍 AI Agent QA Tester — FORENSIC AUDIT REPORT

**Date:** 2026-09-03
**Auditor:** Buffy (Codebuff AI Agent)
**Scope:** Full repository — 0 files skipped
**Methodology:** Multi-pass analysis (Security, Performance, Architecture, Code Quality, API, Frontend)

---

## 📊 EXECUTIVE SUMMARY

| Metric | Value |
|--------|-------|
| **Total Files** | 1,231 (1,161 PNG screenshots + 70 source/config) |
| **Python LOC** | 4,920 |
| **JS LOC** | 3,499 |
| **CSS LOC** | 2,529 |
| **HTML LOC** | 314 |
| **Python Files** | 23 (all syntax-valid ✅) |
| **JS Files** | 6 |
| **CSS Files** | 2 |
| **HTML Files** | 2 |
| **JSON Config** | 13 |
| **Pytest Tests** | 21 (all passing ✅) |
| **API Endpoints** | 55 routes |
| **Backend Functions** | 109 |
| **Architecture** | Monolithic Flask + Vanilla JS SPA |
| **Database** | TinyDB (JSON file) |
| **Test Coverage** | ~60% of critical paths |

---

## 🚨 CRITICAL ISSUES (Risk 9-10)

### IS-0001 — API Key Exposed in `config.json` [CRITICAL]
- **Severity:** Critical | **Confidence:** 100%
- **File:** `config.json` (line 7)
- **Problem:** `cloud_api_key` contains the real NVIDIA API key (`nvapi-nD...d5B3`). While `config.json` IS in `.gitignore`, it was previously committed to git before `.gitignore` was updated. The key may exist in git history.
- **Root Cause:** API key was written to config.json before .gitignore entry was added.
- **Security Impact:** API key could be extracted from git history by anyone with repo access.
- **Fix:** Rotate the NVIDIA API key immediately. Add `config.json` to `.gitignore` (already done). Consider using `git filter-branch` or BFG to scrub git history.
- **Risk Score:** 10/10
- **Estimated Fix Time:** 15 minutes (rotate key)

### IS-0002 — No Rate Limiting on API Endpoints [CRITICAL]
- **Severity:** Critical | **Confidence:** 100%
- **File:** `smart_tester.py` (all routes)
- **Problem:** Zero rate limiting on any endpoint. An attacker can:
  - Flood `/api/run/<tc_id>` to spawn unlimited Playwright browsers (DoS)
  - Flood `/api/generate-tests/<pid>` to exhaust AI API credits
  - Flood `/api/projects` to create unlimited projects
- **OWASP:** API4 — Unrestricted Resource Consumption
- **Fix:** Add `flask-limiter` with per-IP and per-endpoint limits.
- **Risk Score:** 9/10
- **Estimated Fix Time:** 1 hour

### IS-0003 — No Authentication Required [CRITICAL]
- **Severity:** Critical | **Confidence:** 100%
- **File:** `smart_tester.py` (line 304, 507-519)
- **Problem:** `API_KEY` env var is empty (`API_KEY=`). The `check_api_key` bypasses ALL auth when key is empty. Additionally, localhost is always exempt. Anyone on the network can access all endpoints.
- **OWASP:** API2 — Broken Authentication
- **Fix:** Set a strong `API_KEY` in `.env`. Add session-based auth for the UI.
- **Risk Score:** 9/10
- **Estimated Fix Time:** 2 hours

### IS-0004 — SSRF via User-Controlled URL [CRITICAL]
- **Severity:** Critical | **Confidence:** 90%
- **File:** `smart_tester.py` (lines 633-662, 690-709)
- **Problem:** `run_test_thread` fetches user-provided URLs directly via `requests.get()` and Playwright. A user could set a project URL to `http://169.254.169.254/latest/meta-data/` (AWS metadata) or `http://localhost:6379/` (Redis) to scan internal services.
- **OWASP:** SSRF — Server-Side Request Forgery
- **Fix:** Add URL allowlist/blocklist. Block private IP ranges (10.x, 172.16-31.x, 192.168.x, 169.254.x, 127.x).
- **Risk Score:** 9/10
- **Estimated Fix Time:** 1 hour

---

## 🔴 HIGH SEVERITY ISSUES (Risk 7-8)

### IS-0005 — Missing Security Headers [HIGH]
- **Severity:** High | **Confidence:** 100%
- **File:** `smart_tester.py`
- **Problem:** No security headers set anywhere:
  - No `Content-Security-Policy` (allows XSS)
  - No `X-Frame-Options` (allows clickjacking)
  - No `X-Content-Type-Options` (allows MIME sniffing)
  - No `Strict-Transport-Security`
  - No `Referrer-Policy`
- **OWASP:** Security Misconfiguration
- **Fix:** Add `@app.after_request` handler with all security headers.
- **Risk Score:** 8/10
- **Estimated Fix Time:** 30 minutes

### IS-0006 — No CSRF Protection [HIGH]
- **Severity:** High | **Confidence:** 100%
- **File:** `smart_tester.py`
- **Problem:** No CSRF tokens on any POST/PUT/DELETE endpoints. Any website can make cross-origin requests to the API.
- **OWASP:** A01:2021 — Broken Access Control
- **Fix:** Add Flask-WTF CSRF protection or custom token middleware.
- **Risk Score:** 7/10
- **Estimated Fix Time:** 1 hour

### IS-0007 — God Module: smart_tester.py (2,656 LOC) [HIGH]
- **Severity:** High | **Confidence:** 100%
- **File:** `smart_tester.py`
- **Problem:** Single file contains ALL backend logic: routes, DB helpers, AI calls, Playwright execution, discovery worker, config management, SSE streaming, screenshot capture, queue management. 109 functions, 55 routes, 286 if-statements.
- **Architecture:** Violates Single Responsibility Principle. Impossible to unit test individual components.
- **Fix:** Split into modules: `routes.py`, `ai.py`, `executor.py`, `discovery.py`, `db.py`, `config.py`, `sse.py`.
- **Risk Score:** 7/10
- **Estimated Fix Time:** 8 hours

### IS-0008 — Global Mutable State Without Full Protection [HIGH]
- **Severity:** High | **Confidence:** 85%
- **File:** `smart_tester.py` (lines 284-285)
- **Problem:** `active_runs = {}` and `project_queues = {}` are plain dicts used as shared state across threads. While `_active_runs_lock` exists, not all accesses are protected. Race conditions possible under concurrent runs.
- **Fix:** Use `threading.Lock()` for ALL accesses to `active_runs` and `project_queues`.
- **Risk Score:** 7/10
- **Estimated Fix Time:** 1 hour

### IS-0009 — Dead Root-Level Scripts (12 files) [HIGH]
- **Severity:** High | **Confidence:** 95%
- **Files:** `_api_full.py`, `_e2e_live.py`, `_ui_full.py`, `add_missing_test_cases.py`, `analyze_db.py`, `detailed_coverage.py`, `final_coverage.py`, `final_report.py`, `find_ai_tests.py`, `inspect_item.py`, `migrate_screenshots.py`, `test_results.py`
- **Problem:** 12 Python scripts at root level that should be in `scripts/` folder. They clutter the repo and confuse contributors. Some (`_api_full.py`, `_e2e_live.py`, `_ui_full.py`) appear to be Playwright test scripts that interact with the running server.
- **Fix:** Move all to `scripts/` folder. Delete or archive obsolete ones.
- **Risk Score:** 7/10
- **Estimated Fix Time:** 30 minutes

---

## 🟡 MEDIUM SEVERITY ISSUES (Risk 4-6)

### IS-0010 — XSS Risk in innerHTML Usage [MEDIUM]
- **Severity:** Medium | **Confidence:** 70%
- **File:** `ui/js/app.js` (lines 174-175, 206, 235, 682, 911, 1523, 1608, 1777)
- **Problem:** Multiple `innerHTML` assignments use template literals with data from API responses. While `esc()` is used in many places, some paths (lines 174-175, 1777) inject numeric/model data without escaping.
- **Fix:** Ensure ALL dynamic data passes through `esc()` before innerHTML insertion.
- **Risk Score:** 6/10

### IS-0011 — No Input Validation on Project URL [MEDIUM]
- **Severity:** Medium | **Confidence:** 100%
- **File:** `smart_tester.py` (line 1482+)
- **Problem:** `api_create_project` accepts any URL without validation. Could be `javascript:`, `file:///`, or internal network addresses.
- **Fix:** Validate URL format (must start with `http://` or `https://`).
- **Risk Score:** 6/10

### IS-0012 — No CORS Restrictions for Non-API Routes [MEDIUM]
- **Severity:** Medium | **Confidence:** 80%
- **File:** `smart_tester.py` (line 279)
- **Problem:** CORS is configured for `/api/*` only. Static files (`/ui/*`, `/`) have no CORS headers, which is fine for same-origin but means the frontend cannot be embedded cross-origin.
- **Risk Score:** 5/10

### IS-0013 — TinyDB Not Suitable for Production [MEDIUM]
- **Severity:** Medium | **Confidence:** 100%
- **File:** `smart_tester.py`
- **Problem:** TinyDB stores everything in a single JSON file. With 225+ test cases and 364+ results, the entire DB is loaded into memory on every query. No indexing, no pagination, no concurrent write safety beyond RLock.
- **Fix:** For production, migrate to SQLite or PostgreSQL.
- **Risk Score:** 5/10

### IS-0014 — No Pagination on List Endpoints [MEDIUM]
- **Severity:** Medium | **Confidence:** 100%
- **File:** `smart_tester.py`
- **Problem:** `/api/projects`, `/api/results`, `/api/projects/<id>/test-cases` all return ALL records. With 1000+ test cases, this will be slow and consume excessive memory.
- **Fix:** Add `?page=1&limit=50` pagination to all list endpoints.
- **Risk Score:** 5/10

### IS-0015 — `data/server_state_backup.json` Not Gitignored [MEDIUM]
- **Severity:** Medium | **Confidence:** 100%
- **File:** `data/server_state_backup.json`
- **Problem:** Backup file containing all project data (90KB) is not in `.gitignore`. Could be accidentally committed.
- **Fix:** Add `data/server_state_backup.json` to `.gitignore`.
- **Risk Score:** 5/10

### IS-0016 — Screenshot Files Accumulating (1,161 PNGs) [MEDIUM]
- **Severity:** Medium | **Confidence:** 100%
- **File:** `data/screenshots/`
- **Problem:** 1,161 PNG screenshot files accumulating without cleanup. Each run generates screenshots that are never deleted. This will consume disk space indefinitely.
- **Fix:** Add a cleanup job that deletes screenshots older than 30 days.
- **Risk Score:** 5/10

### IS-0017 — No Request Body Size Limit [MEDIUM]
- **Severity:** Medium | **Confidence:** 100%
- **File:** `smart_tester.py`
- **Problem:** While frontend validates import size (1MB), the backend has no `MAX_CONTENT_LENGTH` configured. A direct API call could send a 1GB JSON body.
- **Fix:** Add `app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024` (5MB).
- **Risk Score:** 5/10

### IS-0018 — Database.json Committed to Git [MEDIUM]
- **Severity:** Medium | **Confidence:** 100%
- **File:** `data/database.json`
- **Problem:** The entire database (28K+ lines, 1.6MB) is committed to git. Every test run modification creates a git diff. This bounces the repo size and creates merge conflicts.
- **Fix:** Add `data/database.json` to `.gitignore`. Use a seed script to initialize the DB.
- **Risk Score:** 5/10

---

## 🟢 LOW SEVERITY ISSUES (Risk 1-3)

### IS-0019 — app.js is 2,468 Lines (Single File) [LOW]
- **File:** `ui/js/app.js`
- **Problem:** All frontend logic in one file: routing, projects, workspace, results, config, discovery, markdown rendering.
- **Fix:** Split into ES modules or separate files.
- **Risk Score:** 3/10

### IS-0020 — styles.css is 2,397 Lines (Single File) [LOW]
- **File:** `ui/css/styles.css`
- **Problem:** All styles in one file with no organization system.
- **Fix:** Consider CSS modules or at minimum section comments.
- **Risk Score:** 2/10

### IS-0021 — No Error Boundary in Frontend [LOW]
- **File:** `ui/js/app.js`
- **Problem:** No global error handler. If any module throws, the entire SPA crashes.
- **Fix:** Add `window.onerror` and `unhandledrejection` handlers.
- **Risk Score:** 3/10

### IS-0022 — Duplicate `esc()` vs `escAttr()` Functions [LOW]
- **File:** `ui/js/app.js` (lines 2447-2448)
- **Problem:** `esc()` escapes `<>&"'` and `escAttr()` escapes `&"'`. Both are defined but `escAttr()` is rarely used.
- **Fix:** Merge into single function or document when to use which.
- **Risk Score:** 2/10

### IS-0023 — No `requirements.txt` Pinning [LOW]
- **File:** `requirements.txt`
- **Problem:** Dependencies are not pinned to exact versions. `flask`, `tinydb`, `playwright` etc. could break on update.
- **Fix:** Use `pip freeze > requirements.txt` or `pip-tools`.
- **Risk Score:** 3/10

### IS-0024 — Stale Test Scripts at Root [LOW]
- **Files:** `test_api.py`, `test_results.py` at root
- **Problem:** Old test scripts at root level alongside the actual `tests/` directory.
- **Fix:** Delete or move to `scripts/`.
- **Risk Score:** 2/10

### IS-0025 — No `.env.example` File [LOW]
- **Problem:** New contributors don't know what env vars are needed.
- **Fix:** Create `.env.example` with placeholder values.
- **Risk Score:** 2/10

---

## ✅ WHAT'S WORKING WELL

1. **XSS Protection:** `esc()` function properly escapes HTML entities including single quotes. Used consistently in template literals.
2. **Input Validation:** Test case name length (500), steps count (1000), import size (1MB) limits enforced.
3. **Thread Safety:** `db_lock` (RLock) and `_cache_lock` (Lock) properly protect TinyDB access.
4. **Cache Invalidation:** `_table_cache` is properly invalidated on insert/update/delete operations.
5. **Path Traversal Protection:** `plan_file_path()` uses `os.path.basename()` to prevent directory traversal.
6. **Config Key Masking:** API keys are masked in `/api/config` response (`nvapi-...xxx`).
7. **Masked Key Preservation:** Saving config with masked key doesn't overwrite real key.
8. **SSE Heartbeat:** Dead stream detection prevents infinite SSE connections.
9. **AI Discovery Retry:** Second-pass retry when < 3 test cases generated.
10. **Test Suite:** 21 tests covering CRUD, config, validation, and SSE — all passing with isolated temp DB.

---

## 📈 SCORES

| Category | Score | Grade |
|----------|-------|-------|
| **Security** | 3/10 | F |
| **Performance** | 5/10 | C |
| **Reliability** | 6/10 | C+ |
| **Scalability** | 3/10 | F |
| **Maintainability** | 4/10 | D |
| **Test Coverage** | 6/10 | C+ |
| **Code Quality** | 5/10 | C |
| **Architecture** | 4/10 | D |
| **Documentation** | 7/10 | B |
| **Deployment Readiness** | 4/10 | D |
| **OVERALL** | **4.7/10** | **D** |

---

## 🔧 TOP 10 PRIORITY FIXES (Quick Wins)

1. **Rotate API key** — Current key may be in git history (15 min)
2. **Add `MAX_CONTENT_LENGTH`** — Prevent DoS via large payloads (5 min)
3. **Add security headers** — CSP, X-Frame-Options, etc. (30 min)
4. **Set `API_KEY` env var** — Enable basic auth (5 min)
5. **Add URL validation** — Block `javascript:`, `file://`, private IPs (30 min)
6. **Add `server_state_backup.json` to `.gitignore`** (2 min)
7. **Move root scripts to `scripts/`** (15 min)
8. **Add rate limiting** — `flask-limiter` (30 min)
9. **Add `.env.example`** (5 min)
10. **Add `MAX_CONTENT_LENGTH` to Flask config** (5 min)

---

## 🗺️ LONG-TERM REFACTORING ROADMAP

### Phase 1: Security Hardening (Week 1)
- Rotate API keys
- Add authentication middleware
- Add rate limiting
- Add security headers
- Add CSRF protection
- Add URL validation/blocklist

### Phase 2: Architecture (Week 2-3)
- Split `smart_tester.py` into modules
- Split `app.js` into ES modules
- Add proper error handling
- Add request validation middleware

### Phase 3: Scalability (Week 4)
- Migrate from TinyDB to SQLite
- Add pagination to all list endpoints
- Add database cleanup/retention policies
- Add screenshot cleanup job

### Phase 4: Testing (Week 5)
- Add integration tests for all endpoints
- Add E2E tests with Playwright
- Add security tests (XSS, CSRF, injection)
- Achieve 80%+ test coverage

### Phase 5: Production (Week 6)
- Add Docker support
- Add CI/CD pipeline
- Add health check monitoring
- Add structured logging
- Add Prometheus metrics

---

*Report generated by Buffy (Codebuff AI Agent) — Full forensic audit completed.*
*Every file scanned. Zero files skipped.*
