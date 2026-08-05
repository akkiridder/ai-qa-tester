import os, json, uuid, threading, time, queue, re, math, base64
from datetime import datetime, timezone
from pathlib import Path
from functools import wraps
from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS
from tinydb import TinyDB, Query
import requests
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
TEST_PLANS_DIR = DATA_DIR / "test-plans"
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
UI_DIR = BASE_DIR / "ui"
CONFIG_FILE = BASE_DIR / "config.json"

DATA_DIR.mkdir(exist_ok=True)
TEST_PLANS_DIR.mkdir(exist_ok=True)
SCREENSHOTS_DIR.mkdir(exist_ok=True)
UI_DIR.mkdir(exist_ok=True)

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

db = TinyDB(DB_FILE, sort_keys=True, indent=2)
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
DEFAULT_CONFIG = {"ai_provider":"ollama","ollama_base_url":"http://localhost:11434","ollama_model":"qwen2.5-coder:3b"}

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
    CONFIG_FILE.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")

def call_ai(prompt, cfg=None, timeout=300):
    """Call AI provider (Ollama or Cloud API). Returns response text or None."""
    if cfg is None:
        cfg = get_config()
    provider = cfg.get("ai_provider", "ollama")
    if provider == "cloud" and cfg.get("cloud_base_url") and cfg.get("cloud_api_key"):
        url = cfg["cloud_base_url"].rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {cfg['cloud_api_key']}", "Content-Type": "application/json"}
        body = {"model": cfg.get("cloud_model", ""), "messages": [{"role": "user", "content": prompt}], "stream": False}
        r = requests.post(url, headers=headers, json=body, timeout=timeout)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
        return None
    else:
        url = cfg["ollama_base_url"].rstrip("/") + "/api/chat"
        body = {"model": cfg["ollama_model"], "messages": [{"role": "user", "content": prompt}], "stream": False}
        r = requests.post(url, json=body, timeout=timeout)
        if r.status_code == 200:
            return r.json()["message"]["content"].strip()
        return None

def init_config():
    file_cfg = _read_config_file()
    cfg = safe_all(config_table)
    if not cfg:
        merged = {k: v for k, v in {**DEFAULT_CONFIG, **file_cfg}.items() if k in CONFIG_KEYS}
        safe_insert(config_table, merged)
        return
    if not file_cfg:
        return
    current = dict(cfg[0])
    updates = {}
    for k in CONFIG_KEYS:
        if k in file_cfg and file_cfg[k] and current.get(k) != file_cfg[k]:
            updates[k] = file_cfg[k]
    if updates:
        merged = {k: v for k, v in {**current, **updates}.items() if k in CONFIG_KEYS}
        save_config(merged)

def get_config():
    cfg = safe_all(config_table)
    if not cfg:
        merged = {k: v for k, v in {**DEFAULT_CONFIG, **_read_config_file()}.items() if k in CONFIG_KEYS}
        safe_insert(config_table, merged)
        return dict(merged)
    return {k: v for k, v in dict(cfg[0]).items() if k in CONFIG_KEYS}

def save_config(data):
    cfg = safe_all(config_table)
    if cfg:
        with db_lock:
            config_table.remove(doc_ids=[cfg[0].doc_id])
            config_table.insert(data)
        _invalidate_table_cache("config")
    else:
        safe_insert(config_table, data)
    _write_config_file(data)

init_config()

