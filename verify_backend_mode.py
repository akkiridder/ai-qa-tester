
import requests
import time
import json

base_url = "http://localhost:5000/api"
tc_id = "307fdc814c454a7a" # TC001 from user screenshots

def test():
    print(f"Testing MOBILE run for {tc_id}...")
    res = requests.post(f"{base_url}/run/{tc_id}", json={"mode": "mobile"})
    run_id = res.json()["data"]["runId"]
    print(f"Started run: {run_id}")
    
    # Wait for completion
    while True:
        res = requests.get(f"{base_url}/run/status/{run_id}")
        data = res.json()["data"]
        status = data.get("status")
        print(f"Status: {status}")
        if status in ["completed", "fail", "error"]:
            break
        time.sleep(2)
    
    print("\nRun finished. Checking database record...")
    # Check the result object returned by the API
    result = data.get("result", {})
    print(f"Result object 'mode': {result.get('mode')}")
    
    # Check direct DB
    from tinydb import TinyDB, Query
    db = TinyDB("data/database.json")
    results_table = db.table("results")
    r = results_table.get(Query().id == run_id)
    if r:
        print(f"DB record 'mode': {r.get('mode')}")
    else:
        print("DB record NOT FOUND!")

if __name__ == "__main__":
    test()
