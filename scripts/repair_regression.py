import json
from pathlib import Path

db_path = Path(__file__).parent / "data" / "database.json"
if not db_path.exists():
    print(f"DB not found at {db_path}")
    exit()

with open(db_path, 'r', encoding='utf-8') as f:
    db = json.load(f)

if 'test_cases' in db:
    count = 0
    for tcid, tc in db['test_cases'].items():
        if 'isRegression' not in tc or tc['isRegression'] is not True:
            tc['isRegression'] = True
            count += 1
    
    print(f"Updated {count} test cases with isRegression=True")
    
    with open(db_path, 'w', encoding='utf-8') as f:
        json.dump(db, f, indent=2)
    print("Database saved.")
else:
    print("No test_cases table found.")
