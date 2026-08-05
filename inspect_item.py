import json
from pathlib import Path

db_path = Path(r"C:\Users\AkshayKumar Dudhwala\AI Agent QA\data\database.json")
with open(db_path, 'r', encoding='utf-8') as f:
    db = json.load(f)

item = db['results']['56']
print(f"Keys in item 56: {list(item.keys())}")
for k, v in item.items():
    v_size = len(json.dumps(v))
    if v_size > 1000:
        print(f"  Field '{k}' size: {v_size} bytes")
        if isinstance(v, list) and len(v) > 0:
            print(f"    List length: {len(v)}")
            print(f"    First element size: {len(json.dumps(v[0]))}")
