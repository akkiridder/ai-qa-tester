import json, urllib.request
BASE = "http://127.0.0.1:5000"

def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        return "ERR:" + str(e), None

def post(path, payload=None):
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(BASE + path, data=data, headers={"Content-Type":"application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None

results = []
def check(name, cond, detail=""):
    results.append((name, cond, detail))
    print(("PASS" if cond else "FAIL") + "  " + name + (("  | " + detail) if detail else ""))

# --- config ---
st, cfg = get("/api/config")
data = cfg.get("data", {}) if cfg else {}
check("config endpoint 200", st == 200, str(st))
check("config ai_provider present", "ai_provider" in data, str(data.get("ai_provider")))
check("config cloud_api_key present", "cloud_api_key" in data)
check("config cloud_base_url nvidia", "nvidia.com" in data.get("cloud_base_url",""), data.get("cloud_base_url",""))
check("config ollama_model qwen", data.get("ollama_model"), str(data.get("ollama_model")))

# --- ollama status & models ---
st, s = get("/api/ollama-status")
sd = s.get("data", {}) if s else {}
check("ollama-status 200", st == 200)
check("ollama connected", sd.get("connected") is True, str(sd))
st, m = get("/api/ollama-models")
md = m.get("data", {}) if m else {}
models = md.get("models", []) if isinstance(md, dict) else []
check("ollama-models 200", st == 200)
check("ollama models non-empty", len(models) > 0, str(models))
check("qwen present in models", any("qwen" in str(x).lower() for x in models))

# --- cloud models (real key) ---
st, cm = post("/api/cloud-models")
check("cloud-models returns list", st in (200, 201) and cm and isinstance(cm.get("data"), list), str(st) + " " + str(cm)[:200])

# --- dashboard ---
st, db = get("/api/dashboard")
dd = db.get("data", {}) if db else {}
check("dashboard 200", st == 200)
check("dashboard total_projects > 0", dd.get("total_projects",0) > 0, str(dd.get("total_projects")))
check("dashboard pass_rate is number", isinstance(dd.get("pass_rate"), (int,float)))

# --- projects list ---
st, pl = get("/api/projects")
pld = pl.get("data", []) if pl else []
check("projects 200", st == 200)
check("projects list non-empty", len(pld) > 0, f"{len(pld)} projects")
check("project has testCaseCount", all("testCaseCount" in p for p in pld))

# pick a project with data
core = [p for p in pld if p.get("testCaseCount",0) > 0]
if core:
    pid = core[0].get("id") or core[0].get("_id")
    check("project has id", bool(pid), str(pid))
    # project detail
    st, pd = get(f"/api/projects/{pid}")
    check("project detail 200", st == 200)
    # test cases for project
    st, tcs = get(f"/api/projects/{pid}/test-cases")
    tcd = tcs.get("data", []) if tcs else []
    check("project test-cases 200", st == 200, f"{len(tcd)} tcs")
    check("test cases non-empty", len(tcd) > 0)
    if tcd:
        check("test case has steps/name", bool(tcd[0].get("name")))
        tcid = tcd[0].get("id") or tcd[0].get("_id")
        st, tcdet = get(f"/api/test-cases/{tcid}")
        check("test-case detail 200", st == 200)
        check("test-case export 200", get(f"/api/test-cases/{tcid}/export")[0] == 200)
    # project results
    st, pr = get(f"/api/projects/{pid}/results")
    prd = pr.get("data", []) if pr else []
    check("project results 200", st == 200, f"{len(prd)} results")
    # project dashboard
    st, pdd = get(f"/api/projects/{pid}/dashboard")
    check("project dashboard 200", st == 200)
    # analytics
    st, ana = get(f"/api/projects/{pid}/analytics")
    check("project analytics 200", st == 200)

# --- results list (slim/enriched) ---
st, rs = get("/api/results")
rsd = rs.get("data", []) if rs else []
check("results 200", st == 200)
check("results non-empty", len(rsd) > 0, f"{len(rsd)} results")
if rsd:
    with_name = [r for r in rsd if r.get("projectName")]
    check("results enriched with projectName", len(with_name) > 0, f"{len(with_name)}/{len(rsd)} with projectName")
    check("slim has testCaseName field", "testCaseName" in rsd[0])
    rid = rsd[0].get("id") or rsd[0].get("_id")
    # result detail - may be the /api/results/<rid> which returns raw
    st, rd = get(f"/api/results/{rid}")
    check("result detail 200", st == 200)

# --- test-results alias ---
st, tr = get("/api/test-results")
check("test-results 200", st == 200)

# --- test plans ---
st, tp = get("/api/test-plans")
check("test-plans 200", st == 200)

# --- active runs ---
st, ar = get("/api/run/active")
check("run/active 200", st == 200)

# --- queue active ---
st, qa = get("/api/queue/active")
check("queue/active 200", st == 200)

# --- root serves app ---
st, _ = get("/")
check("root 200 + HTML", st == 200)

print("\n=== SUMMARY ===")
passed = sum(1 for _,c,_ in results if c)
print(f"{passed}/{len(results)} checks passed")
fails = [n for n,c,_ in results if not c]
if fails:
    print("FAILED:", fails)
    import sys; sys.exit(1)
