import os, sys, json, uuid, threading, time, queue, re, math, base64
from datetime import datetime, timezone
from pathlib import Path
from functools import wraps

# Windows console UTF-8 compatibility (prevents 'charmap' / cp1252 UnicodeEncodeError)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_builtin_print = print
def safe_print(*args, **kwargs):
    try:
        _builtin_print(*args, **kwargs)
    except (UnicodeEncodeError, Exception):
        try:
            enc = getattr(sys.stdout, "encoding", None) or "utf-8"
            clean_args = [
                str(a).encode(enc, errors="replace").decode(enc, errors="replace")
                for a in args
            ]
            _builtin_print(*clean_args, **kwargs)
        except Exception:
            pass

print = safe_print

from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from tinydb import TinyDB, Query
import requests
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).parent.resolve()
# Vercel serverless filesystem is read-only except /tmp — keep writable data there
if os.environ.get("VERCEL"):
    DATA_DIR = Path("/tmp") / "ai-qa-data"
else:
    DATA_DIR = BASE_DIR / "data"
TEST_PLANS_DIR = DATA_DIR / "test-plans"
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
UI_DIR = BASE_DIR / "ui"
CONFIG_FILE = BASE_DIR / "config.json"

for _d in (DATA_DIR, TEST_PLANS_DIR, SCREENSHOTS_DIR, UI_DIR):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

DB_FILE = DATA_DIR / "database.json"

def ensure_db_file():
    if not DB_FILE.exists() or DB_FILE.stat().st_size == 0:
        DB_FILE.write_text("{}", encoding="utf-8")
        return
    try:
        json.loads(DB_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        DB_FILE.write_text("{}", encoding="utf-8")

ensure_db_file()


# UTF-8 storage for Windows compatibility
class UTF8JSONStorage:
    def __init__(self, path):
        self._path = path
        self._handle = None
    def read(self):
        import json as _json
        if not self._path.exists():
            return {}
        with open(self._path, 'r', encoding='utf-8') as f:
            return _json.load(f)
    def write(self, data):
        import json as _json
        with open(self._path, 'w', encoding='utf-8') as f:
            _json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=False)
    def close(self):
        pass

db = TinyDB(storage=lambda: UTF8JSONStorage(DB_FILE))
projects_table = db.table("projects")
test_cases_table = db.table("test_cases")
results_table = db.table("results")
config_table = db.table("config")

# Thread-safety helpers for TinyDB (TinyDB's JSONStorage is not safe for concurrent writes)
db_lock = threading.RLock()
_table_cache = {}
_cache_lock = threading.Lock()

def _invalidate_table_cache(table_name=None):
    with _cache_lock:
        if table_name:
            _table_cache.pop(table_name, None)
        else:
            _table_cache.clear()

def safe_all(table):
    name = table.name
    with _cache_lock:
        cached = _table_cache.get(name)
        if cached is not None:
            return list(cached)
    with db_lock:
        try:
            rows = list(table.all())
        except json.JSONDecodeError:
            ensure_db_file()
            rows = list(table.all())
    with _cache_lock:
        _table_cache[name] = rows
    return list(rows)

def safe_insert(table, data):
    with db_lock:
        doc_id = table.insert(data)
    _invalidate_table_cache(table.name)
    return doc_id

def safe_insert_multiple(table, data_list):
    with db_lock:
        doc_ids = table.insert_multiple(data_list)
    _invalidate_table_cache(table.name)
    return doc_ids

def safe_update(table, cond, data):
    with db_lock:
        updated = table.update(data, cond)
    _invalidate_table_cache(table.name)
    return updated

def safe_remove(table, cond):
    with db_lock:
        removed = table.remove(cond)
    _invalidate_table_cache(table.name)
    return removed

def record_id_cond(record_id):
    q = Query()
    return (q.id == record_id) | (q._id == record_id)

def plan_file_path(fn):
    safe = os.path.basename(str(fn).replace("\\", "/"))
    if not safe or safe in (".", ".."):
        return None
    fp = (TEST_PLANS_DIR / safe).resolve()
    try:
        fp.relative_to(TEST_PLANS_DIR.resolve())
    except ValueError:
        return None
    return fp

CONFIG_KEYS = ("ai_provider", "ollama_base_url", "ollama_model", "anthropic_api_key", "cloud_base_url", "cloud_api_key", "cloud_model")
SECRET_KEYS = ("cloud_api_key", "anthropic_api_key")
DEFAULT_CONFIG = {"ai_provider":"ollama","ollama_base_url":"http://localhost:11434","ollama_model":"qwen2.5-coder:3b"}

# Secrets are NEVER committed: load local .env (gitignored) so API_KEY /
# CLOUD_API_KEY / ANTHROPIC_API_KEY work without touching config files.
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

def _env_secret(name):
    v = (os.environ.get(name, "") or "").strip().strip('"').strip("'")
    return v

def _read_config_file():
    if not CONFIG_FILE.exists():
        return {}
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}

def _write_config_file(data):
    payload = {k: data.get(k) for k in CONFIG_KEYS if k in data}
    if not payload:
        return
    existing = _read_config_file()
    existing.update(payload)
    try:
        CONFIG_FILE.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass

def call_ai(prompt, cfg=None, timeout=300, json_mode=False, force_provider=None, on_stats=None):
    """Call AI provider (Ollama or Cloud API). Returns response text or None."""
    if cfg is None:
        cfg = get_config()
    provider = force_provider or cfg.get("ai_provider", "ollama")
    # Cloud API path
    if provider == "cloud" and cfg.get("cloud_base_url") and cfg.get("cloud_api_key"):
        url = cfg["cloud_base_url"].rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {cfg['cloud_api_key']}", "Content-Type": "application/json"}
        body = {"model": cfg.get("cloud_model", ""), "messages": [{"role": "user", "content": prompt}], "stream": False}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            r = requests.post(url, headers=headers, json=body, timeout=timeout)
            if r.status_code == 200:
                data = r.json()
                content = data["choices"][0]["message"]["content"].strip()
                # Track token usage if callback provided
                if on_stats:
                    usage = data.get("usage", {})
                    total_tokens = usage.get("total_tokens", 0)
                    if total_tokens:
                        on_stats(total_tokens)
                return content
            print(f"[call_ai][cloud] HTTP {r.status_code}: {r.text[:300]}", flush=True)
        except Exception as e:
            print(f"[call_ai][cloud] Error: {e}", flush=True)
        # If cloud failed and force_provider was 'cloud', don't fallback
        if force_provider == "cloud":
            return None
    # Ollama path
    if cfg.get("ollama_base_url") and cfg.get("ollama_model"):
        url = cfg["ollama_base_url"].rstrip("/") + "/api/chat"
        body = {"model": cfg["ollama_model"], "messages": [{"role": "user", "content": prompt}], "stream": False}
        try:
            r = requests.post(url, json=body, timeout=timeout)
            if r.status_code == 200:
                content = r.json()["message"]["content"].strip()
                if on_stats:
                    on_stats(0)
                return content
            print(f"[call_ai][ollama] HTTP {r.status_code}: {r.text[:300]}", flush=True)
        except Exception as e:
            print(f"[call_ai][ollama] Error: {e}", flush=True)
    return None

def init_config():
    file_cfg = _read_config_file()
    cfg = safe_all(config_table)
    if not cfg:
        merged = {k: v for k, v in {**DEFAULT_CONFIG, **file_cfg}.items() if k in CONFIG_KEYS and k not in SECRET_KEYS}
        safe_insert(config_table, merged)
        return
    if not file_cfg:
        return
    current = dict(cfg[0])
    updates = {}
    for k in CONFIG_KEYS:
        if k in SECRET_KEYS:
            continue
        if k in file_cfg and file_cfg[k] and current.get(k) != file_cfg[k]:
            updates[k] = file_cfg[k]
        elif k in current and k not in file_cfg:
            updates[k] = current[k]
    if updates:
        # DB never stores secrets — write only non-secret fields
        db_data = {k: v for k, v in {**current, **updates}.items() if k in CONFIG_KEYS and k not in SECRET_KEYS}
        with db_lock:
            config_table.remove(doc_ids=[cfg[0].doc_id])
            config_table.insert(db_data)
        _invalidate_table_cache("config")
        # config.json keeps the REAL secrets from the file (never a stale DB placeholder)
        full = {k: v for k, v in file_cfg.items() if k in CONFIG_KEYS}
        full.update(db_data)
        _write_config_file(full)


def get_config():
    cfg = safe_all(config_table)
    if not cfg:
        merged = {k: v for k, v in {**DEFAULT_CONFIG, **_read_config_file()}.items() if k in CONFIG_KEYS}
        safe_insert(config_table, merged)
        return dict(merged)
    result = {k: v for k, v in dict(cfg[0]).items() if k in CONFIG_KEYS}
    # Secrets never live in the DB — overlay them from the (gitignored) config
    # file first, then OS env vars (highest priority, e.g. Vercel dashboard).
    file_cfg = _read_config_file()
    for k in SECRET_KEYS:
        if file_cfg.get(k):
            result[k] = file_cfg[k]
    env_map = {"cloud_api_key": "CLOUD_API_KEY", "anthropic_api_key": "ANTHROPIC_API_KEY"}
    for k in SECRET_KEYS:
        env_val = _env_secret(env_map[k])
        if env_val:
            result[k] = env_val
    return result

def save_config(data):
    cfg = safe_all(config_table)
    db_data = {k: v for k, v in data.items() if k not in SECRET_KEYS}
    if cfg:
        with db_lock:
            config_table.remove(doc_ids=[cfg[0].doc_id])
            config_table.insert(db_data)
        _invalidate_table_cache("config")
    else:
        safe_insert(config_table, db_data)
    _write_config_file(data)

init_config()

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5MB max request size
CORS(app, resources={r"/api/*": {"origins": [
    re.compile(r"http://localhost(:\d+)?"),
    re.compile(r"http://127\.0\.0\.1(:\d+)?"),
    re.compile(r"chrome-extension://.*"),
]}})
limiter = Limiter(get_remote_address, app=app, default_limits=["200 per minute"], storage_uri="memory://")
active_runs = {}
project_queues = {} # Track bulk project runs
run_streams = {}
_active_runs_lock = threading.Lock()

def _cleanup_completed_runs():
    """Remove completed/errored runs from active_runs to prevent memory leak."""
    with _active_runs_lock:
        to_remove = [rid for rid, r in active_runs.items()
                     if r.get("status") in ("completed", "error")]
        for rid in to_remove:
            del active_runs[rid]
    # Also cleanup orphaned run_streams
    with _active_runs_lock:
        orphaned = [sid for sid in run_streams if sid not in active_runs]
        for sid in orphaned:
            del run_streams[sid]
ACTIVE_STATE_FILE = DATA_DIR / "active_state.json"
_state_save_lock = threading.Lock()
_last_state_save = 0.0
API_KEY = os.environ.get("API_KEY", "").strip()
# HTTP Basic Auth credentials — ALWAYS via env (.env locally, dashboard on
# hosting). NEVER hardcode or commit these; the repo must stay secret-free.
AUTH_USER = os.environ.get("AUTH_USER", "").strip()
AUTH_PASS = os.environ.get("AUTH_PASS", "")
LOCAL_ADDRS = {"127.0.0.1", "::1"}

def _basic_auth_ok():
    """Validate HTTP `Authorization: Basic base64(id:pass)` header."""
    if not (AUTH_USER and AUTH_PASS):
        return False
    auth = request.headers.get("Authorization", "")
    if not auth[:6].lower() == "basic ":
        return False
    try:
        import base64
        decoded = base64.b64decode(auth[6:].strip()).decode("utf-8", "replace")
    except Exception:
        return False
    user, sep, pwd = decoded.partition(":")
    return bool(sep) and user == AUTH_USER and pwd == AUTH_PASS
TEST_ARTIFACT_NAMES = {"Seed Test Project", "API Test Project", "API Test Project v2"}
TEST_ARTIFACT_URLS = {"https://example.com", "http://example.com"}
RESULT_LIST_FIELDS = (
    "_id", "id", "projectId", "projectName", "testCaseId", "testCaseName", "status", "mode", "device",
    "passed", "adapted", "failed", "blocked", "summary", "duration", "runner", "createdAt", "executedAt",
)

def slim_result(record):
    out = {k: record.get(k) for k in RESULT_LIST_FIELDS}
    if not out.get("id"):
        out["id"] = record.get("_id") or record.get("id")
    if not out.get("_id"):
        out["_id"] = record.get("_id") or record.get("id")
    return out

def parse_limit(default=100, max_limit=500):
    try:
        return min(max(int(request.args.get("limit", default)), 1), max_limit)
    except (TypeError, ValueError):
        return default

def save_active_state(force=False):
    global _last_state_save
    now = time.time()
    if not force and now - _last_state_save < 1:
        return
    payload = {
        "savedAt": now_iso(),
        "project_queues": project_queues,
        "active_runs": {
            rid: {
                "id": r.get("id"),
                "status": r.get("status"),
                "testCaseId": r.get("testCaseId"),
                "testCaseName": r.get("testCaseName"),
                "projectId": r.get("projectId"),
                "totalSteps": r.get("totalSteps"),
                "currentStep": r.get("currentStep", 0),
                "started_at": r.get("started_at"),
                "mode": r.get("mode"),
                "device": r.get("device"),
            }
            for rid, r in active_runs.items()
            if r.get("status") in ("queued", "running")
        },
    }
    with _state_save_lock:
        ACTIVE_STATE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        _last_state_save = now

