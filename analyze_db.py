import json
from pathlib import Path

db_path = Path(r"C:\Users\AkshayKumar Dudhwala\AI Agent QA\data\database.json")
with open(db_path, 'r', encoding='utf-8') as f:
    db = json.load(f)

for table_name, data in db.items():
    print(f"Table: {table_name}, Count: {len(data)}")
    if data:
        sizes = [(k, len(json.dumps(v))) for k, v in data.items()]
        sizes.sort(key=lambda x: x[1], reverse=True)
        print(f"  Largest items in {table_name}:")
        for k, s in sizes[:5]:
            print(f"    {k}: {s} bytes")

