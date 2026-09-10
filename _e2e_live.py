import json, time, urllib.request
BASE = "http://127.0.0.1:5000"

TC_ID = "4e4d95ed63a3409e"  # TC011 Page has valid title (example.com)

def post_json(path, payload):
    req = urllib.request.Request(BASE+path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def get(path):
    with urllib.request.urlopen(BASE+path, timeout=30) as r:
        return json.loads(r.read().decode())

# 1. Start the run
print("Starting run for", TC_ID)
resp = post_json(f"/api/run/{TC_ID}", {"mode":"standard","device":"desktop"})
print("run response:", resp.get("data") or resp)
run_id = resp["data"]["runId"]
print("runId:", run_id)

# 2. Follow the run stream (SSE) to see real AI output
print("\n=== SSE STREAM (live) ===")
stream_lines = []
try:
    req = urllib.request.Request(BASE + f"/api/run/stream/{run_id}")
    with urllib.request.urlopen(req, timeout=180) as r:
        buf = ""
        for raw in r:
            txt = raw.decode("utf-8", errors="replace")
            buf += txt
            while "\n\n" in buf:
                evt, buf = buf.split("\n\n", 1)
                eline = [l for l in evt.splitlines() if l.startswith("data:")]
                if eline:
                    data = eline[0][5:].strip()
                    stream_lines.append(data)
                    try:
                        j = json.loads(data)
                        t = j.get("type")
                        if t in ("status","step","ai","log","progress","result","error"):
                            print(f"[{t}]", str(j)[:200])
                        elif t == "heartbeat":
                            pass
                        else:
                            print(f"[{t}]", str(j)[:200])
                    except Exception:
                        print("[raw]", data[:200])
except Exception as e:
    print("stream error:", e)

# 3. Check run status
print("\n=== RUN STATUS ===")
st = get(f"/api/run/status/{run_id}")
print("status:", json.dumps(st.get("data"), indent=2)[:600])

# 4. Fetch the result
print("\n=== RESULT ===")
try:
    res = get(f"/api/run/result/{run_id}")
    rd = res.get("data") or res
    print(json.dumps(rd, indent=2)[:1200])
except Exception as e:
    print("result fetch error:", e)

# 5. Check result in results list & screenshot
time.sleep(1)
try:
    res = get(f"/api/results?limit=1000")
    alldata = res.get("data", [])
    found = [r for r in alldata if r.get("id")==run_id or r.get("_id")==run_id]
    if found:
        r = found[0]
        print("\n=== RESULT FROM LIST ===")
        print("status:", r.get("status"), "| projectName:", r.get("projectName"), "| testCaseName:", r.get("testCaseName"))
        print("mode:", r.get("mode"), "| device:", r.get("device"))
        scr = r.get("screenshots") or []
        print("screenshots in list:", len(scr))
except Exception as e:
    print("list fetch error:", e)