def load_active_state():
    if not ACTIVE_STATE_FILE.exists():
        return
    try:
        data = json.loads(ACTIVE_STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    
    # Restore project queues
    for qid, q in data.get("project_queues", {}).items():
        if q.get("status") in ("running", "queued"):
            q = dict(q)
            q["status"] = "interrupted"
            q["currentTestCase"] = ""
            project_queues[qid] = q
            
    # Restore individual runs
    for rid, r in data.get("active_runs", {}).items():
        r = dict(r)
        # If it was interrupted, we'll try to resume it if it's not part of a project queue
        # (Project queues are handled separately to maintain sequence)
        if r.get("status") in ("running", "queued"):
            r["status"] = "interrupted"
            r["logs"] = []
            r["cancelled"] = False 
            active_runs[rid] = r

def resume_interrupted_runs():
    """Triggered on startup to resume runs marked as interrupted."""
    time.sleep(2) # Brief delay to let system stabilize
    
    # 1. Resume individual runs (not part of a project bulk run)
    resumed_count = 0
    for rid, r in list(active_runs.items()):
        if r.get("status") == "interrupted" and not r.get("projectId"):
            tc_id = r.get("testCaseId")
            mode = r.get("mode", "standard")
            device = r.get("device", "desktop")
            if tc_id:
                print(f"  [SYSTEM] Auto-resuming interrupted run: {rid} ({r.get('testCaseName')})")
                r["status"] = "queued"
                threading.Thread(target=run_test_thread, args=(tc_id, rid, mode, device), daemon=True).start()
                resumed_count += 1
    
    # 2. Resume project queues
    for qid, q in list(project_queues.items()):
        if q.get("status") == "interrupted":
            print(f"  [SYSTEM] Auto-resuming interrupted project queue: {qid}")
            # Re-fetch test cases for this project and restart the full run
            tcs = [t for t in safe_all(test_cases_table) if t.get("projectId") == qid and t.get("isRegression")]
            if not tcs:
                tcs = [t for t in safe_all(test_cases_table) if t.get("projectId") == qid]
            if tcs:
                mode = q.get("mode", "standard")
                device = q.get("device", "desktop")
                run_queue = []
                for tc in tcs:
                    rid = make_id()[:12]
                    active_runs[rid] = {
                        "id": rid, "status": "queued", "testCaseId": tc.get("id") or tc.get("_id"),
                        "logs": [], "cancelled": False, "mode": mode, "device": device,
                        "testCaseName": tc.get("name"), "projectId": qid,
                        "totalSteps": len(tc.get("steps", [])), "currentStep": 0
                    }
                    run_queue.append((tc.get("id") or tc.get("_id"), rid))
                project_queues[qid] = {
                    "id": qid, "status": "running", "total": len(run_queue),
                    "completed": [], "currentTestCase": tcs[0].get("name")
                }
                threading.Thread(target=_run_sequential_queue, args=(qid, run_queue, tcs, mode, device), daemon=True).start()
                resumed_count += 1
            else:
                print(f"  [SYSTEM] No test cases found for project queue {qid} — skipping resume")
                project_queues[qid]["status"] = "completed"

    if resumed_count:
        print(f"  [SYSTEM] Successfully resumed {resumed_count} test run(s).")

def cleanup_test_artifacts():
    projects = safe_all(projects_table)
    tcs = safe_all(test_cases_table)
    results = safe_all(results_table)
    tc_counts = {}
    for t in tcs:
        pid = t.get("projectId")
        tc_counts[pid] = tc_counts.get(pid, 0) + 1
    res_counts = {}
    for r in results:
        pid = r.get("projectId")
        res_counts[pid] = res_counts.get(pid, 0) + 1
    removed = 0
    for p in projects:
        name = p.get("name", "")
        url = (p.get("url") or "").rstrip("/")
        if name not in TEST_ARTIFACT_NAMES or url not in {u.rstrip("/") for u in TEST_ARTIFACT_URLS}:
            continue
        pid = p.get("id") or p.get("_id")
        if tc_counts.get(pid, 0) or res_counts.get(pid, 0):
            continue
        safe_remove(projects_table, record_id_cond(pid))
        removed += 1
    if removed:
        print(f"  Cleaned up {removed} empty API test artifact project(s)")

@app.before_request
def check_api_key():
    # Auth disabled until API_KEY or AUTH_USER/AUTH_PASS is set (local dev).
    auth_on = bool(API_KEY) or bool(AUTH_USER and AUTH_PASS)
    if not auth_on:
        return None
    # Browser preflight is always public.
    if request.method == "OPTIONS":
        return None
    # NOTE: the whole site (UI + /api/*) is locked when auth is on, so the
    # browser shows its native "sign in" popup on first open and then sends
    # the credentials automatically with every request (API, SSE, assets).
    # Localhost is trusted (same-machine dev loop).
    addr = (request.remote_addr or "").strip()
    if addr in LOCAL_ADDRS or addr.startswith("127."):
        return None
    # 1) API key: X-API-Key header, or ?access_key= for EventSource URLs
    #    (browsers cannot set custom headers on SSE connections).
    if API_KEY:
        key = request.headers.get("X-API-Key") or request.args.get("access_key")
        if key and key == API_KEY:
            return None
    # 2) HTTP Basic: Authorization header, or ?access_user/&access_pass=
    #    for EventSource URLs.
    if _basic_auth_ok():
        return None
    if AUTH_USER and AUTH_PASS:
        qu, qp = request.args.get("access_user"), request.args.get("access_pass")
        if qu == AUTH_USER and qp is not None and qp == AUTH_PASS:
            return None
    resp = err("Unauthorized — send X-API-Key header or Basic credentials", 401)
    resp[0].headers["WWW-Authenticate"] = 'Basic realm="ai-qa-tester"'
    return resp

@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
    return response

load_active_state()
cleanup_test_artifacts()

def ok(data):
    return jsonify({"success": True, "data": data})
def err(msg, code=400):
    return jsonify({"success": False, "error": msg}), code

def require_json(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if request.method in ("POST","PUT") and not request.is_json:
            return err("Request must be JSON")
        return f(*args, **kwargs)
    return wrapper

def make_id(): return str(uuid.uuid4()).replace("-","")
def now_iso(): return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

def get_compact_dom(page):
    """Returns comprehensive DOM with REAL CSS selectors for AI context.
    Extracts ALL interactive elements (up to 100) with the most reliable selector available."""
    try:
        return page.evaluate("""() => {
            function bestSelector(el, index) {
                if (el.dataset && el.dataset.testid) return '[data-testid="' + el.dataset.testid + '"]';
                if (el.id) return '#' + CSS.escape(el.id);
                if (el.name) return el.tagName.toLowerCase() + '[name="' + el.name + '"]';
                if (el.getAttribute('aria-label')) return el.tagName.toLowerCase() + '[aria-label="' + el.getAttribute('aria-label') + '"]';
                if (el.getAttribute('role')) {
                    const role = el.getAttribute('role');
                    const txt = (el.innerText || el.value || '').trim().slice(0, 30);
                    if (txt) return '[role="' + role + '"] >> text="' + txt + '"';
                }
                let sel = el.tagName.toLowerCase();
                if (el.type && ['input','button','select'].includes(el.tagName.toLowerCase())) {
                    sel += '[type="' + el.type + '"]';
                }
                if (el.className && typeof el.className === 'string') {
                    const classes = el.className.trim().split(/\\s+/)
                        .filter(c => c && !c.startsWith('ng-') && !c.startsWith('vue-') && !c.startsWith('sc-') && c.length < 30)
                        .slice(0, 3);
                    if (classes.length) sel += '.' + classes.join('.');
                }
                if (el.href) {
                    try {
                        const url = new URL(el.href, location.href);
                        const path = url.pathname;
                        if (path && path !== '/') sel += '[href="' + path + '"]';
                    } catch(e) {}
                }
                if (el.placeholder) sel += '[placeholder="' + el.placeholder.slice(0, 30) + '"]';
                if (sel === el.tagName.toLowerCase()) sel += ':nth-of-type(' + (index + 1) + ')';
                return sel;
            }
            const interactiveSelectors = 'a[href], button, input, select, textarea, [role="button"], [role="link"], [role="tab"], [role="menuitem"], [onclick], [data-testid]';
            const allLinks = [];
            const allForms = [];
            const allInteractive = [];
            const seen = new Set();
            let idx = 0;
            document.querySelectorAll(interactiveSelectors).forEach((el) => {
                if (allInteractive.length >= 100) return;
                const tag = el.tagName.toLowerCase();
                const txt = (el.innerText || el.value || el.placeholder || el.title || el.getAttribute('aria-label') || '').trim().slice(0, 50);
                const s = bestSelector(el, idx);
                if (seen.has(s)) return;
                seen.add(s);
                const entry = tag + ' ' + s + (txt ? ' => "' + txt + '"' : '');
                allInteractive.push(entry);
                if (tag === 'a' && el.href) {
                    try {
                        const url = new URL(el.href, location.href);
                        if (url.origin === location.origin && url.pathname !== location.pathname) {
                            allLinks.push({text: txt || url.pathname, url: el.href, selector: s});
                        }
                    } catch(e) {}
                }
                idx++;
            });
            document.querySelectorAll('form').forEach((form, fi) => {
                if (fi > 5) return;
                const action = form.action || '';
                const method = form.method || 'GET';
                const fields = [];
                form.querySelectorAll('input, select, textarea').forEach((el, ei) => {
                    if (ei > 10) return;
                    const s = bestSelector(el, ei);
                    const ph = el.placeholder || el.name || el.type || '';
                    fields.push(s + ' (' + ph + ')');
                });
                if (fields.length) allForms.push({action: action, method: method, fields: fields});
            });
            const headings = [];
            document.querySelectorAll('h1, h2, h3').forEach((el, i) => {
                if (i > 15) return;
                const txt = el.innerText.trim().slice(0, 60);
                if (txt) headings.push(el.tagName.toLowerCase() + ' "' + txt + '"');
            });
            const navLinks = [];
            document.querySelectorAll('nav a, [role="navigation"] a, .nav a, .menu a, .navbar a, header a').forEach((el, i) => {
                if (i > 20) return;
                const txt = (el.innerText || '').trim().slice(0, 40);
                const s = bestSelector(el, i);
                if (txt && !seen.has(s)) {
                    seen.add(s);
                    navLinks.push(txt + ' => ' + s);
                }
            });
            return JSON.stringify({
                page_title: document.title,
                page_url: location.href,
                headings: headings,
                nav_links: navLinks,
                forms: allForms,
                interactive: allInteractive,
                discoverable_links: allLinks.slice(0, 30)
            }, null, 2);
        }""")
    except Exception as e:
        return f"DOM extraction failed: {str(e)}"

def _is_safe_url(url):
    """Check if URL is safe (not pointing to private/internal networks)."""
    if not url or not isinstance(url, str):
        return False
    try:
        from urllib.parse import urlparse
        import ipaddress
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https', ''):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        # Check for private/internal IPs
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        except ValueError:
            # Not an IP - check hostname patterns
            blocked = ['localhost', '127.0.0.1', '::1', '0.0.0.0', '169.254.169.254',
                       'metadata.google.internal', 'instance-data', '169.254.169.254']
            if hostname.lower() in blocked:
                return False
            # Check for IP-like patterns
            import re
            if re.match(r'^(10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.|127\.)', hostname):
                return False
        return True
    except Exception:
        return False

def _extract_auth_credentials(url):
    """Extracts username and password from basic auth URL (e.g. https://user:pass@domain.com).
    Returns (clean_url, dict(username=..., password=...) or None, (username, password) or None)
    """
    if not url or not isinstance(url, str):
        return url, None, None
    try:
        from urllib.parse import urlparse, urlunparse, unquote
        parsed = urlparse(url)
        if parsed.username or parsed.password:
            user = unquote(parsed.username) if parsed.username else ""
            pwd = unquote(parsed.password) if parsed.password else ""
            netloc = parsed.hostname or ""
            if parsed.port:
                netloc = f"{netloc}:{parsed.port}"
            clean_url = urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
            return clean_url, {"username": user, "password": pwd}, (user, pwd)
    except Exception:
        pass
    return url, None, None

def slugify(s): return re.sub(r'[^a-z0-9-]+', '-', s.lower()).strip('-')

# Ollama helpers
def ollama_available():
    cfg = get_config()
    try:
        r = requests.get(cfg["ollama_base_url"].rstrip("/")+"/api/tags", timeout=5)
        return r.status_code == 200
    except Exception: return False

def get_ollama_models():
    cfg = get_config()
    try:
        r = requests.get(cfg["ollama_base_url"].rstrip("/")+"/api/tags", timeout=5)
        if r.status_code == 200:
            return [m["name"] for m in r.json().get("models",[])]
    except requests.RequestException:
        pass
    return []

def run_test_case_with_ai(test_case, base_url, run_id, log_cb, mode="standard", device="desktop"):
    steps = test_case.get("steps",[])
    if isinstance(steps, str): steps = json.loads(steps) if steps else []
    total = len(steps)
    step_results = []
    _token_total = [0]
    def _track_tokens(resp):
        if resp and "eval_count" in resp:
            _token_total[0] += resp.get("eval_count", 0)
    log_cb("info", f"Starting: {test_case.get('name','Untitled')} | Mode: {mode} | Device: {device} | URL: {base_url} | Steps: {total}")
    if total == 0: return {"status":"pass","steps":[],"passed":0,"adapted":0,"failed":0,"blocked":0,"summary":"No steps"}

    # Extract HTTP basic auth credentials if present in base_url or step targets
    clean_base, creds, req_auth = _extract_auth_credentials(base_url)

    # === Pre-flight health check ===
    # Check the SAME URL the test will actually navigate to (first navigate step),
    # not base_url, so we never false-alert on a different/flaky host.
    nav_target = ""
    for st in steps:
        if st.get("action", "").lower() in ("navigate", "go to"):
            t = (st.get("target") or "").strip()
            if t.startswith("http"):
                nav_target = t
            elif st.get("action", "").lower() in ("navigate", "go to"):
                nav_target = base_url.rstrip("/") + "/" + t.lstrip("/")
            break
    
    if not creds and nav_target:
        _, creds, req_auth = _extract_auth_credentials(nav_target)

    health_url = (nav_target or base_url).rstrip("/")
    log_cb("info", f"Site health check: {health_url}")
    
    health_ok = False
    for attempt in range(2):
        try:
            hr = requests.get(health_url, timeout=10, headers={"User-Agent":"Mozilla/5.0"}, allow_redirects=True, auth=req_auth)
            if hr.status_code >= 500:
                log_cb("warning", f"Site {health_url} returned HTTP {hr.status_code} (Attempt {attempt+1}/2) — retrying...")
                time.sleep(2)
            else:
                log_cb("ok", f"Site {health_url} responded with HTTP {hr.status_code}")
                health_ok = True
                break
        except (requests.ConnectionError, requests.Timeout) as conn_err:
            log_cb("warning", f"Site {health_url} unreachable ({type(conn_err).__name__}) (Attempt {attempt+1}/2)")
            if attempt < 1:
                time.sleep(2)

    if not health_ok:
        log_cb("warning", "Proceeding with test despite health check failures...")

    try:
        adapted_count = 0
        healed_steps = []
        screenshots = {}
        console_logs = []
        network_logs = []

        with sync_playwright() as p:
            # Phase 2: Mobile Emulation
            is_mobile = device == "mobile"
            if is_mobile:
                device_config = p.devices["iPhone 13"]
                browser = p.chromium.launch(headless=True)
                # Ensure we don't pass viewport twice
                ctx_args = device_config.copy()
                ctx_args.update({
                    "viewport": {"width": 390, "height": 844},
                    "is_mobile": True,
                    "has_touch": True
                })
                if creds:
                    ctx_args["http_credentials"] = creds
                ctx = browser.new_context(**ctx_args)
                log_cb("info", f"📱 Emulating Mobile: iPhone 13 ({device_config['user_agent'][:40]}...)")
            else:
                browser = p.chromium.launch(headless=True)
                ctx_args = {"viewport": {"width": 1280, "height": 720}}
                if creds:
                    ctx_args["http_credentials"] = creds
                ctx = browser.new_context(**ctx_args)
            
            page = ctx.new_page()

            # Priority 1: Network & Console Analysis
            page.on("console", lambda msg: console_logs.append({
                "type": msg.type, "text": msg.text, "location": msg.location, "time": now_iso()
            }))
            page.on("pageerror", lambda err: console_logs.append({
                "type": "error", "text": str(err), "time": now_iso()
            }))
            page.on("response", lambda res: network_logs.append({
                "url": res.url, "status": res.status, "method": res.request.method, "time": now_iso()
            }) if res.status >= 400 else None)

            _screenshot_count = [0]
            SCREENSHOT_LIMIT = 100
            def capture_screenshot(step_label):
                if _screenshot_count[0] >= SCREENSHOT_LIMIT:
                    return None
                try:
                    raw = page.screenshot(type="png")
                    filename = f"{run_id}_{step_label}.png"
                    filepath = SCREENSHOTS_DIR / filename
                    filepath.write_bytes(raw)
                    path = f"/api/screenshots/{filename}"
                    screenshots[step_label] = path
                    _screenshot_count[0] += 1
                    return path
                except Exception as e:
                    log_cb("error", f"Screenshot failed: {e}")
                    return None

            for i, step in enumerate(steps):
                s = step.get("seq",i+1)
                action = step.get("action","")
                target = step.get("target","")
                desc = step.get("description","")
                verify = step.get("verify","")
                val = step.get("value","")

                if run_id in active_runs and active_runs[run_id].get("cancelled"):
                    step_results.append({"seq":s,"status":"fail","note":"Test cancelled by user — remaining steps skipped","durationMs":0}); break

                t0 = time.time()
                log_cb("step", f"Step {s}/{total}: {action} {desc}")
                try:
                    if action in ("navigate","go to"):
                        # If target is just a path segment (no http, no /), use base_url
                        if target.startswith("http"):
                            url = target
                        elif target.startswith("/"):
                            url = base_url.rstrip("/") + target
                        else:
                            # Could be a partial path like "Home" or a full path like "accessories.html"
                            url = base_url.rstrip("/") + "/" + target.lstrip("/")
                        nav_ok = False
                        nav_attempts = [url]
                        try:
                            page.goto(url, wait_until="domcontentloaded", timeout=30000)
                            # Wait for URL to actually change from about:blank
                            for _ in range(10):
                                if page.url != "about:blank": break
                                time.sleep(0.5)
                            try: page.wait_for_selector("body", timeout=5000)
                            except Exception:
                                pass
                            nav_ok = True
                        except Exception as nav_err:
                            log_cb("info", f"Navigation failed for step {s}, asking AI...")
                            try:
                                page_html = page.content()[:2000] if page.content() else ""
                                prompt = (
                                    f"Navigation to {url} failed.\n"
                                    f"Error: {str(nav_err)[:200]}\n"
                                    f"Page content: {page_html[:500]}\n\n"
                                    "Suggest an alternative URL or approach.\n"
                                    "Respond with only one line:\n"
                                    "RETRY: <full alternative URL> | ABORT: <reason>"
                                )
                                ai_txt = call_ai(prompt, timeout=10)
                                if ai_txt:
                                    log_cb("info", f"AI nav response: {ai_txt[:200]}")
                                    lines = re.split(r'[\n|]+', ai_txt)
                                    for line in lines:
                                        line = line.strip()
                                        if line.upper().startswith("RETRY:"):
                                            parts = line.split(":", 1)
                                            if len(parts) == 2:
                                                alt_url = parts[1].strip().split("|")[0].split("\n")[0].strip()
                                                if alt_url and alt_url.startswith("http"):
                                                    nav_attempts.append(alt_url)
                                                    break
                            except Exception:
                                pass
                            for alt in nav_attempts[1:]:
                                try:
                                    page.goto(alt, wait_until="domcontentloaded", timeout=30000)
                                    try: page.wait_for_selector("body", timeout=5000)
                                    except Exception:
                                        pass
                                    nav_ok = True
                                    url = alt
                                    break
                                except Exception as alt_err:
                                    log_cb("info", f"AI nav alt '{alt}' failed: {str(alt_err)[:100]}")
                        if nav_ok:
                            status = "pass"
                            step_results.append({"seq":s,"status":status,"note":f"Navigated to {url}","durationMs":int((time.time()-t0)*1000)})
                            if len(nav_attempts) > 1:
                                healed_steps.append({"index": i, "new": url})
                            screenshot = capture_screenshot(f"step-{s}")
                            if screenshot: step_results[-1]["screenshot"] = screenshot
                            log_cb("ok", f"Navigated to {url}")
                            
                            # --- PRE-SCAN VALIDATION ---
                            log_cb("info", "Running Pre-scan validation...")
                            critical_elements = [step.get("target") for step in steps if step.get("action") in ("click", "fill", "verify") and step.get("target")]
                            missing = []
                            for sel in set(critical_elements):
                                if sel and not sel.startswith("text="):
                                    try:
                                        if not page.query_selector(sel):
                                            missing.append(sel)
                                    except Exception as _prescan_err:
                                        log_cb("warning", f"Pre-scan selector error for '{sel}': {_prescan_err}")
                            if missing:
                                log_cb("warning", f"Pre-scan detected {len(missing)} missing critical element(s): {', '.join(missing[:3])}...")
                            else:
                                log_cb("ok", "Pre-scan passed: All critical elements detected.")
                            # ---------------------------
                        else:
                            step_results.append({"seq":s,"status":"fail","note":f"Navigation failed: {url} — site unreachable","durationMs":int((time.time()-t0)*1000)})
                            screenshot = capture_screenshot(f"step-{s}")
                            if screenshot: step_results[-1]["screenshot"] = screenshot
                            log_cb("error", f"Step {s}: navigation failed to {url}")

                    elif action == "click":
                        clicked = False
                        ai_used = False
                        click_attempts = [target]
                        # Fast path: if target looks like TEXT (not CSS), try to resolve it first
                        if not target.startswith('#') and not target.startswith('.') and not target.startswith('[') and not target.startswith('text=') and not target.startswith('xpath=') and not re.match(r'^[a-z]+\[', target):
                            resolved = _find_selector_by_text(page, target, 'click', desc)
                            if resolved and resolved != target:
                                log_cb("info", f"Runtime text resolved: '{target}' -> {resolved}")
                                target = resolved
                                step["target"] = resolved
                        try:
                            if ":visible" not in target and not target.startswith("text=") and not target.startswith("xpath="):
                                try:
                                    page.click(f"{target}:visible", timeout=3000)
                                    clicked = True
                                except Exception:
                                    page.click(target, timeout=3000)
                                    clicked = True
                            else:
                                page.click(target, timeout=5000)
                                clicked = True
                        except Exception:
                            # Hover-before-click: try hovering over parent menu items first
                            try:
                                hover_targets = page.evaluate(r"""(targetText) => {
                                    const t = targetText.toLowerCase();
                                    const menus = document.querySelectorAll('nav li, .menu-item, [class*="nav"] > *, [class*="menu"] > *, .category-item, .parent-category');
                                    const results = [];
                                    for (const el of menus) {
                                        const elText = (el.innerText || '').trim().toLowerCase();
                                        // Check if this menu item text is a prefix of our target
                                        if (t.includes(elText) && elText.length > 2 && elText.length < t.length) {
                                            let s = null;
                                            if (el.id) s = '#' + el.id;
                                            else if (el.className && typeof el.className === 'string') {
                                                const c = el.className.trim().split(/\s+/).filter(c => c && c.length < 30).slice(0,2);
                                                if (c.length) s = el.tagName.toLowerCase() + '.' + c.join('.');
                                            }
                                            if (s) results.push(s);
                                        }
                                    }
                                    return results.slice(0, 3);
                                }""", desc)
                                for ht in (hover_targets or []):
                                    try:
                                        log_cb("info", f"Hovering parent menu: {ht}")
                                        page.hover(ht, timeout=2000)
                                        page.wait_for_timeout(500)
                                        # Now try clicking the target again
                                        page.click(target, timeout=3000)
                                        clicked = True
                                        log_cb("info", f"Clicked after hover: {target}")
                                        break
                                    except Exception as _hover_click_err:
                                        log_cb("info", f"Hover-click attempt on '{ht}' failed: {str(_hover_click_err)[:60]}")
                            except Exception as _hover_eval_err:
                                log_cb("info", f"Hover target evaluation failed: {str(_hover_eval_err)[:60]}")
                        if not clicked:
                            log_cb("info", f"AI CLI Output: Analyzing page for element '{desc}'...")
                            try:
                                dom = get_compact_dom(page)
                                # Truncate DOM for AI context window
                                dom_snippet = dom[:3000] if len(dom) > 3000 else dom
                                prompt = (
                                    f"You are an expert QA Automation AI. You are controlling a browser via Playwright.\n"
                                    f"URL: {page.url}\n"
                                    f"ACTION: Click on '{desc}'\n"
                                    f"FAILED SELECTOR: {target}\n\n"
                                    f"COMPACT DOM:\n{dom_snippet}\n\n"
                                    "Analyze the DOM and find the best alternative selector to click the element.\n"
                                    "Respond with ONLY the selector (no explanation needed):\n"
                                    "SELECTOR: <playwright selector>"
                                )
                                resp = call_ai(prompt, timeout=60)
                                if resp:
                                    reasoning = ""
                                    found_sel = False
                                    for line in resp.split("\n"):
                                        line = line.strip()
                                        if line.upper().startswith("REASONING:"):
                                            reasoning = line.split(":",1)[1].strip()
                                        elif line.upper().startswith("SELECTOR:"):
                                            sel = line.split(":",1)[1].strip().strip('`').strip('"').strip("'")
                                            if sel: 
                                                click_attempts.append(sel)
                                                found_sel = True
                                    
                                    if not found_sel:
                                        for line in resp.split("\n"):
                                            line = line.strip().strip('`').strip('"').strip("'")
                                            if (line.startswith("#") or line.startswith(".") or "text=" in line or ">>" in line) and len(line) < 100:
                                                click_attempts.append(line)
                                                found_sel = True
                                                break
                                    
                                    if reasoning: log_cb("info", f"Ollama CLI Output: {reasoning}")
                                    if not found_sel:
                                        log_cb("warning", f"Ollama CLI Output: AI couldn't suggest a clear selector. Raw: {resp[:100]}...")
                                        click_attempts.append(f"text={desc}")
                                    
                                    if len(click_attempts) > 1:
                                        log_cb("info", f"Ollama CLI Output: Trying AI suggested selector: {click_attempts[-1]}")
                                else:
                                    log_cb("error", "Ollama CLI Output: AI request returned no response")
                            except Exception as ai_err:
                                log_cb("warning", f"AI request error: {ai_err}")
                            
                            for sel in click_attempts[1:]:
                                try:
                                    # Strategy: Scroll into view first, then try to find and click
                                    try:
                                        el = page.wait_for_selector(sel, timeout=5000)
                                        el.scroll_into_view_if_needed()
                                        page.wait_for_timeout(500)
                                        page.click(sel, timeout=5000, force=True)
                                    except Exception:
                                        # Emergency fallback: Click by coordinates if element found but click fails
                                        el = page.query_selector(sel)
                                        if el:
                                            box = el.bounding_box()
                                            if box:
                                                page.mouse.click(box['x'] + box['width']/2, box['y'] + box['height']/2)
                                            else:
                                                page.click(sel, timeout=5000, force=True)
                                        else:
                                            page.click(sel, timeout=5000, force=True)
                                    clicked = True
                                    target = sel
                                    ai_used = True
                                    break
                                except Exception as sel_err:
                                    log_cb("info", f"Ollama CLI Output: AI selector '{sel}' failed: {str(sel_err)[:50]}")
                                    continue
                        if clicked:
                            status = "pass"
                            step_results.append({"seq":s,"status":status,"note":f"Clicked {target}","durationMs":int((time.time()-t0)*1000)})
                            if ai_used:
                                healed_steps.append({"index": i, "new": target})
                            screenshot = capture_screenshot(f"step-{s}")
                            if screenshot: step_results[-1]["screenshot"] = screenshot
                            log_cb("ok", f"Clicked {target}")
                        else:
                            err_msg = f"Click failed: {desc} — element not found on page"
                            try:
                                page_title = page.title()
                                err_msg += f" | Page title: {page_title[:100]}"
                            except Exception:
                                pass
                            step_results.append({"seq":s,"status":"fail","note":err_msg,"durationMs":int((time.time()-t0)*1000)})
                            screenshot = capture_screenshot(f"step-{s}")
                            if screenshot: step_results[-1]["screenshot"] = screenshot
                            log_cb("error", f"Step {s}: all click attempts failed for '{desc}'")

                    elif action in ("type","fill"):
                        val = step.get("value","") or step.get("description","").split("with")[-1].strip()
                        filled = False
                        ai_used = False
                        fill_attempts = [target]
                        # Fast path: resolve TEXT targets to real CSS selectors
                        if not target.startswith('#') and not target.startswith('.') and not target.startswith('[') and not target.startswith('text=') and not target.startswith('xpath=') and not re.match(r'^[a-z]+\[', target):
                            resolved = _find_selector_by_text(page, target, 'fill', desc)
                            if resolved and resolved != target:
                                log_cb("info", f"Runtime text resolved: '{target}' -> {resolved}")
                                target = resolved
                                step["target"] = resolved
                            else:
                                # Aggressive search: find input by label text, placeholder, or nearby text
                                try:
                                    aggressive = page.evaluate("""(desc) => {
                                        const t = desc.toLowerCase();
                                        // Try all inputs
                                        const inputs = document.querySelectorAll('input, select, textarea');
                                        for (const inp of inputs) {
                                            const ph = (inp.placeholder || '').toLowerCase();
                                            const name = (inp.name || '').toLowerCase();
                                            const id = (inp.id || '').toLowerCase();
                                            const label = inp.getAttribute('aria-label') || '';
                                            // Match by placeholder, name, id, or label
                                            if (ph.includes(t) || name.includes(t) || id.includes(t) || label.toLowerCase().includes(t)) {
                                                if (inp.id) return '#' + inp.id;
                                                if (inp.name) return inp.tagName.toLowerCase() + '[name="' + inp.name + '"]';
                                            }
                                        }
                                        // Try label elements
                                        const labels = document.querySelectorAll('label');
                                        for (const l of labels) {
                                            const lt = l.textContent.trim().toLowerCase();
                                            if (lt.includes(t) || t.includes(lt.replace(':', '').trim())) {
                                                if (l.htmlFor) { const inp = document.getElementById(l.htmlFor); if (inp) return '#' + inp.id; }
                                                const inp = l.querySelector('input, select, textarea');
                                                if (inp && inp.id) return '#' + inp.id;
                                            }
                                        }
                                        return null;
                                    }""", desc)
                                    if aggressive:
                                        log_cb("info", f"Aggressive fill resolved: '{target}' -> {aggressive}")
                                        target = aggressive
                                        step["target"] = aggressive
                                except Exception as _agg_err:
                                    log_cb("info", f"Aggressive fill resolution failed: {str(_agg_err)[:80]}")
                        try:
                            if ":visible" not in target and not target.startswith("text=") and not target.startswith("xpath="):
                                try:
                                    page.fill(f"{target}:visible", val, timeout=3000)
                                    filled = True
                                except Exception:
                                    page.fill(target, val, timeout=3000)
                                    filled = True
                            else:
                                page.fill(target, val, timeout=5000)
                                filled = True
                        except Exception:
                            log_cb("info", f"AI CLI Output: Analyzing page for input '{desc}'...")
                            try:
                                dom = get_compact_dom(page)
                                dom_snippet = dom[:3000] if len(dom) > 3000 else dom
                                prompt = (
                                    f"You are an expert QA Automation AI.\n"
                                    f"URL: {page.url}\n"
                                    f"TASK: Fill '{val}' into '{desc}'\n"
                                    f"FAILED SELECTOR: {target}\n\n"
                                    f"COMPACT DOM:\n{dom_snippet}\n\n"
                                    "Analyze the DOM and find the best alternative selector for the input field.\n"
                                    "Respond with ONLY the selector (no explanation needed):\n"
                                    "SELECTOR: <selector>"
                                )
                                resp = call_ai(prompt, timeout=60)
                                if resp:
                                    reasoning = ""
                                    found_sel = False
                                    for line in resp.split("\n"):
                                        line = line.strip()
                                        if line.upper().startswith("REASONING:"):
                                            reasoning = line.split(":",1)[1].strip()
                                        elif line.upper().startswith("SELECTOR:"):
                                            sel = line.split(":",1)[1].strip().strip('`').strip('"').strip("'")
                                            if sel:
                                                fill_attempts.append(sel)
                                                found_sel = True
                                    
                                    if not found_sel:
                                        for line in resp.split("\n"):
                                            line = line.strip().strip('`').strip('"').strip("'")
                                            if (line.startswith("#") or line.startswith(".") or "text=" in line) and len(line) < 100:
                                                fill_attempts.append(line)
                                                found_sel = True
                                                break
                                    
                                    if reasoning: log_cb("info", f"Ollama CLI Output: {reasoning}")
                                    if not found_sel:
                                        log_cb("warning", f"Ollama CLI Output: AI couldn't suggest a fill selector. Raw: {resp[:100]}...")
                                        fill_attempts.append(f"text={desc}")
                                else:
                                    log_cb("error", "Ollama CLI Output: AI request returned no response")
                            except Exception as ai_err:
                                log_cb("warning", f"AI request error: {ai_err}")
                            
                            for sel in fill_attempts[1:]:
                                try:
                                    page.fill(sel, val, timeout=5000)
                                    filled = True
                                    target = sel
                                    ai_used = True
                                    break
                                except Exception:
                                    continue
                        if filled:
                            status = "pass"
                            step_results.append({"seq":s,"status":status,"note":f"Filled {target}","durationMs":int((time.time()-t0)*1000)})
                            if ai_used:
                                healed_steps.append({"index": i, "new": target})
                            screenshot = capture_screenshot(f"step-{s}")
                            if screenshot: step_results[-1]["screenshot"] = screenshot
                            log_cb("ok", f"Filled {target}")
                        else:
                            err_msg = f"Fill failed: {desc} — input field not found"
                            try:
                                page_title = page.title()
                                err_msg += f" | Page title: {page_title[:100]}"
                            except Exception:
                                pass
                            step_results.append({"seq":s,"status":"fail","note":err_msg,"durationMs":int((time.time()-t0)*1000)})
                            screenshot = capture_screenshot(f"step-{s}")
                            if screenshot: step_results[-1]["screenshot"] = screenshot
                            log_cb("error", f"Step {s}: all fill attempts failed for '{desc}'")

                    elif action == "wait":
                        m = re.search(r"\d+", desc)
                        ms = int(m.group()) if m else 2000
                        page.wait_for_timeout(ms)
                        step_results.append({"seq":s,"status":"pass","note":f"Waited {ms}ms","durationMs":int((time.time()-t0)*1000)})
                        screenshot = capture_screenshot(f"step-{s}")
                        if screenshot:
                            step_results[-1]["screenshot"] = screenshot

                    elif action in ("verify","check","verifyElement","verifyText","verify_text"):
                        try:
                            sel = target if target and not target.startswith("text=") else f"text={target or desc}"
                            found_el = False
                            try:
                                page.wait_for_selector(sel, timeout=3000)
                                found_el = True
                            except Exception:
                                # First matching element may be hidden (e.g. mobile nav or modal section); check for any visible match or DOM presence
                                if ":visible" not in sel and not sel.startswith("text=") and not sel.startswith("xpath="):
                                    try:
                                        page.wait_for_selector(f"{sel}:visible", timeout=3000)
                                        found_el = True
                                    except Exception:
                                        if page.locator(sel).count() > 0:
                                            found_el = True
                                elif page.locator(sel).count() > 0:
                                    found_el = True

                            if not found_el:
                                raise TimeoutError(f"Element '{sel}' not found or visible")

                            # If a specific text value is requested to be verified inside the element
                            expected_text = val if action in ("verifyText", "verify_text") and val else (desc if action in ("verifyText", "verify_text") and not val else (val if val else None))
                            if expected_text and target and not target.startswith("text="):
                                actual_text = page.inner_text(target)
                                if expected_text.lower() not in actual_text.lower():
                                    raise ValueError(f"Expected text '{expected_text}' not in '{actual_text}'")
                            step_results.append({"seq":s,"status":"pass","note":f"Found: {target or desc}","durationMs":int((time.time()-t0)*1000)})
                            screenshot = capture_screenshot(f"step-{s}")
                            if screenshot: step_results[-1]["screenshot"] = screenshot
                        except Exception as _v_err:
                            # AI-assisted verification fallback
                            log_cb("info", f"Verification failed for '{target}' ({_v_err}), asking AI...")
                            try:
                                dom = get_compact_dom(page)
                                prompt = (
                                    f"You are an expert QA Automation AI.\n"
                                    f"URL: {page.url}\n"
                                    f"VERIFY: {desc} (Target: {target})\n\n"
                                    f"COMPACT DOM:\n{dom}\n\n"
                                    "Determine if the expected element or state is present.\n"
                                    "Respond with only: FOUND | NOT_FOUND: <reason>"
                                )
                                cfg = get_config()
                                ai_txt = call_ai(prompt, cfg=cfg, timeout=30)
                                if ai_txt:
                                    if ai_txt.upper().startswith("FOUND"):
                                        step_results.append({"seq":s,"status":"pass","note":f"AI verified: {ai_txt}","durationMs":int((time.time()-t0)*1000)})
                                        screenshot = capture_screenshot(f"step-{s}")
                                        if screenshot: step_results[-1]["screenshot"] = screenshot
                                        log_cb("ok", f"AI verified presence of '{desc}'")
                                        continue
                            except Exception: pass
                            
                            step_results.append({"seq":s,"status":"fail","note":f"Verification failed: {target or desc} not found","durationMs":int((time.time()-t0)*1000)})
                            screenshot = capture_screenshot(f"step-{s}")
                            if screenshot: step_results[-1]["screenshot"] = screenshot
                            log_cb("error", f"Step {s}: verification failed for '{target or desc}'")

                    elif action in ("getTitle", "get_title"):
                        title = page.title()
                        step_results.append({"seq":s,"status":"pass","note":f"Title: {title}","durationMs":int((time.time()-t0)*1000)})
                        screenshot = capture_screenshot(f"step-{s}")
                        if screenshot: step_results[-1]["screenshot"] = screenshot

                    elif action in ("isEnabled", "is_enabled"):
                        enabled = page.is_enabled(target, timeout=5000)
                        status = "pass" if enabled else "fail"
                        step_results.append({"seq":s,"status":status,"note":f"Enabled: {enabled}","durationMs":int((time.time()-t0)*1000)})
                        screenshot = capture_screenshot(f"step-{s}")
                        if screenshot: step_results[-1]["screenshot"] = screenshot

                    elif action == "verifyImageLoaded":
                        # Native handler for checking if image loaded
                        loaded = page.evaluate('''(sel) => {
                            const img = document.querySelector(sel);
                            return img && img.complete && img.naturalWidth > 0;
                        }''', target)
                        status = "pass" if loaded else "fail"
                        step_results.append({"seq":s,"status":status,"note":f"Image loaded: {loaded}","durationMs":int((time.time()-t0)*1000)})
                        screenshot = capture_screenshot(f"step-{s}")
                        if screenshot: step_results[-1]["screenshot"] = screenshot

                    elif action in ("verify_visual_health", "verify_css", "verify_styles", "verify_stylesheets"):
                        failed_css_requests = [
                            n for n in network_logs
                            if ('.css' in n.get('url', '').lower() or 'stylesheet' in n.get('url', '').lower())
                            and n.get('status', 200) >= 400
                        ]
                        dom_css_health = page.evaluate(r"""() => {
                            const linkSheets = Array.from(document.querySelectorAll('link[rel="stylesheet"]'));
                            const sheets = Array.from(document.styleSheets);
                            let totalRules = 0;
                            const brokenSheets = [];
                            for (const s of sheets) {
                                try {
                                    const rulesCount = s.cssRules ? s.cssRules.length : 0;
                                    totalRules += rulesCount;
                                    if (rulesCount === 0 && s.href) {
                                        brokenSheets.push(s.href);
                                    }
                                } catch (e) {
                                    if (s.href) brokenSheets.push(s.href);
                                }
                            }
                            return {
                                linkTagCount: linkSheets.length,
                                sheetCount: sheets.length,
                                totalRules: totalRules,
                                brokenSheets: brokenSheets
                            };
                        }""")
                        if failed_css_requests:
                            first_fail = failed_css_requests[0]
                            status = "fail"
                            note = f"FAIL: Critical stylesheet '{first_fail['url']}' returned HTTP {first_fail['status']}! Page UI styling is broken."
                            log_cb("error", note)
                        elif dom_css_health.get('linkTagCount', 0) > 0 and dom_css_health.get('totalRules', 0) == 0:
                            status = "fail"
                            note = f"FAIL: 0 CSS rules active across {dom_css_health.get('linkTagCount')} stylesheets. Page is unstyled."
                            log_cb("error", note)
                        elif dom_css_health.get('linkTagCount', 0) > 0 and len(dom_css_health.get('brokenSheets', [])) == dom_css_health.get('linkTagCount'):
                            broken_first = dom_css_health.get('brokenSheets', [])[0]
                            status = "fail"
                            note = f"FAIL: All external stylesheets failed to load rules ({broken_first}). UI is unstyled."
                            log_cb("error", note)
                        else:
                            status = "pass"
                            note = f"Visual Health OK: {dom_css_health.get('sheetCount', 1)} stylesheets with {dom_css_health.get('totalRules', 0)} active CSS rules"
                            log_cb("ok", note)

                        step_results.append({"seq":s,"status":status,"note":note,"durationMs":int((time.time()-t0)*1000)})
                        screenshot = capture_screenshot(f"step-{s}")
                        if screenshot: step_results[-1]["screenshot"] = screenshot

                    elif action in ("verify_network_assets", "verify_assets"):
                        critical_failures = [
                            n for n in network_logs
                            if any(ext in n.get('url', '').lower() for ext in ['.css', '.woff', '.woff2', '.ttf', 'styles'])
                            and n.get('status', 200) >= 400
                        ]
                        if critical_failures:
                            status = "fail"
                            err_items = [f"{n['url'].split('/')[-1].split('?')[0]} (HTTP {n['status']})" for n in critical_failures[:4]]
                            note = f"FAIL: {len(critical_failures)} critical asset(s) failed to load: {', '.join(err_items)}"
                            log_cb("error", note)
                        else:
                            status = "pass"
                            note = "Tech-Audit OK: All stylesheets, web fonts, and core assets loaded successfully"
                            log_cb("ok", note)

                        step_results.append({"seq":s,"status":status,"note":note,"durationMs":int((time.time()-t0)*1000)})
                        screenshot = capture_screenshot(f"step-{s}")
                        if screenshot: step_results[-1]["screenshot"] = screenshot

                    elif action in ("verify_no_broken_images", "verify_images", "verify_media_health"):
                        broken_images_data = page.evaluate(r"""() => {
                            const imgs = Array.from(document.querySelectorAll('img')).filter(img => img.offsetParent !== null);
                            const broken = [];
                            for (const img of imgs) {
                                if (!img.complete || (img.naturalWidth === 0 && img.naturalHeight === 0)) {
                                    const src = img.src || img.getAttribute('data-src') || img.getAttribute('data-lazy-src') || 'unknown';
                                    if (src && !src.startsWith('data:image/svg') && !src.includes('placeholder')) {
                                        broken.push(src);
                                    }
                                }
                            }
                            return {
                                total: imgs.length,
                                brokenCount: broken.length,
                                broken: broken.slice(0, 4)
                            };
                        }""")
                        if broken_images_data.get('brokenCount', 0) > 0:
                            status = "fail"
                            note = f"FAIL: {broken_images_data['brokenCount']} broken image(s) detected: {', '.join(broken_images_data['broken'])}"
                            log_cb("error", note)
                        else:
                            status = "pass"
                            note = f"Media Health OK: All {broken_images_data.get('total', 0)} visible images loaded successfully"
                            log_cb("ok", note)

                        step_results.append({"seq":s,"status":status,"note":note,"durationMs":int((time.time()-t0)*1000)})
                        screenshot = capture_screenshot(f"step-{s}")
                        if screenshot: step_results[-1]["screenshot"] = screenshot

                    elif action in ("verify_no_horizontal_overflow", "verify_layout_alignment", "verify_no_overflow"):
                        overflow_data = page.evaluate(r"""() => {
                            const docWidth = document.documentElement.scrollWidth;
                            const winWidth = window.innerWidth;
                            const diff = docWidth - winWidth;
                            return {
                                docWidth: docWidth,
                                winWidth: winWidth,
                                hasOverflow: diff > 15,
                                diff: diff
                            };
                        }""")
                        if overflow_data.get('hasOverflow'):
                            status = "fail"
                            note = f"FAIL: Horizontal layout overflow detected ({overflow_data['diff']}px wider than viewport). UI layout spilling/broken."
                            log_cb("error", note)
                        else:
                            status = "pass"
                            note = f"Layout Alignment OK: Zero horizontal overflow (Document: {overflow_data.get('docWidth')}px, Viewport: {overflow_data.get('winWidth')}px)"
                            log_cb("ok", note)

                        step_results.append({"seq":s,"status":status,"note":note,"durationMs":int((time.time()-t0)*1000)})
                        screenshot = capture_screenshot(f"step-{s}")
                        if screenshot: step_results[-1]["screenshot"] = screenshot

                    elif action == "getText":
                        text = page.inner_text(target) if target else page.inner_text("body")
                        step_results.append({"seq":s,"status":"pass","note":f"Got text","durationMs":int((time.time()-t0)*1000)})
                        screenshot = capture_screenshot(f"step-{s}")
                        if screenshot:
                            step_results[-1]["screenshot"] = screenshot

                    elif action == "getAttribute":
                        attr = step.get("value","")
                        val = page.get_attribute(target, attr) if attr else ""
                        step_results.append({"seq":s,"status":"pass","note":f"Got attr {attr}","durationMs":int((time.time()-t0)*1000)})
                        screenshot = capture_screenshot(f"step-{s}")
                        if screenshot:
                            step_results[-1]["screenshot"] = screenshot

                    elif action == "scroll":
                        amount = step.get("value", "down 500")
                        direction = "down"
                        pixels = 500
                        if isinstance(amount, str) and len(amount.split()) >= 2:
                            parts = amount.split()
                            direction = parts[0].lower()
                            try: pixels = int(parts[1])
                            except Exception:
                                pass
                        elif isinstance(amount, (int, float)):
                            pixels = abs(int(amount))
                            direction = "down" if float(amount) > 0 else "up"
                        delta_y = pixels if direction in ("down", "bottom", "d") else -pixels
                        page_title = page.title()
                        try:
                            val = page.evaluate("document.body?.innerText?.length || 0")
                            page_body_len = val if val is not None else 0
                        except Exception:
                            page_body_len = 0
                        if page_body_len < 20 and ("522" in page_title or "error" in page_title.lower()):
                            step_results.append({"seq":s,"status":"fail","note":f"Cannot scroll — page not loaded (title: {page_title})","durationMs":int((time.time()-t0)*1000)})
                            screenshot = capture_screenshot(f"step-{s}")
                            if screenshot: step_results[-1]["screenshot"] = screenshot
                            log_cb("error", f"Step {s}: scroll blocked — page didn't load ({page_title})")
                        else:
                            page.evaluate(f"window.scrollBy(0, {delta_y})")
                            step_results.append({"seq":s,"status":"pass","note":f"Scrolled {direction} {pixels}px","durationMs":int((time.time()-t0)*1000)})
                            screenshot = capture_screenshot(f"step-{s}")
                            if screenshot: step_results[-1]["screenshot"] = screenshot
                            log_cb("ok", f"Scrolled {direction} {pixels}px")

                    else:
                        # Enhanced AI Logic: Provide DOM context for better accuracy
                        # Initialize AI response variable to prevent UnboundLocalError
                        ai = "FAIL: AI not reached"
                        try:
                            page_content = page.content()[:5000] # Get first 5k chars of HTML to avoid token limit
                            prompt = (
                                f"You are a QA automation agent. Current URL: {page.url}\n"
                                f"HTML Context: {page_content}\n"
                                f"Step to execute: {action} {desc}\n"
                                f"Target: {target}\n"
                                f"Expected: {verify}\n\n"
                                "Analyze the HTML and respond with:\n"
                                "DONE: [brief reason] if the step is possible and successful\n"
                                "FAIL: [reason] if it fails\n"
                                "SKIP: [reason] if not applicable\n"
                            )
                            ai = call_ai(prompt, timeout=60)
                            if not ai:
                                ai = f"FAIL: No AI response"
                        except Exception as e: 
                            ai = f"FAIL: Ollama error: {str(e)}"
                        
                        # Process AI response (ai is guaranteed to be a string here)
                        if ai.startswith("DONE:"):
                            step_results.append({"seq":s,"status":"pass","note":ai,"durationMs":int((time.time()-t0)*1000)})
                            screenshot = capture_screenshot(f"step-{s}")
                            if screenshot:
                                step_results[-1]["screenshot"] = screenshot
                        elif ai.startswith("SKIP:"):
                            step_results.append({"seq":s,"status":"pass","note":ai,"durationMs":int((time.time()-t0)*1000)})
                            screenshot = capture_screenshot(f"step-{s}")
                            if screenshot:
                                step_results[-1]["screenshot"] = screenshot
                        else:
                            step_results.append({"seq":s,"status":"fail","note":ai,"durationMs":int((time.time()-t0)*1000)})
                            screenshot = capture_screenshot(f"step-{s}")
                            if screenshot:
                                step_results[-1]["screenshot"] = screenshot

                except Exception as e:
                    step_results.append({"seq":s,"status":"fail","note":str(e),"durationMs":int((time.time()-t0)*1000)})
                    log_cb("error", f"Step {s} error: {e}")

            browser.close()

            # Enforce Visual/CSS Integrity: Check if critical stylesheets failed in network_logs
            critical_css_errors = [
                l for l in network_logs
                if ('.css' in l.get('url', '').lower() or 'stylesheet' in l.get('url', '').lower())
                and l.get('status', 200) in (403, 404, 500, 502, 503)
            ]
            if critical_css_errors:
                first_css_err = critical_css_errors[0]
                fail_msg = f"CRITICAL UI FAILURE: Stylesheet '{first_css_err['url']}' failed with HTTP {first_css_err['status']}! Site UI is unstyled/broken."
                step_results.append({
                    "seq": len(step_results) + 1,
                    "status": "fail",
                    "note": fail_msg,
                    "durationMs": 0
                })
                log_cb("error", fail_msg)

            passed = sum(1 for s in step_results if s["status"]=="pass")
            adapted = sum(1 for s in step_results if s["status"]=="adapted")
            failed = sum(1 for s in step_results if s["status"]=="fail")
            blocked = sum(1 for s in step_results if s["status"]=="blocked")
            cancelled = any("cancelled" in s.get("note","").lower() for s in step_results)
            overall = "fail" if cancelled else ("fail" if failed>0 else ("blocked" if blocked>0 else "pass"))
            summary = f"{passed} passed, {adapted} adapted, {failed} failed, {blocked} blocked / {len(step_results)} total"
            log_cb("info", f"Result: {overall.upper()} ({summary})")
            return {"status":overall,"steps":step_results,"passed":passed,"adapted":adapted,"failed":failed,"blocked":blocked,"summary":summary,"screenshots":screenshots,"healed":healed_steps, "mode": mode, "consoleLogs": console_logs, "networkLogs": network_logs, "totalTokens": _token_total[0]}

    except Exception as e:
        log_cb("error", f"Critical: {e}")
        return {"status":"fail","steps":step_results,"passed":0,"adapted":0,"failed":1,"blocked":0,"summary":f"Error: {e}","screenshots":screenshots,"healed":[], "mode": mode, "consoleLogs": console_logs, "networkLogs": network_logs, "totalTokens": _token_total[0]}

def build_report_markdown(tc_name, steps, passed, adapted, failed, blocked, dur, logs_list, created_at=None, mode="standard", device="desktop"):
    process_log = "\n".join(l.get("message","") for l in logs_list)
    tool_calls = sum(1 for l in logs_list if l.get("level") in ("info","step","ok","error"))
    steps_md = ""
    for s in (steps or []):
        icon = "PASS" if s.get("status")=="pass" else "ADAPTED" if s.get("status")=="adapted" else "FAIL" if s.get("status")=="fail" else "BLOCKED"
        steps_md += f"- {icon} **{s.get('status','blocked').upper()}** — {s.get('note','')}  \n"
    dt = (created_at or now_iso())[:19].replace("T"," ")
    mode_label = mode.capitalize()
    dev_label = "Mobile (iPhone)" if device == "mobile" else "Desktop"
    return (
        f"# AI Browser Test: {tc_name} [{dev_label} / {mode_label}]  \n\n"
        f"| Field | Value |\n| --- | --- |\n"
        f"| Date | {dt} |\n"
        f"| Mode | {mode_label} |\n"
        f"| Device | {dev_label} |\n"
        f"| Duration | {dur/1000:.1f}s |\n"
        f"| Tools | {tool_calls} |\n"
        f"| Passed | {passed} |\n"
        f"| Failed | {failed} |\n"
        f"| Blocked | {blocked} |\n\n"
        f"### Results  \n{steps_md}\n---\n"
        f"### AI Process Log  \n```\n{process_log}\n```"
    )

def run_test_thread(tc_id, run_id, mode="standard", device="desktop"):
    tc = None
    for t in safe_all(test_cases_table):
        if t.get("id")==tc_id or t.get("_id")==tc_id: tc = t; break
    if not tc:
        active_runs[run_id]["status"]="error"; emit_stream(run_id,"error","Test case not found"); return

    project = None
    for p in safe_all(projects_table):
        if p.get("id")==tc.get("projectId") or p.get("_id")==tc.get("projectId"): project=p; break
    base_url = project.get("url","http://localhost") if project else "http://localhost"

    step_idx = [0]
    def log_cb(level, msg):
        active_runs[run_id]["logs"].append({"time":now_iso(),"level":level,"message":msg})
        if level == "step":
            step_idx[0] += 1
            active_runs[run_id]["currentStep"]=step_idx[0]
            emit_stream(run_id, "step", json.dumps({"step": step_idx[0], "status": "running", "note": msg}))
        elif level == "ok":
            emit_stream(run_id, "step", json.dumps({"step": step_idx[0], "status": "pass", "note": msg}))
        elif level in ("error", "fail"):
            emit_stream(run_id, "step", json.dumps({"step": step_idx[0], "status": "fail", "note": msg}))
        elif level == "adapted":
            emit_stream(run_id, "step", json.dumps({"step": step_idx[0], "status": "adapted", "note": msg}))
        else:
            emit_stream(run_id, "log", json.dumps({"level": level, "text": msg}))

    active_runs[run_id]["status"]="running"; active_runs[run_id]["started_at"]=now_iso()
    active_runs[run_id]["totalSteps"]=len(tc.get("steps",[]))
    active_runs[run_id]["currentStep"]=0
    save_active_state()
    
    t0 = time.time()
    result = run_test_case_with_ai(tc, base_url, run_id, log_cb, mode, device)
    dur = int((time.time()-t0)*1000)

    # Phase 1: Auto-Healing Logic
    healed = result.get("healed", [])
    if healed:
        log_cb("info", f"AUTO-HEALING: Found improvements for {len(healed)} steps")
        updated_steps = list(tc.get("steps", []))
        for h in healed:
            idx = h["index"]
            if idx < len(updated_steps):
                updated_steps[idx]["target"] = h["new"]
                log_cb("info", f"  - Step {idx+1}: Updated selector to '{h['new']}'")
        
        safe_update(test_cases_table, record_id_cond(tc_id), {"steps": updated_steps, "updatedAt": now_iso()})
        log_cb("info", "TEST CASE HEALED AND SAVED SUCCESSFULLY")

    # Final sync of steps for the UI (ensure all icons are updated)
    for i, s in enumerate(result.get("steps", [])):
        emit_stream(run_id, "step", json.dumps({
            "step": i + 1,
            "status": s["status"],
            "note": s.get("note", "")
        }))

    # Priority 1: Check for critical technical failures
    c_logs = result.get("consoleLogs", [])
    n_logs = result.get("networkLogs", [])
    final_status = result["status"]
    tech_fail_reason = ""
    
    # Check for critical technical & stylesheet failures
    js_errors = [l.get("text") for l in c_logs if l.get("type") == "error"]
    net_errors = []
    critical_css_errors = []
    for l in n_logs:
        status = l.get("status", 0)
        url = l.get("url", "").lower()
        if status >= 400:
            # Ignore non-critical resources
            if any(k in url for k in ("favicon", "google-analytics", "doubleclick", "pixel", "/ads/")):
                net_errors.append(f"Minor: {l.get('method')} {status} {l.get('url')}")
                continue
            net_errors.append(f"Critical: {l.get('method')} {status} {l.get('url')}")
            if ('.css' in url or 'stylesheet' in url or 'style' in url) and status in (403, 404, 500, 502, 503):
                critical_css_errors.append(f"{l.get('url')} (HTTP {status})")

    # If critical stylesheet failed, enforce final_status = fail!
    if critical_css_errors:
        final_status = "fail"
        result["failed"] = max(1, result.get("failed", 0))
        tech_fail_reason = f"CRITICAL UI FAILURE: Stylesheet failed to load ({critical_css_errors[0]}). Website UI is unstyled/broken!"
        log_cb("error", tech_fail_reason)
    elif final_status == "pass" and (js_errors or net_errors):
        tech_fail_reason = f"Tech Warning: {len(js_errors)} JS error(s) and {len(net_errors)} network failure(s) detected (Functional steps passed)."
        log_cb("warning", tech_fail_reason)
        for err in js_errors:
            log_cb("info", f"  - JS Error: {err[:100]}")
        for err in net_errors:
            log_cb("info", f"  - Network: {err}")

    logs_list = active_runs[run_id]["logs"]
    process_log = "\n".join(l.get("message","") for l in logs_list)
    if tech_fail_reason:
        process_log += f"\n\n[WARNING] {tech_fail_reason}"
        
    tool_calls = sum(1 for l in logs_list if l.get("level") in ("info","step","ok","error"))
    
    current_summary = result["summary"]
    if final_status == "fail":
        if tech_fail_reason and "CRITICAL UI FAILURE" in tech_fail_reason:
            current_summary = f"FAIL ({tech_fail_reason}) | {current_summary}"
    elif tech_fail_reason:
        current_summary = f"PASS (with tech warnings: {tech_fail_reason}) | {current_summary}"

    report_md = build_report_markdown(
        tc.get("name","Untitled"), result.get("steps",[]),
        result["passed"], result["adapted"], result["failed"], result["blocked"],
        dur, logs_list, now_iso(), mode, device
    )
    result_data = {
        "_id": run_id, "id": run_id,
        "projectId": tc.get("projectId",""),
        "projectName": project.get("name","") if project else "",
        "testCaseId": tc_id,
        "testCaseName": tc.get("name","Untitled"),
        "status": final_status,
        "mode": mode,
        "device": device,
        "steps": result["steps"],
        "passed": result["passed"], "adapted": result["adapted"], "failed": result["failed"], "blocked": result["blocked"],
        "summary": current_summary,
        "runner": "ollama-browser",
        "duration": dur,
        "inputTokens": result.get("inputTokens", 0), "outputTokens": result.get("outputTokens", 0), "totalTokens": result.get("totalTokens", 0),
        "toolCalls": tool_calls,
        "processLog": process_log,
        "screenshots": result.get("screenshots", {}), "screenshotDir": "",
        "consoleLogs": c_logs,
        "networkLogs": n_logs,
        "createdAt": now_iso(), "executedAt": now_iso(),
        "rawMarkdown": report_md
    }
    active_runs[run_id]["status"]="completed"
    active_runs[run_id]["result"]=result_data
    active_runs[run_id]["completed_at"]=now_iso()
    active_runs[run_id]["duration"]=dur
    safe_insert(results_table, result_data)
    save_active_state(force=True)
    emit_stream(run_id,"complete",json.dumps({"status":final_status,"summary":current_summary,"runId":run_id,"resultId":run_id}))
    _cleanup_completed_runs()

def emit_stream(run_id, event, data):
    if run_id in run_streams:
        for q in list(run_streams[run_id].values()):
            q.put((event,data))

# ============ DASHBOARD ============
@app.route("/api/dashboard/stats")
def api_dashboard_stats_alias():
    return api_dashboard()

@app.route("/api/dashboard")
def api_dashboard():
    projects = safe_all(projects_table)
    tcs = safe_all(test_cases_table)
    results = safe_all(results_table)
    plans = list(TEST_PLANS_DIR.glob("*.md"))
    total_runs = len(results)
    passed = sum(1 for r in results if r.get("status")=="pass")
    failed = sum(1 for r in results if r.get("status")=="fail")
    blocked = sum(1 for r in results if r.get("status")=="blocked")
    recent = sorted(results, key=lambda r: r.get("createdAt",""), reverse=True)[:5]
    return ok({
        "total_projects": len(projects), "total_plans": len(plans),
        "total_test_cases": len(tcs), "total_results": total_runs,
        "total_passed": passed, "total_failed": failed, "total_blocked": blocked,
        "total_executed": total_runs,
        "pass_rate": round(passed/total_runs*100,1) if total_runs else 0,
        "recent_results": [{
            "filename": r.get("id","") or r.get("_id",""),
            "title": r.get("testCaseName",""),
            "passed": r.get("passed",0), "failed": r.get("failed",0),
            "blocked": r.get("blocked",0),
            "status": r.get("status",""),
            "date": (r.get("createdAt","") or "")[:16].replace("T"," ")
        } for r in recent]
    })

# ============ HEALTH ============
@app.route("/api/health")
def api_health():
    return ok({"status": "healthy", "version": "2.5", "db_ok": True})

# ============ PROJECTS ============
@app.route("/api/projects", methods=["GET"])
def api_list_projects():
    result = []
    for p in safe_all(projects_table):
        p_out = dict(p)
        pid = p.get("id") or p.get("_id","")
        tcs = [t for t in safe_all(test_cases_table) if t.get("projectId")==pid]
        ress = [r for r in safe_all(results_table) if r.get("projectId")==pid]
        p_out["testCaseCount"] = len(tcs)
        p_out["resultCount"] = len(ress)
        if ress:
            p_out["lastRun"] = max(r.get("createdAt","") for r in ress)
            recent10 = sorted(ress, key=lambda r: r.get("createdAt",""), reverse=True)[:10]
            p_out["recentPassed"] = sum(1 for r in recent10 if r.get("status")=="pass")
            p_out["recentFailed"] = sum(1 for r in recent10 if r.get("status")=="fail")
            p_out["recentBlocked"] = sum(1 for r in recent10 if r.get("status")=="blocked")
            p_out["recentStatuses"] = [r.get("status","") for r in recent10[:5]]
        result.append(p_out)
    return ok(result)

@app.route("/api/projects", methods=["POST"])
@require_json
def api_create_project():
    data = request.json
    pid = make_id()[:16]
    project = {
        "_id": pid, "id": pid,
        "name": data.get("name","Untitled"),
        "slug": data.get("slug","") or slugify(data.get("name","untitled")),
        "url": data.get("url","") or data.get("base_url",""),
        "platform": data.get("platform",""),
        "credentials": data.get("credentials",{}),
        "config": data.get("config",{}),
        "createdAt": now_iso(), "updatedAt": now_iso()
    }
    safe_insert(projects_table, project)
    return ok(project)

@app.route("/api/projects/<pid>", methods=["GET"])
def api_get_project(pid):
    for p in safe_all(projects_table):
        if p.get("id")==pid or p.get("_id")==pid: return ok(p)
    return err("Not found",404)

@app.route("/api/projects/<pid>", methods=["PUT"])
@require_json
def api_update_project(pid):
    for p in safe_all(projects_table):
        if p.get("id")==pid or p.get("_id")==pid:
            up = {}
            for k in ("name","url","platform","credentials","config","slug"):
                if k in request.json: up[k]=request.json[k]
            up["updatedAt"]=now_iso()
            safe_update(projects_table, record_id_cond(pid), up)
            for p2 in safe_all(projects_table):
                if p2.get("id")==pid or p2.get("_id")==pid: return ok(p2)
    return err("Not found",404)

@app.route("/api/projects/<pid>", methods=["DELETE"])
def api_delete_project(pid):
    with db_lock:
        projects_table.remove(record_id_cond(pid))
        test_cases_table.remove(Query().projectId==pid)
        results_table.remove(Query().projectId==pid)
    return ok({"status":"deleted"})

@app.route("/api/projects/<pid>/dashboard")
def api_project_dashboard(pid):
    tcs = [t for t in safe_all(test_cases_table) if t.get("projectId")==pid]
    ress = [r for r in safe_all(results_table) if r.get("projectId")==pid]
    passed = sum(1 for r in ress if r.get("status")=="pass")
    return ok({"total_test_cases":len(tcs),"total_runs":len(ress),"pass_rate":round(passed/len(ress)*100,1) if ress else 0})

@app.route("/api/projects/<pid>/analytics")
def api_project_analytics(pid):
    ress = sorted([r for r in safe_all(results_table) if r.get("projectId")==pid], key=lambda r: r.get("createdAt",""))
    passed = sum(1 for r in ress if r.get("status")=="pass")
    failed = sum(1 for r in ress if r.get("status")=="fail")
    blocked = sum(1 for r in ress if r.get("status")=="blocked")
    adapted = sum(1 for r in ress if r.get("status")=="adapted")
    avg_dur = int(sum(r.get("duration",0) for r in ress)/len(ress)) if ress else 0
    trend = [{"status":r.get("status",""),"duration":r.get("duration",0),"date":r.get("createdAt",""),"runner":r.get("runner","")} for r in ress[-20:]]
    return ok({"total":len(ress),"passed":passed,"failed":failed,"blocked":blocked,"adapted":adapted,
        "passRate":round(passed/len(ress)*100,1) if ress else 0,"avgDuration":avg_dur,"recentTrend":trend})

@app.route("/api/projects/<pid>/results", methods=["GET"])
def api_project_results(pid):
    ress = sorted([r for r in safe_all(results_table) if r.get("projectId")==pid], key=lambda r: r.get("createdAt",""), reverse=True)
    ress = ress[:parse_limit(default=50)]
    return ok([slim_result(r) for r in ress])

@app.route("/api/projects/<pid>/results", methods=["POST"])
@require_json
def api_save_project_result(pid):
    for p in safe_all(projects_table):
        if p.get("id") == pid or p.get("_id") == pid:
            data = dict(request.json)
            rid = make_id()[:16]
            data["_id"] = rid
            data["id"] = rid
            data["projectId"] = pid
            data["projectName"] = p.get("name", "")
            data.setdefault("createdAt", now_iso())
            safe_insert(results_table, data)
            return ok(data)
    return err("Project not found", 404)

# ============ TEST CASES ============
@app.route("/api/projects/<pid>/test-cases/reorder", methods=["PUT"])
@require_json
def api_reorder_test_cases(pid):
    ordered_ids = request.json.get("orderedIds", [])
    for i, tcid in enumerate(ordered_ids):
        with db_lock:
            test_cases_table.update({"sortOrder": i}, record_id_cond(tcid))
    return ok({"status": "reordered"})

@app.route("/api/projects/<pid>/test-cases", methods=["GET"])
def api_list_test_cases(pid):
    all_tcs = safe_all(test_cases_table)
    tcs = [t for t in all_tcs if t.get("projectId")==pid]
    tcs = sorted(tcs, key=lambda t: t.get("sortOrder",0))
    resp = ok(tcs)
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    return resp

@app.route("/api/projects/<pid>/test-cases", methods=["POST"])
@require_json
def api_create_test_case(pid):
    data = request.json
    # Validate that the project exists
    project_exists = any(p.get("id") == pid or p.get("_id") == pid for p in safe_all(projects_table))
    if not project_exists:
        return err("Project not found", 404)
    # Input validation
    name = data.get("name", "").strip() if data.get("name") else ""
    if not name:
        return err("Test case name is required", 400)
    if len(name) > 500:
        return err("Test case name too long (max 500 chars)", 400)
    steps_raw = data.get("steps", [])
    if isinstance(steps_raw, list) and len(steps_raw) > 100:
        return err("Too many steps (max 100)", 400)
    tcid = make_id()[:16]
    raw_steps = data.get("steps",[])
    if isinstance(raw_steps,str):
        try: raw_steps = json.loads(raw_steps)
        except Exception: raw_steps = []
    
    # Extension compatibility: Convert extension steps to internal format
    steps = []
    for i, s in enumerate(raw_steps):
        action = s.get("action","")
        # Handle "click" vs "click something"
        if " " in action and any(k in action for k in ("click","type","fill")):
            action = action.split(" ")[0]
            
        steps.append({
            "action": action,
            "target": s.get("target",""),
            "description": s.get("description") or f"{action} {s.get('target','')}",
            "seq": i+1,
            "value": s.get("value") or (s.get("action").split('"')[1] if '"' in s.get("action","") else None),
            "verify": s.get("expected") or s.get("verify") or "Action successful"
        })

    tc = {
        "_id": tcid, "id": tcid, "projectId": pid,
        "name": data.get("name","") or data.get("title","Untitled"),
        "category": data.get("category","positive"),
        "steps": steps,
        "source": data.get("source","manual"),
        "isRegression": data.get("isRegression",True),
        "sortOrder": data.get("sortOrder",0) or len([t for t in safe_all(test_cases_table) if t.get("projectId")==pid]),
        "createdAt": now_iso(), "updatedAt": now_iso()
    }
    safe_insert(test_cases_table, tc)
    return ok(tc)

@app.route("/api/test-cases/<tcid>", methods=["GET"])
def api_get_test_case(tcid):
    for t in safe_all(test_cases_table):
        if t.get("id")==tcid or t.get("_id")==tcid: return ok(t)
    return err("Not found",404)

@app.route("/api/test-cases/<tcid>", methods=["PUT"])
@require_json
def api_update_test_case(tcid):
    if "steps" in request.json and isinstance(request.json["steps"],str):
        try: request.json["steps"]=json.loads(request.json["steps"])
        except Exception: pass
    # Allowlist: only permit known safe fields to be updated
    ALLOWED_TC_UPDATE_FIELDS = {"name", "category", "steps", "source", "isRegression", "sortOrder", "description", "tags"}
    filtered = {k: v for k, v in request.json.items() if k in ALLOWED_TC_UPDATE_FIELDS}
    if not filtered:
        return err("No valid fields to update", 400)
    with db_lock:
        test_cases_table.update(filtered, record_id_cond(tcid))
    for t in safe_all(test_cases_table):
        if t.get("id")==tcid or t.get("_id")==tcid:
            with db_lock:
                test_cases_table.update({"updatedAt":now_iso()}, record_id_cond(tcid))
            t["updatedAt"]=now_iso()
            return ok(t)
    return err("Not found",404)

@app.route("/api/test-cases/<tcid>", methods=["DELETE"])
def api_delete_test_case(tcid):
    q = Query()
    with db_lock:
        matches_before = test_cases_table.search((q.id == tcid) | (q._id == tcid))
        if not matches_before:
            return err("Not found", 404)
        test_cases_table.remove((q.id == tcid) | (q._id == tcid))
    _invalidate_table_cache("test_cases")
    return ok({"status": "deleted", "removed_count": len(matches_before)})

@app.route("/api/test-cases/<tcid>/export")
def api_export_test_case(tcid):
    for t in safe_all(test_cases_table):
        if t.get("id")==tcid or t.get("_id")==tcid: return ok(t)
    return err("Not found",404)

# ============ AI TEST GENERATOR (ADVANCED DISCOVERY) ============
@app.route("/api/generate-tests/<pid>", methods=["POST"])
def api_generate_tests(pid):
    project = None
    for p in safe_all(projects_table):
        if p.get("id")==pid or p.get("_id")==pid:
            project = p
            break
    if not project: return err("Project not found", 404)
    if not project.get("url"): return err("Project URL is missing")
    sid = make_id()[:16]
    run_streams[sid] = {}
    thread = threading.Thread(target=_discovery_worker, args=(pid, project["url"], sid), daemon=True)
    thread.start()
    return ok({"streamId": sid})


def _parse_markdown_test_cases(text):
    """Fallback parser: convert Markdown-style AI output to a list of test case dicts.

    Handles formats like:
        **Test Case N: Title**
        **Name:** Foo
        **Category:** bar
        **Section:** baz
        Steps:
            1. **Action:** click
               **Target:** #id
               **Description:** desc
               **Verify:** verify
    """
    if not text:
        return None
    cases = []
    # Split on "Test Case" header markers
    blocks = re.split(r'^\s*\*\*Test\s*Case\s*[\d:]+\s*:\s*(.+?)\*\*\s*$', text, flags=re.MULTILINE)
    # re.split with a capturing group interleaves: [preamble, title, body, title, body, ...]
    if len(blocks) >= 3:
        for i in range(1, len(blocks), 2):
            title = blocks[i].strip()
            body = blocks[i + 1] if i + 1 < len(blocks) else ""
            cases.append(_parse_markdown_tc(title, body))
    else:
        # Single test case without explicit header
        cases.append(_parse_markdown_tc(None, text))
    cases = [c for c in cases if c.get("name")]
    return cases if cases else None


def _parse_markdown_tc(title, body):
    def field(text, name):
        m = re.search(rf'\*\*{name}:\*\*\s*([^\n*]+)', text, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    tc = {
        "name": title or field(body, "Name") or "Generated Test Case",
        "category": field(body, "Category") or "positive",
        "section": field(body, "Section") or "General",
        "steps": [],
    }
    # Slice the "Steps:" section if present, else use whole body
    steps_body = body
    m = re.search(r'Steps:\s*\n', body, re.IGNORECASE)
    if m:
        steps_body = body[m.end():]
    # Split on numbered steps like "1. **Action:** ..."
    step_parts = re.split(r'(?m)^\s*(\d+)\.\s+\*\*Action:\*\*\s*', steps_body)
    # step_parts = [preamble, num, text, num, text, ...]
    idx = 1
    while idx < len(step_parts):
        num = step_parts[idx]
        # text runs until the next numbered step OR next "**Test Case" OR end
        rest = step_parts[idx + 1] if idx + 1 < len(step_parts) else ""
        # truncate at the next numbered step start if re-split didn't already
        nxt = re.search(r'(?m)^\s*\d+\.\s+\*\*Action:\*\*', rest)
        if nxt:
            rest = rest[:nxt.start()]
        action_v = field(rest, "Action") or rest.strip().splitlines()[0] if rest.strip() else ""
        tc["steps"].append({
            "action": action_v.strip(),
            "target": field(rest, "Target"),
            "description": field(rest, "Description"),
            "verify": field(rest, "Verify") or field(rest, "Expected"),
        })
        idx += 2
    if not tc["steps"]:
        act = field(body, "Action")
        tc["steps"].append({
            "action": act,
            "target": field(body, "Target"),
            "description": field(body, "Description"),
            "verify": field(body, "Verify") or field(body, "Expected"),
        })
    return tc


def field_of(text, *names):
    for name in names:
        m = re.search(rf'\*\*{name}:\*\*\s*([^\n*]+)', text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def selector_exists(page, target):
    """Check if a CSS/XPath/text selector matches any element on the page."""
    if not target or target.startswith('$BASE_URL'):
        return True
    # For text= selectors, use Playwright locator to check visibility
    if target.startswith('text='):
        try:
            count = page.locator(target).count()
            if count == 0:
                return False
            # Check if at least one matching element is visible
            for i in range(min(count, 3)):
                try:
                    if page.locator(target).nth(i).is_visible(timeout=1000):
                        return True
                except:
                    pass
            return False
        except:
            return False
    if target.startswith('css='): target = target[4:]
    if target.startswith('xpath='):
        try:
            return page.evaluate(
                'function(expr){const r=document.evaluate(expr,document,null,XPathResult.FIRST_ORDERED_NODE_TYPE,null);return !!r.singleNodeValue;}',
                target[6:])
        except: return False
    try:
        return page.evaluate('function(s){return !!document.querySelector(s);}', target)
    except: return False


def _find_selector_by_text(page, text, action='', description=''):
    """Find a real CSS selector by matching visible text on the page."""
    if not text or text.startswith('$BASE_URL') or text.startswith('http'):
        return None
    text_lower = text.lower().strip()
    candidates = [f'text={text}', f'text={text_lower}']
    if action == 'fill':
        candidates.extend([
            f"input[placeholder*='{text}' i]", f"input[name*='{text_lower}' i]",
            f"input[aria-label*='{text}' i]", f'#{text_lower}', f"#{text_lower.replace(' ', '-')}",
        ])
        try:
            found = page.evaluate('''(text) => {
                const labels = document.querySelectorAll('label, h1, h2, h3, h4, h5, h6, span, div');
                for (const el of labels) {
                    if (el.textContent.trim().toLowerCase() === text.toLowerCase()) {
                        if (el.htmlFor) { const inp = document.getElementById(el.htmlFor); if (inp) return '#' + inp.id; }
                        const inp = el.querySelector('input, select, textarea');
                        if (inp) { if (inp.id) return '#' + inp.id; if (inp.name) return inp.tagName.toLowerCase() + '[name="' + inp.name + '"]'; }
                        const next = el.nextElementSibling;
                        if (next && ['INPUT','SELECT','TEXTAREA'].includes(next.tagName)) {
                            if (next.id) return '#' + next.id;
                            if (next.name) return next.tagName.toLowerCase() + '[name="' + next.name + '"]';
                        }
                    }
                }
                return null;
            }''', text)
            if found: candidates.insert(0, found)
        except: pass
    if action == 'click':
        candidates.extend([
            f"a:text-is('{text}')", f"button:text-is('{text}')",
            f"[role='button']:text-is('{text}')",
            f"a >> text='{text}'", f"button >> text='{text}'",
        ])
    for cand in candidates:
        if selector_exists(page, cand):
            return cand
    try:
        found = page.evaluate(r'''(text) => {
            const t = text.toLowerCase();
            const els = document.querySelectorAll('a, button, [role="button"], input[type="submit"], input[type="button"]');
            for (const el of els) {
                const et = (el.innerText || el.value || el.placeholder || el.title || '').trim().toLowerCase();
                if (et === t || et.includes(t)) {
                    if (el.id) return '#' + el.id;
                    if (el.name) return el.tagName.toLowerCase() + '[name="' + el.name + '"]';
                    if (el.href) { try { const p = new URL(el.href, location.href).pathname; if (p && p !== '/') return 'a[href="' + p + '"]'; } catch(e) {} }
                    let s = el.tagName.toLowerCase();
                    if (el.className && typeof el.className === 'string') {
                        const c = el.className.trim().split(/\s+/).filter(c => c && c.length < 30).slice(0,2);
                        if (c.length) s += '.' + c.join('.');
                    }
                    return s;
                }
            }
            const labels = document.querySelectorAll('label');
            for (const l of labels) {
                const lt = l.textContent.trim().toLowerCase();
                if (lt.includes(t) || t.includes(lt)) {
                    if (l.htmlFor) { const inp = document.getElementById(l.htmlFor); if (inp) return '#' + inp.id; }
                    const inp = l.querySelector('input, select, textarea');
                    if (inp && inp.id) return '#' + inp.id;
                }
            }
            return null;
        }''', text)
        if found: return found
    except Exception:
        pass
    return None


def _find_working_selector(page, target, description="", log_cb=None):
    """Find a working CSS/text selector for target, trying fallbacks. Module-level version.
    Used by _discovery_worker (previously was a nested duplicate)."""
    def _log(msg):
        if log_cb:
            log_cb("info", msg)
        else:
            print(f"[selector] {msg}", flush=True)

    if not target or target.startswith("http") or target == "$BASE_URL" or target.startswith("text="):
        return target, True
    if selector_exists(page, target):
        return target, True
    tag = None; id_part = None; class_part = None
    if target.startswith('#'):
        id_part = target[1:].split('.')[0].split('[')[0]
        tag = 'a' if id_part else None
    elif '.' in target and not target.startswith('['):
        parts = target.split('.')
        tag = parts[0] if parts[0].isalpha() else None
        class_part = parts[1].split('[')[0] if len(parts) > 1 else None
    elif '[' in target:
        m = re.match(r'([a-zA-Z]+)\[', target)
        if m: tag = m.group(1)
    else:
        tag = target if target.isalpha() else None
    candidates = []
    if id_part:
        candidates.extend([f"#{id_part}", f"[id='{id_part}']"])
        if tag: candidates.append(f"{tag}#{id_part}")
    if class_part and tag:
        candidates.extend([f"{tag}.{class_part}", f".{class_part}"])
    elif class_part:
        candidates.append(f".{class_part}")
    if description:
        desc_lower = description.lower()
        if any(kw in desc_lower for kw in ['fill', 'type', 'enter', 'input', 'email', 'password', 'username', 'name']):
            for word in ['email', 'password', 'username', 'name', 'phone', 'address', 'card', 'country', 'month', 'year', 'search']:
                if word in desc_lower:
                    candidates.extend([f"input[placeholder*='{word}' i]", f"input[name*='{word}' i]", f"#{word}"])
        skip_words = {'the', 'a', 'an', 'to', 'on', 'in', 'of', 'and', 'or', 'is', 'at', 'by', 'for', 'with', 'from', 'click', 'fill', 'verify', 'page', 'field', 'button'}
        desc_words = [w for w in description.split() if len(w) > 3 and w.lower() not in skip_words]
        for word in desc_words[:2]:
            candidates.append(f"text={word}")
    if tag:
        role_map = {'button': 'button', 'input': 'textbox', 'select': 'combobox', 'textarea': 'textbox'}
        if tag in role_map:
            candidates.append(f"[role='{role_map[tag]}']")
    if description:
        for word in description.split():
            if len(word) > 4 and word.lower() not in {'click', 'fill', 'verify', 'the', 'and', 'page'}:
                candidates.append(f"[aria-label*='{word}' i]")
                candidates.append(f"[title*='{word}' i]")
    for cand in candidates:
        if selector_exists(page, cand):
            _log(f"Selector fixed: {target} -> {cand}")
            return cand, True
    _log(f"Selector not found: {target}")
    return target, False



def _build_ecommerce_test_cases(site_map, base_url, log_cb=None):
    """Build comprehensive e-commerce test cases dynamically for ANY storefront
    (Shopify, WooCommerce, Magento, BigCommerce, Custom Next.js/React).
    Uses ONLY crawled data and multi-platform selector fallbacks.
    """
    def _log(msg):
        if log_cb: log_cb("info", msg)
    def _nav(url, desc):
        return {"action": "navigate", "target": url, "description": desc, "verify": "Page loaded"}
    def _scroll(desc="Scroll down page", px=500):
        return {"action": "scroll", "target": "page", "value": f"down {px}", "description": desc, "verify": "Scrolled"}
    def _verify(target, desc, verify="Element visible"):
        return {"action": "verify", "target": target, "description": desc, "verify": verify}
    def _fill(target, value, desc, verify="Field filled"):
        return {"action": "fill", "target": target, "value": value, "description": desc, "verify": verify}

    b = base_url.rstrip('/')
    cats = site_map.get('categories', [])
    # Filter out homepage or empty URLs
    base_paths = {b, b + '/', b + '/default', b + '/default/'}
    cats = [c for c in cats if c.get('url', '').rstrip('/') not in base_paths and c.get('text', '').strip()]
    products = site_map.get('products', [])
    search_info = site_map.get('search')
    cart_url = site_map.get('cart_url') or f"{b}/cart"
    checkout_url = site_map.get('checkout_url') or f"{b}/checkout"
    login_url = site_map.get('login_url')
    register_url = site_map.get('register_url')
    footer_links = site_map.get('footer_links', [])
    search_sel = (search_info.get('selector') if search_info else None) or "input[type='search'], input[name='q'], input[name='s'], input[placeholder*='search' i], #search"
    search_action = search_info.get('action_url') if search_info else None

    # Universal cross-platform selectors
    SEL_PAGE_TITLE = "h1, .page-title, [class*='title'], main"
    SEL_PRODUCTS_GRID = ".products, .product-grid, .grid-products, [class*='product-grid'], [class*='products'], [class*='product-list'], [class*='collection'], [class*='catalog'], main"
    SEL_PRODUCT_CARD = ".product-item, .product-card, [class*='product-item'], [class*='product-card'], li.product, [data-product-id], article, [class*='product']"
    SEL_SORT_FILTER = "select#sorter, .toolbar-sorter, .woocommerce-ordering, [class*='sort'], select[name*='sort' i], [class*='filter'], .sorter, select"
    SEL_PAGINATION = ".pages, .pagination, [class*='pager'], nav[aria-label*='page' i], [class*='pagination' i], .toolbar-bottom"
    SEL_PDP_TITLE = "h1, .product-title, [class*='product-name'], [itemprop='name'], .title"
    SEL_PDP_PRICE = "span.price, .price, [class*='price'], [itemprop='price'], .amount, [data-price]"
    SEL_ADD_TO_CART = "button[id*='cart' i], button[name='add'], button[title*='Add' i], [class*='add-to-cart' i], [class*='addtocart' i], form[action*='cart'] button, button.single_add_to_cart_button, #product-addtocart-button, [data-action='add-to-cart']"
    SEL_PDP_GALLERY = ".product-gallery, [class*='gallery' i], [class*='product-image' i], [class*='featured-image'], img"
    SEL_PDP_DESC = ".description, [class*='description' i], [itemprop='description'], .product-info, main"
    SEL_CART_EMPTY = ".cart-empty, [class*='cart-empty'], [class*='empty-cart'], .cart__empty-text, [class*='cart'] p, [class*='empty'], main"
    SEL_CART_HEADER = "[id*='cart' i], [aria-label*='cart' i], header [href*='cart'], nav [href*='cart'], a[href*='cart'], a[href*='basket'], a[href*='bag'], [class*='cart']"
    SEL_CHECKOUT_PAGE = ".cart-empty, [class*='checkout' i], form, main, #checkout"
    SEL_LOGIN_FORM = "form[action*='login'], form[id*='login' i], form.woocommerce-form-login, #customer-login-form, form"
    SEL_LOGIN_USER = "input[type='email'], input[name*='email' i], input[name*='login' i], input[name*='user' i], #form-login-username, #customer_email, #username"
    SEL_LOGIN_PASS = "input[type='password'], #form-login-password, #customer_password, #password"
    SEL_LOGIN_SUBMIT = "form[action*='login'] button, form button[type='submit'], button[type='submit'], input[type='submit'], button.action.login, button:has-text('Sign In'), button:has-text('Log in')"
    SEL_LOGIN_VALIDATION = "input:invalid, .mage-error, [class*='error' i], [class*='invalid' i], [role='alert'], .message"
    SEL_REG_FIRST = "input[name*='first' i], input#firstname, input[name='name'], input[type='text']"
    SEL_REG_EMAIL = "input[type='email']"
    SEL_REG_PASS = "input[type='password']"
    SEL_REG_SUBMIT = "form button[type='submit'], button[type='submit'], input[type='submit'], button.action.submit"
    SEL_NEWSLETTER = "input[name*='newsletter' i], input[id*='newsletter' i], form[action*='newsletter' i] input, form[action*='subscribe' i] input, #newsletter-subscribe, #newsletter, input[type='email']"

    tests = []

    # ── 0. UI, VISUAL INTEGRITY & TECH-AUDIT ─────────────────────────────────
    _log("Building: UI, Visual Integrity & Tech-Audit tests")
    tests.append({"name": "UI & Visual Integrity - Stylesheet & Layout Health Audit", "category": "tech_audit", "steps": [
        _nav(b + '/', "Navigate to homepage"),
        {"action": "verify_visual_health", "target": "body", "description": "Verify external stylesheets loaded with HTTP 200 and active CSS rules", "verify": "Active stylesheets"},
        _verify("header, [role='banner'], nav", "Verify header container renders with layout styling", "Header styled and visible"),
    ]})
    tests.append({"name": "Tech-Audit - Network & Critical Asset Health", "category": "tech_audit", "steps": [
        _nav(b + '/', "Navigate to homepage"),
        {"action": "verify_network_assets", "target": "critical", "description": "Verify no 4xx/5xx HTTP errors on stylesheets, web fonts or core assets", "verify": "No critical asset errors"},
    ]})
    tests.append({"name": "UI & Media - Broken Images & Media Asset Audit", "category": "tech_audit", "steps": [
        _nav(b + '/', "Navigate to homepage"),
        {"action": "verify_no_broken_images", "target": "img", "description": "Verify all visible images and product thumbnails load with valid natural dimensions", "verify": "Zero broken images"},
    ]})
    tests.append({"name": "UI & Layout - Responsive Viewport & Horizontal Overflow Audit", "category": "tech_audit", "steps": [
        _nav(b + '/', "Navigate to homepage"),
        {"action": "verify_no_horizontal_overflow", "target": "body", "description": "Verify viewport layout alignment has zero horizontal overflow or spilling", "verify": "Zero horizontal overflow"},
    ]})

    # ── 1. HOMEPAGE & HEADER ─────────────────────────────────────────────────
    _log("Building: Homepage & Header tests")
    tests.append({"name": "Homepage - Page Load & Content Verification", "category": "positive", "steps": [
        _nav(b + '/', "Navigate to homepage"),
        {"action": "verify_visual_health", "target": "body", "description": "Verify page stylesheets loaded with active CSS rules", "verify": "CSS rules loaded"},
        _verify(SEL_PAGE_TITLE, "Verify page has a main heading (h1)", "Homepage heading visible"),
        _scroll("Scroll to see more homepage content", 400),
        _verify("section, main, article, div", "Verify page has content sections", "Homepage content sections present"),
    ]})
    tests.append({"name": "Homepage - Navigation Menu Links Present", "category": "positive", "steps": [
        _nav(b + '/', "Navigate to homepage"),
        _verify("nav, header nav, [role='navigation'], header", "Verify main navigation menu is present", "Navigation menu visible"),
        _verify("header a, nav a", "Verify header contains navigation links", "Header links present"),
    ]})
    tests.append({"name": "Homepage - Hero Banner & Featured Products", "category": "positive", "steps": [
        _nav(b + '/', "Navigate to homepage"),
        _verify("header", "Verify header section exists", "Header visible"),
        _scroll("Scroll to hero/banner area", 300),
        _verify("main, section, [class*='hero'], [class*='banner']", "Verify main content sections render", "Main content sections visible"),
    ]})
    first_nav_target = cats[0]['url'] if cats else (products[0]['url'] if products else b + '/')
    tests.append({"name": "Homepage - Brand Logo Return-to-Home Navigation", "category": "positive", "steps": [
        _nav(first_nav_target, "Navigate to subpage"),
        {"action": "click", "target": "a.logo, a[href='/'], [class*='logo'] a, header a[href*='/']:first-of-type, [aria-label*='logo' i]", "description": "Click brand logo in header", "verify": "Logo clicked"},
        _verify(SEL_PAGE_TITLE, "Verify returned to homepage with main heading", "Homepage heading visible"),
    ]})

    # ── 2. CATEGORY NAVIGATION ───────────────────────────────────────────────
    if cats:
        _log(f"Building: Category Navigation tests ({min(len(cats), 8)} categories)")
        for cat in cats[:8]:
            tests.append({"name": f"Category Navigation - {cat['text']}", "category": "positive", "steps": [
                _nav(cat['url'], f"Navigate directly to {cat['text']} category page"),
                _verify(SEL_PAGE_TITLE, f"Verify {cat['text']} page heading visible", "Category page heading shown"),
                _verify(SEL_PRODUCTS_GRID, "Verify product listing container present", "Product listing present on category page"),
            ]})

    # ── 3. PRODUCT LISTING PAGE CONTROLS ─────────────────────────────────────
    _log("Building: Product Listing Page tests")
    first_listing = cats[0]['url'] if cats else (b + '/collections/all' if 'shopify' in b else b + '/shop')
    first_cat_name = cats[0]['text'] if cats else "Catalog"
    tests.append({"name": f"Product Listing - Sort & Filter Controls ({first_cat_name})", "category": "positive", "steps": [
        _nav(first_listing, f"Open {first_cat_name} product listing page"),
        _verify(SEL_PRODUCT_CARD, "Verify individual product cards visible", "Product items visible in grid"),
        _verify(SEL_SORT_FILTER, "Verify product sort toolbar/filter present", "Sort control visible"),
    ]})
    tests.append({"name": f"Product Listing - Pagination ({first_cat_name})", "category": "positive", "steps": [
        _nav(first_listing, f"Open {first_cat_name} product listing page"),
        _scroll("Scroll to bottom for pagination", 800),
        _verify(SEL_PAGINATION, "Verify pagination control exists", "Pagination visible"),
    ]})

    # ── 4. PRODUCT DETAIL PAGE (PDP) ─────────────────────────────────────────
    _log("Building: Product Detail Page tests")
    if products:
        prod = products[0]
        tests.append({"name": f"Product Detail - Page Load & Title ({prod['name'][:40]})", "category": "positive", "steps": [
            _nav(prod['url'], f"Navigate to product: {prod['name'][:40]}"),
            _verify(SEL_PDP_TITLE, "Verify product title (h1) is visible", "Product title shown"),
            _verify(SEL_PDP_PRICE, "Verify product price is displayed", "Product price visible"),
        ]})
        tests.append({"name": "Product Detail - Add to Cart Button", "category": "positive", "steps": [
            _nav(prod['url'], f"Navigate to product: {prod['name'][:40]}"),
            _verify(SEL_ADD_TO_CART, "Verify Add to Cart button present", "Add to Cart button visible"),
        ]})
        tests.append({"name": "Product Detail - Gallery & Description", "category": "positive", "steps": [
            _nav(prod['url'], f"Navigate to product: {prod['name'][:40]}"),
            _verify(SEL_PDP_GALLERY, "Verify product images present", "Product images present"),
            _scroll("Scroll to product description", 400),
            _verify(SEL_PDP_DESC, "Verify product description section", "Description section visible"),
        ]})
        tests.append({"name": "Product Detail - Availability & In-Stock Status", "category": "positive", "steps": [
            _nav(prod['url'], f"Navigate to product: {prod['name'][:40]}"),
            _verify("[class*='stock' i], [itemprop='availability'], .availability, .in-stock, [class*='inventory' i], main", "Verify product availability indicator visible", "Availability indicator visible"),
        ]})
        tests.append({"name": "Product Detail - Active Add to Cart Interaction", "category": "positive", "steps": [
            _nav(prod['url'], f"Navigate to product: {prod['name'][:40]}"),
            {"action": "click", "target": SEL_ADD_TO_CART, "description": "Click Add to Cart button", "verify": "Add to cart triggered"},
            {"action": "wait", "target": "2000", "description": "Wait for cart state update", "verify": "Wait completed"},
            _verify(".message-success, [class*='toast' i], [class*='modal' i], [class*='notification' i], [class*='alert' i], [id*='cart' i], [aria-label*='cart' i], .cart, main", "Verify cart update notification or cart header update", "Cart state updated"),
        ]})
    elif cats:
        tests.append({"name": "Product Detail - Open Category & Verify Products", "category": "positive", "steps": [
            _nav(cats[0]['url'], f"Open {cats[0]['text']} to find products"),
            _verify(SEL_PRODUCT_CARD, "Verify individual product cards exist", "Product cards visible"),
            _scroll("Scroll to second row of products", 500),
        ]})

    # ── 5. SEARCH — POSITIVE & NEGATIVE ──────────────────────────────────────
    _log("Building: Search tests")
    if search_action:
        q_char = "&" if "?" in search_action else "?"
        tests.append({"name": "Search - Positive Search Returns Results", "category": "positive", "steps": [
            _nav(search_action + f"{q_char}q=camera", "Navigate directly to search results for 'camera'"),
            _verify(SEL_PAGE_TITLE, "Verify search results page title", "Search page title visible"),
            _verify(SEL_PRODUCTS_GRID, "Verify product results listed", "Products found in search results"),
        ]})
        tests.append({"name": "Search - Search Different Keyword (printer)", "category": "positive", "steps": [
            _nav(search_action + f"{q_char}q=printer", "Navigate to search results for 'printer'"),
            _verify(SEL_PAGE_TITLE, "Verify search results page heading", "Search results page heading visible"),
            _verify(SEL_PRODUCTS_GRID, "Verify products in search results", "Products visible in search"),
        ]})
        tests.append({"name": "Search - No Results for Nonsense Query", "category": "negative", "steps": [
            _nav(search_action + f"{q_char}q=xyznotexist9999", "Navigate to search for a non-existent product"),
            _verify(".message.notice, [class*='no-results' i], [class*='empty' i], .message, [role='alert'], main p, main", "Verify 'no results found' notice message shown", "No results message displayed"),
        ]})
        tests.append({"name": "Search - Special Characters Search Query Edge Case", "category": "negative", "steps": [
            _nav(search_action + f"{q_char}q=%40%23%24%25%26*", "Navigate to search query with special characters (@#$%&*)"),
            _verify("main, body, h1, [class*='search' i], [class*='no-results' i]", "Verify search handles special characters gracefully without server 500 error", "Handled gracefully"),
        ]})
    else:
        tests.append({"name": "Search - Search Input Present & Interactive", "category": "positive", "steps": [
            _nav(b + '/', "Navigate to homepage"),
            _fill(search_sel, "phone", "Enter query in search input", "Search field filled"),
            _verify(search_sel, "Verify search field exists", "Search input visible"),
        ]})
        tests.append({"name": "Search - Special Characters Search Query Edge Case", "category": "negative", "steps": [
            _nav(b + '/', "Navigate to homepage"),
            _fill(search_sel, "@#$%&*", "Enter special characters in search box", "Special chars entered"),
            _verify(search_sel, "Verify search input handles special characters", "Input handles characters"),
        ]})

    # ── 6. CART OPERATIONS ───────────────────────────────────────────────────
    _log("Building: Cart tests")
    tests.append({"name": "Cart - Empty Cart Page Loads", "category": "positive", "steps": [
        _nav(cart_url, "Navigate to shopping cart page"),
        _verify(SEL_CART_EMPTY, "Verify empty cart message or cart container is displayed", "Empty cart message visible"),
    ]})
    tests.append({"name": "Cart - Cart Link Accessible from Homepage", "category": "positive", "steps": [
        _nav(b + '/', "Navigate to homepage"),
        _verify("header, nav", "Verify header or nav is visible", "Header visible"),
        _verify(SEL_CART_HEADER, "Verify cart link/icon present in header", "Cart icon present"),
        _nav(cart_url, "Navigate directly to cart"),
        _verify(SEL_CART_EMPTY, "Verify cart page is accessible and shows empty state", "Cart page accessible"),
    ]})
    tests.append({"name": "Cart - Checkout URL is Reachable", "category": "positive", "steps": [
        _nav(checkout_url, "Navigate to checkout page URL (redirects to cart if empty)"),
        _verify(SEL_CHECKOUT_PAGE, "Verify checkout URL is reachable (renders page or empty cart)", "Checkout URL accessible"),
    ]})

    # ── 7. USER AUTHENTICATION (Conditional) ─────────────────────────────────
    if login_url:
        _log("Building: Auth tests (Login detected)")
        tests.append({"name": "Auth - Login Page Loads & Form Present", "category": "positive", "steps": [
            _nav(login_url, "Navigate to customer login page"),
            _verify(SEL_LOGIN_FORM, "Verify customer login form is present", "Login form visible"),
            _verify(SEL_LOGIN_USER, "Verify email field present", "Login email field visible"),
            _verify(SEL_LOGIN_PASS, "Verify password field present", "Password field visible"),
            _verify(SEL_LOGIN_SUBMIT, "Verify Sign In button present", "Sign In button visible"),
        ]})
        tests.append({"name": "Auth - Login With Empty Fields Shows Validation", "category": "negative", "steps": [
            _nav(login_url, "Navigate to login page"),
            {"action": "click", "target": SEL_LOGIN_SUBMIT, "description": "Click Sign In without entering credentials", "verify": "Validation triggered"},
            _verify(SEL_LOGIN_VALIDATION, "Verify input validation error triggered", "Invalid input validation triggered"),
        ]})

    if register_url:
        _log("Building: Auth tests (Registration detected)")
        tests.append({"name": "Auth - Customer Registration Page Loads", "category": "positive", "steps": [
            _nav(register_url, "Navigate to customer registration page"),
            _verify(SEL_REG_FIRST, "Verify first name field present", "First name field visible"),
            _verify(SEL_REG_EMAIL, "Verify email input field present", "Email field visible"),
            _verify(SEL_REG_PASS, "Verify password field present", "Password field visible"),
            _verify(SEL_REG_SUBMIT, "Verify Create Account submit button present", "Registration submit button visible"),
        ]})

    if login_url and register_url:
        tests.append({"name": "Auth - Register & Login Link Cross-Navigation", "category": "positive", "steps": [
            _nav(login_url, "Navigate to login page"),
            _verify("a[href*='create'], a[href*='register'], a[href*='signup'], a:has-text('Create'), a:has-text('Register')", "Verify 'Create Account' link on login page", "Register link present on login page"),
            _nav(register_url, "Navigate to registration page"),
            _verify("a[href*='login'], a[href*='signin'], a[href*='account'], a:has-text('Sign In'), a:has-text('Log in')", "Verify 'Already have account? Sign In' link", "Login link on registration page"),
        ]})

    # ── 8. CHECKOUT FLOW ─────────────────────────────────────────────────────
    _log("Building: Checkout Flow tests")
    tests.append({"name": "Checkout - Checkout URL Reachable", "category": "positive", "steps": [
        _nav(checkout_url, "Navigate directly to checkout URL (redirects to cart if empty)"),
        _verify(SEL_CHECKOUT_PAGE, "Verify checkout URL responds and renders page", "Checkout page or empty cart loaded"),
    ]})
    tests.append({"name": "Checkout - Cart Page Then Checkout Accessible", "category": "positive", "steps": [
        _nav(cart_url, "Navigate to cart page"),
        _verify(SEL_CART_EMPTY, "Verify cart page loaded (shows empty cart)", "Cart page loaded"),
        _nav(checkout_url, "Navigate to checkout URL"),
        _verify(SEL_CHECKOUT_PAGE, "Verify checkout URL is reachable after cart visit", "Checkout URL accessible"),
    ]})

    # ── 9. FOOTER & STATIC PAGES ─────────────────────────────────────────────
    _log("Building: Footer & Static Pages tests")
    tests.append({"name": "Footer - Footer Section Visible with Links", "category": "positive", "steps": [
        _nav(b + '/', "Navigate to homepage"),
        _scroll("Scroll to page footer", 2000),
        _verify("footer, .page-footer, [class*='footer']", "Verify footer HTML element is present", "Footer element visible"),
        _verify("footer a, .page-footer a, [class*='footer'] a", "Verify footer contains navigation links", "Footer links present"),
    ]})
    # Test only REAL footer links discovered on this specific website
    for fl in footer_links[:4]:
        tests.append({"name": f"Static Page - {fl['text']} Page Loads", "category": "positive", "steps": [
            _nav(fl['url'], f"Navigate to {fl['text']} page"),
            _verify(SEL_PAGE_TITLE, f"Verify {fl['text']} page has main heading", f"{fl['text']} page heading visible"),
            _verify("main, .content, article, body", f"Verify main content area of {fl['text']} page", "Main content area loaded"),
        ]})

    # ── 10. NEWSLETTER SIGNUP & FORM VALIDATION ─────────────────────────────
    tests.append({"name": "Newsletter - Newsletter Signup Form Present", "category": "positive", "steps": [
        _nav(b + '/', "Navigate to homepage"),
        _scroll("Scroll to newsletter section in footer", 1500),
        _verify(SEL_NEWSLETTER, "Verify newsletter email input field", "Newsletter input visible"),
    ]})
    tests.append({"name": "Newsletter - Invalid Email Format Shows Validation", "category": "negative", "steps": [
        _nav(b + '/', "Navigate to homepage"),
        _scroll("Scroll to newsletter section in footer", 1500),
        _fill(SEL_NEWSLETTER, "invalid_email_no_domain", "Fill invalid email format into newsletter", "Invalid email filled"),
        {"action": "click", "target": "form[action*='newsletter' i] button, form[action*='subscribe' i] button, #newsletter-subscribe button, button[type='submit']", "description": "Submit newsletter form with invalid email", "verify": "Submit clicked"},
        _verify("input:invalid, .error, [class*='error' i], [class*='mage-error'], [role='alert'], form", "Verify validation error is triggered for invalid email", "Validation error shown"),
    ]})

    _log(f"Total template test cases built: {len(tests)}")
    return tests


def _discovery_worker(pid, base_url, sid):
    """Multi-page AI Discovery: crawls site, extracts REAL selectors, verifies them with Playwright."""
    active_runs[sid] = {"id": sid, "status": "running", "projectId": pid, "testCaseName": "AI Discovery", "logs": [], "cancelled": False, "started_at": now_iso()}
    def log_cb(level, msg):
        safe_msg = str(msg)
        try:
            safe_print(f"[discovery][{level}] {safe_msg}", flush=True)
        except Exception:
            pass
        try:
            active_runs[sid]["logs"].append({"time": now_iso(), "level": level, "message": safe_msg})
            emit_stream(sid, "progress", json.dumps({"message": safe_msg}))
        except Exception:
            pass

    if not _is_safe_url(base_url):
        log_cb("error", f"SSRF blocked: {base_url}")
        emit_stream(sid, "error", json.dumps({"message": "URL blocked: private/internal network"}))
        with _active_runs_lock:
            active_runs.pop(sid, None)
        return

    # selector_exists and _find_selector_by_text are defined at module level — used directly below

    def _parse_ai_json(raw):
        if not raw: return None
        raw = raw.strip()
        if raw.startswith('```'):
            raw = re.sub(r'^```(?:json)?\s*\n?', '', raw)
            raw = re.sub(r'\n?```\s*$', '', raw)
            raw = raw.strip()
        try: return json.loads(raw)
        except: pass
        fixed = re.sub(r',\s*}', '}', re.sub(r',\s*]', ']', raw))
        try: return json.loads(fixed)
        except: pass
        for pattern in [r'(\[\s*{[\s\S]*}\s*\])', r'(\{[\s\S]*"test_cases"[\s\S]*\})']:
            m = re.search(pattern, raw)
            if m:
                try: return json.loads(m.group(1))
                except: pass
        return _parse_markdown_test_cases(raw)

    browser = None
    try:
        for _ in range(10):
            if sid in run_streams and run_streams[sid]: break
            time.sleep(0.1)

        log_cb("info", "Launching browser...")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            clean_base, creds, req_auth = _extract_auth_credentials(base_url)
            ctx_args = {"viewport": {"width": 1280, "height": 720}}
            if creds:
                ctx_args["http_credentials"] = creds
            ctx = browser.new_context(**ctx_args)
            page = ctx.new_page()

            log_cb("info", f"Navigating to {base_url}...")
            page.goto(base_url, wait_until="load", timeout=60000)
            page.wait_for_timeout(3000)

            log_cb("info", "Extracting homepage DOM...")
            homepage_dom_raw = get_compact_dom(page)
            homepage_dom = json.loads(homepage_dom_raw) if homepage_dom_raw.startswith('{') else {"interactive": []}
            page_title = homepage_dom.get('page_title', page.title())
            log_cb("info", f"Homepage: {page_title} | {len(homepage_dom.get('interactive', []))} interactive elements")

            discoverable = homepage_dom.get('discoverable_links', [])
            all_page_doms = {base_url.rstrip('/'): homepage_dom}
            visited_urls = {base_url.rstrip('/')}

            pages_to_visit = []
            seen_paths = set()
            for link in discoverable:
                path = link.get('url', '')
                if path and path not in seen_paths and path != '/' and len(pages_to_visit) < 20:
                    seen_paths.add(path)
                    full_url = path if path.startswith('http') else base_url.rstrip('/') + '/' + path.lstrip('/')
                    if _is_safe_url(full_url):
                        pages_to_visit.append({'text': link.get('text', path), 'url': full_url, 'selector': link.get('selector', '')})

            log_cb("info", f"Found {len(pages_to_visit)} sub-pages to discover")

            for i, pg in enumerate(pages_to_visit[:15]):
                if active_runs.get(sid, {}).get('cancelled'): break
                try:
                    log_cb("info", f"[{i+1}/{min(len(pages_to_visit),15)}] Crawling: {pg['text']}")
                    page.goto(pg['url'], wait_until="load", timeout=30000)
                    page.wait_for_timeout(1500)
                    sub_dom_raw = get_compact_dom(page)
                    sub_dom = json.loads(sub_dom_raw) if sub_dom_raw.startswith('{') else {"interactive": []}
                    all_page_doms[pg['url']] = sub_dom
                    visited_urls.add(pg['url'])
                    elem_count = len(sub_dom.get('interactive', []))
                    log_cb("info", f"  -> {sub_dom.get('page_title', 'Unknown')} | {elem_count} elements")
                    for link in sub_dom.get('discoverable_links', []):
                        path = link.get('url', '')
                        if path and path not in seen_paths and len(pages_to_visit) < 20:
                            seen_paths.add(path)
                            full = path if path.startswith('http') else base_url.rstrip('/') + '/' + path.lstrip('/')
                            if _is_safe_url(full):
                                pages_to_visit.append({'text': link.get('text', path), 'url': full, 'selector': link.get('selector', '')})
                except Exception as e:
                    log_cb("warning", f"Failed to crawl {pg['url']}: {e}")

            page.goto(base_url, wait_until="load", timeout=30000)
            page.wait_for_timeout(2000)

            total_elements = sum(len(d.get('interactive', [])) for d in all_page_doms.values())
            log_cb("info", f"Discovery complete: {len(all_page_doms)} pages, {total_elements} total interactive elements")

            # ── Build structured site_map from crawl data ──────────────────
            site_map = {
                "base_url": base_url,
                "page_title": page_title,
                "categories": [],
                "products": [],
                "search": None,
                "cart_url": None,
                "checkout_url": None,
                "login_url": None,
                "register_url": None,
                "footer_links": [],
                "all_page_urls": list(all_page_doms.keys()),
            }

            # Discover navigation categories & special URLs
            for link in pages_to_visit[:25]:
                url = link.get('url', '')
                text = link.get('text', '')
                sel = link.get('selector', '')
                if not url or not text: continue
                low = (url + " " + text).lower()
                if any(k in low for k in ['/cart', '/checkout/cart', '/basket', '/bag']):
                    if not site_map['cart_url']: site_map['cart_url'] = url
                elif any(k in low for k in ['/checkout', '/onestepcheckout']) and '/cart' not in low:
                    if not site_map['checkout_url']: site_map['checkout_url'] = url
                elif any(k in low for k in ['/login', '/account/login', '/customer/account/login', '/my-account', '/signin', '/sign-in']):
                    if not site_map['login_url']: site_map['login_url'] = url
                elif any(k in low for k in ['/register', '/account/create', '/customer/account/create', '/signup', '/sign-up']):
                    if not site_map['register_url']: site_map['register_url'] = url
                elif any(k in low for k in ['/privacy', '/terms', '/contact', '/about', '/faq', '/help', '/policy', '/returns', '/refund', '/shipping']):
                    if not any(x['url'].rstrip('/') == url.rstrip('/') for x in site_map['footer_links']):
                        site_map['footer_links'].append({'text': text, 'url': url})
                elif any(k in low for k in ['wishlist', 'compare', 'newsletter', 'currency', 'language', 'account', 'customer', 'my-account']):
                    pass  # Header utility links, not product categories
                else:
                    site_map['categories'].append({'text': text, 'url': url, 'selector': sel})

            # Discover footer links directly from live DOM if available
            try:
                footer_locs = page.locator("footer a, .page-footer a, [class*='footer'] a, #footer a").all()
                for fl in footer_locs[:30]:
                    f_url = fl.get_attribute("href")
                    f_text = fl.inner_text().strip()
                    if f_url and f_text and len(f_text) > 2 and not f_url.startswith("#") and not f_url.startswith("javascript"):
                        f_full = f_url if f_url.startswith("http") else base_url.rstrip("/") + "/" + f_url.lstrip("/")
                        low = (f_text + " " + f_full).lower()
                        if any(k in low for k in ['contact', 'about', 'privacy', 'terms', 'return', 'refund', 'shipping', 'policy', 'faq', 'help']):
                            if not any(x['url'].rstrip('/') == f_full.rstrip('/') for x in site_map['footer_links']):
                                site_map['footer_links'].append({'text': f_text, 'url': f_full})
            except Exception:
                pass

            # Discover search form & action across ANY platform
            for dom_data in all_page_doms.values():
                for form in dom_data.get('forms', []):
                    action = form.get('action', '')
                    fields = form.get('fields', [])
                    for field in fields:
                        field_low = field.lower()
                        if any(k in field_low for k in ['search', 'query', 'looking', 'find', ' (q)', ' (s)']):
                            field_sel = field.split('(')[0].strip()
                            action_full = action if (action and action.startswith('http')) else (base_url.rstrip('/') + '/' + action.lstrip('/') if action else '')
                            site_map['search'] = {'selector': field_sel, 'action_url': action_full}
                            break
                    if site_map['search']: break

            # Discover real products across ANY platform (Shopify, WooCommerce, Magento, BigCommerce, Custom)
            cat_urls_set = {c.get('url', '').rstrip('/') for c in site_map['categories']}
            cat_names_set = {c.get('text', '').strip().lower() for c in site_map['categories']}
            for url_key, dom_data in all_page_doms.items():
                if url_key == base_url.rstrip('/'): continue
                for elem in dom_data.get('interactive', []):
                    elem_str = str(elem)
                    # Check for product-like URL patterns
                    is_product_pattern = any(p in elem_str for p in ['/products/', '/product/', '/item/', '/p/', '.html'])
                    if is_product_pattern and '=>' in elem_str:
                        parts = elem_str.split('=>')
                        if len(parts) == 2:
                            sel_part = parts[0].strip().split()[-1] if parts[0].strip() else ''
                            text_part = parts[1].strip().strip('"')
                            if text_part and len(text_part) > 3 and not text_part.startswith('http') and sel_part:
                                href_match = re.search(r'href=["\']([^"\']+)["\']', sel_part)
                                if href_match:
                                    prod_url = href_match.group(1)
                                    if not prod_url.startswith('http'):
                                        prod_url = base_url.rstrip('/') + '/' + prod_url.lstrip('/')
                                    clean_url = prod_url.rstrip('/')
                                    # Ensure it is not a category page, homepage, or static link
                                    if clean_url not in cat_urls_set and text_part.strip().lower() not in cat_names_set and not clean_url.endswith('/default'):
                                        if not any(f['url'].rstrip('/') == clean_url for f in site_map['footer_links']):
                                            site_map['products'].append({'name': text_part, 'url': prod_url, 'selector': sel_part})
                                            if len(site_map['products']) >= 3:
                                                break
                if site_map['products']:
                    break

            if not site_map['cart_url']:
                site_map['cart_url'] = base_url.rstrip('/') + '/cart'
            if not site_map['checkout_url']:
                site_map['checkout_url'] = base_url.rstrip('/') + '/checkout'

            log_cb("info", f"Site map: {len(site_map['categories'])} categories, {len(site_map['products'])} products, search={'found' if site_map['search'] else 'not found'}")

            # ── Layer 2: Template-based e-commerce test builder ──────────────
            log_cb("info", "Building comprehensive e-commerce test suite from templates...")
            generated = _build_ecommerce_test_cases(site_map, base_url, log_cb)
            log_cb("info", f"Template builder created {len(generated)} test cases")

            # ── Layer 3: AI enhancement (additive edge cases only) ───────────
            cfg = get_config()
            search_sel = site_map['search']['selector'] if site_map['search'] else '#search'
            ai_prompt = (
                f"You are a senior QA engineer reviewing e-commerce test coverage for: {base_url}\n\n"
                f"We already have {len(generated)} test cases:\n"
                + "\n".join(f"- {tc['name']}" for tc in generated[:30]) + "\n\n"
                "Generate 5-8 ADDITIONAL edge-case / negative test cases we may have missed.\n"
                "Focus on: empty cart checkout, invalid login, newsletter signup, search with special chars, "
                "session persistence, or any site-specific edge case.\n\n"
                "Use ONLY these real URLs:\n"
                + "\n".join(f"- {c['text']}: {c['url']}" for c in site_map['categories'][:10]) + "\n"
                f"- Cart: {site_map['cart_url']}\n- Login: {site_map['login_url']}\n\n"
                f"For navigate steps: use full URL in 'target'.\n"
                f"For fill steps: search input selector is: {search_sel}\n"
                '{"test_cases":[{"name":"Edge Case Name","category":"edge","steps":['
                '{"action":"navigate","target":"https://...","description":"...","verify":"..."},'
                '{"action":"fill","target":"#search","value":"!!!","description":"...","verify":"..."}'
                ']}]}'
            )
            try:
                log_cb("info", "AI enhancement pass (edge cases)...")
                raw_ai = call_ai(ai_prompt, cfg, timeout=120, json_mode=False)
                if raw_ai:
                    extra = _parse_ai_json(raw_ai)
                    if extra:
                        if isinstance(extra, dict):
                            extra = extra.get('test_cases', [v for v in extra.values() if isinstance(v, dict) and v.get('name')])
                        if isinstance(extra, list):
                            extra = [tc for tc in extra if isinstance(tc, dict) and tc.get('name') and tc.get('steps')]
                            existing_names = {tc['name'].lower() for tc in generated}
                            added = 0
                            for tc in extra:
                                if tc.get('name', '').lower() not in existing_names:
                                    for step in tc.get('steps', []):
                                        for field in ('target', 'description'):
                                            if step.get(field) and '$BASE_URL' in step[field]:
                                                step[field] = step[field].replace('$BASE_URL', base_url.rstrip('/'))
                                    generated.append(tc)
                                    existing_names.add(tc['name'].lower())
                                    added += 1
                            log_cb("info", f"AI added {added} edge case(s) — total: {len(generated)}")
                else:
                    log_cb("info", "AI enhancement skipped (no response) — template cases are complete")
            except Exception as e:
                log_cb("info", f"AI enhancement skipped ({e}) — template cases are complete")

            log_cb("info", f"Total: {len(generated)} test cases ready to save")
            browser.close()


        # Remove old ai-discovery test cases for this project so fresh test suite replaces stale cases
        test_cases_table.remove((Query().projectId == pid) & (Query().source == "ai-discovery"))
        _invalidate_table_cache("test_cases")
        all_tcs = safe_all(test_cases_table)
        count = len([t for t in all_tcs if t.get("projectId") == pid])
        to_insert = []
        for i, tc in enumerate(generated):
            tcid = make_id()[:16]
            to_insert.append({
                "_id": tcid, "id": tcid, "projectId": pid,
                "name": tc.get("name", f"AI Discovery {count+i+1}"),
                "category": tc.get("category", "functional"),
                "steps": tc.get("steps", []),
                "source": "ai-discovery",
                "isRegression": True,
                "sortOrder": count + i,
                "createdAt": now_iso(), "updatedAt": now_iso()
            })

        if not to_insert:
            emit_stream(sid, "error", json.dumps({"message": "No test cases to save"}))
            return

        log_cb("info", f"Saving {len(to_insert)} test cases...")
        safe_insert_multiple(test_cases_table, to_insert)
        log_cb("info", f"Done! {len(to_insert)} cases added to project")
        with _active_runs_lock:
            if sid in active_runs:
                active_runs[sid]["status"] = "completed"
                active_runs[sid]["completed_at"] = now_iso()
                active_runs[sid]["result"] = {"created": len(to_insert), "pages_discovered": len(all_page_doms), "total_elements": total_elements}
        emit_stream(sid, "complete", json.dumps({"created": len(to_insert), "pages": len(all_page_doms), "elements": total_elements}))

    except Exception as e:
        import traceback
        try:
            tb = traceback.format_exc()
            safe_print(f"[ERROR] AI Discovery failed: {e}\n{tb}")
        except Exception:
            pass
        err_msg = str(e)
        with _active_runs_lock:
            if sid in active_runs:
                active_runs[sid]["status"] = "error"
                active_runs[sid]["logs"].append({"time": now_iso(), "level": "error", "message": f"Discovery failed: {err_msg[:300]}"})
                active_runs[sid]["completed_at"] = now_iso()
        if browser:
            try: browser.close()
            except: pass
        try:
            emit_stream(sid, "error", json.dumps({"message": err_msg[:500]}))
        except Exception:
            pass
    finally:
        pass

# ============ TEST PLANS ============
@app.route("/api/test-plans")
def api_list_plans():
    plans = []
    for f in sorted(TEST_PLANS_DIR.glob("*.md")):
        content = f.read_text(encoding="utf-8")
        title = ""
        for line in content.split("\n"):
            if line.startswith("# "): title = line[2:].strip(); break
        plans.append({"filename":f.name,"title":title,"test_cases":0,"size":len(content),
            "modified":datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")})
    return ok(plans)

@app.route("/api/test-plans", methods=["POST"])
@require_json
def api_save_plan():
    data = request.json
    fp = plan_file_path(data.get("filename", "plan.md"))
    if not fp:
        return err("Invalid filename", 400)
    fp.write_text(data.get("content", ""), encoding="utf-8")
    return ok({"status": "saved", "filename": fp.name})

@app.route("/api/test-plans/<fn>")
def api_get_plan(fn):
    fp = plan_file_path(fn)
    if not fp or not fp.exists():
        return err("Not found", 404)
    return ok({"filename": fp.name, "content": fp.read_text(encoding="utf-8")})

@app.route("/api/test-plans/<fn>", methods=["DELETE"])
def api_delete_plan(fn):
    fp = plan_file_path(fn)
    if not fp:
        return err("Invalid filename", 400)
    if fp.exists():
        fp.unlink()
    return ok({"status": "deleted"})

# ============ RESULTS ============
@app.route("/api/results")
def api_list_results():
    ress = sorted(safe_all(results_table), key=lambda r: r.get("createdAt",""), reverse=True)
    return ok([slim_result(r) for r in ress[:parse_limit()]])

@app.route("/api/results/<rid>")
def api_get_result(rid):
    for r in safe_all(results_table):
        if r.get("_id")==rid or r.get("id")==rid:
            old_md = r.get("rawMarkdown","")
            if not old_md or "Adapted" in old_md or old_md.startswith("AI Browser Test:"):
                logs = [{"message": r.get("processLog","")}]
                steps = r.get("steps",[])
                r["rawMarkdown"] = build_report_markdown(
                    r.get("testCaseName","Untitled"), steps,
                    r.get("passed",0), r.get("adapted",0),
                    r.get("failed",0), r.get("blocked",0),
                    r.get("duration",0), logs, r.get("createdAt"),
                    r.get("mode", "standard"),
                    r.get("device", "desktop")
                )
                backfill_id = r.get("_id") or r.get("id")
                if backfill_id:
                    q=Query(); safe_update(results_table, (q._id==backfill_id) | (q.id==backfill_id), {"rawMarkdown":r["rawMarkdown"]})
            return ok(r)
    return err("Not found",404)

@app.route("/api/results", methods=["POST"])
@require_json
def api_save_result():
    data=request.json; data["_id"]=make_id()[:16]; data["createdAt"]=now_iso()
    safe_insert(results_table, data); return ok(data)

@app.route("/api/results/<rid>", methods=["DELETE"])
def api_delete_result(rid):
    safe_remove(results_table, record_id_cond(rid))
    return ok({"status":"deleted"})

# Compat aliases for frontend api.js
@app.route("/api/test-results")
def api_test_results_list():
    return api_list_results()

@app.route("/api/test-results/<rid>")
def api_test_result_get(rid):
    return api_get_result(rid)

@app.route("/api/test-results", methods=["POST"])
def api_test_result_save():
    return api_save_result()

@app.route("/api/test-results/<rid>", methods=["DELETE"])
def api_test_result_delete(rid):
    return api_delete_result(rid)

def _run_sequential_queue(pid, run_queue, tcs, mode, device):
    """Shared sequential queue runner — used by both api_run_selected and api_run_project.
    Fixes #3 (duplicate code) and #2 (race condition: use .get() to safely read active_runs)."""
    queue_obj = project_queues.get(pid)
    for tc_id, rid in run_queue:
        # Thread-safe: use .get() to avoid KeyError if run was cleaned up
        run_info = active_runs.get(rid, {})
        if run_info.get("cancelled"):
            continue
        if queue_obj:
            queue_obj["currentTestCase"] = next(
                (t.get("name") for t in tcs if (t.get("id") or t.get("_id")) == tc_id), "Test"
            )
            save_active_state()
        emit_stream(pid, "queue_test_started", json.dumps({
            "runId": rid,
            "testCaseName": queue_obj.get("currentTestCase", "") if queue_obj else ""
        }))
        run_test_thread(tc_id, rid, mode, device)
        if queue_obj:
            res = safe_all(results_table)
            last_res = next((r for r in reversed(res) if r.get("id") == rid), None)
            last_status = last_res.get("status", "pass") if last_res else "pass"
            queue_obj["completed"].append({"id": rid, "status": last_status})
            emit_stream(pid, "queue_progress", json.dumps({
                "completed": len(queue_obj["completed"]),
                "total": queue_obj.get("total", 0),
                "currentTestCase": queue_obj.get("currentTestCase", "")
            }))
            save_active_state()

    if queue_obj:
        queue_obj["status"] = "completed"
        queue_obj["currentTestCase"] = ""
        save_active_state(force=True)
        emit_stream(pid, "queue_completed", json.dumps({"completed": queue_obj.get("completed", [])}))

# ============ RUN ============
@app.route("/api/run/<tc_id>", methods=["POST"])
def api_run_test(tc_id):
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "standard")
    device = data.get("device", "desktop")
    tc = None
    for t in safe_all(test_cases_table):
        if t.get("id")==tc_id or t.get("_id")==tc_id: tc = t; break
    if not tc:
        return err("Test case not found", 404)
    
    run_id = make_id()[:12]
    tc_name = tc.get("name","")
    tc_steps = len(tc.get("steps",[]))
    active_runs[run_id] = {"id":run_id,"status":"queued","testCaseId":tc_id,"testCaseName":tc_name,"totalSteps":tc_steps,"logs":[],"cancelled":False,"mode":mode,"device":device,"projectId":tc.get("projectId","")}
    save_active_state(force=True)
    t = threading.Thread(target=run_test_thread, args=(tc_id,run_id,mode,device), daemon=True); t.start()
    return ok({"runId":run_id,"status":"queued","testCaseName":tc_name,"totalSteps":tc_steps})

@app.route("/api/run/selected", methods=["POST"])
@require_json
def api_run_selected():
    data = request.get_json(silent=True) or {}
    pid = data.get("projectId")
    test_case_ids = data.get("testCaseIds", [])
    mode = data.get("mode", "standard")
    device = data.get("device", "desktop")
    
    if not pid:
        return err("projectId is required")
    if not test_case_ids or not isinstance(test_case_ids, list):
        return err("testCaseIds array is required")
    
    tcs = []
    for tc_id in test_case_ids:
        tc = None
        for t in safe_all(test_cases_table):
            if t.get("id") == tc_id or t.get("_id") == tc_id:
                tc = t
                break
        if tc and tc.get("projectId") == pid:
            tcs.append(tc)
    
    if not tcs:
        return err("No valid test cases found for this project")
    
    run_queue = []
    for tc in tcs:
        rid = make_id()[:12]
        active_runs[rid] = {
            "id": rid, "status": "queued", "testCaseId": tc.get("id") or tc.get("_id"),
            "logs": [], "cancelled": False, "mode": mode, "device": device,
            "testCaseName": tc.get("name"), "projectId": pid,
            "totalSteps": len(tc.get("steps", [])), "currentStep": 0
        }
        run_queue.append((tc.get("id") or tc.get("_id"), rid))
    
    project_queues[pid] = {
        "id": pid, "status": "running", "total": len(run_queue),
        "completed": [], "currentTestCase": tcs[0].get("name")
    }
    save_active_state(force=True)
    
    t = threading.Thread(target=_run_sequential_queue, args=(pid, run_queue, tcs, mode, device), daemon=True)
    t.start()
    
    return ok({"queueId": pid, "total": len(run_queue), "status": "running"})

@app.route("/api/run/project/<pid>", methods=["POST"])
def api_run_project(pid):
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "standard")
    device = data.get("device", "desktop")
    tcs = [t for t in safe_all(test_cases_table) if t.get("projectId")==pid and t.get("isRegression")]
    if not tcs: tcs = [t for t in safe_all(test_cases_table) if t.get("projectId")==pid]
    if not tcs: return err("No test cases in project")

    run_queue = []
    for tc in tcs:
        rid = make_id()[:12]
        active_runs[rid] = {
            "id":rid, "status":"queued", "testCaseId":tc.get("id") or tc.get("_id"),
            "logs":[], "cancelled":False, "mode":mode, "device":device,
            "testCaseName": tc.get("name"), "projectId": pid,
            "totalSteps": len(tc.get("steps", [])), "currentStep": 0
        }
        run_queue.append((tc.get("id") or tc.get("_id"), rid))

    project_queues[pid] = {
        "id": pid, "status": "running", "total": len(run_queue),
        "completed": [], "currentTestCase": tcs[0].get("name")
    }
    save_active_state(force=True)

    threading.Thread(target=_run_sequential_queue, args=(pid, run_queue, tcs, mode, device), daemon=True).start()
    
    return ok({
        "queueId": pid,
        "total": len(run_queue),
        "status": "running"
    })

@app.route("/api/queue/<qid>")
def get_queue(qid):
    q = project_queues.get(qid)
    if not q: return err("Queue not found", 404)
    return ok(q)

@app.route("/api/queue/active")
def get_active_queues():
    return ok([q for q in project_queues.values() if q.get("status") == "running"])

@app.route("/api/queue/stream/<qid>")
def queue_stream(qid):
    def gen():
        while True:
            q = project_queues.get(qid)
            if not q: break
            yield f"data: {json.dumps({'type':'snapshot', **q})}\n\n"
            if q.get("status") in ("completed", "cancelled", "failed"): break
            time.sleep(2)
    return Response(gen(), mimetype="text/event-stream")

@app.route("/api/queue/<qid>/cancel", methods=["POST"])
def cancel_queue(qid):
    q = project_queues.get(qid)
    if q:
        q["status"] = "cancelled"
        # Also cancel all active runs in this project
        for rid, run in active_runs.items():
            if run.get("projectId") == qid and run.get("status") in ("queued", "running"):
                run["cancelled"] = True
    return ok({"success": True})

@app.route("/api/run/plan", methods=["POST"])
def api_run_plan():
    data = request.get_json(silent=True) or {}
    fn=data.get("filename",""); url=data.get("url","")
    mode=data.get("mode","standard")
    device=data.get("device","desktop")
    fp=plan_file_path(fn)  # Use safe validator to prevent path traversal
    if not fp or not fp.exists(): return err("Plan not found",404)
    content=fp.read_text(encoding="utf-8")
    steps=[]
    for line in content.split("\n"):
        if line.strip() and line.strip()[0].isdigit() and "." in line:
            steps.append({"action":"navigate","description":line.split(".",1)[1].strip(),"seq":len(steps)+1,"target":url,"timestamp":1,"value":None,"verify":"Executes successfully"})
    if not steps: return err("No steps in plan")
    tc={"id":f"plan_{make_id()[:8]}","projectId":"plan","name":f"Plan: {fn}","steps":steps}
    rid=make_id()[:12]
    active_runs[rid] = {"id":rid,"status":"queued","testCaseId":tc["id"],"testCaseName":tc["name"],"totalSteps":len(steps),"logs":[],"cancelled":False,"mode":mode,"device":device}
    def plan_thread():
        active_runs[rid]["status"]="running"; active_runs[rid]["started_at"]=now_iso()
        def cb(l,m): active_runs[rid]["logs"].append({"time":now_iso(),"level":l,"message":m}); emit_stream(rid,"log",json.dumps({"level":l,"text":m}))
        cb("info",f"Plan: {fn} @ {url} | Mode: {mode} | Device: {device}")
        result = run_test_case_with_ai(tc, url, rid, cb, mode, device)
        result["id"] = rid
        result["projectId"]=""; result["testCaseId"]=tc["id"]; result["testCaseName"]=tc["name"]; result["runner"]="ollama-browser"
        result["duration"]=0; result["processLog"]=""; result["screenshots"]={}; result["screenshotDir"]=""
        result["createdAt"]=now_iso(); result["executedAt"]=now_iso()
        active_runs[rid]["status"]="completed"; active_runs[rid]["result"]=result
        safe_insert(results_table, result)
        emit_stream(rid,"complete",json.dumps({
            "status": result["status"],
            "summary": result.get("summary", "Complete"),
            "runId": rid,
            "resultId": rid
        }))
    threading.Thread(target=plan_thread, daemon=True).start()
    return ok({"runId":rid,"status":"queued","testCaseName":tc["name"],"totalSteps":len(steps)})


@app.route("/api/run/status/<rid>")
def api_run_status(rid):
    if rid in active_runs:
        r=active_runs[rid]; return ok({"runId":rid,"status":r.get("status"),"logs":r.get("logs",[]),
            "result":r.get("result"),"startedAt":r.get("started_at"),"completedAt":r.get("completed_at"),
            "currentStep":r.get("currentStep",0),"totalSteps":r.get("totalSteps",0)})
    for r in safe_all(results_table):
        if r.get("id")==rid or r.get("_id")==rid: return ok(r)
    return err("Not found",404)

@app.route("/api/run/active")
def api_active_runs():
    active=[]
    # Use list() to avoid RuntimeError if active_runs is modified during iteration
    items = list(active_runs.items())
    if not items:
        return ok([])
    
    # Pre-fetch all test cases to avoid N lookups
    all_tcs = safe_all(test_cases_table)
    tc_map = {t.get("id") or t.get("_id"): t for t in all_tcs}

    for rid, r in items:
        if r.get("status") in ("queued", "running"):
            tc_id = r.get("testCaseId", "")
            tc = tc_map.get(tc_id, {})
            tc_name = tc.get("name", "")
            proj_id = tc.get("projectId", "")
            
            active.append({
                "runId": rid,
                "status": r["status"],
                "testCaseName": tc_name,
                "projectId": proj_id,
                "currentStep": r.get("currentStep",0),
                "totalSteps": r.get("totalSteps",0),
                "startedAt": r.get("started_at", now_iso())
            })
    return ok(active)

@app.route("/api/run/cancel/<rid>", methods=["POST"])
def api_cancel_run(rid):
    if rid in active_runs: active_runs[rid]["cancelled"]=True; return ok({"status":"cancelled"})
    return err("Not found",404)

@app.route("/api/run/stream/<rid>")
def api_run_stream(rid):
    if rid not in run_streams: run_streams[rid]={}
    q = queue.Queue(); qid = str(id(q)); run_streams[rid][qid]=q
    def generate():
        try:
            while True:
                try:
                    event, data = q.get(timeout=30)
                    yield f"event: {event}\ndata: {data}\n\n"
                    if event=="complete": break
                except queue.Empty:
                    # Check if run is done — if so, close stream
                    run_info = active_runs.get(rid)
                    if run_info and run_info.get("status") in ("completed","error"):
                        break
                    yield "event: heartbeat\ndata: ping\n\n"
        finally:
            if rid in run_streams:
                run_streams[rid].pop(qid, None)
                # Clean up the outer key if no more subscribers remain
                if not run_streams[rid]:
                    run_streams.pop(rid, None)
    return Response(generate(), mimetype="text/event-stream", headers={"Cache-Control":"no-store","X-Accel-Buffering":"no"})

@app.route("/api/run/result/<rid>")
def api_run_result(rid):
    for r in safe_all(results_table):
        if r.get("id")==rid or r.get("_id")==rid: return ok(r)
    return err("Not found",404)

# ============ CONFIG ============
@app.route("/api/config")
def api_get_config():
    cfg = get_config()
    # NEVER expose secret values (not even masked — prefix/suffix leaks key info).
    # The UI only needs to know whether a key is configured.
    safe_cfg = {k: v for k, v in cfg.items() if k not in SECRET_KEYS}
    safe_cfg["cloud_api_key_set"] = bool(cfg.get("cloud_api_key"))
    safe_cfg["anthropic_api_key_set"] = bool(cfg.get("anthropic_api_key"))
    return ok(safe_cfg)

def _looks_masked_or_blank(v):
    if not v or not str(v).strip():
        return True
    s = str(v)
    return "..." in s or "***" in s

@app.route("/api/config", methods=["POST"])
@require_json
def api_save_config():
    data=request.json; current=get_config()
    for k in ("ai_provider","ollama_base_url","ollama_model","cloud_base_url","cloud_model"):
        if k in data: current[k]=data[k]
    # Secrets: only overwrite when a real new value is submitted.
    # Blank / masked values must NEVER wipe the stored key.
    for k in SECRET_KEYS:
        if k in data and not _looks_masked_or_blank(data[k]):
            current[k]=data[k]
    save_config(current); return ok({"status":"saved"})

@app.route("/api/ollama-status")
def api_ollama_status():
    return ok({"connected":ollama_available()})

@app.route("/api/ollama/models")
def api_ollama_models_alias():
    return api_ollama_models()

@app.route("/api/ollama-models")
def api_ollama_models():
    cfg=get_config(); models=get_ollama_models()
    return ok({"models":models,"recommended":"qwen2.5-coder:3b","current":cfg.get("ollama_model","")})

@app.route("/api/cloud-models")
def api_cloud_models():
    """Fetch available models from any OpenAI-compatible API (NVIDIA, OpenAI, etc.)"""
    cfg = get_config()
    base_url = request.args.get("base_url") or cfg.get("cloud_base_url", "")
    api_key = request.args.get("api_key") or cfg.get("cloud_api_key", "")
    if not base_url:
        return err("No base URL configured", 400)
    if not api_key:
        return err("No API key configured", 400)
    try:
        url = base_url.rstrip("/") + "/models"
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return err(f"API returned {resp.status_code}: {resp.text[:200]}", 502)
        data = resp.json()
        models = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
        models.sort()
        return ok({"models": models, "count": len(models), "base_url": base_url})
    except requests.exceptions.Timeout:
        return err("Connection timed out", 504)
    except Exception as e:
        return err(f"Failed to fetch models: {str(e)}", 500)

@app.route("/api/cloud-test")
def api_cloud_test():
    """Test cloud API connection"""
    cfg = get_config()
    base_url = request.args.get("base_url") or cfg.get("cloud_base_url", "")
    api_key = request.args.get("api_key") or cfg.get("cloud_api_key", "")
    if not base_url or not api_key:
        return ok({"connected": False, "error": "Missing URL or API key"})
    try:
        url = base_url.rstrip("/") + "/models"
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            return ok({"connected": True})
        return ok({"connected": False, "error": f"HTTP {resp.status_code}"})
    except Exception as e:
        return ok({"connected": False, "error": str(e)[:100]})

@app.route("/api/screenshots/<filename>")
def api_serve_screenshot(filename):
    safe = os.path.basename(str(filename).replace("\\", "/"))
    if not safe or safe in (".", ".."):
        return err("Invalid filename", 400)
    return send_from_directory(str(SCREENSHOTS_DIR), safe)

# ============ UI ============
@app.route("/")
def ui_index(): return send_from_directory(str(UI_DIR),"index.html")

@app.route("/<path:path>")
def ui_static(path):
    fp=UI_DIR/path
    if fp.exists() and fp.is_file(): return send_from_directory(str(UI_DIR),path)
    return send_from_directory(str(UI_DIR),"index.html")

# ============ MAIN ============
if __name__=="__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "127.0.0.1")
    cfg = get_config()
    print("="*50)
    print(f"  AI QA Tester v2 — Backend")
    print(f"  Port: {port}  |  UI: http://localhost:{port}")
    print(f"  Bind: {host}  (set HOST=0.0.0.0 for LAN access)")
    print(f"  Ollama: {'Connected' if ollama_available() else 'Not running'}")
    print(f"  Model: {cfg.get('ollama_model', 'qwen2.5-coder:3b')} @ {cfg.get('ollama_base_url', 'http://localhost:11434')}")
    if API_KEY or (AUTH_USER and AUTH_PASS):
        methods = []
        if API_KEY: methods.append("X-API-Key")
        if AUTH_USER and AUTH_PASS: methods.append(f"Basic (id={AUTH_USER})")
        print(f"  Auth: enabled [{', '.join(methods)}] — all /api/* locked, localhost exempt")
    else:
        print("  WARNING: no API_KEY / AUTH_USER+AUTH_PASS set — API auth is DISABLED.")
    print("="*50)

    # Start auto-resume in background
    threading.Thread(target=resume_interrupted_runs, daemon=True).start()

    # Periodic cleanup of completed runs to prevent memory leak
    def _periodic_cleanup():
        while True:
            time.sleep(60)
            _cleanup_completed_runs()
    threading.Thread(target=_periodic_cleanup, daemon=True).start()

    use_waitress = os.environ.get("USE_WAITRESS", "").lower() in ("1", "true", "yes")
    if use_waitress:
        try:
            from waitress import serve
            print("  Server: Waitress")
            serve(app, host=host, port=port, threads=8)
        except ImportError:
            print("  Server: Flask dev (install waitress for production: pip install waitress)")
            app.run(host=host, port=port, debug=False, threaded=True)
    else:
        print("  Server: Flask dev (set USE_WAITRESS=1 for Waitress)")
        app.run(host=host, port=port, debug=False, threaded=True)
