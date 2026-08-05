import requests
import json

base = 'http://localhost:5000'

# Check recent results
r = requests.get(f'{base}/api/results')
results = r.json().get('data', [])
print('Total results:', len(results))

# Find the recent ones
recent = sorted(results, key=lambda x: x.get('createdAt',''), reverse=True)[:5]
for res in recent:
    print('  ID:', res.get('id'), 'Name:', res.get('testCaseName'), 'Status:', res.get('status'), 'Created:', res.get('createdAt'))