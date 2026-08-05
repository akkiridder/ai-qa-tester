import json
from pathlib import Path
from collections import defaultdict

db_path = Path('data/database.json')
with open(db_path) as f:
    db = json.load(f)

test_cases = db.get('test_cases', {})
ai_tests = [tc for tc in test_cases.values() if tc.get('source') == 'ai-discovery']

print(f'Total AI-Discovery Test Cases in entire DB: {len(ai_tests)}')
print()

# Group by project
by_project = defaultdict(list)
projects = db.get('projects', {})

for tc in ai_tests:
    pid = tc.get('projectId', 'Unknown')
    by_project[pid].append(tc)

print('AI Tests by Project:')
for pid in sorted(by_project.keys()):
    tests = by_project[pid]
    proj_name = 'Unknown'
    if pid in projects:
        proj_name = projects[pid].get('name', 'Unknown')
    print(f'  Project {pid} ({proj_name}): {len(tests)} tests')
    if len(tests) <= 30:
        for tc in tests[:10]:
            cat = tc.get('category', 'N/A')
            name = tc.get('name', 'N/A')
            print(f'    [{cat}] {name}')
        if len(tests) > 10:
            print(f'    ... and {len(tests)-10} more')