app = Flask(__name__, static_folder=None)
CORS(app, resources={r"/api/*": {"origins": [
    re.compile(r"http://localhost(:\d+)?"),
    re.compile(r"http://127\.0\.0\.1(:\d+)?"),
    re.compile(r"chrome-extension://.*"),
]}})
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
LOCAL_ADDRS = {"127.0.0.1", "::1"}
TEST_ARTIFACT_NAMES = {"Seed Test Project", "API Test Project", "API Test Project v2"}
TEST_ARTIFACT_URLS = {"https://example.com", "http://example.com"}
RESULT_LIST_FIELDS = (
    "_id", "id", "projectId", "testCaseId", "testCaseName", "status", "mode", "device",
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
            # For simplicity, we restart the regression run for the project
            # A more advanced version would pick up where it left off
            # api_run_project(qid) # We can't call this directly because it expects Request context
            # So we'll just log it for now or implement a background resume
            pass

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
    if not API_KEY:
        return None
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None
    if request.path.endswith("/stream") or "/stream/" in request.path:
        return None
    addr = (request.remote_addr or "").strip()
    if addr in LOCAL_ADDRS or addr.startswith("127."):
        return None
    key = request.headers.get("X-API-Key") or request.args.get("api_key")
    if key == API_KEY:
        return None
    return err("Unauthorized — set X-API-Key header", 401)

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
    """Returns a grouped, structured DOM representation for AI context."""
    try:
        return page.evaluate('''() => {
            const sections = {
                'header': 'header, .header, nav',
                'main': 'main, #main, .content, .product-container',
                'cart': '#cart, .cart-container, .mini-cart',
                'checkout': '#checkout, .checkout-container',
                'footer': 'footer, .footer'
            };
            
            const interactiveSelectors = 'a, button, input, select, textarea, [role="button"], [onclick]';
            const grouped = {};
            
            for (const [name, sel] of Object.entries(sections)) {
                const container = document.querySelector(sel);
                if (container) {
                    grouped[name] = [];
                    container.querySelectorAll(interactiveSelectors).forEach((el, index) => {
                        if (index > 15) return; // Limit per section
                        const tag = el.tagName.toLowerCase();
                        const txt = (el.innerText || el.value || el.title || '').trim().slice(0, 50);
                        if (txt) grouped[name].push(`<${tag}>${txt}</${tag}>`);
                    });
                }
            }
            
            return JSON.stringify(grouped, null, 2);
        }''')
    except Exception as e:
        return f"DOM extraction failed: {str(e)}"

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

    # === Pre-flight health check ===
    health_url = base_url.rstrip("/")
    log_cb("info", f"Site health check: {health_url}")
    
    health_ok = False
    for attempt in range(2):
        try:
            hr = requests.get(health_url, timeout=10, headers={"User-Agent":"Mozilla/5.0"}, allow_redirects=True)
            if hr.status_code >= 500:
                log_cb("warning", f"Site {health_url} returned HTTP {hr.status_code} (Attempt {attempt+1}/2)")
                try:
                    cfg = get_config()
                    prompt = (
                        f"The URL {health_url} returned HTTP {hr.status_code} (server error).\n"
                        "Should we retry, or abort the test?\n"
                        "Respond with only: RETRY | ABORT: <reason>"
                    )
                    ai_txt = call_ai(prompt, timeout=10)
                    if ai_txt:
                        log_cb("info", f"AI health check: {ai_txt[:200]}")
                        if ai_txt.upper().startswith("ABORT"):
                            return {"status":"fail","steps":[{"seq":0,"status":"fail","note":f"Site down (HTTP {hr.status_code}) — {ai_txt}"}],"passed":0,"adapted":0,"failed":1,"blocked":0,"summary":"Site unreachable — aborted"}
                        # If RETRY, we just continue the loop
                except Exception as e:
                    log_cb("warning", f"AI health check failed: {e}")
            else:
                log_cb("ok", f"Site {health_url} responded with HTTP {hr.status_code}")
                health_ok = True
                break
        except (requests.ConnectionError, requests.Timeout) as conn_err:
            log_cb("warning", f"Site {health_url} unreachable ({type(conn_err).__name__}) (Attempt {attempt+1}/2)")
            if attempt == 0: # Only ask AI on first failure
                try:
                    cfg = get_config()
                    prompt = (
                        f"The URL {health_url} is unreachable ({type(conn_err).__name__}).\n"
                        "Should we retry, or abort the test?\n"
                        "Respond with only: RETRY | ABORT: <reason>"
                    )
                    ai_txt = call_ai(prompt, timeout=10)
                    if ai_txt:
                        log_cb("info", f"AI health check: {ai_txt[:200]}")
                        if ai_txt.upper().startswith("ABORT"):
                            return {"status":"fail","steps":[{"seq":0,"status":"fail","note":f"Site {health_url} unreachable — {ai_txt}"}],"passed":0,"adapted":0,"failed":1,"blocked":0,"summary":"Site unreachable — aborted"}
                except Exception as e:
                    log_cb("warning", f"AI health check failed: {e}")
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
                ctx = browser.new_context(**ctx_args)
                log_cb("info", f"📱 Emulating Mobile: iPhone 13 ({device_config['user_agent'][:40]}...)")
            else:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(viewport={"width":1280,"height":720})
            
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

                if run_id in active_runs and active_runs[run_id].get("cancelled"):
                    step_results.append({"seq":s,"status":"fail","note":"Test cancelled by user — remaining steps skipped","durationMs":0}); break

                t0 = time.time()
                log_cb("step", f"Step {s}/{total}: {action} {desc}")
                try:
                    if action in ("navigate","go to"):
                        url = target if target.startswith("http") else base_url.rstrip("/")+"/"+target.lstrip("/")
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
                            status = "adapted" if len(nav_attempts) > 1 else "pass"
                            step_results.append({"seq":s,"status":status,"note":f"Navigated to {url}","durationMs":int((time.time()-t0)*1000)})
                            if status == "adapted":
                                healed_steps.append({"index": i, "new": url})
                                adapted_count += 1
                            screenshot = capture_screenshot(f"step-{s}")
                            if screenshot: step_results[-1]["screenshot"] = screenshot
                            log_cb("ok" if status=="pass" else "adapted", f"Navigated to {url}")
                            
                            # --- PRE-SCAN VALIDATION ---
                            log_cb("info", "Running Pre-scan validation...")
                            critical_elements = [step.get("target") for step in steps if step.get("action") in ("click", "fill", "verify") and step.get("target")]
                            missing = []
                            for sel in set(critical_elements):
                                if sel and not sel.startswith("text="):
                                    try:
                                        if not page.query_selector(sel):
                                            missing.append(sel)
                                    except: pass
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
                        try:
                            page.click(target, timeout=5000)
                            clicked = True
                        except Exception:
                            log_cb("info", f"Ollama CLI Output: Analyzing page for element '{desc}'...")
                            try:
                                dom = get_compact_dom(page)
                                prompt = (
                                    f"You are an expert QA Automation AI. You are controlling a browser via Playwright.\n"
                                    f"URL: {page.url}\n"
                                    f"ACTION: Click on '{desc}'\n"
                                    f"FAILED SELECTOR: {target}\n\n"
                                    f"COMPACT DOM:\n{dom}\n\n"
                                    "Analyze the DOM and find the best alternative selector to click the element.\n"
                                    "Think step-by-step. First explain your reasoning, then provide the selector.\n"
                                    "Respond with:\n"
                                    "REASONING: <your analysis>\n"
                                    "SELECTOR: <playwright selector>"
                                )
                                resp = call_ai(prompt, timeout=120)
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
                                    log_cb("error", f"Ollama CLI Output: AI request failed with status {r.status_code}")
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
                            status = "adapted" if ai_used else "pass"
                            step_results.append({"seq":s,"status":status,"note":f"Clicked {target}","durationMs":int((time.time()-t0)*1000)})
                            if status == "adapted":
                                healed_steps.append({"index": i, "new": target})
                                adapted_count += 1
                            screenshot = capture_screenshot(f"step-{s}")
                            if screenshot: step_results[-1]["screenshot"] = screenshot
                            log_cb("ok" if status=="pass" else "adapted", f"Clicked {target}")
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
                        try:
                            page.fill(target, val, timeout=5000)
                            filled = True
                        except Exception:
                            log_cb("info", f"Ollama CLI Output: Analyzing page for input '{desc}'...")
                            try:
                                dom = get_compact_dom(page)
                                prompt = (
                                    f"You are an expert QA Automation AI.\n"
                                    f"URL: {page.url}\n"
                                    f"TASK: Fill '{val}' into '{desc}'\n"
                                    f"FAILED SELECTOR: {target}\n\n"
                                    f"COMPACT DOM:\n{dom}\n\n"
                                    "Analyze the DOM and find the best alternative selector for the input field.\n"
                                    "Respond with:\n"
                                    "REASONING: <analysis>\n"
                                    "SELECTOR: <selector>"
                                )
                                resp = call_ai(prompt, timeout=120)
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
                                    log_cb("error", f"Ollama CLI Output: AI request failed with status {r.status_code}")
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
                            status = "adapted" if ai_used else "pass"
                            step_results.append({"seq":s,"status":status,"note":f"Filled {target}","durationMs":int((time.time()-t0)*1000)})
                            if status == "adapted":
                                healed_steps.append({"index": i, "new": target})
                                adapted_count += 1
                            screenshot = capture_screenshot(f"step-{s}")
                            if screenshot: step_results[-1]["screenshot"] = screenshot
                            log_cb("ok" if status=="pass" else "adapted", f"Filled {target}")
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

                    elif action in ("verify","check","verifyElement"):
                        try:
                            page.wait_for_selector(target if target and not target.startswith("text=") else f"text={target or desc}", timeout=5000)
                            step_results.append({"seq":s,"status":"pass","note":f"Found: {target or desc}","durationMs":int((time.time()-t0)*1000)})
                            screenshot = capture_screenshot(f"step-{s}")
                            if screenshot: step_results[-1]["screenshot"] = screenshot
                        except Exception:
                            # AI-assisted verification fallback
                            log_cb("info", f"Verification failed for '{target}', asking AI...")
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
                                ai_txt = call_ai(prompt, timeout=30)
                                if ai_txt:
                                    if ai_txt.upper().startswith("FOUND"):
                                        step_results.append({"seq":s,"status":"adapted","note":f"AI verified: {ai_txt}","durationMs":int((time.time()-t0)*1000)})
                                        adapted_count += 1
                                        screenshot = capture_screenshot(f"step-{s}")
                                        if screenshot: step_results[-1]["screenshot"] = screenshot
                                        log_cb("adapted", f"AI verified presence of '{desc}'")
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
                            ai = call_ai(prompt, timeout=120)
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
                            step_results.append({"seq":s,"status":"adapted","note":ai,"durationMs":int((time.time()-t0)*1000)})
                            adapted_count += 1
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
    
    # If the test passed functionally, but had JS errors or Network failures (4xx/5xx), mark it as 'adapted' (pass with warning)
    if final_status == "pass":
        js_errors = [l.get("text") for l in c_logs if l.get("type") == "error"]
        # Refine network error detection: ignore non-critical asset failures like favicons or analytics
        net_errors = []
        for l in n_logs:
            status = l.get("status", 0)
            url = l.get("url", "").lower()
            if status >= 400:
                # Ignore non-critical resources
                if any(k in url for k in ("favicon", "google-analytics", "doubleclick", "pixel", "/ads/")):
                    # Still track these, but label as minor
                    net_errors.append(f"Minor: {l.get('method')} {status} {l.get('url')}")
                    continue
                net_errors.append(f"Critical: {l.get('method')} {status} {l.get('url')}")
        
        if js_errors or net_errors:
            final_status = "adapted"
            tech_fail_reason = f"Tech Warning: {len(js_errors)} JS error(s) and {len(net_errors)} network failure(s) detected (Functional steps passed)."
            log_cb("warning", tech_fail_reason)
            for err in js_errors:
                log_cb("info", f"  - JS Error: {err[:100]}")
            for err in net_errors:
                log_cb("info", f"  - Network: {err}")

    logs_list = active_runs[run_id]["logs"]
    process_log = "\n".join(l.get("message","") for l in logs_list)
    if tech_fail_reason:
        process_log += f"\n\n[CRITICAL] {tech_fail_reason}"
        
    tool_calls = sum(1 for l in logs_list if l.get("level") in ("info","step","ok","error"))
    
    # Update summary to reflect tech failure
    current_summary = result["summary"]
    if tech_fail_reason:
        current_summary = f"FAIL: {tech_fail_reason} | {current_summary}"

    report_md = build_report_markdown(
        tc.get("name","Untitled"), result.get("steps",[]),
        result["passed"], result["adapted"], result["failed"], result["blocked"],
        dur, logs_list, now_iso(), mode, device
    )
    result_data = {
        "_id": run_id, "id": run_id,
        "projectId": tc.get("projectId",""),
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
            with db_lock:
                projects_table.update(up, record_id_cond(pid))
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
    with db_lock:
        test_cases_table.update(request.json, record_id_cond(tcid))
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
    with db_lock:
        removed = test_cases_table.remove((q.id == tcid) | (q._id == tcid))
    with db_lock:
        matches_after = test_cases_table.search((q.id == tcid) | (q._id == tcid))
    _invalidate_table_cache("test_cases")
    if not matches_before:
        return err("Not found", 404)
    return ok({"status": "deleted", "removed_before": matches_before, "removed_count": len(matches_before)})

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


def _discovery_worker(pid, base_url, sid):
    def log_cb(level, msg):
        emit_stream(sid, "progress", json.dumps({"message": msg}))

    def selector_exists(page, target):
        if not target or target == "$BASE_URL" or target.startswith("text="):
            return True
        if target.startswith("css="):
            target = target[4:]
        if target.startswith("xpath="):
            expr = target[6:]
            try:
                return page.evaluate(
                    "function(expr) { const res = document.evaluate(expr, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null); return !!res.singleNodeValue; }",
                    expr
                )
            except Exception:
                return False
        try:
            return page.evaluate("function(selector) { return !!document.querySelector(selector); }", target)
        except Exception as exc:
            print(f"[DEBUG] selector_exists evaluation failed for target={target}: {exc}")
            return False

    browser = None
    try:
        for _ in range(50):
            if run_streams.get(sid): break
            time.sleep(0.1)
        
        emit_stream(sid, "progress", json.dumps({"message": "Launching browser..."}))
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width":1280,"height":720})
            emit_stream(sid, "progress", json.dumps({"message": f"Navigating to {base_url}..."}))
            page.goto(base_url, wait_until="load", timeout=60000)
            page.wait_for_timeout(3000) # Ensure content settles
            emit_stream(sid, "progress", json.dumps({"message": "Analyzing page DOM structure..."}))
            dom = get_compact_dom(page)
            page_title = page.title()

            cfg = get_config()
            emit_stream(sid, "progress", json.dumps({"message": "Generating test cases with AI (Attempt 1/3)..."}))
            
            prompt = (
                f"You are a Senior eCommerce QA Automation Architect. Generate a broad, functional test suite for the live site: {base_url}\n"
                f"PAGE TITLE: {page_title}\n\n"
                "Use the following functional coverage checklist as a reference. Prioritize user-facing flows, authentication, checkout, search, cart, order lifecycle, and security.\n\n"
                "REFERENCE CHECKLIST:\n"
                "1. Registration / Sign-Up\n"
                "2. Login & Authentication\n"
                "3. Account Recovery & Security\n"
                "4. User Profile & Dashboard\n"
                "5. Home Page & Navigation\n"
                "6. Search\n"
                "7. Product Listing Page (PLP)\n"
                "8. Product Detail Page (PDP)\n"
                "9. Cart / Mini Cart\n"
                "10. Shopping Cart Page\n"
                "11. Checkout & Shipping\n"
                "12. Payment Gateway\n"
                "13. Order Confirmation & Post Order\n"
                "14. Inventory & Stock Management\n"
                "15. Promotions, Coupons & Loyalty\n"
                "16. Session & State Management\n"
                "17. Notifications System\n"
                "18. Admin Panel / Backend Ops (if visible)\n"
                "19. Security Testing (XSS, IDOR, SQLi, rate limiting, price tampering)\n"
                "20. Data Integrity & System Consistency\n"
                "21. Performance & Load Testing behaviors\n\n"
                "INSTRUCTIONS:\n"
                "1. Generate up to 25 test cases, covering as many of the above areas as possible based on the site and DOM structure.\n"
                "2. If a flow is not present, skip it gracefully and focus on visible user journeys.\n"
                "3. Use actual DOM selectors from the provided DOM snippet when available. Prefer ID, class, or data-* selectors; otherwise use 'text=' locators.\n"
                "4. Do not hallucinate unknown fields, forms, or backend details. Use only what can be inferred from the page DOM and URL.\n"
                "5. Each test case must be valid JSON with keys: name, category, section, steps. Each step must include action, target, description, and verify, and optionally value.\n"
                "6. Focus on functional validation rather than implementation details. Validate messages, element states, navigation, and secure failure behavior.\n\n"
                f"DOM ELEMENTS: {dom}"
            )

            raw_ai = None
            for attempt in range(3):
                try:
                    raw_ai = call_ai(prompt, cfg, timeout=300)
                    if raw_ai:
                        break
                    else:
                        log_cb("warning", f"AI Discovery attempt {attempt+1} failed: no response")
                        time.sleep(5)
                except Exception as e:
                    log_cb("warning", f"AI Discovery attempt {attempt+1} failed: {e}")
                    time.sleep(5)

            if not raw_ai:
                emit_stream(sid, "error", json.dumps({"message": "Failed to generate tests after 3 attempts"}))
                return

            # Parsing
            if "```json" in raw_ai: raw_ai = raw_ai.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_ai: raw_ai = raw_ai.split("```")[1].split("```")[0].strip()
            
            generated = None
            try:
                generated = json.loads(raw_ai)
            except json.JSONDecodeError:
                raw_ai = re.sub(r',\s*}', '}', raw_ai)
                raw_ai = re.sub(r',\s*]', ']', raw_ai)
                try:
                    generated = json.loads(raw_ai)
                except json.JSONDecodeError:
                    generated = None

            if generated is None:
                # Fallback: search for a JSON array body inside the AI response
                match = re.search(r"(\[\s*{[\s\S]*\})\s*\]", raw_ai)
                if match:
                    try:
                        generated = json.loads(match.group(0))
                    except Exception:
                        generated = None

            if generated is None:
                match = re.search(r"(\[.*\])", raw_ai, re.DOTALL)
                if match:
                    try:
                        generated = json.loads(match.group(1))
                    except Exception:
                        generated = None

            if generated is None:
                print(f"[DEBUG] AI raw output for project {pid}:\n{raw_ai[:4000]}")
                emit_stream(sid, "error", json.dumps({"message": "AI output could not be parsed as JSON."}))
                return

            if not isinstance(generated, list): generated = [generated]

            # Selector Validation
            emit_stream(sid, "progress", json.dumps({"message": "Validating selectors..."}))
            validated_tcs = []
            for tc in generated:
                valid_steps = []
                for step in tc.get("steps", []):
                    target = step.get("target")
                    if target and target != "$BASE_URL" and not target.startswith("text="):
                        if not selector_exists(page, target):
                            log_cb("warning", f"Invalid selector found and skipped: {target}")
                            continue
                    valid_steps.append(step)
                if valid_steps:
                    tc["steps"] = valid_steps
                    validated_tcs.append(tc)

            generated = validated_tcs
            if not generated:
                emit_stream(sid, "error", json.dumps({"message": "AI generated no valid test cases after selector validation."}))
                browser.close()
                return

            browser.close()
        all_tcs = safe_all(test_cases_table)
        count = len([t for t in all_tcs if t.get("projectId")==pid])

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
            emit_stream(sid, "error", json.dumps({"message": "AI generated no valid test cases after selector validation."}))
            return

        emit_stream(sid, "progress", json.dumps({"message": f"Saving {len(to_insert)} test cases..."}))
        safe_insert_multiple(test_cases_table, to_insert)
        emit_stream(sid, "complete", json.dumps({"created": len(to_insert)}))

    except Exception as e:
        print(f"[ERROR] AI Discovery failed: {e}")
        import traceback
        traceback.print_exc()
        if browser:
            try:
                browser.close()
            except Exception as close_err:
                print(f"[DEBUG] Browser close error: {close_err}")
        emit_stream(sid, "error", json.dumps({"message": str(e)}))

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
    
    def sequential_worker():
        queue_obj = project_queues.get(pid)
        for i, (tc_id, rid) in enumerate(run_queue):
            if rid in active_runs and active_runs[rid].get("cancelled"): continue
            if queue_obj: 
                queue_obj["currentTestCase"] = next((t.get("name") for t in tcs if (t.get("id") or t.get("_id")) == tc_id), "Test")
                save_active_state()
            # Emit queue_test_started so frontend can attach terminal
            emit_stream(pid, "queue_test_started", json.dumps({"runId": rid, "testCaseName": queue_obj.get("currentTestCase", "") if queue_obj else ""}))
            run_test_thread(tc_id, rid, mode, device)
            if queue_obj:
                res = safe_all(results_table)
                last_res = next((r for r in reversed(res) if r.get("id") == rid), None)
                last_status = last_res.get("status", "pass") if last_res else "pass"
                queue_obj["completed"].append({"id": rid, "status": last_status})
                emit_stream(pid, "queue_progress", json.dumps({"completed": len(queue_obj["completed"]), "total": queue_obj.get("total", 0), "currentTestCase": queue_obj.get("currentTestCase", "")}))
                save_active_state()
        
        if queue_obj:
            queue_obj["status"] = "completed"
            queue_obj["currentTestCase"] = ""
            save_active_state(force=True)
            emit_stream(pid, "queue_completed", json.dumps({"completed": queue_obj.get("completed", [])}))
    
    t = threading.Thread(target=sequential_worker, daemon=True)
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

    def sequential_worker():
        queue_obj = project_queues.get(pid)
        for i, (tc_id, rid) in enumerate(run_queue):
            if rid in active_runs and active_runs[rid].get("cancelled"): continue
            if queue_obj: 
                queue_obj["currentTestCase"] = next((t.get("name") for t in tcs if (t.get("id") or t.get("_id")) == tc_id), "Test")
                save_active_state()
            # Emit queue_test_started so frontend can attach terminal
            emit_stream(pid, "queue_test_started", json.dumps({"runId": rid, "testCaseName": queue_obj.get("currentTestCase", "") if queue_obj else ""}))
            run_test_thread(tc_id, rid, mode, device)
            if queue_obj:
                res = safe_all(results_table)
                last_res = next((r for r in reversed(res) if r.get("id") == rid), None)
                last_status = last_res.get("status", "pass") if last_res else "pass"
                queue_obj["completed"].append({"id": rid, "status": last_status})
                emit_stream(pid, "queue_progress", json.dumps({"completed": len(queue_obj["completed"]), "total": queue_obj.get("total", 0), "currentTestCase": queue_obj.get("currentTestCase", "")}))
                save_active_state()
        
        if queue_obj:
            queue_obj["status"] = "completed"
            queue_obj["currentTestCase"] = ""
            save_active_state(force=True)
            emit_stream(pid, "queue_completed", json.dumps({"completed": queue_obj.get("completed", [])}))

    threading.Thread(target=sequential_worker, daemon=True).start()
    
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
    fp=TEST_PLANS_DIR/fn
    if not fp.exists(): return err("Plan not found",404)
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
            if rid in run_streams and qid in run_streams[rid]: del run_streams[rid][qid]
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
    safe_cfg = {k:v for k,v in cfg.items() if k!="anthropic_api_key" or not v}
    if safe_cfg.get("cloud_api_key"):
        key = safe_cfg["cloud_api_key"]
        safe_cfg["cloud_api_key"] = key[:6] + "..." + key[-4:] if len(key) > 10 else "***"
    return ok(safe_cfg)

@app.route("/api/config", methods=["POST"])
@require_json
def api_save_config():
    data=request.json; current=get_config()
    for k in ("ai_provider","ollama_base_url","ollama_model","anthropic_api_key","cloud_base_url","cloud_api_key","cloud_model"):
        if k in data: current[k]=data[k]
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
    if API_KEY:
        print("  API_KEY: enabled (localhost requests exempt)")
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
