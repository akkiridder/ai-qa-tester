import requests
import json
import time

BASE_URL = "http://localhost:5000/api"

def verify_tech_logs():
    print("--- Verifying Priority 1: Network & Console Analysis ---")
    
    # 1. Get a project
    projects = requests.get(f"{BASE_URL}/projects").json()["data"]
    if not projects:
        print("No projects found to test with.")
        return
    pid = projects[0]["_id"]
    
    # 2. Create a test case that we know will have some activity
    # We'll use a public site and look for things that usually log or fail (like missing icons)
    tc_data = {
        "name": "TECH_LOG_VERIFICATION",
        "projectId": pid,
        "steps": [
            {"seq": 1, "action": "navigate", "target": "https://example.com", "description": "Open example.com"},
            {"seq": 2, "action": "click", "target": "h1", "description": "Click the header (should log something if we add a script)"}
        ]
    }
    
    # Actually, let's just run it and see what naturally occurs.
    # Most sites have some console noise or tracking pixel failures.
    
    print(f"Running test for project {pid}...")
    # Use standard mode to ensure full capture
    run_res = requests.post(f"{BASE_URL}/run/project/{pid}", json={"mode": "standard"}).json()
    
    if not run_res.get("success"):
        print(f"Failed to start run: {run_res}")
        return
    
    queue_id = run_res["data"]["queueId"]
    print(f"Started queue: {queue_id}. Waiting for completion...")
    
    # Poll for completion
    completed = False
    for _ in range(30):
        q_status = requests.get(f"{BASE_URL}/queue/{queue_id}").json()["data"]
        if q_status["status"] == "completed":
            completed = True
            break
        time.sleep(5)
        print(f"Status: {q_status['status']} ({len(q_status['completed'])}/{q_status['total']} done)")

    if not completed:
        print("Test run timed out.")
        return

    # 3. Check the most recent result
    results = requests.get(f"{BASE_URL}/results").json()["data"]
    latest = results[0]
    
    print("\n--- Verification Results ---")
    print(f"Result Status: {latest.get('status')}")
    print(f"Console Logs Captured: {len(latest.get('consoleLogs', []))}")
    print(f"Network Failures (4xx+) Captured: {len(latest.get('networkLogs', []))}")
    
    if "consoleLogs" in latest and "networkLogs" in latest:
        print("[PASS] SUCCESS: Data structures 'consoleLogs' and 'networkLogs' exist in database.")
        if len(latest["consoleLogs"]) > 0 or len(latest["networkLogs"]) > 0:
            print("[PASS] SUCCESS: Technical data was actually captured.")
        else:
            print("[WARN] WARNING: Captured lists are empty (might be expected for example.com).")
    else:
        print("[FAIL] FAILURE: Data structures missing from result.")

if __name__ == "__main__":
    verify_tech_logs()
