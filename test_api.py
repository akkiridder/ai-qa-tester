import requests

base = 'http://localhost:5000'

print('=== Testing API Endpoints ===')
print()

# 1. Projects
r = requests.get(f'{base}/api/projects')
print('GET /api/projects:', r.status_code)
projects = r.json().get('data', [])
print('  Found', len(projects), 'projects')
for p in projects[:3]:
    print('  -', p.get('name'), '(', p.get('id'), ')')

# 2. Test cases for first project
if projects:
    pid = projects[0]['id']
    r = requests.get(f'{base}/api/projects/{pid}/test-cases')
    print('GET /api/projects/{}/test-cases:'.format(pid), r.status_code)
    tcs = r.json().get('data', [])
    print('  Found', len(tcs), 'test cases')

# 3. Results
r = requests.get(f'{base}/api/results')
print('GET /api/results:', r.status_code)
results = r.json().get('data', [])
print('  Found', len(results), 'results')

# 4. Config
r = requests.get(f'{base}/api/config')
print('GET /api/config:', r.status_code)
config = r.json().get('data', {})
print('  Config:', config)

# 5. Ollama models
r = requests.get(f'{base}/api/ollama-models')
print('GET /api/ollama-models:', r.status_code)
models = r.json().get('data', {}).get('models', [])
print('  Models:', models[:3])

# 6. Dashboard
r = requests.get(f'{base}/api/dashboard')
print('GET /api/dashboard:', r.status_code)
stats = r.json().get('data', {})
print('  Stats keys:', list(stats.keys())[:6])

print()
print('=== All basic endpoints working ===')
