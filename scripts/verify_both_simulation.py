
import requests
import time
import json

base_url = "http://localhost:5000/api"
tc_id = "307fdc814c454a7a" # TC001 from user screenshots

def test():
    print("--- Simulating Frontend BOTH Mode ---")
    print("1. Triggering Desktop run...")
    res1 = requests.post(f"{base_url}/run/{tc_id}", json={"mode": "standard"})
    run1 = res1.json()["data"]["runId"]
    print(f"   Started run: {run1}")
    
    print("2. Simulating 1 second frontend delay...")
    time.sleep(1)
    
    print("3. Triggering Mobile run...")
    res2 = requests.post(f"{base_url}/run/{tc_id}", json={"mode": "mobile"})
    run2 = res2.json()["data"]["runId"]
    print(f"   Started run: {run2}")
    
    # Wait for completion of run 1
    print(f"\nWaiting for Desktop run ({run1}) to complete...")
    while True:
        res = requests.get(f"{base_url}/run/status/{run1}")
        status = res.json()["data"].get("status")
        if status in ["completed", "fail", "error"]:
            break
        time.sleep(1)
        
    print(f"\nWaiting for Mobile run ({run2}) to complete...")
    while True:
        res = requests.get(f"{base_url}/run/status/{run2}")
        status = res.json()["data"].get("status")
        if status in ["completed", "fail", "error"]:
            break
        time.sleep(1)
    
    print("\n--- Both Runs Finished. Verifying DB ---")
    from tinydb import TinyDB, Query
    db = TinyDB("data/database.json")
    results_table = db.table("results")
    
    r1 = results_table.get(Query().id == run1)
    print(f"Run 1 (Expected Standard): DB Mode = {r1.get('mode') if r1 else 'NOT FOUND'}")
    
    r2 = results_table.get(Query().id == run2)
    print(f"Run 2 (Expected Mobile): DB Mode = {r2.get('mode') if r2 else 'NOT FOUND'}")

if __name__ == "__main__":
    test()
