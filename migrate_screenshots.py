import json
import base64
import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
DB_FILE = DATA_DIR / "database.json"

SCREENSHOTS_DIR.mkdir(exist_ok=True)

def migrate():
    if not DB_FILE.exists():
        print("DB file not found.")
        return

    print(f"Reading {DB_FILE}...")
    with open(DB_FILE, 'r', encoding='utf-8') as f:
        db = json.load(f)

    if 'results' not in db:
        print("No results table found.")
        return

    results = db['results']
    migrated_count = 0

    for rid, res in results.items():
        # Migrate steps
        if 'steps' in res:
            for s in res['steps']:
                if 'screenshot' in s and isinstance(s['screenshot'], str) and s['screenshot'].startswith('data:image'):
                    # Extract base64
                    try:
                        fmt, b64 = s['screenshot'].split(',', 1)
                        raw = base64.b64decode(b64)
                        seq = s.get('seq', 'unknown')
                        filename = f"{rid}_step-{seq}.png"
                        filepath = SCREENSHOTS_DIR / filename
                        filepath.write_bytes(raw)
                        
                        # Update path
                        s['screenshot'] = f"/api/screenshots/{filename}"
                        migrated_count += 1
                    except Exception as e:
                        print(f"Error migrating step screenshot in run {rid}: {e}")

        # Migrate screenshots dict
        if 'screenshots' in res:
            new_screenshots = {}
            for label, data in res['screenshots'].items():
                if isinstance(data, str) and data.startswith('data:image'):
                    try:
                        fmt, b64 = data.split(',', 1)
                        raw = base64.b64decode(b64)
                        filename = f"{rid}_{label}.png"
                        filepath = SCREENSHOTS_DIR / filename
                        filepath.write_bytes(raw)
                        
                        new_screenshots[label] = f"/api/screenshots/{filename}"
                        migrated_count += 1
                    except Exception as e:
                        print(f"Error migrating dict screenshot {label} in run {rid}: {e}")
                        new_screenshots[label] = data
                else:
                    new_screenshots[label] = data
            res['screenshots'] = new_screenshots

    print(f"Migrated {migrated_count} screenshots.")
    
    print(f"Saving updated DB to {DB_FILE}...")
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(db, f, indent=2)
    
    print("Done!")

if __name__ == "__main__":
    migrate()
